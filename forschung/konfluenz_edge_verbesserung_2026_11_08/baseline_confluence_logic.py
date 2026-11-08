# src/fibot/strategy/confluence_logic.py
# Fibo-Kanal-Konfluenz: Limit-Order dort, wo die Kanallinie die 50-61,8%-Zone
# des letzten Impulses kreuzt. Regeln: forschung/konfluenz/PREREG.md.
#
# Long-Logik ist einmal implementiert; Shorts laufen ueber die gespiegelte
# Kursreihe (Preis -> -Preis, Hoch <-> Tief), damit beide Seiten exakt dieselben
# Regeln benutzen.

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from fibot.strategy import trend_filter

DEFAULTS = {
    'pivot_k':          5,      # Extrem ueber +-k Kerzen, bestaetigt k Kerzen spaeter
    'window':           150,    # Kerzen fuer die Kanalsuche
    'max_pivots':       8,      # juengste Pivot-Tiefs als Ankerkandidaten
    'touch_atr':        0.3,    # Pivot gilt als Linienberuehrung
    'break_atr':        0.5,    # Schlusskurs gilt als Linienbruch
    'max_break_frac':   0.03,   # erlaubter Anteil Bruch-Schlusskurse
    'min_span':         20,     # Mindestabstand erster Anker -> aktuelle Kerze
    'min_width_atr':    3.0,    # Mindestbreite des Kanals
    'b_near_upper_atr': 0.5,    # B muss nahe der oberen Linie liegen
    'fib_lo':           0.50,   # Zone 50 % ...
    'fib_hi':           0.618,  # ... bis 61,8 % Retracement
    'fib_sl':           0.786,
    'zone_tol_atr':     0.25,
    'sl_buf_atr':       0.2,
    'min_rr':           1.5,
    'atr_period':       14,
    'min_upper_touches': 1,     # v1: obere Linie nur durch das hoechste Hoch bestimmt
    'max_age_mult':     None,   # v2: Fill spaetestens max_age_mult * (B - A) Kerzen nach B
}

# Strengere Kanaldefinition nach der Stichprobe (PREREG.md, Nachtrag v2)
V2 = {'min_upper_touches': 2, 'max_break_frac': 0.0, 'max_age_mult': 2.0}


@dataclass
class Channel:
    a_pos: int            # erster Anker der unteren Linie
    slope: float
    intercept: float      # Linie: intercept + slope * pos
    width: float          # obere Linie = untere + width
    touches: int

    def lower(self, pos):
        return self.intercept + self.slope * pos

    def upper(self, pos):
        return self.lower(pos) + self.width


@dataclass
class Trade:
    direction: str
    fill_pos: int
    entry: float
    sl: float
    tp: float
    exit_pos: int = -1
    exit: float = float('nan')
    result: str = 'open'
    a_pos: int = -1
    b_pos: int = -1
    channel: Optional[Channel] = None
    meta: dict = field(default_factory=dict)

    @property
    def r_gross(self):
        risk = self.entry - self.sl if self.direction == 'long' else self.sl - self.entry
        move = self.exit - self.entry if self.direction == 'long' else self.entry - self.exit
        return move / risk


def _atr(high, low, close, period):
    prev = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum.reduce([high - low, np.abs(high - prev), np.abs(low - prev)])
    return pd.Series(tr).ewm(span=period, min_periods=period).mean().values


def _pivots(arr, k, mode):
    """Positionen p, an denen arr[p] Extrem ueber [p-k, p+k] ist (bestaetigt bei p+k)."""
    s = pd.Series(arr)
    roll = s.rolling(2 * k + 1, center=True)
    ext = roll.min() if mode == 'low' else roll.max()
    pos = np.where(arr == ext.values)[0]
    # Plateaus: nur das erste Element einer Gleichheitskette behalten
    keep, last = [], -10 ** 9
    for p in pos:
        if p - last > k:
            keep.append(p)
            last = p
    return np.array(keep, dtype=int)


