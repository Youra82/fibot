# src/fibot/utils/trade_manager.py
# FiBot — Trade Manager
# Handles the complete trade lifecycle: entry, TP/SL placement, position monitoring

import logging
import time
import json
import os
import sys
import math
from datetime import datetime
from typing import Optional

import ccxt
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from fibot.utils.exchange import Exchange
from fibot.utils.telegram import send_message, send_photo
from fibot.strategy.fibonacci_logic import generate_signal, signal_summary, FibSignal
from fibot.strategy.confluence_logic import is_confluence
from fibot.strategy.risk_policy import effective_risk_per_contract, validate_stop_distance
from fibot.utils.execution_guard import (
    consumed, consume, entry_client_oid, filled_quantity, symbol_cycle_lock, CycleBusy,
)

TRACKER_DIR = os.path.join(PROJECT_ROOT, 'artifacts', 'tracker')
MIN_NOTIONAL_USDT = 5.0


def _impulse_path(symbol, timeframe):
    return get_tracker_path(symbol, timeframe).replace('.json', '_impulses.json')


def _impulse_key(record):
    if record.get('direction') not in ('long', 'short') or not record.get('b_ts'):
        raise ValueError('Filled confluence impulse identity unavailable')
    return record['direction'] + '|' + pd.Timestamp(record['b_ts']).isoformat()


def _consume_impulse(symbol, timeframe, record, logger):
    if not record.get('b_ts') and record.get('strategy') != 'confluence':
        # A legacy position may survive a strategy migration; it has no channel impulse.
        return True
    try:
        consume(_impulse_path(symbol, timeframe), _impulse_key(record))
        return True
    except (OSError, ValueError, TypeError) as error:
        logger.error(f'Cannot persist filled impulse ({type(error).__name__}); no replacement entry.')
        return False

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
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as error:
            logging.getLogger(__name__).error(f"Tracker-Lesefehler: {error}")
            raise RuntimeError(f"Tracker unlesbar: {path}") from error
    return {}


def write_tracker(path: str, data: dict):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = f"{path}.{os.getpid()}.{time.time_ns()}.tmp"
    try:
        with open(temporary, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        if os.name != 'nt' and hasattr(os, 'O_DIRECTORY'):
            directory_fd = os.open(directory, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except Exception as e:
        logging.getLogger(__name__).error(f"Tracker-Schreibfehler: {e}")
        try:
            if os.path.exists(temporary):
                os.unlink(temporary)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Same-Candle-Guard
# ---------------------------------------------------------------------------
# Der Backtester wertet jede abgeschlossene Kerze genau einmal aus und ueberspringt
# Kerzen, die bei offener Position schliessen. Live laeuft der Cron dagegen alle
# 15 min: ohne diese Bremse wurde nach einem Exit dieselbe (laengst verbrauchte)
# Signalkerze bis zu 24x pro 6h-Kerze erneut gehandelt -- mit veraltetem Entry/SL,
# Sofort-Schliessung per Overshoot-Check und doppelten Gebuehren (Sept. 2026:
# 105 von 133 Live-Trades waren solche Re-Entries). Eigene Datei, damit
# Housekeeper/Overshoot-Check (die den Tracker leeren) den Guard nicht loeschen.

def _candle_guard_path(symbol: str, timeframe: str) -> str:
    os.makedirs(TRACKER_DIR, exist_ok=True)
    safe = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    return os.path.join(TRACKER_DIR, f"fibot_{safe}_candle_guard.json")


def read_consumed_candle(symbol: str, timeframe: str) -> Optional[pd.Timestamp]:
    data = read_tracker(_candle_guard_path(symbol, timeframe))
    ts = data.get('consumed_candle_ts')
    if not ts:
        return None
    try:
        return pd.Timestamp(ts).tz_convert('UTC') if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts, tz='UTC')
    except Exception:
        return None


def mark_candle_consumed(symbol: str, timeframe: str, candle_ts: pd.Timestamp):
    """Markiert candle_ts (Open-Zeit der Kerze) als verbraucht. Nur vorwaerts."""
    candle_ts = pd.Timestamp(candle_ts)
    candle_ts = candle_ts.tz_convert('UTC') if candle_ts.tzinfo else candle_ts.tz_localize('UTC')
    current = read_consumed_candle(symbol, timeframe)
    if current is not None and current >= candle_ts:
        return
    write_tracker(_candle_guard_path(symbol, timeframe), {'consumed_candle_ts': candle_ts.isoformat()})


def last_closed_candle_ts(tf_seconds: int, now: Optional[pd.Timestamp] = None) -> pd.Timestamp:
    """Open-Zeit der zuletzt abgeschlossenen Kerze (UTC-Raster wie Bitget)."""
    now = now if now is not None else pd.Timestamp.now(tz='UTC')
    return now.floor(f'{tf_seconds}s') - pd.Timedelta(seconds=tf_seconds)


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
        exchange.cancel_all_orders_for_symbol(symbol, strict=True)
        time.sleep(1)

        # Sicherheitsnetz: verwaiste Position schließen
        positions = exchange.fetch_open_positions(symbol, strict=True)
        if positions:
            pos        = positions[0]
            close_side = 'sell' if pos['side'] == 'long' else 'buy'
            contracts  = float(pos.get('contracts', 0))
            logger.warning(f"Housekeeper: Verwaiste Position ({pos['side']} {contracts}) — schließe...")
            exchange.place_market_order(symbol, close_side, contracts, reduce=True)
            time.sleep(3)
            if exchange.fetch_open_positions(symbol, strict=True):
                logger.error("Housekeeper: Position konnte nicht geschlossen werden!")
                return False

        # Tracker leeren falls ein abgeschlossener Trade drin steht
        tracker_data = read_tracker(tracker_path)
        if tracker_data.get('status') in ('open', 'pending_entry', 'placing_entry', 'placement_unknown'):
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
                        min_contracts: float = 0.0, free_balance: float = None) -> float:
    """
    Risikobased Sizing:
      risk_amount = balance * risk_pct/100
      contracts   = risk_amount / |entry - sl|
    Ein Exchange-Minimum darf das konfigurierte Risiko niemals anheben.
    Capped by leverage, margin check, minimum notional.
    """
    free = balance if free_balance is None else free_balance
    if not all(math.isfinite(float(x)) and float(x) > 0
               for x in (balance, free, risk_pct, entry, leverage)):
        logger.error("Ungültige Kapital-, Risiko- oder Entry-Daten. Kein Trade.")
        return 0.0
    risk_amount = balance * risk_pct / 100
    price_risk  = abs(entry - sl)
    if not math.isfinite(price_risk) or price_risk <= 0:
        logger.error("SL = Entry, Size-Berechnung unmöglich.")
        return 0.0
    contracts = risk_amount / price_risk

    if min_contracts > 0 and contracts < min_contracts:
        logger.warning(f"Contracts {contracts:.6f} < Exchange-Minimum {min_contracts}: "
                       "Minimum würde das Risikobudget überschreiten. Kein Trade.")
        return 0.0

    # Cap: max notional = balance * leverage
    max_notional = balance * leverage
    max_contracts = max_notional / entry
    contracts = min(contracts, max_contracts)

    notional = contracts * entry
    if notional < MIN_NOTIONAL_USDT:
        logger.warning(f"Notional {notional:.2f} USDT < Minimum {MIN_NOTIONAL_USDT} USDT. Kein Trade.")
        return 0.0

    # Margin-Check: isolierte Margin darf das freie Guthaben nicht übersteigen
    margin = notional / leverage
    if margin > free:
        logger.warning(f"Margin {margin:.2f} USDT > freies Guthaben {free:.2f} USDT. Kein Trade.")
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
        # NaN für Werte außerhalb des Y-Bereichs → Linie bricht ab statt aus dem Chart zu schießen
        upper_ys = [y if y_lo <= y <= y_hi else float('nan') for y in upper_ys]
        lower_ys = [y if y_lo <= y <= y_hi else float('nan') for y in lower_ys]
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
    try:
        with symbol_cycle_lock(TRACKER_DIR, params['market']['symbol']):
            return _full_trade_cycle_locked(exchange, params, telegram_config, logger)
    except CycleBusy:
        logger.warning('Another cycle already manages this symbol; overlapping cron skipped.')


