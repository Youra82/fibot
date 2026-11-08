# Taegliche Anpassung (User-Wunsch "taeglich"): jeden Tag nur Configs handeln, deren abgeschlossene Trades der letzten
# W Tage im Mittel > 0 R lagen (>= 3 Trades). Vergleich: alle Configs und taeglich zufaellig gleich viele Configs
# (200 Ziehungen). Alte Konfluenz-Logik: 407 Configs, Trendfilter (trend_ok), eligible, eine Position je Coin.
import numpy as np, pandas as pd
T = pd.read_pickle('forschung/gewinner_filter_2026_11_08/features.pkl')
T = T[T.eligible & (T.trend_ok == True)].sort_values('ts').reset_index(drop=True)
T['day'] = T.ts.dt.floor('D'); T['known'] = T.exit_ts + T.tf.map(pd.Timedelta)
days = pd.date_range('2025-01-01', '2026-11-08', freq='D', tz='UTC'); cfgs = np.array(sorted(T.cfg.unique()))
K = T.sort_values('known'); kt = K.known.values; kc = K.cfg.values; kr = K.net_R.values
def replay(t):
    busy = {}; keep = []
    for i, r in enumerate(t.itertuples()):
        if r.coin in busy and r.ts <= busy[r.coin]: continue
        busy[r.coin] = r.exit_ts; keep.append(i)
    return t.iloc[keep]
segs = {'2025': ('2025-01-01', '2026-01-01'), '01.01.-09.05.2026': ('2026-01-01', '2026-05-10'), 'OOS 10.05.-08.11.2026': ('2026-05-10', '2026-11-09')}
base = replay(T)
for W in (14, 30):
    sel = {}
    for d in days:
        hi = np.searchsorted(kt, np.datetime64(d.tz_convert(None)), side='right'); lo = np.searchsorted(kt, np.datetime64((d - pd.Timedelta(days=W)).tz_convert(None)), side='left')
        s = pd.DataFrame({'c': kc[lo:hi], 'r': kr[lo:hi]}).groupby('c').r.agg(['size', 'mean'])
        sel[d] = set(s[(s['size'] >= 3) & (s['mean'] > 0)].index)
    m = np.array([c in sel.get(d, set()) for c, d in zip(T.cfg, T.day)])
    chosen = replay(T[m]); rng = np.random.default_rng(1); rnd = {k: [] for k in segs}
    for _ in range(200):
        rs = {d: set(rng.choice(cfgs, len(sel[d]), replace=False)) if len(sel[d]) else set() for d in days}
        rr = replay(T[np.array([c in rs.get(d, set()) for c, d in zip(T.cfg, T.day)])])
        for k, (a, b) in segs.items():
            x = rr[(rr.ts >= a) & (rr.ts < b)]; rnd[k].append(x.net_R.mean())
    print(f'\nFenster {W} Tage (Ø {np.mean([len(v) for v in sel.values()]):.0f} von {len(cfgs)} Configs aktiv je Tag)')
    for k, (a, b) in segs.items():
        c = chosen[(chosen.ts >= a) & (chosen.ts < b)]; al = base[(base.ts >= a) & (base.ts < b)]; r = np.array(rnd[k])
        print(f'  {k:22s} taeglich angepasst: {c.net_R.mean():+.3f} R (n={len(c)}) | alle: {al.net_R.mean():+.3f} (n={len(al)}) | '
              f'zufaellig: {np.nanmean(r):+.3f} | Anteil Zufall >= angepasst: {(r >= c.net_R.mean()).mean():.2f}')
