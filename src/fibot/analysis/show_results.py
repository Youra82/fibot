# src/fibot/analysis/show_results.py
# FiBot — Ergebnisanzeige und Live Signal-Check

import os
import sys
import json
import logging
import argparse
from datetime import date
from typing import Optional

import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

RESULTS_DIR = os.path.join(PROJECT_ROOT, 'artifacts', 'results')
SETTINGS_FILE = os.path.join(PROJECT_ROOT, 'settings.json')

# ANSI Farben
GREEN  = '\033[0;32m'
YELLOW = '\033[1;33m'
RED    = '\033[0;31m'
CYAN   = '\033[0;36m'
BOLD   = '\033[1m'
NC     = '\033[0m'

# ---------------------------------------------------------------------------
# Modus 1: Einzel-Analyse — alle Configs isoliert testen (stbot-Style)
# ---------------------------------------------------------------------------

def run_all_configs_isolated(date_from: str, date_to: str, capital: float):
    from fibot.analysis.backtester import run_backtest, load_ohlcv

    if not os.path.isdir(CONFIGS_DIR):
        print(f"{RED}Kein Configs-Verzeichnis: {CONFIGS_DIR}{NC}")
        return

    cfg_files = sorted(f for f in os.listdir(CONFIGS_DIR)
                       if f.startswith('config_') and f.endswith('.json'))
    if not cfg_files:
        print(f"{YELLOW}Keine Configs gefunden. Erst run_pipeline.sh ausführen.{NC}")
        return

    print(f"\n--- FiBot Ergebnis-Analyse (Einzel-Modus) ---")
    print(f"Zeitraum: {date_from} bis {date_to} | Startkapital: {capital:.0f} USDT\n")

    results = []
    for fname in cfg_files:
        cfg_path = os.path.join(CONFIGS_DIR, fname)
        try:
            with open(cfg_path) as f:
                config = json.load(f)
        except Exception:
            continue

        symbol    = config.get('market', {}).get('symbol', '')
        timeframe = config.get('market', {}).get('timeframe', '')
        if not symbol or not timeframe:
            continue

        print(f"Analysiere Ergebnisse für: {fname}...")
        df = load_ohlcv(symbol, timeframe, date_from, date_to)
        if df.empty or len(df) < 50:
            print(f"  {YELLOW}Keine Daten — übersprungen.{NC}")
            continue

        result = run_backtest(df, config, capital, symbol, timeframe)
        results.append({
            'symbol':    symbol,
            'timeframe': timeframe,
            'trades':    result.total_trades,
            'win_rate':  result.win_rate,
            'pnl_pct':   result.pnl_pct,
            'max_dd':    result.max_drawdown_pct,
            'end_cap':   result.end_capital,
        })

    if not results:
        print(f"{RED}Kein Backtest erfolgreich.{NC}")
        return

    W = 89
    print(f"\n{'='*W}")
    print(f"{'Zusammenfassung aller Einzelstrategien':^{W}}")
    print(f"{'='*W}")
    print(f"  {'Strategie':<22}  {'Trades':>6}  {'Win Rate %':>10}  {'PnL %':>7}  {'Max DD %':>8}  {'Endkapital':>10}")
    for r in sorted(results, key=lambda x: x['pnl_pct'], reverse=True):
        strat  = f"{r['symbol']} ({r['timeframe']})"
        color  = GREEN if r['pnl_pct'] >= 0 else RED
        dd_col = GREEN if r['max_dd'] <= 30 else RED
        print(f"  {strat:<22}  {r['trades']:>6}  {r['win_rate']:>10.2f}  "
              f"{color}{r['pnl_pct']:>7.2f}{NC}  "
              f"{dd_col}{r['max_dd']:>8.2f}{NC}  "
              f"{r['end_cap']:>10.2f}")
    print(f"{'='*W}")


# ---------------------------------------------------------------------------
# Modus 2: Manuelle Portfolio-Simulation — User wählt Configs
# ---------------------------------------------------------------------------

