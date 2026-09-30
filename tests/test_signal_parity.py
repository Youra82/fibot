# tests/test_signal_parity.py
# Regressionstest fuer den Live-vs-Backtest-Fund vom 30.09.2026: generate_signal (live,
# 499 geschlossene Kerzen) und precompute_all_signals (Backtest, volle Historie) wichen
# bei 60 von 794 Kerzen ab, weil der Live-Pfad Swing-Pivots auf einem abgeschnittenen
# Fenster suchte. Jetzt muessen beide Kerze fuer Kerze identisch sein. Rein lokal.

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from fibot.strategy.fibonacci_logic import (
    generate_signal, precompute_indicators, precompute_all_signals, find_significant_swings,
)


def _random_walk(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    spread = np.abs(rng.normal(0, 0.01, n)) * close
    idx = pd.date_range('2025-01-01', periods=n, freq='6h', tz='UTC')
    return pd.DataFrame({'open': close, 'high': close + spread, 'low': close - spread,
                         'close': close, 'volume': rng.uniform(50, 150, n)}, index=idx)


def _config(swing_lookback, pivot_left, pivot_right):
    return {'strategy': {'swing_lookback': swing_lookback, 'pivot_left': pivot_left,
                         'pivot_right': pivot_right, 'structure_lookback': 60,
                         'min_signal_score': 3.0, 'min_rr': 1.0, 'volume_ratio_min': 0.8,
                         'fib_tp1_level': 1.0, 'fib_tp2_level': 1.272, 'candle_limit': 500}}


@pytest.mark.parametrize('swing_lookback,pl,pr,seed', [
    (20, 7, 4, 1), (50, 1, 2, 2), (100, 5, 5, 3), (200, 2, 7, 4),
])
def test_live_signal_equals_backtest_signal(swing_lookback, pl, pr, seed):
    cfg = _config(swing_lookback, pl, pr)
    df = _random_walk(1400, seed)
    bt = precompute_all_signals(precompute_indicators(df, cfg), cfg)
    limit = cfg['strategy']['candle_limit'] - 1
    n_sig = 0
    for i in range(900, len(df)):
        live = generate_signal(df.iloc[i - limit + 1: i + 1], cfg)
        b_dir = {0: 'none', 1: 'long', 2: 'short'}[int(bt['_sig_dir'].iloc[i])]
        assert live.direction == b_dir, f"Bar {i}: live={live.direction} bt={b_dir}"
        if b_dir != 'none':
            n_sig += 1
            assert live.sl_price == pytest.approx(bt['_sig_sl'].iloc[i], rel=1e-6)
            assert live.tp1_price == pytest.approx(bt['_sig_tp1'].iloc[i], rel=1e-6)
    assert n_sig > 0, "Test ohne ein einziges Signal waere wertlos"


def test_find_significant_swings_uses_full_context():
    # Pivot direkt am Fensteranfang: nur mit linkem Kontext als Pivot erkennbar
    df = _random_walk(300, 7)
    lookback, order = 50, 5
    sw = find_significant_swings(df, lookback, order, order)
    start = len(df) - 1 - lookback
    assert sw is not None
    assert start + sw.high_idx <= len(df) - 1 - order
    assert start + sw.low_idx <= len(df) - 1 - order
