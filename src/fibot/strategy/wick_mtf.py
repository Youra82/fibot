# src/fibot/strategy/wick_mtf.py
# "Fibo-Wick-Konfluenz" (MTF + BTC50): Kauf-Limit tief unter der kurzfristigen Mitte, nur dort, wo
#   - eine Fib-Marke des 42-Kerzen-Bereichs (61,8 / 78,6 / 127,2 / 161,8 %),
#   - eine runde Preiszahl und
#   - eine Fib-Marke einer hoeheren Zeitebene
# zusammentreffen. Ziel ist die Rueckkehr zur Mitte. Nur bei BTC-Tag > SMA200 und > SMA50, keine neuen Orders nach
# einem marktweiten Abverkauf (V2-Pause).
#
# Herkunft: Forschung 08.11.2026 (Codex Runde 13/14, eingefroren; Test 2025-01-01..2026-11-08: 34 -> 35,50 USDT,
# MaxDD 19,2 %). Diese Datei ist die EINZIGE Signalrechnung: Backtest (ganze Historie) und Live (kurzes Fenster,
# letzte Zeile) rufen dieselbe Funktion build_arrays() auf.
import hashlib

import numpy as np
import pandas as pd

STRAT_TFS = (1, 2, 4)                 # Strategie-Zeitebenen in Stunden
NATIVE_TFS = {'30m': .5, '1h': 1, '2h': 2, '4h': 4, '6h': 6}
DEPTHS = (7, 11)                      # Kauf-Limit x % unter der Mitte
FIB = (.618, .786, 1.272, 1.618)
TOL = .25                             # Toleranz in ATR
MTF_OTHER = (2, 4, 6)                 # hoehere Zeitebenen fuer die Zusatz-Konfluenz
STOP_PCT = .10
L, K, RISK, TOTAL_RISK, COIN_CAP = 3, 12, .075, .45, 1
MAX_BARS = 59                         # Zeitausstieg in Kerzen der Strategie-Zeitebene
MAKER, TAKER, SLIP, MMR, FUND = .0002, .0006, .0002, .005, .0001
MIN_NOTIONAL = 5.0
EXCLUDE = {'USDC', 'XAUT', 'PAXG', 'XAU', 'XAG', 'BTCDOM', 'DEFI', 'EUR', 'GBP'}
# Ausfuehrungs-Universum der Pruefung (54 Coins mit 30m-Historie)
UNIVERSE = ['AAVE', 'ADA', 'ALGO', 'APT', 'ARB', 'ATOM', 'AVAX', 'AXS', 'BAT', 'BCH', 'BLUR', 'BNB', 'BTC', 'CRV', 'DOGE',
            'DOT', 'EGLD', 'ETC', 'ETH', 'ETHFI', 'FET', 'FIL', 'GALA', 'HBAR', 'ICP', 'INJ', 'JUP', 'LDO', 'LINK', 'LTC',
            'MAGIC', 'NEAR', 'ONDO', 'OP', 'PEPE', 'PYTH', 'QNT', 'RSR', 'SAND', 'SEI', 'SHIB', 'SOL', 'STRK', 'STX', 'SUI',
            'SUSHI', 'THETA', 'TIA', 'TRX', 'UNI', 'WLD', 'XLM', 'XRP', 'XTZ']
STRATEGIES = [(h, 'R25', d) for h in STRAT_TFS for d in DEPTHS]


def stop_distance(ep, atr):
    return max(ep * STOP_PCT, atr, ep * .01)


def btc_regime_series(daily: pd.DataFrame) -> pd.Series:
    """1 = BTC-Tagesschluss > SMA200, gueltig ab dem Folgetag (Index = Tagesbeginn + 1 Tag)."""
    ma = daily.close.rolling(200).mean()
    reg = (daily.close > ma).astype(float).where(ma.notna())
    reg.index = reg.index + pd.Timedelta(days=1)
    return reg


def features(d: pd.DataFrame, reg: pd.Series) -> pd.DataFrame:
    """Merkmale je Kerze der nativen Zeitebene; alles um eine Kerze verschoben (nur abgeschlossene Daten)."""
    pc = d.close.shift()
    atr = pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
    mid = (d.high.rolling(5).max() + d.low.rolling(5).min()) / 2
    f = pd.DataFrame(dict(mid=mid.shift(), atr=atr.shift(), lo=d.low.rolling(42).min().shift(),
                          hi=d.high.rolling(42).max().shift()), index=d.index)
    f['g'] = reg.reindex(d.index, method='ffill')
    f.loc[f.index[:43], 'g'] = np.nan
    return f


