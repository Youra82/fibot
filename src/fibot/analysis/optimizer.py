# src/fibot/analysis/optimizer.py
# FiBot — Parameter-Optimierung per Optuna
# Findet die besten Fibonacci-Strategie-Parameter für ein gegebenes Symbol/Timeframe

import os
import sys
import json
import logging
import argparse
import warnings
from datetime import date

import pandas as pd

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
except ImportError:
    print("FEHLER: optuna nicht installiert. Bitte: pip install optuna")
    sys.exit(1)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from fibot.analysis.backtester import run_backtest, load_ohlcv, auto_days_for_timeframe

logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(message)s')
logging.getLogger('optuna').setLevel(logging.WARNING)
warnings.filterwarnings('ignore')
logger = logging.getLogger(__name__)

MIN_TRADES = 5     # Mindestanzahl Trades für ein gültiges Ergebnis
CONFIGS_DIR = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs')


# ---------------------------------------------------------------------------
# Objective für Optuna
# ---------------------------------------------------------------------------

_df_global: pd.DataFrame = None
_symbol_global: str = ""
_timeframe_global: str = ""
_capital_global: float = 1000.0
_max_dd_global: float = 30.0
_min_wr_global: float = 0.0


def _objective(trial: optuna.Trial) -> float:
    global _df_global, _symbol_global, _timeframe_global, _capital_global
    global _max_dd_global, _min_wr_global

    # --- Parameter vorschlagen ---
    config = {
        "market": {
            "symbol":    _symbol_global,
            "timeframe": _timeframe_global,
        },
        "strategy": {
            "swing_lookback":              trial.suggest_int("swing_lookback", 50, 200, step=10),
            "pivot_left":                  trial.suggest_int("pivot_left",  2, 8),
            "pivot_right":                 trial.suggest_int("pivot_right", 2, 8),
            "structure_lookback":          trial.suggest_int("structure_lookback", 30, 100, step=10),
            "fib_entry_min":               0.382,
            "fib_entry_max":               0.618,
            "fib_sl_level":                0.786,
            "fib_tp1_level":               1.000,
            "fib_tp2_level":               1.272,
            "proximity_pct":               trial.suggest_float("proximity_pct",    0.3, 3.0, step=0.1),
            "structure_tolerance_atr_mult": trial.suggest_float("structure_tolerance_atr_mult", 0.1, 1.0, step=0.1),
            "rsi_period":                  14,
            "rsi_oversold":                trial.suggest_float("rsi_oversold",   30.0, 50.0, step=1.0),
            "rsi_overbought":              trial.suggest_float("rsi_overbought", 50.0, 70.0, step=1.0),
            "volume_ratio_min":            trial.suggest_float("volume_ratio_min", 0.5, 2.0, step=0.1),
            "min_rr":                      trial.suggest_float("min_rr",           1.0, 3.0, step=0.1),
            "atr_period":                  14,
            "atr_sl_multiplier":           trial.suggest_float("atr_sl_multiplier", 0.5, 3.0, step=0.1),
            "min_signal_score":            trial.suggest_float("min_signal_score",  2.0, 7.0, step=0.5),
            "candle_limit":                500,
        },
        "risk": {
            "leverage":           trial.suggest_int("leverage", 3, 20),
            "risk_per_entry_pct": trial.suggest_float("risk_per_entry_pct", 0.5, 2.0, step=0.1),
            "margin_mode":        "isolated",
        }
    }

    try:
        result = run_backtest(_df_global, config, _capital_global,
                              _symbol_global, _timeframe_global)
    except Exception:
        return -999.0

    if result.total_trades < MIN_TRADES:
        return -999.0

    if result.max_drawdown_pct > _max_dd_global:
        return -999.0

    if result.win_rate < _min_wr_global:
        return -999.0

    # Ziel: PnL optimieren, RR als Bonus
    score = result.pnl_pct + result.avg_rr * 5.0
    return score


