# Gemeinsame Testumgebung fuer die Strategiesuche (Claude + Codex), 08.11.2026.
# Daten: geobot-Speicher (nur heute gelistete Coins -> Survivorship), Kosten konservativ.
import os
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
GEO = os.path.join(ROOT, 'geobot', 'data', 'cache')
FIB = os.path.join(ROOT, 'fibot', 'data', 'cache')
SEED = 20261108
DISC_END = pd.Timestamp('2026-01-01', tz='UTC')     # Suche auf A bis 31.12.2025
HOLD_START = pd.Timestamp('2026-10-15', tz='UTC')   # Endtest unberuehrt
TAKER, MAKER, SLIP = 0.0006, 0.0002, 0.0002         # je Seite; Schlupf auf Market/Stop
EXCLUDE = {'USDC', 'XAUT', 'PAXG', 'XAU', 'XAG', 'BTCDOM', 'DEFI', 'EUR', 'GBP'}


def _read(path):
    df = pd.read_csv(path)
    df.index = pd.to_datetime(df[df.columns[0]], utc=True)
    df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    return df[~df.index.duplicated()].sort_index()


def load_universe(tf='4h', min_bars=600):
    out = {}
    for f in sorted(os.listdir(GEO)):
        if not f.endswith(f'-USDT-USDT_{tf}.csv'):
            continue
        coin = f.split('-')[0]
        if coin in EXCLUDE:
            continue
        df = _read(os.path.join(GEO, f))
        if len(df) >= min_bars:
            out[coin] = df
    return out


def split_coins(coins):
    coins = sorted(coins)
    rng = np.random.default_rng(SEED)
    perm = list(rng.permutation(coins))
    h = len(perm) // 2
    return set(perm[:h]), set(perm[h:])


def btc_daily():
    """BTC-Tageskerzen: stbot (ab 2019) + ltbbot (bis heute) + Tage aus geobot-4h, zusammengesetzt."""
    parts = []
    for p in (os.path.join(ROOT, 'ltbbot', 'data', 'cache', 'BTC-USDT-USDT_1d.csv'),
              os.path.join(ROOT, 'stbot', 'data', 'cache', 'BTC-USDT-USDT_1d.csv')):
        if os.path.exists(p):
            parts.append(_read(p))
    h4 = _read(os.path.join(GEO, 'BTC-USDT-USDT_4h.csv'))
    d4 = h4.resample('1D').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
    parts.append(d4.iloc[:-1])          # angebrochenen letzten Tag verwerfen
    d = parts[0]
    for p in parts[1:]:
        d = d.combine_first(p)
    if d.index[0] > pd.Timestamp('2021-01-01', tz='UTC'):
        raise RuntimeError('BTC 1d: zu kurze Historie')
    return d


def btc_regime():
    """1 = BTC Tagesschluss > SMA200, bekannt ab dem Folgetag (Index = Zeitpunkt, ab dem es gilt)."""
    d = btc_daily()
    up = (d.close > d.close.rolling(200).mean()).astype(float)[d.close.rolling(200).count() >= 200]
    up.index = up.index + pd.Timedelta(days=1)
    return up


def at(series, index):
    """Wert der Reihe zum jeweiligen Zeitpunkt (letzter bekannter), fuer einen DatetimeIndex."""
    pos = series.index.searchsorted(index, side='right') - 1
    vals = series.values
    return np.where(pos >= 0, vals[np.clip(pos, 0, None)], np.nan)


def atr(df, n=14):
    h, l, c = df.high.values, df.low.values, df.close.values
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    return pd.Series(tr, index=df.index).rolling(n).mean().values


