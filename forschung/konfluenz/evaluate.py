# fibot/forschung/konfluenz/evaluate.py -- Auswertung exakt nach PREREG.md
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
files = sys.argv[1:] or ['trades.json']
t = pd.concat([pd.DataFrame(json.load(open(os.path.join(HERE, f)))) for f in files], ignore_index=True)
print('Dateien:', files)
t['fill_ts'] = pd.to_datetime(t['fill_ts'], utc=True)
t = t[t.result != 'open'].copy()
t['net'] = t.r_gross - t.fee_taker
t['net_maker'] = t.r_gross - t.fee_maker
t['oos'] = t.fill_ts >= pd.Timestamp('2026-04-01', tz='UTC')
PRIM = ['4h', '6h', '1d']


def block(d, name):
    if len(d) == 0:
        print(f'{name:<28} keine Trades')
        return
    bs = [np.random.default_rng(i).choice(d.net.values, len(d)).mean() for i in range(2000)]
    lo, hi = np.percentile(bs, [2.5, 97.5])
    print(f'{name:<28} n={len(d):>4}  WR={100 * (d.result == "win").mean():5.1f}%  '
          f'brutto={d.r_gross.mean():+.3f}R  netto={d.net.mean():+.3f}R [{lo:+.3f}, {hi:+.3f}]  '
          f'maker={d.net_maker.mean():+.3f}R  Summe={d.net.sum():+.1f}R')


p = t[t.tf.isin(PRIM)]
print('=== PRIMAER (4h/6h/1d, Taker) ===')
block(p, 'Gesamt')
block(p[~p.oos], 'bis 2026-03-31')
block(p[p.oos], 'OOS ab 2026-04-01')
for tf in PRIM:
    block(p[p.tf == tf], f'  TF {tf}')
block(p[p.dir == 'long'], '  long')
block(p[p.dir == 'short'], '  short')
coin = p.groupby('coin').net.agg(['size', 'sum', 'mean']).round(2)
print('\nje Coin:\n', coin)
print('\nje Jahr:\n', p.groupby(p.fill_ts.dt.year).net.agg(['size', 'mean', 'sum']).round(3))

c1 = len(p) >= 300 and p.net.mean() >= 0.10
c2 = len(p[p.oos]) > 0 and p[p.oos].net.mean() > 0
n_coins = len(coin)
need = 6 if n_coins <= 10 else 12
c3 = (coin['sum'] > 0).sum() >= need
print(f'\nKriterium 1 (>=300 Trades, >= +0,10R): {"ERFUELLT" if c1 else "NICHT erfuellt"}')
print(f'Kriterium 2 (OOS > 0):                 {"ERFUELLT" if c2 else "NICHT erfuellt"}')
print(f'Kriterium 3 (>={need}/{n_coins} Coins positiv):   {"ERFUELLT" if c3 else "NICHT erfuellt"} ({(coin["sum"] > 0).sum()}/{n_coins})')
print('==> BESTANDEN' if (c1 and c2 and c3) else '==> NICHT BESTANDEN')

print('\n=== SEKUNDAER (1h/2h, Taker) ===')
s = t[t.tf.isin(['1h', '2h'])]
block(s, 'Gesamt')
block(s[s.oos], 'OOS')
for tf in ['1h', '2h']:
    block(s[s.tf == tf], f'  TF {tf}')
