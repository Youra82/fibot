# src/fibot/analysis/backtester.py
# FiBot — Backtester
# Simulates the Fibonacci strategy on historical OHLCV data

import os
import sys
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict

import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from fibot.strategy.fibonacci_logic import (
    precompute_indicators, precompute_all_signals,
    # generate_signal kept for live trading in strategy/run.py
)

logger = logging.getLogger(__name__)

MIN_NOTIONAL_USDT = 5.0
FEE_PCT           = 0.06 / 100   # Bitget Taker-Gebühr (je Seite)


# ---------------------------------------------------------------------------
# Trade record
# ---------------------------------------------------------------------------
@dataclass
class BacktestTrade:
    bar_idx: int
    timestamp: pd.Timestamp
    direction: str
    entry: float
    sl: float
    tp1: float
    contracts: float
    score: float
    reason: str
    exit_price: float = 0.0
    exit_bar: int = 0
    result: str = "open"        # "win" | "loss" | "open"
    pnl_usdt: float = 0.0
    pnl_pct: float = 0.0
    hold_bars: int = 0


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    start_capital: float
    end_capital: float
    trades: List[BacktestTrade] = field(default_factory=list)

    @property
    def total_trades(self) -> int:
        return len([t for t in self.trades if t.result != "open"])

    @property
    def wins(self) -> int:
        return len([t for t in self.trades if t.result == "win"])

    @property
    def losses(self) -> int:
        return len([t for t in self.trades if t.result == "loss"])

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades * 100 if self.total_trades else 0.0

    @property
    def pnl_pct(self) -> float:
        return (self.end_capital - self.start_capital) / self.start_capital * 100

    @property
    def max_drawdown_pct(self) -> float:
        if not self.trades:
            return 0.0
        equity = self.start_capital
        peak   = equity
        max_dd = 0.0
        for t in self.trades:
            equity += t.pnl_usdt
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @property
    def avg_rr(self) -> float:
        finished = [t for t in self.trades if t.result != "open"]
        if not finished:
            return 0.0
        risk_rewards = []
        for t in finished:
            risk = abs(t.entry - t.sl)
            reward = abs(t.exit_price - t.entry)
            if risk > 0:
                risk_rewards.append(reward / risk)
        return float(np.mean(risk_rewards)) if risk_rewards else 0.0

    def summary(self) -> str:
        return (
            f"=== FiBot Backtest: {self.symbol} ({self.timeframe}) ===\n"
            f"Kapital    : {self.start_capital:.2f} → {self.end_capital:.2f} USDT "
            f"({self.pnl_pct:+.2f}%)\n"
            f"Trades     : {self.total_trades} | W:{self.wins} L:{self.losses} "
            f"| WR: {self.win_rate:.1f}%\n"
            f"Max DD     : {self.max_drawdown_pct:.2f}%\n"
            f"Avg R:R    : 1:{self.avg_rr:.2f}\n"
        )


# ---------------------------------------------------------------------------
# Backtester
# ---------------------------------------------------------------------------