def _full_trade_cycle_locked(exchange: Exchange, params: dict, telegram_config: dict, logger):
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
    # strict: bei API-Fehler NICHT "keine Position" annehmen -- sonst wuerde der Lauf eine
    # bestehende Position fuer geschlossen halten, Orders stornieren und neu einsteigen
    # (mbot-Liquidation 2026-08 durch genau dieses Muster).
    try:
        positions = exchange.fetch_open_positions(symbol, strict=True)
    except Exception as e:
        logger.error(f"Positionsabfrage fehlgeschlagen ({e}) -- Lauf wird ohne Aktion beendet.")
        return
    tf_seconds = exchange.exchange.parse_timeframe(timeframe)
    if positions:
        # Kerzen, die bei offener Position schliessen, wertet der Backtester nicht aus
        try:
            mark_candle_consumed(symbol, timeframe, last_closed_candle_ts(tf_seconds))
        except Exception as error:
            # Der Entry-Guard darf neue Entries sperren, aber nie die Verwaltung
            # einer bereits offenen Position (SL/TP/Overshoot) abschalten.
            logger.error(f"Candle-Guard unlesbar ({error}); Positionsmanagement laeuft weiter.")
        pos = positions[0]
        pos_side = pos.get('side', 'long')
        size_key = 'contracts' if 'contracts' in pos else 'contractSize'
        contracts_pos = float(pos.get(size_key, 0))
        entry_price = float(pos.get('entryPrice', 0))
        pnl = float(pos.get('unrealizedPnl', 0))
        logger.info(f"Offene Position: {pos_side.upper()} {contracts_pos} @ {entry_price:.4f} | PnL {pnl:.2f} USDT")

        # --- Self-Repair: SL/TP prüfen und ggf. neu platzieren (wie vbot) ---
        sl_price_val = None
        tp_price_val = None
        try:
            tracker_data   = read_tracker(tracker_path)
            if is_confluence(params) and tracker_data.get('b_ts'):
                _consume_impulse(symbol, timeframe, tracker_data, logger)
            trigger_orders = exchange.fetch_open_trigger_orders(symbol, strict=True)
            if is_confluence(params):
                # An die Entry gehaengte SL/TP liegen als Position-TP/SL (profit_loss) vor
                trigger_orders = list(trigger_orders) + list(exchange.fetch_position_tpsl_orders(symbol, strict=True))
                if tracker_data.get('status') in (
                        'pending_entry', 'placing_entry', 'placement_unknown',
                        'fill_reconcile', 'position_reconcile'):
                    tracker_data['status'] = 'open'
                    tracker_data.pop('reconcile_after', None)
                    write_tracker(tracker_path, tracker_data)
                    send_message(bot_token, chat_id,
                                 f"FiBot ENTRY gefuellt ({symbol} {timeframe}) @ {entry_price:.6g} | "
                                 f"SL {tracker_data.get('sl_price')} | TP {tracker_data.get('tp1_price')}")
            open_order_ids = {str(o.get('id', '')) for o in trigger_orders}
            close_side     = 'sell' if pos_side == 'long' else 'buy'

            saved_sl_id  = str(tracker_data.get('sl_order_id', ''))
            saved_tp_id  = str(tracker_data.get('tp_order_id', ''))
            sl_price_val = tracker_data.get('sl_price')
            tp_price_val = tracker_data.get('tp1_price')

            # IDs sind bevorzugt, aber ein erfolgreicher Broker-Aufruf kann einer
            # fehlgeschlagenen Tracker-Aktualisierung vorausgehen. Deshalb immer
            # zusätzlich die tatsächlich offenen Triggerpreise berücksichtigen.
            sl_exists = bool(saved_sl_id and saved_sl_id in open_order_ids)
            tp_exists = bool(saved_tp_id and saved_tp_id in open_order_ids)
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
                        sl_exists = sl_exists or trig < entry_price
                        tp_exists = tp_exists or trig > entry_price
                    else:
                        sl_exists = sl_exists or trig > entry_price
                        tp_exists = tp_exists or trig < entry_price
            logger.info(f"Schutzorder-Check — SL={sl_exists} TP={tp_exists} | {len(trigger_orders)} Orders")

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
                    exchange.place_market_order(symbol, close_side, contracts_pos, reduce=True)
                    time.sleep(2)
                    remaining = exchange.fetch_open_positions(symbol, strict=True)
                    if not remaining:
                        exchange.cancel_all_orders_for_symbol(symbol, strict=True)
                        write_tracker(tracker_path, {})
                        logger.info(f"Position {symbol} geschlossen — Tracker geleert.")
                        send_message(
                            bot_token, chat_id,
                            f"FiBot NOTSCHLIESSUNG ({symbol}): Preis {current_price:.6f} hat "
                            f"{reason} ({level:.6f}) überschritten. Position geschlossen."
                        )
                    else:
                        logger.error(f"Notschliessung {symbol}: Position noch offen nach Market-Order — Tracker bleibt!")
            except Exception as e:
                logger.error(f"Fehler beim Preis-Overshoot-Check: {e}")

        return  # Position läuft — nichts weiter tun

    # --- No open position → Aufräumen + neues Signal suchen ---
    if is_confluence(params):
        confluence_cycle(exchange, params, telegram_config, logger)
        return
    if not housekeeper_routine(exchange, symbol, tracker_path, logger):
        logger.error("Housekeeper nicht sicher abgeschlossen; kein neuer Entry.")
        return
    logger.info("Keine offene Position. Suche Fib-Signal...")

    df = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=candle_limit)
    if df.empty or len(df) < 150:
        logger.warning(f"Zu wenig Daten: {len(df)} Kerzen.")
        return

    # Die Exchange liefert die aktuell noch laufende Kerze immer als letzte Zeile mit.
    # Pivot-Bestätigung und Swing-Werte würden dadurch live einen Tick zu früh greifen
    # und Entry auf einen ungeschlossenen Wick statt auf einen bestätigten Kurs setzen —
    # der Backtester sieht dagegen ausschließlich abgeschlossene Kerzen. Deshalb hier
    # dieselbe Kerze verwerfen, solange sie noch nicht fertig ist.
    candle_close_time = df.index[-1] + pd.Timedelta(seconds=tf_seconds)
    if candle_close_time > pd.Timestamp.now(tz='UTC'):
        df = df.iloc[:-1]
        if df.empty or len(df) < 150:
            logger.warning("Zu wenig abgeschlossene Kerzen nach Entfernen der offenen Kerze.")
            return

    signal_candle_ts = df.index[-1]
    consumed_ts = read_consumed_candle(symbol, timeframe)
    if consumed_ts is not None and signal_candle_ts <= consumed_ts:
        logger.info(f"Signalkerze {signal_candle_ts} bereits verbraucht (Guard: {consumed_ts}) — warte auf neue Kerze.")
        return

    signal: FibSignal = generate_signal(df, params)

    if signal.direction == "none":
        logger.info("Kein Signal.")
        return

    # Ab hier ist die Kerze verbraucht -- egal ob Entry klappt, kein erneuter Versuch
    # mit veraltetem Preis in den folgenden Cron-Ticks.
    mark_candle_consumed(symbol, timeframe, signal_candle_ts)

    if signal.score < min_score:
        logger.info(f"Score {signal.score:.1f} < Minimum {min_score}. Signal ignoriert.")
        return

    # --- Get balance ---
    balance = exchange.fetch_balance_usdt()
    equity = exchange.fetch_equity_usdt()
    if balance <= 0 or equity <= 0:
        logger.error("Kontostand 0 oder nicht abrufbar.")
        return

    # --- Calc size ---
    min_amount = exchange.markets.get(symbol, {}).get('limits', {}).get('amount', {}).get('min', 0.0)
    contracts = calc_position_size(
        equity, risk_pct, signal.entry_price, signal.sl_price, leverage, logger,
        min_contracts=min_amount, free_balance=balance)
    if contracts <= 0:
        return

    sized_contracts = contracts
    contracts_str = exchange.amount_to_precision(symbol, contracts)
    contracts = float(contracts_str)
    if (not math.isfinite(contracts) or contracts <= 0
            or contracts > sized_contracts * (1 + 1e-10)):
        logger.warning("Precision-Rundung erhöht Menge/Risiko oder ist ungültig. Kein Trade.")
        return

    # Notional-Check nach Precision-Rundung (Rundung kann unter 5 USDT fallen)
    notional_after_round = contracts * signal.entry_price
    if notional_after_round < MIN_NOTIONAL_USDT:
        logger.warning(f"Notional {notional_after_round:.2f} USDT < Minimum {MIN_NOTIONAL_USDT} USDT nach Precision-Rundung. Kein Trade.")
        return

    # Precision darf nicht durch Anheben auf das Exchange-Minimum das Risiko erhöhen.
    if min_amount > 0 and contracts < min_amount:
        logger.warning(f"Nach Precision-Rundung {contracts:.6f} < Minimum {min_amount}. Kein Trade.")
        return

    # --- Place entry (Limit at signal price, consistent with backtester) ---
    entry_side = 'buy' if signal.direction == 'long' else 'sell'

    logger.info(f"Platziere Entry: {entry_side.upper()} {contracts} @ {signal.entry_price:.4f}")
    try:
        entry_order = exchange.place_limit_order(
            symbol, entry_side, contracts, signal.entry_price)
    except ccxt.InsufficientFunds:
        logger.warning("Nicht genug freie Margin für Entry (andere Position belegt Kapital). Kein Trade.")
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
# Fibo-Kanal-Konfluenz: wartende Limit-Order am Konfluenzpunkt
# ---------------------------------------------------------------------------

