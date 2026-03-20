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
# Modus 1: Einzel-Backtest
# ---------------------------------------------------------------------------

def run_single_backtest(symbol: str, timeframe: str,
                         date_from: Optional[str], date_to: Optional[str],
                         days: Optional[int], capital: float, config_path: Optional[str]):
    from fibot.analysis.backtester import (
        run_backtest, save_backtest_result, load_ohlcv, auto_days_for_timeframe
    )

    today = date.today().isoformat()

    if date_from:
        start_date = date_from
        end_date   = date_to if date_to else today
    else:
        n_days     = days if days else auto_days_for_timeframe(timeframe)
        end_date   = today
        start_date = (pd.Timestamp(today, tz='UTC') - pd.Timedelta(days=n_days)).strftime('%Y-%m-%d')

    print(f"\n{CYAN}Lade Daten: {symbol} ({timeframe}) [{start_date} → {end_date}]{NC}")
    df = load_ohlcv(symbol, timeframe, start_date, end_date)
    if df.empty:
        print(f"{RED}Keine Daten geladen. Abbruch.{NC}")
        return

    print(f"  {len(df)} Kerzen geladen ({df.index[0].date()} → {df.index[-1].date()})")

    if config_path and os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
    else:
        # Versuche passende Config zu finden
        safe = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
        cfg_path = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs',
                                f"config_{safe}_fib.json")
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                config = json.load(f)
            print(f"  Config: {os.path.basename(cfg_path)}")
        else:
            print(f"  {YELLOW}Keine Config gefunden — verwende Standardparameter.{NC}")
            config = _default_config(symbol, timeframe)

    risk_cfg = config.get('risk', {})
    config['risk']['risk_per_entry_pct'] = capital / 1000  # normiere auf Kapital

    print(f"\n{CYAN}Starte Backtest...{NC}\n")
    result = run_backtest(df, config, capital, symbol, timeframe)
    _print_result(result)
    out_path = save_backtest_result(result, RESULTS_DIR)
    print(f"\n{GREEN}Ergebnis gespeichert: {out_path}{NC}")


# ---------------------------------------------------------------------------
# Modus 2: Alle aktiven Strategien aus settings.json backtesten
# ---------------------------------------------------------------------------

def run_all_from_settings(date_from: Optional[str], date_to: Optional[str],
                           days: Optional[int], capital: float):
    if not os.path.exists(SETTINGS_FILE):
        print(f"{RED}settings.json nicht gefunden.{NC}")
        return

    with open(SETTINGS_FILE) as f:
        settings = json.load(f)

    strategies = settings.get('live_trading_settings', {}).get('active_strategies', [])
    active = [s for s in strategies if s.get('active', False)]

    if not active:
        print(f"{YELLOW}Keine aktiven Strategien in settings.json.{NC}")
        return

    print(f"\n{CYAN}Backteste {len(active)} aktive Strategie(n)...{NC}\n")

    from fibot.analysis.backtester import (
        run_backtest, save_backtest_result, load_ohlcv, auto_days_for_timeframe
    )

    today = date.today().isoformat()
    results = []

    for s in active:
        symbol    = s['symbol']
        timeframe = s['timeframe']

        if date_from:
            start_date = date_from
            end_date   = date_to if date_to else today
        else:
            n_days     = days if days else auto_days_for_timeframe(timeframe)
            end_date   = today
            start_date = (pd.Timestamp(today, tz='UTC') - pd.Timedelta(days=n_days)).strftime('%Y-%m-%d')

        print(f"{'─'*55}")
        print(f"{BOLD}{symbol} ({timeframe}){NC}  [{start_date} → {end_date}]")

        df = load_ohlcv(symbol, timeframe, start_date, end_date)
        if df.empty:
            print(f"  {RED}Keine Daten. Übersprungen.{NC}")
            continue

        safe     = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
        cfg_path = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs',
                                f"config_{safe}_fib.json")
        config   = json.load(open(cfg_path)) if os.path.exists(cfg_path) \
                   else _default_config(symbol, timeframe)

        result = run_backtest(df, config, capital, symbol, timeframe)
        _print_result(result, compact=True)
        save_backtest_result(result, RESULTS_DIR)
        results.append(result)

    if len(results) > 1:
        print(f"\n{'═'*55}")
        print(f"{BOLD}Übersicht:{NC}")
        print(f"{'Symbol':<22} {'TF':<5} {'PnL':>8} {'WR':>7} {'Trades':>7} {'MaxDD':>8}")
        print(f"{'─'*55}")
        for r in results:
            color = GREEN if r.pnl_pct >= 0 else RED
            print(f"{r.symbol:<22} {r.timeframe:<5} "
                  f"{color}{r.pnl_pct:>+7.2f}%{NC} "
                  f"{r.win_rate:>6.1f}% "
                  f"{r.total_trades:>7} "
                  f"{r.max_drawdown_pct:>7.2f}%")


