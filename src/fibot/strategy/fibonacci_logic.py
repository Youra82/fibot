# src/fibot/strategy/fibonacci_logic.py
# FiBot — Fibonacci Retracement + Structure Trading Bot
# Core logic: Swing detection, Fibonacci levels, Structure detection, Signal generation

import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, List
from scipy.signal import argrelmax, argrelmin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FIB_RATIOS = {
    "0.0":    0.000,
    "23.6":   0.236,
    "38.2":   0.382,
    "50.0":   0.500,
    "61.8":   0.618,
    "78.6":   0.786,
    "100.0":  1.000,
    "127.2":  1.272,
    "161.8":  1.618,
}

# Entry zones: price must be within these Fib bands
ENTRY_FIB_LONG  = ("38.2", "61.8")   # bounce from retracement into this band → long
ENTRY_FIB_SHORT = ("38.2", "61.8")   # rejection at retracement into this band → short

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class SwingPoints:
    high_price: float
    high_idx: int
    low_price: float
    low_idx: int
    direction: str  # "up" if low → high, "down" if high → low

@dataclass
class FibLevels:
    swing_high: float
    swing_low: float
    direction: str          # "up" (long setup) or "down" (short setup)
    levels: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        self.levels = self._compute()

    def _compute(self) -> Dict[str, float]:
        """
        For a DOWN move (high → low):
          0%    = swing_low  (current low)
          100%  = swing_high (from where it dropped)
          161.8%= extension above swing_high
        Price bouncing upward from the low → LONG setup:
          Entry at 38.2% → 61.8% retracement (price recovering)
          TP1  = 100% (back to swing_high)
          TP2  = 127.2% / 161.8% (extension)
          SL   = below 0% (below swing_low)

        For an UP move (low → high):
          0%    = swing_high (current high)
          100%  = swing_low  (from where it rose)
          161.8%= extension below swing_low
        Price dropping from the high → SHORT setup:
          Entry at 38.2% → 61.8% retracement (price pulling back)
          TP1  = 100% (back to swing_low)
          TP2  = 127.2% / 161.8% (extension)
          SL   = above 0% (above swing_high)
        """
        diff = self.swing_high - self.swing_low
        levels = {}
        if self.direction == "up":
            # Retracement levels for SHORT: measured from swing_high DOWN
            for name, ratio in FIB_RATIOS.items():
                levels[name] = self.swing_high - ratio * diff
        else:
            # Retracement levels for LONG: measured from swing_low UP
            for name, ratio in FIB_RATIOS.items():
                levels[name] = self.swing_low + ratio * diff
        return levels

    def get(self, key: str) -> float:
        return self.levels[key]

    def closest_level(self, price: float) -> Tuple[str, float, float]:
        """Returns (level_name, level_price, distance_pct) of the closest Fib level."""
        best_name, best_price, best_dist = "", 0.0, float("inf")
        for name, lvl in self.levels.items():
            dist = abs(price - lvl) / lvl * 100
            if dist < best_dist:
                best_dist = dist
                best_name = name
                best_price = lvl
        return best_name, best_price, best_dist


@dataclass
class StructureInfo:
    type: str           # "wedge_down", "wedge_up", "triangle", "channel_down", "channel_up", "none"
    bias: str           # "bearish", "bullish", "neutral"
    upper_slope: float  # slope of upper trendline (price per bar)
    lower_slope: float  # slope of lower trendline
    upper_intercept: float
    lower_intercept: float
    n_bars: int         # lookback bars used
    support_at: float   # current lower trendline value (center)
    resistance_at: float  # current upper trendline value (center)
    # Toleranzzone: ATR-basierter Puffer um die Trendlinie
    # Preis gilt als "an der Struktur" wenn er in dieser Zone liegt
    support_zone_low: float   # support_at - atr_mult * ATR
    support_zone_high: float  # support_at + atr_mult * ATR
    resistance_zone_low: float   # resistance_at - atr_mult * ATR
    resistance_zone_high: float  # resistance_at + atr_mult * ATR
    breakout: str       # "none", "up", "down"
    breakout_strength: float  # 0–1