def _confluence_size(exchange: Exchange, symbol: str, plan: dict, risk_pct: float,
                     leverage: int, logger) -> float:
    """Risiko auf das Gesamtkapital (wie im Backtest), Margin auf das freie Guthaben gekappt."""
    equity = exchange.fetch_equity_usdt()
    free = exchange.fetch_balance_usdt()
    try:
        risk = effective_risk_per_contract(plan['limit'], plan['sl'])
    except ValueError as error:
        logger.error(f'Ungueltiges Konfluenz-Risiko ({error}). Keine Order.')
        return 0.0
    if not all(math.isfinite(x) and x > 0 for x in (equity, free, risk, risk_pct, leverage, plan['limit'])):
        return 0.0
    contracts = equity * risk_pct / 100 / risk
    max_by_margin = free * leverage * 0.95 / plan['limit']
    if contracts > max_by_margin:
        logger.warning(f"Margin-Kappung: {contracts:.6f} -> {max_by_margin:.6f} Contracts (frei {free:.2f} USDT)")
        contracts = max_by_margin
    min_amount = exchange.markets.get(symbol, {}).get('limits', {}).get('amount', {}).get('min', 0.0) or 0.0
    # An exchange minimum cannot override the intended loss or available margin.
    if contracts < min_amount:
        logger.warning('Exchange minimum exceeds risk or margin budget. No order.')
        return 0.0
    maximum = contracts
    contracts = float(exchange.amount_to_precision(symbol, contracts))
    if not math.isfinite(contracts) or contracts <= 0 or contracts > maximum + 1e-12 or contracts < min_amount:
        logger.warning('Rounded quantity violates risk, margin or exchange minimum. No order.')
        return 0.0
    if contracts * plan['limit'] < MIN_NOTIONAL_USDT:
        logger.warning(f"Notional {contracts * plan['limit']:.2f} USDT < {MIN_NOTIONAL_USDT} USDT. Keine Order.")
        return 0.0
    logger.info(f"Size: {contracts} Contracts | Kapital {equity:.2f} | Risiko {equity * risk_pct / 100:.2f} USDT")
    return contracts