def run_manual_portfolio(filenames: list, date_from: str, date_to: str, capital: float):
    from fibot.analysis.backtester import run_backtest, load_ohlcv

    print(f"\n--- FiBot Manuelle Portfolio-Simulation ---")
    print(f"Zeitraum: {date_from} bis {date_to} | Startkapital: {capital:.0f} USDT\n")

    results = []
    for fname in filenames:
        cfg_path = os.path.join(CONFIGS_DIR, fname.strip())
        if not os.path.exists(cfg_path):
            print(f"  {RED}Config nicht gefunden: {fname}{NC}")
            continue
        try:
            with open(cfg_path) as f:
                config = json.load(f)
        except Exception:
            continue

        symbol    = config.get('market', {}).get('symbol', '')
        timeframe = config.get('market', {}).get('timeframe', '')
        if not symbol or not timeframe:
            continue

        print(f"Analysiere Ergebnisse für: {fname.strip()}...")
        df = load_ohlcv(symbol, timeframe, date_from, date_to)
        if df.empty or len(df) < 50:
            print(f"  {YELLOW}Keine Daten — übersprungen.{NC}")
            continue

        result = run_backtest(df, config, capital, symbol, timeframe)
        results.append({
            'symbol':    symbol,
            'timeframe': timeframe,
            'trades':    result.total_trades,
            'win_rate':  result.win_rate,
            'pnl_pct':   result.pnl_pct,
            'max_dd':    result.max_drawdown_pct,
            'end_cap':   result.end_capital,
        })

    if not results:
        print(f"{RED}Kein Backtest erfolgreich.{NC}")
        return

    W = 89
    print(f"\n{'='*W}")
    print(f"{'Manuelle Portfolio-Simulation':^{W}}")
    print(f"{'='*W}")
    print(f"  {'Strategie':<22}  {'Trades':>6}  {'Win Rate %':>10}  {'PnL %':>7}  {'Max DD %':>8}  {'Endkapital':>10}")
    for r in results:
        strat  = f"{r['symbol']} ({r['timeframe']})"
        color  = GREEN if r['pnl_pct'] >= 0 else RED
        dd_col = GREEN if r['max_dd'] <= 30 else RED
        print(f"  {strat:<22}  {r['trades']:>6}  {r['win_rate']:>10.2f}  "
              f"{color}{r['pnl_pct']:>7.2f}{NC}  "
              f"{dd_col}{r['max_dd']:>8.2f}{NC}  "
              f"{r['end_cap']:>10.2f}")

    # Kombiniertes Portfolio (Kapital / N)
    n        = len(results)
    per_cap  = capital / n
    port_end = sum(per_cap * (1 + r['pnl_pct'] / 100) for r in results)
    port_pnl = (port_end - capital) / capital * 100
    port_dd  = max(r['max_dd'] for r in results)
    col      = GREEN if port_pnl >= 0 else RED
    print(f"{'─'*W}")
    print(f"  Portfolio ({n} Strategie(n), je {per_cap:.2f} USDT):  "
          f"{col}{port_pnl:+.2f}%{NC}  |  End: {col}{port_end:.2f} USDT{NC}  |  MaxDD: {port_dd:.2f}%")
    print(f"{'='*W}")


# ---------------------------------------------------------------------------
# Modus 3: Portfolio-Optimierer — beste Coins/TFs für gegebene Randbedingungen
# ---------------------------------------------------------------------------

CONFIGS_DIR = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs')
OPT_RESULTS  = os.path.join(PROJECT_ROOT, 'artifacts', 'results', 'optimization_results.json')


