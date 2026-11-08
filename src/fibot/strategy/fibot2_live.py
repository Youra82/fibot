# src/fibot/strategy/fibot2_live.py
# fibot 2.0 Live-Zyklus: EIN Prozess fuer alle Konfluenz-Configs (configs_fibot2/), Cron alle 15 Minuten.
# Je Lauf (Beginn einer 15m-Kerze t):
#   1. Pending-Entries abgleichen: gefuellt -> Position (Impuls B verbraucht), sonst bei faelliger Config stornieren
#   2. faellige Configs (deren Kerze bei t schliesst): Kerzen laden, virtuelle Trades der letzten 14 Tage neu rechnen
#   3. Phasentor je Zeitebene aus den virtuellen Trades ALLER Configs
#   4. faellige Configs: plan_next_order (unveraenderter Detektor) -> Mindest-Stop 2 ATR, Tor offen, Coin frei,
#      Impuls nicht verbraucht -> Limit mit angehaengtem TP/SL (Groesse: 0,7 % Risiko, Summe Notional <= 10 x Konto)
# Harte Sperren: eine Position bzw. Order je Coin, ein Einstieg je Impuls, eine Order je Config und Kerze.
import glob
import json
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from fibot.strategy import fibot2_logic as F  # noqa: E402
from fibot.strategy.confluence_logic import plan_next_order  # noqa: E402

CONFIG_DIR = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs_fibot2')
STATE_FILE = os.path.join(PROJECT_ROOT, 'artifacts', 'fibot2_state.json')
EVENTS_FILE = os.path.join(PROJECT_ROOT, 'artifacts', 'fibot2_virtual.pkl')
LOCK_FILE = os.path.join(PROJECT_ROOT, 'artifacts', 'fibot2.lock')
TF_ORDER = {'1d': 0, '6h': 1, '4h': 2, '2h': 3, '1h': 4, '30m': 5, '15m': 6}   # hoehere Zeitebene zuerst
log = logging.getLogger('fibot2')


def tf_delta(tf):
    return pd.Timedelta(tf)


def window_bars(tf):
    return int(F.GATE_DAYS * 86400 / tf_delta(tf).total_seconds()) + 2000


def load_configs():
    out = []
    for p in sorted(glob.glob(os.path.join(CONFIG_DIR, '*.json'))):
        c = json.load(open(p))
        if c['market']['timeframe'] not in F.EXCLUDED_TF:
            c['_key'] = os.path.basename(p)[7:-9]
            out.append(c)
    return sorted(out, key=lambda c: (TF_ORDER[c['market']['timeframe']], c['_key']))


def due(cfg, t):
    """Config faellig, wenn bei t eine Kerze ihrer Zeitebene beginnt (vorherige gerade geschlossen)."""
    d = tf_delta(cfg['market']['timeframe'])
    return t == t.floor(d)


# ---------------------------------------------------------------- Zustand
def load_state():
    try:
        return json.load(open(STATE_FILE))
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(last_t=None, pending={}, positions={}, consumed={}, last_plan_candle={})


def save_state(st):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + '.tmp'
    json.dump(st, open(tmp, 'w'), indent=1, default=str); os.replace(tmp, STATE_FILE)


def load_events():
    try:
        return pd.read_pickle(EVENTS_FILE)
    except (FileNotFoundError, EOFError):
        return pd.DataFrame()


def save_events(ev):
    ev.to_pickle(EVENTS_FILE + '.tmp'); os.replace(EVENTS_FILE + '.tmp', EVENTS_FILE)


# ---------------------------------------------------------------- Boerse
def account_positions(ex):
    ps = ex.exchange.fetch_positions(params={'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'})
    return {p['symbol']: p for p in ps if abs(float(p.get('contracts') or 0)) > 1e-12}


OHLCV_DIR = os.path.join(PROJECT_ROOT, 'artifacts', 'fibot2_ohlcv')


