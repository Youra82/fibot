"""Lokale Tests fuer die Log-Auswertung im Tagescheck (keine Bitget-Aufrufe)."""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import pandas as pd

import daily_live_vs_backtest_check as mod

LOCAL_TZ = datetime.now().astimezone().tzinfo
FILL_CANDLE = pd.Timestamp('2026-10-22 10:00', tz='UTC')  # Beginn der Fuellkerze (1h)


def _write_log(tmp_path, key, entries):
    """entries: (Minuten nach Kerzenbeginn, Level, Meldung) -- Zeitstempel in Ortszeit wie RotatingFileHandler."""
    lines = []
    for minutes, level, msg in entries:
        ts = (FILL_CANDLE + pd.Timedelta(minutes=minutes)).tz_convert(LOCAL_TZ)
        lines.append(f"{ts.strftime('%Y-%m-%d %H:%M:%S')},123 - {level} - {msg}\n")
    (tmp_path / f'fibot_{key}.log').write_text(''.join(lines), encoding='utf-8')


def test_no_setup_live(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'LOG_DIR', str(tmp_path))
    _write_log(tmp_path, 'SANDUSDTUSDT_1h', [(0.5, 'INFO', 'Kein Konfluenz-Setup fuer die laufende Kerze.')])
    assert mod.explain_from_log('SANDUSDTUSDT_1h', FILL_CANDLE).startswith('Live-Code sah kein Setup')


def test_limit_order_placed_but_not_filled(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'LOG_DIR', str(tmp_path))
    _write_log(tmp_path, 'UNIUSDTUSDT_1h', [
        (0.5, 'INFO', 'Limit nachgezogen: LONG @ 6.123 | SL 6.0 | TP 6.4'),
        (15.5, 'INFO', 'Limit-Order fuer 2026-10-22T10:00:00+00:00 liegt bereits @ 6.123000.'),
    ])
    assert mod.explain_from_log('UNIUSDTUSDT_1h', FILL_CANDLE).startswith('Limit-Order lag, live nicht gefüllt')


def test_margin_beats_other_reasons(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'LOG_DIR', str(tmp_path))
    _write_log(tmp_path, 'OPUSDTUSDT_1h', [
        (0.5, 'WARNING', 'Nicht genug freie Margin fuer die Konfluenz-Order.'),
        (15.5, 'INFO', 'Kein Konfluenz-Setup fuer die laufende Kerze.'),
    ])
    assert mod.explain_from_log('OPUSDTUSDT_1h', FILL_CANDLE).startswith('zu wenig freie Margin')


def test_bot_not_running_and_missing_log(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'LOG_DIR', str(tmp_path))
    _write_log(tmp_path, 'DOTUSDTUSDT_2h', [(-300, 'INFO', 'Kein Konfluenz-Setup fuer die laufende Kerze.')])
    assert mod.explain_from_log('DOTUSDTUSDT_2h', FILL_CANDLE).startswith('Bot lief in dem Zeitraum nicht')
    assert mod.explain_from_log('XRPUSDTUSDT_2h', FILL_CANDLE) == 'kein Bot-Log vorhanden'


def test_active_periods_follow_team_history():
    history = [
        {'valid_from': '2026-10-14T01:15:00+00:00', 'team': {'AVAXUSDTUSDT_1h': None, 'SANDUSDTUSDT_1h': None}},
        {'valid_from': '2026-10-21T01:15:00+00:00', 'team': {'SANDUSDTUSDT_1h': None}},
    ]
    ts = pd.Timestamp
    assert mod.active_periods(history, 'AVAXUSDTUSDT_1h') == [
        (ts('2026-10-14T01:15:00+00:00'), ts('2026-10-21T01:15:00+00:00'))]
    assert mod.active_periods(history, 'SANDUSDTUSDT_1h') == [(ts('2026-10-14T01:15:00+00:00'), None)]


def test_position_without_stop_loss_is_reported():
    pos = [{'symbol': 'XRPUSDT', 'holdSide': 'short', 'markPrice': '1.2781'},
           {'symbol': 'ARBUSDT', 'holdSide': 'long', 'markPrice': '0.168'}]
    plans = [  # XRP: nur Trailing (unter dem Kurs, kein SL); ARB: SL an der Einstiegs-Order
        {'symbol': 'XRPUSDT', 'planType': 'track_plan', 'tradeSide': 'close', 'posSide': 'short', 'triggerPrice': '1.22'},
        {'symbol': 'ARBUSDT', 'planType': 'profit_loss', 'tradeSide': 'close', 'posSide': 'long',
         'triggerPrice': '0.108', 'stopLossTriggerPrice': '0.108'},
    ]
    flags = mod.positions_without_sl(pos, plans)
    assert len(flags) == 1 and 'XRP short OHNE Stop-Loss' in flags[0]
    plans.append({'symbol': 'XRPUSDT', 'planType': 'normal_plan', 'tradeSide': 'close', 'posSide': 'short',
                  'triggerPrice': '1.41'})
    assert mod.positions_without_sl(pos, plans) == []
