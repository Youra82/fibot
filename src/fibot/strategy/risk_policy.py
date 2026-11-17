"""Non-configurable execution-risk floors shared by live trading and backtests."""

import math


POLICY_VERSION = 2

# A config or optimizer trial may widen these limits, but can never lower them.
MIN_STOP_PCT = 0.003          # 0.30 % of entry
MIN_STOP_ATR = 0.30           # 0.30 average true range
MIN_STOP_TICKS = 3

# Conservative standard-cost model used for sizing and research.
TAKER_FEE_PCT = 0.0006        # 0.06 % per side
ROUND_TRIP_FEE_PCT = TAKER_FEE_PCT * 2
STOP_SLIPPAGE_RESERVE_PCT = 0.0005
ROUND_TRIP_COST_PCT = ROUND_TRIP_FEE_PCT + STOP_SLIPPAGE_RESERVE_PCT


def minimum_stop_distance(entry: float, atr: float | None = None,
                          tick_size: float | None = None) -> float:
    """Return the hard price distance below which no FiBot order is valid."""
    entry = abs(float(entry))
    if not math.isfinite(entry) or entry <= 0:
        raise ValueError('Invalid entry for stop policy')
    distances = [entry * MIN_STOP_PCT]
    if atr is not None:
        atr = float(atr)
        if not math.isfinite(atr) or atr <= 0:
            raise ValueError('Invalid ATR for stop policy')
        distances.append(atr * MIN_STOP_ATR)
    if tick_size is not None:
        tick_size = float(tick_size)
        if not math.isfinite(tick_size) or tick_size <= 0:
            raise ValueError('Invalid tick size for stop policy')
        distances.append(tick_size * MIN_STOP_TICKS)
    return max(distances)


def stop_below_entry(entry: float, raw_stop: float, atr: float) -> float:
    """Apply the floor in the normalized long coordinate system.

    Confluence shorts are calculated on mirrored prices, so both directions pass
    through this exact function before the short prices are mirrored back.
    """
    entry = float(entry)
    raw_stop = float(raw_stop)
    distance = max(entry - raw_stop, minimum_stop_distance(entry, atr))
    return entry - distance


def validate_stop_distance(entry: float, stop: float,
                           tick_size: float | None = None) -> float:
    """Fail closed if a rounded venue bracket violates the production floor."""
    entry = float(entry)
    stop = float(stop)
    if any(not math.isfinite(value) or value <= 0 for value in (entry, stop)):
        raise ValueError('Invalid entry/stop for stop policy')
    distance = abs(entry - stop)
    required = minimum_stop_distance(entry, tick_size=tick_size)
    tolerance = max(abs(entry), required, 1.0) * 1e-12
    if distance + tolerance < required:
        raise ValueError(
            f'Stop distance {distance / entry * 100:.4f}% below hard minimum '
            f'{required / entry * 100:.4f}%')
    return distance


def effective_risk_per_contract(entry: float, stop: float) -> float:
    """Price risk plus conservative round-trip fees and stop slippage reserve."""
    distance = validate_stop_distance(entry, stop)
    return distance + abs(float(entry)) * ROUND_TRIP_COST_PCT
