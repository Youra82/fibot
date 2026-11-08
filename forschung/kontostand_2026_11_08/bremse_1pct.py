# Nachtrag: DD-Bremse mit 1 % Basis (User-Wahl 1 %), Pool 38 und Team 17 -- gleiche Rechnung wie pool38.py/live17.py.
import os, sys, runpy
HERE = os.path.dirname(os.path.abspath(__file__))
for name in ('pool38.py', 'live17.py'):
    src = open(os.path.join(HERE, name), encoding='utf-8').read().split('V = [')[0]
    g = {'__file__': os.path.join(HERE, name), '__name__': 'x'}; exec(src, g)
    pd = g['pd']; run = g['run']; P = g['P']
    print(f'\n{name}: {P.cfg.nunique()} Configs')
    for seg, (a, b) in {'2024': ('2024-01-01', '2025-01-01'), '2025': ('2025-01-01', '2026-01-01'), '01.01.-09.05.2026': ('2026-01-01', '2026-05-10'),
                        'OOS 10.05.-08.11.2026': ('2026-05-10', '2026-11-09'), 'ab 15.10.2026': ('2026-10-15', '2026-11-09')}.items():
        a, b = pd.Timestamp(a, tz='UTC'), pd.Timestamp(b, tz='UTC')
        e1, d1, _ = run(P, a, b, .01); e2, d2, _ = run(P, a, b, .01, True)
        print(f'  {seg:22s} 1 % fest: {100*(e1/34-1):+6.0f} % DD {100*d1:4.0f} % | 1 % + Bremse: {100*(e2/34-1):+6.0f} % DD {100*d2:4.0f} %')
