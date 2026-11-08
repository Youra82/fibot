# Fibo-Kanal-Konfluenz 2.0 "Kanal-Wick" (Claude), Erkundung auf Entwicklungsdaten bis 2024.
# Regel: gueltiger Kanal + Impuls A->B (Bot-Code), Kauf-Limit 0,5 ATR unter der unteren Kanallinie, nur wenn dort
# eine Fib-Marke des Impulses (0,786/0,886/1,0/1,272) UND eine runde Zahl je +-0,25 ATR liegen. TP Kanal-Mittellinie,
# Stop 10 % (mind. 1 ATR), BTC-Tag > SMA200 und > SMA50, max. 60 Kerzen. Long. Kosten wie runde3.
import os, sys
from multiprocessing import Pool
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', '..', 'src'))
from fibot.strategy.confluence_logic import DEFAULTS, find_channel, _atr, _pivots
MAK, TAK, SLP = .0002, .0006, .0002
P = {**DEFAULTS, 'pivot_k': 3, 'window': 150, 'min_upper_touches': 1, 'max_break_frac': 0.0, 'min_width_atr': 2.0}
DEV = sys.argv[1] if len(sys.argv) > 1 else ''


def rd(p):
    d = pd.read_csv(p); d.index = pd.to_datetime(d[d.columns[0]], utc=True)
    return d[['open', 'high', 'low', 'close']].astype(float).sort_index()


def regime(btc):
    c = btc.close; ok = ((c > c.rolling(200).mean()) & (c > c.rolling(50).mean())).astype(float)
    ok.index = ok.index + pd.Timedelta(days=1); return ok


def job(args):
    f, reg = args
    df = rd(f); coin = os.path.basename(f).split('-')[0]
    o, h, l, c = (df[x].values for x in ('open', 'high', 'low', 'close'))
    n, k = len(c), int(P['pivot_k'])
    if n < 300: return []
    atr = _atr(h, l, c, 14); pl, ph = _pivots(l, k, 'low'), _pivots(h, k, 'high')
    g = reg.reindex(df.index, method='ffill').values
    out, free, used = [], 0, set()
    for i in range(int(P['window']) + k + 1, n):
        if i < free or g[i] != 1: continue
        j = i - 1; a = atr[j]
        ch = find_channel(j, l, h, c, atr, pl, ph, P)
        if ch is None or not np.isfinite(a): continue
        lp = pl[(pl >= ch.a_pos) & (pl <= j - k)]
        touch = lp[np.abs(l[lp] - ch.lower(lp)) <= P['touch_atr'] * a]
        if len(touch) == 0: continue
        A = int(touch[-1]); hp = ph[(ph > A) & (ph <= j - k)]
        if len(hp) == 0: continue
        B = int(hp[np.argmax(h[hp])])
        if B in used or np.max(h[B:j + 1]) > h[B]: continue
        hi, lo = h[B], l[A]; diff = hi - lo
        limit = ch.lower(i) - 0.5 * a
        if c[j] <= ch.lower(j) or limit <= 0: continue           # Kurs noch ueber der Linie
        fib = min(abs(limit - (hi - r * diff)) for r in (.786, .886, 1.0, 1.272)) <= .25 * a
        unit = 10. ** (np.floor(np.log10(limit)) - 1)
        rnd = abs(limit - round(limit / unit) * unit) <= .25 * a
        if not (fib and rnd): continue
        if l[i] > limit: continue
        used.add(B)
        ep = min(o[i], limit); sl = ep - max(.10 * ep, a); res, xp = None, None
        for jj in range(i, min(n, i + 60)):
            mid = ch.lower(jj) + ch.width / 2
            if l[jj] <= sl: xp = (o[jj] if o[jj] < sl and jj > i else sl) * (1 - SLP); res = 'sl'; break
            if jj > i and h[jj] >= mid: xp = max(o[jj], mid); res = 'tp'; break
        if res is None: jj = min(n - 1, i + 59); xp = c[jj] * (1 - SLP); res = 'time'
        ret = xp / ep - 1 - MAK - (MAK if res == 'tp' else TAK) * xp / ep
        out.append(dict(coin=coin, entry_ts=df.index[i], ret=ret, res=res))
        free = jj + 1
    return out


if __name__ == '__main__':
    files = [os.path.join(DEV, x) for x in sorted(os.listdir(DEV)) if x.endswith('_4h.csv')]
    reg = regime(rd(sys.argv[2]))
    with Pool(6) as p: parts = p.map(job, [(f, reg) for f in files], chunksize=2)
    T = pd.DataFrame([r for x in parts for r in x])
    T.to_pickle(os.path.join(HERE, 'kanal_wick_dev.pkl'))
    if T.empty: print('keine Trades'); sys.exit()
    d = T.groupby(T.entry_ts.dt.floor('D')).ret.mean()
    print(f"Trades {len(T)} | Ø {T.ret.mean()*100:+.3f} %/Trade | Median {T.ret.median()*100:+.2f} | Treffer {(T.ret>0).mean():.0%} | "
          f"Stops {(T.res=='sl').mean():.1%} | Tagesmittel {d.mean()*100:+.3f} % | Coins {T.coin.nunique()}")
    print(T.groupby(T.entry_ts.dt.year).ret.agg(['size', 'mean']).assign(mean=lambda x: x['mean'] * 100).round(3).to_string())
