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

MIN_TRADES = 2     # Mindestanzahl Trades für ein gültiges Ergebnis (1d-Timeframe hat wenige Signale)
CONFIGS_DIR = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs')


# ---------------------------------------------------------------------------
# Kapital-adaptive Parameter-Ranges
# ---------------------------------------------------------------------------

def _get_capital_ranges(capital: float) -> dict:
    """
    Passt Optimierungs-Ranges automatisch ans Startkapital an.

    Hintergrund: notional = (capital × risk_pct/100) ÷ sl_pct_of_price
    Damit notional ≥ MIN_NOTIONAL_USDT (5 USDT):
      risk_pct_min = MIN_NOTIONAL_USDT × sl_pct × 100 / capital

    Beispiel (capital=15, sl_pct≈3% auf 1d):
      risk_pct_min = 5 × 0.03 × 100 / 15 = 1.0%

    Zusätzlich: engere atr_sl_multiplier-Range bei kleinem Kapital,
    damit der SL nicht so weit weg liegt (kleineres price_risk → höheres notional).
    """
    # Maximales effektives Risiko pro Trade: risk_pct × leverage
    # Der Backtester berechnet PnL = price_diff × contracts × leverage.
    # Bei SL-Hit: Verlust = risk_amount × leverage = capital × risk_pct/100 × leverage
    # → effective_risk_pct = risk_pct × leverage muss begrenzt sein.
    # Faustformel: nach 3 Verlust-Trades noch ≥ (1 − max_dd/100) Kapital übrig
    #   → (1 − eff/100)^3 ≥ 0.7  →  eff ≤ ~11%
    # Wir nutzen 15% als Obergrenze (etwas großzügiger für kleine Kapitalien).
    # Das bestimmt: max_leverage = floor(15 / risk_pct_min)
    if capital < 50:
        # Kleinstes Kapital: risk_pct muss hoch sein (Notional), Hebel daher begrenzt
        # risk_pct_min=2% → max_leverage=7  (2×7=14 ≤ 15)
        # risk_pct_max=8% → max_leverage=7  (8×7=56 → wird durch Constraint begrenzt)
        # min_max_dd=99: kleines Kapital → DD-Filter deaktivieren damit TPE-Sampler
        # überhaupt Feedback bekommt und konvergieren kann.
        # Hintergrund: 14% eff. Risiko/Trade → fast alle Configs haben DD>30%.
        # Mit DD-Filter=30% → alle Trials -999 → TPE blind → nie valide Config.
        # Die beste gefundene Config wird trotzdem nach DD-Kriterium bewertet + angezeigt.
        return {
            "risk_per_entry_pct": (2.0,  8.0, 0.5),
            "atr_sl_multiplier":  (0.5,  2.0, 0.1),
            "leverage":           (3,     7),
            "max_effective_risk": 15.0,   # risk_pct × leverage ≤ 15%
            "min_max_dd":         99.0,   # max_dd wird auf mindestens diesen Wert angehoben
        }
    elif capital < 200:
        return {
            "risk_per_entry_pct": (1.0,  5.0, 0.5),
            "atr_sl_multiplier":  (0.5,  3.0, 0.1),
            "leverage":           (3,    15),
            "max_effective_risk": 20.0,
            "min_max_dd":         50.0,
        }
    else:
        # Standard-Ranges für ausreichend Kapital
        return {
            "risk_per_entry_pct": (0.5,  3.0, 0.1),
            "atr_sl_multiplier":  (0.5,  3.0, 0.1),
            "leverage":           (3,    20),
            "max_effective_risk": 30.0,
            "min_max_dd":         30.0,
        }


# ---------------------------------------------------------------------------
# Objective für Optuna (Closure — thread-safe für n_jobs > 1)
# ---------------------------------------------------------------------------

