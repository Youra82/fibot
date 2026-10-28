# tests/test_trend_filter.py
# Trendfilter "nur in Richtung des uebergeordneten Trends": kein Lookahead, Regel, Live == Backtest,
# Live-Zyklus legt gegen den Trend keine Order.

import os
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from fibot.strategy import trend_filter as tf

CFG = {**tf.DEFAULTS}


def _candles(n, freq, seed=1, start='2025-01-01'):
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, 1, n))
    idx = pd.date_range(start, periods=n, freq=freq, tz='UTC')
    return pd.DataFrame({'open': c, 'high': c + 1, 'low': c - 1, 'close': c, 'volume': 1.0}, index=idx)


def test_htf_trend_uses_only_closed_candles():
    df = _candles(2000, '1h')
    ts = df.index[1500]
    before = tf._value_at(tf.htf_trend(df, '1h', CFG), ts)
    changed = df.copy()
    changed.loc[changed.index >= ts, 'close'] *= 3      # Zukunft drastisch aendern
    after = tf._value_at(tf.htf_trend(changed, '1h', CFG), ts)
    assert before == after
    # ein HTF-Wert ist erst nach Schluss seiner 4h-Kerze bekannt
    s = tf.htf_trend(df, '1h', CFG)
    assert (s.index.minute == 0).all() and (s.index.hour % 4 == 0).all()


def test_daily_trend_known_after_day_close():
    d = _candles(200, '1D')
    s = tf.daily_trend(d, CFG)
    assert s.index[0] == d.index[CFG['daily_sma'] - 1] + pd.Timedelta(days=1)


def test_allowed_rule():
    idx = pd.DatetimeIndex([pd.Timestamp('2026-01-01', tz='UTC')])
    up, down = pd.Series([1.0], index=idx), pd.Series([0.0], index=idx)
    t = pd.Timestamp('2026-01-02', tz='UTC')
    assert tf.allowed('long', t, up, up) and not tf.allowed('long', t, up, down)
    assert tf.allowed('short', t, down, down) and not tf.allowed('short', t, down, up)
    assert not tf.allowed('long', pd.Timestamp('2025-12-31', tz='UTC'), up, up)   # unbekannt -> kein Trade
    sig = np.array([1, 2, 0, 1])
    ix = pd.DatetimeIndex([t] * 4)
    assert list(tf.mask_signals(sig, ix, up, up)) == [1, 0, 0, 1]


def _cached(symbol_file):
    path = os.path.join(ROOT, 'data', 'cache', symbol_file)
    if not os.path.exists(path):
        pytest.skip(f'kein Kerzen-Cache {symbol_file}')
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    return df


def test_live_decision_equals_backtest_on_real_candles():
    """Live (nur die letzten Kerzen wie vom Bot geladen) entscheidet wie der Backtest (volle Historie)."""
    from fibot.utils.trade_manager import _trend_filter_reject
    base = _cached('BTC-USDT-USDT_1h.csv').tail(6000)
    daily = _cached('BTC-USDT-USDT_1d.csv')
    htf_bt, day_bt = tf.htf_trend(base, '1h', CFG), tf.daily_trend(daily, CFG)
    need = tf.base_bars_needed(CFG)
    checked = mism = 0
    for m in range(need + 200, len(base), 97):
        now = base.index[m]
        ex = MagicMock()
        ex.fetch_recent_ohlcv.side_effect = lambda s, t, limit: (
            base.iloc[:m].tail(limit) if t == '1h' else daily[daily.index < now.floor('D') + pd.Timedelta(days=1)].tail(limit))
        for d in ('long', 'short'):
            with patch('pandas.Timestamp.now', return_value=now + pd.Timedelta(minutes=5)), \
                 patch.object(tf, 'settings', return_value=dict(CFG)):
                live_ok = _trend_filter_reject(ex, 'BTC/USDT:USDT', '1h', base.iloc[m - 600:m],
                                               {'direction': d}, now.isoformat(), MagicMock()) is None
            bt_ok = tf.allowed(d, now, htf_bt, day_bt)
            checked += 1
            mism += live_ok != bt_ok
    assert checked > 50
    assert mism <= max(1, checked // 100), f'{mism}/{checked} abweichende Entscheidungen'


def test_cycle_places_no_order_against_trend():
    import fibot.utils.trade_manager as tm
    plan = {'direction': 'long', 'limit': 100.0, 'sl': 99.0, 'tp': 104.0, 'rr': 4.0, 'a_ts': 'a', 'b_ts': 'b'}
    df = _candles(700, '4h', start='2026-01-01')
    now = df.index[-1] + pd.Timedelta(hours=4, minutes=5)
    store = {}
    cfg = {'market': {'symbol': 'BTC/USDT:USDT', 'timeframe': '4h'},
           'strategy': {'type': 'confluence', 'candle_limit': 600}, 'risk': {'leverage': 5, 'risk_per_entry_pct': 1.0}}
    ex = MagicMock()
    ex.exchange.parse_timeframe.return_value = 4 * 3600
    ex.fetch_recent_ohlcv.return_value = df
    with patch.object(tm, 'read_tracker', side_effect=lambda p: dict(store.get(p, {}))), \
         patch.object(tm, 'write_tracker', side_effect=lambda p, d: store.__setitem__(p, dict(d))), \
         patch.object(tm, 'send_message'), patch.object(tm, 'send_photo'), \
         patch('fibot.strategy.confluence_logic.plan_next_order', return_value=plan), \
         patch.object(tm, '_trend_filter_reject', return_value='4x4h ab, Tag ab'), \
         patch('pandas.Timestamp.now', return_value=now):
        tm.confluence_cycle(ex, cfg, {}, MagicMock())
    ex.place_limit_order_with_tpsl.assert_not_called()
