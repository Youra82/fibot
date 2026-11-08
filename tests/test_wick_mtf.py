# tests/test_wick_mtf.py -- Fibo-Wick-Konfluenz: Live-Fenster = Backtest, harte Sperren
import os
import sys
import tempfile

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))
from fibot.strategy import wick_mtf as W  # noqa: E402
from fibot.strategy import wick_mtf_live as LIVE  # noqa: E402
from fake_bitget import FakeBitget  # noqa: E402

COINS = ['BTC'] + [f'C{k:02d}' for k in range(24)]
START = pd.Timestamp('2025-01-01', tz='UTC')


def _walk(seed, n, start, freq, p0):
    rng = np.random.default_rng(seed)
    r = rng.standard_t(3, n) * .012
    c = p0 * np.exp(np.cumsum(r))
    o = np.r_[p0, c[:-1]]
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, .006, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, .02, n)))      # lange untere Dochte
    return pd.DataFrame(dict(open=o, high=hi, low=lo, close=c), index=pd.date_range(start, periods=n, freq=freq))


def _resample(d, rule):
    return d.resample(rule, origin='epoch').agg(dict(open='first', high='max', low='min', close='last')).dropna()


@pytest.fixture(scope='module')
def frames():
    fr = {}
    for k, c in enumerate(COINS):
        m = _walk(k, 48 * 40, START, '30min', 1.0 + k)
        fr[c, '30m'] = m
        for tf, rule in (('1h', '1h'), ('2h', '2h'), ('4h', '4h'), ('6h', '6h')):
            fr[c, tf] = _resample(m, rule)
    d = _walk(99, 400, START - pd.Timedelta(days=360), '1D', 30000.)
    d['close'] = np.linspace(20000, 60000, len(d))                    # BTC klar ueber SMA200/SMA50
    d['open'] = d.close.shift().bfill(); d['high'] = d[['open', 'close']].max(axis=1) * 1.01
    d['low'] = d[['open', 'close']].min(axis=1) * .99
    fr['BTC', '1d'] = d
    return fr


def _full(frames):
    raw = {c: frames[c, '30m'] for c in COINS}
    nat = {(c, tf): frames[c, tf] for c in COINS for tf in ('1h', '2h', '4h', '6h')}
    idx = pd.date_range(START, raw['BTC'].index.max(), freq='30min')
    return W.build_arrays(raw, nat, frames['BTC', '1d'], idx)


def test_live_window_equals_backtest(frames):
    full = _full(frames)
    fx = FakeBitget(frames)
    rng = np.random.default_rng(1)
    checked = hits = 0
    for t in sorted(rng.choice(full['idx'][48 * 15:], 40, replace=False)):
        t = pd.Timestamp(t); fx.now = t
        raw, nat, daily = LIVE.fetch_market_data(fx, COINS, t)
        data, i = LIVE.signals_at(raw, nat, daily, t)
        k = full['idx'].get_loc(t)
        assert data['names'] == full['names']
        assert data['entry_ok'][i] == full['entry_ok'][k]
        for key in W.STRATEGIES:
            np.testing.assert_array_equal(data['masks'][key][i], full['masks'][key][k])
            hits += int(full['masks'][key][k].sum())
        for h in W.STRAT_TFS:
            np.testing.assert_allclose(data['f'][h][0][i], full['f'][h][0][k], rtol=1e-6)
            np.testing.assert_allclose(data['f'][h][1][i], full['f'][h][1][k], rtol=1e-6)
        checked += 1
    assert checked == 40 and hits > 0, 'Test braucht echte Signale'


def test_stop_distance_never_tight():
    for ep, atr in ((1.0, .001), (100., 0.), (5., 2.)):
        assert W.stop_distance(ep, atr) >= .10 * ep


def test_one_order_per_coin_and_bar_long_only(frames, monkeypatch):
    monkeypatch.setattr(LIVE, 'STATE_FILE', os.path.join(tempfile.mkdtemp(), 's.json'))
    fx = FakeBitget(frames)
    full = _full(frames)
    orders = []
    orig = fx.create_order

    def spy(sym, typ, side, amount, price=None, params=None):
        orders.append((fx.now, sym, side))
        return orig(sym, typ, side, amount, price, params)
    fx.create_order = spy
    for t in full['idx'][48 * 15: 48 * 25]:
        fx.begin_bar(t)
        LIVE.run_cycle(fx, now=t + pd.Timedelta(seconds=5), coins=COINS)
        LIVE.run_cycle(fx, now=t + pd.Timedelta(minutes=15), coins=COINS)   # zweiter Cron-Lauf in derselben Kerze
        fx.process_bar(t)
        held = {s for s in fx.positions}
        assert len(held) <= W.K
    assert orders, 'Test braucht Orders'
    assert all(side == 'buy' for _, _, side in orders)
    per_bar = pd.Series([(t.floor('30min'), s) for t, s, _ in orders]).value_counts()
    assert per_bar.max() == 1
