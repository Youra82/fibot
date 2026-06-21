#!/usr/bin/env python3
"""
show_chart.py — Simuliert einen Fibonacci-Chart und sendet ihn per Telegram.

Laedt OHLCV-Daten, berechnet Fibonacci-Signal und schickt einen PNG-Chart
mit Fibonacci-Grid, Entry-Zone und Entry/SL/TP-Levels. Kein echter Trade.

Aufruf:
    .venv/bin/python show_chart.py
    .venv/bin/python show_chart.py --symbol BTC/USDT:USDT --timeframe 4h
    .venv/bin/python show_chart.py --symbol BTC/USDT:USDT --timeframe 4h --side long
"""
import argparse
import json
import logging
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from fibot.utils.exchange import Exchange
from fibot.utils.trade_manager import _generate_fib_chart_png
from fibot.utils.telegram import send_photo, send_message
from fibot.strategy.fibonacci_logic import (
    generate_signal, precompute_indicators,
    find_significant_swings, compute_fib_levels, calc_atr,
    FibSignal, FibLevels, StructureInfo,
)

logging.basicConfig(level=logging.WARNING, format='[%(levelname)s] %(message)s')

CONFIGS_DIR = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs')
TMP_DIR     = os.path.join(PROJECT_ROOT, 'artifacts', 'tmp')


def _load_secrets():
    with open(os.path.join(PROJECT_ROOT, 'secret.json')) as f:
        return json.load(f)


def _load_settings():
    with open(os.path.join(PROJECT_ROOT, 'settings.json')) as f:
        return json.load(f)


def _load_config(symbol: str, timeframe: str) -> dict:
    safe = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    path = os.path.join(CONFIGS_DIR, f'config_{safe}_fib.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _make_dummy_signal(df, config: dict, force_side: str) -> FibSignal:
    """Baut ein FibSignal mit ATR-basiertem SL/TP wenn kein echtes Signal existiert."""
    cfg    = config.get('strategy', {})
    atr    = calc_atr(df, period=int(cfg.get('atr_period', 14)))
    entry  = float(df['close'].iloc[-1])
    mult   = float(cfg.get('atr_sl_multiplier', 1.5))
    min_rr = float(cfg.get('min_rr', 1.5))

    side   = force_side or 'long'
    sl     = entry - mult * atr if side == 'long' else entry + mult * atr
    tp     = entry + min_rr * abs(entry - sl) if side == 'long' \
             else entry - min_rr * abs(entry - sl)

    # Swing fuer Fib-Grid
    swing_lb   = int(cfg.get('swing_lookback', 100))
    pivot_left = int(cfg.get('pivot_left', 5))
    pivot_right= int(cfg.get('pivot_right', 5))
    swings = find_significant_swings(df, swing_lb, pivot_left, pivot_right)
    if swings:
        fibs_obj = compute_fib_levels(swings)
    else:
        # Fallback: einfaches Fib-Grid aus Preis ± 3×ATR
        diff = 3 * atr
        from fibot.strategy.fibonacci_logic import SwingPoints
        swings = SwingPoints(
            high_price=entry + diff, high_idx=0,
            low_price=entry - diff,  low_idx=1,
            direction='down' if side == 'long' else 'up',
        )
        fibs_obj = compute_fib_levels(swings)

    struct = StructureInfo(
        type='none', bias='neutral',
        upper_slope=0, lower_slope=0,
        upper_intercept=0, lower_intercept=0,
        n_bars=0, support_at=0, resistance_at=0,
        support_zone_low=0, support_zone_high=0,
        resistance_zone_low=0, resistance_zone_high=0,
        breakout='none', breakout_strength=0.0,
    )
    rr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0

    return FibSignal(
        direction=side,
        entry_price=entry,
        sl_price=sl,
        tp1_price=tp,
        tp2_price=tp,
        fib_levels=fibs_obj,
        structure=struct,
        entry_fib_name='[SIMULATION]',
        rr_ratio=rr,
        reason='[SIMULATION]',
        score=0.0,
    )


def generate_and_send(exchange: Exchange, symbol: str, timeframe: str,
                      force_side: str, tg: dict) -> bool:
    config = _load_config(symbol, timeframe)
    if not config:
        print(f"  WARNUNG: Keine Config für {symbol} {timeframe} gefunden — nutze Defaults.")
        config = {'strategy': {}, 'risk': {}, 'market': {'symbol': symbol, 'timeframe': timeframe}}

    candle_limit = int(config.get('strategy', {}).get('candle_limit', 300))
    print(f"  Lade OHLCV {symbol} ({timeframe})...")
    df = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=candle_limit)
    if df is None or df.empty or len(df) < 150:
        print(f"  WARNUNG: Nicht genug Daten ({len(df) if df is not None else 0} Kerzen).")
        return False

    df = df.iloc[:-1]
    df = precompute_indicators(df, config)

    signal: FibSignal = generate_signal(df, config)

    if signal.direction != 'none' and not force_side:
        print(f"  Echtes Signal: {signal.direction.upper()} | Score {signal.score:.1f} | {signal.reason[:60]}")
    else:
        side = force_side or 'long'
        signal = _make_dummy_signal(df, config, side)
        print(f"  Kein Signal — simuliere {side.upper()} mit ATR-Levels")

    print(f"  Entry: {signal.entry_price:.6g} | SL: {signal.sl_price:.6g} | TP: {signal.tp1_price:.6g}")

    os.makedirs(TMP_DIR, exist_ok=True)
    path = _generate_fib_chart_png(df, signal, symbol, timeframe)

    if not path or not os.path.exists(path):
        print("  FEHLER: PNG konnte nicht erstellt werden.")
        return False

    side_label = 'LONG' if signal.direction == 'long' else 'SHORT'
    caption = (
        f"[SIMULATION] FIBOT | {symbol} ({timeframe})\n"
        f"{side_label} @ {signal.entry_price:.6g}  |  "
        f"SL: {signal.sl_price:.6g}  |  TP: {signal.tp1_price:.6g}  |  "
        f"Score: {signal.score:.1f}/10"
    )
    send_photo(tg['bot_token'], tg['chat_id'], path, caption)
    os.remove(path)
    print("  Chart gesendet.")
    return True