def _round_confluence_plan(exchange: Exchange, symbol: str, plan: dict) -> dict:
    """Round the complete bracket to venue precision and recompute its real R:R."""
    rounded = dict(plan)
    for key in ('limit', 'sl', 'tp'):
        rounded[key] = float(exchange.price_to_precision(symbol, rounded[key]))
    values = (rounded['limit'], rounded['sl'], rounded['tp'])
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError('Gerundete Planpreise sind ungueltig')
    if rounded.get('direction') == 'long':
        valid_geometry = rounded['sl'] < rounded['limit'] < rounded['tp']
    elif rounded.get('direction') == 'short':
        valid_geometry = rounded['tp'] < rounded['limit'] < rounded['sl']
    else:
        valid_geometry = False
    if not valid_geometry:
        raise ValueError('Gerundete Entry/SL/TP-Geometrie ist ungueltig')
    risk = validate_stop_distance(rounded['limit'], rounded['sl'])
    reward = abs(rounded['tp'] - rounded['limit'])
    rounded['rr'] = reward / risk
    if not math.isfinite(rounded['rr']):
        raise ValueError('Gerundetes R:R ist ungueltig')
    return rounded


PENDING_RISK_HYSTERESIS = 0.05


def _pending_entry_within_risk(exchange: Exchange, plan: dict, contracts: float,
                               risk_pct: float, logger):
    """Recheck only stop-loss risk; an open order has already reserved its margin.

    ``None`` means account risk cannot be verified. In that case the known broker
    order is retained rather than mutated on incomplete information.
    """
    try:
        equity = float(exchange.fetch_equity_usdt())
        contracts = float(contracts)
        risk_pct = float(risk_pct)
        risk_per_contract = effective_risk_per_contract(plan['limit'], plan['sl'])
        values = (equity, contracts, risk_pct, risk_per_contract)
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError('ungueltige Risikowerte')
    except (KeyError, TypeError, ValueError, ArithmeticError, OSError) as error:
        logger.error(f'Risiko der wartenden Order nicht sicher pruefbar ({error}); '
                     'bestehende Order bleibt liegen.')
        return None
    planned_loss = contracts * risk_per_contract
    allowed_loss = equity * risk_pct / 100
    if planned_loss > allowed_loss * (1 + PENDING_RISK_HYSTERESIS):
        logger.warning(f"Wartende Order ueber aktuellem Risikobudget: "
                       f"{planned_loss:.4f} > {allowed_loss:.4f} USDT; sie wird neu dimensioniert.")
        return False
    return True


