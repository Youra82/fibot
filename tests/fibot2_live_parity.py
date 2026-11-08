# tests/fibot2_live_parity.py -- fibot 2.0: unveraenderter Live-Zyklus auf simulierter Boerse vs. Forschungsrechnung
# (virtual_events + Phasentor + Mindest-Stop + eine Position je Coin) auf denselben Cache-Daten.
#   python tests/fibot2_live_parity.py 2026-07-20 2026-07-26 CFG1 CFG2 ...
import functools, json, os, sys, tempfile, time
import numpy as np, pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))
import logging; logging.disable(logging.INFO)
from fibot.strategy import fibot2_logic as F, fibot2_live as LIVE  # noqa: E402

MIN_N = 3


def load_cache(sym, tf):
    d = pd.read_csv(os.path.join(ROOT, 'data', 'cache', sym.replace('/', '-').replace(':', '-') + f'_{tf}.csv'))
    d.index = pd.to_datetime(d.iloc[:, 0], utc=True)
    d = d[['open', 'high', 'low', 'close']].astype(float).sort_index()
    return d[~d.index.duplicated()]


class FakeEx:
    def __init__(self, cfgs, cash=1000.):
        self.data = {(c['market']['symbol'], c['market']['timeframe']): load_cache(c['market']['symbol'], c['market']['timeframe']) for c in cfgs}
        self.markets = {c['market']['symbol']: {} for c in cfgs}; self.exchange = self
        self.now = None; self.orders = {}; self.pos = {}; self.ledger = []; self.oid = 0; self.cash = cash

    def fetch_recent_ohlcv(self, sym, tf, limit=1000):
        d = self.data[sym, tf]; return d[d.index <= self.now].iloc[-limit:].copy()

    def fetch_positions(self, params=None):
        return [dict(symbol=s, contracts=v['amount'], entryPrice=v['limit']) for s, v in self.pos.items()]

    def fetch_order(self, oid, sym):
        o = self.orders.get(oid); return {'status': o['status'], 'filled': o['amount'] if o['status'] != 'open' else 0}

    def cancel_order(self, oid, sym):
        if self.orders[oid]['status'] == 'open': self.orders[oid]['status'] = 'canceled'

    def cancel_all_orders_for_symbol(self, sym): pass
    def fetch_equity_usdt(self): return self.cash
    def amount_to_precision(self, sym, a): return repr(float(a))
    def fetch_min_amount_tradable(self, sym): return 0.
    def set_margin_mode(self, *a, **k): pass
    def set_leverage(self, *a, **k): pass

    def place_limit_order_with_tpsl(self, sym, side, amount, price, sl, tp):
        self.oid += 1; oid = str(self.oid)
        tf = next(tf for (s, tf) in self.data if s == sym and self._placing_tf == tf)
        self.orders[oid] = dict(sym=sym, tf=tf, side=side, amount=amount, limit=price, sl=sl, tp=tp, candle=self.now, status='open')
        return {'id': oid}

    def step(self, t):
        """Kerzen abwickeln, die vor t abgeschlossen sind (Regeln wie Forschung: Fill-Kerze SL zuerst, danach SL vor TP)."""
        for oid, o in self.orders.items():
            if o['status'] != 'open': continue
            d = self.data[o['sym'], o['tf']]; c = o['candle']
            if c + pd.Timedelta(o['tf']) > t: continue
            r = d.loc[c]; lng = o['side'] == 'buy'
            if (r.low <= o['limit']) if lng else (r.high >= o['limit']):
                o['status'] = 'closed'; self.pos[o['sym']] = dict(o, fill=c, last=c)
                if (r.low <= o['sl']) if lng else (r.high >= o['sl']):
                    self._exit(o['sym'], c, 'loss')
            else:
                o['status'] = 'canceled_by_candle'
        for sym in list(self.pos):
            p = self.pos[sym]; d = self.data[sym, p['tf']]; lng = p['side'] == 'buy'
            for ts in d.index[(d.index > p['last']) & (d.index + pd.Timedelta(p['tf']) <= t)]:
                r = d.loc[ts]; p['last'] = ts
                if (r.low <= p['sl']) if lng else (r.high >= p['sl']): self._exit(sym, ts, 'loss'); break
                if (r.high >= p['tp']) if lng else (r.low <= p['tp']): self._exit(sym, ts, 'win'); break

    def _exit(self, sym, ts, res):
        p = self.pos.pop(sym); self.ledger.append(dict(coin=sym.split('/')[0], tf=p['tf'], ts=p['fill'], exit_ts=ts, res=res))


