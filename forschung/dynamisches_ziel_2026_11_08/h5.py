# H5 (Nachtrag 2): Stop je stop_atr-Terzil dynamisch waehlen (S oder A2), Ziel Struktur.
import os, numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
P = pd.read_pickle(os.path.join(HERE, 'pfade.pkl')); P = P[(P.eligible == True) & (P.trend_ok == True)].sort_values('ts').reset_index(drop=True)
LE, CE, OE = (pd.Timestamp(x, tz='UTC') for x in ('2026-01-01', '2026-05-10', '2026-11-09'))
L = P[P.ts < LE]; q = L.stop_atr.quantile([1/3, 2/3]).values
P['cell'] = np.where(P.stop_atr <= q[0], 'T1', np.where(P.stop_atr <= q[1], 'T2', 'T3'))
tab = {}
for c, g in P[P.ts < LE].groupby('cell'):
    tab[c] = 'A2' if (len(g) >= 100 and g.A2_K.mean() > g.S_K.mean()) else 'S'
    print(f'Lernen {c} (stop_atr <= {dict(zip(["T1","T2"], q.round(2))).get(c, "max")}): S_K {g.S_K.mean():+.3f}  A2_K {g.A2_K.mean():+.3f} -> {tab[c]}')
pick = P.cell.map(tab)
P['dyn'] = np.where(pick == 'A2', P.A2_K, P.S_K); P['dyn_ex'] = np.where(pick == 'A2', P.A2_K_exit, P.S_K_exit)
def ci(s, diff):
    d = pd.DataFrame({'day': s.ts.dt.floor('D').values, 'x': diff}).dropna().groupby('day').x.agg(['sum', 'size'])
    blk = (d.index - d.index[0]).days // 28; g = [d[blk == b] for b in np.unique(blk)]; rng = np.random.default_rng(20261108)
    m = [(lambda z: z['sum'].sum() / z['size'].sum())(pd.concat([g[j] for j in rng.integers(0, len(g), len(g))])) for _ in range(2000)]
    return np.quantile(m, [.025, .975])
def rep(s, r, ex):
    t = s.assign(r=r, ex=pd.to_datetime(pd.Series(ex, index=s.index), utc=True)).dropna(subset=['r']); busy = {}; keep = []
    for i, x in enumerate(t.itertuples()):
        if x.coin in busy and x.ts <= busy[x.coin]: continue
        busy[x.coin] = x.ex; keep.append(i)
    return t.iloc[keep].r.mean(), len(keep)
for name, m in {'Pruefen 01-05/2026': (P.ts >= LE) & (P.ts < CE), 'OOS 10.05.-08.11.2026': (P.ts >= CE) & (P.ts < OE)}.items():
    s = P[m]; lo, hi = ci(s, (s.dyn - s.S_K).values)
    a, na = rep(s, s.dyn.values, s.dyn_ex.values); b, nb = rep(s, s.S_K.values, s.S_K_exit.values)
    print(f'{name}: dynamischer Stop {s.dyn.mean():+.3f} vs S_K {s.S_K.mean():+.3f} | Diff {(s.dyn - s.S_K).mean():+.3f} (95 % {lo:+.3f} .. {hi:+.3f}) | je Coin {a:+.3f} (n={na}) vs {b:+.3f} (n={nb})')
