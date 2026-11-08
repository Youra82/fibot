# tests/test_risk_dynamik2.py -- Fehlerfaelle aus dem Codex-Review Runde 3
import json
import logging
import os
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))
from fibot.utils import risk_cap  # noqa: E402

LOG = logging.getLogger('test')


@pytest.fixture
def dyn_an(monkeypatch):
    monkeypatch.setattr(risk_cap, 'dynamic_settings', lambda settings_file=None: dict(risk_cap.DEFAULT_DYNAMIC))


def test_observe_account_erster_lauf_und_auszahlung(dyn_an):
    import fibot.utils.trade_manager as tm
    ex = MagicMock()
    ex.fetch_equity_usdt.return_value = 1000.
    tm.observe_account(ex, LOG)                                         # erster Lauf: Startpunkt
    assert risk_cap.current_peak() == 1000.
    ex.fetch_equity_usdt.return_value = 800.
    ex.fetch_cash_flows.return_value = [('w1', 10**13, -200.)]          # Auszahlung 200 in beiden Auszuegen
    tm.observe_account(ex, LOG)
    assert risk_cap.current_peak() == 800.                              # kein kuenstlicher Drawdown


def test_observe_account_verwirft_unpassende_auszuege(dyn_an):
    import fibot.utils.trade_manager as tm
    ex = MagicMock()
    ex.fetch_equity_usdt.return_value = 1000.
    tm.observe_account(ex, LOG)
    ex.fetch_equity_usdt.return_value = 1500.                           # Einzahlung schon im Kontostand ...
    ex.fetch_cash_flows.side_effect = [[], [('d1', 10**13, 500.)]]      # ... aber erst im zweiten Auszug sichtbar
    tm.observe_account(ex, LOG)
    assert risk_cap.current_peak() == 1000.                             # keine Fortschreibung in diesem Lauf
    ex.fetch_cash_flows.side_effect = None
    ex.fetch_cash_flows.return_value = [('d1', 10**13, 500.)]
    tm.observe_account(ex, LOG)
    assert risk_cap.current_peak() == 1500.                             # Einzahlung genau einmal (nicht 2000)


def test_observe_account_api_fehler_aendert_nichts(dyn_an):
    import fibot.utils.trade_manager as tm
    ex = MagicMock()
    ex.fetch_equity_usdt.return_value = 1000.
    tm.observe_account(ex, LOG)
    ex.fetch_equity_usdt.return_value = 1500.
    ex.fetch_cash_flows.side_effect = RuntimeError('API weg')
    tm.observe_account(ex, LOG)
    assert risk_cap.current_peak() == 1000.


def test_live_risk_pct_liest_nur(dyn_an):
    risk_cap.observe_equity(1000.)
    assert risk_cap.live_risk_pct(1.0, 850.) == pytest.approx(0.5)
    assert risk_cap.live_risk_pct(1.0, 1500.) == pytest.approx(1.0)     # ueber dem Hoch: voll, aber ...
    assert risk_cap.current_peak() == 1000.                             # ... ohne den Hoechststand zu veraendern


def test_peak_at_kausal_und_nach_zeitstempel():
    p = risk_cap.PEAK_FILE
    risk_cap.observe_equity(1000., path=p, now_ms=1_000)
    risk_cap.observe_equity(1100., path=p, now_ms=3_000)
    risk_cap.observe_equity(1100., flows=[('d', 2_000, 400.)], path=p, now_ms=4_000)   # Buchung 2000, beobachtet 4000
    assert risk_cap.peak_at(2_500)['peak'] == 1000.                     # kein Wissen aus spaeteren Beobachtungen
    assert risk_cap.peak_at(3_500)['peak'] == 1100.
    assert risk_cap.peak_at(4_500)['peak'] == 1500.


