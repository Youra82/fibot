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

# Feinere Timeframe je Strategie-Timeframe fuer die SL/TP-Intrabar-Reihenfolgen-
# Aufloesung (oraclebot-Muster).
FINE_TF_MAP = {
    '5m': '1m', '15m': '1m', '30m': '1m',
    '1h': '5m', '2h': '5m',
    '4h': '15m', '6h': '15m',
    '1d': '1h',
}


def _resolve_ambiguous_exit(fine_slice, sl_price, tp_price, side):
    """
    Wenn eine Coarse-Kerze SOWOHL SL als auch TP beruehrt haette, per feineren
    Kerzen die tatsaechliche Reihenfolge aufloesen, statt SL blind zu
    bevorzugen (bisherige Konvention).
    Rueckgabe: (exit_price, result_str) oder (None, None).
    """
    if fine_slice is None or fine_slice.empty:
        return None, None
    for _, bar in fine_slice.iterrows():
        if side == 'long':
            if bar['low'] <= sl_price:
                return sl_price, 'loss'
            if bar['high'] >= tp_price:
                return tp_price, 'win'
        else:
            if bar['high'] >= sl_price:
                return sl_price, 'loss'
            if bar['low'] <= tp_price:
                return tp_price, 'win'
    return None, None


class LazyFineData:
    """
    On-Demand-Fetcher fuer Fein-Daten (Intrabar-Aufloesung). Laedt Fein-Kerzen
    nur fuer die Tage, an denen im Backtest tatsaechlich eine same-candle
    SL/TP-Ambiguitaet auftritt, statt den kompletten Backtest-Zeitraum vorab
    herunterzuladen. Ergebnis ist identisch zum eagerly geladenen DataFrame,
    nur Zeitpunkt und Groesse der Netzwerk-Fetches aendern sich.

    WICHTIG: Fetcht bewusst NICHT ueber load_ohlcv() -- load_ohlcv() cached auf
    EINE gemeinsame CSV-Datei pro (symbol, timeframe) und ueberschreibt diese
    bei jedem Cache-Miss komplett mit dem neu angefragten (schmalen) Fenster.
    Wiederholte schmale Lazy-Anfragen wuerden diese Datei gegenseitig
    ueberschreiben/invalidieren (Cache-Thrashing). Daher direkter ccxt-Zugriff
    ohne Beruehrung des Disk-Caches.
    """
    def __init__(self, symbol, fine_tf):
        self.symbol = symbol
        self.fine_tf = fine_tf
        self._days = {}
        self._exchange = None

    def _get_exchange(self):
        if self._exchange is None:
            self._exchange = _public_exchange()
        return self._exchange

    def _ensure_day(self, day):
        # Rate-Limit/Netzwerkfehler werden per _with_retry wiederholt und danach
        # weitergereicht -- vorher schluckte ein blankes except sie und die
        # Ambiguitaet fiel still auf "SL zuerst" zurueck.
        if day in self._days:
            return
        exchange = self._get_exchange()
        tf_ms    = exchange.parse_timeframe(self.fine_tf) * 1000
        since_ms = int(day.timestamp() * 1000)
        end_ms   = int((day + pd.Timedelta(days=1)).timestamp() * 1000)
        all_ohlcv = []
        cursor = since_ms
        while cursor < end_ms:
            ohlcv = _with_retry(lambda: exchange.fetch_ohlcv(self.symbol, self.fine_tf, cursor, 200),
                                f"Fine-OHLCV {self.symbol} {self.fine_tf}")
            if not ohlcv:
                break
            ohlcv = [c for c in ohlcv if c[0] <= end_ms]
            if not ohlcv:
                break
            all_ohlcv.extend(ohlcv)
            cursor = ohlcv[-1][0] + tf_ms
            if len(ohlcv) < 200:
                break
        if not all_ohlcv:
            self._days[day] = None
            return
        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)
        df = df[~df.index.duplicated(keep='last')]
        self._days[day] = df if not df.empty else None

    def get_slice(self, start_ts, end_ts):
        if self.fine_tf is None:
            return None
        start_ts = pd.Timestamp(start_ts)
        end_ts = pd.Timestamp(end_ts)
        first_day = start_ts.floor('D')
        last_day = (end_ts - pd.Timedelta(microseconds=1)).floor('D')
        parts = []
        day = first_day
        while day <= last_day:
            self._ensure_day(day)
            if self._days[day] is not None:
                parts.append(self._days[day])
            day += pd.Timedelta(days=1)
        if not parts:
            return None
        combined = pd.concat(parts).sort_index()
        combined = combined[~combined.index.duplicated(keep='first')]
        return combined.loc[(combined.index >= start_ts) & (combined.index < end_ts)]


