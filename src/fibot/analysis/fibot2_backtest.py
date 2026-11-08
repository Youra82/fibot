# src/fibot/analysis/fibot2_backtest.py
# Portfolio-Backtest fibot 2.0 -- dieselben Funktionen wie live (fibot2_logic), dieselben Regeln wie fibot2_live:
#  * Configs je Kerzenbeginn in Live-Reihenfolge (hoehere Zeitebene zuerst)
#  * Coin blockiert, solange eine Position offen ist oder eine Order dieser Kerze liegt (auch ungefuellt)
#  * Phasentor je TF aus virtuellen Trades aller Configs, sichtbar erst nach Schluss der Ausstiegskerze
#  * Mindest-Stop 2 ATR, Risiko 0,7 % je Trade, Summe Notional <= 10 x Konto
# Aufruf: python -m fibot.analysis.fibot2_backtest --start 2026-05-10 [--end ...] [--equity 34] [--save PREFIX]
import argparse, glob, json, logging, os
from multiprocessing import Pool

import numpy as np
import pandas as pd

from fibot.strategy import fibot2_logic as F

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
CONFIG_DIR = os.path.join(ROOT, 'src', 'fibot', 'strategy', 'configs_fibot2')
TF_ORDER = {'1d': 0, '6h': 1, '4h': 2, '2h': 3, '1h': 4, '30m': 5, '15m': 6}
WARM_BARS = 3000


def load_cache(sym, tf, source='cache'):
    """source 'cache' = data/cache (Backtest-Historie), 'live' = Kerzen-Zwischenspeicher des Live-Bots (Tagesbericht)."""
    if source == 'live':
        p = os.path.join(ROOT, 'artifacts', 'fibot2_ohlcv', f"{sym.split('/')[0]}_{tf}.pkl")
        return pd.read_pickle(p) if os.path.exists(p) else None
    p = os.path.join(ROOT, 'data', 'cache', sym.replace('/', '-').replace(':', '-') + f'_{tf}.csv')
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p); d.index = pd.to_datetime(d.iloc[:, 0], utc=True)
    d = d[['open', 'high', 'low', 'close']].astype(float).sort_index()
    return d[~d.index.duplicated()]


def _job(args):
    path, start, end, source = args
    logging.disable(logging.WARNING)
    cfg = json.load(open(path)); sym, tf = cfg['market']['symbol'], cfg['market']['timeframe']
    d = load_cache(sym, tf, source)
    if d is None:
        return None, None
    d = d[d.index + pd.Timedelta(tf) <= end]
    pos = d.index.searchsorted(start - pd.Timedelta(days=F.GATE_DAYS + 30))
    d = d.iloc[max(0, pos - WARM_BARS):]
    if len(d) < 400:
        return None, None
    ev = F.virtual_events(d, cfg, since=start - pd.Timedelta(days=F.GATE_DAYS + 30))
    pl = F.plan_instances(d, cfg, since=start)
    pl['coin'] = sym.split('/')[0]
    return ev, pl


def build(start, end, workers=6, source='cache'):
    files = [f for f in sorted(glob.glob(os.path.join(CONFIG_DIR, '*.json')))
             if json.load(open(f))['market']['timeframe'] not in F.EXCLUDED_TF]
    with Pool(workers) as p:
        parts = p.map(_job, [(f, start, end, source) for f in files], chunksize=2)
    ev = pd.concat([e for e, _ in parts if e is not None and not e.empty], ignore_index=True)
    pl = pd.concat([x for _, x in parts if x is not None and not x.empty], ignore_index=True)
    return ev, pl


