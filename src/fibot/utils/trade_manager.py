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
from fibot.utils.telegram import send_message, send_photo
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
# Housekeeper
# ---------------------------------------------------------------------------

def housekeeper_routine(exchange: Exchange, symbol: str, tracker_path: str, logger) -> bool:
    """Storniert offene Orders, schließt verwaiste Positionen, leert den Tracker.
    Wird aufgerufen wenn keine offene Position existiert (nach SL/TP oder Pending-Cancel)."""
    try:
        logger.info(f"Housekeeper: Starte Aufräumroutine für {symbol}...")
        exchange.cancel_all_orders_for_symbol(symbol)
        time.sleep(1)

        # Sicherheitsnetz: verwaiste Position schließen
        positions = exchange.fetch_open_positions(symbol)
        if positions:
            pos        = positions[0]
            close_side = 'sell' if pos['side'] == 'long' else 'buy'
            contracts  = float(pos.get('contracts', 0))
            logger.warning(f"Housekeeper: Verwaiste Position ({pos['side']} {contracts}) — schließe...")
            exchange.place_market_order(symbol, close_side, contracts, reduce=True)
            time.sleep(3)
            if exchange.fetch_open_positions(symbol):
                logger.error("Housekeeper: Position konnte nicht geschlossen werden!")
                return False

        # Tracker leeren falls ein abgeschlossener Trade drin steht
        tracker_data = read_tracker(tracker_path)
        if tracker_data.get('status') in ('open', 'pending_entry'):
            write_tracker(tracker_path, {})
            logger.info(f"Housekeeper: Tracker für {symbol} geleert.")

        logger.info(f"Housekeeper: {symbol} ist sauber.")
        return True
    except Exception as e:
        logger.error(f"Housekeeper-Fehler: {e}", exc_info=True)
        return False


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
# Chart-Generierung: Fibonacci-Kerzendiagramm mit Levels + Entry/SL/TP
# ---------------------------------------------------------------------------

