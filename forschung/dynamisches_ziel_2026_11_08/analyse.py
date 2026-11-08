# Auswertung nach PREREG.md: Nachschlagetabelle "bestes Ziel je Zelle" aus dem Lernzeitraum, getestet in Pruefen und OOS.
import os
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
P = pd.read_pickle(os.path.join(HERE, 'pfade.pkl'))
P = P[(P.eligible == True) & (P.trend_ok == True)].sort_values('ts').reset_index(drop=True)
LEARN_END, CHK_END, OOS_END = (pd.Timestamp(x, tz='UTC') for x in ('2026-01-01', '2026-05-10', '2026-11-09'))
TG = ['R10', 'R15', 'R20', 'R30', 'K']
P['tfgrp'] = np.where(P.tf.isin(['15m', '30m']), 'kurz', 'lang')
learn = P[P.ts < LEARN_END]


def terz(col):
    q = learn[col].quantile([1 / 3, 2 / 3]).values
    return np.where(P[col] <= q[0], 'T1', np.where(P[col] <= q[1], 'T2', 'T3'))


CELLS = {'H1_atr_rank': terz('atr_rank'), 'H2_impuls': terz('impuls_atr'), 'H3_stop_atr': terz('stop_atr')}
CELLS['H4_kombi'] = P.tfgrp + '|' + P['dir'] + '|' + CELLS['H1_atr_rank']


def block_ci(day, diff, n=2000):
    d = pd.DataFrame({'day': day, 'x': diff}).dropna().groupby('day').x.agg(['sum', 'size'])
    if len(d) < 30: return (np.nan, np.nan)
    blk = (d.index - d.index[0]).days // 28; g = [d[blk == b] for b in np.unique(blk)]
    rng = np.random.default_rng(20261108); m = []
    for _ in range(n):
        s = pd.concat([g[j] for j in rng.integers(0, len(g), len(g))]); m.append(s['sum'].sum() / s['size'].sum())
    return tuple(np.quantile(m, [.025, .975]))


def replay_mean(rcol_values, exits, seg):
    t = seg.assign(r=rcol_values, ex=pd.to_datetime(pd.Series(exits, index=seg.index), utc=True)).dropna(subset=['r']); busy = {}; keep = []
    for i, x in enumerate(t.itertuples()):
        if x.coin in busy and x.ts <= busy[x.coin]: continue
        busy[x.coin] = x.ex; keep.append(i)
    return t.iloc[keep].r.mean(), len(keep)


segs = {'Lernen bis 2025': P.ts < LEARN_END, 'Pruefen 01-05/2026': (P.ts >= LEARN_END) & (P.ts < CHK_END),
        'OOS 10.05.-08.11.2026': (P.ts >= CHK_END) & (P.ts < OOS_END)}
print(f'Einstiege mit Trendfilter: {len(P)} (Lernen {len(learn)})')
for stop in ('S', 'A2'):
    lm = {t: learn[f'{stop}_{t}'].mean() for t in TG}
    fixed = max(lm, key=lm.get)
    print(f'\n=== Stop {stop}: Lernmittel je Ziel ' + ', '.join(f'{t} {v:+.3f}' for t, v in lm.items()) + f' -> festes bestes Ziel {fixed}')
    for seg, m in segs.items():
        s = P[m]; print(f'  {seg:24s} n={len(s):5d} | ' + ' '.join(f'{t} {s[f"{stop}_{t}"].mean():+.3f}' for t in TG))
    for hname, cell in CELLS.items():
        P['_c'] = cell; L = P[P.ts < LEARN_END]
        table = {}
        for c, g in L.groupby('_c'):
            mm = {t: g[f'{stop}_{t}'].mean() for t in TG}
            table[c] = max(mm, key=mm.get) if len(g) >= 100 else 'K'
        choice = P._c.map(table).fillna('K')
        dyn = np.array([P.at[i, f'{stop}_{t}'] for i, t in zip(P.index, choice)])
        dyn_ex = np.array([P.at[i, f'{stop}_{t}_exit'] for i, t in zip(P.index, choice)], dtype=object)
        print(f'  {hname}: Tabelle {table}')
        for seg, m in segs.items():
            if seg.startswith('Lernen'): continue
            s = P[m]; d = dyn[m.values]
            for ref in (fixed, 'K'):
                diff = d - s[f'{stop}_{ref}'].values; lo, hi = block_ci(s.ts.dt.floor('D').values, diff)
                print(f'     {seg:22s} dynamisch {np.nanmean(d):+.3f} vs {ref:3s} {s[f"{stop}_{ref}"].mean():+.3f} | '
                      f'Differenz {np.nanmean(diff):+.3f} (95 % {lo:+.3f} .. {hi:+.3f})')
            rm, rn = replay_mean(d, dyn_ex[m.values], s)
            km, kn = replay_mean(s[f'{stop}_K'].values, s[f'{stop}_K_exit'].values, s)
            print(f'     {"":22s} eine Position je Coin: dynamisch {rm:+.3f} (n={rn}) vs K {km:+.3f} (n={kn})')
