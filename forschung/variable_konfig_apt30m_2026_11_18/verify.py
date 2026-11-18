"""Abgleich CUDA-Kernel gegen den Python-Originalcode (plan + signal_exit), je Coin die Live-Config
plus eine abweichende Kombination."""

import math
import sys

import numpy as np
import pandas as pd

from engine import (Engine, ROUND_TRIP_COST_PCT, config_for, enc, logic, read_cache,
                    setup_from_config)

SETUPS = [('APT', '30m'), ('SHIB', '30m'), ('BAT', '1h'), ('DOT', '2h')]


def python_events(H, L, C, config):
    p = logic.strategy_params(config)
    plan = logic._plan_one_direction(H, L, C, p)
    n = len(C)
    out = []
    for i in np.flatnonzero(plan['fill'][:n]):
        limit, sl, tp = plan['limit'][i], plan['sl'][i], plan['tp'][i]
        if plan['instant'][i]:
            ex, price = i, sl
        else:
            ex = -1
            for t in range(i + 1, n):
                sh, th = L[t] <= sl, H[t] >= tp
                if sh or th:
                    ex, price = t, (sl if sh else tp)
                    break
        r = math.nan
        if ex >= 0:
            risk = limit - sl
            r = (price - limit) / risk - abs(limit) * ROUND_TRIP_COST_PCT / risk
        out.append((int(i), int(ex), r))
    return pd.DataFrame(out, columns=['i', 'x', 'r'])


def main():
    bad = 0
    for coin, tf in SETUPS:
        setup = setup_from_config(coin, tf)
        df = read_cache(coin, tf)
        eng = Engine(setup, df, np.zeros(len(df), dtype=np.int16), 1)
        other = {**setup.live, 'pivot_k': 3 if setup.live['pivot_k'] == 5 else 5,
                 'zone_tol_atr': 0.35, 'min_rr': 1.3, 'max_age_mult': 2.0, 'fib_hi': 0.618}
        for params in (setup.live, other):
            combo = eng.combo_index(params)
            cfg = config_for(setup, {k: enc(v) for k, v in params.items()})
            for name, (H, L, C) in eng.dirs.items():
                ref = python_events(H, L, C, cfg)
                got = eng.raw_events(combo, name)
                same = len(ref) == len(got) and (ref['i'].to_numpy() == got['i'].to_numpy()).all() \
                    and (ref['x'].to_numpy() == got['x'].to_numpy()).all()
                dr = np.nanmax(np.abs(ref['r'].to_numpy() - got['r'].to_numpy())) if same and len(ref) else 0.0
                ok = same and dr < 1e-5
                bad += not ok
                print(f'{setup.name} combo {combo} {name}: python {len(ref)} / cuda {len(got)}, '
                      f'max |dR| {dr:.1e} -> {"OK" if ok else "ABWEICHUNG"}', flush=True)
        eng.free()
    print('ALLES GLEICH' if bad == 0 else f'{bad} ABWEICHUNGEN')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
