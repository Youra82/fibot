# Wochenauswahl wie der Live-Optimizer (show_results Modus 3, --from oos, objective pnl, MaxDD 30, ein TF je Coin),
# aber nur mit Kerzen bis zum Auswahltag. Aufruf: python select_weeks.py <idx> <n_parts>
import json, os, sys, time, pickle
ROOT = r'C:\Users\matol\Desktop\botprojekte\fibot'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'src')); os.chdir(ROOT)
import logging; logging.disable(logging.WARNING)
import contextlib, io
import pandas as pd
from fibot.analysis.portfolio_simulator import run_portfolio_simulation

CAP, MAXDD = 100.0, 30.0
data = pickle.load(open(os.path.join(HERE, 'data.pkl'), 'rb'))     # {fname: {symbol, timeframe, df, config}}
weeks = json.load(open(os.path.join(HERE, 'weeks.json')))
idx, parts = int(sys.argv[1]), int(sys.argv[2])
mine = [w for i, w in enumerate(weeks) if i % parts == idx]

def sim(files, cut):
    sd = {}
    for f in files:
        d = data[f]
        sd[f] = {**d, 'df': d['df'][d['df'].index < cut]}
    with contextlib.redirect_stdout(io.StringIO()):
        return run_portfolio_simulation(CAP, sd, '', '')

out = {}
for w in mine:
    t0 = time.time(); cut = pd.Timestamp(w)
    cands = []
    for f in data:
        df = data[f]['df']
        if (df[df.index < cut]['_sig_dir'] != 0).sum() == 0:
            continue
        r = sim([f], cut)
        if r and not r.get('liquidation_date') and r['max_drawdown_pct'] <= MAXDD:
            cands.append((r['total_pnl_pct'], f))
    team, best = [], None
    if cands:
        cands.sort(reverse=True)
        best_pnl, f0 = cands[0]
        team = [f0]; coins = {data[f0]['symbol'].split('/')[0]}
        rest = [f for _, f in cands[1:]]
        while True:
            add, add_pnl = None, best_pnl
            for f in rest:
                if data[f]['symbol'].split('/')[0] in coins:
                    continue
                r = sim(team + [f], cut)
                if not r or r.get('liquidation_date') or r['max_drawdown_pct'] > MAXDD:
                    continue
                if r['total_pnl_pct'] > add_pnl:
                    add, add_pnl = f, r['total_pnl_pct']
            if add is None:
                break
            team.append(add); coins.add(data[add]['symbol'].split('/')[0]); rest.remove(add); best_pnl = add_pnl
        best = best_pnl
    out[w] = {'team': team, 'sel_pnl': best, 'n_cands': len(cands)}
    print(f'{w[:10]}: {len(team)} Strategien aus {len(cands)} Kandidaten ({time.time() - t0:.0f}s)', flush=True)
    json.dump(out, open(os.path.join(HERE, f'sel_{idx}.json'), 'w'))
