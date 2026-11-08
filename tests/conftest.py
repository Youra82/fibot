# tests/conftest.py -- Tests duerfen nie den echten Konto-Hoechststand (artifacts/db/equity_peak.json) schreiben.
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


@pytest.fixture(autouse=True)
def _peak_datei_isolieren(tmp_path, monkeypatch):
    from fibot.utils import risk_cap
    monkeypatch.setattr(risk_cap, 'PEAK_FILE', str(tmp_path / 'equity_peak.json'))
    monkeypatch.setattr(risk_cap, 'HISTORY_FILE', str(tmp_path / 'equity_history.jsonl'))