# ---------------------------------------------------------------------------
# Modus 3: Gespeicherte Ergebnisse anzeigen
# ---------------------------------------------------------------------------

def show_saved_results():
    if not os.path.exists(RESULTS_DIR):
        print(f"{YELLOW}Keine gespeicherten Ergebnisse gefunden.{NC}")
        return

    files = sorted(
        [f for f in os.listdir(RESULTS_DIR) if f.startswith('backtest_') and f.endswith('.json')],
        key=lambda f: os.path.getmtime(os.path.join(RESULTS_DIR, f)),
        reverse=True
    )

    if not files:
        print(f"{YELLOW}Keine Backtest-Ergebnisse in {RESULTS_DIR}.{NC}")
        return

    print(f"\n{BOLD}Gespeicherte Backtest-Ergebnisse:{NC}\n")
    print(f"{'#':<4} {'Datei':<38} {'PnL':>8} {'WR':>7} {'Trades':>7} {'MaxDD':>8}")
    print(f"{'─'*70}")

    for i, fname in enumerate(files, 1):
        try:
            with open(os.path.join(RESULTS_DIR, fname)) as f:
                d = json.load(f)
            pnl   = d.get('pnl_pct', 0)
            wr    = d.get('win_rate', 0)
            tr    = d.get('total_trades', 0)
            dd    = d.get('max_drawdown', 0)
            color = GREEN if pnl >= 0 else RED
            print(f"{i:<4} {fname:<38} {color}{pnl:>+7.2f}%{NC} {wr:>6.1f}% {tr:>7} {dd:>7.2f}%")
        except Exception:
            print(f"{i:<4} {fname:<38}  {RED}(Lesefehler){NC}")

    print()
    choice = input("Nummer für Details (Enter = zurück): ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(files):
        fname = files[int(choice) - 1]
        with open(os.path.join(RESULTS_DIR, fname)) as f:
            d = json.load(f)
        _print_json_result(d)


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
    parser.add_argument('--mode',      type=int, required=True, help="1-5")
    parser.add_argument('--symbol',    default=None)
    parser.add_argument('--timeframe', default='4h')
    parser.add_argument('--from',      dest='date_from', default=None)
    parser.add_argument('--to',        dest='date_to',   default=None)
    parser.add_argument('--days',      type=int, default=None)
    parser.add_argument('--capital',   type=float, default=1000.0)
    parser.add_argument('--config',    default=None)
    args = parser.parse_args()

    if args.mode == 1:
        if not args.symbol:
            print(f"{RED}--symbol erforderlich für Modus 1.{NC}")
            sys.exit(1)
        run_single_backtest(args.symbol, args.timeframe,
                            args.date_from, args.date_to, args.days,
                            args.capital, args.config)
    elif args.mode == 2:
        run_all_from_settings(args.date_from, args.date_to, args.days, args.capital)
    elif args.mode == 3:
        show_saved_results()
    elif args.mode == 4:
        if not args.symbol:
            print(f"{RED}--symbol erforderlich für Modus 4.{NC}")
            sys.exit(1)
        run_signal_check(args.symbol, args.timeframe)
    elif args.mode == 5:
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
