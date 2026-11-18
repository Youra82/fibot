"""CUDA-Engine: alle Parameter-Kombinationen einer fibot-Konfluenz-Config in einem Lauf.

Liefert je Kombination die rohen Fill-Ereignisse (Long und Short getrennt, mit
Ausstieg und Netto-R nach Kosten) sowie Monatssummen nach Trendfilter und
"eine Position zur Zeit" -- dieselbe Logik wie events_from_signals im Repo.
Coin, Zeiteinheit, feste Teile und Raster kommen aus der Live-Config.
"""

from dataclasses import dataclass
from itertools import product
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

from fibot.analysis.cuda_channels import _load_cupy, gpu_channel_series, install_cuda_channels
from fibot.strategy import confluence_logic as logic
from fibot.strategy import trend_filter
from fibot.strategy.risk_policy import ROUND_TRIP_COST_PCT

CACHE = ROOT / 'data' / 'cache'
CONFIGS = ROOT / 'src' / 'fibot' / 'strategy' / 'configs'
NO_AGE = 9.0   # Kurven-Kodierung fuer max_age_mult = None (keine Altersgrenze)

CHANNEL_KEYS = ('pivot_k', 'window', 'max_break_frac')
PLAN_ORDER = ('fib_lo', 'fib_hi', 'fib_sl', 'zone_tol_atr', 'sl_buf_atr',
              'min_rr', 'max_age_mult', 'b_near_upper_atr')
PARAMS = list(CHANNEL_KEYS) + list(PLAN_ORDER)
FIXED_KEYS = ('min_upper_touches', 'min_width_atr', 'touch_atr', 'tp_mode')
BASE_GRID = {
    'pivot_k': (3, 5), 'window': (100, 150), 'max_break_frac': (0.0, 0.03),
    'fib_lo': (0.382, 0.5), 'fib_hi': (0.618, 0.705), 'fib_sl': (0.786, 0.886),
    'zone_tol_atr': (0.1, 0.15, 0.2, 0.25, 0.3, 0.35),
    'sl_buf_atr': (0.1, 0.15, 0.2, 0.25, 0.35, 0.5),
    'min_rr': (1.3, 1.5, 1.8, 2.2, 2.8),
    'max_age_mult': (1.5, 2.0, 3.0),
    'b_near_upper_atr': (0.5, 1.0),
}


def enc(value) -> float:
    return NO_AGE if value is None else float(value)


@dataclass
class Setup:
    coin: str
    tf: str
    live: dict
    fixed: dict
    grid: dict

    @property
    def symbol(self):
        return f'{self.coin}/USDT:USDT'

    @property
    def name(self):
        return f'{self.coin}_{self.tf}'


def setup_from_config(coin: str, tf: str) -> Setup:
    cfg = json.loads((CONFIGS / f'config_{coin}USDTUSDT_{tf}_fib.json').read_text(encoding='utf-8'))
    s = cfg['strategy']
    live = {}
    for key in PARAMS:
        v = s.get(key)
        live[key] = None if v is None else round(float(v), 6) if isinstance(v, float) else v
    grid = {}
    for key, base in BASE_GRID.items():
        values = {enc(v) for v in base} | {enc(live[key])}
        grid[key] = tuple(sorted(values))
    fixed = {key: s[key] for key in FIXED_KEYS}
    return Setup(coin, tf, live, fixed, grid)


def config_for(setup: Setup, params: dict) -> dict:
    p = {k: (None if k == 'max_age_mult' and enc(v) == NO_AGE else v) for k, v in params.items()}
    return {'market': {'symbol': setup.symbol, 'timeframe': setup.tf},
            'strategy': {'type': 'confluence', **setup.fixed, **p, 'candle_limit': 600,
                         'risk_policy_version': 2},
            'risk': {'leverage': 10, 'risk_per_entry_pct': 1.0, 'margin_mode': 'isolated'}}


