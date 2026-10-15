"""
FiBot — Sicherheitscheck / Unit-Tests
"""
import json
import os
import sys
import pytest
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

CONFIGS_DIR  = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs')
SETTINGS_FILE = os.path.join(PROJECT_ROOT, 'settings.json')


# ---------------------------------------------------------------------------
# 1. Settings.json
# ---------------------------------------------------------------------------

def test_settings_exists():
    assert os.path.exists(SETTINGS_FILE), "settings.json nicht gefunden"


def test_settings_valid_json():
    with open(SETTINGS_FILE) as f:
        data = json.load(f)
    assert isinstance(data, dict)


def test_settings_active_strategies():
    with open(SETTINGS_FILE) as f:
        data = json.load(f)
    strategies = data.get('live_trading_settings', {}).get('active_strategies', [])
    assert len(strategies) > 0, "Keine active_strategies in settings.json"
    for s in strategies:
        assert 'symbol'    in s, f"'symbol' fehlt: {s}"
        assert 'timeframe' in s, f"'timeframe' fehlt: {s}"
        assert 'active'    in s, f"'active' fehlt: {s}"
        assert '/' in s['symbol'], f"Ungültiges Symbol-Format: {s['symbol']}"


def test_settings_optimization_settings():
    with open(SETTINGS_FILE) as f:
        data = json.load(f)
    opt = data.get('optimization_settings', {})
    assert 'enabled'      in opt
    assert 'num_trials'   in opt
    assert 'start_capital' in opt
    # Zahl oder "auto" (= aktueller Kontostand von Bitget, siehe auto_optimizer_scheduler)
    assert str(opt['start_capital']).lower() == 'auto' or float(opt['start_capital']) > 0


# ---------------------------------------------------------------------------
# 2. Configs
# ---------------------------------------------------------------------------

def test_configs_dir_exists():
    assert os.path.isdir(CONFIGS_DIR), f"Configs-Verzeichnis nicht gefunden: {CONFIGS_DIR}"


def _active_config_files():
    """Gibt Config-Dateien der aktiven Strategien zurück."""
    with open(SETTINGS_FILE) as f:
        data = json.load(f)
    result = []
    for s in data.get('live_trading_settings', {}).get('active_strategies', []):
        sym = s.get('symbol', '')
        tf  = s.get('timeframe', '')
        if sym and tf:
            safe = f"{sym.replace('/', '').replace(':', '')}_{tf}"
            result.append(f"config_{safe}_fib.json")
    return result


def test_active_configs_exist():
    for fname in _active_config_files():
        path = os.path.join(CONFIGS_DIR, fname)
        assert os.path.exists(path), f"Config fehlt: {fname}"


def test_active_configs_valid_json():
    for fname in _active_config_files():
        path = os.path.join(CONFIGS_DIR, fname)
        if not os.path.exists(path):
            pytest.skip(f"Config nicht vorhanden: {fname}")
        with open(path) as f:
            cfg = json.load(f)
        assert 'strategy' in cfg, f"'strategy' fehlt in {fname}"
        assert 'risk'     in cfg, f"'risk' fehlt in {fname}"
        assert 'market'   in cfg, f"'market' fehlt in {fname}"


def test_active_configs_have_backtest_meta():
    for fname in _active_config_files():
        path = os.path.join(CONFIGS_DIR, fname)
        if not os.path.exists(path):
            pytest.skip(f"Config nicht vorhanden: {fname}")
        with open(path) as f:
            cfg = json.load(f)
        bt = cfg.get('_backtest', {})
        assert 'pnl_pct' in bt, f"'_backtest.pnl_pct' fehlt in {fname}"


def test_active_configs_risk_params():
    for fname in _active_config_files():
        path = os.path.join(CONFIGS_DIR, fname)
        if not os.path.exists(path):
            pytest.skip(f"Config nicht vorhanden: {fname}")
        with open(path) as f:
            cfg = json.load(f)
        risk = cfg.get('risk', {})
        lev  = float(risk.get('leverage', 0))
        rpe  = float(risk.get('risk_per_entry_pct', 0))
        assert lev  >= 1,   f"Ungültiger Leverage in {fname}: {lev}"
        assert rpe  >  0,   f"Ungültiges risk_per_entry_pct in {fname}: {rpe}"
        assert rpe  <= 10,  f"risk_per_entry_pct zu hoch in {fname}: {rpe}"


# ---------------------------------------------------------------------------
# 3. Backtester — Einheit
# ---------------------------------------------------------------------------