def closed_candles(ex, symbol, tf, t):
    """Abgeschlossene Kerzen (Fenster window_bars). Lokaler Zwischenspeicher: nur neue Kerzen werden nachgeladen;
    die letzten 3 gespeicherten Kerzen werden immer neu geholt (Korrekturen der Boerse)."""
    os.makedirs(OHLCV_DIR, exist_ok=True)
    path = os.path.join(OHLCV_DIR, f"{symbol.split('/')[0]}_{tf}.pkl")
    need = window_bars(tf)
    try:
        old = pd.read_pickle(path)
    except (FileNotFoundError, EOFError):
        old = None
    if old is not None and len(old) >= need - 5:
        missing = int((t - old.index[-1]) / tf_delta(tf)) + 3
        new = ex.fetch_recent_ohlcv(symbol, tf, limit=max(missing, 5))
        df = old if new is None or new.empty else pd.concat([old[old.index < new.index[0]], new[['open', 'high', 'low', 'close']]])
    else:
        df = ex.fetch_recent_ohlcv(symbol, tf, limit=need)
    if df is None or df.empty:
        return None
    df = df[['open', 'high', 'low', 'close']].astype(float)
    df = df[~df.index.duplicated(keep='last')].sort_index().iloc[-need:]
    df.to_pickle(path + '.tmp'); os.replace(path + '.tmp', path)     # atomar (Tagesbericht liest parallel)
    return df[df.index + tf_delta(tf) <= t]                     # nur abgeschlossene Kerzen


# ---------------------------------------------------------------- Zyklus
def run_cycle(ex, notify=lambda m: None, now=None):
    t = (now or pd.Timestamp.now(tz='UTC')).floor('15min')
    st = load_state()
    if st.get('last_t') and pd.Timestamp(st['last_t']) >= t:
        log.info(f'{t} bereits bearbeitet.'); return st
    cfgs = load_configs(); msgs = []
    due_cfgs = [c for c in cfgs if due(c, t)]

    # 1. Pending abgleichen
    live = account_positions(ex)
    for sym, pend in list(st['pending'].items()):
        order = None
        try:
            order = ex.fetch_order(pend['order_id'], sym)
        except Exception as e:
            log.warning(f'Order {sym} nicht abrufbar: {e}')
        filled = float((order or {}).get('filled') or 0) > 0 or sym in live
        if filled:
            st['consumed'][pend['cfg']] = (st['consumed'].get(pend['cfg'], []) + [pend['b_ts']])[-50:]
            if sym in live:
                st['positions'][sym] = pend
                msgs.append(f"FILL {sym.split('/')[0]} {pend['cfg'].split('_')[-1]} {pend['direction']} @ {pend['limit']:.6g} "
                            f"SL {pend['sl']:.6g} TP {pend['tp']:.6g}")
            else:
                msgs.append(f"FILL+EXIT {sym.split('/')[0]} zwischen zwei Laeufen")
            if (order or {}).get('status') == 'open':
                ex.cancel_order(pend['order_id'], sym)               # Rest einer Teilfuellung
            del st['pending'][sym]
        elif any(c['_key'] == pend['cfg'] for c in due_cfgs):
            ex.cancel_order(pend['order_id'], sym)                   # neue Kerze -> neu planen (nachziehen)
            del st['pending'][sym]
    for sym in list(st['positions']):
        if sym not in live:
            v = st['positions'].pop(sym)
            msgs.append(f"EXIT {sym.split('/')[0]} {v['cfg'].split('_')[-1]} (TP/SL)")
            ex.cancel_all_orders_for_symbol(sym)

    # 2. virtuelle Trades der faelligen Configs
    ev = load_events(); frames = {}
    since = t - pd.Timedelta(days=F.GATE_DAYS + 2)
    new_parts = []
    cached = set(ev.cfg.unique()) if not ev.empty else set()
    calc = [c for c in cfgs if c in due_cfgs or (c['_key'] not in cached and not st.get('warm_done'))]
    for c in calc:
        sym, tf = c['market']['symbol'], c['market']['timeframe']
        if sym not in ex.markets:
            continue
        df = closed_candles(ex, sym, tf, t)
        if df is None or len(df) < 400:
            continue
        frames[c['_key']] = df
        e = F.virtual_events(df, c, since=since - pd.Timedelta(days=30))
        if not e.empty:
            new_parts.append(e)
    if not ev.empty and calc:
        ev = ev[~ev.cfg.isin([c['_key'] for c in calc if c['_key'] in frames])]
    st['warm_done'] = True
    ev = pd.concat([ev] + new_parts, ignore_index=True) if new_parts else ev
    if not ev.empty:
        ev = ev[ev.exit_ts >= since]
    save_events(ev)

    # 3. Phasentor
    gates = {tf: F.gate_value(ev, tf, t) for tf in TF_ORDER}
    log.info('Phasentor: ' + ', '.join(f'{k} {v:+.3f}' if np.isfinite(v) else f'{k} -' for k, v in gates.items()))

    # 4. neue Orders
    equity = float(ex.fetch_equity_usdt())
    used = sum(abs(float(p['contracts'])) * float(p.get('entryPrice') or 0) for p in live.values())
    used += sum(v['notional'] for v in st['pending'].values())
    busy = {s.split('/')[0] for s in list(live) + list(st['pending'])}
    placed = []
    for c in due_cfgs:
        if c['_key'] not in frames:
            continue
        key = c['_key']; sym, tf = c['market']['symbol'], c['market']['timeframe']; coin = sym.split('/')[0]
        df = frames.get(key)
        if df is None or coin in busy or st['last_plan_candle'].get(key) == str(t):
            continue
        plan = plan_next_order(df, c)
        if plan is None or plan['b_ts'] in st['consumed'].get(key, []):
            continue
        x = F.feature_at(F.features_frame(df, tf), t)          # Kerze, die bei t vollstaendig bekannt ist
        g_open = bool(np.isfinite(gates[tf]) and gates[tf] > 0)
        why = F.entry_allowed(plan, float(x.atr_pct) if x is not None else np.nan, g_open)
        if why:
            log.info(f'{key}: {plan["direction"]} @ {plan["limit"]:.6g} verworfen ({why})'); continue
        risk_pct = abs(plan['limit'] - plan['sl']) / plan['limit']
        notional = equity * F.RISK_PER_TRADE / risk_pct
        if used + notional > F.MAX_NOTIONAL_X * equity:
            log.info(f'{key}: Notional-Grenze erreicht'); continue
        amount = float(ex.amount_to_precision(sym, notional / plan['limit']))
        if amount <= 0 or amount < ex.fetch_min_amount_tradable(sym) or amount * plan['limit'] < 5:
            log.info(f'{key}: Menge unter Boersenminimum'); continue
        side = 'buy' if plan['direction'] == 'long' else 'sell'
        try:
            if sym not in st.setdefault('prepared', {}):
                ex.set_margin_mode(sym, 'isolated'); ex.set_leverage(sym, 10, 'isolated'); st['prepared'][sym] = True
            order = ex.place_limit_order_with_tpsl(sym, side, amount, plan['limit'], plan['sl'], plan['tp'])
        except Exception as e:
            log.error(f'{key}: Order fehlgeschlagen: {e}'); continue
        st['pending'][sym] = dict(order_id=str(order.get('id')), cfg=key, direction=plan['direction'], limit=plan['limit'],
                                  sl=plan['sl'], tp=plan['tp'], b_ts=plan['b_ts'], candle=str(t), notional=notional)
        st['last_plan_candle'][key] = str(t)
        used += notional; busy.add(coin)
        placed.append(f"{coin} {tf} {plan['direction']} @ {plan['limit']:.6g} (SL {plan['sl']:.6g}, TP {plan['tp']:.6g})")

    st['last_t'] = str(t)
    save_state(st)
    if placed:
        msgs.append('Neue Limits: ' + '; '.join(placed))
    if msgs:
        notify('FiBot 2.0 ' + t.strftime('%d.%m. %H:%M') + '\n' + '\n'.join(msgs))
    log.info(f'{t}: {len(due_cfgs)} Configs faellig, {len(placed)} neue Limits, {len(st["positions"])} Positionen.')
    return st


