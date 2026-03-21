# src/fibot/analysis/optimizer.py
# FiBot — Parameter-Optimierung per Optuna
# Findet die besten Fibonacci-Strategie-Parameter für ein gegebenes Symbol/Timeframe

import os
import sys
import json
import logging
import argparse
import warnings
import math
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

CONFIGS_DIR = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs')

# Minimale Trades pro Timeframe: skaliert mit Anzahl Candles im Backtest-Zeitraum.
# Faustformel: 1 Trade pro 300 Candles (bei typischen Fib-Setups ca. 0.3% Signal-Rate).
# Beispiele: 1d/1000 Candles → 3, 4h/2190 → 7, 1h/8760 → 29, 30m/17500 → 58
_TF_MIN_TRADES = {
    "1m": 150, "3m": 120, "5m": 100, "15m": 80,
    "30m": 60, "1h": 50, "2h": 40,
    "4h": 30, "6h": 20, "8h": 20, "12h": 15,
    "1d": 10, "3d": 8, "1w": 5,
}

def _min_trades(timeframe: str) -> int:
    """Gibt die Mindestanzahl Trades für einen gegebenen Timeframe zurück."""
    return _TF_MIN_TRADES.get(timeframe, 5)


# ---------------------------------------------------------------------------
# Kapital- und DD-adaptive Parameter-Ranges
# ---------------------------------------------------------------------------

def _max_eff_risk_from_dd(max_dd: float, k: int = 3) -> float:
    """
    Berechnet das maximale effektive Risiko pro Trade aus dem gewünschten max_dd.

    Formel: nach k aufeinanderfolgenden Verlusten soll Drawdown <= max_dd bleiben.
      (1 - eff/100)^k >= 1 - max_dd/100
      eff <= (1 - (1 - max_dd/100)^(1/k)) * 100

    k=3: schneller Vorfilter — pruned Kombinationen die selbst bei 3 Verlusten
    in Folge schon den max_dd reissen würden. Feinere DD-Kontrolle übernimmt
    der Backtester (er prüft den tatsächlichen DD über alle Trades).

    Beispiele (k=3):
      max_dd=30%  ->  eff <= 11.2%  (z.B. 2% x 5x = 10%)
      max_dd=50%  ->  eff <= 20.6%  (z.B. 3% x 6x = 18%)
      max_dd=70%  ->  eff <= 33.1%  (z.B. 5% x 6x = 30%)
      max_dd=99%  ->  eff <= 78.5%  (praktisch unbegrenzt)
    """
    survival = 1.0 - max_dd / 100.0
    if survival <= 0:
        return 100.0
    return (1.0 - survival ** (1.0 / k)) * 100.0


def _get_capital_ranges(capital: float, max_dd: float = 30.0) -> dict:
    """
    Gibt Optimierungs-Ranges zurück, abhängig von Kapital UND max_dd.

    max_effective_risk wird mathematisch aus max_dd abgeleitet:
    Kein starre Obergrenze mehr — der Optimizer sucht selbst die beste
    Kombination aus risk_pct × leverage die den DD-Constraint einhält.

    Kapital bestimmt nur die risk_pct-Range (Notional-Constraint):
      notional = capital × risk_pct/100 / price_risk_pct
      Damit notional >= 5 USDT: risk_pct >= 5 × price_risk_pct × 100 / capital
      Bei typischem price_risk_pct=1%: risk_pct_min = 5 USDT / capital × 100%
    """
    max_eff_risk = _max_eff_risk_from_dd(max_dd)

    if capital < 50:
        # Bei kleinem Kapital höhere risk_pct nötig für ausreichende Notional (5 USDT)
        # risk_pct_min=1%: 1% × 25 USDT = 0.25 USDT → notional bei 1% SL = 25 USDT ✓
        return {
            "risk_per_entry_pct": (1.0,  8.0, 0.5),
            "atr_sl_multiplier":  (0.5,  2.0, 0.1),
            "leverage":           (2,    20),
            "max_effective_risk": max_eff_risk,
        }
    elif capital < 200:
        return {
            "risk_per_entry_pct": (0.5,  5.0, 0.5),
            "atr_sl_multiplier":  (0.5,  3.0, 0.1),
            "leverage":           (2,    20),
            "max_effective_risk": max_eff_risk,
        }
    else:
        return {
            "risk_per_entry_pct": (0.5,  3.0, 0.1),
            "atr_sl_multiplier":  (0.5,  3.0, 0.1),
            "leverage":           (2,    20),
            "max_effective_risk": max_eff_risk,
        }


