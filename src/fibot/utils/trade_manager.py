# src/fibot/utils/trade_manager.py
# FiBot — Trade Manager
# Handles the complete trade lifecycle: entry, TP/SL placement, position monitoring

import logging
import time
import json
import os
import sys
from datetime import datetime
from typing import Optional

import ccxt
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from fibot.utils.exchange import Exchange
from fibot.utils.telegram import send_message
from fibot.strategy.fibonacci_logic import generate_signal, signal_summary, FibSignal

TRACKER_DIR = os.path.join(PROJECT_ROOT, 'artifacts', 'tracker')
MIN_NOTIONAL_USDT = 5.0

# ---------------------------------------------------------------------------
# Tracker helpers
# ---------------------------------------------------------------------------

def get_tracker_path(symbol: str, timeframe: str) -> str:
    os.makedirs(TRACKER_DIR, exist_ok=True)
    safe = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    return os.path.join(TRACKER_DIR, f"fibot_{safe}.json")


def read_tracker(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def write_tracker(path: str, data: dict):
    try:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        logging.getLogger(__name__).error(f"Tracker-Schreibfehler: {e}")


def update_performance(path: str, result: str, logger):
    """result: 'win' | 'loss' | 'breakeven'"""
    data = read_tracker(path)
    perf = data.get('performance', {
        'total_trades': 0, 'wins': 0, 'losses': 0,
        'consecutive_losses': 0, 'max_consecutive_losses': 0
    })
    perf['total_trades'] += 1
    if result == 'win':
        perf['wins'] += 1
        perf['consecutive_losses'] = 0
    elif result == 'loss':
        perf['losses'] += 1
        perf['consecutive_losses'] += 1
        perf['max_consecutive_losses'] = max(
            perf['max_consecutive_losses'], perf['consecutive_losses'])
    total = perf['total_trades']
    perf['win_rate'] = round(perf['wins'] / total * 100, 1) if total else 0
    data['performance'] = perf
    write_tracker(path, data)
    logger.info(f"Performance: {perf['wins']}W / {perf['losses']}L | WR {perf['win_rate']}%")


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------

def calc_position_size(balance: float, risk_pct: float, entry: float,
                        sl: float, leverage: int, logger,
                        min_contracts: float = 0.0) -> float:
    """
    Risikobased Sizing:
      risk_amount = balance * risk_pct/100
      contracts   = risk_amount / |entry - sl|
    Wird auf Exchange-Minimum angehoben wenn nötig (wie vbot).
    Capped by leverage, margin check, minimum notional.
    """
    risk_amount = balance * risk_pct / 100
    price_risk  = abs(entry - sl)
    if price_risk <= 0:
        logger.error("SL = Entry, Size-Berechnung unmöglich.")
        return 0.0
    contracts = risk_amount / price_risk

    # Auf Exchange-Minimum anheben wenn nötig (statt Trade zu skippen)
    if min_contracts > 0 and contracts < min_contracts:
        logger.info(f"Contracts {contracts:.6f} < Exchange-Minimum {min_contracts}, hebe auf Minimum an.")
        contracts = min_contracts

    # Cap: max notional = balance * leverage
    max_notional = balance * leverage
    max_contracts = max_notional / entry
    contracts = min(contracts, max_contracts)

    notional = contracts * entry
    if notional < MIN_NOTIONAL_USDT:
        logger.warning(f"Notional {notional:.2f} USDT < Minimum {MIN_NOTIONAL_USDT} USDT. Kein Trade.")
        return 0.0

    # Margin-Check: isolierte Margin darf Kapital nicht übersteigen
    margin = notional / leverage
    if margin > balance:
        logger.warning(f"Margin {margin:.2f} USDT > Kapital {balance:.2f} USDT. Kein Trade.")
        return 0.0

    logger.info(f"Size: {contracts:.6f} Contracts | Notional: {notional:.2f} USDT | Risiko: {risk_amount:.2f} USDT")
    return contracts


# ---------------------------------------------------------------------------
# Main trade cycle
# ---------------------------------------------------------------------------

def full_trade_cycle(exchange: Exchange, params: dict, telegram_config: dict, logger):
    """
    Called once per cron tick for one symbol/timeframe.
    1. Check existing position → manage it
    2. If no position → check for new Fib signal → enter
    """
    symbol    = params['market']['symbol']
    timeframe = params['market']['timeframe']
    leverage  = int(params['risk'].get('leverage', 10))
    margin_mode = params['risk'].get('margin_mode', 'isolated')
    risk_pct  = float(params['risk'].get('risk_per_entry_pct', 1.0))
    min_score = float(params['strategy'].get('min_signal_score', 4.0))
    candle_limit = int(params['strategy'].get('candle_limit', 300))

    bot_token = telegram_config.get('bot_token', '')
    chat_id   = telegram_config.get('chat_id', '')
    tracker_path = get_tracker_path(symbol, timeframe)

    logger.info(f"--- FiBot Cycle: {symbol} {timeframe} ---")

    # --- Set leverage & margin ---
    exchange.set_margin_mode(symbol, margin_mode)
    time.sleep(0.3)
    exchange.set_leverage(symbol, leverage, margin_mode)
    time.sleep(0.3)

    # --- Check open positions ---
    positions = exchange.fetch_open_positions(symbol)
    if positions:
        pos = positions[0]
        pos_side = pos.get('side', 'long')
        size_key = 'contracts' if 'contracts' in pos else 'contractSize'
        contracts_pos = float(pos.get(size_key, 0))
        entry_price = float(pos.get('entryPrice', 0))
        pnl = float(pos.get('unrealizedPnl', 0))
        logger.info(f"Offene Position: {pos_side.upper()} {contracts_pos} @ {entry_price:.4f} | PnL {pnl:.2f} USDT")

        # --- Self-Repair: SL/TP prüfen und ggf. neu platzieren (wie vbot) ---
        try:
            tracker_data   = read_tracker(tracker_path)
            trigger_orders = exchange.fetch_open_trigger_orders(symbol)
            open_order_ids = {str(o.get('id', '')) for o in trigger_orders}
            close_side     = 'sell' if pos_side == 'long' else 'buy'

            saved_sl_id  = str(tracker_data.get('sl_order_id', ''))
            saved_tp_id  = str(tracker_data.get('tp_order_id', ''))
            sl_price_val = tracker_data.get('sl_price')
            tp_price_val = tracker_data.get('tp1_price')

            if saved_sl_id and saved_tp_id:
                # ID-basierte Erkennung (zuverlässig)
                sl_exists = saved_sl_id in open_order_ids
                tp_exists = saved_tp_id in open_order_ids
                logger.info(f"ID-Check — SL={sl_exists} (ID:{saved_sl_id}) TP={tp_exists} (ID:{saved_tp_id})")
            else:
                # Preis-Fallback: SL/TP anhand Entry-Preis-Relation erkennen
                sl_exists = False
                tp_exists = False
                if entry_price > 0:
                    for order in trigger_orders:
                        trig_raw = (order.get('stopPrice') or order.get('triggerPrice')
                                    or order.get('info', {}).get('triggerPrice')
                                    or order.get('info', {}).get('planPrice'))
                        try:
                            trig = float(trig_raw)
                        except (ValueError, TypeError):
                            continue
                        if pos_side == 'long':
                            if trig < entry_price:
                                sl_exists = True
                            elif trig > entry_price:
                                tp_exists = True
                        else:
                            if trig > entry_price:
                                sl_exists = True
                            elif trig < entry_price:
                                tp_exists = True
                    logger.info(f"Preis-Fallback — SL={sl_exists} TP={tp_exists} | {len(trigger_orders)} Trigger-Orders")

            if not sl_exists or not tp_exists:
                logger.warning(f"Self-Repair: SL={sl_exists} TP={tp_exists} — platziere fehlende Orders neu")
                if not sl_exists and sl_price_val and contracts_pos > 0:
                    try:
                        sl_resp = exchange.place_trigger_market_order(
                            symbol, close_side, contracts_pos, float(sl_price_val), reduce=True)
                        new_sl_id = str(sl_resp.get('id', '')) if sl_resp else ''
                        tracker_data['sl_order_id'] = new_sl_id
                        logger.info(f"SL repariert @ {sl_price_val:.4f} (neue ID: {new_sl_id})")
                    except Exception as e:
                        logger.error(f"SL-Reparatur fehlgeschlagen: {e}")
                elif not sl_exists and not sl_price_val:
                    logger.error("SL fehlt aber SL-Preis unbekannt — manuelle Intervention nötig!")

                if not tp_exists and tp_price_val and contracts_pos > 0:
                    try:
                        tp_resp = exchange.place_trigger_market_order(
                            symbol, close_side, contracts_pos, float(tp_price_val), reduce=True)
                        new_tp_id = str(tp_resp.get('id', '')) if tp_resp else ''
                        tracker_data['tp_order_id'] = new_tp_id
                        logger.info(f"TP repariert @ {tp_price_val:.4f} (neue ID: {new_tp_id})")
                    except Exception as e:
                        logger.error(f"TP-Reparatur fehlgeschlagen: {e}")
                elif not tp_exists and not tp_price_val:
                    logger.error("TP fehlt aber TP-Preis unbekannt — manuelle Intervention nötig!")

                write_tracker(tracker_path, tracker_data)
                send_message(bot_token, chat_id,
                             f"FiBot Self-Repair ({symbol}): SL={sl_exists} TP={tp_exists} — Orders neu gesetzt.")
        except Exception as e:
            logger.error(f"Fehler beim Self-Repair-Check: {e}")

        # --- Preis-Overshoot-Check: Position schließen falls Preis SL oder TP überschritten ---
        if sl_price_val and tp_price_val and contracts_pos > 0:
            try:
                current_price = float(exchange.fetch_ticker(symbol)['last'])
                sl_val = float(sl_price_val)
                tp_val = float(tp_price_val)
                if pos_side == 'long':
                    breached = current_price <= sl_val or current_price >= tp_val
                    reason   = "SL" if current_price <= sl_val else "TP"
                else:
                    breached = current_price >= sl_val or current_price <= tp_val
                    reason   = "SL" if current_price >= sl_val else "TP"
                if breached:
                    level = sl_val if reason == 'SL' else tp_val
                    logger.warning(
                        f"Preis-Overshoot: {current_price:.6f} hat {reason} ({level:.6f}) überschritten — "
                        f"schließe Position {symbol} per Market."
                    )
                    try:
                        exchange.cancel_all_orders_for_symbol(symbol)
                    except Exception as ce:
                        logger.warning(f"Cancel-Orders fehlgeschlagen (ignoriert): {ce}")
                    exchange.place_market_order(symbol, close_side, contracts_pos, reduce=True)
                    write_tracker(tracker_path, {})
                    send_message(
                        bot_token, chat_id,
                        f"FiBot NOTSCHLIESSUNG ({symbol}): Preis {current_price:.6f} hat "
                        f"{reason} ({level:.6f}) überschritten. Position geschlossen."
                    )
                    logger.info(f"Position {symbol} geschlossen — Tracker geleert.")
            except Exception as e:
                logger.error(f"Fehler beim Preis-Overshoot-Check: {e}")

        return  # Position läuft — nichts weiter tun

    # --- No open position → look for new signal ---
    logger.info("Keine offene Position. Suche Fib-Signal...")

    df = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=candle_limit)
    if df.empty or len(df) < 150:
        logger.warning(f"Zu wenig Daten: {len(df)} Kerzen.")
        return

    signal: FibSignal = generate_signal(df, params)

    if signal.direction == "none":
        logger.info("Kein Signal.")
        return

    if signal.score < min_score:
        logger.info(f"Score {signal.score:.1f} < Minimum {min_score}. Signal ignoriert.")
        return

    # --- Get balance ---
    balance = exchange.fetch_balance_usdt()
    if balance <= 0:
        logger.error("Kontostand 0 oder nicht abrufbar.")
        return

    # --- Calc size ---
    min_amount = exchange.markets.get(symbol, {}).get('limits', {}).get('amount', {}).get('min', 0.0)
    contracts = calc_position_size(
        balance, risk_pct, signal.entry_price, signal.sl_price, leverage, logger,
        min_contracts=min_amount)
    if contracts <= 0:
        return

    contracts_str = exchange.amount_to_precision(symbol, contracts)
    contracts = float(contracts_str)

    # Sicherheitsnetz: amount_to_precision rundet ggf. unter Exchange-Minimum
    if min_amount > 0 and contracts < min_amount:
        logger.info(f"Nach Precision-Rundung {contracts:.6f} < Minimum {min_amount} — hebe erneut an.")
        contracts = min_amount
        contracts_str = exchange.amount_to_precision(symbol, contracts)
        contracts = float(contracts_str)
        notional = contracts * signal.entry_price
        if notional < MIN_NOTIONAL_USDT:
            logger.warning(f"Notional {notional:.2f} USDT < Minimum {MIN_NOTIONAL_USDT} USDT nach Korrektur. Kein Trade.")
            return

    # --- Place entry (Limit at signal price, consistent with backtester) ---
    entry_side = 'buy' if signal.direction == 'long' else 'sell'

    logger.info(f"Platziere Entry: {entry_side.upper()} {contracts} @ {signal.entry_price:.4f}")
    try:
        entry_order = exchange.place_limit_order(
            symbol, entry_side, contracts, signal.entry_price)
    except Exception as e:
        logger.error(f"Entry-Order fehlgeschlagen: {e}")
        send_message(bot_token, chat_id, f"FiBot FEHLER ({symbol}): Entry fehlgeschlagen: {e}")
        return

    if not entry_order:
        logger.error("Entry-Order konnte nicht platziert werden.")
        return

    entry_order_id = entry_order.get('id')
    logger.info(f"Entry Order ID: {entry_order_id}")

    # Wait briefly for fill
    time.sleep(3)

    # Check if filled
    try:
        filled_order = exchange.fetch_order(entry_order_id, symbol)
    except Exception:
        filled_order = None

    if filled_order and filled_order.get('status') == 'closed':
        actual_entry = float(filled_order.get('average', signal.entry_price))
        logger.info(f"Entry gefüllt @ {actual_entry:.4f}")
        sl_order_id, tp_order_id = _place_tp_sl(exchange, symbol, entry_side, contracts,
                                                  actual_entry, signal, logger)
        _save_trade_state(tracker_path, signal, actual_entry, contracts, entry_order_id,
                          sl_order_id=sl_order_id, tp_order_id=tp_order_id)
        summary = signal_summary(signal, symbol, timeframe)
        send_message(bot_token, chat_id,
                     f"FiBot ENTRY\n{summary}\n\nFill: {actual_entry:.4f}")
    else:
        # Order pending — save as pending, will be checked next cycle
        _save_trade_state(tracker_path, signal, signal.entry_price, contracts,
                          entry_order_id, status="pending_entry")
        logger.info(f"Entry Order ausstehend (ID: {entry_order_id}).")
        summary = signal_summary(signal, symbol, timeframe)
        send_message(bot_token, chat_id,
                     f"FiBot ORDER GESETZT\n{summary}\n\nOrder ID: {entry_order_id}")


