"""Safety tests for the research-only neural config selector."""

from dataclasses import replace
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from neural_selector_experiment import (
    Event, market_features, route_metrics, routing_scores, split_events,
)


def _event(entry, exit_, variant='v01', net_r=1.0, entry_idx=10, exit_idx=12):
    return Event(
        variant=variant, entry_idx=entry_idx, exit_idx=exit_idx,
        entry_time=pd.Timestamp(entry, tz='UTC').isoformat(),
        exit_time=pd.Timestamp(exit_, tz='UTC').isoformat(),
        features=[0.0], net_r=net_r, win_r=2.0, loss_r=-1.1,
        risk_pct=1.0, won=net_r > 0,
    )


def test_market_features_never_use_current_candle():
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 500)))
    spread = rng.uniform(0.1, 1.0, len(close))
    index = pd.date_range('2025-01-01', periods=len(close), freq='1h', tz='UTC')
    frame = pd.DataFrame({
        'open': close - spread / 4, 'high': close + spread,
        'low': close - spread, 'close': close,
        'volume': rng.uniform(10, 100, len(close)),
    }, index=index)
    original = market_features(frame, '1h')
    changed = frame.copy()
    changed.iloc[-1, changed.columns.get_loc('close')] *= 10
    changed.iloc[-1, changed.columns.get_loc('high')] *= 10
    changed.iloc[-1, changed.columns.get_loc('volume')] *= 100
    mutated = market_features(changed, '1h')
    pd.testing.assert_series_equal(original.iloc[-1], mutated.iloc[-1])


def test_split_excludes_labels_crossing_a_temporal_boundary():
    events = [
        _event('2025-10-01', '2025-10-02'),
        _event('2025-10-31', '2025-11-03'),
        _event('2026-01-01', '2026-01-02'),
        _event('2026-04-30', '2026-05-02'),
        _event('2026-06-01', '2026-06-02'),
    ]
    train, validation, test = split_events(events, '2025-11-02', '2026-05-01')
    assert [event.entry_time for event in train] == [events[0].entry_time]
    assert [event.entry_time for event in validation] == [events[2].entry_time]
    assert [event.entry_time for event in test] == [events[4].entry_time]


def test_router_selects_best_variant_and_obeys_open_trade_lock():
    first = _event('2026-06-01', '2026-06-02', 'v01', -1.0, 10, 12)
    better = replace(first, variant='v02', net_r=2.0, won=True)
    overlap = _event('2026-06-01 12:00', '2026-06-03', 'v03', 5.0, 11, 13)
    metrics = route_metrics([first, better, overlap], np.array([0.1, 0.9, 2.0]))
    assert metrics['trades'] == 1
    assert metrics['choices'] == {'v02': 1}
    assert metrics['pnl_pct'] == pytest.approx(2.0)


def test_win_probability_is_converted_to_expected_net_r():
    event = _event('2026-06-01', '2026-06-02')
    score = routing_scores([event], np.array([0.25]), 'win')
    assert score[0] == pytest.approx(0.25 * 2.0 + 0.75 * -1.1)
