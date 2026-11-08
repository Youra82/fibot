# src/fibot/analysis/wick_mtf_backtest.py
# Konto-Backtest der Fibo-Wick-Konfluenz (MTF + BTC50) auf dem 30m-Ausfuehrungsraster.
# Signale, Positionsgroesse und Stop kommen ausschliesslich aus fibot.strategy.wick_mtf (gleiche Funktionen wie live).
#
# Aufruf:  python -m fibot.analysis.wick_mtf_backtest <DATENWURZEL> [--start 2025-01-01] [--end JJJJ-MM-TT] [--save PREFIX]
# DATENWURZEL enthaelt daten_30m, daten_1h, daten_2h, daten_4h, daten_6h (Dateien COIN-USDT-USDT_<tf>.csv) und daten_BTC_1d.csv.
import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from fibot.strategy import wick_mtf as W


def read_csv(p: Path) -> pd.DataFrame:
    d = pd.read_csv(p); d.index = pd.to_datetime(d.iloc[:, 0], utc=True)
    d = d[['open', 'high', 'low', 'close']].astype(float).sort_index()
    return d[~d.index.duplicated(keep='last')]


def load_root(root: Path, names=None, end=None, **cfg):
    root = Path(root)
    daily = read_csv(root / 'daten_BTC_1d.csv')
    names = names or W.UNIVERSE
    raw = {}
    for n in names:
        p = root / 'daten_30m' / f'{n}-USDT-USDT_30m.csv'
        if not p.exists():
            raise FileNotFoundError(f'30m-Daten fehlen fuer {n}: {p}')
        raw[n] = read_csv(p)
    natives = {}
    for tf in ('1h', '2h', '4h', '6h'):
        for n in names:
            p = root / f'daten_{tf}' / f'{n}-USDT-USDT_{tf}.csv'
            if p.exists():
                natives[n, tf] = read_csv(p)
    if end is None:
        end = max(d.index.max() for d in raw.values()) + pd.Timedelta(minutes=30)
    idx = pd.date_range(min(d.index.min() for d in raw.values()), end - pd.Timedelta(minutes=30), freq='30min')
    return W.build_arrays(raw, natives, daily, idx, **cfg), end


