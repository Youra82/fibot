# Ausstiegsregeln aus PREREG.md je gefuellter Order (Kerzenpfad, SL zuerst, Regel wirkt ab Folgekerze).
# Aufruf: python exits.py <idx> <parts>
import json, os, sys
ROOT = r'C:\Users\matol\Desktop\botprojekte\fibot'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'src')); os.chdir(ROOT)
import logging; logging.disable(logging.WARNING)
import numpy as np, pandas as pd
from fibot.analysis.backtester import load_ohlcv
from fibot.strategy.confluence_logic import plan_both, strategy_params

FEE, TODAY = 0.0006, '2026-10-28'
idx, parts = int(sys.argv[1]), int(sys.argv[2])
CFG = 'src/fibot/strategy/configs'
VARIANTS = {'E0': None, 'BE05': ('be', 0.5), 'BE10': ('be', 1.0), 'BE15': ('be', 1.5), 'P10': ('part', 1.0), 'P15': ('part', 1.5)}

def run(H, L, i, n, Lm, SLm, TPm, rule):
    """R (vor Gebuehren) und Ende-Index. None = noch offen."""
    risk = Lm - SLm; rr = (TPm - Lm) / risk
    if L[i] <= SLm:
        return -1.0, i
    stop, part = SLm, 0.0                     # part = bereits gesicherter R-Anteil (Teilschluss)
    size = 1.0
    for k in range(i + 1, n):
        if L[k] <= stop:
            r_stop = (stop - Lm) / risk       # -1 oder 0 (Einstand)
            return part + size * r_stop, k
        if rule and rule[0] == 'part' and size == 1.0 and H[k] >= Lm + rule[1] * risk:
            part, size = 0.5 * rule[1], 0.5
        if H[k] >= TPm:
            return part + size * rr, k
        if rule and H[k] >= Lm + rule[1] * risk:
            stop = max(stop, Lm)              # ab naechster Kerze Einstand
    return None, None

rows = []
for f in sorted(os.listdir(CFG))[idx::parts]:
    cfg = json.load(open(f'{CFG}/{f}')); p = strategy_params(cfg)
    sym, tf = cfg['market']['symbol'], cfg['market']['timeframe']
    t0 = pd.Timestamp(cfg['_backtest']['start_date'], tz='UTC')
    warm = (t0 - pd.Timedelta(tf) * (int(p['window']) + 100)).strftime('%Y-%m-%d')
    df = load_ohlcv(sym, tf, warm, TODAY)
    df = df[df.index + pd.Timedelta(tf) <= pd.Timestamp.now(tz='UTC')]
    h, l = df.high.values.astype(float), df.low.values.astype(float)
    n = len(df)
    lo, sh = plan_both(df, cfg)
    for dname, pl, sgn in (('long', lo, 1), ('short', sh, -1)):
        H, L = (h, l) if sgn == 1 else (-l, -h)
        for i in np.nonzero(pl['fill'][:n])[0]:
            ts = df.index[i]
            if ts < t0: continue
            lim, sl, tp = pl['limit'][i], pl['sl'][i], pl['tp'][i]
            Lm, SLm, TPm = sgn * lim, sgn * sl, sgn * tp
            fee_r = FEE * 2 * abs(lim) / abs(lim - sl)
            row = {'cfg': f[7:-9], 'tf': tf, 'dir': dname, 'ts': ts, 'fee_r': fee_r}
            ok = True
            for name, rule in VARIANTS.items():
                r, k = run(H, L, i, n, Lm, SLm, TPm, rule)
                if r is None: ok = False; break
                row[name] = r - fee_r
            if ok: rows.append(row)
    print(f, len(rows), flush=True)
pd.DataFrame(rows).to_csv(os.path.join(HERE, f'exits_{idx}.csv'), index=False)
