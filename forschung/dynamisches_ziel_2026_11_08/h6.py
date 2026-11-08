# H6 (Nachtrag 3): Segment-Tor je stop_atr-Terzil, 60-Tage-Fenster virtueller Trades, Strukturstop + Strukturziel.
import os, numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
P = pd.read_pickle(os.path.join(HERE, 'pfade.pkl')); P = P[(P.eligible == True) & (P.trend_ok == True)].sort_values('ts').reset_index(drop=True)
LE, CE, OE = (pd.Timestamp(x, tz='UTC') for x in ('2026-01-01', '2026-05-10', '2026-11-09'))
q = P[P.ts < LE].stop_atr.quantile([1/3, 2/3]).values
P['seg'] = np.where(P.stop_atr <= q[0], 'eng', np.where(P.stop_atr <= q[1], 'mittel', 'weit'))
P['known'] = pd.to_datetime(P.S_K_exit, utc=True) + P.tf.map(pd.Timedelta)
gate = np.ones(len(P), bool); val = np.full(len(P), np.nan)
for s, g in P.groupby('seg'):
    k = g.dropna(subset=['S_K']).sort_values('known'); kt = k.known.values; cs = np.r_[0, np.cumsum(k.S_K.values)]
    ts = g.ts.values; hi = np.searchsorted(kt, ts, side='right'); lo = np.searchsorted(kt, ts - np.timedelta64(60, 'D'), side='left')
    n = hi - lo; m = np.where(n > 0, (cs[hi] - cs[lo]) / np.maximum(n, 1), np.nan)
    val[g.index] = m; gate[g.index] = np.where(n >= 30, m > 0, True)
P['gate'] = gate
def ci(s, diff):
    d = pd.DataFrame({'day': s.ts.dt.floor('D').values, 'x': diff}).dropna().groupby('day').x.agg(['sum', 'size'])
    blk = (d.index - d.index[0]).days // 28; g = [d[blk == b] for b in np.unique(blk)]; rng = np.random.default_rng(20261108)
    m = [(lambda z: z['sum'].sum() / z['size'].sum())(pd.concat([g[j] for j in rng.integers(0, len(g), len(g))])) for _ in range(2000)]
    return np.quantile(m, [.025, .975])
def rep(s):
    t = s.assign(ex=pd.to_datetime(s.S_K_exit, utc=True)).dropna(subset=['S_K']); busy = {}; keep = []
    for i, x in enumerate(t.itertuples()):
        if x.coin in busy and x.ts <= busy[x.coin]: continue
        busy[x.coin] = x.ex; keep.append(i)
    return t.iloc[keep].S_K.mean(), len(keep)
for name, m in {'Lernen bis 2025': P.ts < LE, 'Pruefen 01-05/2026': (P.ts >= LE) & (P.ts < CE), 'OOS 10.05.-08.11.2026': (P.ts >= CE) & (P.ts < OE),
                '  davon ab 15.10.': P.ts >= pd.Timestamp('2026-10-15', tz='UTC')}.items():
    s = P[m]; on = s[s.gate]; off = s[~s.gate]
    diff = np.where(s.gate, s.S_K, 0.) - s.S_K.values      # Tor zu = Trade entfaellt (0 R) statt S_K
    lo, hi = ci(s, -np.where(s.gate, 0., s.S_K.values))     # Gewinn durch Tor = -(R der weggelassenen)
    a, na = rep(on); b, nb = rep(s)
    print(f'{name:22s} gehandelt {len(on):5d} Ø {on.S_K.mean():+.3f} | weggelassen {len(off):5d} Ø {off.S_K.mean():+.3f} | '
          f'Summe R mit Tor {on.S_K.sum():+8.1f} vs ohne {s.S_K.sum():+8.1f} (Gewinn je Signal 95 % {lo:+.3f}..{hi:+.3f}) | je Coin {a:+.3f} (n={na}) vs {b:+.3f} (n={nb})')
print(P[P.ts >= CE].groupby('seg').gate.mean().round(2).to_dict(), '<- Anteil offen je Segment im OOS')