def _get_fine_slice(fine_data, start_ts, end_ts):
    if fine_data is None:
        return None
    if hasattr(fine_data, 'get_slice'):
        return fine_data.get_slice(start_ts, end_ts)
    return fine_data.loc[(fine_data.index >= start_ts) & (fine_data.index < end_ts)]


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
                  timeframe: str = "4h",
                  min_contracts: float = 0.0,
                  fine_data: pd.DataFrame = None) -> BacktestResult:
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
    coarse_duration = df.index[1] - df.index[0] if len(df.index) >= 2 else None

    for i in range(candle_warmup, len(df)):
        ts = timestamps[i]

        # --- Manage open trade ---
        if open_trade is not None:
            high_i = high_arr[i]
            low_i  = low_arr[i]

            if open_trade.direction == 'long':
                hit_sl = low_i  <= open_trade.sl
                hit_tp = high_i >= open_trade.tp1
            else:  # short
                hit_sl = high_i >= open_trade.sl
                hit_tp = low_i  <= open_trade.tp1

            if hit_sl and hit_tp:
                # Beide Level in derselben Kerze moeglich -- per Fein-Daten
                # (falls vorhanden) real aufloesen statt SL blind zu bevorzugen
                # (oraclebot-Muster).
                exit_p = None
                if fine_data is not None and coarse_duration is not None:
                    fine_slice = _get_fine_slice(fine_data, ts, ts + coarse_duration)
                    exit_p, _resolved = _resolve_ambiguous_exit(fine_slice, open_trade.sl, open_trade.tp1, open_trade.direction)
                    hit_tp = (_resolved == 'win')
                if exit_p is None:
                    exit_p = open_trade.sl  # Fallback: alte SL-first-Konvention
                    hit_tp = False
            elif hit_sl:
                exit_p = open_trade.sl
            elif hit_tp:
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

        # Position sizing: risiko-basiert, dann auf verfügbare Margin kappen (wie live bot)
        risk_amount   = capital * risk_pct / 100
        contracts     = risk_amount / price_risk
        if min_contracts > 0 and contracts < min_contracts:
            contracts = min_contracts
        max_contracts = (capital * leverage) / entry   # Margin-Cap: notional ≤ capital × leverage
        contracts     = min(contracts, max_contracts)
        notional      = contracts * entry
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
    "1m":  30,
    "3m":  60,
    "5m":  90,
    "15m": 90,
    "30m": 365,
    "1h":  365,
    "2h":  730,
    "4h":  730,
    "6h":  1095,
    "8h":  1095,
    "12h": 1095,
    "1d":  1095,
    "3d":  1825,
    "1w":  1825,
}

def auto_days_for_timeframe(timeframe: str) -> int:
    """Gibt die empfohlene Anzahl historischer Tage für den gegebenen Timeframe zurück."""
    return DAYS_BY_TIMEFRAME.get(timeframe, 365)


# ---------------------------------------------------------------------------
# Data loading with cache
# ---------------------------------------------------------------------------

_PUBLIC_EXCHANGE = None


def _with_retry(fn, what: str, attempts: int = 7):
    """Wiederholt fn bei Rate-Limit/Netzwerkfehlern mit exponentiellem Backoff.
    Nach dem letzten Versuch wird der Fehler weitergereicht -- NIE still mit
    Teil-Daten weiterrechnen (Sept. 2026: 429-Welle beim Portfolio-Optimizer
    brach Downloads ab, Backtests liefen auf abgeschnittener Historie)."""
    import ccxt
    import time as time_mod
    delay = 2
    for k in range(attempts):
        try:
            return fn()
        except ccxt.NetworkError as e:   # umfasst DDoSProtection/RateLimitExceeded (429) + Timeouts
            if k == attempts - 1:
                raise
            logger.warning(f"{what}: {type(e).__name__} — Retry {k + 1}/{attempts - 1} in {delay}s")
            time_mod.sleep(delay)
            delay = min(delay * 2, 60)