def main():
    parser = argparse.ArgumentParser(description='Fibonacci-Chart simulieren und per Telegram senden')
    parser.add_argument('--symbol',    type=str, help='Symbol (z.B. BTC/USDT:USDT)')
    parser.add_argument('--timeframe', type=str, help='Timeframe (z.B. 4h)')
    parser.add_argument('--side',      type=str, default='',
                        choices=['long', 'short', ''],
                        help='Richtung erzwingen (default: echtes Fib-Signal)')
    args = parser.parse_args()

    secrets  = _load_secrets()
    settings = _load_settings()

    tg = secrets.get('telegram', {})
    if not tg.get('bot_token') or not tg.get('chat_id'):
        print("FEHLER: Kein Telegram-Token/Chat-ID in secret.json.")
        sys.exit(1)

    accounts = secrets.get('fibot', [])
    if isinstance(accounts, dict):
        accounts = [accounts]
    if not accounts:
        print("FEHLER: Kein 'fibot'-Account in secret.json.")
        sys.exit(1)

    print("Initialisiere Exchange...")
    exchange = Exchange(accounts[0])
    if not exchange.markets:
        print("FEHLER: Exchange konnte nicht initialisiert werden.")
        sys.exit(1)

    active = settings.get('live_trading_settings', {}).get('active_strategies', [])

    if args.symbol or args.timeframe:
        targets = [
            s for s in active
            if (not args.symbol    or s['symbol']    == args.symbol)
            and (not args.timeframe or s['timeframe'] == args.timeframe)
        ]
        if not targets and (args.symbol or args.timeframe):
            sym = args.symbol or active[0]['symbol'] if active else 'BTC/USDT:USDT'
            tf  = args.timeframe or '4h'
            targets = [{'symbol': sym, 'timeframe': tf, 'active': True}]
    else:
        targets = [s for s in active if s.get('active', False)]

    if not targets:
        print("Keine passenden Strategien gefunden.")
        sys.exit(1)

    print(f"\n{len(targets)} Strategie(n) — generiere Charts...\n")
    send_message(tg['bot_token'], tg['chat_id'],
                 f"FiBot Chart-Simulation ({len(targets)} Strategie(n))")

    ok = 0
    for s in targets:
        symbol    = s['symbol']
        timeframe = s['timeframe']
        print(f"[{symbol} / {timeframe}]")
        try:
            if generate_and_send(exchange, symbol, timeframe, args.side, tg):
                ok += 1
        except Exception as e:
            print(f"  FEHLER: {e}")

    print(f"\nFertig: {ok}/{len(targets)} Charts gesendet.")


if __name__ == '__main__':
    main()
