# tests/test_confluence.py
# Fibo-Kanal-Konfluenz: Live-Plan (600 geschlossene Kerzen) == Backtest-Plan (volle Historie),
# Live-Zyklus (Order legen / nachziehen / aufraeumen) mit Mock-Exchange.

import os
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from fibot.strategy.confluence_logic import plan_both, plan_next_order, V2

CFG = {'market': {'symbol': 'BTC/USDT:USDT', 'timeframe': '4h'},
       'strategy': {'type': 'confluence', **V2, 'max_age_mult': None, 'candle_limit': 600},
       'risk': {'leverage': 5, 'risk_per_entry_pct': 1.0}}


def _df(seed=3, n=2600):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    trend = 100 + 0.02 * t + 8 * np.sin(t / 40) + np.cumsum(rng.normal(0, 0.6, n))
    close = trend
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) + rng.uniform(0.1, 1.2, n)
    low = np.minimum(open_, close) - rng.uniform(0.1, 1.2, n)
    idx = pd.date_range('2023-01-01', periods=n, freq='4h', tz='UTC')
    return pd.DataFrame({'open': open_, 'high': high, 'low': low, 'close': close, 'volume': 1.0}, index=idx)


def _real_or_synthetic():
    path = os.path.join(ROOT, 'data', 'cache', 'BTC-USDT-USDT_4h.csv')
    if os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df.tail(3000)
    return _df()


def test_live_plan_equals_backtest_plan():
    df = _real_or_synthetic()
    lo, sh = plan_both(df, CFG)
    limit = 600
    checked = mism = planned = 0
    for m in range(limit, len(df)):
        live = plan_next_order(df.iloc[m - limit:m], CFG)
        bt = None
        for d, pl in (('long', lo), ('short', sh)):
            if np.isfinite(pl['limit'][m]):
                bt = (d, pl['limit'][m], pl['sl'][m], pl['tp'][m])
                break
        checked += 1
        if bt is None and live is None:
            continue
        planned += 1
        if bt is None or live is None or bt[0] != live['direction'] \
                or not np.allclose(bt[1:], (live['limit'], live['sl'], live['tp']), rtol=1e-6):
            mism += 1
    assert planned > 0
    # ATR (EWM) haengt minimal von der Historienlaenge ab -> Toleranz 1 % der geplanten Kerzen
    assert mism <= max(1, planned // 100), f'{mism}/{planned} Plan-Abweichungen bei {checked} Kerzen'


def _mock_exchange(df_with_open, order_status='open'):
    ex = MagicMock()
    ex.exchange.parse_timeframe.return_value = 4 * 3600
    ex.fetch_recent_ohlcv.return_value = df_with_open
    ex.fetch_equity_usdt.return_value = 100.0
    ex.fetch_balance_usdt.return_value = 100.0
    ex.markets = {'BTC/USDT:USDT': {'limits': {'amount': {'min': 0.0001}}}}
    ex.amount_to_precision.side_effect = lambda s, a: f'{a:.4f}'
    ex.place_limit_order_with_tpsl.return_value = {'id': 'O1'}
    ex.fetch_order.return_value = {'status': order_status}
    return ex


def test_cycle_places_keeps_and_replaces(tmp_path):
    import fibot.utils.trade_manager as tm
    df = _real_or_synthetic()
    lo, sh = plan_both(df, CFG)
    planned = [m for m in range(700, len(df) - 1) if np.isfinite(lo['limit'][m]) or np.isfinite(sh['limit'][m])]
    if not planned:
        pytest.skip('kein Setup im Datenausschnitt')
    m = planned[0]
    # Fenster bis m-1 geschlossen + laufende Kerze m
    win = df.iloc[m - 600:m + 1]
    now = win.index[-1] + pd.Timedelta(minutes=5)
    store = {}
    with patch.object(tm, 'read_tracker', side_effect=lambda p: dict(store.get(p, {}))), \
         patch.object(tm, 'write_tracker', side_effect=lambda p, d: store.__setitem__(p, dict(d))), \
         patch.object(tm, 'send_message'), \
         patch('pandas.Timestamp.now', return_value=now):
        ex = _mock_exchange(win)
        tm.confluence_cycle(ex, CFG, {}, MagicMock())
        assert ex.place_limit_order_with_tpsl.call_count == 1
        tr = list(store.values())[0]
        assert tr['status'] == 'pending_entry'
        # gleicher Lauf, gleiche Kerze -> Order bleibt liegen
        tm.confluence_cycle(ex, CFG, {}, MagicMock())
        assert ex.place_limit_order_with_tpsl.call_count == 1
        ex.cancel_order.assert_not_called()
        # gefuellt und schon wieder geschlossen -> aufraeumen, kein neuer Entry fuer denselben Impuls
        ex.fetch_order.return_value = {'status': 'closed'}
        tm.confluence_cycle(ex, CFG, {}, MagicMock())
        ex.cancel_all_orders_for_symbol.assert_called()