def read_cache(coin: str, timeframe: str) -> pd.DataFrame:
    path = CACHE / f"{coin}-USDT-USDT_{timeframe}.csv"
    df = pd.read_csv(path, index_col='timestamp', parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[~df.index.duplicated(keep='last')].sort_index()
    saved = pd.Timestamp(path.stat().st_mtime, unit='s', tz='UTC')
    return df[df.index + pd.Timedelta(timeframe) <= saved]


def prev_index(positions: np.ndarray, n: int) -> np.ndarray:
    arr = np.full(n, -1, dtype=np.int64)
    arr[positions] = positions
    return np.maximum.accumulate(arr).astype(np.int32)


def sparse(values: np.ndarray, mode: str) -> np.ndarray:
    n = len(values)
    levels = int(math.floor(math.log2(n))) + 1
    table = np.empty((levels, n))
    table[0] = values
    op = np.maximum if mode == 'max' else np.minimum
    for lev in range(1, levels):
        step = 1 << (lev - 1)
        table[lev] = table[lev - 1]
        table[lev, :n - step] = op(table[lev - 1, :n - step], table[lev - 1, step:])
    return table


def trend_masks(df: pd.DataFrame, setup: Setup) -> tuple[np.ndarray, np.ndarray]:
    cfg = trend_filter.settings()
    if not cfg['enabled']:
        ones = np.ones(len(df), dtype=np.uint8)
        return ones, ones
    htf = trend_filter.htf_trend(df[['close']], setup.tf, cfg)
    daily = trend_filter.daily_trend(read_cache(setup.coin, '1d'), cfg)

    def at(series):
        pos = series.index.searchsorted(df.index, side='right') - 1
        out = np.full(len(df), np.nan)
        ok = pos >= 0
        out[ok] = series.to_numpy()[pos[ok]]
        return out
    h, d = at(htf), at(daily)
    return (((h == 1.0) & (d == 1.0)).astype(np.uint8),
            ((h == 0.0) & (d == 0.0)).astype(np.uint8))


class Engine:
    def __init__(self, setup: Setup, df: pd.DataFrame, month_of_bar: np.ndarray, nmonth: int, log=print):
        self.cp = cp = _load_cupy()
        install_cuda_channels()
        self.setup, self.df, self.n, self.log = setup, df, len(df), log
        grid = setup.grid
        self.ch_keys = list(product(*(grid[k] for k in CHANNEL_KEYS)))
        plan_vals = list(product(*(grid[k] for k in PLAN_ORDER)))
        rows = []
        for ch_i, ch in enumerate(self.ch_keys):
            for pl in plan_vals:
                rows.append((ch_i, *ch, *pl))
        arr = np.array(rows, dtype=np.float64)
        self.ncombo = len(arr)
        self.cch = arr[:, 0].astype(np.int32)
        self.pv = arr[:, 1:]                                   # kodiert (None -> NO_AGE)
        self.ck = self.pv[:, 0].astype(np.int32)
        self.ckidx = np.searchsorted(np.array(sorted(set(self.ck))), self.ck).astype(np.int32)
        self.kvals = sorted(set(self.ck.tolist()))
        self.cwin = self.pv[:, 1].astype(np.int32)
        self.cpar = self.pv[:, 3:].copy()
        age = PLAN_ORDER.index('max_age_mult')
        self.cpar[self.cpar[:, age] == NO_AGE, age] = 0.0      # 0 = keine Altersgrenze im Kernel
        source = (HERE / 'plan_kernel.cu').read_text(encoding='utf-8')
        module = cp.RawModule(code=source, options=('--fmad=false',))
        self.k_plan, self.k_combine = module.get_function('plan'), module.get_function('combine')
        h, l, c = (df[x].to_numpy(dtype=float) for x in ('high', 'low', 'close'))
        self.dirs = {'L': (h, l, c), 'S': (-l, -h, -c)}
        self.events = {name: self._run_direction(*a, name) for name, a in self.dirs.items()}
        self.okL, self.okS = trend_masks(df, setup)
        self.month = month_of_bar.astype(np.int16)
        self.nmonth = nmonth
        self._combine()

    def _run_direction(self, H, L, C, name):
        cp, n, setup = self.cp, self.n, self.setup
        t0 = time.time()
        cols = {key: [] for key in ('valid', 'apos', 'slope', 'icpt', 'width')}
        atr = None
        live_enc = {k: enc(v) for k, v in setup.live.items()}
        for k, window, mbf in self.ch_keys:
            p = logic.strategy_params(config_for(setup, {**live_enc, 'pivot_k': int(k),
                                                         'window': int(window), 'max_break_frac': mbf}))
            res = gpu_channel_series(H, L, C, p)
            atr = res['atr']
            cols['valid'].append(res['valid'].astype(np.uint8))
            cols['apos'].append(res['a_pos'].astype(np.int64))
            for key in ('slope', 'icpt', 'width'):
                cols[key].append(res[key])
        prevL = np.stack([prev_index(logic._pivots(L, k, 'low'), n) for k in self.kvals])
        prevH = np.stack([prev_index(logic._pivots(H, k, 'high'), n) for k in self.kvals])
        lg = np.zeros(n + 1, dtype=np.int32)
        lg[2:] = np.floor(np.log2(np.arange(2, n + 1))).astype(np.int32)
        g = {key: cp.asarray(np.ascontiguousarray(value)) for key, value in {
            'H': H, 'L': L, 'C': C, 'atr': atr, 'prevL': prevL, 'prevH': prevH,
            **{key: np.stack(v) for key, v in cols.items()},
            'spH': sparse(H, 'max'), 'spC': sparse(C, 'min'), 'lg': lg,
            'cch': self.cch, 'ckidx': self.ckidx, 'ck': self.ck, 'cwin': self.cwin,
            'cpar': self.cpar}.items()}
        counts = cp.zeros(self.ncombo, dtype=cp.int32)
        offsets = cp.zeros(self.ncombo, dtype=cp.int64)
        tp_upper = np.int32(1 if setup.fixed['tp_mode'] == 'upper' else 0)

        def launch(write, ev_i, ev_x, ev_r):
            batch, threads = 4096, 64
            for base in range(0, self.ncombo, batch):
                blocks = (min(batch, self.ncombo - base) + threads - 1) // threads
                self.k_plan((blocks,), (threads,), (
                    g['H'], g['L'], g['C'], g['atr'], g['prevL'], g['prevH'],
                    g['valid'], g['apos'], g['slope'], g['icpt'], g['width'],
                    g['spH'], g['spC'], g['lg'], g['cch'], g['ckidx'], g['ck'], g['cwin'],
                    g['cpar'], np.float64(setup.fixed['touch_atr']), np.float64(ROUND_TRIP_COST_PCT),
                    tp_upper, np.int32(self.ncombo), np.int32(base), np.int32(n), np.int32(write),
                    counts, offsets, ev_i, ev_x, ev_r))
                cp.cuda.Stream.null.synchronize()
        dummy_i = cp.zeros(1, dtype=cp.int32)
        launch(0, dummy_i, dummy_i, cp.zeros(1, dtype=cp.float32))
        total = int(counts.sum())
        offsets[1:] = cp.cumsum(counts)[:-1]
        if total > 80_000_000:
            raise RuntimeError('zu viele Ereignisse fuer den Speicher')
        ev_i = cp.zeros(max(total, 1), dtype=cp.int32)
        ev_x = cp.zeros(max(total, 1), dtype=cp.int32)
        ev_r = cp.zeros(max(total, 1), dtype=cp.float32)
        launch(1, ev_i, ev_x, ev_r)
        self.log(f"[{setup.name} {name}] {total:,} Fills, {self.ncombo:,} Kombis, {time.time() - t0:.1f}s")
        del g
        cp.get_default_memory_pool().free_all_blocks()
        return {'counts': counts, 'offsets': offsets, 'i': ev_i, 'x': ev_x, 'r': ev_r}

    def aggregate(self, labels: np.ndarray, nlabels: int, labels_short: np.ndarray | None = None):
        """Netto-R- und Trade-Summen je Kombination und Label (Label der Einstiegskerze, -1 = ignorieren).
        Jede Kombination laeuft fuer sich mit Trendfilter und einer Position zur Zeit."""
        cp = self.cp
        shape = self.ncombo * nlabels
        msum = cp.zeros(shape, dtype=cp.float32)
        mcnt = cp.zeros(shape, dtype=cp.int32)
        mwin = cp.zeros(shape, dtype=cp.int32)
        eL, eS = self.events['L'], self.events['S']
        self.k_combine(((self.ncombo + 127) // 128,), (128,), (
            eL['offsets'], eL['counts'], eL['i'], eL['x'], eL['r'],
            eS['offsets'], eS['counts'], eS['i'], eS['x'], eS['r'],
            cp.asarray(self.okL), cp.asarray(self.okS), cp.asarray(labels.astype(np.int16)),
            cp.asarray((labels if labels_short is None else labels_short).astype(np.int16)),
            np.int32(nlabels), np.int32(self.ncombo), msum, mcnt, mwin, np.int32(0), np.int32(1)))
        cp.cuda.Stream.null.synchronize()
        out = (cp.asnumpy(msum).reshape(self.ncombo, nlabels).astype(np.float64),
               cp.asnumpy(mcnt).reshape(self.ncombo, nlabels))
        del msum, mcnt, mwin
        return out

    def aggregate_exit_gpu(self, labels: np.ndarray, nlabels: int):
        """Netto-R je Kombination und Label der AUSSTIEGS-Kerze, bleibt als float32 auf der GPU."""
        cp = self.cp
        msum = cp.zeros(self.ncombo * nlabels, dtype=cp.float32)
        dummy = cp.zeros(1, dtype=cp.int32)
        eL, eS = self.events['L'], self.events['S']
        self.k_combine(((self.ncombo + 127) // 128,), (128,), (
            eL['offsets'], eL['counts'], eL['i'], eL['x'], eL['r'],
            eS['offsets'], eS['counts'], eS['i'], eS['x'], eS['r'],
            cp.asarray(self.okL), cp.asarray(self.okS), cp.asarray(labels.astype(np.int16)),
            cp.asarray(labels.astype(np.int16)),
            np.int32(nlabels), np.int32(self.ncombo), msum, dummy, dummy, np.int32(1), np.int32(0)))
        cp.cuda.Stream.null.synchronize()
        return msum.reshape(self.ncombo, nlabels)

    def combo_from_values(self, values: np.ndarray) -> int:
        """Schneller Index aus kodierten Rasterwerten (Reihenfolge = PARAMS, Produkt-Reihenfolge)."""
        idx = 0
        for key, v in zip(PARAMS, values):
            grid = np.array(self.setup.grid[key])
            idx = idx * len(grid) + int(np.argmin(np.abs(grid - v)))
        return idx

    def _combine(self):
        self.msum, self.mcnt = self.aggregate(self.month, self.nmonth)

    def free(self):
        self.events = None
        self.cp.get_default_memory_pool().free_all_blocks()

    def raw_events(self, combo: int, name: str) -> pd.DataFrame:
        ev = self.events[name]
        cnt = int(ev['counts'][combo]); off = int(ev['offsets'][combo])
        return pd.DataFrame({'i': self.cp.asnumpy(ev['i'][off:off + cnt]),
                             'x': self.cp.asnumpy(ev['x'][off:off + cnt]),
                             'r': self.cp.asnumpy(ev['r'][off:off + cnt])})

    def merged_events(self, combo: int) -> pd.DataFrame:
        """Long/Short zusammengefuehrt (gleiche Kerze: Long) + Trendfilter, vor busy."""
        lo, sh = self.raw_events(combo, 'L'), self.raw_events(combo, 'S')
        lo['d'], sh['d'] = 1, 2
        sh = sh[~sh['i'].isin(lo['i'])]
        ev = pd.concat([lo, sh]).sort_values('i', kind='stable').reset_index(drop=True)
        ok = np.where(ev['d'] == 1, self.okL[ev['i']], self.okS[ev['i']]).astype(bool)
        return ev[ok].reset_index(drop=True)

    def combo_index(self, params: dict) -> int:
        target = np.array([enc(params[key]) for key in PARAMS])
        hit = np.flatnonzero(np.all(np.isclose(self.pv, target), axis=1))
        if len(hit) != 1:
            raise KeyError(params)
        return int(hit[0])
