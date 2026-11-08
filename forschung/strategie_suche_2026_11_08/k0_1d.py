import os, sys
from multiprocessing import Pool
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', '..', 'src'))
import harness as H, konfluenz_k as K
from runde3 import sim_one, leg_ret, stop_ok
from h1_h5 import block_bootstrap_p
from fibot.strategy.confluence_logic import _atr
def job(coin):
    d4 = H._read(os.path.join(H.GEO, f'{coin}-USDT-USDT_4h.csv'))
    g = d4.resample('1D')
    df = g.agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'})
    df = df[g.size() == 6].dropna()
    if len(df) < 260: return []
    o, h, l, c, v = (df[x].values for x in ('open', 'high', 'low', 'close', 'volume'))
    out = []
    for side, (O, Hh, L, C) in ((1, (o, h, l, c)), (-1, (-o, -l, -h, -c))):
        atr = _atr(Hh, L, C, 14); free = 0
        for e in K.touch_events(O, Hh, L, C, v):
            i = e['i']
            if i < free: continue
            ep = min(e['limit'], O[i])
            if not stop_ok(e['limit'], e['sl'], atr[i - 1], ep): continue
            x, j, res = sim_one(O, Hh, L, C, i, ep, e['sl'], e['tp'], i + 1)
            ret = leg_ret(ep, x)
            out.append({'coin': coin, 'side': side, 'entry_ts': df.index[i], 'ret': ret, 'res': res, 'R': ret * abs(ep) / (ep - e['sl']), 'bars': j - i + 1})
            free = j + 1
    return out
if __name__ == '__main__':
    U = H.load_universe('4h'); A, B = H.split_coins(U)
    with Pool(6) as p: parts = p.map(job, list(U))
    T = pd.DataFrame([r for x in parts for r in x]); T.to_pickle(os.path.join(HERE, 'trades_k0_1d.pkl'))
    print(len(T), 'Trades')
    seg = H.segments(T, A, B)
    for k, s in seg.items():
        H.evaluate(s, k)
        if len(s): print(f"    Tagesmittel {s.groupby(pd.to_datetime(s.entry_ts, utc=True).dt.floor('D')).ret.mean().mean()*100:+.3f} %  R {s.R.mean():+.3f}")
    p1 = seg['PRUEF  B bis 14.10.26']
    print('P1 p', round(block_bootstrap_p(p1, n=9999, seed=20261109), 4) if len(p1) else 'nan',
          '| Stress', round((p1.ret - 0.0015 - 0.0001 * np.ceil(p1.bars * 3)).mean() * 100, 3))
