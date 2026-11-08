# Marktdrift je Segment: Long zufaellig, 6 Kerzen halten (24h), Kosten Taker beidseitig -> Basis fuer Vergleiche
import numpy as np, pandas as pd
from harness import *
U = load_universe('4h'); A, B = split_coins(U); reg = btc_regime()
rng = np.random.default_rng(2); rows = []
for coin, df in U.items():
    c = df.close.values; o = df.open.values; up = at(reg, df.index)
    for i in np.where(rng.random(len(df)) < 0.03)[0]:
        if 30 < i < len(df) - 7:
            r = o[i + 6] / o[i + 1] - 1
            rows.append({'coin': coin, 'entry_ts': df.index[i + 1], 'ret': r - 2 * (TAKER + SLIP), 'regime': up[i]})
D = pd.DataFrame(rows)
for lab, m in (('alle', D.regime == D.regime), ('BTC>SMA200', D.regime == 1), ('BTC<SMA200', D.regime == 0)):
    print('---', lab)
    for k, s in segments(D[m], A, B).items(): evaluate(s, k)
