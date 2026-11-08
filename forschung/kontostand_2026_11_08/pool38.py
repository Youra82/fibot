# Pool-Variante: alle 38 Configs, aus denen der Optimizer waehlt -- Risiko-Varianten (Stand 3d3385e, Trendfilter), max 9 Positionen, eine je Coin, Notional <= 10x.
# Varianten vorab festgelegt: LIVE heute (Risiko je Config aus settings.json), 1/0,5/0,3 % fest, 0,5/0,3 % + DD-Bremse,
# 0,5 % + Bremse + Kurvenfilter (E3). Grenze: Configs wurden historisch optimiert und am 31.10. auf 04-10/2026 gewaehlt.
import json, os, numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
import glob
LIVE = {}
for f in glob.glob(os.path.join(ROOT, 'src', 'fibot', 'strategy', 'configs', '*.json')):
    c = json.load(open(f)); LIVE[os.path.basename(f)[7:-9]] = c['risk']['risk_per_entry_pct'] / 100
P = pd.read_pickle(os.path.join(ROOT, 'forschung', 'dynamisches_ziel_2026_11_08', 'pfade.pkl'))
P = P[P.cfg.isin(LIVE) & (P.eligible == True) & (P.trend_ok == True)].dropna(subset=['S_K']).sort_values('ts').reset_index(drop=True)
P['exit'] = pd.to_datetime(P.S_K_exit, utc=True); P['known'] = P.exit + P.tf.map(pd.Timedelta)

def run(t, a, b, risk, brake=False, filt=False, eq0=34., maxpos=9):
    t = t[(t.ts >= a) & (t.ts < b)]
    v = t.sort_values('known'); veq = 1.; vt = []; vv = []
    for x in v.itertuples(): veq *= 1 + .01 * x.S_K; vt.append(x.known); vv.append(veq)
    vs = pd.Series(vv, index=pd.DatetimeIndex(vt)); vs = vs[~vs.index.duplicated(keep='last')]; ma = vs.rolling('30D').mean()
    eq = eq0; peak = eq0; dd = 0.; op = []; busy = {}; n = 0
    for x in t.itertuples():
        for o in [o for o in op if o[0] <= x.ts]:
            eq += o[2]; op.remove(o); peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
        if x.coin in busy and x.ts <= busy[x.coin]: continue
        if len(op) >= maxpos: continue
        if filt:
            p = vs.index.searchsorted(x.ts, side='right') - 1
            if p >= 0 and vs.index[p] >= vs.index[0] + pd.Timedelta(days=30) and vs.iloc[p] < ma.iloc[p]: continue
        r = LIVE[x.cfg] if risk == 'live' else risk
        if brake: r *= max(.25, 1 - (1 - eq / peak) / .30)
        notional = eq * r / (x.risk_pct / 100)
        if sum(o[1] for o in op) + notional > 10 * eq: continue
        op.append((x.exit, notional, eq * r * x.S_K)); busy[x.coin] = x.exit; n += 1
    for o in sorted(op): eq += o[2]; peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
    return eq, dd, n

V = [('Config-Risiko (1-3 %)', 'live', 0, 0), ('1 % fest', .01, 0, 0), ('0,5 % fest', .005, 0, 0), ('0,3 % fest', .003, 0, 0),
     ('0,5 % + Bremse', .005, 1, 0), ('0,3 % + Bremse', .003, 1, 0), ('0,5 % + Bremse + Filter', .005, 1, 1)]
segs = {'2024': ('2024-01-01', '2025-01-01'), '2025': ('2025-01-01', '2026-01-01'), '01.01.-09.05.2026': ('2026-01-01', '2026-05-10'),
        'OOS 10.05.-08.11.2026': ('2026-05-10', '2026-11-09'), 'ab 15.10.2026': ('2026-10-15', '2026-11-09')}
rows = []
for seg, (a, b) in segs.items():
    a, b = pd.Timestamp(a, tz='UTC'), pd.Timestamp(b, tz='UTC')
    for lab, r, br, f in V:
        e, d, n = run(P, a, b, r, br, f); rows.append(dict(Zeitraum=seg, Variante=lab, Ende=round(e, 2), Rendite=f'{100*(e/34-1):+.0f} %', DD=f'{100*d:.0f} %', Trades=n))
R = pd.DataFrame(rows)
print(f'{P.cfg.nunique()} Configs, {len(P)} Signale')
for seg in segs: print(f'\n{seg}'); print(R[R.Zeitraum == seg].drop(columns='Zeitraum').to_string(index=False))
