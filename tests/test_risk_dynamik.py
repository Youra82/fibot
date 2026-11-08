# tests/test_risk_dynamik.py -- Kontoverlauf-Anpassung: Fehlerfaelle aus dem Codex-Review Runde 2
# (Parallelzugriffe, Kapitalbewegungen, beschaedigter Zustand, Reset/Protokoll, Storno-Fehler, Margin, Kerzenraster).
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


def _parallel_observe(args):
    path, hist, equity = args
    from fibot.utils import risk_cap as rc
    rc.HISTORY_FILE = hist
    for _ in range(20):
        rc.observe_equity(equity, path=path)
    return equity


def test_hoechststand_sinkt_nie_auch_bei_parallelen_prozessen(tmp_path):
    from multiprocessing import Pool
    path, hist = str(tmp_path / 'peak.json'), str(tmp_path / 'h.jsonl')
    risk_cap.observe_equity(100., path=path)
    with Pool(6) as pool:
        pool.map(_parallel_observe, [(path, hist, e) for e in (101., 150., 120., 110., 149., 105.)])
    assert json.load(open(path))['peak'] == 150.


def test_ein_und_auszahlungen_erzeugen_keinen_drawdown(tmp_path):
    path = str(tmp_path / 'peak.json')
    assert risk_cap.observe_equity(1000., path=path, now_ms=1_000) == 1000.             # Start (Ausgangspunkt 1000)
    peak = risk_cap.observe_equity(850., flows=[('b1', 2_000, -150.)], path=path, now_ms=3_000)   # Auszahlung 150
    assert peak == 850. and risk_cap.drawdown_factor(850., peak) == 1.0
    assert risk_cap.observe_equity(850., flows=[('b1', 2_000, -150.)], path=path, now_ms=4_000) == 850.  # nicht doppelt
    risk_cap.observe_equity(722.5, path=path, now_ms=5_000)                             # 15 % Handelsverlust
    peak = risk_cap.observe_equity(1222.5, flows=[('b2', 6_000, 500.)], path=path, now_ms=7_000)   # Einzahlung 500
    assert peak == 1350.                                                                # Drawdown bleibt sichtbar
    assert risk_cap.drawdown_factor(1222.5, peak) == pytest.approx(1 - (1 - 1222.5 / 1350) / .30)


@pytest.mark.parametrize('inhalt', ['{kaputt', '{"peak": NaN}', '{"peak": -5}', '[]', '{"peak": "x"}'])
def test_beschaedigter_hoechststand_scheitert_sichtbar(tmp_path, inhalt):
    path = tmp_path / 'peak.json'
    path.write_text(inhalt)
    with pytest.raises(ValueError):
        risk_cap.observe_equity(100., path=str(path))


def test_reset_protokolliert_und_peak_at(tmp_path):
    path = str(tmp_path / 'peak.json')
    risk_cap.observe_equity(1000., path=path, now_ms=1_000)
    risk_cap.observe_equity(1200., path=path, now_ms=2_000)
    assert risk_cap.peak_at(1_500)['peak'] == 1000.
    assert risk_cap.peak_at(2_500)['peak'] == 1200.
    risk_cap.reset_peak(900., 'Test-Neustart', path=path)
    lines = [json.loads(x) for x in open(risk_cap.HISTORY_FILE, encoding='utf-8')]
    assert any(e['event'] == 'reset' and e['grund'] == 'Test-Neustart' and e['alter_peak'] == 1200. for e in lines)
    with pytest.raises(ValueError):
        risk_cap.reset_peak(900., '', path=path)


def test_kontostand_null_wird_nicht_beobachtet(tmp_path):
    with pytest.raises(ValueError):
        risk_cap.observe_equity(0., path=str(tmp_path / 'p.json'))


def test_cap_null_bedeutet_ueberall_keine_obergrenze():
    assert risk_cap.capped_risk_pct(3.0, cap=0) == 3.0


def test_klassisch_margin_gegen_freies_guthaben():
    from fibot.utils.trade_manager import calc_position_size
    assert calc_position_size(1000., 1.0, 100., 99., 2, LOG, free_balance=5.) == 0.0
    assert calc_position_size(1000., 1.0, 100., 99., 2, LOG, free_balance=1000.) == pytest.approx(10.)


def test_storno_fehler_erzeugt_keine_zweite_order():
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
        assert ex.place_limit_order_with_tpsl.call_count == 1
        key = list(store)[0]
        store[key]['candle_ts'] = 'alt'                                  # neuer Plan -> Storno noetig
        ex.cancel_order.side_effect = RuntimeError('API weg')
        tm.confluence_cycle(ex, CFG, {}, MagicMock())
        assert ex.place_limit_order_with_tpsl.call_count == 1            # KEINE Ersatzorder
        assert store[key]['status'] == 'pending_entry'                   # Tracker bleibt
        ex.cancel_order.side_effect = None
        ex.cancel_order.return_value = None                              # Order weg ...
        ex.fetch_order.return_value = {'status': 'closed'}               # ... weil gefuellt
        store[key]['candle_ts'] = 'alt'
        tm.confluence_cycle(ex, CFG, {}, MagicMock())
        assert ex.place_limit_order_with_tpsl.call_count == 1


def _frame(freq, n, sig_at):
    idx = pd.date_range('2026-01-01', periods=n, freq=freq, tz='UTC')
    d = pd.DataFrame({'open': 100., 'high': 100.2, 'low': 99.8, 'close': 100., 'volume': 1.}, index=idx)
    for col, v in (('_sig_dir', 0), ('_sig_entry', 0.), ('_sig_sl', 0.), ('_sig_tp1', 0.), ('_sig_score', 0.),
                   ('_sig_instant', False), ('_sig_swing_high', 0.), ('_sig_swing_low', 0.)):
        d[col] = v
    if sig_at is not None:
        d.iloc[sig_at, d.columns.get_loc('_sig_dir')] = 1
        d.iloc[sig_at, [d.columns.get_loc(c) for c in ('_sig_entry', '_sig_sl', '_sig_tp1')]] = [100., 90., 200.]
        d.iloc[sig_at + 1:, d.columns.get_loc('close')] = 110.
        d.iloc[sig_at + 1:, d.columns.get_loc('high')] = 110.2
        d.iloc[sig_at + 1:, d.columns.get_loc('low')] = 109.8
    return d


def test_simulator_kein_kuenstlicher_drawdown_bei_unterschiedlichen_rastern():
    from fibot.analysis import portfolio_simulator as ps
    cfg = lambda s, tf: {'market': {'symbol': s, 'timeframe': tf}, 'strategy': {'type': 'confluence'},
                         'risk': {'leverage': 10, 'risk_per_entry_pct': 1.0}}
    sd = {'a': {'symbol': 'A/USDT:USDT', 'timeframe': '1h', 'df': _frame('1h', 6, 0), 'config': cfg('A/USDT:USDT', '1h')},
          'b': {'symbol': 'B/USDT:USDT', 'timeframe': '30m', 'df': _frame('30min', 12, None), 'config': cfg('B/USDT:USDT', '30m')}}
    with patch.object(ps, 'max_risk_pct', return_value=1.0), \
         patch.object(ps, 'dynamic_settings', return_value=dict(risk_cap.DEFAULT_DYNAMIC)):
        res = ps.run_portfolio_simulation(1000., sd, '2026-01-01', '2026-01-02')
    assert res['trade_count'] == 0                                       # Position bleibt offen (Ziel 200)
    assert res['max_drawdown_pct'] < 0.01                                # offener Gewinn verschwindet nicht zwischendurch