# ---------------------------------------------------------------------------
# Objective für Optuna (Closure — thread-safe für n_jobs > 1)
# ---------------------------------------------------------------------------

def _make_objective(df, symbol, timeframe, capital, max_dd, min_wr, _stats: list):
    """
    _stats: gemeinsame Liste [max_trades_seen, n_valid_eff_risk, n_too_few_trades, n_high_dd]
    Wird von allen Trials aktualisiert — erlaubt Diagnose-Ausgabe nach Abschluss.
    """
    ranges = _get_capital_ranges(capital, max_dd)
    r_min,   r_max,   r_step   = ranges["risk_per_entry_pct"]
    atr_min, atr_max, atr_step = ranges["atr_sl_multiplier"]
    lev_min, lev_max            = ranges["leverage"]
    max_eff_risk                = ranges["max_effective_risk"]
    min_trades                  = _min_trades(timeframe)

    def _objective(trial: optuna.Trial) -> float:
        config = {
            "market": {"symbol": symbol, "timeframe": timeframe},
            "strategy": {
                "swing_lookback":               trial.suggest_int("swing_lookback", 20, 200, step=10),
                "pivot_left":                   trial.suggest_int("pivot_left",  1, 8),
                "pivot_right":                  trial.suggest_int("pivot_right", 1, 8),
                "structure_lookback":           trial.suggest_int("structure_lookback", 20, 100, step=10),
                "fib_entry_min":                0.382,
                "fib_entry_max":                0.618,
                "fib_sl_level":                 0.786,
                "fib_tp1_level":                1.000,
                "fib_tp2_level":                1.272,
                "fib_tolerance_atr_mult":       trial.suggest_float("fib_tolerance_atr_mult",       0.2, 2.0, step=0.1),
                "structure_tolerance_atr_mult": trial.suggest_float("structure_tolerance_atr_mult", 0.1, 1.0, step=0.1),
                "rsi_period":                   14,
                "rsi_oversold":                 trial.suggest_float("rsi_oversold",   30.0, 50.0, step=1.0),
                "rsi_overbought":               trial.suggest_float("rsi_overbought", 50.0, 70.0, step=1.0),
                "volume_ratio_min":             trial.suggest_float("volume_ratio_min", 0.1, 2.0, step=0.1),
                "min_rr":                       trial.suggest_float("min_rr",           1.0, 3.0, step=0.1),
                "atr_period":                   14,
                "atr_sl_multiplier":            trial.suggest_float("atr_sl_multiplier", atr_min, atr_max, step=atr_step),
                "min_signal_score":             trial.suggest_float("min_signal_score",  1.0, 7.0, step=0.5),
                "candle_limit":                 500,
            },
            "risk": {
                # Leverage-Range direkt aus risk_pct ableiten:
                # max_leverage = floor(max_eff_risk / risk_pct)
                # → jeder Trial erfüllt automatisch risk_pct × leverage ≤ max_eff_risk
                # → kein Pruning, alle Trials erreichen den Backtest
                "risk_per_entry_pct": trial.suggest_float("risk_per_entry_pct", r_min, r_max, step=r_step),
                "leverage":           trial.suggest_int(
                    "leverage", lev_min,
                    max(lev_min, min(lev_max, int(max_eff_risk / trial.params["risk_per_entry_pct"])))
                ),
                "margin_mode":        "isolated",
            }
        }

        try:
            result = run_backtest(df, config, capital, symbol, timeframe)
        except Exception:
            return -999.0

        # Diagnose: Maximum an Trades über alle Trials tracken
        if result.total_trades > _stats[0]:
            _stats[0] = result.total_trades

        if result.total_trades < min_trades:
            _stats[2] += 1   # zu wenige Trades
            return -999.0
        if result.max_drawdown_pct > max_dd:
            _stats[3] += 1   # DD zu hoch
            # Besten (niedrigsten) erreichbaren DD tracken für Diagnose
            if result.max_drawdown_pct < _stats[4]:
                _stats[4] = result.max_drawdown_pct
            return -999.0
        if result.win_rate < min_wr:
            return -999.0
        # Score belohnt: Profit + R:R-Qualität + Trade-Häufigkeit (logarithmisch)
        # log(trades+1)*10: 10 Trades=+24, 32 Trades=+35, 100 Trades=+46
        # Logarithmisch damit mehr Trades immer besser sind, aber mit Deckelung
        trade_bonus = math.log1p(result.total_trades) * 10.0
        return result.pnl_pct + result.avg_rr * 5.0 + trade_bonus
    return _objective