def run_portfolio_finder(capital: float, target_max_dd: float, min_wr: float,
                          start_date: str, end_date: str):
    """
    Lädt alle vorhandenen Configs, backtestet sie und wählt per Greedy-Algorithmus
    das optimale Portfolio aus — identisch zu stbot's Mode 3.

    Randbedingungen:
      - max_drawdown  <= target_max_dd
      - win_rate      >= min_wr  (0 = kein Limit)
    Ziel: maximales End-Kapital bei eingehaltenen Randbedingungen.
    Coin-Kollision: kein Coin doppelt im Portfolio (z.B. BTC 4h + BTC 6h → nur einer).
    """
    from fibot.analysis.backtester import run_backtest, load_ohlcv

    # --- Alle Configs laden ---
    if not os.path.isdir(CONFIGS_DIR):
        print(f"{RED}Kein Configs-Verzeichnis gefunden: {CONFIGS_DIR}{NC}")
        return

    cfg_files = sorted(f for f in os.listdir(CONFIGS_DIR)
                       if f.startswith('config_') and f.endswith('.json'))
    if not cfg_files:
        print(f"{YELLOW}Keine Configs gefunden. Erst run_pipeline.sh ausführen.{NC}")
        return

    print(f"\n{CYAN}Lade {len(cfg_files)} Config(s) und starte Backtests...{NC}")
    print(f"  Zeitraum: {start_date} → {end_date} | Kapital: {capital:.0f} USDT")
    print(f"  Randbedingungen: MaxDD <= {target_max_dd:.0f}%"
          + (f"  |  WR >= {min_wr:.0f}%" if min_wr > 0 else ""))
    print()

    # --- Einzel-Backtests ---
    single_results = []
    for fname in cfg_files:
        cfg_path = os.path.join(CONFIGS_DIR, fname)
        try:
            with open(cfg_path) as f:
                config = json.load(f)
        except Exception as e:
            print(f"  {RED}Lesefehler {fname}: {e}{NC}")
            continue

        symbol    = config.get('market', {}).get('symbol', '')
        timeframe = config.get('market', {}).get('timeframe', '')
        if not symbol or not timeframe:
            continue

        df = load_ohlcv(symbol, timeframe, start_date, end_date)
        if df.empty or len(df) < 50:
            print(f"  {YELLOW}Übersprungen (keine Daten): {fname}{NC}")
            continue

        result = run_backtest(df, config, capital, symbol, timeframe)

        entry = {
            'filename':  fname,
            'symbol':    symbol,
            'timeframe': timeframe,
            'coin':      symbol.split('/')[0],
            'pnl_pct':   result.pnl_pct,
            'end_cap':   result.end_capital,
            'win_rate':  result.win_rate,
            'max_dd':    result.max_drawdown_pct,
            'trades':    result.total_trades,
            'avg_rr':    result.avg_rr,
        }
        single_results.append(entry)

        dd_color  = GREEN if result.max_drawdown_pct <= target_max_dd else RED
        pnl_color = GREEN if result.pnl_pct >= 0 else RED
        print(f"  {fname:<42}  "
              f"PnL {pnl_color}{result.pnl_pct:>+7.2f}%{NC}  "
              f"WR {result.win_rate:>5.1f}%  "
              f"Trades {result.total_trades:>4}  "
              f"DD {dd_color}{result.max_drawdown_pct:>6.2f}%{NC}")

    if not single_results:
        print(f"{RED}Kein Backtest erfolgreich. Abbruch.{NC}")
        return

    # --- Filter nach Randbedingungen ---
    valid = [r for r in single_results
             if r['max_dd'] <= target_max_dd and r['win_rate'] >= min_wr]

    print(f"\n{'═'*65}")
    print(f"  {len(valid)}/{len(single_results)} Configs erfüllen die Randbedingungen.")

    if not valid:
        print(f"\n{RED}Keine Config erfüllt MaxDD<={target_max_dd:.0f}%"
              + (f" und WR>={min_wr:.0f}%" if min_wr > 0 else "") + f".{NC}")
        # Zeige trotzdem bestes Ergebnis
        best = max(single_results, key=lambda x: x['pnl_pct'])
        print(f"  Bester erreichbarer DD: {min(r['max_dd'] for r in single_results):.1f}%")
        print(f"  TIPP: --target-max-dd auf mindestens {int(min(r['max_dd'] for r in single_results)) + 5} erhöhen.")
        return

    # --- Greedy Portfolio-Aufbau ---
    # Kapital wird gleichmäßig auf alle Strategien aufgeteilt (capital / N).
    # portfolio_pnl_pct = Durchschnitt aller Einzel-PnL% (unabhängig von N).
    # Coin-Kollision: kein Coin doppelt, egal welcher Timeframe
    #   (BTC 2h + BTC 15m wäre schon blockiert da coin='BTC')

    def _port_stats(strats: list) -> tuple:
        """Gibt (end_cap, pnl_pct) für das Portfolio zurück (Kapital geteilt durch N)."""
        n        = len(strats)
        per_cap  = capital / n
        end_sum  = sum(per_cap * (1 + r['pnl_pct'] / 100) for r in strats)
        pnl_pct  = (end_sum - capital) / capital * 100
        return end_sum, pnl_pct

    valid.sort(key=lambda x: x['pnl_pct'], reverse=True)
    portfolio  = [valid[0]]
    used_coins = {valid[0]['coin']}
    remaining  = valid[1:]

    print(f"\n{BOLD}Starte Portfolio-Aufbau (Greedy):{NC}")
    print(f"  Hinweis: Kapital wird gleichmaessig auf alle Coins aufgeteilt.")
    print(f"  Start: {valid[0]['filename']}  (PnL {valid[0]['pnl_pct']:+.2f}%)")

    improved = True
    while improved and remaining:
        improved      = False
        best_addition = None
        _, best_pnl   = _port_stats(portfolio)

        for candidate in remaining:
            if candidate['coin'] in used_coins:
                continue   # kein Coin doppelt (auch verschiedene Timeframes blockiert)

            combined_max_dd = max(r['max_dd'] for r in portfolio + [candidate])
            if combined_max_dd > target_max_dd:
                continue

            _, candidate_pnl = _port_stats(portfolio + [candidate])
            if candidate_pnl > best_pnl:
                best_pnl      = candidate_pnl
                best_addition = candidate

        if best_addition:
            portfolio.append(best_addition)
            used_coins.add(best_addition['coin'])
            remaining.remove(best_addition)
            improved = True
            _, cur_pnl = _port_stats(portfolio)
            print(f"  + {best_addition['filename']}  "
                  f"(PnL {best_addition['pnl_pct']:+.2f}%  -> Portfolio avg {cur_pnl:+.2f}%)")

    # --- Portfolio-Ergebnis anzeigen ---
    n_strats     = len(portfolio)
    per_cap      = capital / n_strats
    port_end_cap, port_pnl_pct = _port_stats(portfolio)
    port_max_dd  = max(r['max_dd'] for r in portfolio)

    print(f"\n{'═'*65}")
    print(f"{BOLD}Optimales Portfolio ({n_strats} Strategie(n), je {per_cap:.2f} USDT):{NC}\n")
    print(f"  {'Config':<42} {'Kapital':>9} {'PnL':>8} {'WR':>7} {'Trades':>7} {'MaxDD':>8}")
    print(f"  {'─'*72}")
    for r in sorted(portfolio, key=lambda x: x['pnl_pct'], reverse=True):
        pc       = GREEN if r['pnl_pct'] >= 0 else RED
        r_endcap = per_cap * (1 + r['pnl_pct'] / 100)
        print(f"  {r['filename']:<42} {per_cap:>8.2f}  "
              f"{pc}{r['pnl_pct']:>+7.2f}%{NC} "
              f"{r['win_rate']:>6.1f}% {r['trades']:>7} {r['max_dd']:>7.2f}%")

    print(f"\n  {'─'*50}")
    pnl_col = GREEN if port_pnl_pct >= 0 else RED
    print(f"  Gesamt-Kapital : {capital:.2f} USDT  ({n_strats} x {per_cap:.2f} USDT)")
    print(f"  Portfolio-End  : {pnl_col}{port_end_cap:.2f} USDT{NC}"
          f"  ({pnl_col}{port_pnl_pct:+.2f}%{NC})")
    print(f"  Portfolio MaxDD: {port_max_dd:.2f}%  (konservativ = max Einzel-DD)")
    print(f"{'═'*65}\n")

    # --- Ergebnis speichern ---
    os.makedirs(os.path.dirname(OPT_RESULTS), exist_ok=True)
    with open(OPT_RESULTS, 'w') as f:
        json.dump({'optimal_portfolio': [r['filename'] for r in portfolio]}, f, indent=2)
    print(f"{GREEN}Ergebnis gespeichert: {OPT_RESULTS}{NC}")