def simulate(data, start, end, equity0=34.0):
    idx, names, P = data['idx'], data['names'], data['p']
    strategies = data.get('strategies') or W.STRATEGIES
    candidates = [[] for _ in idx]
    for s, j in W.candidate_order(names, strategies):
        for i in np.flatnonzero(data['masks'][strategies[s]][:, j]):
            candidates[i].append((s, j))
    cash = float(equity0); pos = {}; last = np.full(len(names), np.nan); ledger = []; rows = [(start, cash, 0, 0.)]
    rejects = Counter(); fills = []; funding = 0.

    def eq(p):
        return cash + sum(v['margin'] + v['q'] * (p[j] - v['entry']) for (s, j), v in pos.items())

    def liq_price(v):
        return max(0., (v['entry'] - v['margin'] / v['q']) / (1 - W.MMR - W.TAKER))

    def close(key, x, reason, t, fee):
        nonlocal cash
        v = pos.pop(key); value = max(0., v['margin'] + v['q'] * (x - v['entry']) - v['q'] * x * fee); cash += value
        ledger.append(dict(strategy=strategies[key[0]], coin=names[key[1]], entry_ts=v['ts'], exit_ts=t, entry=v['entry'],
                           exit=x, notional=v['q'] * v['entry'], pnl=value - v['initial_margin'] - v['fee'], res=reason))

    for i in np.flatnonzero((idx >= start) & (idx < end)):
        t = idx[i]; o, h, low, c = [P[k][i] for k in ('open', 'high', 'low', 'close')]; marks = np.where(np.isfinite(o), o, last)
        for key in list(pos):
            if not np.isfinite(o[key[1]]):
                close(key, last[key[1]] * (1 - W.SLIP), 'data_gap', t, W.TAKER)
        if t.hour % 8 == 0 and t.minute == 0:
            for (s, j), v in pos.items():
                charge = v['q'] * marks[j] * W.FUND; v['margin'] -= charge; funding += charge
        gap_closed = set()
        for key in list(pos):
            s, j = key; v = pos[key]; liq = liq_price(v); thr = max(liq, v['sl'])
            if o[j] <= thr:
                close(key, o[j] * (1 - W.SLIP), 'liq' if o[j] <= liq else 'sl', t, W.TAKER); gap_closed.add(key)
        equity = eq(marks); available = cash; slots = W.K - len(pos); budget = sum(v['risk'] for v in pos.values())
        counts = Counter(j for s, j in pos); selected = []
        if i > 0 and data['entry_ok'][i]:
            for s, j in candidates[i]:
                if (s, j) in pos or (s, j) in gap_closed or not np.isfinite(o[j]):
                    continue
                if slots <= 0:
                    rejects['slots'] += 1; break
                if counts[j] >= W.COIN_CAP:
                    rejects['coin_cap'] += 1; continue
                tf, _, depth = strategies[s]
                mid, atr = data['f'][tf]; band = mid[i, j] * (1 - depth / 100)
                n, dist = W.size_order(equity, available, budget, band, atr[i, j])
                if dist >= band:
                    continue
                if n <= 0:
                    rejects['minimum_cash_risk'] += 1; continue
                loss = dist / band + W.MAKER + W.TAKER + W.SLIP
                selected.append((s, j, band, n)); available -= n / W.L + n * W.MAKER; budget += n * loss; slots -= 1; counts[j] += 1
        for s, j, band, n in selected:
            if low[j] > band:
                rejects['unfilled'] += 1; continue
            ep = min(o[j], band); q = n / ep; tf = strategies[s][0]; dist = W.stop_distance(ep, data['f'][tf][1][i, j])
            if n < W.MIN_NOTIONAL or dist >= ep:
                continue
            margin = n / W.L; fee = n * W.MAKER; cash -= margin + fee
            pos[s, j] = dict(q=q, entry=ep, margin=margin, initial_margin=margin, fee=fee, sl=ep - dist, i=i, ts=t,
                             risk=n * (dist / ep + W.MAKER + W.TAKER + W.SLIP)); fills.append(t)
        for key in list(pos):
            s, j = key; v = pos[key]; liq = liq_price(v); thr = max(liq, v['sl']); tf = strategies[s][0]; mid = data['f'][tf][0][i, j]
            t1 = t + pd.Timedelta(minutes=30)
            if low[j] <= thr:
                close(key, min(o[j], thr) * (1 - W.SLIP), 'liq' if liq >= v['sl'] else 'sl', t1, W.TAKER)
            elif i > v['i'] and np.isfinite(mid) and h[j] >= mid:
                close(key, max(o[j], mid), 'tp', t1, W.MAKER)
            elif (i - v['i']) * .5 >= W.MAX_BARS * tf:
                close(key, c[j] * (1 - W.SLIP), 'time', t1, W.TAKER)
        last = np.where(np.isfinite(c), c, last); equity = eq(last)
        used = sum(v['q'] * last[j] for (s, j), v in pos.items())
        rows.append((t + pd.Timedelta(minutes=30), equity, len(pos), used / max(equity, 1e-20)))
    cv = pd.DataFrame(rows, columns=['ts', 'equity', 'positions', 'exposure'])
    years = (end - start).total_seconds() / 86400 / 365.25
    res = dict(start=str(start), end_time=str(end), end=float(cv.equity.iloc[-1]),
               cagr_pct=100 * ((cv.equity.iloc[-1] / equity0) ** (1 / years) - 1),
               dd_pct=float(100 * (1 - cv.equity / cv.equity.cummax()).max()), trades=len(fills),
               liquidations=sum(x['res'] == 'liq' for x in ledger), exits=dict(Counter(x['res'] for x in ledger)),
               funding=funding, open_end=len(pos), rejects=dict(rejects))
    return res, cv, pd.DataFrame(ledger)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('root'); ap.add_argument('--start', default='2025-01-01'); ap.add_argument('--end')
    ap.add_argument('--save'); ap.add_argument('--equity', type=float, default=34.0)
    a = ap.parse_args()
    end = pd.Timestamp(a.end, tz='UTC') if a.end else None
    data, end = load_root(Path(a.root), end=end)
    res, cv, ledger = simulate(data, pd.Timestamp(a.start, tz='UTC'), end, a.equity)
    print(json.dumps(res, indent=2, default=str))
    if a.save:
        cv.to_csv(f'{a.save}_equity.csv', index=False); ledger.to_csv(f'{a.save}_trades.csv', index=False)


if __name__ == '__main__':
    main()
