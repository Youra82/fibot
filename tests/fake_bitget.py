# tests/fake_bitget.py -- simulierte Bitget-Boerse fuer den Wick-Konfluenz-Live-Zyklus.
# Spielt historische 30m-Kerzen ab: begin_bar(t) (Funding, Gap-Stops zum Open) -> Live-Zyklus -> process_bar(t)
# (Limit-Fills, Stops, Take-Profits innerhalb der Kerze). Kosten wie im Backtest.
import numpy as np
import pandas as pd

from fibot.strategy import wick_mtf as W

TF_H = {'30m': .5, '1h': 1, '2h': 2, '4h': 4, '6h': 6, '1d': 24}


class FakeBitget:
    def __init__(self, frames: dict, cash: float = 34.0):
        """frames: {(coin, tf): DataFrame open/high/low/close}, tf in 30m/1h/2h/4h/6h, dazu ('BTC', '1d')."""
        self.frames = frames
        self.exchange = self
        self.cash = float(cash)
        self.now = None
        self.positions = {}          # sym -> dict(q, entry, margin, initial_margin, fee, sl, fill_bar)
        self.entries = {}            # order_id -> dict(sym, amount, price, sl)
        self.tp = {}                 # sym -> limit-Preis (reduce-only)
        self.ledger = []
        self._oid = 0
        coins = {c for c, tf in frames if tf == '30m'}
        self.markets = {f'{c}/USDT:USDT': {'active': True, 'info': {'symbolStatus': 'normal'}} for c in coins}
        self.bar30 = {c: frames[c, '30m'] for c in coins}

    # ---------------------------------------------------------------- Marktdaten
    def _row(self, coin, t):
        d = self.bar30[coin]
        return d.loc[t] if t in d.index else None

    def fetch_recent_ohlcv(self, symbol, timeframe, limit=1000):
        coin = symbol.split('/')[0]; d = self.frames.get((coin, timeframe))
        if d is None:
            return pd.DataFrame()
        h = TF_H[timeframe]; t = self.now
        cur = t.floor('D') if h >= 24 else t.floor(pd.Timedelta(hours=h))
        past = d[d.index < cur].iloc[-(limit - 1):].copy()
        r = self._row(coin, t)
        if r is not None and np.isfinite(r.open):
            o = d.loc[cur, 'open'] if cur in d.index else r.open
            # laufende Kerze: nur Open bekannt, Hoch/Tief/Schluss bewusst falsch (darf nie verwendet werden)
            past.loc[cur] = [o, o * 1.37, o * .61, o * 1.11] + ([0.0] if past.shape[1] == 5 else [])
        past['volume'] = 0.0
        return past

    def fetch_ticker(self, symbol):
        r = self._row(symbol.split('/')[0], self.now)
        return {'last': float(r.open)}

    def _mark(self, sym):
        r = self._row(sym.split('/')[0], self.now)
        return float(r.open) if r is not None and np.isfinite(r.open) else self.positions[sym]['entry']

    # ---------------------------------------------------------------- Konto
    def fetch_equity_usdt(self):
        return self.cash + sum(v['margin'] + v['q'] * (self._mark(s) - v['entry']) for s, v in self.positions.items())

    def fetch_balance_usdt(self):
        return self.cash

    def fetch_positions(self, symbols=None, params=None):
        return [dict(symbol=s, contracts=v['q'], entryPrice=v['entry'], contractSize=1, side='long')
                for s, v in self.positions.items()]

    def fetch_min_amount_tradable(self, symbol):
        return 0.0

    def amount_to_precision(self, symbol, amount):
        return repr(float(amount))

    def price_to_precision(self, symbol, price):
        return repr(float(price))

    def set_margin_mode(self, *a, **k):
        pass

    def set_leverage(self, *a, **k):
        pass

    # ---------------------------------------------------------------- Orders
    def create_order(self, symbol, type_, side, amount, price=None, params=None):
        assert type_ == 'limit' and side == 'buy'
        self._oid += 1; oid = str(self._oid)
        self.entries[oid] = dict(sym=symbol, amount=float(amount), price=float(price),
                                 sl=float(params['stopLoss']['triggerPrice']))
        return {'id': oid}

    def cancel_stale_entry_orders(self, keep):
        out = [(v['sym'], k) for k, v in self.entries.items() if v['sym'] not in keep]
        for _, k in out:
            self.entries.pop(k)
        return out

    def fetch_open_orders(self, sym):
        return [{'id': 'tp', 'reduceOnly': True, 'info': {'tradeSide': 'close'}}] if sym in self.tp else []

    def cancel_order(self, oid, sym):
        self.tp.pop(sym, None)

    def fetch_open_trigger_orders(self, sym):
        return []

    def fetch_position_tpsl_orders(self, sym):
        v = self.positions.get(sym)
        return [{'stopPrice': v['sl'], 'info': {'tradeSide': 'close'}}] if v else []

    def place_trigger_market_order(self, sym, side, amount, trigger, reduce=False, params=None):
        self.positions[sym]['sl'] = float(trigger)

    def place_limit_order(self, sym, side, amount, price, reduce=False, params=None):
        assert reduce and side == 'sell'
        self.tp[sym] = float(price)

    def close_position(self, sym):
        self._close(sym, self._mark(sym) * (1 - W.SLIP), 'time', W.TAKER)

    # ---------------------------------------------------------------- Kerzenablauf
    def _close(self, sym, x, reason, fee):
        v = self.positions.pop(sym); self.tp.pop(sym, None)
        value = max(0., v['margin'] + v['q'] * (x - v['entry']) - v['q'] * x * fee); self.cash += value
        self.ledger.append(dict(coin=sym.split('/')[0], entry_ts=v['fill_bar'], exit_ts=self.now, entry=v['entry'], exit=x,
                                pnl=value - v['initial_margin'] - v['fee'], res=reason))

    def begin_bar(self, t):
        self.now = t
        if t.hour % 8 == 0 and t.minute == 0:
            for s, v in self.positions.items():
                v['margin'] -= v['q'] * self._mark(s) * W.FUND
        for s in list(self.positions):
            r = self._row(s.split('/')[0], t)
            if r is not None and np.isfinite(r.open) and r.open <= self.positions[s]['sl']:
                self._close(s, float(r.open) * (1 - W.SLIP), 'sl', W.TAKER)

    def process_bar(self, t):
        for oid, e in list(self.entries.items()):
            r = self._row(e['sym'].split('/')[0], t)
            if r is None or not np.isfinite(r.low) or r.low > e['price']:
                continue
            self.entries.pop(oid)
            ep = min(float(r.open), e['price']); n = e['amount'] * ep
            margin = n / W.L; fee = n * W.MAKER; self.cash -= margin + fee
            self.positions[e['sym']] = dict(q=e['amount'], entry=ep, margin=margin, initial_margin=margin, fee=fee,
                                            sl=e['sl'], fill_bar=t)
        t1 = t + pd.Timedelta(minutes=30)
        for s in list(self.positions):
            v = self.positions[s]; r = self._row(s.split('/')[0], t)
            if r is None or not np.isfinite(r.low):
                continue
            self.now = t1
            if r.low <= v['sl']:
                self._close(s, min(float(r.open), v['sl']) * (1 - W.SLIP), 'sl', W.TAKER)
            elif s in self.tp and v['fill_bar'] < t and r.high >= self.tp[s]:
                self._close(s, max(float(r.open), self.tp[s]), 'tp', W.MAKER)
            self.now = t
