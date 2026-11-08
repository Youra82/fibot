# src/fibot/strategy/wick_mtf_live.py
# Live-Zyklus der Fibo-Wick-Konfluenz (ein Konto-Prozess, 30m-Takt). Bildet den Backtest
# fibot.analysis.wick_mtf_backtest Schritt fuer Schritt ab:
#   Kerzenbeginn t:
#     1. alle unausgefuehrten Entry-Limits der Vorkerze stornieren (Order lebt genau eine Kerze)
#     2. Positionen abgleichen: neue Fills uebernehmen, geschlossene melden
#     3. je Position: Zeitausstieg (59 Kerzen der Strategie-TF), SL vorhanden?, TP-Limit auf aktuelle Mitte
#     4. Freigabe (BTC > SMA200 und > SMA50, keine V2-Pause) -> Kandidaten in fester Hash-Reihenfolge,
#        Limit-Kauf an der Konfluenz mit angehaengtem Stop (mind. 10 % Abstand)
# Harte Sperren: nur Long, 1 Position je Coin, hoechstens eine Entry-Order je Coin und Kerze, 12 Slots.
import json
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from fibot.strategy import wick_mtf as W  # noqa: E402

STATE_FILE = os.path.join(PROJECT_ROOT, 'artifacts', 'wick_mtf_state.json')
LOCK_FILE = os.path.join(PROJECT_ROOT, 'artifacts', 'wick_mtf.lock')
FETCH = {'30m': 60, '1h': 120, '2h': 120, '4h': 120, '6h': 120}
DAILY_BARS = 320
log = logging.getLogger('wick_mtf')


def symbol_of(coin):
    return f'{coin}/USDT:USDT'


def bar_start(now=None):
    now = now or pd.Timestamp.now(tz='UTC')
    return now.floor('30min')


# ---------------------------------------------------------------- Zustand
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(last_bar=None, pending={}, positions={}, last_entry_bar={}, prepared={})


def save_state(st):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(st, f, indent=2, default=str)
    os.replace(tmp, STATE_FILE)


# ---------------------------------------------------------------- Daten
def _add_current_row(d, t, hours):
    """Laufende native Kerze anlegen, falls die Boerse sie noch nicht liefert. Ihr Inhalt fliesst nie in
    die Merkmale ein (alles um eine Kerze verschoben) -- sie wird nur fuer die Zeitzuordnung gebraucht."""
    cur = t.floor(pd.Timedelta(hours=hours)) if hours < 24 else t.floor('D')
    if d.empty or d.index.max() < cur:
        d = pd.concat([d, pd.DataFrame({k: [np.nan] for k in ('open', 'high', 'low', 'close')}, index=[cur])])
    return d


def fetch_market_data(ex, coins, t):
    raw, natives = {}, {}
    for n in coins:
        sym = symbol_of(n)
        for tf, lim in FETCH.items():
            d = ex.fetch_recent_ohlcv(sym, tf, limit=lim)
            if d is None or d.empty:
                continue
            d = d[['open', 'high', 'low', 'close']].astype(float)
            d = d[d.index <= t]
            h = W.NATIVE_TFS[tf]
            d = _add_current_row(d, t, h)
            if tf == '30m':
                raw[n] = d
            else:
                natives[n, tf] = d
    daily = ex.fetch_recent_ohlcv(symbol_of('BTC'), '1d', limit=DAILY_BARS)[['open', 'high', 'low', 'close']].astype(float)
    daily = _add_current_row(daily[daily.index <= t], t, 24)
    return raw, natives, daily


def signals_at(raw, natives, daily, t):
    """Masken/Merkmale fuer die Kerze t -- dieselbe build_arrays-Rechnung wie im Backtest."""
    idx = pd.date_range(min(d.index.min() for d in raw.values()), t, freq='30min')
    data = W.build_arrays(raw, natives, daily, idx)
    i = len(idx) - 1
    assert idx[i] == t
    return data, i


# ---------------------------------------------------------------- Boerse
def all_positions(ex):
    ps = ex.exchange.fetch_positions(params={'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'})
    out = {}
    for p in ps:
        c = float(p.get('contracts') or 0)
        if abs(c) > 1e-12:
            out[p['symbol']] = p
    return out


def tradable(ex, sym):
    m = ex.markets.get(sym)
    if not m or not m.get('active', True):
        return False
    status = (m.get('info') or {}).get('symbolStatus')
    return status in (None, 'normal')          # 'limit_open', 'restrictedAPI', 'off' = Delisting/Sperre


def cancel_all_entries(ex):
    """Alle offenen Entry-Limits (tradeSide 'open') kontoweit stornieren und bestaetigen."""
    cancelled = ex.cancel_stale_entry_orders(set())
    for _ in range(3):
        left = ex.cancel_stale_entry_orders(set())
        if not left:
            break
        cancelled += left; time.sleep(1)
    else:
        raise RuntimeError('Entry-Orders liessen sich nicht vollstaendig stornieren')
    return cancelled


