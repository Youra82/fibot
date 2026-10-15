# fibot/forschung/konfluenz/run_test.py
# Fuehrt den vorregistrierten Test (PREREG.md) aus und speichert alle Trades.
# Aufruf aus dem fibot-Ordner:  .venv/Scripts/python.exe forschung/konfluenz/run_test.py

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))
os.chdir(ROOT)

import pandas as pd

from fibot.analysis.backtester import load_ohlcv
from fibot.strategy.confluence_logic import run_confluence, V2

COINS = ['AAVE', 'ADA', 'AVAX', 'BNB', 'BTC', 'DOGE', 'ETH', 'LINK', 'SOL', 'XRP']
EXTRA = ['LTC', 'DOT', 'NEAR', 'UNI', 'ATOM', 'TRX', 'FIL', 'BCH', 'ETC', 'XLM']   # PREREG Nachtrag v2
VERSION = sys.argv[1] if len(sys.argv) > 1 else 'v1'
PARAMS = V2 if VERSION == 'v2' else None
if 'extra' in sys.argv:
    COINS = EXTRA
TFS = ['4h', '6h', '1d', '1h', '2h'] if 'primary' not in sys.argv else ['4h', '6h', '1d']
OUTFILE = os.path.join(HERE, 'trades.json' if VERSION == 'v1' else f"trades_{VERSION}{'_extra' if 'extra' in sys.argv else ''}.json")
START, END = '2023-04-08', '2026-10-15'
TAKER, MAKER = 0.0006, 0.0002

out = []
for tf in TFS:
    for coin in COINS:
        t0 = time.time()
        df = load_ohlcv(f'{coin}/USDT:USDT', tf, START, END)
        trades = run_confluence(df, PARAMS)
        for t in trades:
            risk = abs(t.entry - t.sl)
            fee_taker = (2 * TAKER * t.entry) / risk
            exit_fee = MAKER if t.result == 'win' else TAKER
            fee_maker = ((MAKER + exit_fee) * t.entry) / risk
            ch = t.channel
            out.append({
                'coin': coin, 'tf': tf, 'dir': t.direction, 'result': t.result,
                'fill_ts': str(df.index[t.fill_pos]), 'exit_ts': str(df.index[t.exit_pos]),
                'entry': t.entry, 'sl': t.sl, 'tp': t.tp, 'exit': t.exit,
                'r_gross': t.r_gross, 'fee_taker': fee_taker, 'fee_maker': fee_maker,
                'a_ts': str(df.index[t.a_pos]), 'b_ts': str(df.index[t.b_pos]),
                'ch_a_ts': str(df.index[ch.a_pos]), 'ch_slope': ch.slope, 'ch_icpt': ch.intercept,
                'ch_width': ch.width, 'ch_touches': ch.touches, 'fill_pos': t.fill_pos, 'ch_a_pos': ch.a_pos,
                'mirrored': t.direction == 'short', **{k: v for k, v in t.meta.items() if k != 'mirrored'},
            })
        print(f'{tf:>3} {coin:<5} Kerzen {len(df):>6}  Trades {len(trades):>3}  {time.time() - t0:5.1f}s', flush=True)
        json.dump(out, open(OUTFILE, 'w'))
print('FERTIG', len(out))
