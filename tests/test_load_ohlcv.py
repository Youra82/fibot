# tests/test_load_ohlcv.py
# Regressionstests fuer den Portfolio-Optimizer-Lauf vom 30.09.2026: load_ohlcv lud bei
# end_date=heute jedes Mal die komplette Historie neu (Cache griff nie) und brach bei
# 429 still ab -> Backtests auf abgeschnittenen Daten. Rein lokal, gemockte Boerse.

import os
import sys
from unittest.mock import MagicMock, patch

import ccxt
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from fibot.analysis import backtester as bt

TF_MS = 4 * 3600 * 1000


class FakeExchange:
    """Liefert lueckenlose 4h-Kerzen bis zur letzten abgeschlossenen Kerze."""
    def __init__(self, fail_first=0, always_fail=False):
        self.calls = []
        self.fail_left = fail_first
        self.always_fail = always_fail
        self.last_closed_ms = int((pd.Timestamp.now(tz='UTC').floor('4h') - pd.Timedelta(hours=4)).timestamp() * 1000)

    def parse_timeframe(self, tf):
        return ccxt.Exchange.parse_timeframe(tf)

    def fetch_ohlcv(self, symbol, tf, since, limit):
        self.calls.append(since)
        if self.always_fail or self.fail_left > 0:
            self.fail_left -= 1
            raise ccxt.DDoSProtection('bitget {"code":"429","msg":"Too Many Requests"}')
        since = since - since % TF_MS
        rows = []
        t = since
        while len(rows) < limit and t <= self.last_closed_ms + TF_MS:   # inkl. offener Kerze wie Bitget
            rows.append([t, 1.0, 2.0, 0.5, 1.5, 10.0])
            t += TF_MS
        return rows


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(bt, 'PROJECT_ROOT', str(tmp_path))
    monkeypatch.setattr('time.sleep', lambda s: None)
    return tmp_path


def _load(fake, start='2026-08-01'):
    with patch.object(bt, '_public_exchange', return_value=fake):
        return bt.load_ohlcv('BTC/USDT:USDT', '4h', start, pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d'))


def test_only_closed_candles_and_second_call_is_cache_hit(env):
    fake = FakeExchange()
    df = _load(fake)
    last_closed = pd.Timestamp.now(tz='UTC').floor('4h') - pd.Timedelta(hours=4)
    assert df.index.max() == last_closed
    assert df.index.to_series().diff().dropna().eq(pd.Timedelta(hours=4)).all()
    fake2 = FakeExchange()
    df2 = _load(fake2)
    assert fake2.calls == []            # frueher: jedes Mal volle Historie neu
    assert df2.equals(df)


def test_only_missing_tail_is_downloaded(env):
    _load(FakeExchange())
    path = os.path.join(env, 'data', 'cache', 'BTC-USDT-USDT_4h.csv')
    cached = pd.read_csv(path, index_col='timestamp', parse_dates=True)
    cached.iloc[:-5].to_csv(path)       # letzte 5 Kerzen fehlen
    fake = FakeExchange()
    df = _load(fake)
    assert len(fake.calls) == 1
    assert df.index.max() == pd.Timestamp.now(tz='UTC').floor('4h') - pd.Timedelta(hours=4)


def test_gap_in_cache_is_repaired(env):
    _load(FakeExchange())
    path = os.path.join(env, 'data', 'cache', 'BTC-USDT-USDT_4h.csv')
    cached = pd.read_csv(path, index_col='timestamp', parse_dates=True)
    cached.drop(cached.index[[40, 41, 90]]).to_csv(path)      # Altlast: Luecken im Cache
    df = _load(FakeExchange())
    assert df.index.to_series().diff().dropna().eq(pd.Timedelta(hours=4)).all()


class ExclusiveSinceExchange(FakeExchange):
    """Bitget-Verhalten an manchen Seitengrenzen: since wird exklusiv behandelt."""
    def fetch_ohlcv(self, symbol, tf, since, limit):
        return super().fetch_ohlcv(symbol, tf, since + 1, limit)[1:] if since % TF_MS == 0 \
            else super().fetch_ohlcv(symbol, tf, since, limit)


def test_exclusive_since_pagination_loses_no_candle(env):
    df = _load(ExclusiveSinceExchange(), start='2026-01-01')
    assert len(df) > 400    # mehrere 200er-Seiten
    diffs = df.index.to_series().diff().dropna()
    assert diffs.eq(pd.Timedelta(hours=4)).all(), diffs[diffs != pd.Timedelta(hours=4)]


def test_429_is_retried(env):
    fake = FakeExchange(fail_first=3)
    df = _load(fake)
    assert not df.empty


def test_persistent_429_fails_hard_instead_of_truncating(env):
    with pytest.raises(ccxt.DDoSProtection):
        _load(FakeExchange(always_fail=True))
    assert not os.path.exists(os.path.join(env, 'data', 'cache', 'BTC-USDT-USDT_4h.csv'))