def _order_updates_enabled() -> bool:
    """settings.json live_trading_settings.telegram_order_updates (Standard: an):
    Telegram auch beim Nachziehen und beim Storno ungueltiger Setups."""
    try:
        with open(os.path.join(PROJECT_ROOT, 'settings.json')) as f:
            return bool(json.load(f).get('live_trading_settings', {}).get('telegram_order_updates', True))
    except Exception:
        return True


def _trend_filter_reject(exchange: Exchange, symbol: str, timeframe: str, df: pd.DataFrame,
                         plan: dict, current_candle: str, logger) -> str | None:
    """Trendfilter (dieselben Funktionen wie im Backtest). Rueckgabe: Grund der Ablehnung oder None.
    Fehlen Daten, wird abgelehnt (lieber keine Order als eine ungefilterte)."""
    from fibot.strategy import trend_filter
    cfg = trend_filter.settings()
    if not cfg['enabled']:
        return None
    now = pd.Timestamp.now(tz='UTC')
    try:
        base = df
        need = trend_filter.base_bars_needed(cfg)
        if len(base) < need:
            base = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=need + 5)
            if not base.empty and base.index[-1] + pd.Timedelta(timeframe) > now:
                base = base.iloc[:-1]
        daily = exchange.fetch_recent_ohlcv(symbol, '1d', limit=trend_filter.DAILY_BARS_NEEDED)
        if not daily.empty and daily.index[-1] + pd.Timedelta(days=1) > now:
            daily = daily.iloc[:-1]
        if len(base) < need or len(daily) < int(cfg['daily_sma']) + 1:
            return f"zu wenig Kerzen ({len(base)} {timeframe}, {len(daily)} Tage)"
        htf = trend_filter.htf_trend(base, timeframe, cfg)
        day = trend_filter.daily_trend(daily, cfg)
    except Exception as e:
        logger.warning(f"Trendfilter: Daten nicht ladbar: {e}")
        return "Trenddaten nicht ladbar"
    ts = pd.Timestamp(current_candle)
    if trend_filter.allowed(plan['direction'], ts, htf, day):
        return None
    h = trend_filter._value_at(htf, ts); d = trend_filter._value_at(day, ts)
    lab = lambda v: 'auf' if v == 1.0 else ('ab' if v == 0.0 else '?')
    return f"{int(cfg['htf_mult'])}x{timeframe} {lab(h)}, Tag {lab(d)}"


RECONCILE_DELAY_SECONDS = 60


def _utc_now() -> pd.Timestamp:
    return pd.Timestamp.now(tz='UTC')


def _start_reconcile(tracker: dict, status: str) -> dict:
    updated = dict(tracker)
    updated['status'] = status
    updated['reconcile_after'] = (_utc_now() + pd.Timedelta(seconds=RECONCILE_DELAY_SECONDS)).isoformat()
    updated['no_position_confirmations'] = 0
    return updated


def _reconcile_due(tracker: dict) -> bool:
    try:
        deadline = pd.Timestamp(tracker['reconcile_after'])
        deadline = deadline.tz_convert('UTC') if deadline.tzinfo else deadline.tz_localize('UTC')
        return _utc_now() >= deadline
    except (KeyError, TypeError, ValueError):
        return False


def _intent_expired(tracker: dict, hours: int = 2) -> bool:
    try:
        created = pd.Timestamp(tracker['intent_created_at'])
        created = created.tz_convert('UTC') if created.tzinfo else created.tz_localize('UTC')
        return _utc_now() >= created + pd.Timedelta(hours=hours)
    except (KeyError, TypeError, ValueError):
        return False


def _tracked_order(exchange: Exchange, tracker: dict, symbol: str):
    order_id = str(tracker.get('order_id') or '')
    if order_id:
        return exchange.fetch_order(order_id, symbol)
    client_oid = str(tracker.get('client_oid') or '')
    if client_oid:
        return exchange.fetch_order_by_client_oid(client_oid, symbol)
    raise ValueError('Tracked entry has neither order_id nor client_oid')


def _entry_intent(symbol: str, timeframe: str, current_candle: str, plan: dict,
                  contracts: float, notified_b_ts) -> dict:
    oid = entry_client_oid(
        'confluence', symbol, timeframe, plan['direction'], plan['b_ts'], current_candle,
        plan['limit'], plan['sl'], plan['tp'], contracts,
    )
    return {
        'status': 'placing_entry', 'strategy': 'confluence', 'order_id': '', 'client_oid': oid,
        'candle_ts': current_candle, 'direction': plan['direction'], 'entry_price': plan['limit'],
        'sl_price': plan['sl'], 'tp1_price': plan['tp'], 'contracts': contracts,
        'a_ts': plan['a_ts'], 'b_ts': plan['b_ts'], 'notified_b_ts': notified_b_ts,
        'intent_created_at': _utc_now().isoformat(), 'timestamp': _utc_now().isoformat(),
    }