def _public_exchange():
    """Eine geteilte Bitget-Instanz: load_markets() (inkl. fetch_currencies) nur einmal
    pro Prozess statt bei jedem Download."""
    global _PUBLIC_EXCHANGE
    if _PUBLIC_EXCHANGE is None:
        import ccxt
        exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
        _with_retry(exchange.load_markets, "load_markets")
        _PUBLIC_EXCHANGE = exchange
    return _PUBLIC_EXCHANGE


def _fetch_ohlcv_range(exchange, symbol: str, timeframe: str,
                       since_ms: int, end_ms: int, tf_ms: int) -> list:
    # Paginierung ueberlappend (naechste Seite ab der letzten erhaltenen Kerze statt
    # +1 Kerze): mit "letzte + tf" verlor Bitget an manchen Seitengrenzen genau eine
    # Kerze (ETH 4h: 3 Luecken in 21 Monaten, gleiche Bugklasse wie die 91-Tage-Luecke
    # in ltbbot). Duplikate werden unten verworfen.
    rows = []
    skips = 0
    last_ts = None
    while since_ms <= end_ms:
        try:
            ohlcv = _with_retry(lambda: exchange.fetch_ohlcv(symbol, timeframe, since_ms, 200),
                                f"OHLCV {symbol} {timeframe}")
        except Exception as e:
            # Bitget 40017: startTime vor Beginn der verfuegbaren Historie -> 30 Tage vor
            if '40017' in str(e) and skips < 3:
                logger.warning(f"Bitget startTime-Fehler — überspringe 30 Tage vorwärts. ({skips + 1}/3)")
                since_ms += 30 * 24 * 3600 * 1000
                skips += 1
                continue
            raise
        if not ohlcv:
            break
        ohlcv = [c for c in ohlcv if c[0] <= end_ms and (last_ts is None or c[0] > last_ts)]
        if not ohlcv:
            break
        rows.extend(ohlcv)
        last_ts = ohlcv[-1][0]
        if last_ts >= end_ms:
            break
        since_ms = last_ts
    return rows


def _repair_gaps(exchange, df: pd.DataFrame, symbol: str, timeframe: str, tf_ms: int) -> pd.DataFrame:
    """Laedt fehlende Kerzen innerhalb von df gezielt nach (auch Altlasten im Cache)."""
    tf_td = pd.Timedelta(milliseconds=tf_ms)
    expected = pd.date_range(df.index.min(), df.index.max(), freq=tf_td)
    missing = expected.difference(df.index)
    if missing.empty:
        return df
    # zusammenhaengende Luecken zu Bereichen gruppieren
    groups, start, prev = [], missing[0], missing[0]
    for ts in missing[1:]:
        if ts - prev > tf_td:
            groups.append((start, prev))
            start = ts
        prev = ts
    groups.append((start, prev))
    parts = [df]
    for a, b in groups:
        rows = _fetch_ohlcv_range(exchange, symbol, timeframe,
                                  int((a - tf_td).timestamp() * 1000), int(b.timestamp() * 1000), tf_ms)
        if rows:
            part = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            part['timestamp'] = pd.to_datetime(part['timestamp'], unit='ms', utc=True)
            parts.append(part.set_index('timestamp'))
    repaired = pd.concat(parts)
    repaired = repaired[~repaired.index.duplicated(keep='last')].sort_index()
    still = expected.difference(repaired.index)
    logger.info(f"Lücken-Reparatur {symbol} ({timeframe}): {len(missing) - len(still)}/{len(missing)} "
                f"Kerzen nachgeladen" + (f", {len(still)} fehlen auch bei Bitget" if len(still) else ""))
    return repaired