def run_backtest(df: pd.DataFrame, config: dict,
                  start_capital: float = 1000.0,
                  symbol: str = "UNKNOWN",
                  timeframe: str = "4h") -> BacktestResult:
    """
    Walk-forward backtest on df.
    For each bar (after warm-up), generate a signal on df[:i].
    If a trade is open, check if SL or TP was hit in the current bar.
    """
    strategy_cfg    = config.get('strategy', {})
    risk_cfg        = config.get('risk', {})
    leverage        = int(risk_cfg.get('leverage', 10))
    risk_pct        = float(risk_cfg.get('risk_per_entry_pct', 1.0))
    swing_lookback  = int(strategy_cfg.get('swing_lookback', 100))
    pivot_order     = max(int(strategy_cfg.get('pivot_left', 5)),
                          int(strategy_cfg.get('pivot_right', 5)), 1)
    candle_warmup   = swing_lookback + pivot_order + 10

    result = BacktestResult(
        symbol=symbol,
        timeframe=timeframe,
        start_capital=start_capital,
        end_capital=start_capital
    )

    capital   = start_capital
    open_trade: Optional[BacktestTrade] = None

    # ── Batch-Precomputation: O(N log N) statt O(N²) ──────────────────────────
    # Schritt 1: Indikatoren (RSI, ATR, Vol-Ratio) — einmal, vektorisiert
    df = precompute_indicators(df, config)
    # Schritt 2: Alle Signale vorberechnen — argrelmax EINMAL auf vollem Array,
    #            dann searchsorted (O(log N)) pro Bar statt argrelmax (O(lookback)).
    #            Ersetzt precompute_swings_and_zones + generate_signal im Loop komplett.
    df = precompute_all_signals(df, config)

    logger.info(f"Starte Backtest: {symbol} ({timeframe}) | {len(df)} Kerzen | Kapital: {start_capital}")

    # Numpy-Arrays vor der Loop extrahieren — O(1) Zugriff statt pandas iloc
    high_arr      = df['high'].values
    low_arr       = df['low'].values
    sig_dir_arr   = df['_sig_dir'].values    # 0=none, 1=long, 2=short
    sig_entry_arr = df['_sig_entry'].values
    sig_sl_arr    = df['_sig_sl'].values
    sig_tp1_arr   = df['_sig_tp1'].values
    sig_score_arr = df['_sig_score'].values
    timestamps    = df.index

    for i in range(candle_warmup, len(df)):
        ts = timestamps[i]

        # --- Manage open trade ---
        if open_trade is not None:
            high_i = high_arr[i]
            low_i  = low_arr[i]

            hit_sl  = False
            hit_tp  = False

            if open_trade.direction == 'long':
                if low_i  <= open_trade.sl:
                    hit_sl = True
                    exit_p = open_trade.sl
                elif high_i >= open_trade.tp1:
                    hit_tp = True
                    exit_p = open_trade.tp1
            else:  # short
                if high_i >= open_trade.sl:
                    hit_sl = True
                    exit_p = open_trade.sl
                elif low_i  <= open_trade.tp1:
                    hit_tp = True
                    exit_p = open_trade.tp1

            if hit_sl or hit_tp:
                price_diff = exit_p - open_trade.entry
                if open_trade.direction == 'short':
                    price_diff = -price_diff

                notional = open_trade.contracts * open_trade.entry
                fees_usdt = notional * FEE_PCT * 2      # Entry + Exit Gebühr
                pnl_usdt = price_diff * open_trade.contracts * leverage - fees_usdt
                pnl_pct  = pnl_usdt / capital * 100

                open_trade.exit_price = exit_p
                open_trade.exit_bar   = i
                open_trade.result     = 'win' if hit_tp else 'loss'
                open_trade.pnl_usdt   = pnl_usdt
                open_trade.pnl_pct    = pnl_pct
                open_trade.hold_bars  = i - open_trade.bar_idx

                capital += pnl_usdt
                result.trades.append(open_trade)
                open_trade = None

                logger.debug(f"[{ts}] Trade {'WIN' if hit_tp else 'LOSS'} @ {exit_p:.4f} | "
                             f"PnL {pnl_usdt:+.2f} USDT | Kapital: {capital:.2f}")

            # Cap at 0
            if capital <= 0:
                logger.warning("Kapital auf 0 gefallen. Backtest beendet.")
                break

            # If trade still open, don't look for new signals
            if open_trade is not None:
                continue

        # --- O(1) Signal-Lookup aus vorberechneten Arrays ---
        if sig_dir_arr[i] == 0:
            continue

        entry      = sig_entry_arr[i]
        sl         = sig_sl_arr[i]
        price_risk = abs(entry - sl)
        if price_risk <= 0:
            continue

        # Notional check
        risk_amount = capital * risk_pct / 100
        contracts   = risk_amount / price_risk
        notional    = contracts * entry
        if notional < MIN_NOTIONAL_USDT:
            logger.debug(f"[{ts}] Notional zu klein: {notional:.2f} USDT")
            continue

        direction_str = 'long' if sig_dir_arr[i] == 1 else 'short'
        open_trade = BacktestTrade(
            bar_idx=i,
            timestamp=ts,
            direction=direction_str,
            entry=entry,
            sl=sl,
            tp1=sig_tp1_arr[i],
            contracts=contracts,
            score=sig_score_arr[i],
            reason='precomputed',
        )
        logger.debug(f"[{ts}] {direction_str.upper()} Entry @ {entry:.4f} | "
                     f"SL {sl:.4f} | TP {sig_tp1_arr[i]:.4f} | Score {sig_score_arr[i]:.1f}")

    # Close any remaining open trade at last bar close
    if open_trade is not None:
        last_price = float(df['close'].iloc[-1])
        price_diff = last_price - open_trade.entry
        if open_trade.direction == 'short':
            price_diff = -price_diff
        notional_last = open_trade.contracts * open_trade.entry
        fees_last     = notional_last * FEE_PCT * 2
        pnl_usdt = price_diff * open_trade.contracts * leverage - fees_last
        open_trade.exit_price = last_price
        open_trade.exit_bar   = len(df) - 1
        open_trade.result     = 'open'
        open_trade.pnl_usdt   = pnl_usdt
        open_trade.hold_bars  = len(df) - 1 - open_trade.bar_idx
        capital += pnl_usdt
        result.trades.append(open_trade)

    result.end_capital = capital
    logger.info(result.summary())
    return result


# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------

def save_backtest_result(result: BacktestResult, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    safe = f"{result.symbol.replace('/', '').replace(':', '')}_{result.timeframe}"
    out_path = os.path.join(output_dir, f"backtest_{safe}.json")

    data = {
        'symbol':        result.symbol,
        'timeframe':     result.timeframe,
        'start_capital': result.start_capital,
        'end_capital':   round(result.end_capital, 4),
        'pnl_pct':       round(result.pnl_pct, 2),
        'total_trades':  result.total_trades,
        'wins':          result.wins,
        'losses':        result.losses,
        'win_rate':      round(result.win_rate, 2),
        'max_drawdown':  round(result.max_drawdown_pct, 2),
        'avg_rr':        round(result.avg_rr, 2),
        'trades': [
            {
                'idx':       t.bar_idx,
                'ts':        str(t.timestamp),
                'direction': t.direction,
                'entry':     round(t.entry, 6),
                'sl':        round(t.sl, 6),
                'tp1':       round(t.tp1, 6),
                'exit':      round(t.exit_price, 6),
                'result':    t.result,
                'pnl_usdt':  round(t.pnl_usdt, 4),
                'pnl_pct':   round(t.pnl_pct, 4),
                'hold_bars': t.hold_bars,
                'score':     t.score,
            }
            for t in result.trades
        ]
    }

    with open(out_path, 'w') as f:
        json.dump(data, f, indent=2)
    logger.info(f"Backtest-Ergebnis gespeichert: {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Timeframe → empfohlene Backtest-Tage
# ---------------------------------------------------------------------------
DAYS_BY_TIMEFRAME = {
    "1m":  90,
    "3m":  90,
    "5m":  180,
    "15m": 180,
    "30m": 365,
    "1h":  365,
    "2h":  365,
    "4h":  730,   # 2 Jahre für sinnvolle Fib-Swing-Erkennung
    "6h":  730,
    "8h":  730,
    "12h": 730,
    "1d":  1095,  # 3 Jahre
    "3d":  1460,
    "1w":  1460,
}

def auto_days_for_timeframe(timeframe: str) -> int:
    """Gibt die empfohlene Anzahl historischer Tage für den gegebenen Timeframe zurück."""
    return DAYS_BY_TIMEFRAME.get(timeframe, 365)


# ---------------------------------------------------------------------------
# Data loading with cache
# ---------------------------------------------------------------------------

def load_ohlcv(symbol: str, timeframe: str,
               start_date: str, end_date: str) -> pd.DataFrame:
    """
    Lädt OHLCV-Daten für einen Datumsbereich.
    Nutzt einen lokalen CSV-Cache (data/cache/) um wiederholte Downloads zu vermeiden.
    Cache wird automatisch ergänzt wenn der angefragte Zeitraum nicht abgedeckt ist.

    Args:
        symbol:     z.B. "BTC/USDT:USDT"
        timeframe:  z.B. "4h"
        start_date: "YYYY-MM-DD"
        end_date:   "YYYY-MM-DD"  (inklusiv)
    """
    import ccxt
    import time as time_mod

    cache_dir = os.path.join(PROJECT_ROOT, 'data', 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    safe_symbol = symbol.replace('/', '-').replace(':', '-')
    cache_file  = os.path.join(cache_dir, f"{safe_symbol}_{timeframe}.csv")

    req_start = pd.to_datetime(start_date, utc=True)
    req_end   = pd.to_datetime(end_date + 'T23:59:59Z', utc=True)

    cached = pd.DataFrame()

    # --- Versuch 1: Cache lesen ---
    if os.path.exists(cache_file):
        try:
            cached = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
            cached.index = cached.index.tz_localize('UTC') if cached.index.tz is None \
                           else cached.index.tz_convert('UTC')
            cached.sort_index(inplace=True)
            cached = cached[~cached.index.duplicated(keep='last')]

            if cached.index.min() <= req_start and cached.index.max() >= req_end:
                logger.info(f"Cache-Hit: {symbol} ({timeframe}) [{start_date} → {end_date}]")
                return cached.loc[req_start:req_end].copy()
            else:
                logger.info(f"Cache unvollständig — lade fehlende Daten nach.")
        except Exception as e:
            logger.warning(f"Cache-Lesefehler ({cache_file}): {e} — lade neu.")
            cached = pd.DataFrame()

    # --- Versuch 2: Von Bitget herunterladen (kein API-Key nötig für OHLCV) ---
    logger.info(f"Download: {symbol} ({timeframe}) [{start_date} → {end_date}] ...")
    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    exchange.load_markets()
    tf_ms     = exchange.parse_timeframe(timeframe) * 1000
    since_ms  = int(exchange.parse8601(start_date + 'T00:00:00Z'))
    end_ms    = int(exchange.parse8601(end_date   + 'T23:59:59Z'))
    all_ohlcv = []

    retries = 0
    while since_ms < end_ms:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since_ms, 200)
            if not ohlcv:
                break
            ohlcv = [c for c in ohlcv if c[0] <= end_ms]
            if not ohlcv:
                break
            all_ohlcv.extend(ohlcv)
            since_ms = ohlcv[-1][0] + tf_ms
            retries = 0
            time_mod.sleep(exchange.rateLimit / 1000)
        except Exception as e:
            err_str = str(e)
            # Bitget 40017: startTime zu weit zurück → 30 Tage nach vorne springen
            if '40017' in err_str and retries < 3:
                skip_ms = 30 * 24 * 3600 * 1000
                logger.warning(f"Bitget startTime-Fehler — überspringe 30 Tage vorwärts. ({retries+1}/3)")
                since_ms += skip_ms
                retries += 1
            else:
                logger.warning(f"Download-Fehler: {e}")
                break

    if not all_ohlcv:
        logger.error("Keine Daten heruntergeladen.")
        return pd.DataFrame()

    new_df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    new_df['timestamp'] = pd.to_datetime(new_df['timestamp'], unit='ms', utc=True)
    new_df.set_index('timestamp', inplace=True)
    new_df.sort_index(inplace=True)
    new_df = new_df[~new_df.index.duplicated(keep='last')]

    # Cache aktualisieren (merge mit vorhandenem Cache)
    if not cached.empty:
        merged = pd.concat([cached, new_df])
        merged = merged[~merged.index.duplicated(keep='last')]
        merged.sort_index(inplace=True)
    else:
        merged = new_df

    try:
        merged.to_csv(cache_file)
        logger.info(f"Cache gespeichert: {cache_file} ({len(merged)} Kerzen gesamt)")
    except Exception as e:
        logger.warning(f"Cache-Schreibfehler: {e}")

    return new_df.loc[req_start:req_end].copy()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    from datetime import date as date_type

    logging.basicConfig(level=logging.INFO,
                         format='%(asctime)s %(levelname)s %(message)s')

    parser = argparse.ArgumentParser(
        description="FiBot Backtester",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Beispiele:
  # Automatischer Zeitraum (empfohlen)
  python backtester.py --symbol BTC/USDT:USDT --timeframe 4h

  # Fester Zeitraum
  python backtester.py --symbol BTC/USDT:USDT --timeframe 4h --from 2023-01-01 --to 2024-01-01

  # Von Datum bis heute
  python backtester.py --symbol BTC/USDT:USDT --timeframe 4h --from 2023-06-01

  # Letzten N Tage
  python backtester.py --symbol BTC/USDT:USDT --timeframe 4h --days 365
        """
    )
    parser.add_argument('--symbol',    default='BTC/USDT:USDT', help="Handelspaar (z.B. BTC/USDT:USDT)")
    parser.add_argument('--timeframe', default='4h',            help="Zeitrahmen (z.B. 4h, 1h, 1d)")
    parser.add_argument('--from',      dest='date_from', default=None, metavar='YYYY-MM-DD',
                        help="Startdatum (hat Vorrang vor --days)")
    parser.add_argument('--to',        dest='date_to',   default=None, metavar='YYYY-MM-DD',
                        help="Enddatum (Standard: heute)")
    parser.add_argument('--days',      type=int, default=None,
                        help="Alternativ zu --from/--to: letzte N Tage (Standard: auto)")
    parser.add_argument('--capital',   type=float, default=1000.0, help="Startkapital in USDT")
    parser.add_argument('--config',    type=str,   default=None,   help="Pfad zur config_*.json")
    args = parser.parse_args()

    # --- Zeitraum auflösen ---
    today = date_type.today().isoformat()

    if args.date_from:
        # Modus: --from [--to]
        start_date = args.date_from
        end_date   = args.date_to if args.date_to else today
        logger.info(f"Zeitraum: {start_date} → {end_date}")
    else:
        # Modus: --days oder auto
        days = args.days if args.days is not None else auto_days_for_timeframe(args.timeframe)
        end_date   = today
        start_date = (pd.Timestamp(today, tz='UTC') - pd.Timedelta(days=days)).strftime('%Y-%m-%d')
        logger.info(f"Zeitraum: letzte {days} Tage ({start_date} → {end_date})")

    # --- Config laden ---
    if args.config:
        with open(args.config) as f:
            config = json.load(f)
    else:
        config = {
            "market":   {"symbol": args.symbol, "timeframe": args.timeframe},
            "strategy": {
                "swing_lookback":              100,
                "pivot_left":                  5,
                "pivot_right":                 5,
                "structure_lookback":          60,
                "fib_entry_min":               0.382,
                "fib_entry_max":               0.618,
                "fib_sl_level":                0.786,
                "fib_tp1_level":               1.618,
                "fib_tp2_level":               1.618,
                "proximity_pct":               0.5,
                "structure_tolerance_atr_mult": 0.3,
                "rsi_period":                  14,
                "rsi_oversold":                45,
                "rsi_overbought":              55,
                "volume_ratio_min":            1.0,
                "min_rr":                      1.5,
                "atr_period":                  14,
                "atr_sl_multiplier":           1.5,
                "min_signal_score":            4.0,
                "candle_limit":                500,
            },
            "risk": {
                "leverage":           10,
                "risk_per_entry_pct": 1.0,
                "margin_mode":        "isolated",
            }
        }

    # --- Daten laden (mit Cache) ---
    df = load_ohlcv(args.symbol, args.timeframe, start_date, end_date)
    if df.empty:
        logger.error("Keine Daten geladen. Abbruch.")
        sys.exit(1)
    logger.info(f"Kerzen geladen: {len(df)} ({df.index[0]} → {df.index[-1]})")

    # --- Backtest ---
    result = run_backtest(df, config, args.capital, args.symbol, args.timeframe)
    print("\n" + result.summary())

    out_dir = os.path.join(PROJECT_ROOT, 'artifacts', 'results')
    save_backtest_result(result, out_dir)