def _make_minimal_df(n=300):
    """Erstellt einen minimalen OHLCV-DataFrame für Tests."""
    import numpy as np
    np.random.seed(42)
    dates  = pd.date_range('2024-01-01', periods=n, freq='4h', tz='UTC')
    close  = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high   = close + abs(np.random.randn(n) * 0.3)
    low    = close - abs(np.random.randn(n) * 0.3)
    open_  = close + np.random.randn(n) * 0.1
    volume = abs(np.random.randn(n) * 1000 + 5000)
    return pd.DataFrame({
        'timestamp': dates, 'open': open_, 'high': high,
        'low': low, 'close': close, 'volume': volume,
    }).set_index('timestamp')


def _minimal_config():
    return {
        'market':   {'symbol': 'BTC/USDT:USDT', 'timeframe': '4h'},
        'strategy': {
            'swing_lookback': 50, 'pivot_left': 3, 'pivot_right': 3,
            'fib_entry_pct': 0.382, 'fib_tp_pct': 1.0,
            'rsi_period': 14, 'rsi_long_max': 70, 'rsi_short_min': 30,
            'atr_period': 14, 'vol_ma_period': 20, 'vol_factor': 1.0,
            'trend_ema_period': 50, 'use_trend_filter': False,
        },
        'risk': {'leverage': 5, 'risk_per_entry_pct': 1.0},
    }


def test_backtester_import():
    from fibot.analysis.backtester import run_backtest, BacktestResult
    assert callable(run_backtest)


def test_backtester_runs_without_error():
    from fibot.analysis.backtester import run_backtest, precompute_indicators, precompute_all_signals
    df  = _make_minimal_df()
    cfg = _minimal_config()
    df  = precompute_indicators(df, cfg)
    df  = precompute_all_signals(df, cfg)
    result = run_backtest(df, cfg, start_capital=100.0, symbol='BTC/USDT:USDT', timeframe='4h')
    assert result is not None
    assert result.start_capital == 100.0
    assert result.end_capital   >= 0


def test_backtester_result_fields():
    from fibot.analysis.backtester import run_backtest, precompute_indicators, precompute_all_signals
    df  = _make_minimal_df()
    cfg = _minimal_config()
    df  = precompute_indicators(df, cfg)
    df  = precompute_all_signals(df, cfg)
    result = run_backtest(df, cfg, start_capital=100.0)
    assert hasattr(result, 'trades')
    assert hasattr(result, 'win_rate')
    assert hasattr(result, 'max_drawdown_pct')
    assert 0 <= result.win_rate <= 100
    assert result.max_drawdown_pct >= 0


# ---------------------------------------------------------------------------
# 4. auto_days_for_timeframe
# ---------------------------------------------------------------------------

def test_auto_days_known_timeframes():
    from fibot.analysis.backtester import auto_days_for_timeframe
    assert auto_days_for_timeframe('5m')  ==  90
    assert auto_days_for_timeframe('15m') ==  90
    assert auto_days_for_timeframe('1h')  == 365
    assert auto_days_for_timeframe('4h')  == 730
    assert auto_days_for_timeframe('1d')  == 1095


def test_auto_days_unknown_returns_default():
    from fibot.analysis.backtester import auto_days_for_timeframe
    assert auto_days_for_timeframe('99x') == 365


# ---------------------------------------------------------------------------
# 5. Secret.json (nur Struktur, kein Inhalt)
# ---------------------------------------------------------------------------

def test_secret_exists():
    secret_path = os.path.join(PROJECT_ROOT, 'secret.json')
    if not os.path.exists(secret_path):
        pytest.skip("secret.json nicht vorhanden (nur auf VPS)")
    assert os.path.exists(secret_path)


def test_secret_has_fibot_key():
    secret_path = os.path.join(PROJECT_ROOT, 'secret.json')
    if not os.path.exists(secret_path):
        pytest.skip("secret.json nicht vorhanden")
    with open(secret_path) as f:
        data = json.load(f)
    assert 'fibot' in data, "'fibot'-Key fehlt in secret.json"
    fibot = data['fibot']
    if isinstance(fibot, list):
        fibot = fibot[0]
    assert 'apiKey'  in fibot, "'apiKey' fehlt unter 'fibot'"
    assert 'secret'  in fibot, "'secret' fehlt unter 'fibot'"


# ---------------------------------------------------------------------------
# 6. Struktur-Klassifikation — Live/Backtest muessen identisch bleiben
# ---------------------------------------------------------------------------
# detect_structure() (live) und _quick_structure_precomputed() (Backtest)
# sind bewusst getrennte Implementierungen (Performance: der Backtest darf
# kein detect_structure() pro Bar aufrufen). Sie sind bisher schon einmal
# unbemerkt auseinandergedriftet -- diese Tests fixieren das gemeinsame
# Verhalten, damit ein zukuenftiger Umbau das nicht wieder tut.

