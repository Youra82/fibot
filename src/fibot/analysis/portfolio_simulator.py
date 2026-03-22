# src/fibot/analysis/portfolio_simulator.py
# Chronologische Portfolio-Simulation für mehrere FiBot-Fibonacci-Strategien.
#
# Wie stbot: alle Strategien laufen auf einem gemeinsamen Kapital.
# Position-Sizing: equity × risk_pct / sl_pct = Notional (dynamisch)
# Margin-Check: offene Positionen dürfen gesamtes equity nicht überschreiten
# SL/TP: bar-für-bar aus precomputed Signals (_sig_sl, _sig_tp1)

import os
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

FEE_PCT     = 0.06 / 100   # Bitget Taker-Gebühr (je Seite)
MIN_NOTIONAL = 5.0          # Bitget Minimum


def run_portfolio_simulation(start_capital: float,
                              strategies_data: dict,
                              start_date: str,
                              end_date: str) -> dict | None:
    """
    Chronologische Portfolio-Simulation für mehrere FiBot-Strategien.

    strategies_data: {
        filename: {
            'symbol':    str,
            'timeframe': str,
            'df':        pd.DataFrame  (mit precomputed Signals)
            'config':    dict
        }
    }

    Ablauf pro Timestamp:
      A) Offene Positionen schließen wenn SL oder TP erreicht (nächste Kerze)
      B) Neue Signale prüfen und Position öffnen falls Margin verfügbar
      C) Equity tracken (realized + unrealized PnL)

    Gibt zurück:
      end_capital, total_pnl_pct, max_drawdown_pct, trade_count,
      win_rate, liquidation_date, equity_curve
    """
    # 1. Strategien mit precomputed Signals vorbereiten ─────────────────────
    processed = {}
    for fname, strat in strategies_data.items():
        df = strat['df']
        if df is None or df.empty:
            continue

        if '_sig_dir' not in df.columns:
            try:
                from fibot.strategy.fibonacci_logic import precompute_all_signals
                df = precompute_all_signals(df, strat['config'])
            except Exception:
                continue

        processed[fname] = {
            'symbol':    strat['symbol'],
            'timeframe': strat['timeframe'],
            'df':        df,
            'risk':      strat['config'].get('risk', {}),
        }

    if not processed:
        return None

    # 2. Gemeinsamen Zeitstrahl aller Strategien aufbauen ────────────────────
    all_ts: set = set()
    for strat in processed.values():
        all_ts.update(strat['df'].index)
    sorted_ts = sorted(all_ts)

    # 3. Simulation ──────────────────────────────────────────────────────────
    equity         = float(start_capital)
    peak_equity    = equity
    max_dd_pct     = 0.0
    max_dd_date    = None
    liquidation_date = None

    # Warte-Flags: nach SL-Hit keine neue Position bis nächste Signalkerze
    open_positions: dict = {}   # fname → pos-dict
    trade_history:  list = []
    equity_curve:   list = []

    for ts in sorted_ts:
        if liquidation_date:
            break

        # ── A) Offene Positionen schließen ──────────────────────────────
        for fname in list(open_positions.keys()):
            strat = processed[fname]
            if ts not in strat['df'].index:
                continue

            candle = strat['df'].loc[ts]
            pos    = open_positions[fname]

            # Nur ab der Kerze NACH dem Entry prüfen
            if ts <= pos['entry_ts']:
                continue

            exit_price = None
            if pos['direction'] == 'long':
                if candle['low']  <= pos['sl']:  exit_price = pos['sl']
                elif candle['high'] >= pos['tp']: exit_price = pos['tp']
            else:
                if candle['high'] >= pos['sl']:  exit_price = pos['sl']
                elif candle['low']  <= pos['tp']: exit_price = pos['tp']

            if exit_price is not None:
                lev = pos.get('leverage', 1)
                if pos['direction'] == 'long':
                    raw_pnl = pos['notional'] * (exit_price - pos['entry']) / pos['entry'] * lev
                else:
                    raw_pnl = pos['notional'] * (pos['entry'] - exit_price) / pos['entry'] * lev

                fees    = pos['notional'] * FEE_PCT * 2
                net_pnl = raw_pnl - fees
                equity += net_pnl

                trade_history.append({
                    'fname':     fname,
                    'direction': pos['direction'],
                    'entry':     pos['entry'],
                    'exit':      exit_price,
                    'pnl':       net_pnl,
                    'ts':        ts,
                })
                del open_positions[fname]

        # ── B) Neue Positionen öffnen ────────────────────────────────────
        if equity > 0:
            for fname, strat in processed.items():
                if fname in open_positions:
                    continue
                if ts not in strat['df'].index:
                    continue

                row     = strat['df'].loc[ts]
                sig_dir_raw = row.get('_sig_dir', 0)
                if not sig_dir_raw or sig_dir_raw == 'none':
                    continue
                # _sig_dir ist int (0=none, 1=long, 2=short) → in String umwandeln
                sig_dir = 'long' if sig_dir_raw == 1 else ('short' if sig_dir_raw == 2 else str(sig_dir_raw))

                entry = float(row.get('_sig_entry', np.nan))
                sl    = float(row.get('_sig_sl',    np.nan))
                tp    = float(row.get('_sig_tp1',   np.nan))

                if any(np.isnan(v) or v <= 0 for v in [entry, sl, tp]):
                    continue

                sl_pct = abs(entry - sl) / entry
                if sl_pct <= 0:
                    continue

                risk     = strat['risk']
                leverage = max(1, int(risk.get('leverage', 3)))
                risk_pct = risk.get('risk_per_entry_pct', 0.5) / 100

                # Notional aus aktuellem equity × risk_pct / sl_pct (dynamisch, wie Einzel-Backtester)
                notional = (equity * risk_pct) / sl_pct
                margin   = notional / leverage

                if notional < MIN_NOTIONAL:
                    continue

                # Margin-Check: bereits belegte Margin anderer Strategien darf equity nicht überschreiten
                # (gleiche Logik wie Einzel-Backtester: eigene neue Position immer erlaubt)
                used_margin = sum(p['margin'] for p in open_positions.values())
                if used_margin > equity:
                    continue

                open_positions[fname] = {
                    'direction': sig_dir,
                    'entry':     entry,
                    'sl':        sl,
                    'tp':        tp,
                    'notional':  notional,
                    'margin':    margin,
                    'leverage':  leverage,
                    'entry_ts':  ts,
                }

        # ── C) Equity tracken (realized + unrealized) ────────────────────
        unrealized = 0.0
        for fname, pos in open_positions.items():
            strat = processed[fname]
            if ts in strat['df'].index:
                close_p = float(strat['df'].loc[ts, 'close'])
                lev = pos.get('leverage', 1)
                if pos['direction'] == 'long':
                    unrealized += pos['notional'] * (close_p - pos['entry']) / pos['entry'] * lev
                else:
                    unrealized += pos['notional'] * (pos['entry'] - close_p) / pos['entry'] * lev

        total_eq = equity + unrealized
        equity_curve.append({'timestamp': ts, 'equity': total_eq})

        peak_equity = max(peak_equity, total_eq)
        dd = (peak_equity - total_eq) / peak_equity if peak_equity > 0 else 0.0
        if dd > max_dd_pct:
            max_dd_pct = dd
            max_dd_date = ts

        if total_eq <= 0 and liquidation_date is None:
            liquidation_date = ts

    # 4. Ergebnis zusammenstellen ────────────────────────────────────────────
    final_equity  = equity_curve[-1]['equity'] if equity_curve else start_capital
    total_pnl_pct = (final_equity / start_capital - 1) * 100 if start_capital > 0 else 0.0
    wins          = sum(1 for t in trade_history if t['pnl'] > 0)
    win_rate      = (wins / len(trade_history) * 100) if trade_history else 0.0

    eq_df = pd.DataFrame(equity_curve)
    if not eq_df.empty:
        eq_df['timestamp'] = pd.to_datetime(eq_df['timestamp'])
        eq_df.set_index('timestamp', inplace=True, drop=False)

    return {
        'start_capital':     start_capital,
        'end_capital':       final_equity,
        'total_pnl_pct':     total_pnl_pct,
        'trade_count':       len(trade_history),
        'win_rate':          win_rate,
        'max_drawdown_pct':  max_dd_pct * 100,
        'max_drawdown_date': max_dd_date,
        'liquidation_date':  liquidation_date,
        'equity_curve':      eq_df,
        'trade_history':     trade_history,
    }