# ---------------------------------------------------------------------------
# Haupt-Optimierungsfunktion
# ---------------------------------------------------------------------------

def optimize(symbol: str, timeframe: str,
             start_date: str, end_date: str,
             capital: float = 1000.0,
             n_trials: int = 200,
             max_dd: float = 30.0,
             min_wr: float = 0.0,
             n_jobs: int = 1) -> dict | None:
    """
    Lädt Daten, optimiert Parameter mit Optuna und gibt die beste Config zurück.
    Gibt None zurück wenn kein gültiges Ergebnis gefunden wurde.
    """
    # Kapital- und DD-adaptive Ranges anzeigen
    ranges = _get_capital_ranges(capital, max_dd)
    r = ranges["risk_per_entry_pct"]
    a = ranges["atr_sl_multiplier"]
    l = ranges["leverage"]
    m = ranges["max_effective_risk"]
    print(f"\n  Parameter-Ranges (Kapital: {capital:.0f} USDT, Max-DD: {max_dd:.0f}%):")
    print(f"    risk_per_entry_pct : {r[0]:.1f} - {r[1]:.1f}%")
    print(f"    leverage           : {l[0]} - {l[1]}x")
    print(f"    max effective risk : {m:.1f}%  (aus max_dd={max_dd:.0f}%: nach 3 Verlusten <= {max_dd:.0f}% DD)")
    print(f"    min trades         : {_min_trades(timeframe)}  (Timeframe: {timeframe})")

    print(f"\n  Lade Daten: {symbol} ({timeframe}) [{start_date} → {end_date}]")
    df = load_ohlcv(symbol, timeframe, start_date, end_date)
    if df.empty or len(df) < 150:
        print(f"  FEHLER: Nicht genug Daten ({len(df)} Kerzen). Übersprungen.")
        return None
    print(f"  {len(df)} Kerzen geladen.")

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
        pruner=optuna.pruners.MedianPruner(),
    )

    # _stats: [max_trades_seen, n_eff_risk_pruned, n_too_few_trades, n_high_dd, best_dd_seen]
    _stats = [0, 0, 0, 0, float('inf')]
    objective = _make_objective(df, symbol, timeframe, capital, max_dd, min_wr, _stats)
    cores_str = "alle Kerne" if n_jobs == -1 else f"{n_jobs} Kern(e)"
    print(f"  Optimiere {n_trials} Trials ({cores_str})...")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True, n_jobs=n_jobs)

    best = study.best_trial
    if best.value <= -999.0:
        max_trades, n_pruned, n_few, n_dd, best_dd = _stats
        print(f"  WARNUNG: Kein gueltiges Ergebnis gefunden.")
        print(f"  Diagnose: zu wenige Trades: {n_few}  |  DD zu hoch: {n_dd}")
        if n_dd > 0 and best_dd < float('inf'):
            suggested_dd = int(best_dd) + 10
            print(f"  Bester erreichbarer DD: {best_dd:.1f}%  (Limit war: {max_dd:.0f}%)")
            print(f"  TIPP: --max-dd {suggested_dd} verwenden um Configs zu finden.")
        elif max_trades < _min_trades(timeframe):
            tf_map = {"1d": "4h", "4h": "1h", "1h": "30m", "6h": "2h"}
            alt_tf  = tf_map.get(timeframe, "kleinerer Timeframe")
            print(f"  TIPP: Strategie findet auf '{timeframe}' zu selten Signale "
                  f"(max. {max_trades} Trades, Minimum: {_min_trades(timeframe)}).")
            print(f"        Empfehlung: '{alt_tf}' verwenden (mehr Kerzen = mehr Setups).")
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
            "fib_tolerance_atr_mult":       round(params["fib_tolerance_atr_mult"], 2),
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
    parser.add_argument('--jobs',     type=int,   default=1,
                        help="CPU-Kerne für Parallelisierung (Standard: 1, Python GIL limitiert Threading)")
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
                max_dd=args.max_dd, min_wr=args.min_wr,
                n_jobs=args.jobs
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