# ---------------------------------------------------------------------------
# TP / SL placement
# ---------------------------------------------------------------------------

def _place_tp_sl(exchange: Exchange, symbol: str, entry_side: str,
                  contracts: float, actual_entry: float,
                  signal: FibSignal, logger) -> tuple:
    """Places TP1 and SL trigger-market orders. Returns (sl_order_id, tp_order_id)."""
    close_side = 'sell' if entry_side == 'buy' else 'buy'
    sl_order_id = ''
    tp_order_id = ''

    # SL
    try:
        sl_order = exchange.place_trigger_market_order(
            symbol, close_side, contracts,
            trigger_price=signal.sl_price,
            reduce=True
        )
        sl_order_id = str(sl_order.get('id', '')) if sl_order else ''
        logger.info(f"SL Order platziert @ {signal.sl_price:.4f} | ID: {sl_order_id}")
    except Exception as e:
        logger.error(f"SL-Order fehlgeschlagen: {e}")

    time.sleep(0.5)

    # TP1
    try:
        tp_order = exchange.place_trigger_market_order(
            symbol, close_side, contracts,
            trigger_price=signal.tp1_price,
            reduce=True
        )
        tp_order_id = str(tp_order.get('id', '')) if tp_order else ''
        logger.info(f"TP1 Order platziert @ {signal.tp1_price:.4f} | ID: {tp_order_id}")
    except Exception as e:
        logger.error(f"TP1-Order fehlgeschlagen: {e}")

    return sl_order_id, tp_order_id