def load_ohlcv(symbol: str, timeframe: str,
               start_date: str, end_date: str) -> pd.DataFrame:
    """
    Lädt OHLCV-Daten für einen Datumsbereich (nur abgeschlossene Kerzen).
    Nutzt einen lokalen CSV-Cache (data/cache/) und lädt nur fehlende Stücke nach
    (Anfang vor dem Cache, Ende nach der letzten Cache-Kerze).

    Vorher galt der Cache nur als Treffer, wenn er bis end_date 23:59 reichte --
    fuer "bis heute" nie erfuellbar, jeder Lauf lud die volle Historie neu.

    Args:
        symbol:     z.B. "BTC/USDT:USDT"
        timeframe:  z.B. "4h"
        start_date: "YYYY-MM-DD"
        end_date:   "YYYY-MM-DD"  (inklusiv)
    """
    import ccxt

    cache_dir = os.path.join(PROJECT_ROOT, 'data', 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    safe_symbol = symbol.replace('/', '-').replace(':', '-')
    cache_file  = os.path.join(cache_dir, f"{safe_symbol}_{timeframe}.csv")

    tf_ms = ccxt.Exchange.parse_timeframe(timeframe) * 1000
    tf_td = pd.Timedelta(milliseconds=tf_ms)
    req_start = pd.to_datetime(start_date, utc=True)
    req_end   = pd.to_datetime(end_date + 'T23:59:59Z', utc=True)
    last_closed = pd.Timestamp.now(tz='UTC').floor(tf_td) - tf_td   # Open-Zeit der letzten fertigen Kerze
    eff_end = min(req_end.floor(tf_td), last_closed)

    cached = pd.DataFrame()
    if os.path.exists(cache_file):
        try:
            cached = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
            cached.index = cached.index.tz_localize('UTC') if cached.index.tz is None \
                           else cached.index.tz_convert('UTC')
            cached.sort_index(inplace=True)
            cached = cached[~cached.index.duplicated(keep='last')]
            # Kerzen, die beim Speichern noch offen waren, sind unvollstaendig -> verwerfen
            saved_at = pd.Timestamp(os.path.getmtime(cache_file), unit='s', tz='UTC')
            cached = cached[cached.index + tf_td <= saved_at]
        except Exception as e:
            logger.warning(f"Cache-Lesefehler ({cache_file}): {e} — lade neu.")
            cached = pd.DataFrame()

    ranges = []
    if cached.empty:
        ranges.append((req_start, eff_end))
    else:
        if cached.index.min() > req_start + tf_td:
            ranges.append((req_start, cached.index.min() - tf_td))
        if cached.index.max() < eff_end:
            ranges.append((cached.index.max() + tf_td, eff_end))

    n_cached = len(cached)
    if not ranges:
        logger.info(f"Cache-Hit: {symbol} ({timeframe}) [{start_date} → {end_date}]")
        merged = cached
    else:
        exchange = _public_exchange()
        parts = [cached] if not cached.empty else []
        for a, b in ranges:
            if a > b:
                continue
            logger.info(f"Download: {symbol} ({timeframe}) [{a} → {b}] ...")
            rows = _fetch_ohlcv_range(exchange, symbol, timeframe,
                                      int(a.timestamp() * 1000), int(b.timestamp() * 1000), tf_ms)
            if rows:
                part = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                part['timestamp'] = pd.to_datetime(part['timestamp'], unit='ms', utc=True)
                parts.append(part.set_index('timestamp'))
        if not parts:
            logger.error("Keine Daten heruntergeladen.")
            return pd.DataFrame()
        merged = pd.concat(parts)
        merged = merged[~merged.index.duplicated(keep='last')].sort_index()
        merged = merged[merged.index <= last_closed]

    # Luecken innerhalb der Historie nachladen -- nur wenn noetig Netzwerk anfassen
    expected_n = int((merged.index.max() - merged.index.min()) / tf_td) + 1
    if len(merged) < expected_n:
        merged = _repair_gaps(_public_exchange(), merged, symbol, timeframe, tf_ms)

    if ranges or len(merged) != n_cached:
        try:
            merged.to_csv(cache_file)
            logger.info(f"Cache gespeichert: {cache_file} ({len(merged)} Kerzen gesamt)")
        except Exception as e:
            logger.warning(f"Cache-Schreibfehler: {e}")

    return merged.loc[req_start:req_end].copy()


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
    try:
        import ccxt as _ccxt
        _exch = _ccxt.bitget({'options': {'defaultType': 'swap'}})
        _markets = _exch.load_markets()
        _min_contracts = float(
            _markets.get(args.symbol, {}).get('limits', {}).get('amount', {}).get('min', 0.0) or 0.0)
    except Exception:
        _min_contracts = 0.0

    _fine_tf = FINE_TF_MAP.get(args.timeframe)
    _fine_data = LazyFineData(args.symbol, _fine_tf) if _fine_tf else None

    result = run_backtest(df, config, args.capital, args.symbol, args.timeframe,
                          min_contracts=_min_contracts, fine_data=_fine_data)
    print("\n" + result.summary())

    out_dir = os.path.join(PROJECT_ROOT, 'artifacts', 'results')
    save_backtest_result(result, out_dir)
