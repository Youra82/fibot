import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import json
import numpy as np
from fibot.analysis.backtester import run_backtest, load_ohlcv
from fibot.strategy.fibonacci_logic import precompute_indicators, precompute_all_signals
from fibot.analysis.portfolio_simulator import run_portfolio_simulation, FEE_PCT

cfg_path = os.path.join(os.path.dirname(__file__), 'src/fibot/strategy/configs/config_AAVEUSDTUSDT_30m_fib.json')
with open(cfg_path) as f:
    config = json.load(f)

start_date, end_date, capital = '2025-03-01', '2026-03-22', 25.0
symbol, timeframe = 'AAVE/USDT:USDT', '30m'

df = load_ohlcv(symbol, timeframe, start_date, end_date)
print(f"Kerzen: {len(df)}")

df = precompute_indicators(df, config)
df = precompute_all_signals(df, config)

sig = df['_sig_dir'].values
print(f"_sig_dir dtype: {df['_sig_dir'].dtype}")
print(f"Signale: {(sig != 0).sum()} (long={(sig==1).sum()}, short={(sig==2).sum()})")

# Backtester
bt = run_backtest(df, config, capital, symbol, timeframe)
print(f"\nBacktester  : {bt.end_capital:.2f} USDT | Trades={bt.total_trades} | WR={bt.win_rate:.1f}% | DD={bt.max_drawdown_pct:.2f}%")

# Portfolio-Sim mit AAVE allein — mit Debug
risk    = config.get('risk', {})
lev     = max(1, int(risk.get('leverage', 3)))
rp      = risk.get('risk_per_entry_pct', 0.5) / 100
MIN_NOT = 5.0

equity = capital
trades_opened = 0
skipped_min_not = 0
skipped_margin  = 0
skipped_sig0    = 0
open_pos = {}
trade_results = []

sorted_ts = sorted(df.index)
for ts in sorted_ts:
    # A) Schließen
    for fname in list(open_pos.keys()):
        pos = open_pos[fname]
        if ts <= pos['entry_ts']:
            continue
        candle = df.loc[ts]
        exit_p = None
        if pos['direction'] == 'long':
            if candle['low'] <= pos['sl']:   exit_p = pos['sl']
            elif candle['high'] >= pos['tp']: exit_p = pos['tp']
        else:
            if candle['high'] >= pos['sl']:  exit_p = pos['sl']
            elif candle['low'] <= pos['tp']: exit_p = pos['tp']
        if exit_p:
            if pos['direction'] == 'long':
                raw = pos['notional'] * (exit_p - pos['entry']) / pos['entry'] * lev
            else:
                raw = pos['notional'] * (pos['entry'] - exit_p) / pos['entry'] * lev
            fees = pos['notional'] * FEE_PCT * 2
            equity += raw - fees
            trade_results.append(raw - fees)
            del open_pos[fname]

    # B) Öffnen
    if equity <= 0:
        break
    row = df.loc[ts]
    sd = row.get('_sig_dir', 0)
    if not sd:
        skipped_sig0 += 1
        continue
    if 'aave' not in open_pos:
        sig_dir = 'long' if sd == 1 else 'short'
        entry = float(row['_sig_entry'])
        sl    = float(row['_sig_sl'])
        tp    = float(row['_sig_tp1'])
        if np.isnan(entry) or entry <= 0 or np.isnan(sl) or np.isnan(tp):
            continue
        sl_pct = abs(entry - sl) / entry
        if sl_pct <= 0:
            continue
        notional = (equity * rp) / sl_pct
        margin   = notional / lev
        if notional < MIN_NOT:
            skipped_min_not += 1
            continue
        used = sum(p['margin'] for p in open_pos.values())
        if used + margin > equity:
            skipped_margin += 1
            continue
        open_pos['aave'] = {'direction': sig_dir, 'entry': entry, 'sl': sl,
                             'tp': tp, 'notional': notional, 'margin': margin, 'entry_ts': ts}
        trades_opened += 1

wins = sum(1 for t in trade_results if t > 0)
wr   = wins / len(trade_results) * 100 if trade_results else 0
print(f"Manual-Sim  : {equity:.2f} USDT | Trades={len(trade_results)} | WR={wr:.1f}%")
print(f"  Signale gesamt (nicht 0): {(sig!=0).sum()}")
print(f"  Übersprungen (kein Signal): {skipped_sig0}")
print(f"  Übersprungen MIN_NOTIONAL: {skipped_min_not}")
print(f"  Übersprungen Margin:       {skipped_margin}")
print(f"  Trade-Eröffnungen:         {trades_opened}")
print(f"  Offene Positionen am Ende: {len(open_pos)}")

# Offizielle Portfolio-Sim
strategies_data = {'cfg': {'symbol': symbol, 'timeframe': timeframe, 'df': df, 'config': config}}
sim = run_portfolio_simulation(capital, strategies_data, start_date, end_date)
print(f"\nOffiz. Sim  : {sim['end_capital']:.2f} USDT | Trades={sim['trade_count']} | WR={sim['win_rate']:.1f}% | DD={sim['max_drawdown_pct']:.2f}%")