# ---------------------------------------------------------------------------
# Modus 4: Live Signal-Check
# ---------------------------------------------------------------------------

def run_signal_check(symbol: str, timeframe: str):
    from fibot.strategy.fibonacci_logic import generate_signal, signal_summary
    from fibot.analysis.backtester import load_ohlcv, auto_days_for_timeframe

    today      = date.today().isoformat()
    n_days     = min(auto_days_for_timeframe(timeframe), 200)
    start_date = (pd.Timestamp(today, tz='UTC') - pd.Timedelta(days=n_days)).strftime('%Y-%m-%d')

    print(f"\n{CYAN}Lade aktuelle Daten: {symbol} ({timeframe})...{NC}")
    df = load_ohlcv(symbol, timeframe, start_date, today)
    if df.empty:
        print(f"{RED}Keine Daten geladen.{NC}")
        return

    safe     = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    cfg_path = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs',
                            f"config_{safe}_fib.json")
    config   = json.load(open(cfg_path)) if os.path.exists(cfg_path) \
               else _default_config(symbol, timeframe)

    print(f"  {len(df)} Kerzen | Letzte Kerze: {df.index[-1]}")
    print(f"\n{CYAN}Berechne Fibonacci-Signal...{NC}\n")

    signal = generate_signal(df, config)
    summary = signal_summary(signal, symbol, timeframe)

    if signal.direction == "none":
        print(f"{YELLOW}{summary}{NC}")
    elif signal.direction == "long":
        print(f"{GREEN}{summary}{NC}")
    else:
        print(f"{RED}{summary}{NC}")


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _print_result(result, compact: bool = False):
    from fibot.analysis.backtester import BacktestResult
    pnl_color = GREEN if result.pnl_pct >= 0 else RED

    if compact:
        print(f"  Kapital: {result.start_capital:.0f} → {result.end_capital:.2f} USDT "
              f"({pnl_color}{result.pnl_pct:+.2f}%{NC}) | "
              f"Trades: {result.total_trades} | WR: {result.win_rate:.1f}% | "
              f"MaxDD: {result.max_drawdown_pct:.2f}% | Avg R:R 1:{result.avg_rr:.2f}")
        return

    print(f"{'═'*55}")
    print(f"{BOLD}Backtest: {result.symbol} ({result.timeframe}){NC}")
    print(f"{'─'*55}")
    print(f"  Kapital     : {result.start_capital:.2f} → "
          f"{pnl_color}{result.end_capital:.2f} USDT{NC} "
          f"({pnl_color}{result.pnl_pct:+.2f}%{NC})")
    print(f"  Trades      : {result.total_trades}  "
          f"({GREEN}W:{result.wins}{NC} / {RED}L:{result.losses}{NC})")
    print(f"  Win-Rate    : {result.win_rate:.1f}%")
    print(f"  Max Drawdown: {result.max_drawdown_pct:.2f}%")
    print(f"  Avg R:R     : 1:{result.avg_rr:.2f}")

    if result.trades:
        closed = [t for t in result.trades if t.result != 'open']
        if closed:
            longs  = len([t for t in closed if t.direction == 'long'])
            shorts = len([t for t in closed if t.direction == 'short'])
            print(f"  Long/Short  : {longs} / {shorts}")
            avg_hold = sum(t.hold_bars for t in closed) / len(closed)
            print(f"  Ø Haltedauer: {avg_hold:.1f} Kerzen")
    print(f"{'═'*55}")