def _generate_fib_chart_png(df: pd.DataFrame, signal: FibSignal, symbol: str,
                              timeframe: str, n_candles: int = 40) -> Optional[str]:
    """
    Zeichnet Kerzendiagramm mit Fibonacci-Grid, Entry-Zone und Entry/SL/TP-Tags.
    Gibt Pfad zur temporaeren PNG-Datei zurueck (oder None bei Fehler).
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
    except ImportError:
        return None

    if df is None or df.empty:
        return None

    from datetime import timezone

    display_df = df[['open', 'high', 'low', 'close']].iloc[-n_candles:].reset_index(drop=True)
    n = len(display_df)
    if n == 0:
        return None

    opens  = display_df['open'].values
    highs  = display_df['high'].values
    lows   = display_df['low'].values
    closes = display_df['close'].values

    entry  = signal.entry_price
    sl     = signal.sl_price
    tp     = signal.tp1_price
    fibs   = signal.fib_levels
    side   = signal.direction

    fig, ax = plt.subplots(figsize=(14, 7))
    fig.patch.set_facecolor('#0d1117')
    ax.set_facecolor('#0d1117')

    bar_w = 0.6

    # 1. Kerzen
    for i in range(n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        color = '#26a69a' if c >= o else '#ef5350'
        ax.plot([i, i], [l, h], color=color, linewidth=0.8, zorder=2)
        body_h = max(abs(c - o), (h - l) * 0.005)
        ax.add_patch(mpatches.FancyBboxPatch(
            (i - bar_w / 2, min(o, c)), bar_w, body_h,
            boxstyle="square,pad=0", linewidth=0, facecolor=color, zorder=3,
        ))

    # 2. Y-Limits
    y_min = float(lows.min())
    y_max = float(highs.max())
    for p in [entry, sl, tp, fibs.swing_high, fibs.swing_low]:
        if p:
            y_min = min(y_min, float(p) * 0.999)
            y_max = max(y_max, float(p) * 1.001)
    margin = (y_max - y_min) * 0.15
    y_lo, y_hi = y_min - margin, y_max + margin
    ax.set_xlim(-1, n + 1)
    ax.set_ylim(y_lo, y_hi)

    def _in_range(price):
        return y_lo < float(price) < y_hi

    # 3. Fibonacci-Grid
    FIB_STYLE = {
        '0.0':   ('#ffffff', 0.5, '--'),
        '23.6':  ('#90caf9', 0.4, ':'),
        '38.2':  ('#ffd700', 0.7, '--'),
        '50.0':  ('#ce93d8', 0.5, '--'),
        '61.8':  ('#ffd700', 0.7, '--'),
        '78.6':  ('#90caf9', 0.4, ':'),
        '100.0': ('#ffffff', 0.5, '--'),
        '127.2': ('#80cbc4', 0.4, ':'),
        '161.8': ('#00e676', 0.6, '--'),
    }
    for key, price in fibs.levels.items():
        if not _in_range(price):
            continue
        color, alpha, ls = FIB_STYLE.get(key, ('#888888', 0.3, ':'))
        ax.axhline(price, color=color, linewidth=0.7, linestyle=ls, alpha=alpha, zorder=4)
        ax.text(n + 0.2, price, f' {key}%', color=color, fontsize=7,
                va='center', alpha=0.85, zorder=5)

    # 4. Entry-Zone shading (38.2–61.8% des Fib-Grids)
    if side == 'long':
        zone_lo = fibs.levels.get('38.2', 0)
        zone_hi = fibs.levels.get('61.8', 0)
    else:
        zone_lo = fibs.levels.get('61.8', 0)
        zone_hi = fibs.levels.get('38.2', 0)
    if zone_lo and zone_hi:
        ax.axhspan(min(zone_lo, zone_hi), max(zone_lo, zone_hi),
                   color='#ffd700', alpha=0.06, zorder=1)

    # 5. Risiko/Reward-Zonen
    ax.axhspan(min(sl, entry), max(sl, entry), color='#ff1744', alpha=0.07, zorder=1)
    ax.axhspan(min(tp, entry), max(tp, entry), color='#00c853', alpha=0.07, zorder=1)

    # 6. Swing High / Low Marker
    if _in_range(fibs.swing_high):
        ax.axhline(fibs.swing_high, color='#ef9a9a', linewidth=0.6,
                   linestyle=':', alpha=0.5, zorder=4)
        ax.text(0.2, fibs.swing_high, ' Swing H', color='#ef9a9a',
                fontsize=7, va='bottom', alpha=0.75, zorder=5)
    if _in_range(fibs.swing_low):
        ax.axhline(fibs.swing_low, color='#a5d6a7', linewidth=0.6,
                   linestyle=':', alpha=0.5, zorder=4)
        ax.text(0.2, fibs.swing_low, ' Swing L', color='#a5d6a7',
                fontsize=7, va='top', alpha=0.75, zorder=5)

    # 7. Entry/SL/TP Preis-Tags
    def _price_tag(price, label, color, lw=1.5, ls='--'):
        if not _in_range(price):
            return
        ax.axhline(price, color=color, linewidth=lw, linestyle=ls, zorder=6)
        ax.text(n - 0.3, price, f'  {label}: {price:.6g}  ',
                color='#0d1117', fontsize=8.5, va='center', ha='right',
                fontweight='bold', zorder=8,
                bbox=dict(facecolor=color, edgecolor='none', alpha=0.92,
                          boxstyle='square,pad=0.25'))

    _price_tag(tp,    'TP',    '#00c853')
    _price_tag(entry, 'Entry', '#ffd700')
    _price_tag(sl,    'SL',    '#ff1744')

    # 8. Struktur-Trendlinien
    struct = signal.structure
    n_struct = struct.n_bars  # Anzahl Bars im Struktur-Fenster (z.B. 60)
    if n_struct > 0 and struct.type != 'none':
        # Offset: Struktur-Index des ersten sichtbaren Display-Bars
        struct_offset = n_struct - n_candles
        xs = list(range(n))
        upper_ys = [struct.upper_slope * (i + struct_offset) + struct.upper_intercept for i in xs]
        lower_ys = [struct.lower_slope * (i + struct_offset) + struct.lower_intercept for i in xs]
        # Nur zeichnen wo Werte im Y-Bereich liegen
        ax.plot(xs, upper_ys, color='#ef9a9a', linewidth=0.9, linestyle='--',
                alpha=0.6, zorder=5, label='Resistance')
        ax.plot(xs, lower_ys, color='#a5d6a7', linewidth=0.9, linestyle='--',
                alpha=0.6, zorder=5, label='Support')

    # 9. Info-Box oben links mit Signal-Kriterien
    side_label = 'LONG ▲' if side == 'long' else 'SHORT ▼'
    sl_pct  = abs(entry - sl) / entry * 100
    tp_pct  = abs(tp - entry) / entry * 100
    rr      = tp_pct / sl_pct if sl_pct > 0 else 0

    # Signal-Kriterien aus reason parsen ("SHORT | K1 | K2 | ..." → ["K1", "K2", ...])
    reason_parts = signal.reason.split(' | ') if signal.reason else []
    # Erstes Element ist die Richtung ("LONG"/"SHORT") → überspringen
    criteria = [p for p in reason_parts[1:] if p and not p.startswith('R:R')]
    criteria = criteria[:4]  # max 4 Zeilen

    info_lines = [
        f"{side_label}   Score: {signal.score:.1f}/10   R:R 1:{rr:.1f}",
        f"Struktur: {struct.type} ({struct.bias})",
        "─" * 32,
    ] + [f"✓ {c}" for c in criteria] + [
        f"Swing H: {fibs.swing_high:.6g}   Swing L: {fibs.swing_low:.6g}",
    ]
    ax.text(0.01, 0.98, '\n'.join(info_lines),
            transform=ax.transAxes, fontsize=7.5, va='top', ha='left',
            color='#cccccc', fontfamily='monospace',
            bbox=dict(facecolor='#1a2332', edgecolor='#2a3a4a',
                      alpha=0.88, boxstyle='round,pad=0.5'),
            zorder=9)

    # 11. Styling
    ax.set_title(
        f"FIBOT  |  {symbol}  {timeframe}  |  {side_label}  |  letzte {n} Kerzen",
        color='#e0e0e0', fontsize=11, pad=10,
    )
    ax.tick_params(colors='#888888', labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor('#2a3a4a')
    ax.set_xticks([])
    ax.yaxis.tick_right()
    ax.grid(axis='y', color='#1e2a3a', linewidth=0.4, zorder=0)
    plt.tight_layout()

    tmp_dir = os.path.join(PROJECT_ROOT, 'artifacts', 'tmp')
    os.makedirs(tmp_dir, exist_ok=True)
    from datetime import datetime, timezone
    ts       = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    sym_safe = symbol.replace('/', '-').replace(':', '-')
    path     = os.path.join(tmp_dir, f'fib_entry_{sym_safe}_{timeframe}_{ts}.png')
    fig.savefig(path, dpi=130, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


def _send_fib_chart(df: pd.DataFrame, signal: FibSignal, symbol: str, timeframe: str,
                     telegram_config: dict, logger):
    """Generiert Fibonacci-Chart-PNG und sendet es via Telegram."""
    bot_token = telegram_config.get('bot_token', '')
    chat_id   = telegram_config.get('chat_id', '')
    if not bot_token or not chat_id:
        return
    try:
        path = _generate_fib_chart_png(df, signal, symbol, timeframe)
        if path and os.path.exists(path):
            side_label = 'LONG' if signal.direction == 'long' else 'SHORT'
            caption = (
                f"FIBOT | {symbol} ({timeframe})\n"
                f"{side_label} @ {signal.entry_price:.6g}  |  "
                f"SL: {signal.sl_price:.6g}  |  TP: {signal.tp1_price:.6g}  |  "
                f"Score: {signal.score:.1f}/10"
            )
            send_photo(bot_token, chat_id, path, caption)
            os.remove(path)
    except Exception as e:
        logger.warning(f"Fib-Chart senden fehlgeschlagen: {e}")


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
                    # Fallback: TP aus Entry + SL rekonstruieren (1:2 R:R)
                    # entry_val: Tracker bevorzugt, sonst direkt aus Position
                    entry_val = tracker_data.get('entry_price') or (entry_price if entry_price > 0 else None)
                    # sl_price_val: Tracker bevorzugt, sonst aus dem noch vorhandenen SL-Trigger-Order
                    if not sl_price_val and sl_exists:
                        for _o in trigger_orders:
                            _trig = (_o.get('stopPrice') or _o.get('triggerPrice')
                                     or _o.get('info', {}).get('triggerPrice')
                                     or _o.get('info', {}).get('planPrice'))
                            try:
                                _trig_f = float(_trig)
                                if (pos_side == 'long' and _trig_f < entry_price) or \
                                   (pos_side == 'short' and _trig_f > entry_price):
                                    sl_price_val = _trig_f
                                    break
                            except (ValueError, TypeError):
                                continue
                    if entry_val and sl_price_val and contracts_pos > 0:
                        rr = float(params.get('strategy', {}).get('min_rr', 2.0))
                        sl_dist = abs(float(entry_val) - float(sl_price_val))
                        if pos_side == 'long':
                            recovered_tp = float(entry_val) + rr * sl_dist
                        else:
                            recovered_tp = float(entry_val) - rr * sl_dist
                        logger.warning(f"TP-Preis rekonstruiert aus Entry/SL (min_rr={rr}): {recovered_tp:.4f}")
                        try:
                            tp_resp = exchange.place_trigger_market_order(
                                symbol, close_side, contracts_pos, recovered_tp, reduce=True)
                            new_tp_id = str(tp_resp.get('id', '')) if tp_resp else ''
                            tracker_data['tp_order_id'] = new_tp_id
                            tracker_data['tp1_price'] = recovered_tp
                            logger.info(f"TP rekonstruiert & repariert @ {recovered_tp:.4f} (ID: {new_tp_id})")
                            send_message(bot_token, chat_id,
                                         f"FiBot TP-Rekonstruktion ({symbol}): kein tp1_price im Tracker, "
                                         f"TP neu berechnet @ {recovered_tp:.4f} (1:2 R:R) und gesetzt.")
                        except Exception as e:
                            logger.error(f"TP-Rekonstruktion fehlgeschlagen: {e}")
                            send_message(bot_token, chat_id,
                                         f"FiBot ALARM ({symbol}): TP fehlt, Rekonstruktion fehlgeschlagen: {e}")
                    else:
                        logger.error("TP fehlt und auch Entry/SL-Preis unbekannt — manuelle Intervention nötig!")
                        send_message(bot_token, chat_id,
                                     f"FiBot ALARM ({symbol}): TP fehlt, Preis unbekannt — manuelle Intervention!")

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
                    time.sleep(2)
                    remaining = exchange.fetch_open_positions(symbol)
                    if not remaining:
                        write_tracker(tracker_path, {})
                        logger.info(f"Position {symbol} geschlossen — Tracker geleert.")
                    else:
                        logger.error(f"Notschliessung {symbol}: Position noch offen nach Market-Order — Tracker bleibt!")
                    send_message(
                        bot_token, chat_id,
                        f"FiBot NOTSCHLIESSUNG ({symbol}): Preis {current_price:.6f} hat "
                        f"{reason} ({level:.6f}) überschritten. Position geschlossen."
                    )
            except Exception as e:
                logger.error(f"Fehler beim Preis-Overshoot-Check: {e}")

        return  # Position läuft — nichts weiter tun

    # --- No open position → Aufräumen + neues Signal suchen ---
    housekeeper_routine(exchange, symbol, tracker_path, logger)
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

    # Notional-Check nach Precision-Rundung (Rundung kann unter 5 USDT fallen)
    notional_after_round = contracts * signal.entry_price
    if notional_after_round < MIN_NOTIONAL_USDT:
        logger.warning(f"Notional {notional_after_round:.2f} USDT < Minimum {MIN_NOTIONAL_USDT} USDT nach Precision-Rundung. Kein Trade.")
        return

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
    except ccxt.InsufficientFunds as e:
        logger.warning(f"Nicht genug freie Margin für Entry (andere Position belegt Kapital). Kein Trade.")
        return
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
        _send_fib_chart(df, signal, symbol, timeframe, telegram_config, logger)
    else:
        # Order pending — save as pending, will be checked next cycle
        _save_trade_state(tracker_path, signal, signal.entry_price, contracts,
                          entry_order_id, status="pending_entry")
        logger.info(f"Entry Order ausstehend (ID: {entry_order_id}).")
        summary = signal_summary(signal, symbol, timeframe)
        send_message(bot_token, chat_id,
                     f"FiBot ORDER GESETZT\n{summary}\n\nOrder ID: {entry_order_id}")
        _send_fib_chart(df, signal, symbol, timeframe, telegram_config, logger)


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