def reference(cfgs, start, end):
    evs = []
    for c in cfgs:
        d = load_cache(c['market']['symbol'], c['market']['timeframe']); d = d[d.index < end]
        evs.append(F.virtual_events(d.iloc[-(LIVE.window_bars(c['market']['timeframe']) + 3000):], c))
    E = pd.concat(evs, ignore_index=True)
    E['gate'] = [F.gate_value(E, r.tf, r.ts, min_n=MIN_N) for r in E.itertuples()]
    m = E.eligible & (E.gate > 0) & (E.stop_atr >= F.MIN_STOP_ATR) & (E.ts >= start) & (E.ts < end)
    E = E[m].copy(); E['o'] = E.tf.map(LIVE.TF_ORDER)
    E = E.sort_values(['ts', 'o']); busy = {}; keep = []
    for r in E.itertuples():
        if r.coin in busy and r.ts <= busy[r.coin]: continue
        busy[r.coin] = r.exit_ts; keep.append(r.Index)
    return E.loc[keep]


def main(start, end, keys):
    start, end = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
    cfgs = [dict(json.load(open(os.path.join(LIVE.CONFIG_DIR, f'config_{k}_fib.json'))), _key=k) for k in keys]
    LIVE.load_configs = lambda: sorted(cfgs, key=lambda c: (LIVE.TF_ORDER[c['market']['timeframe']], c['_key']))
    tmp = tempfile.mkdtemp(); LIVE.STATE_FILE = os.path.join(tmp, 's.json'); LIVE.EVENTS_FILE = os.path.join(tmp, 'e.pkl')
    LIVE.OHLCV_DIR = os.path.join(tmp, 'ohlcv')
    F.gate_value = functools.partial(F.gate_value, min_n=MIN_N)
    fx = FakeEx(cfgs)
    orig = fx.place_limit_order_with_tpsl
    plan_tf = {}
    def place(sym, side, amount, price, sl, tp):
        fx._placing_tf = next(c['market']['timeframe'] for c in LIVE.load_configs() if c['market']['symbol'] == sym and c['_key'] == LIVE._current_key)
        return orig(sym, side, amount, price, sl, tp)
    fx.place_limit_order_with_tpsl = place
    import fibot.strategy.confluence_logic as CL
    orig_plan = LIVE.plan_next_order
    def plan_spy(df, c):
        LIVE._current_key = c['_key']; return orig_plan(df, c)
    LIVE.plan_next_order = plan_spy
    t0 = time.time()
    for t in pd.date_range(start, end, freq='15min', inclusive='left'):
        fx.now = t; fx.step(t); LIVE.run_cycle(fx, now=t + pd.Timedelta(seconds=10))
    fx.now = end; fx.step(end + pd.Timedelta(days=30))
    live = pd.DataFrame(fx.ledger); ref = reference(cfgs, start, end)
    a = set(zip(ref.coin, ref.tf, ref.ts)); b = set(zip(live.coin, live.tf, live.ts)) if len(live) else set()
    print(f'Laufzeit {time.time() - t0:.0f}s | Forschung {len(a)} Trades | Live {len(b)} Trades')
    print('nur Forschung:', sorted(a - b)); print('nur Live:', sorted(b - a))
    return a == b


if __name__ == '__main__':
    ok = main(sys.argv[1], sys.argv[2], sys.argv[3:]); print('PARITAET OK' if ok else 'PARITAET VERLETZT')
