# Claude Runde 18: Docht-Rueckkehr mit ATR-Tiefe und Fibonacci-Ziel (unabhaengig von Codex).
# Mechanismus: Liquidations-/Stop-Kaskaden erzeugen tiefe Dochte, die schnell zur kurzfristigen Mitte zurueckkehren
# (bisher einzige robuste Kante). Tiefe in ATR statt Prozent -> jeder Coin bekommt seine Tiefe aus der eigenen
# Schwankung (kein Je-Coin-Tuning). Fib-Ziel 61,8 % des Rueckwegs = Teil der Rueckkehr, der am haeufigsten erreicht wird.
# Lieferformat wie Codex Runde 18: VARIANTEN, trades(root, variante) -> DataFrame (coin, tf, dir, ts, exit_ts, ret, stress_ret)
import os
import numpy as np
import pandas as pd

MAK, TAK, SLP, FUND = .02, .06, .02, .01            # Prozent
VARIANTEN = ['W1_1h_3ATR_MID', 'W2_4h_3ATR_MID', 'W3_1h_3ATR_F618', 'W4_4h_3ATR_F618', 'W5_1h_4ATR_MID']
CFG = {'W1_1h_3ATR_MID': ('1h', 3., 1.), 'W2_4h_3ATR_MID': ('4h', 3., 1.), 'W3_1h_3ATR_F618': ('1h', 3., .618),
       'W4_4h_3ATR_F618': ('4h', 3., .618), 'W5_1h_4ATR_MID': ('1h', 4., 1.)}
H = {'1h': 1, '4h': 4}
MAX_BARS = 48


def _rd(p):
    d = pd.read_csv(p); d.index = pd.to_datetime(d.iloc[:, 0], utc=True)
    d = d[['open', 'high', 'low', 'close']].astype(float).sort_index()
    return d[~d.index.duplicated(keep='last')]


def _gate(root):
    b = _rd(os.path.join(root, 'BTC_1d.csv')); c = b.close; ma = c.rolling(200).mean()
    g = (c > ma).astype(float).where(ma.notna()); g.index = g.index + pd.Timedelta(days=1)   # gilt ab Folgetag
    return g


def _coin(d, gate, tf, k, frac):
    h = H[tf]; d = d.reindex(pd.date_range(d.index.min(), d.index.max(), freq=pd.Timedelta(hours=h)))
    o, hi, lo, c = (d[x].to_numpy() for x in ('open', 'high', 'low', 'close'))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.fmax(hi - lo, np.fmax(np.abs(hi - pc), np.abs(lo - pc)))
    atr = pd.Series(tr).rolling(14).mean().shift().to_numpy()
    mid = ((pd.Series(hi).rolling(5).max() + pd.Series(lo).rolling(5).min()) / 2).shift().to_numpy()
    g = gate.reindex(d.index, method='ffill').to_numpy()
    band = mid - k * atr
    with np.errstate(invalid='ignore'):
        sig = (g == 1) & np.isfinite(band) & (band > 0) & (lo <= band)
    sig[:30] = False
    out, i, n, ts = [], 0, len(c), d.index
    cand = np.flatnonzero(sig); kx = 0
    while kx < len(cand):
        i = cand[kx]
        ep = min(o[i], band[i]) if np.isfinite(o[i]) else band[i]
        sl = ep - max(.10 * ep, 1.5 * atr[i])
        res = None
        for j in range(i, min(n, i + MAX_BARS)):
            if not np.isfinite(lo[j]):
                continue
            if lo[j] <= sl:
                xp = (o[j] if (j > i and o[j] < sl) else sl) * (1 - SLP / 100); fee = TAK; res = 'sl'; break
            if j > i and np.isfinite(mid[j]):
                tp = ep + frac * (mid[j] - ep)
                if tp > ep and hi[j] >= tp:
                    xp = max(o[j], tp); fee = MAK; res = 'tp'; break
        if res is None:
            j = min(n - 1, i + MAX_BARS - 1); xp = c[j] * (1 - SLP / 100) if np.isfinite(c[j]) else ep; fee = TAK; res = 'time'
        fund = FUND * (j - i + 1) * h / 8
        gross = (xp / ep - 1) * 100
        cost = MAK + fee + fund
        out.append((ts[i], ts[j] + pd.Timedelta(hours=h), gross - cost, gross - 2 * cost, res))
        kx = np.searchsorted(cand, j + 1)
    return out


def trades(root, variante):
    tf, k, frac = CFG[variante]; gate = _gate(root); rows = []
    folder = os.path.join(root, tf)
    for f in sorted(os.listdir(folder)):
        coin = f.split('_')[0]
        d = _rd(os.path.join(folder, f))
        if len(d) < 300:
            continue
        for ts, ex, r, sr, res in _coin(d, gate, tf, k, frac):
            rows.append(dict(coin=coin, tf=tf, dir='long', ts=ts, exit_ts=ex, ret=r, stress_ret=sr, res=res))
    return pd.DataFrame(rows)
