# tests/test_risk_cap.py -- Risiko-Obergrenze je Einstieg (risk_cap.py): Werteprüfung und VERHALTEN im Live-Sizing,
# in der liegenden Order und im Portfolio-Simulator (Codex-Review 08.11.2026: keine reinen Quelltext-Prüfungen).
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


def _settings(tmp_path, live):
    p = tmp_path / 'settings.json'
    p.write_text(json.dumps({'live_trading_settings': live}))
    return str(p)


# ---------------------------------------------------------------- Werte
def test_standard_und_eigene_werte(tmp_path):
    assert risk_cap.max_risk_pct(_settings(tmp_path, {})) == 1.0                       # fehlt -> 1 %
    assert risk_cap.max_risk_pct(str(tmp_path / 'fehlt.json')) == 1.0                  # Datei fehlt -> 1 %
    assert risk_cap.capped_risk_pct(3.0, settings_file=_settings(tmp_path, {})) == 1.0
    assert risk_cap.capped_risk_pct(0.5, settings_file=_settings(tmp_path, {})) == 0.5   # kleiner bleibt
    assert risk_cap.capped_risk_pct(3.0, settings_file=_settings(tmp_path, {'max_risk_per_entry_pct': 0.5})) == 0.5
    assert risk_cap.capped_risk_pct(3.0, settings_file=_settings(tmp_path, {'max_risk_per_entry_pct': None})) == 3.0
    assert risk_cap.capped_risk_pct(3.0, settings_file=_settings(tmp_path, {'max_risk_per_entry_pct': 0})) == 3.0
    assert risk_cap.capped_risk_pct(3.0, cap=2.0) == 2.0                                 # eingefrorener Wert
    assert risk_cap.capped_risk_pct(3.0, cap=None) == 3.0


@pytest.mark.parametrize('bad', [-1, float('nan'), float('inf'), True, '1'])
def test_ungueltige_obergrenze_scheitert_sichtbar(tmp_path, bad):
    with pytest.raises(ValueError):
        risk_cap.max_risk_pct(_settings(tmp_path, {'max_risk_per_entry_pct': bad}))


@pytest.mark.parametrize('bad', [-2, float('nan'), float('inf'), False, None])
def test_ungueltiges_config_risiko_scheitert_sichtbar(bad):
    with pytest.raises(ValueError):
        risk_cap.capped_risk_pct(bad, cap=1.0)


def test_kaputte_settings_struktur(tmp_path):
    p = tmp_path / 's.json'; p.write_text(json.dumps({'live_trading_settings': None}))
    with pytest.raises(ValueError):
        risk_cap.max_risk_pct(str(p))


# ---------------------------------------------------------------- Live-Sizing
def test_calc_position_size_hebt_nicht_auf_mindestmenge_an():
    from fibot.utils.trade_manager import calc_position_size
    # 34 USDT, 1 % -> 0,34 USDT Risiko, 1 USDT Stopabstand -> 0,34 Einheiten < Minimum 1 -> KEIN Trade (frueher: 1 = 2,9 %)
    assert calc_position_size(34., 1.0, 100., 99., 10, LOG, min_contracts=1.0) == 0.0
    c = calc_position_size(34., 1.0, 100., 99., 10, LOG, min_contracts=0.1)
    assert c == pytest.approx(0.34) and c * 1.0 <= 34 * .01 + 1e-12          # Risiko exakt 1 %


def _ex(equity=34., free=34., min_amt=0.0, prec=lambda a: f'{a:.6f}'):
    ex = MagicMock()
    ex.fetch_equity_usdt.return_value = equity; ex.fetch_balance_usdt.return_value = free
    ex.markets = {'X/USDT:USDT': {'limits': {'amount': {'min': min_amt}}}}
    ex.amount_to_precision.side_effect = lambda s, a: prec(a)
    return ex


def test_confluence_size_gedeckelt_und_ohne_aufrunden():
    from fibot.utils.trade_manager import _confluence_size
    plan = {'limit': 100., 'sl': 98.}                                           # 2 USDT Stopabstand
    c = _confluence_size(_ex(equity=1000., free=1000.), 'X/USDT:USDT', plan, 1.0, 10, LOG)
    assert c * 2 == pytest.approx(10.0, rel=1e-6)                              # 1 % von 1000 = 10 USDT Stoprisiko
    assert _confluence_size(_ex(min_amt=1.0), 'X/USDT:USDT', plan, 1.0, 10, LOG) == 0.0     # unter Minimum -> keine Order
    up = _ex(equity=1000., free=1000., prec=lambda a: f'{a + 1:.6f}')             # Rundung erhoeht Menge -> keine Order
    assert _confluence_size(up, 'X/USDT:USDT', plan, 1.0, 10, LOG) == 0.0