def _allowed(p, n):
    return 0 if p['max_break_frac'] <= 0 else max(1, p['max_break_frac'] * n)


def find_channel(i, lows, highs, closes, atr, pl_pos, ph_pos, p):
    """Steigenden Kanal mit Daten bis einschliesslich Kerze i suchen (nur bestaetigte Pivots)."""
    k = p['pivot_k']
    a = atr[i]
    if not np.isfinite(a) or a <= 0:
        return None
    lo_win = i - p['window']
    conf_l = pl_pos[(pl_pos >= lo_win) & (pl_pos <= i - k)][-p['max_pivots']:]
    conf_h = ph_pos[(ph_pos >= lo_win) & (ph_pos <= i - k)]
    if len(conf_l) < 2 or len(conf_h) < 1:
        return None
    best = None
    for x in range(len(conf_l) - 1):
        for y in range(x + 1, len(conf_l)):
            p1, p2 = conf_l[x], conf_l[y]
            if p2 - p1 < 2 * k or lows[p2] <= lows[p1]:
                continue
            if i - p1 < p['min_span']:
                continue
            slope = (lows[p2] - lows[p1]) / (p2 - p1)
            icpt = lows[p1] - slope * p1
            seg = np.arange(p1, i + 1)
            line = icpt + slope * seg
            # Schlusskurs-Brueche unter der Linie
            br = np.count_nonzero(closes[p1:i + 1] < line - p['break_atr'] * a)
            if br > _allowed(p, len(seg)):
                continue
            lp = conf_l[conf_l >= p1]
            dev = lows[lp] - (icpt + slope * lp)
            if np.any(dev < -p['break_atr'] * a):
                continue
            touches = int(np.count_nonzero(np.abs(dev) <= p['touch_atr'] * a))
            if touches < 2:
                continue
            hp = conf_h[conf_h >= p1]
            if len(hp) == 0:
                continue
            width = float(np.max(highs[hp] - (icpt + slope * hp)))
            if width < p['min_width_atr'] * a:
                continue
            br_up = np.count_nonzero(closes[p1:i + 1] > line + width + p['break_atr'] * a)
            if br_up > _allowed(p, len(seg)):
                continue
            up_dev = highs[hp] - (icpt + slope * hp + width)
            if np.count_nonzero(np.abs(up_dev) <= p['touch_atr'] * a) < p['min_upper_touches']:
                continue
            key = (touches, p2)
            if best is None or key > best[0]:
                best = (key, Channel(int(p1), float(slope), float(icpt), width, touches))
    return best[1] if best else None


