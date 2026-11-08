# Konfluenz mit alternativen Zielen/Stops (Regeln werden in PREREG_KONFLUENZ_RUNDE3.md festgelegt).
# Einstieg wie K0 (Limit im Voraus, Maker). Kosten: Austrittsgebuehr auf Austritts-Notional (Codex-Korrektur).
import os
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'src'))
import harness as H                                    # noqa: E402
import konfluenz_k as K                                # noqa: E402
from fibot.strategy.confluence_logic import _atr       # noqa: E402

MAXBARS = 120


def sim_rule(o, h, l, c, ev, atr, rule):
    """rule: dict(target=('upper'|'R'|'fib'), x=Zahl, min_stop_atr, min_stop_pct, maxbars, filter=callable(e)->bool)."""
    trades, free_from, n = [], 0, len(c)
    for e in ev:
        i = e['i']
        if i < free_from:
            continue
        if rule.get('filter') and not rule['filter'](e, i, o, h, l, c, atr):
            continue
        limit = e['limit']
        a = atr[i - 1]
        stop_dist = max(limit - e['sl'], rule.get('min_stop_atr', 0) * a, rule.get('min_stop_pct', 0) / 100 * abs(limit))
        sl = limit - stop_dist
        if rule['target'] == 'upper':
            tp = e['tp']
        elif rule['target'] == 'R':
            tp = limit + rule['x'] * stop_dist
        elif rule['target'] == 'fib':          # Retracement-Level des Impulses (x = Anteil von B aus), z. B. 0.382
            hi, lo = e['hi'], e['lo']
            tp = hi - rule['x'] * (hi - lo)
        else:
            raise ValueError(rule['target'])
        if tp <= limit:
            continue
        ep = min(limit, o[i])
        mb = rule.get('maxbars', MAXBARS)
        if l[i] <= sl:
            xp, j, res = sl - H.SLIP * abs(sl), i, 'sl'
        else:
            res = None
            for j in range(i + 1, min(n, i + mb)):
                if l[j] <= sl:
                    xp = (o[j] if o[j] < sl else sl); xp -= H.SLIP * abs(xp); res = 'sl'; break
                if h[j] >= tp:
                    xp = max(tp, o[j]) if o[j] > tp else tp; xp -= H.SLIP * abs(xp); res = 'tp'; break
            if res is None:
                j = min(n - 1, i + mb - 1); xp = c[j] - H.SLIP * abs(c[j]); res = 'time'
        gross = (xp - ep) / abs(ep)
        ret = gross - H.MAKER - H.TAKER * abs(xp) / abs(ep)
        trades.append({'i0': i, 'j': j, 'ret': ret, 'res': res, 'R': ret * abs(ep) / stop_dist,
                       'stop_pct': stop_dist / abs(ep) * 100, 'bars': j - i + 1})
        free_from = j + 1
    return trades


def events_with_levels(O, Hh, L, C, v):
    ev = K.touch_events(O, Hh, L, C, v)
    for e in ev:
        e['hi'], e['lo'] = Hh[e['B']], L[e['A']]
    return ev


def run_rules(rules, coins=None, procs=6):
    U = H.load_universe('4h')
    coins = coins or list(U)
    with Pool(procs) as pool:
        parts = pool.starmap(_job, [(coin, rules) for coin in coins], chunksize=2)
    return pd.DataFrame([r for p in parts for r in p])


def _job(coin, rules):
    df = H._read(os.path.join(H.GEO, f'{coin}-USDT-USDT_4h.csv'))
    o, h, l, c, v = (df[x].values for x in ('open', 'high', 'low', 'close', 'volume'))
    out = []
    for side, (O, Hh, L, C) in ((1, (o, h, l, c)), (-1, (-o, -l, -h, -c))):
        ev = events_with_levels(O, Hh, L, C, v)
        atr = _atr(Hh, L, C, 14)
        for name, rule in rules.items():
            if rule.get('side') and rule['side'] != side:
                continue
            for t in sim_rule(O, Hh, L, C, ev, atr, rule):
                out.append({**t, 'coin': coin, 'rule': name, 'side': 'long' if side == 1 else 'short',
                            'entry_ts': df.index[t['i0']], 'exit_ts': df.index[t['j']]})
    return out