def confluence_cycle(exchange: Exchange, params: dict, telegram_config: dict, logger):
    """Ohne offene Position: Limit-Order fuer die laufende Kerze planen, nachziehen oder entfernen.
    Der Plan kommt aus plan_next_order() -- derselben Rechnung wie im Backtest."""
    from fibot.strategy.confluence_logic import plan_next_order

    symbol    = params['market']['symbol']
    timeframe = params['market']['timeframe']
    leverage  = int(params['risk'].get('leverage', 5))
    risk_pct  = float(params['risk'].get('risk_per_entry_pct', 1.0))
    bot_token = telegram_config.get('bot_token', '')
    chat_id   = telegram_config.get('chat_id', '')
    tracker_path = get_tracker_path(symbol, timeframe)
    tracker = read_tracker(tracker_path)
    tf_seconds = exchange.exchange.parse_timeframe(timeframe)
    # Impuls, zu dem schon eine Telegram-Nachricht ging (bleibt beim Nachziehen erhalten)
    legacy_keep_only = bool(
        tracker.get('notified_b_ts') and not tracker.get('status')
        and tracker.get('execution_guard_version') != 1
    )
    keep = {'notified_b_ts': tracker.get('notified_b_ts'), 'execution_guard_version': 1}
    if legacy_keep_only:
        # Der alte Tracker speicherte keine Richtung. Sperre deshalb beide
        # Richtungen fuer dieses historische B dauerhaft, auch wenn gerade
        # kein Plan existiert. So kann es spaeter nicht erneut auftauchen.
        for direction in ('long', 'short'):
            if not _consume_impulse(
                    symbol, timeframe,
                    {'direction': direction, 'b_ts': tracker['notified_b_ts']}, logger):
                return
        write_tracker(tracker_path, keep)
        logger.warning('Vor-Upgrade-Impuls konservativ in beiden Richtungen als verbraucht markiert.')

    # Eine einzelne leere Positionsantwort darf nie frisch aktivierte Schutzorders entfernen.
    if tracker.get('status') == 'open':
        if not _consume_impulse(symbol, timeframe, tracker, logger):
            return
        tracker = _start_reconcile(tracker, 'position_reconcile')
        write_tracker(tracker_path, tracker)
        logger.warning('Position einmal nicht sichtbar; bestaetige das in spaeteren Laeufen.')
        return

    if tracker.get('status') in ('position_reconcile', 'fill_reconcile'):
        if not _reconcile_due(tracker):
            logger.info('Position/Fill wird zeitversetzt abgeglichen; keine neue Order.')
            return
        try:
            if exchange.fetch_open_positions(symbol, strict=True):
                tracker['status'] = 'open'
                tracker.pop('reconcile_after', None)
                tracker.pop('no_position_confirmations', None)
                write_tracker(tracker_path, tracker)
                return
        except Exception as error:
            logger.error(f'Positionsabgleich unklar ({error}); Schutz bleibt unveraendert.')
            return

        if tracker.get('status') == 'fill_reconcile':
            try:
                reconciled_order = _tracked_order(exchange, tracker, symbol)
                reconciled_status = (reconciled_order or {}).get('status')
                reconciled_filled = filled_quantity(reconciled_order)
            except Exception as error:
                logger.error(f'Fill-Abgleich unklar ({error}); Schutz bleibt unveraendert.')
                return
            if reconciled_status == 'open':
                if reconciled_filled > 0:
                    try:
                        exchange.cancel_order(tracker.get('order_id'), symbol)
                    except Exception as error:
                        logger.warning(f'Restmengen-Storno unklar ({error}); keine neue Order.')
                tracker['reconcile_after'] = (
                    _utc_now() + pd.Timedelta(seconds=RECONCILE_DELAY_SECONDS)).isoformat()
                write_tracker(tracker_path, tracker)
                return
            if reconciled_status not in ('closed', 'canceled', 'cancelled', 'expired', 'rejected') \
                    or reconciled_filled <= 0:
                logger.error('Fill-Order ist nicht sicher abgeschlossen; keine neue Order.')
                return

        confirmations = int(tracker.get('no_position_confirmations') or 0) + 1
        if confirmations < 2:
            tracker['no_position_confirmations'] = confirmations
            tracker['reconcile_after'] = (
                _utc_now() + pd.Timedelta(seconds=RECONCILE_DELAY_SECONDS)).isoformat()
            write_tracker(tracker_path, tracker)
            logger.info('Erste spaetere Nullpositions-Bestaetigung; ein weiterer Lauf folgt.')
            return

        if tracker.get('status') == 'position_reconcile':
            exchange.cancel_all_orders_for_symbol(symbol, strict=True)
        write_tracker(tracker_path, keep)
        send_message(bot_token, chat_id, f"FiBot ({symbol} {timeframe}): Position geschlossen.")
        tracker = {}

    # Write-ahead-Intent nach Absturz/Timeout nur ueber clientOid uebernehmen, nie blind neu senden.
    if tracker.get('status') in ('placing_entry', 'placement_unknown'):
        client_oid = str(tracker.get('client_oid') or '')
        if not client_oid:
            logger.error('Unklarer Entry ohne clientOid; keine neue Order.')
            return
        try:
            order = exchange.fetch_order_by_client_oid(client_oid, symbol)
            if order is None:
                for candidate in exchange.fetch_open_orders(symbol, strict=True):
                    candidate_oid = str(candidate.get('clientOrderId') or candidate.get('clientOid') or '')
                    if candidate_oid == client_oid:
                        order = candidate
                        break
        except Exception as error:
            logger.error(f'Entry-Intent nicht abgleichbar ({error}); keine neue Order.')
            return
        if order is None:
            tracker['not_found_checks'] = int(tracker.get('not_found_checks') or 0) + 1
            write_tracker(tracker_path, tracker)
            if tracker['not_found_checks'] >= 2 and _intent_expired(tracker):
                if not _consume_impulse(symbol, timeframe, tracker, logger):
                    return
                write_tracker(tracker_path, keep)
                logger.error('Unklarer Entry nach zwei Stunden nicht auffindbar; Impuls sicherheitshalber verworfen.')
                send_message(bot_token, chat_id,
                             f"FiBot ALARM ({symbol}): unklarer Entry nicht auffindbar; Impuls verworfen.")
            return

        status = order.get('status')
        tracker['order_id'] = str(order.get('id') or tracker.get('order_id') or '')
        try:
            quantity_filled = filled_quantity(order)
        except (TypeError, ValueError):
            logger.error('Entry-Intent gefunden, Fillmenge aber unbekannt; keine neue Order.')
            return
        if status == 'closed' or quantity_filled > 0:
            if not _consume_impulse(symbol, timeframe, tracker, logger):
                return
            try:
                if exchange.fetch_open_positions(symbol, strict=True):
                    tracker['status'] = 'open'
                else:
                    tracker = _start_reconcile(tracker, 'fill_reconcile')
                write_tracker(tracker_path, tracker)
            except Exception as error:
                logger.error(f'Position nach Entry unklar ({error}); Intent bleibt erhalten.')
            return
        if status == 'open':
            tracker['status'] = 'pending_entry'
            write_tracker(tracker_path, tracker)
        elif status in ('canceled', 'cancelled', 'expired', 'rejected'):
            write_tracker(tracker_path, keep)
            tracker = {}
        else:
            logger.error(f'Entry-Intent hat unbekannten Status {status!r}; keine neue Order.')
            return

    # 2) Abgeschlossene Kerzen laden (laufende Kerze verwerfen)
    df = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=int(params['strategy'].get('candle_limit', 600)))
    if df.empty:
        logger.warning("Keine Kerzen geladen.")
        return
    if df.index[-1] + pd.Timedelta(seconds=tf_seconds) > pd.Timestamp.now(tz='UTC'):
        df = df.iloc[:-1]
    if len(df) < 200:
        logger.warning(f"Zu wenig abgeschlossene Kerzen: {len(df)}")
        return
    current_candle = (df.index[-1] + pd.Timedelta(seconds=tf_seconds)).isoformat()
    plan = plan_next_order(df, params)
    filtered_reason = None
    if plan is not None:
        filtered_reason = _trend_filter_reject(exchange, symbol, timeframe, df, plan, current_candle, logger)
        if filtered_reason:
            logger.info(f"Trendfilter: {plan['direction'].upper()} @ {plan['limit']:.6g} nicht erlaubt ({filtered_reason}).")
            plan = None
        else:
            try:
                plan = _round_confluence_plan(exchange, symbol, plan)
            except Exception as error:
                logger.error(f'Planpreise nicht sicher rundbar ({error}); keine Order.')
                return

    # 3) Bestehende wartende Order pruefen
    cancelled_prev = None   # stornierte wartende Order (fuer Telegram: nachgezogen / ungueltig)
    if tracker.get('status') == 'pending_entry':
        order = None
        try:
            order = exchange.fetch_order(tracker.get('order_id'), symbol)
        except Exception as e:
            logger.warning(f"Pending-Order nicht abrufbar: {e}")
            return
        status = (order or {}).get('status')
        cancelled_with_fill = False
        if status in ('canceled', 'cancelled', 'expired', 'rejected'):
            try:
                cancelled_with_fill = filled_quantity(order) > 0
            except (TypeError, ValueError):
                return
        if status == 'closed' or cancelled_with_fill:
            if not _consume_impulse(symbol, timeframe, tracker, logger):
                return
            try:
                if exchange.fetch_open_positions(symbol, strict=True):
                    tracker['status'] = 'open'
                else:
                    tracker = _start_reconcile(tracker, 'fill_reconcile')
                write_tracker(tracker_path, tracker)
                return
            except Exception:
                logger.error('Position after fill is unknown; protective orders retained.')
                return
        elif status == 'open':
            try:
                if filled_quantity(order) > 0:
                    if not _consume_impulse(symbol, timeframe, tracker, logger):
                        return
                    try:
                        exchange.cancel_order(tracker.get('order_id'), symbol)
                    except Exception as error:
                        logger.warning(f'Restmengen-Storno unklar ({error}); Fill wird weiter abgeglichen.')
                    tracker = _start_reconcile(tracker, 'fill_reconcile')
                    write_tracker(tracker_path, tracker)
                    return
            except (TypeError, ValueError):
                logger.error('Pending fill quantity unknown; no replacement.')
                return
            same = (plan is not None and tracker.get('candle_ts') == current_candle
                    and tracker.get('direction') == plan['direction']
                    and abs(float(tracker.get('entry_price', 0)) - plan['limit']) <= 1e-9 * max(1.0, plan['limit'])
                    and abs(float(tracker.get('sl_price', 0)) - plan['sl']) <= 1e-9 * max(1.0, plan['sl'])
                    and abs(float(tracker.get('tp1_price', 0)) - plan['tp']) <= 1e-9 * max(1.0, plan['tp']))
            if same:
                risk_state = _pending_entry_within_risk(
                    exchange, plan, tracker.get('contracts'), risk_pct, logger)
                if risk_state is None:
                    return
                same = risk_state
            if same:
                logger.info(f"Limit-Order fuer {current_candle} liegt bereits @ {plan['limit']:.6f}.")
                return
            logger.info("Neue Kerze bzw. neuer Plan: wartende Order wird storniert.")
            try:
                cancellation = exchange.cancel_order(tracker.get('order_id'), symbol)
            except Exception as e:
                logger.warning(f"Storno fehlgeschlagen: {e}")
                return
            try:
                after = exchange.fetch_order(tracker.get('order_id'), symbol)
                cancellation_filled = 0.0
                if isinstance(cancellation, dict) and cancellation.get('filled') is not None:
                    cancellation_filled = filled_quantity(cancellation)
                after_filled = filled_quantity(after)
                if cancellation_filled > 0 or after_filled > 0 or after.get('status') == 'closed':
                    if not _consume_impulse(symbol, timeframe, tracker, logger):
                        return
                    if exchange.fetch_open_positions(symbol, strict=True):
                        tracker['status'] = 'open'
                    else:
                        tracker = _start_reconcile(tracker, 'fill_reconcile')
                    write_tracker(tracker_path, tracker)
                    return
                if after.get('status') not in ('canceled', 'cancelled', 'expired', 'rejected'):
                    return
                if exchange.fetch_open_positions(symbol, strict=True):
                    return
            except Exception:
                logger.error('Cancellation/fill/position not confirmed; no replacement.')
                return
            cancelled_prev = dict(tracker)
            write_tracker(tracker_path, keep)
        elif status in ('canceled', 'cancelled', 'expired', 'rejected'):
            try:
                if filled_quantity(order) > 0:
                    _consume_impulse(symbol, timeframe, tracker, logger)
                    return
            except (TypeError, ValueError):
                return
            write_tracker(tracker_path, keep)
        else:
            logger.error('Pending order state unknown; tracker retained, no new entry.')
            return

    if plan is not None:
        try:
            if consumed(_impulse_path(symbol, timeframe), _impulse_key(plan)):
                logger.info('Confluence impulse already filled; no duplicate entry.')
                plan = None
        except (OSError, ValueError, TypeError):
            logger.error('Impulse history unavailable; no new entry.')
            return
    updates = _order_updates_enabled()
    if plan is None:
        if not filtered_reason:
            logger.info("Kein Konfluenz-Setup fuer die laufende Kerze.")
        if cancelled_prev and updates:
            why = f"gegen den uebergeordneten Trend ({filtered_reason})" if filtered_reason else "Setup ungueltig"
            send_message(bot_token, chat_id,
                         f"FiBot ({symbol} {timeframe}): {why} - wartende "
                         f"{str(cancelled_prev.get('direction', '')).upper()}-Order "
                         f"@ {float(cancelled_prev.get('entry_price', 0)):.6g} storniert.")
        return

    # Size against the exact rounded protection prices submitted to the venue.
    contracts = _confluence_size(exchange, symbol, plan, risk_pct, leverage, logger)
    if contracts <= 0:
        return
    side = 'buy' if plan['direction'] == 'long' else 'sell'
    intent = _entry_intent(
        symbol, timeframe, current_candle, plan, contracts,
        plan['b_ts'],
    )
    # Write-ahead: if this fails, no request is allowed to reach the broker.
    write_tracker(tracker_path, intent)
    try:
        order = exchange.place_limit_order_with_tpsl(
            symbol, side, contracts, plan['limit'], plan['sl'], plan['tp'], intent['client_oid'])
    except (ccxt.InsufficientFunds, ccxt.InvalidOrder, ccxt.BadRequest, ValueError) as error:
        write_tracker(tracker_path, keep)
        logger.warning(f"Konfluenz-Order sicher abgelehnt ({error}).")
        return
    except Exception as e:
        intent['status'] = 'placement_unknown'
        intent['placement_error'] = type(e).__name__
        write_tracker(tracker_path, intent)
        logger.error(f"Konfluenz-Order fehlgeschlagen: {e}")
        send_message(bot_token, chat_id,
                     f"FiBot ALARM ({symbol}): Entry-Antwort unklar; clientOid-Abgleich folgt, keine Ersatzorder.")
        return
    order_id = str((order or {}).get('id') or '')
    if not order_id:
        intent['status'] = 'placement_unknown'
        write_tracker(tracker_path, intent)
        logger.error('Brokerantwort ohne Order-ID; clientOid-Abgleich folgt, keine Ersatzorder.')
        return
    intent['status'] = 'pending_entry'
    intent['order_id'] = order_id
    intent['timestamp'] = _utc_now().isoformat()
    write_tracker(tracker_path, intent)
    if keep['notified_b_ts'] == plan['b_ts']:
        # gleicher Impuls, Order nur auf die neue Kanalposition nachgezogen -> keine neue Nachricht
        logger.info(f"Limit nachgezogen: {plan['direction'].upper()} @ {plan['limit']:.6g} "
                    f"(SL {plan['sl']:.6g}, TP {plan['tp']:.6g})")
        if updates and cancelled_prev:
            send_message(bot_token, chat_id,
                         f"FiBot ({symbol} {timeframe}): Limit nachgezogen "
                         f"{float(cancelled_prev.get('entry_price', 0)):.6g} -> {plan['limit']:.6g} "
                         f"({plan['direction'].upper()}) | SL {plan['sl']:.6g} | TP {plan['tp']:.6g}")
        return
    caption = (f"FiBot KONFLUENZ-ORDER ({symbol} {timeframe})\n"
               f"{plan['direction'].upper()} Limit {plan['limit']:.6g}\n"
               f"SL {plan['sl']:.6g} | TP {plan['tp']:.6g} | R:R {plan['rr']:.2f}\n"
               f"Impuls {plan['a_ts'][:16]} -> {plan['b_ts'][:16]}\n"
               f"Die Order wird jede Kerze mit der Kanallinie nachgezogen.")
    try:
        from fibot.utils.confluence_chart import confluence_chart
        path, _ = confluence_chart(df, params, symbol, timeframe, plan_override=plan)
        send_photo(bot_token, chat_id, path, caption)
        os.remove(path)
    except Exception as e:
        logger.warning(f"Chart fuer Telegram fehlgeschlagen ({e}) - sende nur Text.")
        send_message(bot_token, chat_id, caption)


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
        'timestamp':    _utc_now().isoformat(),
    })
    write_tracker(path, data)