def _print_json_result(d: dict):
    pnl_color = GREEN if d.get('pnl_pct', 0) >= 0 else RED
    print(f"\n{'═'*55}")
    print(f"{BOLD}{d['symbol']} ({d['timeframe']}){NC}")
    print(f"{'─'*55}")
    print(f"  Kapital    : {d['start_capital']:.2f} → "
          f"{pnl_color}{d['end_capital']:.2f} USDT{NC} "
          f"({pnl_color}{d['pnl_pct']:+.2f}%{NC})")
    print(f"  Trades     : {d['total_trades']}  (W:{d['wins']} / L:{d['losses']})")
    print(f"  Win-Rate   : {d['win_rate']:.1f}%")
    print(f"  Max DD     : {d['max_drawdown']:.2f}%")
    print(f"  Avg R:R    : 1:{d['avg_rr']:.2f}")

    trades = d.get('trades', [])
    if trades:
        print(f"\n  Letzte 5 Trades:")
        print(f"  {'Datum':<22} {'Dir':<7} {'Entry':>10} {'Exit':>10} {'PnL':>9} {'Erg'}")
        print(f"  {'─'*65}")
        for t in trades[-5:]:
            color  = GREEN if t['result'] == 'win' else (RED if t['result'] == 'loss' else NC)
            result_str = '✓' if t['result'] == 'win' else ('✗' if t['result'] == 'loss' else '…')
            print(f"  {t['ts'][:19]:<22} {t['direction']:<7} "
                  f"{t['entry']:>10.4f} {t['exit']:>10.4f} "
                  f"{color}{t['pnl_usdt']:>+8.2f}$  {result_str}{NC}")
    print(f"{'═'*55}\n")