def main():
    os.makedirs(os.path.join(PROJECT_ROOT, 'logs'), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                        handlers=[logging.FileHandler(os.path.join(PROJECT_ROOT, 'logs', 'fibot2.log')), logging.StreamHandler()])
    from fibot.utils.exchange import Exchange
    from fibot.utils.telegram import send_message
    secrets = json.load(open(os.path.join(PROJECT_ROOT, 'secret.json')))
    acc = secrets['fibot'][0] if isinstance(secrets['fibot'], list) else secrets['fibot']
    tg = secrets.get('telegram', {})
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if time.time() - os.path.getmtime(LOCK_FILE) < 840:
            log.warning('Anderer Lauf aktiv -- beende.'); return
        os.remove(LOCK_FILE); fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode()); os.close(fd)
        run_cycle(Exchange(acc), notify=lambda m: send_message(tg.get('bot_token'), tg.get('chat_id'), m))
    except Exception as e:
        log.exception(f'Zyklus fehlgeschlagen: {e}')
        try:
            send_message(tg.get('bot_token'), tg.get('chat_id'), f'FiBot 2.0 FEHLER: {e}')
        except Exception:
            pass
    finally:
        try:
            os.remove(LOCK_FILE)
        except FileNotFoundError:
            pass


if __name__ == '__main__':
    main()