def simulate_long(o, h, l, c, p=None, direction='long'):
    """Konfluenz-Strategie (long) auf OHLC-Arrays. Gibt geschlossene + offene Trades zurueck."""
    p = {**DEFAULTS, **(p or {})}
    n = len(c)
    k = p['pivot_k']
    atr = _atr(h, l, c, p['atr_period'])
    pl_pos = _pivots(l, k, 'low')
    ph_pos = _pivots(h, k, 'high')

    trades: List[Trade] = []
    pos: Optional[Trade] = None
    used_b = set()
    chan: Optional[Channel] = None
    chan_key = None

    for i in range(p['window'] + k + 1, n):
        j = i - 1                      # Entscheidungsbasis: Daten bis Kerze j
        # --- offene Position verwalten (Kerze i) ---
        if pos is not None:
            if l[i] <= pos.sl:
                pos.exit, pos.exit_pos, pos.result = pos.sl, i, 'loss'
            elif h[i] >= pos.tp:
                pos.exit, pos.exit_pos, pos.result = pos.tp, i, 'win'
            if pos.result != 'open':
                trades.append(pos)
                pos = None
            continue

        # --- Kanal mit Daten bis j suchen (jede Kerze, damit Brueche sofort zaehlen) ---
        chan = find_channel(j, l, h, c, atr, pl_pos, ph_pos, p)
        if chan is None:
            continue
        a = atr[j]
        # Impuls: A = letztes Pivot-Tief an der Linie, B = hoechstes bestaetigtes Hoch danach
        lp = pl_pos[(pl_pos >= chan.a_pos) & (pl_pos <= j - k)]
        touch = lp[np.abs(l[lp] - chan.lower(lp)) <= p['touch_atr'] * a]
        if len(touch) == 0:
            continue
        A = int(touch[-1])
        hp = ph_pos[(ph_pos > A) & (ph_pos <= j - k)]
        if len(hp) == 0:
            continue
        B = int(hp[np.argmax(h[hp])])
        if B in used_b:
            continue
        if h[B] < chan.upper(B) - p['b_near_upper_atr'] * a:
            continue
        hi, lo = h[B], l[A]
        if np.max(h[B:j + 1]) > hi:     # neues Hoch nach B -> Impuls noch nicht fertig
            continue
        diff = hi - lo
        f50, f618, f786 = hi - p['fib_lo'] * diff, hi - p['fib_hi'] * diff, hi - p['fib_sl'] * diff
        if np.min(c[B:j + 1]) < f786:
            used_b.add(B)
            continue
        if p['max_age_mult'] is not None and i - B > p['max_age_mult'] * (B - A):
            continue
        limit = chan.lower(i)
        tol = p['zone_tol_atr'] * a
        if not (f618 - tol <= limit <= f50 + tol):
            continue
        if c[j] <= limit:
            continue
        sl = min(f786, limit) - p['sl_buf_atr'] * a
        tp = chan.upper(i)
        if limit - sl <= 0 or (tp - limit) / (limit - sl) < p['min_rr']:
            continue
        # --- Order liegt in Kerze i ---
        if l[i] <= limit:
            used_b.add(B)
            t = Trade(direction, i, limit, sl, tp, a_pos=A, b_pos=B, channel=chan,
                      meta={'f50': f50, 'f618': f618, 'f786': f786, 'atr': a})
            if l[i] <= sl:             # Fuellkerze erreicht SL -> konservativ Verlust
                t.exit, t.exit_pos, t.result = sl, i, 'loss'
                trades.append(t)
            else:
                pos = t
    if pos is not None:
        pos.exit, pos.exit_pos = c[-1], n - 1
        trades.append(pos)
    return trades


def run_confluence(df: pd.DataFrame, params=None) -> List[Trade]:
    """Long + Short (gespiegelt). Short-Trades werden in echte Preise zurueckgerechnet."""
    o, h, l, c = (df[x].values.astype(float) for x in ('open', 'high', 'low', 'close'))
    longs = simulate_long(o, h, l, c, params, 'long')
    shorts = simulate_long(-o, -l, -h, -c, params, 'short')
    for t in shorts:
        t.entry, t.sl, t.tp, t.exit = -t.entry, -t.sl, -t.tp, -t.exit
        for kk in ('f50', 'f618', 'f786'):
            t.meta[kk] = -t.meta[kk]
        t.meta['mirrored'] = True
    return sorted(longs + shorts, key=lambda t: t.fill_pos)


# ===========================================================================
# Produktiv-Pfad (Live + Backtest + Optimizer teilen exakt diese Funktionen)
# ===========================================================================
# Unterschied zum Forschungs-Simulator oben: Planung und Fill-Ereignisse sind
# unabhaengig vom Positionsstatus. Jedes Impuls-Hoch B erzeugt hoechstens EIN
# Fill-Ereignis (erste Beruehrung des Limits); ob daraus ein Trade wird,
# entscheidet der Aufrufer (Backtester: keine offene Position; Live: dito).
# Damit kann der Live-Bot aus den letzten Kerzen denselben Zustand
# rekonstruieren wie der Backtest aus der vollen Historie.

CHANNEL_KEYS = ('pivot_k', 'window', 'max_pivots', 'touch_atr', 'break_atr',
                'max_break_frac', 'min_span', 'min_width_atr', 'min_upper_touches', 'atr_period')