@dataclass
class FibSignal:
    direction: str      # "long", "short", "none"
    entry_price: float
    sl_price: float
    tp1_price: float    # conservative TP (100% level)
    tp2_price: float    # aggressive TP (127.2% / 161.8%)
    fib_levels: FibLevels
    structure: StructureInfo
    entry_fib_name: str  # which Fib level triggered entry
    rr_ratio: float     # risk:reward ratio
    reason: str         # human-readable explanation
    score: float        # 0–10 signal quality score


# ---------------------------------------------------------------------------
# 1. Pivot / Swing Detection
# ---------------------------------------------------------------------------
def find_pivot_highs(df: pd.DataFrame, left: int = 5, right: int = 5) -> pd.Series:
    """Pivot high detection via scipy argrelmax — vectorized C code, kein Python-Loop."""
    highs = df['high'].values
    order = max(left, right, 1)
    idx = argrelmax(highs, order=order)[0]
    pivot = np.zeros(len(highs), dtype=bool)
    pivot[idx] = True
    return pd.Series(pivot, index=df.index)


def find_pivot_lows(df: pd.DataFrame, left: int = 5, right: int = 5) -> pd.Series:
    """Pivot low detection via scipy argrelmin — vectorized C code, kein Python-Loop."""
    lows = df['low'].values
    order = max(left, right, 1)
    idx = argrelmin(lows, order=order)[0]
    pivot = np.zeros(len(lows), dtype=bool)
    pivot[idx] = True
    return pd.Series(pivot, index=df.index)