def test_bill_vorzeichen_aus_buchungstyp():
    from fibot.utils.exchange import Exchange
    ex = Exchange.__new__(Exchange)
    ex.markets = {'x': {}}
    ex.exchange = MagicMock()
    ex.exchange.privateMixGetV2MixAccountBill.return_value = {'data': {'bills': [
        {'billId': '1', 'cTime': '1', 'amount': '50', 'businessType': 'trans_to_exchange'},     # raus, positiv gemeldet
        {'billId': '2', 'cTime': '2', 'amount': '-70', 'businessType': 'trans_from_exchange'},  # rein, negativ gemeldet
        {'billId': '3', 'cTime': '3', 'amount': '9', 'businessType': 'open_long'},              # kein Kapitalfluss
    ]}}
    rows = ex.fetch_cash_flows(0)
    assert sorted(rows) == [('1', 1, -50.), ('2', 2, 70.)]


def test_tracker_after_close_behaelt_verbrauchte_impulse():
    from fibot.utils.trade_manager import tracker_after_close
    t = tracker_after_close({'status': 'open', 'b_ts': 'B2', 'consumed_b': ['B1'], 'notified_b_ts': 'B2', 'order_id': 'x'})
    assert t == {'consumed_b': ['B1', 'B2'], 'notified_b_ts': 'B2'}


def test_unbekannter_orderstatus_keine_zweite_order():
    import fibot.utils.trade_manager as tm
    from test_confluence import CFG, _mock_exchange, _real_or_synthetic
    from fibot.strategy.confluence_logic import plan_both
    df = _real_or_synthetic()
    lo, sh = plan_both(df, CFG)
    planned = [m for m in range(700, len(df) - 1) if np.isfinite(lo['limit'][m]) or np.isfinite(sh['limit'][m])]
    if not planned:
        pytest.skip('kein Setup im Datenausschnitt')
    m = planned[0]
    win = df.iloc[m - 600:m + 1]
    now = win.index[-1] + pd.Timedelta(minutes=5)
    store = {}
    with patch.object(tm, 'read_tracker', side_effect=lambda p: dict(store.get(p, {}))), \
         patch.object(tm, 'write_tracker', side_effect=lambda p, d: store.__setitem__(p, dict(d))), \
         patch.object(tm, 'send_message'), patch.object(tm, 'send_photo'), \
         patch.object(tm, '_trend_filter_reject', return_value=None), \
         patch('pandas.Timestamp.now', return_value=now):
        ex = _mock_exchange(win)
        tm.confluence_cycle(ex, CFG, {}, MagicMock())
        key = list(store)[0]
        store[key]['candle_ts'] = 'alt'
        ex.fetch_order.side_effect = RuntimeError('API weg')            # Status nicht abrufbar
        tm.confluence_cycle(ex, CFG, {}, MagicMock())
        assert ex.place_limit_order_with_tpsl.call_count == 1
        ex.cancel_order.assert_not_called()
        assert store[key]['status'] == 'pending_entry'


def test_notschliessung_behaelt_impulssperre_im_echten_ablauf():
    """Gefuellt + per Notschliessung geschlossen -> naechster Lauf handelt denselben Impuls NICHT erneut."""
    import fibot.utils.trade_manager as tm
    from test_confluence import CFG, _mock_exchange, _real_or_synthetic
    from fibot.strategy.confluence_logic import plan_both
    df = _real_or_synthetic()
    lo, sh = plan_both(df, CFG)
    planned = [m for m in range(700, len(df) - 1) if np.isfinite(lo['limit'][m]) or np.isfinite(sh['limit'][m])]
    if not planned:
        pytest.skip('kein Setup im Datenausschnitt')
    m = planned[0]
    win = df.iloc[m - 600:m + 1]
    now = win.index[-1] + pd.Timedelta(minutes=5)
    store = {}
    with patch.object(tm, 'read_tracker', side_effect=lambda p: dict(store.get(p, {}))), \
         patch.object(tm, 'write_tracker', side_effect=lambda p, d: store.__setitem__(p, dict(d))), \
         patch.object(tm, 'send_message'), patch.object(tm, 'send_photo'), \
         patch.object(tm, '_trend_filter_reject', return_value=None), \
         patch('pandas.Timestamp.now', return_value=now):
        ex = _mock_exchange(win)
        tm.confluence_cycle(ex, CFG, {}, MagicMock())
        key = list(store)[0]
        store[key] = tm.tracker_after_close(dict(store[key], status='open'))   # wie Notschliessung
        tm.confluence_cycle(ex, CFG, {}, MagicMock())
        assert ex.place_limit_order_with_tpsl.call_count == 1                 # kein zweiter Einstieg


