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
    result = run_backtest(df, cfg, capital=100.0, symbol='BTC/USDT:USDT', timeframe='4h')
    assert result is not None
    assert result.start_capital == 100.0
    assert result.end_capital   >= 0


def test_backtester_result_fields():
    from fibot.analysis.backtester import run_backtest, precompute_indicators, precompute_all_signals
    df  = _make_minimal_df()
    cfg = _minimal_config()
    df  = precompute_indicators(df, cfg)
    df  = precompute_all_signals(df, cfg)
    result = run_backtest(df, cfg, capital=100.0)
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
    assert os.path.exists(secret_path), \
        "secret.json fehlt — bitte aus secret.json.template erstellen"


def test_secret_has_fibot_key():
    secret_path = os.path.join(PROJECT_ROOT, 'secret.json')
    if not os.path.exists(secret_path):
        pytest.skip("secret.json nicht vorhanden")
    with open(secret_path) as f:
        data = json.load(f)
    assert 'fibot' in data, "'fibot'-Key fehlt in secret.json"
    fibot = data['fibot']
    assert 'apiKey'     in fibot, "'apiKey' fehlt unter 'fibot'"
    assert 'secretKey'  in fibot, "'secretKey' fehlt unter 'fibot'"


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

    from fibot.utils.exchange import Exchange
    try:
        exchange = Exchange(secrets['fibot'])
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
    import time
    from fibot.utils.exchange import Exchange

    exchange, symbol = live_setup

    bal = exchange.fetch_balance_usdt()
    print(f'\n--- Verfuegbares Guthaben: {bal:.4f} USDT ---')
    if bal < 5.0:
        pytest.skip(f'Zu wenig Guthaben ({bal:.2f} USDT < 5 USDT) fuer Live-Test.')

    # Leverage & Margin setzen
    print('-> Setze Margin-Modus: isolated | Leverage: 5x')
    exchange.set_margin_mode(symbol, 'isolated')
    time.sleep(0.5)
    exchange.set_leverage(symbol, 5, 'isolated')
    time.sleep(0.5)

    # Aktuellen Preis holen
    ticker = exchange.exchange.fetch_ticker(symbol)
    price  = float(ticker['last'])
    print(f'-> Aktueller PEPE-Preis: {price:.8f}')

    # Limit-Order weit unter Markt → wird nie gefüllt, kann sicher storniert werden
    limit_price = round(price * 0.50, 8)
    amount      = exchange.exchange.amount_to_precision(symbol, 500_000)

    print(f'\n[Schritt 1/3] Platziere LONG Limit-Order @ {limit_price:.8f} ({amount} PEPE)...')
    order = exchange.place_limit_order(symbol, 'buy', float(amount), limit_price)
    assert order and order.get('id'), 'FEHLER: Limit-Order wurde nicht platziert.'
    order_id = order['id']
    print(f'-> Order platziert. ID: {order_id}')
    time.sleep(2)

    print('\n[Schritt 2/3] Pruefe ob Order offen ist...')
    open_orders = exchange.fetch_open_orders(symbol)
    ids = [o['id'] for o in open_orders]
    assert order_id in ids, f'FEHLER: Order {order_id} nicht in offenen Orders gefunden.'
    print(f'-> Order gefunden ({len(open_orders)} offene Order(s)).')

    print('\n[Schritt 3/3] Storniere Order...')
    exchange.cancel_order(order_id, symbol)
    time.sleep(2)

    remaining = exchange.fetch_open_orders(symbol)
    remaining_ids = [o['id'] for o in remaining]
    assert order_id not in remaining_ids, 'FEHLER: Order wurde nicht storniert.'
    print('-> Order erfolgreich storniert.')

    positions = exchange.fetch_open_positions(symbol)
    assert len(positions) == 0, 'FEHLER: Unerwartete offene Position nach dem Test.'

    print('\n--- LIVE-TEST ERFOLGREICH (PEPE) ---')