def test_is_parallel_identical_slopes():
    from fibot.strategy.fibonacci_logic import _is_parallel
    assert _is_parallel(0.01, 0.01) is True


def test_is_parallel_within_tolerance():
    from fibot.strategy.fibonacci_logic import _is_parallel, _CHANNEL_PARALLEL_TOL
    # 20% Unterschied liegt unter der 35%-Standardtoleranz
    assert _is_parallel(0.012, 0.010, tol=_CHANNEL_PARALLEL_TOL) is True


def test_is_parallel_beyond_tolerance():
    from fibot.strategy.fibonacci_logic import _is_parallel
    # Realer Fall (AVAX 6h, 2026-09-10): Widerstand steigt 77% schneller als Support
    assert _is_parallel(0.016431, 0.009288, tol=0.35) is False


def test_is_parallel_one_flat_one_not():
    from fibot.strategy.fibonacci_logic import _is_parallel
    assert _is_parallel(0.0, 0.01) is False


def test_is_parallel_both_flat():
    from fibot.strategy.fibonacci_logic import _is_parallel
    assert _is_parallel(0.0, 0.0) is True


def test_classify_channel_when_parallel():
    from fibot.strategy.fibonacci_logic import _classify_structure_type_bias
    # beide Linien steigen, fast gleiche Steigung, Abstand waechst nur leicht
    t, b = _classify_structure_type_bias(0.010, 0.009, spread_start=1.0, spread_end=1.05)
    assert t == "channel_up"
    assert b == "bullish"


def test_classify_broadening_when_diverging():
    from fibot.strategy.fibonacci_logic import _classify_structure_type_bias
    # AVAX-Fund: beide Linien steigen, aber staerker als 35% Unterschied -> kein sauberer Kanal
    t, b = _classify_structure_type_bias(0.016431, 0.009288, spread_start=1.0, spread_end=1.3)
    assert t == "broadening_up"
    assert b == "neutral"


def test_classify_wedge_when_narrowing():
    from fibot.strategy.fibonacci_logic import _classify_structure_type_bias
    # beide Linien fallen, Abstand verengt sich klar (< 85% des Start-Abstands)
    t, b = _classify_structure_type_bias(-0.010, -0.009, spread_start=1.0, spread_end=0.5)
    assert t == "wedge_down"
    assert b == "bullish"


def test_classify_triangle_when_opposite_direction():
    from fibot.strategy.fibonacci_logic import _classify_structure_type_bias
    t, b = _classify_structure_type_bias(0.02, -0.01, spread_start=1.0, spread_end=0.2)
    assert t == "triangle"
    assert b == "bearish"  # obere Linie (Widerstand) ist steiler


def test_live_and_backtest_structure_agree():
    """
    Regressionstest fuer den Fund vom 10.09.2026: detect_structure() (live)
    und _quick_structure_precomputed() (Backtest) muessen fuer dieselben
    Kerzen denselben Bias liefern. Vor dem Fix stimmten nur 3/8 echte
    Live-Coins ueberein (unterschiedliche Pivot-Ordnung + Fenster-Randeffekte).
    """
    import numpy as np
    from scipy.signal import argrelmax, argrelmin
    from fibot.strategy.fibonacci_logic import (
        precompute_indicators, detect_structure, _quick_structure_precomputed,
    )

    df = _make_minimal_df(n=400)
    config = _minimal_config()
    df = precompute_indicators(df, config)

    piv_l, piv_r = 3, 3
    struct_lb = 60
    struct_tol = 0.3
    order = max(piv_l, piv_r, 1)

    atr = float(df['_atr'].iloc[-1])
    live_struct = detect_structure(df, struct_lb, piv_l, piv_r,
                                   tolerance_atr_mult=struct_tol, atr_override=atr)

    highs, lows, closes = df['high'].values, df['low'].values, df['close'].values
    ph_pos = argrelmax(highs, order=order)[0]
    pl_pos = argrelmin(lows, order=order)[0]
    ph_val = highs[ph_pos]
    pl_val = lows[pl_pos]
    i = len(df) - 1
    bt_bias, _, _ = _quick_structure_precomputed(
        highs, lows, closes, ph_pos, pl_pos, ph_val, pl_val,
        i, struct_lb, order, atr, struct_tol, direction="down")

    assert live_struct.bias == bt_bias, (
        f"Live-Bias '{live_struct.bias}' ({live_struct.type}) != "
        f"Backtest-Bias '{bt_bias}' -- Struktur-Erkennung ist wieder auseinandergelaufen."
    )