def precompute_indicators(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Berechnet RSI, ATR und Volume-Ratio einmal für das gesamte DataFrame.
    Das Ergebnis wird als Spalten (_rsi, _atr, _vol_ratio) gespeichert
    und von generate_signal genutzt um O(n²) Neuberechnungen zu vermeiden.
    """
    cfg = config.get("strategy", {})
    rsi_period = int(cfg.get("rsi_period", 14))
    atr_period = int(cfg.get("atr_period", 14))

    df = df.copy()

    # RSI
    delta    = df['close'].diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/rsi_period, min_periods=rsi_period).mean()
    avg_loss = loss.ewm(alpha=1/rsi_period, min_periods=rsi_period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['_rsi'] = 100 - (100 / (1 + rs))

    # ATR
    prev_close = df['close'].shift(1)
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - prev_close).abs(),
        (df['low']  - prev_close).abs(),
    ], axis=1).max(axis=1)
    df['_atr'] = tr.ewm(span=atr_period, min_periods=atr_period).mean()

    # Volume ratio
    df['_vol_ratio'] = df['volume'] / df['volume'].rolling(20).mean()

    return df


def find_significant_swings(df: pd.DataFrame, lookback: int = 100,
                              pivot_left: int = 5, pivot_right: int = 5) -> Optional[SwingPoints]:
    """
    Within the last `lookback` candles, find the most significant swing:
    - The highest pivot high and lowest pivot low
    - Returns SwingPoints with direction indicating the latest move
    """
    recent = df.iloc[-lookback:].copy().reset_index(drop=True)

    ph = find_pivot_highs(recent, pivot_left, pivot_right)
    pl = find_pivot_lows(recent, pivot_left, pivot_right)

    pivot_high_indices = ph[ph].index.tolist()
    pivot_low_indices  = pl[pl].index.tolist()

    if not pivot_high_indices or not pivot_low_indices:
        logger.debug("Keine Pivot-Punkte gefunden.")
        return None

    # Dominant swing: largest high and largest low in lookback
    max_high_idx = max(pivot_high_indices, key=lambda i: recent['high'].iloc[i])
    min_low_idx  = min(pivot_low_indices,  key=lambda i: recent['low'].iloc[i])

    high_price = recent['high'].iloc[max_high_idx]
    low_price  = recent['low'].iloc[min_low_idx]

    # Direction: which came last?
    if max_high_idx > min_low_idx:
        direction = "up"   # low → high (most recent move was UP → look for SHORT retracement)
    else:
        direction = "down" # high → low (most recent move was DOWN → look for LONG retracement)

    return SwingPoints(
        high_price=high_price,
        high_idx=max_high_idx,
        low_price=low_price,
        low_idx=min_low_idx,
        direction=direction,
    )


# ---------------------------------------------------------------------------
# 2. Fibonacci Level Calculation
# ---------------------------------------------------------------------------
def compute_fib_levels(swings: SwingPoints) -> FibLevels:
    """
    From swings, compute the Fibonacci grid.
    direction="down" → LONG setup (price fell, now rebounding)
    direction="up"   → SHORT setup (price rose, now retracing)
    """
    return FibLevels(
        swing_high=swings.high_price,
        swing_low=swings.low_price,
        direction=swings.direction,
    )


# ---------------------------------------------------------------------------
# 3. Structure Detection (Wedge / Triangle / Channel)
# ---------------------------------------------------------------------------
def _fit_line(x: np.ndarray, y: np.ndarray) -> Tuple[float, float]:
    """Linear regression: returns (slope, intercept)."""
    if len(x) < 2:
        return 0.0, float(y[0]) if len(y) else 0.0
    coeffs = np.polyfit(x, y, 1)
    return float(coeffs[0]), float(coeffs[1])


def detect_structure(df: pd.DataFrame, lookback: int = 60,
                     pivot_left: int = 3, pivot_right: int = 3,
                     tolerance_atr_mult: float = 0.3) -> StructureInfo:
    """
    Fits linear regression lines through pivot highs and pivot lows.
    Classifies the resulting shape as wedge/triangle/channel.

    Toleranzzone:
      Jede Trendlinie hat eine ATR-basierte Pufferzone (± tolerance_atr_mult × ATR).
      - Preis IN der Zone → "testet die Struktur" → Confluence-Bonus
      - Preis AUSSERHALB der Zone → echter Breakout (kein falscher Ausbruch)

      Beispiel (BTC, ATR=800, mult=0.3):
        support_at       = 83.200
        support_zone_low = 83.200 - 0.3*800 = 82.960  ← Untergrenze
        support_zone_high= 83.200 + 0.3*800 = 83.440  ← Obergrenze
        → Preis zwischen 82.960–83.440 = "an der Unterstützung"
    """
    recent = df.iloc[-lookback:].copy().reset_index(drop=True)
    n = len(recent)

    # ATR für Toleranzzone berechnen (über gesamten lookback)
    atr = calc_atr(recent, period=min(14, n - 1))

    ph = find_pivot_highs(recent, pivot_left, pivot_right)
    pl = find_pivot_lows(recent, pivot_left, pivot_right)

    ph_idx = np.array(ph[ph].index.tolist(), dtype=float)
    pl_idx = np.array(pl[pl].index.tolist(), dtype=float)

    tolerance = tolerance_atr_mult * atr

    # Need at least 2 pivot highs and 2 pivot lows for meaningful lines
    if len(ph_idx) < 2 or len(pl_idx) < 2:
        logger.debug("Nicht genug Pivots für Strukturerkennung.")
        s = float(recent['low'].iloc[-1])
        r = float(recent['high'].iloc[-1])
        return StructureInfo(
            type="none", bias="neutral",
            upper_slope=0, lower_slope=0,
            upper_intercept=r, lower_intercept=s,
            n_bars=n,
            support_at=s, resistance_at=r,
            support_zone_low=s - tolerance,   support_zone_high=s + tolerance,
            resistance_zone_low=r - tolerance, resistance_zone_high=r + tolerance,
            breakout="none", breakout_strength=0.0
        )

    ph_prices = recent['high'].iloc[ph_idx.astype(int)].values
    pl_prices = recent['low'].iloc[pl_idx.astype(int)].values

    up_slope, up_intercept = _fit_line(ph_idx, ph_prices)
    lo_slope, lo_intercept = _fit_line(pl_idx, pl_prices)

    # Current trendline values (at bar n-1)
    cur = float(n - 1)
    resistance_at = up_slope * cur + up_intercept
    support_at    = lo_slope * cur + lo_intercept

    # Toleranzzonen um die Trendlinien
    support_zone_low    = support_at    - tolerance
    support_zone_high   = support_at    + tolerance
    resistance_zone_low = resistance_at - tolerance
    resistance_zone_high= resistance_at + tolerance

    # Classify
    up_dir = "up"   if up_slope > 0 else "down"
    lo_dir = "up"   if lo_slope > 0 else "down"

    if up_dir == "down" and lo_dir == "down":
        spread_start = (up_slope * 0 + up_intercept) - (lo_slope * 0 + lo_intercept)
        spread_end   = resistance_at - support_at
        if spread_end < spread_start * 0.85:
            structure_type = "wedge_down"
            bias = "bullish"
        else:
            structure_type = "channel_down"
            bias = "bearish"
    elif up_dir == "up" and lo_dir == "up":
        spread_start = (up_slope * 0 + up_intercept) - (lo_slope * 0 + lo_intercept)
        spread_end   = resistance_at - support_at
        if spread_end < spread_start * 0.85:
            structure_type = "wedge_up"
            bias = "bearish"
        else:
            structure_type = "channel_up"
            bias = "bullish"
    else:
        structure_type = "triangle"
        bias = "bearish" if abs(up_slope) > abs(lo_slope) else "bullish"

    # Breakout detection:
    # Echter Breakout = letzter Close AUSSERHALB der Toleranzzone (nicht nur über der Linie)
    last_close = float(recent['close'].iloc[-1])
    breakout = "none"
    breakout_strength = 0.0

    if last_close > resistance_zone_high:
        # Klar oberhalb der Resistance-Zone → Breakout UP
        breakout = "up"
        breakout_strength = min(1.0, (last_close - resistance_zone_high) / resistance_zone_high * 100)
        logger.debug(f"Breakout UP: close={last_close:.2f} > resistance_zone_high={resistance_zone_high:.2f} "
                     f"(Trendlinie={resistance_at:.2f} ± {tolerance:.2f})")
    elif last_close < support_zone_low:
        # Klar unterhalb der Support-Zone → Breakout DOWN
        breakout = "down"
        breakout_strength = min(1.0, (support_zone_low - last_close) / support_zone_low * 100)
        logger.debug(f"Breakout DOWN: close={last_close:.2f} < support_zone_low={support_zone_low:.2f} "
                     f"(Trendlinie={support_at:.2f} ± {tolerance:.2f})")
    elif support_zone_low <= last_close <= support_zone_high:
        logger.debug(f"Preis testet Support-Zone: {support_zone_low:.2f}–{support_zone_high:.2f}")
    elif resistance_zone_low <= last_close <= resistance_zone_high:
        logger.debug(f"Preis testet Resistance-Zone: {resistance_zone_low:.2f}–{resistance_zone_high:.2f}")

    return StructureInfo(
        type=structure_type,
        bias=bias,
        upper_slope=up_slope,
        lower_slope=lo_slope,
        upper_intercept=up_intercept,
        lower_intercept=lo_intercept,
        n_bars=n,
        support_at=support_at,
        resistance_at=resistance_at,
        support_zone_low=support_zone_low,
        support_zone_high=support_zone_high,
        resistance_zone_low=resistance_zone_low,
        resistance_zone_high=resistance_zone_high,
        breakout=breakout,
        breakout_strength=breakout_strength,
    )


# ---------------------------------------------------------------------------
# 4. RSI
# ---------------------------------------------------------------------------
def calc_rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    high = df['high']
    low  = df['low']
    prev_close = df['close'].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return float(tr.ewm(span=period, min_periods=period).mean().iloc[-1])


def calc_volume_ratio(df: pd.DataFrame, period: int = 20) -> float:
    """Current volume vs. rolling mean."""
    vol_ma = df['volume'].rolling(period).mean().iloc[-1]
    if vol_ma == 0:
        return 1.0
    return float(df['volume'].iloc[-1] / vol_ma)


# ---------------------------------------------------------------------------
# 5. Signal Generation
# ---------------------------------------------------------------------------
def generate_signal(df: pd.DataFrame, config: dict) -> FibSignal:
    """
    Main entry point. Returns a FibSignal.

    config keys used:
      swing_lookback       int   (default 100) — candles to look for swings
      pivot_left           int   (default 5)
      pivot_right          int   (default 5)
      structure_lookback   int   (default 60)
      fib_entry_min        float (default 0.382) — min retracement for entry
      fib_entry_max        float (default 0.618) — max retracement for entry
      fib_sl_level         float (default 0.786) — SL at this Fib level
      fib_tp1_level        float (default 1.000) — TP1 at this Fib level
      fib_tp2_level        float (default 1.272) — TP2 at this Fib level
      rsi_period           int   (default 14)
      rsi_oversold         float (default 45)   — LONG only if RSI < this
      rsi_overbought       float (default 55)   — SHORT only if RSI > this
      volume_ratio_min     float (default 1.0)  — volume must be > mean * this
      min_rr               float (default 1.5)  — minimum R:R ratio
      atr_period                    int   (default 14)
      atr_sl_multiplier             float (default 1.5)  — SL = ATR * this (cap)
      fib_tolerance_atr_mult        float (default 0.5)  — Fib-Zonen-Toleranz = ATR * this
                                                            Erweitert die Entry-Zone (38.2%–61.8%)
                                                            um ± fib_tolerance_atr_mult * ATR
                                                            (wie Struktur-Toleranzzone, aber für Fib)
      structure_tolerance_atr_mult  float (default 0.3)  — Struktur-Toleranzzone = ATR * this
    """
    cfg = config.get("strategy", {})

    swing_lookback          = int(cfg.get("swing_lookback",             100))
    pivot_left              = int(cfg.get("pivot_left",                   5))
    pivot_right             = int(cfg.get("pivot_right",                  5))
    structure_lookback      = int(cfg.get("structure_lookback",          60))
    fib_entry_min           = float(cfg.get("fib_entry_min",           0.382))
    fib_entry_max           = float(cfg.get("fib_entry_max",           0.618))
    fib_sl_level            = float(cfg.get("fib_sl_level",            0.786))
    fib_tp1_level           = float(cfg.get("fib_tp1_level",           1.000))
    fib_tp2_level           = float(cfg.get("fib_tp2_level",           1.272))
    rsi_period              = int(cfg.get("rsi_period",                  14))
    rsi_oversold            = float(cfg.get("rsi_oversold",             45))
    rsi_overbought          = float(cfg.get("rsi_overbought",           55))
    volume_ratio_min        = float(cfg.get("volume_ratio_min",         1.0))
    min_rr                  = float(cfg.get("min_rr",                   1.5))
    atr_period              = int(cfg.get("atr_period",                  14))
    atr_sl_mult             = float(cfg.get("atr_sl_multiplier",        1.5))
    fib_tol_mult            = float(cfg.get("fib_tolerance_atr_mult",  0.5))
    struct_tol_mult         = float(cfg.get("structure_tolerance_atr_mult", 0.3))

    no_signal = FibSignal(
        direction="none", entry_price=0.0, sl_price=0.0,
        tp1_price=0.0, tp2_price=0.0,
        fib_levels=FibLevels(0.0, 0.0, "none"),
        structure=StructureInfo("none","neutral",0,0,0,0,0,0,0,0,0,0,0,"none",0),
        entry_fib_name="", rr_ratio=0.0, reason="Kein Signal", score=0.0
    )

    if len(df) < swing_lookback + pivot_left + pivot_right + 10:
        logger.debug("Nicht genug Daten für Signal-Berechnung.")
        return no_signal

    current_price = float(df['close'].iloc[-1])

    # -- Step 1: Swings --
    swings = find_significant_swings(df, swing_lookback, pivot_left, pivot_right)
    if swings is None:
        return no_signal

    move_pct = abs(swings.high_price - swings.low_price) / swings.low_price * 100
    if move_pct < 1.0:
        logger.debug(f"Swing zu klein: {move_pct:.2f}%")
        return no_signal

    # -- Step 2: Fib levels --
    fibs = compute_fib_levels(swings)

    # -- Step 3: ATR (vorberechnet, O(1)) für frühe Zonen-Prüfung --
    atr = float(df['_atr'].iloc[-1]) if '_atr' in df.columns else calc_atr(df, atr_period)
    fib_tolerance = fib_tol_mult * atr

    # -- Step 4: Frühe Zonen-Prüfung VOR detect_structure --
    # detect_structure ist teuer (argrelmax + polyfit). Nur aufrufen wenn
    # der Preis tatsächlich in der Fibonacci-Zone liegt.
    if swings.direction == "down":
        _z_low  = fibs.levels["38.2"] - fib_tolerance
        _z_high = fibs.levels["61.8"] + fib_tolerance
    else:  # "up"
        _z_low  = fibs.levels["61.8"] - fib_tolerance
        _z_high = fibs.levels["38.2"] + fib_tolerance
    if not (_z_low <= current_price <= _z_high):
        return no_signal

    # -- Step 5: Structure (mit ATR-basierter Toleranzzone) --
    # Nur erreicht wenn Preis in der Fib-Zone liegt (~1-5% aller Bars)
    structure = detect_structure(df, structure_lookback, pivot_left, pivot_right,
                                 tolerance_atr_mult=struct_tol_mult)

    # -- Step 6: Restliche Indikatoren (vorberechnet, O(1)) --
    rsi       = float(df['_rsi'].iloc[-1])       if '_rsi'       in df.columns else calc_rsi(df['close'], rsi_period)
    vol_ratio = float(df['_vol_ratio'].iloc[-1])  if '_vol_ratio'  in df.columns else calc_volume_ratio(df)

    # -- Step 7: Entry zone (Scoring) --
    score = 0.0
    reason_parts = []

    # LONG: swings.direction == "down" (price dropped → we look for bounce)
    if swings.direction == "down":
        entry_low  = fibs.levels["38.2"]
        entry_high = fibs.levels["61.8"]

        zone_low      = _z_low
        zone_high     = _z_high
        near_zone     = True   # bereits geprüft oben
        price_in_zone = entry_low <= current_price <= entry_high

        if not near_zone:
            return no_signal

        # RSI filter: nur blocken wenn klar überkauft (RSI >= rsi_overbought)
        if rsi < rsi_oversold:
            score += 2.0
            reason_parts.append(f"RSI überverkauft ({rsi:.1f})")
        elif rsi < rsi_overbought:
            score += 1.0
        else:
            return no_signal

        # Volume filter
        if vol_ratio >= volume_ratio_min:
            score += 1.5
            reason_parts.append(f"Volumen {vol_ratio:.2f}x")

        # Structure alignment
        if structure.bias in ("bullish", "neutral"):
            score += 1.5
            reason_parts.append(f"Struktur: {structure.type} ({structure.bias})")

        if structure.breakout == "up":
            score += 2.0
            reason_parts.append(f"Breakout UP (Stärke {structure.breakout_strength:.2f})")

        # Fib-Zonen-Scoring: Kernzone (38.2–61.8) > Toleranzzone
        if price_in_zone:
            score += 1.5
            reason_parts.append(f"Preis in Fib-Kernzone (38.2–61.8%)")
        else:
            score += 0.5   # Preis in Toleranzzone (außerhalb Kernzone)
            reason_parts.append(f"Preis in Fib-Toleranzzone (±{fib_tolerance:.2f})")

        # Support confluence: Preis in der ATR-Toleranzzone der Struktur-Trendlinie
        if structure.support_zone_low <= current_price <= structure.support_zone_high:
            score += 1.5
            reason_parts.append(
                f"Fib+Struktur-Confluence: Support-Zone "
                f"({structure.support_zone_low:.2f}–{structure.support_zone_high:.2f})"
            )

        # ATR-based SL
        sl_atr  = current_price - atr * atr_sl_mult
        sl_fib  = fibs.levels["78.6"]
        sl_price = max(sl_atr, sl_fib)   # use the higher (tighter) SL

        tp1_price = fibs.levels["100.0"]   # back to swing high
        tp2_price = fibs.levels["127.2"]   # extension

        risk   = current_price - sl_price
        reward = tp1_price - current_price
        if risk <= 0:
            return no_signal
        rr = reward / risk
        if rr < min_rr:
            reason_parts.append(f"R:R zu niedrig ({rr:.2f})")
            return no_signal

        score = min(10.0, score)
        reason = "LONG | " + " | ".join(reason_parts) + f" | R:R {rr:.2f}"
        logger.info(f"[FibSignal] LONG @ {current_price:.4f} | SL {sl_price:.4f} | TP1 {tp1_price:.4f} | Score {score:.1f}")

        return FibSignal(
            direction="long",
            entry_price=current_price,
            sl_price=sl_price,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            fib_levels=fibs,
            structure=structure,
            entry_fib_name="38.2–61.8 Retracement",
            rr_ratio=rr,
            reason=reason,
            score=score,
        )

    # SHORT: swings.direction == "up" (price rose → we look for rejection)
    elif swings.direction == "up":
        entry_low  = fibs.levels["61.8"]   # for UP-direction: 61.8 is the LOWER price
        entry_high = fibs.levels["38.2"]   # for UP-direction: 38.2 is the HIGHER price

        zone_low      = _z_low
        zone_high     = _z_high
        near_zone     = True   # bereits geprüft oben
        price_in_zone = entry_low <= current_price <= entry_high

        # RSI filter: nur blocken wenn klar überverkauft (RSI <= rsi_oversold)
        if rsi > rsi_overbought:
            score += 2.0
            reason_parts.append(f"RSI überkauft ({rsi:.1f})")
        elif rsi > rsi_oversold:
            score += 1.0
        else:
            return no_signal

        # Volume
        if vol_ratio >= volume_ratio_min:
            score += 1.5
            reason_parts.append(f"Volumen {vol_ratio:.2f}x")

        # Structure
        if structure.bias in ("bearish", "neutral"):
            score += 1.5
            reason_parts.append(f"Struktur: {structure.type} ({structure.bias})")

        if structure.breakout == "down":
            score += 2.0
            reason_parts.append(f"Breakout DOWN (Stärke {structure.breakout_strength:.2f})")

        # Fib-Zonen-Scoring: Kernzone (38.2–61.8) > Toleranzzone
        if price_in_zone:
            score += 1.5
            reason_parts.append(f"Preis in Fib-Kernzone (38.2–61.8%)")
        else:
            score += 0.5   # Preis in Toleranzzone (außerhalb Kernzone)
            reason_parts.append(f"Preis in Fib-Toleranzzone (±{fib_tolerance:.2f})")

        # Resistance confluence: Preis in der ATR-Toleranzzone der Struktur-Trendlinie
        if structure.resistance_zone_low <= current_price <= structure.resistance_zone_high:
            score += 1.5
            reason_parts.append(
                f"Fib+Struktur-Confluence: Resistance-Zone "
                f"({structure.resistance_zone_low:.2f}–{structure.resistance_zone_high:.2f})"
            )

        sl_atr   = current_price + atr * atr_sl_mult
        sl_fib   = fibs.levels["78.6"]
        sl_price = min(sl_atr, sl_fib)   # lower (tighter) SL

        tp1_price = fibs.levels["100.0"]   # back to swing low
        tp2_price = fibs.levels["127.2"]

        risk   = sl_price - current_price
        reward = current_price - tp1_price
        if risk <= 0:
            return no_signal
        rr = reward / risk
        if rr < min_rr:
            return no_signal

        score = min(10.0, score)
        reason = "SHORT | " + " | ".join(reason_parts) + f" | R:R {rr:.2f}"
        logger.info(f"[FibSignal] SHORT @ {current_price:.4f} | SL {sl_price:.4f} | TP1 {tp1_price:.4f} | Score {score:.1f}")

        return FibSignal(
            direction="short",
            entry_price=current_price,
            sl_price=sl_price,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
            fib_levels=fibs,
            structure=structure,
            entry_fib_name="38.2–61.8 Retracement",
            rr_ratio=rr,
            reason=reason,
            score=score,
        )

    return no_signal


# ---------------------------------------------------------------------------
# 6. Helper: signal summary for logging / Telegram
# ---------------------------------------------------------------------------
def signal_summary(sig: FibSignal, symbol: str, timeframe: str) -> str:
    if sig.direction == "none":
        return f"[{symbol} {timeframe}] Kein Fib-Signal."

    arrow = "📈" if sig.direction == "long" else "📉"
    direction_str = "LONG" if sig.direction == "long" else "SHORT"
    fibs = sig.fib_levels
    sl_pct  = abs(sig.entry_price - sig.sl_price)  / sig.entry_price * 100
    tp1_pct = abs(sig.tp1_price   - sig.entry_price) / sig.entry_price * 100
    tp2_pct = abs(sig.tp2_price   - sig.entry_price) / sig.entry_price * 100

    return (
        f"{arrow} FiBot Signal — {symbol} ({timeframe})\n"
        f"Richtung : {direction_str}\n"
        f"Entry    : {sig.entry_price:.4f} ({sig.entry_fib_name})\n"
        f"SL       : {sig.sl_price:.4f}  (-{sl_pct:.2f}%)\n"
        f"TP1      : {sig.tp1_price:.4f} (+{tp1_pct:.2f}%) [Fib 100%]\n"
        f"TP2      : {sig.tp2_price:.4f} (+{tp2_pct:.2f}%) [Fib 127.2%]\n"
        f"R:R      : 1:{sig.rr_ratio:.2f}\n"
        f"Score    : {sig.score:.1f}/10\n"
        f"Struktur : {sig.structure.type} ({sig.structure.bias})\n"
        f"Swing    : H={fibs.swing_high:.4f} / L={fibs.swing_low:.4f}\n"
        f"Grund    : {sig.reason}"
    )