_CHANNEL_CACHE: dict = {}


def strategy_params(config: dict) -> dict:
    """Konfluenz-Parameter aus config['strategy'] (fehlende Werte = Lehrbuch-Defaults)."""
    s = config.get('strategy', {})
    p = {**DEFAULTS, 'tp_mode': 'upper'}
    for k in list(p):
        if k in s:
            p[k] = s[k]
    return p


def _channel_series(h, l, c, p, cache_key=None):
    """Kanal fuer jede Kerze j (Daten bis j). Rueckgabe: dict mit Arrays."""
    ck = None
    if cache_key is not None:
        ck = (cache_key, tuple(p[k] for k in CHANNEL_KEYS))
        if ck in _CHANNEL_CACHE:
            return _CHANNEL_CACHE[ck]
    n = len(c)
    k = int(p['pivot_k'])
    atr = _atr(h, l, c, int(p['atr_period']))
    pl_pos = _pivots(l, k, 'low')
    ph_pos = _pivots(h, k, 'high')
    valid = np.zeros(n, dtype=bool)
    a_pos = np.zeros(n, dtype=np.int64)
    slope = np.zeros(n)
    icpt = np.zeros(n)
    width = np.zeros(n)
    for j in range(int(p['window']) + k, n):
        ch = find_channel(j, l, h, c, atr, pl_pos, ph_pos, p)
        if ch is not None:
            valid[j], a_pos[j], slope[j], icpt[j], width[j] = True, ch.a_pos, ch.slope, ch.intercept, ch.width
    res = {'atr': atr, 'pl': pl_pos, 'ph': ph_pos, 'valid': valid, 'a_pos': a_pos,
           'slope': slope, 'icpt': icpt, 'width': width}
    if ck is not None:
        if len(_CHANNEL_CACHE) > 400:
            _CHANNEL_CACHE.clear()
        _CHANNEL_CACHE[ck] = res
    return res


def _plan_one_direction(h, l, c, p, cache_key=None):
    """Plant fuer jede Kerze i in [0, n] (i = n ist die noch kommende Kerze) die
    Limit-Order aus Daten bis i-1 und markiert Fill-Ereignisse (i < n)."""
    n = len(c)
    ch = _channel_series(h, l, c, p, cache_key)
    atr, pl_pos, ph_pos = ch['atr'], ch['pl'], ch['ph']
    k = int(p['pivot_k'])
    lim = np.full(n + 1, np.nan)
    sl_a = np.full(n + 1, np.nan)
    tp_a = np.full(n + 1, np.nan)
    a_a = np.full(n + 1, -1, dtype=np.int64)
    b_a = np.full(n + 1, -1, dtype=np.int64)
    fill = np.zeros(n + 1, dtype=bool)
    instant = np.zeros(n + 1, dtype=bool)
    used_b = set()
    age_mult = p.get('max_age_mult')
    for i in range(int(p['window']) + k + 1, n + 1):
        j = i - 1
        if not ch['valid'][j]:
            continue
        a = atr[j]
        slope, icpt, width, a0 = ch['slope'][j], ch['icpt'][j], ch['width'][j], ch['a_pos'][j]
        lp = pl_pos[(pl_pos >= a0) & (pl_pos <= j - k)]
        touch = lp[np.abs(l[lp] - (icpt + slope * lp)) <= p['touch_atr'] * a]
        if len(touch) == 0:
            continue
        A = int(touch[-1])
        hp = ph_pos[(ph_pos > A) & (ph_pos <= j - k)]
        if len(hp) == 0:
            continue
        B = int(hp[np.argmax(h[hp])])
        if B in used_b:
            continue
        if h[B] < icpt + slope * B + width - p['b_near_upper_atr'] * a:
            continue
        hi, lo = h[B], l[A]
        if np.max(h[B:j + 1]) > hi:
            continue
        diff = hi - lo
        f50 = hi - p['fib_lo'] * diff
        f618 = hi - p['fib_hi'] * diff
        f786 = hi - p['fib_sl'] * diff
        if np.min(c[B:j + 1]) < f786:
            used_b.add(B)
            continue
        if age_mult is not None and i - B > age_mult * (B - A):
            continue
        limit = icpt + slope * i
        tol = p['zone_tol_atr'] * a
        if not (f618 - tol <= limit <= f50 + tol) or c[j] <= limit:
            continue
        sl = min(f786, limit) - p['sl_buf_atr'] * a
        tp = icpt + slope * i + width if p.get('tp_mode', 'upper') == 'upper' else hi
        if limit - sl <= 0 or (tp - limit) / (limit - sl) < p['min_rr']:
            continue
        lim[i], sl_a[i], tp_a[i], a_a[i], b_a[i] = limit, sl, tp, A, B
        if i < n and l[i] <= limit:
            fill[i] = True
            instant[i] = l[i] <= sl
            used_b.add(B)
    return {'limit': lim, 'sl': sl_a, 'tp': tp_a, 'A': a_a, 'B': b_a, 'fill': fill, 'instant': instant, 'ch': ch}