def _reattach_tp_sl(exchange: Exchange, position: dict, params: dict, logger):
    """Re-places TP/SL if they were lost (e.g. after restart)."""
    symbol = params['market']['symbol']
    side = position.get('side', 'long')
    size_key = 'contracts' if 'contracts' in position else 'contractSize'
    contracts = float(position.get(size_key, 0))
    entry_price = float(position.get('entryPrice', 0))

    # Read stored signal from tracker
    tracker_path = get_tracker_path(symbol, params['market']['timeframe'])
    data = read_tracker(tracker_path)
    sl_price  = data.get('sl_price', 0)
    tp1_price = data.get('tp1_price', 0)

    if not sl_price or not tp1_price:
        logger.warning("Keine gespeicherten TP/SL-Preise im Tracker. Überspringe.")
        return

    close_side = 'sell' if side == 'long' else 'buy'

    try:
        exchange.place_trigger_market_order(symbol, close_side, contracts,
                                             trigger_price=sl_price, reduce=True)
        logger.info(f"SL re-attached @ {sl_price:.4f}")
    except Exception as e:
        logger.error(f"SL re-attach fehlgeschlagen: {e}")

    time.sleep(0.5)

    try:
        exchange.place_trigger_market_order(symbol, close_side, contracts,
                                             trigger_price=tp1_price, reduce=True)
        logger.info(f"TP1 re-attached @ {tp1_price:.4f}")
    except Exception as e:
        logger.error(f"TP1 re-attach fehlgeschlagen: {e}")


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _save_trade_state(path: str, signal: FibSignal, entry: float,
                       contracts: float, order_id: str, status: str = "open",
                       sl_order_id: str = '', tp_order_id: str = ''):
    data = read_tracker(path)
    data.update({
        'status':       status,
        'direction':    signal.direction,
        'entry_price':  entry,
        'sl_price':     signal.sl_price,
        'tp1_price':    signal.tp1_price,
        'tp2_price':    signal.tp2_price,
        'contracts':    contracts,
        'order_id':     order_id,
        'sl_order_id':  sl_order_id,
        'tp_order_id':  tp_order_id,
        'signal_score': signal.score,
        'reason':       signal.reason,
        'timestamp':    datetime.utcnow().isoformat(),
    })
    write_tracker(path, data)
