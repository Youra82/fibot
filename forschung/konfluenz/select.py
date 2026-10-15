# fibot/forschung/konfluenz/select.py
# Waehlt aus search/candidates/ die Configs nach den vorab festgelegten Kriterien
# und kopiert die besten 20 nach src/fibot/strategy/configs/ (Aufruf mit --write).
#
# Kriterien (festgelegt vor Ende des Suchlaufs, 15.10.2026):
#   OOS-PnL >= 10 %, OOS-MaxDD <= 30 %, OOS-Trades >= 10, In-Sample-PnL > 0
#   (In-Sample-Mindesttrades und DD <= 30 % erzwingt bereits der Optimizer)
#   Rangfolge: OOS-Calmar = OOS-PnL / max(OOS-DD, 5)

import glob
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
CAND = os.path.join(HERE, 'search', 'candidates')
CONFIGS = os.path.join(ROOT, 'src', 'fibot', 'strategy', 'configs')
ARCHIVE = os.path.join(ROOT, 'src', 'fibot', 'strategy', 'configs_alt_fibo')
N_PICK = 20

rows = []
for path in sorted(glob.glob(os.path.join(CAND, 'config_*.json'))):
    cfg = json.load(open(path))
    b = cfg['_backtest']
    o = b['oos']
    rows.append({
        'file': os.path.basename(path), 'is_pnl': b['pnl_pct'], 'is_dd': b['max_drawdown'],
        'is_n': b['total_trades'], 'oos_pnl': o['pnl_pct'], 'oos_dd': o['max_drawdown'],
        'oos_n': o['total_trades'], 'oos_wr': o['win_rate'],
        'calmar': o['pnl_pct'] / max(o['max_drawdown'], 5.0),
    })

ok = [r for r in rows if r['oos_pnl'] >= 10 and r['oos_dd'] <= 30 and r['oos_n'] >= 10 and r['is_pnl'] > 0]
ok.sort(key=lambda r: r['calmar'], reverse=True)
pick = ok[:N_PICK]

print(f"Kandidaten mit gueltiger Config: {len(rows)} | erfuellen Kriterien: {len(ok)} | ausgewaehlt: {len(pick)}\n")
print(f"{'Config':<36} {'IS PnL':>8} {'IS DD':>6} {'IS n':>5} | {'OOS PnL':>8} {'OOS DD':>7} {'OOS n':>6} {'WR':>5} {'Calmar':>7}")
for r in sorted(rows, key=lambda r: r['calmar'], reverse=True):
    mark = '*' if r in pick else ' '
    print(f"{mark}{r['file'][7:-9]:<35} {r['is_pnl']:>+7.1f}% {r['is_dd']:>5.1f}% {r['is_n']:>5} | "
          f"{r['oos_pnl']:>+7.1f}% {r['oos_dd']:>6.1f}% {r['oos_n']:>6} {r['oos_wr']:>4.0f}% {r['calmar']:>7.2f}")

if '--write' in sys.argv and pick:
    os.makedirs(ARCHIVE, exist_ok=True)
    moved = 0
    for f in glob.glob(os.path.join(CONFIGS, 'config_*.json')):
        c = json.load(open(f))
        if c.get('strategy', {}).get('type') != 'confluence':
            shutil.move(f, os.path.join(ARCHIVE, os.path.basename(f)))
            moved += 1
    for r in pick:
        shutil.copy2(os.path.join(CAND, r['file']), os.path.join(CONFIGS, r['file']))
    print(f"\n{moved} alte Fibo-Configs nach configs_alt_fibo/ verschoben, {len(pick)} Konfluenz-Configs geschrieben.")
