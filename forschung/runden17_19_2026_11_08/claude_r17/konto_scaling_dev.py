# NUR Entwicklungsdaten (< 10.05.2026): Risiko-Skalierung nach Phasenstaerke fuer P5.
import numpy as np, pandas as pd
import claude_filter_phase as P
from pruefung_r17 import replay, FULL
T = pd.read_pickle(FULL).sort_values('ts').reset_index(drop=True).drop(columns=['per', 'selected'])
E = T[T.eligible & (T.ts < '2026-05-10')].reset_index(drop=True)
tf14 = pd.Series(np.nan, index=E.index)
for _, g in E.groupby('tf'):
    tf14.loc[g.index] = P._global_gate(g, 14, min_n=15)
E['gate'] = tf14.values
m = (E.gate > 0).to_numpy() & (E.stop_atr >= 2).to_numpy()
t = replay(E, m).sort_values('ts')
print('Gate-Werte der genommenen Trades: Median', round(t.gate.median(), 3), 'Anteil > 0.25:', round((t.gate > .25).mean(), 2))
def konto(t, start, end, rfun, lev=10., eq0=34.):
    t = t[(t.ts >= start) & (t.ts < end)]; eq = eq0; peak = eq0; dd = 0.; op = []
    for row in t.itertuples():
        for o in [o for o in op if o[0] <= row.ts]:
            eq += o[2]; op.remove(o); peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
        r = rfun(row.gate); notional = eq * r / (row.risk_pct / 100)
        if sum(o[1] for o in op) + notional > lev * eq: continue
        op.append((row.exit_ts, notional, eq * r * row.net_R))
    for o in sorted(op): eq += o[2]; peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
    return eq, dd
rules = {'fest 1 %': lambda g: .01, 'fest 0,7 %': lambda g: .007, 'skaliert 1 % / 2 % (>0,25 R)': lambda g: .02 if g > .25 else .01,
         'skaliert 0,7 % / 1,4 % (>0,25 R)': lambda g: .014 if g > .25 else .007}
for s, (a, b) in {'2025': ('2025-01-01', '2026-01-01'), '01.01.-09.05.2026': ('2026-01-01', '2026-05-10'), '2024': ('2024-01-01', '2025-01-01')}.items():
    for k, f in rules.items():
        eq, dd = konto(t, pd.Timestamp(a, tz='UTC'), pd.Timestamp(b, tz='UTC'), f)
        print(f'{s:18s} {k:34s} 34 -> {eq:9.2f} ({100*(eq/34-1):+7.1f} %)  MaxDD {100*dd:5.1f} %')
