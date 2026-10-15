# fibot/forschung/konfluenz/search.py
# Optimiert die Konfluenz-Strategie je Coin/Timeframe auf In-Sample und bewertet
# unveraendert auf Out-of-Sample. Kandidaten landen in search/candidates/.
# Aufruf aus dem fibot-Ordner:  .venv/Scripts/python.exe forschung/konfluenz/search.py [workers]

import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

COINS = ['AAVE', 'ADA', 'AVAX', 'BNB', 'BTC', 'DOGE', 'ETH', 'LINK', 'SOL', 'XRP',
         'LTC', 'DOT', 'NEAR', 'UNI', 'ATOM', 'TRX', 'FIL', 'BCH', 'ETC', 'XLM']
TFS = ['1h', '2h', '4h', '6h', '1d']
START, OOS_START, END = '2023-04-08', '2026-04-01', '2026-10-15'
# In-Sample-Beginn je Timeframe (kleine TF: kuerzere Historie -> aehnliche Kerzenzahl, aktuelleres Regime)
START_BY_TF = {'5m': '2025-10-01', '15m': '2025-04-01', '30m': '2024-04-01'}
TRIALS = 150
TRIALS_BY_TF = {'5m': 100, '15m': 120}
OUT = os.path.join(HERE, 'search', 'candidates')


def job(coin, tf):
    os.chdir(ROOT)
    import warnings
    warnings.filterwarnings('ignore')
    from fibot.analysis.optimizer import optimize_confluence
    t0 = time.time()
    sym = f'{coin}/USDT:USDT'
    cfg = optimize_confluence(sym, tf, START_BY_TF.get(tf, START), OOS_START, END, capital=100.0,
                              n_trials=TRIALS_BY_TF.get(tf, TRIALS), max_dd=30.0, verbose=False)
    if cfg is not None:
        with open(os.path.join(OUT, f'config_{coin}USDTUSDT_{tf}_fib.json'), 'w') as f:
            json.dump(cfg, f, indent=2)
    return coin, tf, cfg, time.time() - t0


if __name__ == '__main__':
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    # optional: --coins A B C --tfs 1h 2h  (zweite Runde mit weiteren Coins)
    def _arg_list(flag, default):
        if flag not in sys.argv:
            return default
        i = sys.argv.index(flag) + 1
        vals = []
        while i < len(sys.argv) and not sys.argv[i].startswith('--'):
            vals.append(sys.argv[i]); i += 1
        return vals
    COINS = _arg_list('--coins', COINS)
    TFS = _arg_list('--tfs', TFS)
    os.makedirs(OUT, exist_ok=True)
    # langsame Timeframes zuerst einplanen
    jobs = [(c, tf) for tf in TFS for c in COINS
            if not os.path.exists(os.path.join(OUT, f'config_{c}USDTUSDT_{tf}_fib.json'))]
    print(f'{len(jobs)} Jobs, {workers} Prozesse', flush=True)
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(job, c, tf): (c, tf) for c, tf in jobs}
        for fu in as_completed(futs):
            c, tf = futs[fu]
            done += 1
            try:
                _, _, cfg, dt = fu.result()
            except Exception as e:
                print(f'[{done}/{len(jobs)}] {c} {tf} FEHLER {e}', flush=True)
                continue
            if cfg is None:
                print(f'[{done}/{len(jobs)}] {c:<5}{tf:>3}  keine gueltige Config  ({dt:.0f}s)', flush=True)
            else:
                b, o = cfg['_backtest'], cfg['_backtest']['oos']
                print(f'[{done}/{len(jobs)}] {c:<5}{tf:>3}  IS {b["pnl_pct"]:+7.1f}% DD {b["max_drawdown"]:5.1f}% n={b["total_trades"]:>3} | '
                      f'OOS {o["pnl_pct"]:+7.1f}% DD {o["max_drawdown"]:5.1f}% n={o["total_trades"]:>3}  ({dt:.0f}s)', flush=True)
    print('FERTIG', flush=True)