def _make_objective(df, symbol, timeframe, capital, max_dd, min_wr, _stats: list):
    """
    _stats: gemeinsame Liste [max_trades_seen, n_valid_eff_risk, n_too_few_trades, n_high_dd]
    Wird von allen Trials aktualisiert — erlaubt Diagnose-Ausgabe nach Abschluss.
    """
    ranges = _get_capital_ranges(capital)
    r_min,   r_max,   r_step   = ranges["risk_per_entry_pct"]
    atr_min, atr_max, atr_step = ranges["atr_sl_multiplier"]
    lev_min, lev_max            = ranges["leverage"]
    max_eff_risk                = ranges["max_effective_risk"]
    # Adaptive max_dd: für kleines Kapital wird max_dd automatisch angehoben,
    # damit der Optimizer überhaupt valide Configs finden kann.
    max_dd = max(max_dd, ranges.get("min_max_dd", 0.0))

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
                "leverage":           trial.suggest_int("leverage", lev_min, lev_max),
                "risk_per_entry_pct": trial.suggest_float("risk_per_entry_pct", r_min, r_max, step=r_step),
                "margin_mode":        "isolated",
            }
        }
        # Effektives Risiko pro Trade: risk_pct × leverage
        # Bei SL-Hit verliert man: capital × risk_pct/100 × leverage
        # Zu hoch → Konto geht bei 1-2 Verlust-Trades auf 0
        effective_risk = config["risk"]["risk_per_entry_pct"] * config["risk"]["leverage"]
        if effective_risk > max_eff_risk:
            _stats[1] += 1   # eff-risk zu hoch
            return -999.0

        try:
            result = run_backtest(df, config, capital, symbol, timeframe)
        except Exception:
            return -999.0

        # Diagnose: Maximum an Trades über alle Trials tracken
        if result.total_trades > _stats[0]:
            _stats[0] = result.total_trades

        if result.total_trades < MIN_TRADES:
            _stats[2] += 1   # zu wenige Trades
            return -999.0
        if result.max_drawdown_pct > max_dd:
            _stats[3] += 1   # DD zu hoch
            return -999.0
        if result.win_rate < min_wr:
            return -999.0
        return result.pnl_pct + result.avg_rr * 5.0
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
    # Kapital-adaptive Ranges anzeigen wenn nötig
    if capital < 200:
        ranges = _get_capital_ranges(capital)
        r = ranges["risk_per_entry_pct"]
        a = ranges["atr_sl_multiplier"]
        l = ranges["leverage"]
        m = ranges["max_effective_risk"]
        print(f"\n  HINWEIS: Kleines Kapital ({capital:.1f} USDT) — Parameter-Ranges automatisch angepasst:")
        print(f"    risk_per_entry_pct : {r[0]:.1f} – {r[1]:.1f}%  (Standard: 0.5–3.0%)")
        print(f"    atr_sl_multiplier  : {a[0]:.1f} – {a[1]:.1f}   (Standard: 0.5–3.0)")
        print(f"    leverage           : {l[0]} – {l[1]}x      (Standard: 3–20x)")
        print(f"    max effective risk : {m:.0f}%  (risk_pct x leverage <= {m:.0f}%)")
        adaptive_dd = max(max_dd, ranges.get("min_max_dd", 0.0))
        if adaptive_dd > max_dd:
            print(f"    max drawdown       : {max_dd:.0f}% -> {adaptive_dd:.0f}% (auto-angepasst fuer kleines Kapital)")

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

    # _stats: [max_trades_seen, n_eff_risk_pruned, n_too_few_trades, n_high_dd]
    _stats = [0, 0, 0, 0]
    objective = _make_objective(df, symbol, timeframe, capital, max_dd, min_wr, _stats)
    cores_str = "alle Kerne" if n_jobs == -1 else f"{n_jobs} Kern(e)"
    print(f"  Optimiere {n_trials} Trials ({cores_str})...")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True, n_jobs=n_jobs)

    best = study.best_trial
    if best.value <= -999.0:
        max_trades, n_pruned, n_few, n_dd = _stats
        print(f"  WARNUNG: Kein gültiges Ergebnis gefunden.")
        print(f"  Diagnose: max. Trades in einem Trial = {max_trades}  "
              f"(Minimum: {MIN_TRADES})")
        print(f"           eff-Risk-Pruning: {n_pruned}  |  "
              f"zu wenige Trades: {n_few}  |  DD zu hoch: {n_dd}")
        if max_trades < MIN_TRADES:
            tf_map = {"1d": "4h", "4h": "1h", "1h": "30m", "6h": "2h"}
            alt_tf  = tf_map.get(timeframe, "kleinerer Timeframe")
            print(f"  TIPP: Strategie findet auf '{timeframe}' zu selten Signale.")
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
