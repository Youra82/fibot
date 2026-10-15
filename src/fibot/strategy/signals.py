# src/fibot/strategy/signals.py
# Zentraler Verteiler: waehlt anhand von config['strategy']['type'] die Signal-Logik.
# Backtester, Portfolio-Simulator, show_results und Optimizer rufen nur noch diese Funktion.

import pandas as pd

from fibot.strategy.confluence_logic import is_confluence, precompute_confluence_signals
from fibot.strategy.fibonacci_logic import precompute_all_signals, precompute_indicators


def precompute_signals(df: pd.DataFrame, config: dict, cache_key=None) -> pd.DataFrame:
    """Signal-Spalten (_sig_dir, _sig_entry, _sig_sl, _sig_tp1, ...) fuer die Config."""
    if is_confluence(config):
        return precompute_confluence_signals(df, config, cache_key)
    df = precompute_indicators(df, config)
    return precompute_all_signals(df, config)