def build_arrays(raw: dict, natives: dict, daily: pd.DataFrame, idx: pd.DatetimeIndex, strategies=None,
                 mtf: bool = True, btc50: bool = True) -> dict:
    """raw: {coin: 30m-DataFrame}; natives: {(coin, tf): DataFrame} fuer 1h/2h/4h/6h; daily: BTC-Tageskerzen;
    idx: 30m-Ausfuehrungsraster. Rueckgabe: Preise, Mitte/ATR je TF, Order-Masken, Alarm, Einstiegsfreigabe.
    strategies/mtf/btc50: nur fuer die Forschung; Standard = eingefrorene Live-Einstellung."""
    strategies = [tuple(x) for x in (strategies or STRATEGIES)]
    names = sorted(raw)
    reg = btc_regime_series(daily)
    shape = (len(idx), len(names))
    prices = {k: np.full(shape, np.nan, dtype='float32') for k in ('open', 'high', 'low', 'close')}
    for j, n in enumerate(names):
        d = raw[n]; ii = idx.get_indexer(d.index); ok = ii >= 0
        for k in prices:
            prices[k][ii[ok], j] = d[k].values[ok]
    fs, masks, bounds = {}, {}, {}
    for tf, h in NATIVE_TFS.items():
        arrays = {k: np.full(shape, np.nan, dtype='float32') for k in ('mid', 'atr', 'lo', 'hi', 'g')}
        for j, n in enumerate(names):
            d = raw[n] if tf == '30m' else natives.get((n, tf))
            if d is None or d.empty:
                continue
            native = pd.date_range(d.index.min(), d.index.max(), freq=pd.Timedelta(hours=h)); d = d.reindex(native)
            f = features(d, reg).reindex(idx, method='ffill', tolerance=pd.Timedelta(hours=h) - pd.Timedelta(minutes=30))
            for k in arrays:
                arrays[k][:, j] = f[k]
        mid, a, lo, hi, g = [arrays[k] for k in ('mid', 'atr', 'lo', 'hi', 'g')]
        fs[h] = (mid, a); bounds[h] = (lo, hi)
        for sh, rule, depth in strategies:
            if sh != h:
                continue
            band = mid * (1 - depth / 100)
            delta = np.minimum.reduce([np.abs(hi - x * (hi - lo) - band) for x in FIB])
            m = (g == 1) & np.isfinite(a) & (a > 0) & (delta <= TOL * a)
            if rule == 'R25':
                unit = 10. ** (np.floor(np.log10(np.maximum(band, 1e-20))) - 1)
                m &= np.abs(band - np.round(band / unit) * unit) <= TOL * a
            masks[h, rule, depth] = m
    for key in (list(masks) if mtf else []):
        h, _, depth = key
        band = fs[h][0] * (1 - depth / 100); support = np.zeros(shape, bool)
        for other in MTF_OTHER:
            if other <= h:
                continue
            lo, hi = bounds[other]; oa = fs[other][1]
            delta = np.minimum.reduce([np.abs(hi - x * (hi - lo) - band) for x in FIB])
            support |= delta <= TOL * np.minimum(fs[h][1], oa)
        masks[key] = masks[key] & support
    # V2-Pause: abgeschlossene 4h-Rendite auf dem 30m-Raster
    c = prices['close']; ret = np.full(shape, np.nan, dtype='float32'); ret[8:] = c[8:] / c[:-8] - 1
    valid = np.isfinite(ret); den = valid.sum(1)
    breadth = np.divide(((ret <= -.03) & valid).sum(1), den, out=np.zeros(len(idx)), where=den > 0)
    btc_ret = ret[:, names.index('BTC')] if 'BTC' in names else np.full(len(idx), np.nan)
    alarm = (breadth >= .30) | (btc_ret <= -.02) | (den < 20)
    btc50_ok = (daily.close > daily.close.rolling(50).mean()).shift(1).reindex(idx, method='ffill').fillna(False).to_numpy(bool)
    paused = pd.Series(alarm).shift(1, fill_value=True).to_numpy(bool)
    entry_ok = ~paused & btc50_ok if btc50 else ~paused
    return dict(idx=idx, names=names, p=prices, f=fs, masks=masks, alarm=alarm, btc50=btc50_ok, entry_ok=entry_ok,
                strategies=strategies)


def candidate_order(names, strategies):
    """Feste Hash-Reihenfolge der Kandidaten (wie in der Pruefung)."""
    return sorted([(s, j) for s in range(len(strategies)) for j in range(len(names))],
                  key=lambda x: hashlib.sha256(f'R10-v1|{strategies[x[0]]}|{names[x[1]]}'.encode()).digest())


def size_order(equity, available, budget, band, atr):
    """Notional einer neuen Order (0 = keine Order). Gleiche Formel live und im Backtest."""
    dist = stop_distance(band, atr)
    if dist >= band:
        return 0.0, dist
    loss = dist / band + MAKER + TAKER + SLIP
    n = min(equity * L / K, equity * RISK / loss, max(0., equity * TOTAL_RISK - budget) / loss, available / (1 / L + MAKER))
    return (n if n >= MIN_NOTIONAL else 0.0), dist