# ---------------------------------------------------------------------------
# Haupt-Optimierungsfunktion
# ---------------------------------------------------------------------------

def optimize(symbol: str, timeframe: str,
             start_date: str, end_date: str,
             capital: float = 1000.0,
             n_trials: int = 200,
             max_dd: float = 30.0,
             min_wr: float = 0.0) -> dict | None:
    """
    Lädt Daten, optimiert Parameter mit Optuna und gibt die beste Config zurück.
    Gibt None zurück wenn kein gültiges Ergebnis gefunden wurde.
    """
    global _df_global, _symbol_global, _timeframe_global, _capital_global
    global _max_dd_global, _min_wr_global

    print(f"\n  Lade Daten: {symbol} ({timeframe}) [{start_date} → {end_date}]")
    df = load_ohlcv(symbol, timeframe, start_date, end_date)
    if df.empty or len(df) < 150:
        print(f"  FEHLER: Nicht genug Daten ({len(df)} Kerzen). Übersprungen.")
        return None
    print(f"  {len(df)} Kerzen geladen.")

    _df_global        = df
    _symbol_global    = symbol
    _timeframe_global = timeframe
    _capital_global   = capital
    _max_dd_global    = max_dd
    _min_wr_global    = min_wr

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
        pruner=optuna.pruners.MedianPruner(),
    )

    print(f"  Optimiere {n_trials} Trials... ", end='', flush=True)
    study.optimize(_objective, n_trials=n_trials, show_progress_bar=False,
                   n_jobs=1)
    print("fertig.")

    best = study.best_trial
    if best.value <= -999.0:
        print(f"  WARNUNG: Kein gültiges Ergebnis gefunden (zu wenige Trades oder DD zu hoch).")
        return None

    print(f"  Bestes Ergebnis: Score={best.value:.2f}")

    params = best.params
    config = {
        "market": {"symbol": symbol, "timeframe": timeframe},
        "strategy": {
            "swing_lookback":               params["swing_lookback"],
            "pivot_left":                   params["pivot_left"],
            "pivot_right":                  params["pivot_right"],
            "structure_lookback":           params["structure_lookback"],
            "fib_entry_min":                0.382,
            "fib_entry_max":                0.618,
            "fib_sl_level":                 0.786,
            "fib_tp1_level":                1.000,
            "fib_tp2_level":                1.272,
            "proximity_pct":                round(params["proximity_pct"], 2),
            "structure_tolerance_atr_mult": round(params["structure_tolerance_atr_mult"], 2),
            "rsi_period":                   14,
            "rsi_oversold":                 round(params["rsi_oversold"], 1),
            "rsi_overbought":               round(params["rsi_overbought"], 1),
            "volume_ratio_min":             round(params["volume_ratio_min"], 2),
            "min_rr":                       round(params["min_rr"], 2),
            "atr_period":                   14,
            "atr_sl_multiplier":            round(params["atr_sl_multiplier"], 2),
            "min_signal_score":             round(params["min_signal_score"], 1),
            "candle_limit":                 500,
        },
        "risk": {
            "leverage":           params["leverage"],
            "risk_per_entry_pct": round(params["risk_per_entry_pct"], 2),
            "margin_mode":        "isolated",
        }
    }

    # Backtest mit best config für finale Metriken
    try:
        result = run_backtest(df, config, capital, symbol, timeframe)
        config["_backtest"] = {
            "pnl_pct":       round(result.pnl_pct, 2),
            "win_rate":      round(result.win_rate, 1),
            "total_trades":  result.total_trades,
            "max_drawdown":  round(result.max_drawdown_pct, 2),
            "avg_rr":        round(result.avg_rr, 2),
            "start_date":    start_date,
            "end_date":      end_date,
            "capital":       capital,
        }
        print(f"  Backtest: PnL={result.pnl_pct:+.2f}%  WR={result.win_rate:.1f}%  "
              f"Trades={result.total_trades}  MaxDD={result.max_drawdown_pct:.2f}%")
    except Exception as e:
        logger.warning(f"Finale Backtest-Berechnung fehlgeschlagen: {e}")

    return config