def test_confluence_cycle_nutzt_obergrenze_und_ersetzt_zu_grosse_liegende_order(tmp_path):
    import fibot.utils.trade_manager as tm
    from test_confluence import CFG, _mock_exchange, _real_or_synthetic
    from fibot.strategy.confluence_logic import plan_both
    df = _real_or_synthetic(); lo, sh = plan_both(df, CFG)
    planned = [m for m in range(700, len(df) - 1) if np.isfinite(lo['limit'][m]) or np.isfinite(sh['limit'][m])]
    if not planned:
        pytest.skip('kein Setup im Datenausschnitt')
    m = planned[0]; win = df.iloc[m - 600:m + 1]; now = win.index[-1] + pd.Timedelta(minutes=5)
    cfg = {**CFG, 'risk': {'leverage': 5, 'risk_per_entry_pct': 3.0}}             # Config will 3 %
    store = {}; sizes = []
    with patch.object(tm, 'read_tracker', side_effect=lambda p: dict(store.get(p, {}))), \
         patch.object(tm, 'write_tracker', side_effect=lambda p, d: store.__setitem__(p, dict(d))), \
         patch.object(tm, 'send_message'), patch.object(tm, 'send_photo'), \
         patch.object(tm, '_trend_filter_reject', return_value=None), \
         patch.object(tm, 'capped_risk_pct', side_effect=lambda r: risk_cap.capped_risk_pct(r, cap=1.0)), \
         patch('pandas.Timestamp.now', return_value=now):
        ex = _mock_exchange(win)
        ex.place_limit_order_with_tpsl.side_effect = lambda s, side, c, lim, sl, tp: sizes.append((c, lim, sl)) or {'id': f'O{len(sizes)}'}
        tm.confluence_cycle(ex, cfg, {}, MagicMock())
        c, lim, sl = sizes[-1]
        assert c * abs(lim - sl) <= 100.0 * 0.01 * (1 + 1e-6)                     # gehandelt mit 1 %, nicht 3 %
        # liegende Order kuenstlich zu gross (z. B. vor Senkung der Obergrenze platziert) -> wird ersetzt
        key = list(store)[0]; store[key]['contracts'] = c * 3
        tm.confluence_cycle(ex, cfg, {}, MagicMock())
        assert ex.cancel_order.call_count == 1 and len(sizes) == 2
        # passende liegende Order bleibt liegen
        tm.confluence_cycle(ex, cfg, {}, MagicMock())
        assert ex.cancel_order.call_count == 1 and len(sizes) == 2


# ---------------------------------------------------------------- Portfolio-Simulator (Teamauswahl)
def test_portfolio_simulator_rechnet_mit_obergrenze_und_meldet_sie():
    from fibot.analysis import portfolio_simulator as ps
    idx = pd.date_range('2026-01-01', periods=6, freq='1h', tz='UTC')
    df = pd.DataFrame({'open': 100., 'high': 100.5, 'low': 99.5, 'close': 100., 'volume': 1.}, index=idx)
    df['_sig_dir'] = 0; df['_sig_entry'] = 0.; df['_sig_sl'] = 0.; df['_sig_tp1'] = 0.; df['_sig_score'] = 0.
    df['_sig_instant'] = False; df['_sig_swing_high'] = 0.; df['_sig_swing_low'] = 0.
    df.iloc[1, df.columns.get_loc('_sig_dir')] = 1
    df.iloc[1, [df.columns.get_loc(c) for c in ('_sig_entry', '_sig_sl', '_sig_tp1')]] = [100., 98., 110.]
    df.iloc[2, df.columns.get_loc('low')] = 97.                                    # Stop wird getroffen -> -1 R
    cfg = {'market': {'symbol': 'X/USDT:USDT', 'timeframe': '1h'}, 'strategy': {'type': 'confluence'},
           'risk': {'leverage': 10, 'risk_per_entry_pct': 3.0}}
    with patch.object(ps, 'max_risk_pct', return_value=1.0):
        res = ps.run_portfolio_simulation(1000., {'f': {'symbol': 'X/USDT:USDT', 'timeframe': '1h', 'df': df, 'config': cfg}},
                                          '2026-01-01', '2026-01-02')
    assert res['max_risk_per_entry_pct'] == 1.0
    assert res['trade_count'] == 1
    loss = 1000. - res['end_capital']
    assert 10.0 <= loss <= 11.5                                                     # 1 % Stoprisiko + Gebuehren (ohne Obergrenze: ~31,8)


