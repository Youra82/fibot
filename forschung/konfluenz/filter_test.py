# fibot/forschung/konfluenz/filter_test.py
# Wirkt der zerobot-Regime-Filter auf die Konfluenz-Trades?
#   S6: Long nur wenn BTC > SMA200 (Tag); Short nur wenn BTC < SMA50 UND Coin < eigener SMA100
#   S4: Long nur wenn BTC > SMA200; Short nur wenn BTC < SMA200
#   LONG: nur Longs
# Geprueft wird zum Fill-Zeitpunkt mit der letzten ABGESCHLOSSENEN Tageskerze (kein Lookahead).
# Naeherung: geblockte Trades werden entfernt (Pfadeffekte freiwerdender Positionen nicht simuliert).

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))
os.chdir(ROOT)

import numpy as np
import pandas as pd

from fibot.analysis.backtester import load_ohlcv

_daily = {}


def daily(coin):
    if coin not in _daily:
        d = load_ohlcv(f'{coin}/USDT:USDT', '1d', '2022-06-01', '2026-10-15')['close']
        _daily[coin] = pd.DataFrame({'c': d, 's50': d.rolling(50).mean(), 's100': d.rolling(100).mean(),
                                     's200': d.rolling(200).mean()})
    return _daily[coin]


def state(coin, ts):
    """Werte der letzten abgeschlossenen Tageskerze vor ts."""
    day = ts.floor('1D') - pd.Timedelta(days=1)
    b = daily('BTC').loc[:day].iloc[-1]
    c = daily(coin).loc[:day].iloc[-1]
    return b, c


def allowed(rule, d, b, c):
    if rule == 'ohne':
        return True
    if rule == 'LONG':
        return d == 'long'
    if rule == 'S4':
        return (b.c > b.s200) if d == 'long' else (b.c < b.s200)
    if rule == 'S6':
        return (b.c > b.s200) if d == 'long' else (b.c < b.s50 and c.c < c.s100)


def load(files):
    t = pd.concat([pd.DataFrame(json.load(open(os.path.join(HERE, f)))) for f in files], ignore_index=True)
    t = t[t.result != 'open'].copy()
    t['fill_ts'] = pd.to_datetime(t.fill_ts, utc=True)
    t['net'] = t.r_gross - t.fee_taker
    t['oos'] = t.fill_ts >= pd.Timestamp('2026-04-01', tz='UTC')
    st = [state(r.coin, r.fill_ts) for r in t.itertuples()]
    for rule in ('S6', 'S4', 'LONG', 'ohne'):
        t[rule] = [allowed(rule, d, b, c) for d, (b, c) in zip(t.dir, st)]
    return t


def report(t, title):
    print(f'\n=== {title} ===')
    print(f"{'Filter':<6} {'Abschnitt':<10} {'Trades':>6} {'netto R/Trade':>14} {'95%-Bereich':>18} {'Summe R':>8} {'Long':>5} {'Short':>5}")
    for rule in ('ohne', 'S6', 'S4', 'LONG'):
        for name, part in (('gesamt', t), ('bis 03/26', t[~t.oos]), ('OOS', t[t.oos])):
            x = part[part[rule]]
            if len(x) == 0:
                continue
            bs = [np.random.default_rng(i).choice(x.net.values, len(x)).mean() for i in range(1500)]
            lo, hi = np.percentile(bs, [2.5, 97.5])
            print(f"{rule:<6} {name:<10} {len(x):>6} {x.net.mean():>+14.3f} [{lo:+.3f}, {hi:+.3f}] {x.net.sum():>+8.1f} "
                  f"{(x.dir == 'long').sum():>5} {(x.dir == 'short').sum():>5}")


if __name__ == '__main__':
    v1 = load(['trades.json'])
    report(v1[v1.tf.isin(['4h', '6h', '1d'])], 'v1 Lehrbuch-Parameter, 10 Coins, 4h/6h/1d')
    report(v1[v1.tf.isin(['1h', '2h'])], 'v1 Lehrbuch-Parameter, 10 Coins, 1h/2h')
    v2 = load(['trades_v2.json', 'trades_v2_extra.json'])
    report(v2, 'v2 strenger Kanal, 20 Coins, 4h/6h/1d')