def save_config(config: dict, symbol: str, timeframe: str) -> str:
    os.makedirs(CONFIGS_DIR, exist_ok=True)
    safe = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    path = os.path.join(CONFIGS_DIR, f"config_{safe}_fib.json")
    with open(path, 'w') as f:
        json.dump(config, f, indent=2)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FiBot Optimizer")
    parser.add_argument('--symbols',    nargs='+', required=True,
                        help="Symbole (z.B. BTC ETH oder BTC/USDT:USDT)")
    parser.add_argument('--timeframes', nargs='+', required=True,
                        help="Timeframes (z.B. 4h 1d)")
    parser.add_argument('--from',  dest='date_from', default=None, metavar='YYYY-MM-DD')
    parser.add_argument('--to',    dest='date_to',   default=None, metavar='YYYY-MM-DD')
    parser.add_argument('--days',  type=int, default=None)
    parser.add_argument('--capital',  type=float, default=1000.0)
    parser.add_argument('--trials',   type=int,   default=200)
    parser.add_argument('--max-dd',   type=float, default=30.0,
                        help="Max erlaubter Drawdown %% (Standard: 30)")
    parser.add_argument('--min-wr',   type=float, default=0.0,
                        help="Min Win-Rate %% (Standard: 0)")
    args = parser.parse_args()

    today = date.today().isoformat()

    GREEN  = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED    = '\033[0;31m'
    CYAN   = '\033[0;36m'
    BOLD   = '\033[1m'
    NC     = '\033[0m'

    for raw_sym in args.symbols:
        # Kurznamen expandieren: BTC → BTC/USDT:USDT
        if '/' not in raw_sym:
            symbol = f"{raw_sym.upper()}/USDT:USDT"
        else:
            symbol = raw_sym

        for timeframe in args.timeframes:
            if args.date_from:
                start_date = args.date_from
                end_date   = args.date_to if args.date_to else today
            else:
                n_days     = args.days if args.days else auto_days_for_timeframe(timeframe)
                end_date   = today
                start_date = (pd.Timestamp(today, tz='UTC') -
                              pd.Timedelta(days=n_days)).strftime('%Y-%m-%d')

            print(f"\n{BOLD}{'═'*55}{NC}")
            print(f"{BOLD}Optimiere: {symbol} ({timeframe}){NC}")
            print(f"  Zeitraum: {start_date} → {end_date}")
            print(f"  Trials:   {args.trials}  |  Kapital: {args.capital}  |  "
                  f"Max-DD: {args.max_dd}%  |  Min-WR: {args.min_wr}%")

            best_config = optimize(
                symbol, timeframe, start_date, end_date,
                capital=args.capital, n_trials=args.trials,
                max_dd=args.max_dd, min_wr=args.min_wr
            )

            if best_config is None:
                print(f"  {RED}Keine gültige Config gefunden. Übersprungen.{NC}")
                continue

            path = save_config(best_config, symbol, timeframe)
            bt = best_config.get("_backtest", {})
            print(f"\n  {GREEN}✓ Config gespeichert: {os.path.basename(path)}{NC}")
            if bt:
                color = GREEN if bt.get('pnl_pct', 0) >= 0 else RED
                print(f"  {color}PnL: {bt['pnl_pct']:+.2f}%{NC}  "
                      f"WR: {bt['win_rate']:.1f}%  "
                      f"Trades: {bt['total_trades']}  "
                      f"MaxDD: {bt['max_drawdown']:.2f}%  "
                      f"Avg R:R 1:{bt['avg_rr']:.2f}")

    print(f"\n{BOLD}Optimierung abgeschlossen.{NC}")
