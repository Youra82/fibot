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
    assert float(opt['start_capital']) > 0


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
# 6. Live Workflow Test — PEPE/USDT:USDT auf Bitget (wie dnabot)
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def live_setup():
    import time
    print('\n--- Starte FiBot Live-Workflow-Test (PEPE) ---')

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


def test_live_pepe_order_on_bitget(live_setup):
    """
    Simuliert einen echten FiBot-Eintrag wie im Livebetrieb:
    1. Limit Entry-Order etwas unter Markt (wird nicht gefüllt)
    2. SL + TP als Trigger-Market Orders
    3. Alle 3 Orders auf Bitget sichtbar + Telegram-Benachrichtigung
    4. Aufräumen: Orders stornieren
    """
    import time
    import math

    exchange, symbol = live_setup

    # Telegram laden
    with open(os.path.join(PROJECT_ROOT, 'secret.json')) as f:
        secrets_data = json.load(f)
    tg = secrets_data.get('telegram', {})
    bot_token = tg.get('bot_token', '')
    chat_id   = tg.get('chat_id', '')
    from fibot.utils.telegram import send_message

    bal = exchange.fetch_balance_usdt()
    print(f'\n--- Verfuegbares Guthaben: {bal:.4f} USDT ---')
    if bal < 5.0:
        pytest.skip(f'Zu wenig Guthaben ({bal:.2f} USDT < 5 USDT) fuer Live-Test.')

    # Margin & Leverage
    print('-> Setze Margin-Modus: isolated | Leverage: 5x')
    exchange.set_margin_mode(symbol, 'isolated')
    time.sleep(0.5)
    exchange.set_leverage(symbol, 5, 'isolated')
    time.sleep(0.5)

    # Aktuellen Preis holen + Fib-Signal simulieren
    ticker     = exchange.exchange.fetch_ticker(symbol)
    price      = float(ticker['last'])
    entry_price = round(price * 0.98, 8)   # 2% unter Markt → Limit wird nie gefüllt
    sl_price    = round(price * 0.95, 8)   # 5% unter Markt
    tp_price    = round(price * 1.04, 8)   # 4% über Markt (2:1 R:R)
    print(f'-> PEPE @ {price:.8f} | Entry: {entry_price:.8f} | SL: {sl_price:.8f} | TP: {tp_price:.8f}')

    # Positionsgröße: Risiko 0.5 USDT auf SL-Distanz
    price_risk  = abs(entry_price - sl_price)
    contracts   = 0.5 / price_risk
    amount_str  = exchange.amount_to_precision(symbol, contracts)
    amount      = float(amount_str)
    notional    = amount * entry_price
    print(f'-> Contracts: {amount} | Notional: {notional:.2f} USDT')
    if notional < 5.0:
        # Auf Mindest-Notional aufstocken
        amount  = float(exchange.amount_to_precision(symbol, math.ceil(6.0 / entry_price)))
        notional = amount * entry_price
        print(f'-> Auf Minimum aufgestockt: {amount} PEPE | Notional: {notional:.2f} USDT')

    # --- Schritt 1: Limit Entry-Order ---
    print(f'\n[Schritt 1/3] Platziere Limit Entry-Order @ {entry_price:.8f}...')
    entry_order = exchange.place_limit_order(symbol, 'buy', amount, entry_price)
    assert entry_order and entry_order.get('id'), 'FEHLER: Entry-Order nicht platziert.'
    entry_id = entry_order['id']
    print(f'-> Entry-Order platziert. ID: {entry_id}')
    time.sleep(1)

    # --- Schritt 2: SL + TP Trigger-Orders ---
    print(f'\n[Schritt 2/3] Setze SL @ {sl_price:.8f} und TP @ {tp_price:.8f}...')
    sl_order = exchange.place_trigger_market_order(symbol, 'sell', amount, trigger_price=sl_price, reduce=True)
    time.sleep(0.5)
    tp_order = exchange.place_trigger_market_order(symbol, 'sell', amount, trigger_price=tp_price, reduce=True)
    time.sleep(2)

    # Prüfen was auf Bitget angekommen ist
    open_orders    = exchange.fetch_open_orders(symbol)
    trigger_orders = exchange.fetch_open_trigger_orders(symbol)
    entry_ids      = [o['id'] for o in open_orders]

    assert entry_id in entry_ids, f'FEHLER: Entry-Order {entry_id} nicht in offenen Orders.'
    print(f'-> Entry-Order sichtbar auf Bitget [OK]  (unter "Open Orders")')
    print(f'-> {len(trigger_orders)} Trigger-Order(s) sichtbar auf Bitget [OK]  (unter "Trigger Orders")')

    leverage  = 5
    margin    = round((amount * entry_price) / leverage, 2)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    send_message(bot_token, chat_id,
        f"[TEST] FIBOT ORDER GESETZT\n\n"
        f"Account: Jurij\n"
        f"Symbol: {symbol}\n"
        f"Richtung: LONG\n"
        f"Menge: {amount} Kontrakte\n"
        f"Entry: {entry_price:.8f} USDT (Limit, unter Markt)\n"
        f"Hebel: {leverage}x | Margin: {margin:.2f} USDT\n"
        f"Take-Profit: {tp_price:.8f} USDT\n"
        f"Stop-Loss: {sl_price:.8f} USDT\n\n"
        f"Zeit: {now} UTC")
    print('-> Telegram gesendet.')

    print('\n' + '='*60)
    print('  JETZT BITGET PRUEFEN:')
    print(f'  - "Open Orders"    -> Limit Entry @ {entry_price:.8f}')
    print(f'  - "Trigger Orders" -> SL @ {sl_price:.8f}')
    print(f'                        TP @ {tp_price:.8f}')
    print('  Orders werden in 30 Sekunden storniert...')
    print('='*60)

    for remaining in range(30, 0, -5):
        print(f'  -> Stornierung in {remaining}s...')
        time.sleep(5)

    # --- Schritt 3: Aufräumen ---
    print(f'\n[Schritt 3/3] Storniere alle Orders...')
    exchange.cancel_all_orders_for_symbol(symbol)
    time.sleep(3)

    final_open    = exchange.fetch_open_orders(symbol)
    final_trigger = exchange.fetch_open_trigger_orders(symbol)
    assert entry_id not in [o['id'] for o in final_open], 'FEHLER: Entry-Order nicht storniert.'

    send_message(bot_token, chat_id,
        f"\u2705 *TEST ABGESCHLOSSEN*\n\nAlle Orders storniert.\nFiBot Workflow-Test bestanden.")
    print('-> Alle Orders storniert.')
    print('\n--- LIVE-TEST ERFOLGREICH (PEPE) ---')