# ---------------------------------------------------------------- Codex Runde 4
def test_einzahlung_vor_dem_start_zaehlt_nie(tmp_path):
    p = str(tmp_path / 'peak.json')
    risk_cap.observe_equity(1500., [], path=p, now_ms=10_000)                    # Start nach Einzahlung (Bill bei 9000)
    peak = risk_cap.observe_equity(1500., [('d', 9_000, 500.)], path=p, now_ms=20_000)   # Ueberlappung liefert alten Bill
    assert peak == 1500.


def test_veralteter_snapshot_wird_verworfen(tmp_path):
    p = str(tmp_path / 'peak.json')
    risk_cap.observe_equity(1000., [], path=p, now_ms=1_000)
    v_a = risk_cap.state_version(p)                                              # Prozess A beginnt (vor Auszahlung)
    v_b = risk_cap.state_version(p)                                              # Prozess B beginnt
    assert risk_cap.observe_equity(800., [('w', 2_000, -200.)], path=p, now_ms=3_000, expected_version=v_b) == 800.
    assert risk_cap.observe_equity(1000., [], path=p, now_ms=4_000, expected_version=v_a) is None   # veraltet
    assert json.load(open(p))['peak'] == 800.


def test_bill_ids_nach_zeit_nicht_nach_anzahl(tmp_path):
    p = str(tmp_path / 'peak.json')
    risk_cap.observe_equity(1000., [], path=p, now_ms=1_000)
    bills = [(f'b{i}', 2_000 + i, 1.) for i in range(501)]
    a = risk_cap.observe_equity(1000., bills, path=p, now_ms=10_000)
    b = risk_cap.observe_equity(1000., bills, path=p, now_ms=11_000)            # gleicher Auszug erneut
    assert a == b == 1501.


def _setup_pending(tm, store):
    from test_confluence import CFG, _mock_exchange, _real_or_synthetic
    from fibot.strategy.confluence_logic import plan_both
    df = _real_or_synthetic()
    lo, sh = plan_both(df, CFG)
    planned = [m for m in range(700, len(df) - 1) if np.isfinite(lo['limit'][m]) or np.isfinite(sh['limit'][m])]
    if not planned:
        pytest.skip('kein Setup im Datenausschnitt')
    m = planned[0]
    win = df.iloc[m - 600:m + 1]
    return CFG, _mock_exchange(win), win.index[-1] + pd.Timedelta(minutes=5)


@pytest.mark.parametrize('fall', ['teilfuellung_im_storno', 'unbekannter_status'])
def test_keine_volle_ersatzorder(fall):
    import fibot.utils.trade_manager as tm
    store = {}
    cfg, ex, now = _setup_pending(tm, store)
    with patch.object(tm, 'read_tracker', side_effect=lambda p: dict(store.get(p, {}))), \
         patch.object(tm, 'write_tracker', side_effect=lambda p, d: store.__setitem__(p, dict(d))), \
         patch.object(tm, 'send_message'), patch.object(tm, 'send_photo'), \
         patch.object(tm, '_trend_filter_reject', return_value=None), \
         patch('pandas.Timestamp.now', return_value=now):
        tm.confluence_cycle(ex, cfg, {}, MagicMock())
        key = list(store)[0]
        store[key]['candle_ts'] = 'alt'
        if fall == 'teilfuellung_im_storno':
            ex.cancel_order.side_effect = None
            ex.cancel_order.return_value = {'id': 'old', 'status': 'canceled', 'filled': 2}
        else:
            ex.fetch_order.return_value = {'status': 'mystery'}
        tm.confluence_cycle(ex, cfg, {}, MagicMock())
        assert ex.place_limit_order_with_tpsl.call_count == 1