def run_trades(df, entries, side=1, max_bars=60, entry_type='market'):
    """entries: Liste von (i, entry_price_or_None, sl, tp). i = Kerze, in der eingestiegen wird.
    market: Einstieg zum Open der Kerze i. limit: Fill wenn Kerze i den Preis beruehrt (Maker), sonst verfallen.
    SL zuerst, wenn SL und TP in derselben Kerze. Ein Trade je Coin gleichzeitig. Rueckgabe: Liste dicts."""
    o, h, l, c = df.open.values, df.high.values, df.low.values, df.close.values
    idx = df.index
    n = len(df)
    trades, busy_until = [], -1
    for (i, px, sl, tp) in entries:
        if i <= busy_until or i >= n:
            continue
        if entry_type == 'market':
            ep, fee_in = o[i] * (1 + side * SLIP), TAKER
        else:
            touched = l[i] <= px if side == 1 else h[i] >= px
            if not touched:
                continue
            ep, fee_in = (min(px, o[i]) if side == 1 else max(px, o[i])), MAKER
        res, xp, j = None, None, i
        for j in range(i, min(n, i + max_bars)):
            hit_sl = (l[j] <= sl) if side == 1 else (h[j] >= sl)
            hit_tp = (h[j] >= tp) if side == 1 else (l[j] <= tp)
            if hit_sl:
                gap = (o[j] < sl) if side == 1 else (o[j] > sl)
                xp = (o[j] if gap and j > i else sl) * (1 - side * SLIP)
                res, fee_out = 'sl', TAKER
                break
            if hit_tp and j > i:
                xp, res, fee_out = tp, 'tp', MAKER
                break
        if res is None:
            j = min(n - 1, i + max_bars - 1)
            xp, res, fee_out = c[j] * (1 - side * SLIP), 'time', TAKER
        ret = side * (xp / ep - 1) - fee_in - fee_out
        trades.append({'entry_ts': idx[i], 'exit_ts': idx[j], 'entry': ep, 'exit': xp, 'ret': ret, 'res': res,
                       'bars': j - i + 1, 'side': side})
        busy_until = j
    return trades


def evaluate(tr, label=''):
    """tr: DataFrame mit coin, entry_ts, ret. Kriterien aus dem Protokoll."""
    if tr is None or len(tr) == 0:
        print(f'{label}: keine Trades'); return {}
    tr = tr.copy()
    tr['day'] = pd.to_datetime(tr.entry_ts, utc=True).dt.floor('D')
    daily = tr.groupby('day').ret.mean()
    t_day = daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily))) if len(daily) > 2 else np.nan
    per_coin = tr.groupby('coin').ret.sum()
    top5 = per_coin.sort_values(ascending=False).index[:5]
    wo = tr[~tr.coin.isin(top5)].ret.mean()
    mid = tr.entry_ts.min() + (tr.entry_ts.max() - tr.entry_ts.min()) / 2
    h1, h2 = tr[tr.entry_ts < mid].ret.mean(), tr[tr.entry_ts >= mid].ret.mean()
    r = {'n': len(tr), 'ret_pct': tr.ret.mean() * 100, 'median_pct': tr.ret.median() * 100, 't_tag': t_day,
         'trefferquote': (tr.ret > 0).mean() * 100, 'coins_pos_pct': (per_coin > 0).mean() * 100,
         'ohne_top5_pct': wo * 100, 'h1_pct': h1 * 100, 'h2_pct': h2 * 100, 'coins': tr.coin.nunique(),
         'trades_pro_jahr': len(tr) / max(1e-9, (tr.entry_ts.max() - tr.entry_ts.min()).days / 365)}
    r['bestanden'] = bool(r['ret_pct'] > 0 and r['t_tag'] >= 2 and r['coins_pos_pct'] >= 55 and r['ohne_top5_pct'] > 0
                          and r['h1_pct'] > 0 and r['h2_pct'] > 0)
    print(f"{label:34s} n {r['n']:6d} | {r['ret_pct']:+.3f} %/Trade (Median {r['median_pct']:+.2f}) t {r['t_tag']:+.1f} | "
          f"Treffer {r['trefferquote']:.0f} % | Coins+ {r['coins_pos_pct']:.0f} % | ohne Top5 {r['ohne_top5_pct']:+.3f} | "
          f"H1 {r['h1_pct']:+.3f} H2 {r['h2_pct']:+.3f} | {r['trades_pro_jahr']:.0f}/J | {'BESTANDEN' if r['bestanden'] else 'nein'}")
    return r


def segments(tr, A, B):
    """Die drei Pruefsegmente des Protokolls."""
    ts = pd.to_datetime(tr.entry_ts, utc=True)
    return {
        'SUCHE  A bis 2025': tr[tr.coin.isin(A) & (ts < DISC_END)],
        'PRUEF  B bis 14.10.26': tr[tr.coin.isin(B) & (ts < HOLD_START)],
        'PRUEF  A 2026 bis 14.10.': tr[tr.coin.isin(A) & (ts >= DISC_END) & (ts < HOLD_START)],
        'ENDTEST alle ab 15.10.': tr[ts >= HOLD_START],
    }
