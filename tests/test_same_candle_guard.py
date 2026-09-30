# tests/test_same_candle_guard.py
# Regressionstest fuer den Live-vs-Backtest-Fund vom 30.09.2026: nach einem Exit
# hat der Live-Bot dieselbe, bereits verbrauchte 6h-Signalkerze in jedem 15-min-
# Cron-Tick erneut gehandelt (AAVE 17.09.: 24 Re-Entries in 11 h). Rein lokal,
# keine Bitget-Verbindung.

import os
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from fibot.utils import trade_manager as tm
from fibot.strategy.fibonacci_logic import FibSignal

SYMBOL, TF, TF_SEC = 'AAVE/USDT:USDT', '6h', 6 * 3600


@pytest.fixture(autouse=True)
def tmp_tracker(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, 'TRACKER_DIR', str(tmp_path))


def _df(last_open: str, n: int = 200) -> pd.DataFrame:
    idx = pd.date_range(end=pd.Timestamp(last_open, tz='UTC'), periods=n, freq='6h')
    return pd.DataFrame({'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.0, 'volume': 1.0}, index=idx)


def _exchange(positions, df):
    ex = MagicMock()
    ex.exchange.parse_timeframe.return_value = TF_SEC
    ex.fetch_open_positions.return_value = positions
    ex.fetch_recent_ohlcv.return_value = df
    ex.fetch_balance_usdt.return_value = 60.0
    ex.markets = {SYMBOL: {'limits': {'amount': {'min': 0.1}}}}
    ex.amount_to_precision.side_effect = lambda s, c: f"{c:.1f}"
    ex.place_limit_order.return_value = {'id': 'x'}
    ex.fetch_order.return_value = {'status': 'open'}
    return ex


def _signal():
    return FibSignal(direction='short', entry_price=100.0, sl_price=102.0, tp1_price=90.0,
                     tp2_price=85.0, score=9.0, reason='test', fib_levels=None,
                     structure=None, entry_fib_name='61.8', rr_ratio=5.0)


PARAMS = {'market': {'symbol': SYMBOL, 'timeframe': TF},
          'risk': {'leverage': 2, 'risk_per_entry_pct': 0.5},
          'strategy': {'min_signal_score': 1.0}}


def _run(ex, now):
    with patch.object(tm, 'generate_signal', return_value=_signal()) as gen, \
         patch.object(tm, 'send_message'), patch.object(tm, '_send_fib_chart'), \
         patch.object(tm, 'signal_summary', return_value=''), \
         patch.object(tm, 'housekeeper_routine'), patch.object(tm.time, 'sleep'), \
         patch.object(tm.pd.Timestamp, 'now', return_value=pd.Timestamp(now, tz='UTC')):
        tm.full_trade_cycle(ex, PARAMS, {}, MagicMock())
    return gen


def test_last_closed_candle_ts():
    now = pd.Timestamp('2026-09-17 13:00:53', tz='UTC')
    assert tm.last_closed_candle_ts(TF_SEC, now) == pd.Timestamp('2026-09-17 06:00', tz='UTC')


def test_first_tick_after_close_enters_once():
    # 12:00-Kerze offen -> letzte geschlossene 06:00; erster Tick handelt
    ex = _exchange([], _df('2026-09-17 12:00'))
    _run(ex, '2026-09-17 12:01')
    assert ex.place_limit_order.call_count == 1
    # zweiter Tick in derselben Kerze (Position inzwischen ausgestoppt): kein Re-Entry
    ex2 = _exchange([], _df('2026-09-17 12:00'))
    gen = _run(ex2, '2026-09-17 13:00')
    assert ex2.place_limit_order.call_count == 0
    assert gen.call_count == 0


def test_candle_closed_while_in_position_is_skipped():
    # 00:01 Entry auf 18:00-Kerze, Position laeuft bis 12:58 -> 06:00-Kerze schloss bei offener Position
    _run(_exchange([], _df('2026-09-17 00:00')), '2026-09-17 00:01')
    pos = [{'side': 'short', 'contracts': 0.1, 'entryPrice': 119.43, 'unrealizedPnl': 0}]
    ex_pos = _exchange(pos, _df('2026-09-17 12:00'))
    ex_pos.fetch_open_trigger_orders.return_value = []
    _run(ex_pos, '2026-09-17 12:45')
    assert tm.read_consumed_candle(SYMBOL, TF) == pd.Timestamp('2026-09-17 06:00', tz='UTC')
    # 13:00 flat: letzte geschlossene Kerze (06:00) ist verbraucht -> kein Trade (vorher: 24 Re-Entries)
    ex = _exchange([], _df('2026-09-17 12:00'))
    _run(ex, '2026-09-17 13:00')
    assert ex.place_limit_order.call_count == 0


def test_next_candle_trades_again():
    _run(_exchange([], _df('2026-09-17 12:00')), '2026-09-17 12:01')
    ex = _exchange([], _df('2026-09-17 18:00'))
    _run(ex, '2026-09-17 18:01')
    assert ex.place_limit_order.call_count == 1


def test_guard_survives_tracker_wipe():
    _run(_exchange([], _df('2026-09-17 12:00')), '2026-09-17 12:01')
    tm.write_tracker(tm.get_tracker_path(SYMBOL, TF), {})  # Housekeeper/Overshoot leeren den Tracker
    assert tm.read_consumed_candle(SYMBOL, TF) == pd.Timestamp('2026-09-17 06:00', tz='UTC')
