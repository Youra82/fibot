# Runde 19 (Claude): K1 nur 2h/4h/6h, K2 nur Short, K3 Short + 2h/4h/6h -- auf Entwicklungsdaten < 10.05.2026 gefunden
# (Diagnose nach Richtung/TF), VOR dem OOS eingefroren. Einziger OOS-Test, kumulierte Holm-Korrektur ueber alle bisher
# im OOS getesteten Kandidaten (13 aus Runde 17 + 3 = 16). Bestanden: net_R > 0, >= 100 Trades, Holm-p < 0,05.
import json, sys
import numpy as np, pandas as pd
sys.path.insert(0, r'C:\Users\matol\AppData\Local\Temp\claude\730956f1654d4379\fe70ee45-49b1-4380-8ac8-e10420d5a60b\scratchpad\fib\claude_r17')
from pruefung_r17 import replay, p_boot, stats, holm, T0, FULL  # noqa: E402

S = r'C:\Users\matol\AppData\Local\Temp\claude\730956f1654d4379\fe70ee45-49b1-4380-8ac8-e10420d5a60b\scratchpad\fib'

if __name__ == '__main__':
    T = pd.read_pickle(FULL).sort_values('ts').reset_index(drop=True).drop(columns=['per', 'selected'])
    E = T[T.eligible].reset_index(drop=True)
    hi = E.tf.isin(['2h', '4h', '6h']).to_numpy(); sh = (E['dir'] == 'short').to_numpy()
    masks = {'BASE': np.ones(len(E), bool), 'K1_TF_2h_4h_6h': hi, 'K2_SHORT': sh, 'K3_SHORT_TF_2h+': sh & hi}
    res = {}
    for k, m in masks.items():
        t = replay(E, m); o = t[t.ts >= T0].copy()
        res[k] = stats(o); res[k]['p'] = p_boot(o) if len(o) >= 20 else 1.
        res[k]['pct'] = float((o.net_R * o.risk_pct).mean()) if len(o) else None
    prev = json.load(open(S + r'\claude_r17\oos_ergebnis_r17.json'))
    allp = {k: v['p'] for k, v in prev.items() if k != 'BASE'}
    allp.update({k: res[k]['p'] for k in res if k != 'BASE'})
    names = list(allp); adj = holm(np.array([allp[k] for k in names])); adjd = dict(zip(names, adj))
    for k in res:
        if k == 'BASE': continue
        res[k]['p_holm16'] = float(adjd[k])
        res[k]['bestanden'] = bool(res[k]['n'] >= 100 and res[k]['R'] > 0 and adjd[k] < .05)
    json.dump(res, open(S + r'\claude_r19\oos_ergebnis_r19.json', 'w'), indent=1)
    print(pd.DataFrame(res).T[['n', 'R', 'pct', 'stress_R', 'ohne_top5', 'ab_15_10', 'n_ab_15_10', 'p', 'p_holm16', 'bestanden']].to_string())
