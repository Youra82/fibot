# Kelly-Sizing (Video "The Math Every Trader Gets Wrong") fuer die alte Kanal-Konfluenz -- vorab festgelegt:
# Kelly je Config nur aus Trades < 10.05.2026 (trend_ok, eligible): f = W - (1-W)/b, b = Ø Gewinn-R / Ø Verlust-R.
# Kandidat: halbes Kelly, Deckel 2 %, f<=0 oder n<20 -> kein Kapital. Kontrolle: fest 1 % fuer alle Configs.
# Konto 34 USDT, eine Position je Coin (Replay), Summe Notional <= 10x Konto, OOS 10.05.-08.11.2026, einmaliger Blick.
import numpy as np, pandas as pd
T = pd.read_pickle('forschung/gewinner_filter_2026_11_08/features.pkl')
T = T[T.eligible & (T.trend_ok == True)].sort_values('ts').reset_index(drop=True)
T0 = pd.Timestamp('2026-05-10', tz='UTC')
dev = T[T.exit_ts < T0]
k = {}
for cfg, g in dev.groupby('cfg'):
    w, l = g[g.net_R > 0], g[g.net_R <= 0]
    if len(g) < 20 or not len(w) or not len(l): k[cfg] = 0.; continue
    W = len(w) / len(g); b = w.net_R.mean() / abs(l.net_R.mean()); k[cfg] = W - (1 - W) / b
T['kelly'] = T.cfg.map(k).fillna(0.)
def replay(t):
    busy = {}; keep = []
    for i, r in enumerate(t.itertuples()):
        if r.coin in busy and r.ts <= busy[r.coin]: continue
        busy[r.coin] = r.exit_ts; keep.append(i)
    return t.iloc[keep]
def konto(t, rfun, a, b, eq0=34., lev=10.):
    t = t[(t.ts >= a) & (t.ts < b)]; eq = eq0; peak = eq0; dd = 0.; op = []; n = 0
    for r in t.itertuples():
        for o in [o for o in op if o[0] <= r.ts]:
            eq += o[2]; op.remove(o); peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
        f = rfun(r)
        if f <= 0: continue
        notional = eq * f / (r.risk_pct / 100)
        if sum(o[1] for o in op) + notional > lev * eq: continue
        op.append((r.exit_ts, notional, eq * f * r.net_R)); n += 1
    for o in sorted(op): eq += o[2]; peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
    return eq, dd, n
ctrl = replay(T); kel = replay(T[T.kelly > 0])
print(f'Configs mit Kelly>0: {sum(v > 0 for v in k.values())} von {len(k)} | Median halbes Kelly {np.median([min(v/2,.02) for v in k.values() if v>0]):.2%}')
for name, (a, b) in {'Entwicklung 2025': ('2025-01-01', '2026-01-01'), 'Entwicklung 01.01.-09.05.2026': ('2026-01-01', '2026-05-10'), 'OOS 26W': ('2026-05-10', '2026-11-09')}.items():
    a, b = pd.Timestamp(a, tz='UTC'), pd.Timestamp(b, tz='UTC')
    e1, d1, n1 = konto(ctrl, lambda r: .01, a, b); e2, d2, n2 = konto(kel, lambda r: min(r.kelly / 2, .02), a, b)
    o1 = ctrl[(ctrl.ts >= a) & (ctrl.ts < b)].net_R.mean(); o2 = kel[(kel.ts >= a) & (kel.ts < b)].net_R.mean()
    print(f'{name:30s} Kontrolle 1 %: 34->{e1:9.2f} DD {100*d1:5.1f} % n={n1:5d} R {o1:+.3f} | halbes Kelly: 34->{e2:9.2f} DD {100*d2:5.1f} % n={n2:5d} R {o2:+.3f}')