def simulate(ev, pl, start, end, equity0=34.0):
    ev = ev.copy(); ev['visible'] = ev.exit_ts + ev.tf.map(pd.Timedelta)
    ev = ev[ev.eligible].sort_values('visible')
    vis_t = ev.visible.values; ex_t = ev.exit_ts.values; nr = ev.net_R.values; tfs = ev.tf.values
    trade = ev.set_index(['cfg', 'ts', 'dir'])[['exit_ts', 'net_R', 'R', 'risk_pct']]
    pl = pl[(pl.ts >= start) & (pl.ts < end)].copy(); pl['o'] = pl.tf.map(TF_ORDER)
    pl = pl.sort_values(['ts', 'o', 'cfg'])
    gate_cache = {}

    def gate(tf, t):
        k = (tf, t)
        if k not in gate_cache:
            hi = np.searchsorted(vis_t, np.datetime64(t.tz_convert(None)), side='right')
            m = (tfs[:hi] == tf) & (ex_t[:hi] >= np.datetime64((t - pd.Timedelta(days=F.GATE_DAYS)).tz_convert(None)))
            m &= ex_t[:hi] < np.datetime64(t.tz_convert(None))
            gate_cache[k] = nr[:hi][m].mean() if m.sum() >= F.GATE_MIN_N else np.nan
        return gate_cache[k]

    eq = equity0; peak = eq; dd = 0.; busy = {}; openp = []; ledger = []; curve = [(start, eq)]
    for r in pl.itertuples():
        t = r.ts
        for o in sorted([o for o in openp if o['free'] <= t], key=lambda o: o['free']):
            eq += o['pnl']; openp.remove(o); peak = max(peak, eq); dd = max(dd, 1 - eq / peak); curve.append((o['free'], eq))
        if busy.get(r.coin, t) > t:
            continue
        g = gate(r.tf, t)
        if not (np.isfinite(g) and g > 0) or not (r.stop_atr >= F.MIN_STOP_ATR):
            continue
        risk = abs(r.limit - r.sl) / r.limit; notional = eq * F.RISK_PER_TRADE / risk
        if sum(o['notional'] for o in openp) + notional > F.MAX_NOTIONAL_X * eq:
            continue
        busy[r.coin] = t + pd.Timedelta(r.tf)
        if not r.fill:
            continue
        try:
            x = trade.loc[(r.cfg, t, r.dir)]
        except KeyError:
            continue                                  # Trade am Datenende noch offen
        if isinstance(x, pd.DataFrame):
            x = x.iloc[0]
        free = x.exit_ts + pd.Timedelta(r.tf)
        busy[r.coin] = free
        pnl = eq * F.RISK_PER_TRADE * x.net_R
        openp.append(dict(free=free, notional=notional, pnl=pnl))
        ledger.append(dict(coin=r.coin, cfg=r.cfg, tf=r.tf, dir=r.dir, ts=t, exit_ts=x.exit_ts, limit=r.limit, sl=r.sl, tp=r.tp,
                           net_R=x.net_R, pnl=pnl, gate=g, stop_atr=r.stop_atr))
    for o in sorted(openp, key=lambda o: o['free']):
        eq += o['pnl']; peak = max(peak, eq); dd = max(dd, 1 - eq / peak); curve.append((o['free'], eq))
    L = pd.DataFrame(ledger); C = pd.DataFrame(curve, columns=['ts', 'equity'])
    days = (end - start).total_seconds() / 86400
    res = dict(start=str(start), end=str(end), equity_start=equity0, equity_end=eq, ret_pct=100 * (eq / equity0 - 1),
               maxdd_pct=100 * dd, trades=len(L), trades_per_day=len(L) / days,
               winrate=float((L.net_R > 0).mean()) if len(L) else None, mean_R=float(L.net_R.mean()) if len(L) else None)
    return res, L, C


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default='2026-05-10'); ap.add_argument('--end'); ap.add_argument('--equity', type=float, default=34.)
    ap.add_argument('--save'); a = ap.parse_args()
    start = pd.Timestamp(a.start, tz='UTC'); end = pd.Timestamp(a.end, tz='UTC') if a.end else pd.Timestamp.now(tz='UTC').floor('15min')
    ev, pl = build(start, end)
    res, L, C = simulate(ev, pl, start, end, a.equity)
    print(json.dumps(res, indent=1, default=str))
    if len(L):
        L['monat'] = L.ts.dt.strftime('%Y-%m')
        print(L.groupby('monat').agg(trades=('pnl', 'size'), pnl=('pnl', 'sum'), R=('net_R', 'mean')).round(3).to_string())
        print(L.groupby('tf').agg(trades=('pnl', 'size'), R=('net_R', 'mean')).round(3).to_string())
    if a.save:
        L.to_csv(a.save + '_trades.csv', index=False); C.to_csv(a.save + '_equity.csv', index=False)


if __name__ == '__main__':
    main()