# ---------------------------------------------------------------- Codex Runde 5
@pytest.mark.parametrize('storno_antwort', [None, {'id': 'O1', 'status': 'canceled', 'filled': 0}])
def test_nach_storno_noch_offen_keine_ersatzorder(storno_antwort):
    import fibot.utils.trade_manager as tm
    store = {}
    cfg, ex, now = _setup_pending(tm, store)
    with patch.object(tm, 'read_tracker', side_effect=lambda p: dict(store.get(p, {}))),          patch.object(tm, 'write_tracker', side_effect=lambda p, d: store.__setitem__(p, dict(d))),          patch.object(tm, 'send_message'), patch.object(tm, 'send_photo'),          patch.object(tm, '_trend_filter_reject', return_value=None),          patch('pandas.Timestamp.now', return_value=now):
        tm.confluence_cycle(ex, cfg, {}, MagicMock())
        key = list(store)[0]
        old_id = store[key]['order_id']
        store[key]['candle_ts'] = 'alt'
        ex.cancel_order.side_effect = None
        ex.cancel_order.return_value = storno_antwort
        ex.fetch_order.side_effect = None
        ex.fetch_order.return_value = {'status': 'open', 'filled': 0}      # Storno noch nicht bestaetigt
        tm.confluence_cycle(ex, cfg, {}, MagicMock())
        assert ex.place_limit_order_with_tpsl.call_count == 1
        assert store[key]['order_id'] == old_id                              # Tracker zeigt weiter die alte Order


def test_beendete_teilfuellung_ohne_position_verbraucht_impuls():
    import fibot.utils.trade_manager as tm
    store = {}
    cfg, ex, now = _setup_pending(tm, store)
    with patch.object(tm, 'read_tracker', side_effect=lambda p: dict(store.get(p, {}))),          patch.object(tm, 'write_tracker', side_effect=lambda p, d: store.__setitem__(p, dict(d))),          patch.object(tm, 'send_message'), patch.object(tm, 'send_photo'),          patch.object(tm, '_trend_filter_reject', return_value=None),          patch('pandas.Timestamp.now', return_value=now):
        tm.confluence_cycle(ex, cfg, {}, MagicMock())
        key = list(store)[0]
        b_ts = store[key]['b_ts']
        ex.fetch_order.side_effect = None
        ex.fetch_order.return_value = {'status': 'canceled', 'filled': 1.5}  # teilgefuellt + beendet
        ex.fetch_open_positions.return_value = []                            # Position schon wieder zu
        tm.confluence_cycle(ex, cfg, {}, MagicMock())
        assert b_ts in store[key]['consumed_b']                              # nicht dauerhaft blockiert ...
        assert ex.place_limit_order_with_tpsl.call_count == 1                # ... und kein Neueinstieg in denselben Impuls


def test_strikte_positionsabfrage_meldet_unlesbare_daten():
    from fibot.utils.exchange import Exchange
    ex = Exchange.__new__(Exchange)
    ex.markets = {'X/USDT:USDT': {}}
    ex.exchange = MagicMock()
    ex.exchange.fetch_positions.return_value = [{'contracts': 'invalid', 'initialMargin': 10}]
    with pytest.raises(RuntimeError):
        ex.fetch_open_positions('X/USDT:USDT', strict=True)
    assert ex.fetch_open_positions('X/USDT:USDT') == []                  # nicht-strikt wie bisher