# ---------------------------------------------------------------------------
# 7. Live-Test der Konfluenz-Orderart — PEPE/USDT:USDT auf Bitget (Minimalbetrag)
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def live_setup():
    import time
    print('\n--- Starte FiBot Live-Workflow-Test (PEPE) ---')

    if os.environ.get('FIBOT_SKIP_LIVE'):
        pytest.skip('FIBOT_SKIP_LIVE gesetzt — Live-Test uebersprungen.')
    secret_path = os.path.join(PROJECT_ROOT, 'secret.json')
    if not os.path.exists(secret_path):
        pytest.skip('secret.json nicht gefunden — Live-Test uebersprungen.')

    with open(secret_path) as f:
        secrets = json.load(f)

    if not secrets.get('fibot'):
        pytest.skip("Kein 'fibot'-Key in secret.json — Live-Test uebersprungen.")

    fibot_cfg = secrets['fibot']
    if isinstance(fibot_cfg, list):
        fibot_cfg = fibot_cfg[0]

    from fibot.utils.exchange import Exchange
    try:
        exchange = Exchange(fibot_cfg)
        if not exchange.markets:
            pytest.fail('Exchange konnte nicht initialisiert werden.')
    except Exception as e:
        pytest.fail(f'Exchange-Initialisierung fehlgeschlagen: {e}')

    symbol = 'PEPE/USDT:USDT'

    print(f'-> Bereinige {symbol} vor dem Test...')
    try:
        exchange.cancel_all_orders_for_symbol(symbol)
        time.sleep(2)
        positions = exchange.fetch_open_positions(symbol)
        if positions:
            pos  = positions[0]
            side = 'sell' if pos['side'] == 'long' else 'buy'
            amt  = float(pos.get('contracts') or pos.get('contractSize', 0))
            if amt > 0:
                exchange.place_market_order(symbol, side, amt, reduce=True)
                time.sleep(3)
        print('-> Ausgangszustand sauber.')
    except Exception as e:
        pytest.fail(f'Fehler beim Bereinigen: {e}')

    yield exchange, symbol

    print('\n[Teardown] Raeume nach dem Test auf...')
    try:
        exchange.cancel_all_orders_for_symbol(symbol)
        time.sleep(2)
        positions = exchange.fetch_open_positions(symbol)
        if positions:
            pos  = positions[0]
            side = 'sell' if pos['side'] == 'long' else 'buy'
            amt  = float(pos.get('contracts') or pos.get('contractSize', 0))
            if amt > 0:
                exchange.place_market_order(symbol, side, amt, reduce=True)
                time.sleep(3)
        exchange.cancel_all_orders_for_symbol(symbol)
        print('-> Teardown abgeschlossen.')
    except Exception as e:
        print(f'FEHLER beim Teardown: {e}')


def _tpsl_prices(orders):
    """Trigger-Preise aus Bitget Position-TP/SL-Orders (profit_loss)."""
    out = []
    for o in orders:
        trig = (o.get('triggerPrice') or o.get('stopPrice') or o.get('info', {}).get('triggerPrice'))
        try:
            out.append((float(trig), o.get('info', {}).get('planType', '')))
        except (TypeError, ValueError):
            continue
    return out


