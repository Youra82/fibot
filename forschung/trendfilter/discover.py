# Suchphase: NUR Trades vor 2026-04-01 (In-Sample). OOS und ab 15.10. bleiben unberuehrt.
import glob, os
import numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__))
ev = pd.concat([pd.read_csv(f, parse_dates=['ts']) for f in glob.glob(os.path.join(HERE, 'events_*.csv'))], ignore_index=True)
ev['ts'] = pd.to_datetime(ev.ts, utc=True)
ev['split'] = np.where(ev.ts < pd.Timestamp('2026-04-01', tz='UTC'), 'DISC',
               np.where(ev.ts < pd.Timestamp('2026-10-15', tz='UTC'), 'VAL', 'HOLD'))
ev.to_csv(os.path.join(HERE, 'events_all.csv'), index=False)
print('Ereignisse je Teil:', ev.split.value_counts().to_dict())
d = ev[ev.split == 'DISC'].copy()
print(f"\nDISC: {len(d)} Trades | WR {d.win.mean()*100:.1f} % | R/Trade {d.R.mean():+.3f} | Summe {d.R.sum():+.0f}R | Sofort-Verluste {d.instant.mean()*100:.1f} %")

feats = ['rr', 'sl_atr', 'width_atr', 'slope_atr', 'imp_atr', 'imp_bars', 'age_bars', 'age_ratio', 'retr', 'dist_atr',
         'atr_pct', 'mom3_atr', 'btc_r30', 'btc_r7', 'coin_r30', 'coin_r7', 'coin_trend', 'hour']
print('\nRangkorrelation mit Gewinn/R (DISC) und Quintile (WR % | R/Trade):')
rows = []
for f in feats:
    x = d[[f, 'R', 'win']].dropna()
    if x[f].nunique() < 3: continue
    rw = spearmanr(x[f], x.win).correlation; rR = spearmanr(x[f], x.R).correlation
    q = pd.qcut(x[f].rank(method='first'), 5, labels=False)
    g = x.groupby(q).agg(wr=('win', 'mean'), r=('R', 'mean'), lo=(f, 'min'), hi=(f, 'max'))
    rows.append((abs(rw), f, rw, rR, g))
for _, f, rw, rR, g in sorted(rows, reverse=True):
    qs = ' | '.join(f"[{a:.3g}..{b:.3g}] {w*100:4.1f}% {r:+.2f}" for a, b, w, r in zip(g.lo, g.hi, g.wr, g.r))
    print(f"{f:<11} rho_win {rw:+.3f} rho_R {rR:+.3f} :: {qs}")
for cat in ('dir', 'tf', 'wday', 'instant'):
    g = d.groupby(cat).agg(n=('R', 'size'), wr=('win', 'mean'), r=('R', 'mean'))
    print(f"\n{cat}:", ' | '.join(f"{k}: n {v.n} WR {v.wr*100:.1f}% R {v.r:+.2f}" for k, v in g.iterrows()))
# Hebel 2: wie weit liefen Verlierer ins Plus?
lz = d[~d.win]
print('\nVerlierer: Anteil mit MFE >= x R vor dem SL:', ' | '.join(f"{x}R {(lz.mfe >= x).mean()*100:.0f}%" for x in (0.25, 0.5, 1, 1.5, 2)))
wz = d[d.win]
print('Gewinner: tiefster Ruecksetzer (MAE) <= -x R:', ' | '.join(f"-{x}R {(wz.mae <= -x).mean()*100:.0f}%" for x in (0.25, 0.5, 0.75, 0.9)))
print('Gewinner mittlere Haltedauer (Kerzen):', round(wz.bars.mean(), 1), '| Verlierer:', round(lz.bars.mean(), 1))
