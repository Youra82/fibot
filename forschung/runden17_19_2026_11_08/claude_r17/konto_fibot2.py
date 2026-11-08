# Kontorechnung fibot 2.0 (eingefrorene Regeln P4 / P5 aus Runde 17, KEINE neue Auswahl):
# 34 USDT Start, Risiko r je Trade (bis Stop, net_R enthaelt Kosten), Notional = Konto*r/risk_pct,
# Summe Notional offener Positionen <= LEV * Konto (sonst Trade ausgelassen), eine Position je Coin (replay).
import sys
import numpy as np, pandas as pd
sys.path.insert(0, r'C:\Users\matol\AppData\Local\Temp\claude\730956f1654d4379\fe70ee45-49b1-4380-8ac8-e10420d5a60b\scratchpad\fib\claude_r17')
import claude_filter_phase as P
from pruefung_r17 import replay, FULL

T = pd.read_pickle(FULL).sort_values('ts').reset_index(drop=True).drop(columns=['per', 'selected'])
E = T[T.eligible].reset_index(drop=True)
idx, M = P.masks_phase(E)
M = {'BASE (heutige Logik, alle 407)': np.ones(len(E), bool), 'P5 Phasentor je TF + Stop>=2ATR': M['P5_TF14_STOP2'],
     'P4 Phasentor je TF': M['P4_TF14']}


def konto(t, start, end, r=.01, lev=10., eq0=34.):
    t = t[(t.ts >= start) & (t.ts < end)].sort_values('ts')
    eq = eq0; peak = eq0; dd = 0.; open_ = []      # (exit_ts, notional, pnl)
    taken = 0
    for row in t.itertuples():
        for o in [o for o in open_ if o[0] <= row.ts]:
            eq += o[2]; open_.remove(o); peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
        if eq <= 0: break
        notional = eq * r / (row.risk_pct / 100)
        if sum(o[1] for o in open_) + notional > lev * eq: continue
        open_.append((row.exit_ts, notional, eq * r * row.net_R)); taken += 1
    for o in sorted(open_):
        eq += o[2]; peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
    return eq, dd, taken


segs = {'Entwicklung 08.04.2023-09.05.2026': ('2023-04-01', '2026-05-10'), '  davon 2025': ('2025-01-01', '2026-01-01'),
        '  davon 01.01.-09.05.2026': ('2026-01-01', '2026-05-10'), 'OOS 26W 10.05.-08.11.2026': ('2026-05-10', '2026-11-09')}
for name, m in M.items():
    t = replay(E, m)
    print(name)
    for s, (a, b) in segs.items():
        eq, dd, n = konto(t, pd.Timestamp(a, tz='UTC'), pd.Timestamp(b, tz='UTC'))
        print(f'   {s:34s} 34 -> {eq:10.2f} USDT ({100 * (eq / 34 - 1):+8.1f} %)  MaxDD {100 * dd:5.1f} %  Trades {n}')