def test_live_confluence_order_on_bitget(live_setup):
    """
    Echter Test der Konfluenz-Orderart auf Bitget (PEPE, Minimalbetrag):
    A) Limit-Order UNTER Markt mit angehaengtem SL/TP -> Bitget speichert preset-SL/TP an der Order
       -> wieder storniert, kein Fill.
    B) Limit-Order knapp UEBER Markt (sofortiger Fill, ca. 6 USDT Notional) mit angehaengtem SL/TP
       -> Position offen, Bitget hat SL und TP als Position-TP/SL aktiviert, der Self-Repair-Abruf
       des Bots (fetch_position_tpsl_orders) findet beide -> Position sofort per Market geschlossen.
    Kosten: wenige Cent Gebuehren.
    """
    import math
    import time

    exchange, symbol = live_setup
    with open(os.path.join(PROJECT_ROOT, 'secret.json')) as f:
        tg = json.load(f).get('telegram', {})
    from fibot.utils.telegram import send_message

    free = exchange.fetch_balance_usdt()
    print(f'\n--- Freies Guthaben: {free:.2f} USDT ---')
    if free < 5.0:
        pytest.skip(f'Zu wenig freies Guthaben ({free:.2f} USDT) fuer den Live-Test.')

    exchange.set_margin_mode(symbol, 'isolated')
    time.sleep(0.5)
    exchange.set_leverage(symbol, 5, 'isolated')
    time.sleep(0.5)
    price = float(exchange.exchange.fetch_ticker(symbol)['last'])
    amount = float(exchange.amount_to_precision(symbol, math.ceil(6.0 / price)))
    print(f'-> PEPE @ {price:.8f} | Menge {amount} (~{amount * price:.2f} USDT)')

    # ---------------- A) ohne Fill ----------------
    entry_a, sl_a, tp_a = price * 0.97, price * 0.94, price * 1.03
    print(f'\n[A] Limit-Kauf {entry_a:.8f} (unter Markt) mit SL {sl_a:.8f} / TP {tp_a:.8f}')
    order_a = exchange.place_limit_order_with_tpsl(symbol, 'buy', amount, entry_a, sl_a, tp_a)
    assert order_a and order_a.get('id'), 'Order A wurde nicht angelegt.'
    time.sleep(2)
    info_a = (exchange.fetch_order(order_a['id'], symbol) or {}).get('info', {})
    preset_sl = float(info_a.get('presetStopLossPrice') or 0)
    preset_tp = float(info_a.get('presetStopSurplusPrice') or 0)
    print(f'-> Bitget meldet an der Order: presetStopLossPrice={preset_sl}  presetStopSurplusPrice={preset_tp}')
    exchange.cancel_order(order_a['id'], symbol)
    time.sleep(1)
    assert abs(preset_sl - sl_a) / sl_a < 0.01, f'SL nicht an der Order gespeichert (info: {info_a})'
    assert abs(preset_tp - tp_a) / tp_a < 0.01, f'TP nicht an der Order gespeichert (info: {info_a})'
    print('-> [A] OK: SL und TP haengen an der Limit-Order, Order storniert.')

    # ---------------- B) mit Fill ----------------
    price = float(exchange.exchange.fetch_ticker(symbol)['last'])
    entry_b, sl_b, tp_b = price * 1.005, price * 0.97, price * 1.03
    print(f'\n[B] Limit-Kauf {entry_b:.8f} (knapp ueber Markt -> sofortiger Fill) mit SL {sl_b:.8f} / TP {tp_b:.8f}')
    order_b = exchange.place_limit_order_with_tpsl(symbol, 'buy', amount, entry_b, sl_b, tp_b)
    assert order_b and order_b.get('id'), 'Order B wurde nicht angelegt.'
    pos = []
    for _ in range(10):
        time.sleep(1.5)
        pos = exchange.fetch_open_positions(symbol, strict=True)
        if pos:
            break
    assert pos, 'Order B wurde nicht gefuellt (keine Position).'
    print(f"-> Position offen: {pos[0].get('side')} {pos[0].get('contracts')} @ {pos[0].get('entryPrice')}")
    time.sleep(2)
    tpsl = _tpsl_prices(exchange.fetch_position_tpsl_orders(symbol))
    print(f'-> Position-TP/SL laut Bitget: {tpsl}')
    found_sl = any(abs(p - sl_b) / sl_b < 0.01 for p, _ in tpsl)
    found_tp = any(abs(p - tp_b) / tp_b < 0.01 for p, _ in tpsl)

    # sofort schliessen, egal wie die Pruefung ausgeht
    exchange.place_market_order(symbol, 'sell', float(pos[0].get('contracts')), reduce=True)
    time.sleep(3)
    exchange.cancel_all_orders_for_symbol(symbol)
    time.sleep(2)
    left = exchange.fetch_open_positions(symbol, strict=True)
    print(f'-> Position geschlossen: {not left}')

    ok = found_sl and found_tp and not left
    send_message(tg.get('bot_token', ''), tg.get('chat_id', ''),
                 f"[TEST] FiBot Konfluenz-Order live (PEPE, ~{amount * price:.1f} USDT)\n"
                 f"A) SL/TP an Limit-Order gespeichert: ja\n"
                 f"B) Fill -> Position-SL aktiv: {'ja' if found_sl else 'NEIN'}, TP aktiv: {'ja' if found_tp else 'NEIN'}\n"
                 f"Position wieder geschlossen: {'ja' if not left else 'NEIN'}\n"
                 f"{'BESTANDEN' if ok else 'FEHLGESCHLAGEN'}")
    assert found_sl, f'Nach dem Fill kein SL als Position-TP/SL gefunden: {tpsl}'
    assert found_tp, f'Nach dem Fill kein TP als Position-TP/SL gefunden: {tpsl}'
    assert not left, 'Test-Position wurde nicht geschlossen!'
    print('\n--- LIVE-TEST KONFLUENZ-ORDER ERFOLGREICH ---')
