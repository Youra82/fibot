# Signale der Replay-Daten (wf/data.pkl) auf die Regel H4D1 filtern -> wf_htf/data.pkl
import os, sys, pickle, json, shutil
ROOT = r'C:\Users\matol\Desktop\botprojekte\fibot'
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.join(os.path.dirname(HERE), 'wf')
sys.path.insert(0, os.path.join(ROOT, 'src')); os.chdir(ROOT)
import logging; logging.disable(logging.WARNING)
import numpy as np, pandas as pd
from fibot.analysis.backtester import load_ohlcv

data = pickle.load(open(os.path.join(SRC, 'data.pkl'), 'rb'))
def d1_up(sym):
    for st in ('2022-01-01', '2023-06-01', '2024-06-01', '2025-01-01', '2025-06-01', '2025-10-01'):
        d = load_ohlcv(sym, '1d', st, '2026-10-28')
        if not d.empty: break
    c = d.close.astype(float); u = (c > c.rolling(50).mean()).astype(float); u[c.rolling(50).mean().isna()] = np.nan
    u.index = u.index + pd.Timedelta(days=1); return u
kept = tot = 0
for f, d in data.items():
    df = d['df'].copy(); tf = pd.Timedelta(d['timeframe']); htf = 4 * tf
    hc = df.close.resample(htf, origin='epoch').last().dropna()
    up = (hc > hc.ewm(span=50, adjust=False).mean()).astype(float).iloc[50:]; up.index = up.index + htf
    du = d1_up(d['symbol'])
    sig = df['_sig_dir'].values.copy()
    for i in np.nonzero(sig)[0]:
        ts = df.index[i]
        p1 = up.index.searchsorted(ts, side='right') - 1; p2 = du.index.searchsorted(ts, side='right') - 1
        h4 = up.values[p1] if p1 >= 0 else np.nan; dd = du.values[p2] if p2 >= 0 else np.nan
        want = 1.0 if sig[i] == 1 else 0.0
        tot += 1
        if h4 == want and dd == want: kept += 1
        else: sig[i] = 0
    df['_sig_dir'] = sig
    data[f] = {**d, 'df': df}
pickle.dump(data, open(os.path.join(HERE, 'data.pkl'), 'wb'))
shutil.copy(os.path.join(SRC, 'weeks.json'), os.path.join(HERE, 'weeks.json'))
print(f'Signale behalten: {kept}/{tot} ({kept/tot*100:.0f} %)')