# ---------------------------------------------------------------- dynamisch nach Kontoverlauf
def test_drawdown_faktor():
    d = risk_cap.DEFAULT_DYNAMIC
    assert risk_cap.drawdown_factor(100, 100, d) == 1.0
    assert risk_cap.drawdown_factor(120, 100, d) == 1.0                     # ueber dem Hoch
    assert risk_cap.drawdown_factor(85, 100, d) == pytest.approx(0.5)       # 15 % DD -> halber Einsatz
    assert risk_cap.drawdown_factor(70, 100, d) == pytest.approx(0.25)      # 30 % DD -> Untergrenze
    assert risk_cap.drawdown_factor(40, 100, d) == pytest.approx(0.25)
    assert risk_cap.drawdown_factor(50, 100, {**d, 'enabled': False}) == 1.0


def test_dynamik_einstellungen(tmp_path):
    assert risk_cap.dynamic_settings(_settings(tmp_path, {}))['enabled'] is True                       # Standard an
    assert risk_cap.dynamic_settings(_settings(tmp_path, {'dynamic_risk': None}))['enabled'] is False  # null = aus
    s = risk_cap.dynamic_settings(_settings(tmp_path, {'dynamic_risk': {'dd_full': 0.2}}))
    assert s['dd_full'] == 0.2 and s['floor'] == 0.25
    for bad in ({'enabled': 'ja'}, {'dd_full': 0}, {'floor': 1.5}, {'dd_full': float('nan')}):
        with pytest.raises(ValueError):
            risk_cap.dynamic_settings(_settings(tmp_path, {'dynamic_risk': bad}))


def test_hoechststand_steigt_nur(tmp_path):
    p = str(tmp_path / 'peak.json')
    assert risk_cap.observe_equity(100., path=p) == 100.
    assert risk_cap.observe_equity(80., path=p) == 100.                      # Rueckgang aendert den Hoechststand nicht
    assert risk_cap.observe_equity(130., path=p) == 130.


def test_live_sizing_halbiert_bei_15_prozent_drawdown(monkeypatch):
    from fibot.utils.trade_manager import _confluence_size
    risk_cap.observe_equity(1000.)                                           # Hoechststand 1000 (isolierte Testdatei)
    monkeypatch.setattr(risk_cap, 'dynamic_settings', lambda settings_file=None: dict(risk_cap.DEFAULT_DYNAMIC))
    c = _confluence_size(_ex(equity=850., free=850.), 'X/USDT:USDT', {'limit': 100., 'sl': 98.}, 1.0, 10, LOG)
    assert c * 2 == pytest.approx(850 * 0.01 * 0.5, rel=1e-6)                # 1 % x Faktor 0,5


def test_simulator_rechnet_kontoverlauf_wie_live():
    from fibot.analysis import portfolio_simulator as ps
    idx = pd.date_range('2026-01-01', periods=6, freq='1h', tz='UTC')
    df = pd.DataFrame({'open': 100., 'high': 100.5, 'low': 99.5, 'close': 100., 'volume': 1.}, index=idx)
    for col, v in (('_sig_dir', 0), ('_sig_entry', 0.), ('_sig_sl', 0.), ('_sig_tp1', 0.), ('_sig_score', 0.),
                   ('_sig_instant', False), ('_sig_swing_high', 0.), ('_sig_swing_low', 0.)):
        df[col] = v
    df.iloc[1, df.columns.get_loc('_sig_dir')] = 1
    df.iloc[1, [df.columns.get_loc(c) for c in ('_sig_entry', '_sig_sl', '_sig_tp1')]] = [100., 98., 110.]
    df.iloc[2, df.columns.get_loc('low')] = 97.
    cfg = {'market': {'symbol': 'X/USDT:USDT', 'timeframe': '1h'}, 'strategy': {'type': 'confluence'},
           'risk': {'leverage': 10, 'risk_per_entry_pct': 3.0}}
    sd = {'f': {'symbol': 'X/USDT:USDT', 'timeframe': '1h', 'df': df, 'config': cfg}}
    with patch.object(ps, 'max_risk_pct', return_value=1.0), \
         patch.object(ps, 'dynamic_settings', return_value=dict(risk_cap.DEFAULT_DYNAMIC)):
        voll = ps.run_portfolio_simulation(1000., sd, '2026-01-01', '2026-01-02')
        halb = ps.run_portfolio_simulation(1000., sd, '2026-01-01', '2026-01-02', start_peak=1000. / .85)   # 15 % unter Hoch
    assert (1000. - halb['end_capital']) == pytest.approx((1000. - voll['end_capital']) * 0.5, rel=1e-6)
    assert halb['max_drawdown_pct'] == pytest.approx(voll['max_drawdown_pct'] * 0.5, rel=1e-3)   # gemeldeter DD ab Start