def plan_both(df: pd.DataFrame, config: dict, cache_key=None):
    """Plaene fuer Long (echte Preise) und Short (gespiegelt, zurueckgerechnet)."""
    p = strategy_params(config)
    h, l, c = (df[x].values.astype(float) for x in ('high', 'low', 'close'))
    lo = _plan_one_direction(h, l, c, p, None if cache_key is None else (cache_key, 'L'))
    sh = _plan_one_direction(-l, -h, -c, p, None if cache_key is None else (cache_key, 'S'))
    for key in ('limit', 'sl', 'tp'):
        sh[key] = -sh[key]
    return lo, sh


_TREND_CACHE: dict = {}


def _trend_series_for_backtest(df: pd.DataFrame, config: dict, tf_cfg: dict):
    """HTF- und Tagestrend fuer den Backtest: laedt Vorlauf (EMA eingeschwungen) und Tageskerzen.
    Fehlen die Daten, bricht der Backtest ab statt ungefiltert weiterzurechnen."""
    from fibot.analysis.backtester import load_ohlcv
    symbol, tf = config['market']['symbol'], config['market']['timeframe']
    start = df.index[0] - pd.Timedelta(tf) * trend_filter.base_bars_needed(tf_cfg)
    key = (symbol, tf, start.floor('D'), df.index[-1].floor('D'), tuple(sorted(tf_cfg.items())))
    if key not in _TREND_CACHE:
        if len(_TREND_CACHE) > 200:
            _TREND_CACHE.clear()
        end_s = df.index[-1].strftime('%Y-%m-%d')
        ext = load_ohlcv(symbol, tf, start.strftime('%Y-%m-%d'), end_s)
        base = df[['close']] if ext is None or ext.empty else ext[['close']].combine_first(df[['close']])
        daily = load_ohlcv(symbol, '1d', (df.index[0] - pd.Timedelta(days=trend_filter.DAILY_BARS_NEEDED)).strftime('%Y-%m-%d'), end_s)
        if daily is None or daily.empty:
            raise RuntimeError(f"Trendfilter: keine Tageskerzen fuer {symbol} -- Backtest abgebrochen")
        _TREND_CACHE[key] = (trend_filter.htf_trend(base, tf, tf_cfg), trend_filter.daily_trend(daily, tf_cfg))
    return _TREND_CACHE[key]


