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

from fibot.strategy.fibonacci_logic import generate_signal, FibSignal

logger = logging.getLogger(__name__)

MIN_NOTIONAL_USDT = 5.0


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
    strategy_cfg  = config.get('strategy', {})
    risk_cfg      = config.get('risk', {})
    leverage      = int(risk_cfg.get('leverage', 10))
    risk_pct      = float(risk_cfg.get('risk_per_entry_pct', 1.0))
    min_score     = float(strategy_cfg.get('min_signal_score', 4.0))
    candle_warmup = int(strategy_cfg.get('swing_lookback', 100)) + 20

    result = BacktestResult(
        symbol=symbol,
        timeframe=timeframe,
        start_capital=start_capital,
        end_capital=start_capital
    )

    capital   = start_capital
    open_trade: Optional[BacktestTrade] = None

    logger.info(f"Starte Backtest: {symbol} ({timeframe}) | {len(df)} Kerzen | Kapital: {start_capital}")

    for i in range(candle_warmup, len(df)):
        bar = df.iloc[i]
        ts  = df.index[i]

        # --- Manage open trade ---
        if open_trade is not None:
            high_i = bar['high']
            low_i  = bar['low']

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

                pnl_usdt = price_diff * open_trade.contracts * leverage
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

        # --- Look for new signal ---
        slice_df = df.iloc[:i+1]
        signal: FibSignal = generate_signal(slice_df, config)

        if signal.direction == "none" or signal.score < min_score:
            continue

        # Notional check
        risk_amount = capital * risk_pct / 100
        price_risk  = abs(signal.entry_price - signal.sl_price)
        if price_risk <= 0:
            continue
        contracts = risk_amount / price_risk
        notional  = contracts * signal.entry_price
        if notional < MIN_NOTIONAL_USDT:
            logger.debug(f"[{ts}] Notional zu klein: {notional:.2f} USDT")
            continue

        open_trade = BacktestTrade(
            bar_idx=i,
            timestamp=ts,
            direction=signal.direction,
            entry=signal.entry_price,
            sl=signal.sl_price,
            tp1=signal.tp1_price,
            contracts=contracts,
            score=signal.score,
            reason=signal.reason,
        )
        logger.debug(f"[{ts}] {signal.direction.upper()} Entry @ {signal.entry_price:.4f} | "
                     f"SL {signal.sl_price:.4f} | TP {signal.tp1_price:.4f} | Score {signal.score:.1f}")

    # Close any remaining open trade at last bar close
    if open_trade is not None:
        last_price = float(df['close'].iloc[-1])
        price_diff = last_price - open_trade.entry
        if open_trade.direction == 'short':
            price_diff = -price_diff
        pnl_usdt = price_diff * open_trade.contracts * leverage
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
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import ccxt
    import time as time_mod

    logging.basicConfig(level=logging.INFO,
                         format='%(asctime)s %(levelname)s %(message)s')

    parser = argparse.ArgumentParser(description="FiBot Backtester")
    parser.add_argument('--symbol',    default='BTC/USDT:USDT')
    parser.add_argument('--timeframe', default='4h')
    parser.add_argument('--days',      type=int, default=None,
                        help="Historische Tage (Standard: automatisch je nach Timeframe)")
    parser.add_argument('--capital',   type=float, default=1000.0)
    parser.add_argument('--config',    type=str, default=None, help="Pfad zur config_*.json")
    args = parser.parse_args()

    # Tage automatisch ableiten wenn nicht angegeben
    days = args.days if args.days is not None else auto_days_for_timeframe(args.timeframe)
    logger.info(f"Backtest-Zeitraum: {days} Tage (Timeframe: {args.timeframe})")

    # Load config
    if args.config:
        with open(args.config) as f:
            config = json.load(f)
    else:
        # Default config for quick testing
        config = {
            "market":   {"symbol": args.symbol, "timeframe": args.timeframe},
            "strategy": {
                "swing_lookback":    100,
                "pivot_left":        5,
                "pivot_right":       5,
                "structure_lookback": 60,
                "fib_entry_min":     0.382,
                "fib_entry_max":     0.618,
                "fib_sl_level":      0.786,
                "fib_tp1_level":     1.000,
                "fib_tp2_level":     1.272,
                "proximity_pct":     0.5,
                "rsi_period":        14,
                "rsi_oversold":      45,
                "rsi_overbought":    55,
                "volume_ratio_min":  1.0,
                "min_rr":            1.5,
                "atr_period":        14,
                "atr_sl_multiplier": 1.5,
                "min_signal_score":  4.0,
                "candle_limit":      500,
            },
            "risk": {
                "leverage":          10,
                "risk_per_entry_pct": 1.0,
                "margin_mode":       "isolated",
            }
        }

    # Fetch data
    logger.info(f"Lade historische Daten: {args.symbol} ({args.timeframe}) ...")
    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    exchange.load_markets()
    tf_ms = exchange.parse_timeframe(args.timeframe) * 1000
    since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000
    all_ohlcv = []
    while since < exchange.milliseconds():
        try:
            ohlcv = exchange.fetch_ohlcv(args.symbol, args.timeframe, since, 200)
            if not ohlcv:
                break
            all_ohlcv.extend(ohlcv)
            since = ohlcv[-1][0] + tf_ms
            time_mod.sleep(exchange.rateLimit / 1000)
        except Exception as e:
            logger.error(f"Fehler beim Laden: {e}")
            break

    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)
    df = df[~df.index.duplicated(keep='last')]
    logger.info(f"Geladen: {len(df)} Kerzen")

    result = run_backtest(df, config, args.capital, args.symbol, args.timeframe)
    print("\n" + result.summary())

    out_dir = os.path.join(PROJECT_ROOT, 'artifacts', 'results')
    save_backtest_result(result, out_dir)