def cancel_close_limits(ex, sym):
    for o in ex.fetch_open_orders(sym):
        if o.get('reduceOnly') or (o.get('info') or {}).get('tradeSide') == 'close':
            ex.cancel_order(o['id'], sym)


def has_stop(ex, sym, entry):
    """Schliessende Trigger-Order auf der Verlustseite (unter dem Entry) in BEIDEN Bitget-Kategorien
    (normal_plan und Position-TP/SL 'loss_plan') -- Muster ltbbot."""
    for o in ex.fetch_open_trigger_orders(sym) + ex.fetch_position_tpsl_orders(sym):
        info = o.get('info') or {}
        if info.get('tradeSide') != 'close':
            continue
        trig = o.get('stopPrice') or info.get('triggerPrice')
        if trig is not None and float(trig) < entry:
            return True
    return False


def place_entry(ex, sym, amount, price, sl):
    params = {'hedged': True, 'marginMode': 'isolated', 'productType': 'USDT-FUTURES',
              'stopLoss': {'triggerPrice': float(ex.price_to_precision(sym, sl)), 'type': 'market'}}
    return ex.exchange.create_order(sym, 'limit', 'buy', float(ex.amount_to_precision(sym, amount)),
                                    float(ex.price_to_precision(sym, price)), params=params)


