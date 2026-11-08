# Jede gefuellte Order aller 407 Kandidaten einzeln (Regeln: PLAN.md).
# Aufruf aus fibot/: .venv/Scripts/python forschung/untersuchung_2026_11_08/events.py
import glob
import json
import logging
import os
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FIB = os.path.abspath(os.path.join(HERE, '..', '..'))
CAND = os.path.join(FIB, 'forschung', 'konfluenz', 'search', 'candidates')
LIVE = os.path.join(FIB, 'src', 'fibot', 'strategy', 'configs')
sys.path.insert(0, os.path.join(FIB, 'src'))
logging.disable(logging.WARNING)
FEE = 0.0006
OOS, HOLD = pd.Timestamp('2026-04-01', tz='UTC'), pd.Timestamp('2026-10-15', tz='UTC')


def load(sym, tf):
    p = os.path.join(FIB, 'data', 'cache', f"{sym.replace('/', '-').replace(':', '-')}_{tf}.csv")
    df = pd.read_csv(p)
    tcol = 'timestamp' if 'timestamp' in df.columns else df.columns[0]
    df.index = pd.to_datetime(df[tcol], utc=True)
    return df[['open', 'high', 'low', 'close']].astype(float).sort_index()[lambda d: ~d.index.duplicated()]


def job(fname):
    from fibot.strategy import trend_filter
    from fibot.strategy.confluence_logic import plan_both
    cfg = json.load(open(os.path.join(CAND, fname)))
    sym, tf = cfg['market']['symbol'], cfg['market']['timeframe']
    is_start = pd.Timestamp(cfg['_backtest']['start_date'], tz='UTC')
    df = load(sym, tf)
    # Vorlauf fuer Kanal (window) und Trendfilter mitnehmen
    warm = pd.Timedelta(tf) * (int(cfg['strategy'].get('window', 150)) + 4 * 200 + 20)
    df = df[df.index >= is_start - warm]
    n = len(df)
    h, l = df['high'].values, df['low'].values
    lo, sh = plan_both(df, cfg)
    tcfg = trend_filter.DEFAULTS
    try:
        htf = trend_filter.htf_trend(df, tf, tcfg)
        daily = df.resample('1D').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
        dtr = trend_filter.daily_trend(daily, tcfg)
    except Exception:
        htf = dtr = None
    rows = []
    for dname, pl, sgn in (('long', lo, 1), ('short', sh, -1)):
        H, L = (h, l) if sgn == 1 else (-l, -h)
        for i in np.nonzero(pl['fill'][:n])[0]:
            ts = df.index[i]
            if ts < is_start:
                continue
            lim, sl, tp = pl['limit'][i], pl['sl'][i], pl['tp'][i]
            Lm, SLm, TPm = sgn * lim, sgn * sl, sgn * tp
            res, k = None, i
            if L[i] <= SLm:
                res = 'loss'
            else:
                for k in range(i + 1, n):
                    if L[k] <= SLm:
                        res = 'loss'
                        break
                    if H[k] >= TPm:
                        res = 'win'
                        break
            if res is None:
                continue
            R = ((TPm - Lm) / (Lm - SLm) if res == 'win' else -1.0) - FEE * 2 * abs(lim) / abs(lim - sl)
            tf_ok = None if htf is None else trend_filter.allowed(dname, ts, htf, dtr)
            rows.append({'cfg': fname[7:-9], 'coin': sym.split('/')[0], 'tf': tf, 'dir': dname, 'ts': ts,
                         'exit_ts': df.index[k], 'R': R, 'win': res == 'win', 'rr': (TPm - Lm) / (Lm - SLm),
                         'risk_pct': abs(lim - sl) / abs(lim) * 100, 'trend_ok': tf_ok,
                         'per': 'IS' if ts < OOS else ('OOS' if ts < HOLD else 'HOLD')})
    return rows


def main():
    files = sorted(os.path.basename(f) for f in glob.glob(os.path.join(CAND, '*.json')))
    live = {os.path.basename(f) for f in glob.glob(os.path.join(LIVE, '*.json'))}
    # Live-Configs muessen den Kandidaten entsprechen
    diff = [f for f in live if json.load(open(os.path.join(LIVE, f)))['strategy']
            != json.load(open(os.path.join(CAND, f)))['strategy']]
    print(f"{len(files)} Kandidaten, {len(live)} live, abweichende Parameter: {diff}", flush=True)
    with Pool(6) as pool:
        parts = []
        for j, r in enumerate(pool.imap_unordered(job, files, chunksize=2)):
            parts.append(r)
            if j % 25 == 0:
                print(f"  {j + 1}/{len(files)}", flush=True)
    ev = pd.DataFrame([r for p in parts for r in p])
    ev['selected'] = ev.cfg.map(lambda c: f"config_{c}_fib.json" in live)
    ev.to_pickle(os.path.join(HERE, 'events.pkl'))
    print(f"FERTIG {len(ev)} Ereignisse", flush=True)


if __name__ == '__main__':
    main()