def _default_config(symbol: str, timeframe: str) -> dict:
    return {
        "market":   {"symbol": symbol, "timeframe": timeframe},
        "strategy": {
            "swing_lookback": 100, "pivot_left": 5, "pivot_right": 5,
            "structure_lookback": 60, "fib_entry_min": 0.382, "fib_entry_max": 0.618,
            "fib_sl_level": 0.786, "fib_tp1_level": 1.000, "fib_tp2_level": 1.272,
            "fib_tolerance_atr_mult": 0.5, "structure_tolerance_atr_mult": 0.3,
            "rsi_period": 14, "rsi_oversold": 45, "rsi_overbought": 55,
            "volume_ratio_min": 1.0, "min_rr": 1.5, "atr_period": 14,
            "atr_sl_multiplier": 1.5, "min_signal_score": 4.0, "candle_limit": 500,
        },
        "risk": {"leverage": 10, "risk_per_entry_pct": 1.0, "margin_mode": "isolated"},
    }


# ---------------------------------------------------------------------------
# CLI (wird von show_results.sh aufgerufen)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FiBot Show Results")
    parser.add_argument('--mode',          type=int, required=True, help="1-4")
    parser.add_argument('--from',          dest='date_from', default=None)
    parser.add_argument('--to',            dest='date_to',   default=None)
    parser.add_argument('--capital',       type=float, default=1000.0)
    parser.add_argument('--configs',       default=None,
                        help="Leerzeichen-getrennte Config-Dateinamen für Modus 2")
    parser.add_argument('--target-max-dd', type=float, default=30.0,
                        help="Max Drawdown %% für Portfolio-Finder (Modus 3)")
    parser.add_argument('--min-wr',        type=float, default=0.0,
                        help="Min Win-Rate %% für Portfolio-Finder (Modus 3)")
    args = parser.parse_args()

    today = date.today().isoformat()
    start = args.date_from if args.date_from else '2024-01-01'
    end   = args.date_to   if args.date_to   else today

    if args.mode == 1:
        run_all_configs_isolated(start, end, args.capital)

    elif args.mode == 2:
        if not args.configs:
            print(f"{RED}--configs erforderlich für Modus 2.{NC}")
            sys.exit(1)
        filenames = args.configs.split()
        run_manual_portfolio(filenames, start, end, args.capital)

    elif args.mode == 3:
        run_portfolio_finder(args.capital, args.target_max_dd, args.min_wr, start, end)

    elif args.mode == 4:
        from fibot.analysis.interactive_chart import run_interactive_chart
        secret_path = os.path.join(PROJECT_ROOT, 'secret.json')
        secrets = {}
        if os.path.exists(secret_path):
            with open(secret_path) as f:
                secrets = json.load(f)
        run_interactive_chart(secrets)

    else:
        print(f"{RED}Ungültiger Modus.{NC}")
        sys.exit(1)