# ---------------------------------------------------------------- Zyklus
def run_cycle(ex, notify=lambda m: None, now=None, coins=None):
    t = bar_start(now)
    st = load_state()
    if st.get('last_bar') and pd.Timestamp(st['last_bar']) >= t:
        log.info(f'Kerze {t} bereits bearbeitet.'); return st
    coins = coins or W.UNIVERSE
    msgs = []

    # 1. Entry-Limits der Vorkerze stornieren
    cancelled = cancel_all_entries(ex)
    if cancelled:
        log.info(f'{len(cancelled)} Entry-Limit(s) der Vorkerze storniert.')

    # 2. Positionen abgleichen
    live = all_positions(ex)
    for sym, pend in list(st['pending'].items()):
        p = live.get(sym)
        if p is not None and sym not in st['positions']:
            st['positions'][sym] = dict(pend, entry=float(p.get('entryPrice') or pend['band']),
                                        contracts=float(p['contracts']))
            msgs.append(f"FILL {sym.split('/')[0]} {pend['strategy']} @ {float(p.get('entryPrice') or 0):.6g} "
                        f"SL {pend['sl']:.6g}")
    st['pending'] = {}
    for sym in list(st['positions']):
        if sym not in live:
            v = st['positions'].pop(sym)
            msgs.append(f"EXIT {sym.split('/')[0]} {v['strategy']} (TP/SL an der Boerse)")
            cancel_close_limits(ex, sym)

    raw, natives, daily = fetch_market_data(ex, coins, t)
    if 'BTC' not in raw:
        raise RuntimeError('BTC-Daten fehlen -- Zyklus abgebrochen')
    data, i = signals_at(raw, natives, daily, t)
    names = data['names']; col = {n: j for j, n in enumerate(names)}

    # 3. Positionen verwalten
    for sym, v in list(st['positions'].items()):
        coin = sym.split('/')[0]; tf = v['tf']; j = col.get(coin)
        held_h = (t - pd.Timestamp(v['bar'])).total_seconds() / 3600
        if held_h >= W.MAX_BARS * tf + .5:          # Backtest: Schluss der 118.(x tf) 30m-Kerze = Open der naechsten
            cancel_close_limits(ex, sym); ex.close_position(sym); st['positions'].pop(sym)
            msgs.append(f'ZEIT-EXIT {coin} nach {held_h:.0f} h'); continue
        if not has_stop(ex, sym, float(live[sym].get('entryPrice') or v['band'])):
            px = float(ex.fetch_ticker(sym)['last'])
            if px <= v['sl']:
                ex.close_position(sym); st['positions'].pop(sym); msgs.append(f'NOT-EXIT {coin}: SL fehlte, Kurs unter SL')
                continue
            ex.place_trigger_market_order(sym, 'sell', float(live[sym]['contracts']), v['sl'], reduce=True)
            msgs.append(f'SL nachgelegt {coin} @ {v["sl"]:.6g}')
        cancel_close_limits(ex, sym)
        mid = data['f'][tf][0][i, j] if j is not None else np.nan
        if np.isfinite(mid):
            ex.place_limit_order(sym, 'sell', float(live[sym]['contracts']), float(mid), reduce=True)
            v['tp'] = float(mid)

    # 4. neue Entry-Limits
    placed = []
    if data['entry_ok'][i]:
        equity = float(ex.fetch_equity_usdt()); available = float(ex.fetch_balance_usdt())
        slots = W.K - len(live)
        budget = 0.0
        for sym, p in live.items():
            v = st['positions'].get(sym)
            notional = abs(float(p['contracts'])) * float(p.get('entryPrice') or 0) * float(p.get('contractSize') or 1)
            budget += v['risk'] if v else notional * (W.STOP_PCT + W.MAKER + W.TAKER + W.SLIP)
        held = {s.split('/')[0] for s in live}
        o = data['p']['open'][i]
        for s, j in W.candidate_order(names, W.STRATEGIES):
            key = W.STRATEGIES[s]
            if not data['masks'][key][i, j]:
                continue
            coin = names[j]; sym = symbol_of(coin)
            if coin in held or st['last_entry_bar'].get(sym) == str(t) or not np.isfinite(o[j]):
                continue
            if slots <= 0:
                break
            if not tradable(ex, sym):
                log.info(f'{coin}: nicht handelbar (Delisting/Sperre) -- uebersprungen'); continue
            tf, _, depth = key
            mid, atr = data['f'][tf]; band = float(mid[i, j]) * (1 - depth / 100)
            n, dist_b = W.size_order(equity, available, budget, band, float(atr[i, j]))
            if dist_b >= band or n <= 0:
                continue
            # Backtest: Fill zu min(Open, band), Menge n/ep, Stop vom Fill-Preis aus
            ep = min(float(o[j]), band); dist = W.stop_distance(ep, float(atr[i, j]))
            if dist >= ep:
                continue
            amount = float(ex.amount_to_precision(sym, n / ep))
            min_amt = ex.fetch_min_amount_tradable(sym)
            if amount <= 0 or amount < min_amt or amount * ep < W.MIN_NOTIONAL:
                log.info(f'{coin}: Menge {amount} unter Boersenminimum {min_amt} -- uebersprungen'); continue
            sl = ep - dist
            if sym not in st['prepared']:
                ex.set_margin_mode(sym, 'isolated'); ex.set_leverage(sym, W.L, 'isolated'); st['prepared'][sym] = True
            try:
                order = place_entry(ex, sym, amount, band, sl)
            except Exception as e:
                log.error(f'{coin}: Entry-Order fehlgeschlagen: {e}'); continue
            loss = dist_b / band + W.MAKER + W.TAKER + W.SLIP        # Reservierung wie Backtest (band-basiert)
            st['pending'][sym] = dict(order_id=order.get('id'), strategy=list(key), tf=tf, band=band, sl=sl, bar=str(t),
                                      risk=n * (dist / ep + W.MAKER + W.TAKER + W.SLIP), notional=n)
            st['last_entry_bar'][sym] = str(t)
            available -= n / W.L + n * W.MAKER; budget += n * loss; slots -= 1; held.add(coin)
            placed.append(f'{coin} {tf}h/{depth}% @ {band:.6g} SL {sl:.6g} ({n:.1f} USDT)')
    else:
        reason = 'BTC unter SMA50' if not data['btc50'][i] else 'V2-Pause (Marktabverkauf)'
        log.info(f'Keine neuen Einstiege: {reason}')

    st['last_bar'] = str(t)
    save_state(st)
    if placed:
        msgs.append('Neue Limits: ' + '; '.join(placed))
    if msgs:
        notify('FiBot Wick-Konfluenz ' + t.strftime('%d.%m. %H:%M') + '\n' + '\n'.join(msgs))
    log.info(f'Zyklus {t}: {len(placed)} Limit(s), {len(st["positions"])} Position(en).')
    return st


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                        handlers=[logging.FileHandler(os.path.join(PROJECT_ROOT, 'logs', 'wick_mtf.log')),
                                  logging.StreamHandler()])
    from fibot.utils.exchange import Exchange
    from fibot.utils.telegram import send_message
    with open(os.path.join(PROJECT_ROOT, 'secret.json')) as f:
        secrets = json.load(f)
    acc = secrets['fibot'][0] if isinstance(secrets['fibot'], list) else secrets['fibot']
    tg = secrets.get('telegram', {})
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if time.time() - os.path.getmtime(LOCK_FILE) < 600:
            log.warning('Anderer Lauf aktiv -- beende.'); return
        os.remove(LOCK_FILE); fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode()); os.close(fd)
        run_cycle(Exchange(acc), notify=lambda m: send_message(tg.get('bot_token'), tg.get('chat_id'), m))
    except Exception as e:
        log.exception(f'Zyklus fehlgeschlagen: {e}')
        try:
            send_message(tg.get('bot_token'), tg.get('chat_id'), f'FiBot Wick-Konfluenz FEHLER: {e}')
        except Exception:
            pass
    finally:
        try:
            os.remove(LOCK_FILE)
        except FileNotFoundError:
            pass


if __name__ == '__main__':
    main()
