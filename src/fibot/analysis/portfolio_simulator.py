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

from fibot.analysis.backtester import _get_fine_slice

FEE_PCT     = 0.06 / 100   # Bitget Taker-Gebühr (je Seite)
MIN_NOTIONAL = 5.0          # Bitget Minimum


def _resolve_ambiguous_exit(fine_slice, sl_price, tp_price, side):
    """
    Wenn eine Coarse-Kerze SOWOHL SL als auch TP beruehrt haette, per feineren
    Kerzen die tatsaechliche Reihenfolge aufloesen, statt SL blind zu
    bevorzugen (bisherige Konvention, oraclebot-Muster).
    Rueckgabe: exit_price oder None.
    """
    if fine_slice is None or fine_slice.empty:
        return None
    for _, bar in fine_slice.iterrows():
        if side == 'long':
            if bar['low'] <= sl_price:
                return sl_price
            if bar['high'] >= tp_price:
                return tp_price
        else:
            if bar['high'] >= sl_price:
                return sl_price
            if bar['low'] <= tp_price:
                return tp_price
    return None


def run_portfolio_simulation(start_capital: float,
                              strategies_data: dict,
                              start_date: str,
                              end_date: str,
                              symbol_blocks: list | None = None) -> dict | None:
    """
    Chronologische Portfolio-Simulation für mehrere FiBot-Strategien.

    Optional fuer den Live-Abgleich (daily_live_vs_backtest_check.py):
      strategies_data[fname]['active_periods'] = [(von, bis), ...] -- Fuellung nur, wenn die
        Fuellkerze im Team-Zeitraum der Strategie beginnt (bis=None: offen)
      symbol_blocks = [(symbol, von, bis), ...] -- Symbol hat eine aeltere Live-Position, die der
        Simulator nicht kennt; bis=None: noch offen

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
                from fibot.strategy.signals import precompute_signals
                df = precompute_signals(df, strat['config'])
            except Exception:
                continue

        fine_df = strat.get('fine_df')
        coarse_duration = df.index[1] - df.index[0] if len(df.index) >= 2 else None

        processed[fname] = {
            'symbol':    strat['symbol'],
            'timeframe': strat['timeframe'],
            'df':        df,
            'risk':      strat['config'].get('risk', {}),
            'confluence': strat['config'].get('strategy', {}).get('type') == 'confluence',
            'fine_df':   fine_df,
            'coarse_duration': coarse_duration,
            'active_periods': strat.get('active_periods'),
        }

    if not processed:
        return None

    # 2. Arrays + Index-Maps (statt df.loc je Zeitpunkt -- das war bei vielen Strategien der
    #    Engpass: der woechentliche Optimizer lief mit 38 Configs ins 2-h-Timeout)
    for strat in processed.values():
        df = strat['df']
        strat['pos'] = {ts: i for i, ts in enumerate(df.index)}
        strat['h'] = df['high'].values
        strat['l'] = df['low'].values
        strat['c'] = df['close'].values
        n = len(df)
        strat['sd'] = df['_sig_dir'].values if '_sig_dir' in df.columns else np.zeros(n)
        strat['se'] = df['_sig_entry'].values if '_sig_entry' in df.columns else np.full(n, np.nan)
        strat['ss'] = df['_sig_sl'].values if '_sig_sl' in df.columns else np.full(n, np.nan)
        strat['st'] = df['_sig_tp1'].values if '_sig_tp1' in df.columns else np.full(n, np.nan)
        strat['si'] = df['_sig_instant'].values if '_sig_instant' in df.columns else np.zeros(n, dtype=bool)

    # Signale je Zeitpunkt in der Reihenfolge von `processed` (bestimmt die Margin-Vergabe)
    signals_at: dict = {}
    for fname, strat in processed.items():
        sd = strat['sd']
        for i in np.nonzero(sd)[0]:
            signals_at.setdefault(strat['df'].index[i], []).append(fname)

    # 3. Gemeinsamen Zeitstrahl aller Strategien aufbauen ────────────────────
    all_ts: set = set()
    for strat in processed.values():
        all_ts.update(strat['df'].index)
    sorted_ts = sorted(all_ts)

    # 4. Simulation ──────────────────────────────────────────────────────────
    equity         = float(start_capital)
    peak_equity    = equity
    max_dd_pct     = 0.0
    max_dd_date    = None
    liquidation_date = None

    open_positions: dict = {}   # fname → pos-dict
    trade_history:  list = []
    equity_curve:   list = []

    for ts in sorted_ts:
        if liquidation_date:
            break

        # ── A) Offene Positionen schließen ──────────────────────────────
        closed_now = set()
        for fname in list(open_positions.keys()):
            strat = processed[fname]
            i = strat['pos'].get(ts)
            if i is None:
                continue
            pos = open_positions[fname]

            # Nur ab der Kerze NACH dem Entry prüfen
            if ts <= pos['entry_ts']:
                continue

            if pos['direction'] == 'long':
                hit_sl = strat['l'][i] <= pos['sl']
                hit_tp = strat['h'][i] >= pos['tp']
            else:
                hit_sl = strat['h'][i] >= pos['sl']
                hit_tp = strat['l'][i] <= pos['tp']

            exit_price = None
            if hit_sl and hit_tp:
                # Beide Level in derselben Kerze moeglich -- per Fein-Daten
                # (falls vorhanden) real aufloesen statt SL blind zu bevorzugen
                # (oraclebot-Muster).
                fine_df = strat.get('fine_df')
                coarse_duration = strat.get('coarse_duration')
                if fine_df is not None and coarse_duration is not None:
                    fine_slice = _get_fine_slice(fine_df, ts, ts + coarse_duration)
                    exit_price = _resolve_ambiguous_exit(fine_slice, pos['sl'], pos['tp'], pos['direction'])
                if exit_price is None:
                    exit_price = pos['sl']  # Fallback: alte SL-first-Konvention
            elif hit_sl:
                exit_price = pos['sl']
            elif hit_tp:
                exit_price = pos['tp']

            if exit_price is not None:
                if pos['direction'] == 'long':
                    raw_pnl = pos['notional'] * (exit_price - pos['entry']) / pos['entry']
                else:
                    raw_pnl = pos['notional'] * (pos['entry'] - exit_price) / pos['entry']

                fees    = pos['notional'] * FEE_PCT * 2
                net_pnl = raw_pnl - fees
                equity += net_pnl

                sl_dist_pct = abs(pos['entry'] - pos['sl']) / pos['entry'] * 100 if pos['entry'] else 0
                trade_history.append({
                    'fname':      fname,
                    'direction':  pos['direction'],
                    'entry':      pos['entry'],
                    'exit':       exit_price,
                    'pnl':        net_pnl,
                    'ts':         ts,
                    'notional':   pos['notional'],
                    'leverage':   pos.get('leverage', 1),
                    'sl_dist_pct': sl_dist_pct,
                    'entry_ts':   pos['entry_ts'],
                })
                del open_positions[fname]
                closed_now.add(fname)

        # ── B) Neue Positionen öffnen (nur Strategien mit Signal in dieser Kerze) ──
        if equity > 0:
            for fname in signals_at.get(ts, ()):
                strat = processed[fname]
                if fname in open_positions:
                    continue
                # Konfluenz: kein Limit-Fill in der Kerze, in der die Position schloss
                if strat.get('confluence') and fname in closed_now:
                    continue
                if strat.get('active_periods') is not None and not any(
                        a <= ts and (b is None or ts < b) for a, b in strat['active_periods']):
                    continue
                if symbol_blocks and any(sym == strat['symbol'] and a <= ts and (b is None or ts < b)
                                         for sym, a, b in symbol_blocks):
                    continue
                i = strat['pos'][ts]
                sig_dir_raw = strat['sd'][i]
                # _sig_dir ist int (0=none, 1=long, 2=short) → in String umwandeln
                sig_dir = 'long' if sig_dir_raw == 1 else ('short' if sig_dir_raw == 2 else str(sig_dir_raw))

                entry = float(strat['se'][i])
                sl    = float(strat['ss'][i])
                tp    = float(strat['st'][i])

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

                # Margin-Cap: auf verfügbare Margin kappen (wie live bot)
                used_margin      = sum(p['margin'] for p in open_positions.values())
                available_margin = equity - used_margin
                if available_margin <= 0:
                    continue
                max_notional = available_margin * leverage
                notional     = min(notional, max_notional)
                margin       = notional / leverage

                if notional < MIN_NOTIONAL:
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

                # Konfluenz: Fuellkerze erreicht auch den SL -> sofort Verlust
                if bool(strat['si'][i]):
                    fees = notional * FEE_PCT * 2
                    net_pnl = -notional * sl_pct - fees
                    equity += net_pnl
                    trade_history.append({
                        'fname': fname, 'direction': sig_dir, 'entry': entry, 'exit': sl,
                        'pnl': net_pnl, 'ts': ts, 'notional': notional, 'leverage': leverage,
                        'sl_dist_pct': sl_pct * 100, 'entry_ts': ts,
                    })
                    del open_positions[fname]

        # ── C) Equity tracken (realized + unrealized) ────────────────────
        unrealized = 0.0
        for fname, pos in open_positions.items():
            strat = processed[fname]
            i = strat['pos'].get(ts)
            if i is not None:
                close_p = float(strat['c'][i])
                if pos['direction'] == 'long':
                    unrealized += pos['notional'] * (close_p - pos['entry']) / pos['entry']
                else:
                    unrealized += pos['notional'] * (pos['entry'] - close_p) / pos['entry']

        total_eq = equity + unrealized
        equity_curve.append({'timestamp': ts, 'equity': total_eq})

        peak_equity = max(peak_equity, total_eq)
        dd = (peak_equity - total_eq) / peak_equity if peak_equity > 0 else 0.0
        if dd > max_dd_pct:
            max_dd_pct = dd
            max_dd_date = ts

        if total_eq <= 0 and liquidation_date is None:
            liquidation_date = ts

    # 5. Ergebnis zusammenstellen ────────────────────────────────────────────
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
        'open_positions':    [{'fname': f, 'direction': p['direction'], 'entry': p['entry'],
                               'entry_ts': p['entry_ts']} for f, p in open_positions.items()],
    }
