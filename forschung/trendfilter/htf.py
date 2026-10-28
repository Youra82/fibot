# Test nach PREREG_HTF.md
import json, os, sys
ROOT = r'C:\Users\matol\Desktop\botprojekte\fibot'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'src')); os.chdir(ROOT)
import logging; logging.disable(logging.WARNING)
import numpy as np, pandas as pd
from fibot.analysis.backtester import load_ohlcv

ev = pd.read_csv(os.path.join(HERE, 'events_all.csv')); ev['ts'] = pd.to_datetime(ev.ts, utc=True)
ev['h4'] = np.nan
for cfgname, g in ev.groupby('cfg'):
    cfg = json.load(open(f'src/fibot/strategy/configs/config_{cfgname}_fib.json'))
    sym, tf = cfg['market']['symbol'], cfg['market']['timeframe']
    tfd = pd.Timedelta(tf); htf = 4 * tfd
    start = (g.ts.min() - htf * 120).strftime('%Y-%m-%d')
    df = load_ohlcv(sym, tf, start, '2026-10-28')
    hc = df.close.resample(htf, origin='epoch').last().dropna()
    up = (hc > hc.ewm(span=50, adjust=False).mean()).astype(float)
    up = up.iloc[50:]                                   # EMA eingeschwungen
    up.index = up.index + htf                          # bekannt ab Schluss der HTF-Kerze
    pos = up.index.searchsorted(g.ts, side='right') - 1
    vals = np.where(pos >= 0, up.values[np.clip(pos, 0, None)], np.nan)
    sgn = np.where(g.dir == 'long', 1, -1)
    ev.loc[g.index, 'h4'] = np.where(np.isnan(vals), np.nan, np.where(sgn == 1, vals, 1 - vals))   # 1 = mit dem Trend
ev['d1'] = ev.coin_trend
ev = ev.dropna(subset=['h4', 'd1'])
RULES = {'F0': lambda d: d.index == d.index, 'H4': lambda d: d.h4 == 1, 'D1': lambda d: d.d1 == 1,
         'H4D1': lambda d: (d.h4 == 1) & (d.d1 == 1)}

def stats(d):
    out = {}
    for k, f in RULES.items():
        m = f(d); s = d[m]
        out[k] = dict(n=int(m.sum()), keep=m.mean() * 100, wr=s.win.mean() * 100, r=s.R.mean(), sum=s.R.sum())
    return out
def show(name, st):
    print(f"\n{name}:")
    print(f"{'Regel':<6}{'Trades':>7}{'behalten':>10}{'Treffer %':>10}{'R/Trade':>9}{'Summe R':>9}")
    for k, v in st.items():
        print(f"{k:<6}{v['n']:>7}{v['keep']:>9.0f}%{v['wr']:>10.1f}{v['r']:>+9.3f}{v['sum']:>+9.0f}")

D, V, Hd = (ev[ev.split == s] for s in ('DISC', 'VAL', 'HOLD'))
sd = stats(D); show('DISC (Suche)', sd)
cands = [k for k in ('H4', 'D1', 'H4D1') if sd[k]['keep'] >= 35]
pick = max(cands, key=lambda k: sd[k]['r'])
print('\nAuswahl auf DISC (hoechster R/Trade, >= 35 % behalten):', pick)
sv = stats(V); show('VAL (Pruefung)', sv); show('HOLD (ab 15.10., nur Bericht)', stats(Hd))
# Bootstrap: Differenz R/Trade gefiltert - Basis (VAL)
m = RULES[pick](V).values; r = V.R.values; rng = np.random.default_rng(7); diffs = []
for _ in range(5000):
    ix = rng.integers(0, len(r), len(r)); rr, mm = r[ix], m[ix]
    diffs.append(rr[mm].mean() - rr.mean())
lo, hi = np.percentile(diffs, [5, 95]); dv = sv[pick]['r'] - sv['F0']['r']
c1 = lo > 0; c2 = sv[pick]['wr'] >= sv['F0']['wr'] + 3
print(f"\nVAL {pick}: R/Trade-Differenz {dv:+.3f}, 90%-Intervall [{lo:+.3f}, {hi:+.3f}] -> {c1} | Treffer {sv[pick]['wr']:.1f} >= {sv['F0']['wr']+3:.1f} -> {c2}")
print('ERGEBNIS:', 'BESTANDEN' if c1 and c2 else 'NICHT BESTANDEN')
# Gegenrichtung zur Einordnung
for k in ('H4', 'D1'):
    for nm, d in (('DISC', D), ('VAL', V)):
        g = d[d[k.lower()] == 0]
        print(f"gegen {k} {nm}: n {len(g)} Treffer {g.win.mean()*100:.1f} % R/Trade {g.R.mean():+.3f}")
ev.to_csv(os.path.join(HERE, 'events_htf.csv'), index=False)
