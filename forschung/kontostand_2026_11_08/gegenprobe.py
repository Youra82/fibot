# Gegenprobe (beschreibend): ist die DD-Bremse besser als einfach weniger festes Risiko?
import os, sys
sys.argv = ['x']; HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, 'kontostand.py'), encoding='utf-8').read().split('T = replay(P)')[0]
exec(src.replace("os.path.dirname(os.path.abspath(__file__))", repr(HERE)))
T = replay(P)
def run_fixed(t, a, b, r, eq0=34.):
    t = t[(t.ts >= a) & (t.ts < b)]; eq = eq0; peak = eq0; dd = 0.; op = []
    for x in t.itertuples():
        for o in [o for o in op if o[0] <= x.ts]: eq += o[2]; op.remove(o); peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
        notional = eq * r / (x.risk_pct / 100)
        if sum(o[1] for o in op) + notional > 10 * eq: continue
        op.append((x.exit, notional, eq * r * x.S_K))
    for o in sorted(op): eq += o[2]; peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
    return eq, dd
for name, (a, b) in {'2024': ('2024-01-01', '2025-01-01'), '2025': ('2025-01-01', '2026-01-01'), '01.01.-09.05.2026': ('2026-01-01', '2026-05-10'), 'OOS 10.05.-08.11.2026': ('2026-05-10', '2026-11-09')}.items():
    a, b = pd.Timestamp(a, tz='UTC'), pd.Timestamp(b, tz='UTC')
    print(f'{name:22s} | ' + ' | '.join(f'{100*r:.1f} % fest: {e:8.2f} (DD {100*d:4.1f} %)' for r in (.005, .003) for e, d in [run_fixed(T, a, b, r)]))