def precompute_confluence_signals(df: pd.DataFrame, config: dict, cache_key=None) -> pd.DataFrame:
    """Signal-Spalten im Format des bestehenden Backtesters/Portfolio-Simulators.
    _sig_dir sitzt auf der FUELL-Kerze; _sig_entry ist der Limitpreis.
    _sig_instant = SL in derselben Kerze erreicht (konservativ Verlust)."""
    lo, sh = plan_both(df, config, cache_key)
    n = len(df)
    sig_dir = np.zeros(n, dtype=np.int8)
    entry = np.zeros(n)
    sl = np.zeros(n)
    tp = np.zeros(n)
    inst = np.zeros(n, dtype=bool)
    sw_hi = np.zeros(n)
    sw_lo = np.zeros(n)
    hv, lv = df['high'].values, df['low'].values
    for d, pl in ((1, lo), (2, sh)):
        for i in np.where(pl['fill'][:n])[0]:
            if sig_dir[i] != 0:          # Long und Short in derselben Kerze: Long behalten
                continue
            sig_dir[i] = d
            entry[i], sl[i], tp[i], inst[i] = pl['limit'][i], pl['sl'][i], pl['tp'][i], pl['instant'][i]
            A, B = pl['A'][i], pl['B'][i]
            if d == 1:
                sw_lo[i], sw_hi[i] = lv[A], hv[B]
            else:
                sw_hi[i], sw_lo[i] = hv[A], lv[B]
    tf_cfg = trend_filter.settings()
    if tf_cfg['enabled'] and sig_dir.any():
        htf, daily = _trend_series_for_backtest(df, config, tf_cfg)
        sig_dir = trend_filter.mask_signals(sig_dir, df.index, htf, daily)
    df = df.copy()
    df['_sig_dir'] = sig_dir
    df['_sig_entry'] = entry
    df['_sig_sl'] = sl
    df['_sig_tp1'] = tp
    df['_sig_score'] = np.where(sig_dir > 0, 1.0, 0.0)
    df['_sig_instant'] = inst
    df['_sig_swing_high'] = sw_hi
    df['_sig_swing_low'] = sw_lo
    return df


def plan_next_order(df_closed: pd.DataFrame, config: dict) -> Optional[dict]:
    """Live: Limit-Order fuer die laufende Kerze (Index n) aus abgeschlossenen Kerzen.
    Identische Rechnung wie im Backtest (plan_both, Index n)."""
    lo, sh = plan_both(df_closed, config)
    n = len(df_closed)
    for d, pl in (('long', lo), ('short', sh)):   # Long zuerst, wie im Backtest
        if np.isfinite(pl['limit'][n]):
            risk = abs(pl['limit'][n] - pl['sl'][n])
            return {'direction': d, 'limit': float(pl['limit'][n]), 'sl': float(pl['sl'][n]),
                    'tp': float(pl['tp'][n]), 'rr': abs(pl['tp'][n] - pl['limit'][n]) / risk,
                    'a_ts': str(df_closed.index[pl['A'][n]]), 'b_ts': str(df_closed.index[pl['B'][n]])}
    return None


def is_confluence(config: dict) -> bool:
    return config.get('strategy', {}).get('type') == 'confluence'


def channel_lines_for_fills(df: pd.DataFrame, config: dict) -> list:
    """Fuer Charts: Kanal (echte Preise), wie er zum Zeitpunkt jedes Fills bekannt war."""
    lo, sh = plan_both(df, config)
    n = len(df)
    out = []
    for d, pl in (('long', lo), ('short', sh)):
        ch = pl['ch']
        for i in np.where(pl['fill'][:n])[0]:
            j = i - 1
            a0, sl_, ic, w = int(ch['a_pos'][j]), ch['slope'][j], ch['icpt'][j], ch['width'][j]
            x1 = min(n - 1, i + 30)
            l0, l1 = ic + sl_ * a0, ic + sl_ * x1
            if d == 'long':
                lower, upper = (l0, l1), (l0 + w, l1 + w)
            else:
                upper, lower = (-l0, -l1), (-(l0 + w), -(l1 + w))
            out.append({'direction': d, 'x0': df.index[a0], 'x1': df.index[x1],
                        'lower': lower, 'upper': upper, 'fill_ts': df.index[i]})
    return out
