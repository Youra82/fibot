# Anpassung nach dem eigenen Kontostand (User-Idee), vorab festgelegt, nicht optimiert:
# E1 Kontokurven-Filter: virtuelle Kontokurve (alle Signale, 1 % fest) > ihr 30-Tage-Mittel -> handeln, sonst nicht.
# E2 Drawdown-Bremse: Risiko = 1 % * max(0,25; 1 - DD/30 %), DD = Rueckgang des echten Kontos vom Hoechststand.
# E3 = E1 + E2. Kontrolle 1 % fest. Alte Konfluenz (S_K = heute), Trendfilter, eine Position je Coin, Notional <= 10x.
import os, numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
P = pd.read_pickle(os.path.join(ROOT, 'forschung', 'dynamisches_ziel_2026_11_08', 'pfade.pkl'))
P = P[(P.eligible == True) & (P.trend_ok == True)].dropna(subset=['S_K']).sort_values('ts').reset_index(drop=True)
P['exit'] = pd.to_datetime(P.S_K_exit, utc=True); P['known'] = P.exit + P.tf.map(pd.Timedelta)

def replay(t):
    busy = {}; keep = []
    for i, x in enumerate(t.itertuples()):
        if x.coin in busy and x.ts <= busy[x.coin]: continue
        busy[x.coin] = x.exit; keep.append(i)
    return t.iloc[keep]

def run(t, a, b, filt=False, brake=False, eq0=34.):
    t = t[(t.ts >= a) & (t.ts < b)]
    # virtuelle Kontokurve (1 % fest, alle Signale) fuer E1 -- nur bekannte Ergebnisse
    v = t.sort_values('known'); veq = 1.0; vt = []; vv = []
    for x in v.itertuples(): veq *= (1 + .01 * x.S_K); vt.append(x.known); vv.append(veq)
    vs = pd.Series(vv, index=pd.DatetimeIndex(vt)); vs = vs[~vs.index.duplicated(keep='last')]
    ma = vs.rolling('30D').mean()
    eq = eq0; peak = eq0; dd = 0.; op = []; n = 0
    for x in t.itertuples():
        for o in [o for o in op if o[0] <= x.ts]:
            eq += o[2]; op.remove(o); peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
        if filt:
            pos = vs.index.searchsorted(x.ts, side='right') - 1
            if pos >= 0 and vs.index[pos] >= vs.index[0] + pd.Timedelta(days=30) and vs.iloc[pos] < ma.iloc[pos]: continue
        r = .01
        if brake: r = .01 * max(.25, 1 - (1 - eq / peak) / .30)
        notional = eq * r / (x.risk_pct / 100)
        if sum(o[1] for o in op) + notional > 10 * eq: continue
        op.append((x.exit, notional, eq * r * x.S_K)); n += 1
    for o in sorted(op): eq += o[2]; peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
    return eq, dd, n

T = replay(P)
segs = {'2024': ('2024-01-01', '2025-01-01'), '2025': ('2025-01-01', '2026-01-01'), '01.01.-09.05.2026': ('2026-01-01', '2026-05-10'),
        'OOS 10.05.-08.11.2026': ('2026-05-10', '2026-11-09'), 'ab 15.10.2026': ('2026-10-15', '2026-11-09')}
for name, (a, b) in segs.items():
    a, b = pd.Timestamp(a, tz='UTC'), pd.Timestamp(b, tz='UTC'); out = []
    for lab, f, br in (('Kontrolle 1 %', 0, 0), ('E1 Kurvenfilter', 1, 0), ('E2 DD-Bremse', 0, 1), ('E3 beides', 1, 1)):
        e, d, n = run(T, a, b, f, br); out.append(f'{lab}: {e:8.2f} (DD {100*d:4.1f} %, n={n})')
    print(f'{name:22s} | ' + ' | '.join(out))
