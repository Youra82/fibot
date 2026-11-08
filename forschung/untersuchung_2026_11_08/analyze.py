# Auswertung F1, F2, F3, F5 (Regeln: PLAN.md). Aufruf aus fibot/.
import os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
FIB = os.path.abspath(os.path.join(HERE, '..', '..'))
ev = pd.read_pickle(os.path.join(HERE, 'events.pkl'))
ev['ts'] = pd.to_datetime(ev.ts, utc=True)
FILTER = '--filter' in sys.argv
if FILTER:
    ev = ev[ev.trend_ok == True]
print(f"Ereignisse {len(ev)}  Configs {ev.cfg.nunique()}  {'MIT Trendfilter' if FILTER else 'ohne Trendfilter'}")


def t_over(x):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    return x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 2 else np.nan


per = ev.groupby(['cfg', 'per']).R.agg(['mean', 'count', 'sum']).unstack('per')
sel = ev.groupby('cfg').selected.first()
print("\n=== F1: Methode (alle Kandidaten, Mittel der Config-Mittel) ===")
for p in ('IS', 'OOS', 'HOLD'):
    for name, mask in (('alle 407', sel.index == sel.index), ('38 ausgew.', sel.values), ('369 uebrige', ~sel.values)):
        m = per['mean'][p][mask].dropna()
        cnt = per['count'][p][mask].fillna(0)
        pooled = ev[(ev.per == p) & ev.cfg.isin(sel.index[mask])].R
        print(f"  {p:4s} {name:12s} Configs {len(m):3d}  R/Trade (Config-Mittel) {m.mean():+.3f}  t {t_over(m):+.1f}  "
              f"gepoolt {pooled.mean():+.3f} (n {len(pooled)})  Treffer {ev[(ev.per == p) & ev.cfg.isin(sel.index[mask])].win.mean() * 100:.1f} %")

print("\n=== F2: Vorhersagekraft (Spearman ueber Configs, >=3 Trades im Ziel) ===")
for a, b in (('IS', 'OOS'), ('OOS', 'HOLD'), ('IS', 'HOLD')):
    d = pd.DataFrame({'a': per['mean'][a], 'b': per['mean'][b], 'nb': per['count'][b]}).dropna()
    d = d[d.nb >= 3]
    r, pv = spearmanr(d.a, d.b)
    print(f"  {a:3s} -> {b:4s}  Configs {len(d):3d}  Rho {r:+.3f}  p {pv:.3f}")
# Auswahl-Bedingung nachgebildet: OOS-Summe > 0 -> HOLD?
d = pd.DataFrame({'oos': per['sum']['OOS'], 'hold': per['mean']['HOLD'], 'n': per['count']['HOLD']}).dropna()
for lab, m in (('OOS-Summe > 0', d.oos > 0), ('OOS-Summe <= 0', d.oos <= 0)):
    x = d[m & (d.n >= 1)]
    print(f"  {lab:16s} Configs {len(x):3d}  HOLD R/Trade {x.hold.mean():+.3f}")
# Bootstrap 38 vs uebrige im HOLD
h = per['mean']['HOLD'].dropna()
hs, ho = h[sel.reindex(h.index).values], h[~sel.reindex(h.index).values]
rng = np.random.default_rng(1)
bs = [rng.choice(hs, len(hs)).mean() - rng.choice(ho, len(ho)).mean() for _ in range(5000)]
print(f"  HOLD 38 vs uebrige: {hs.mean():+.3f} vs {ho.mean():+.3f}  Diff {hs.mean() - ho.mean():+.3f}  "
      f"90 % [{np.percentile(bs, 5):+.3f}, {np.percentile(bs, 95):+.3f}]")

print("\n=== F3: Zeitverlauf (gepoolt je Monat) ===")
ev['mon'] = ev.ts.dt.strftime('%Y-%m')
g = ev[ev.ts >= '2025-04-01'].groupby(['mon', 'selected']).R.agg(['mean', 'count']).unstack('selected')
g.columns = [f"{a}_{'38' if b else 'rest'}" for a, b in g.columns]
print(g[['mean_38', 'count_38', 'mean_rest', 'count_rest']].round(3).to_string())
s = ev[ev.selected & (ev.per == 'OOS')]
mon = s.groupby('mon').R.sum().sort_values(ascending=False)
print(f"  38 im OOS: Summe {s.R.sum():+.0f} R, davon bester Monat {mon.index[0]} {mon.iloc[0]:+.0f} R, "
      f"ohne besten Monat {s.R.sum() - mon.iloc[0]:+.0f} R")

print("\n=== F5: Marktphase (BTC Tag) ===")
b = pd.read_csv(os.path.join(FIB, 'data', 'cache', 'BTC-USDT-USDT_1d.csv'))
b.index = pd.to_datetime(b.iloc[:, 0], utc=True); c = b.close.astype(float)
reg = pd.DataFrame({'r30': c.pct_change(30) * 100, 'vol30': np.log(c).diff().rolling(30).std() * np.sqrt(365) * 100})
reg.index = reg.index + pd.Timedelta(days=1)   # bekannt ab Tagesschluss
ev['day'] = ev.ts.dt.floor('D')
ev = ev.join(reg, on='day')
hist = ev[ev.per != 'HOLD'].dropna(subset=['r30'])
q_r = np.percentile(reg.loc['2024-01-01':'2026-10-14'].r30.dropna(), [33.3, 66.7])
q_v = np.percentile(reg.loc['2024-01-01':'2026-10-14'].vol30.dropna(), [33.3, 66.7])
lab = lambda x, q, n: np.where(x < q[0], f'{n}-tief', np.where(x < q[1], f'{n}-mittel', f'{n}-hoch'))
for e in (hist, ev):
    e['phase_r'] = lab(e.r30.values, q_r, 'BTC30d'); e['phase_v'] = lab(e.vol30.values, q_v, 'Vola')
print(f"  Grenzen BTC 30d-Rendite {q_r.round(1)} %, Vola {q_v.round(1)} %")
hold_days = reg.loc['2026-10-15':]
print(f"  HOLD-Lage: BTC 30d-Rendite Mittel {hold_days.r30.mean():+.1f} % (min {hold_days.r30.min():+.1f}), "
      f"Vola {hold_days.vol30.mean():.1f} %")
for col in ('phase_r', 'phase_v'):
    t = hist.groupby([col, 'dir']).R.agg(['mean', 'count']).unstack('dir').round(3)
    print(t.to_string())
hh = ev[ev.per == 'HOLD']
print("  HOLD je Phase/Richtung:")
print(hh.groupby(['phase_r', 'dir']).R.agg(['mean', 'count']).round(3).to_string())
print("  HOLD je Richtung (alle):", hh.groupby('dir').R.agg(['mean', 'count']).round(3).to_dict())
