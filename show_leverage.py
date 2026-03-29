#!/usr/bin/env python3
"""Zeigt Hebel, SL, Risiko und Backtest-Parameter aller aktiven fibot-Strategien."""
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(PROJECT_ROOT, 'settings.json')
CONFIGS_DIR   = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs')


def fmt(val, suffix='', decimals=2, fallback='—'):
    if isinstance(val, (int, float)):
        return f"{val:.{decimals}f}{suffix}"
    return fallback


def main():
    try:
        with open(SETTINGS_PATH) as f:
            settings = json.load(f)
    except FileNotFoundError:
        print("Fehler: settings.json nicht gefunden.")
        sys.exit(1)

    live = settings.get('live_trading_settings', {})
    active_files = []

    for s in live.get('active_strategies', []):
        if not isinstance(s, dict) or not s.get('active', True):
            continue
        symbol_clean = s['symbol'].replace('/', '').replace(':', '')
        tf = s['timeframe']
        candidate = f"config_{symbol_clean}_{tf}_fib.json"
        if os.path.exists(os.path.join(CONFIGS_DIR, candidate)):
            active_files.append(candidate)
        else:
            print(f"  WARN  Config fuer {s['symbol']} {tf} nicht gefunden.")

    if not active_files:
        print("Keine aktiven Konfigurationen gefunden.")
        sys.exit(0)

    print()
    print(f"  Modus     : Manuell (settings.json)")
    print(f"  Strategien: {len(active_files)}")

    for filename in active_files:
        full_path = os.path.join(CONFIGS_DIR, filename)
        if not os.path.exists(full_path):
            print(f"\n  WARN  {filename} nicht gefunden.")
            continue

        with open(full_path) as f:
            cfg = json.load(f)

        risk      = cfg.get('risk', {})
        strat_cfg = cfg.get('strategy', {})
        bt        = cfg.get('_backtest', {})
        mkt       = cfg.get('market', {})

        symbol = mkt.get('symbol', '').split('/')[0]
        tf     = mkt.get('timeframe', '')
        label  = f"{symbol}/{tf}" if symbol else filename.replace('config_', '').replace('.json', '')

        leverage    = risk.get('leverage')
        risk_pct    = risk.get('risk_per_entry_pct')
        margin      = risk.get('margin_mode', '—')
        min_rr      = strat_cfg.get('min_rr')
        fib_sl      = strat_cfg.get('fib_sl_level')
        atr_mult    = strat_cfg.get('atr_sl_multiplier')
        pnl         = bt.get('pnl_pct')

        # SL-Zeile: Fib-Level + ATR-Mult
        if isinstance(fib_sl, (int, float)) and isinstance(atr_mult, (int, float)):
            sl_str = f"Fib {fib_sl:.3f}  (ATR x{atr_mult:.2f})"
        elif isinstance(fib_sl, (int, float)):
            sl_str = f"Fib {fib_sl:.3f}"
        elif isinstance(atr_mult, (int, float)):
            sl_str = f"ATR x{atr_mult:.2f}"
        else:
            sl_str = '—'

        print()
        print(f"  {'=' * 52}")
        print(f"  {label}")
        print(f"  {'=' * 52}")
        print(f"  Hebel          : {fmt(leverage, 'x', 0)}")
        print(f"  Risiko/Trade   : {fmt(risk_pct, '%')}")
        print(f"  Min R:R        : {fmt(min_rr, '', 2)}")
        print(f"  Margin         : {margin}")
        print(f"  ---")
        print(f"  SL             : {sl_str}")
        print(f"  TSL Aktivierung: kein TSL")
        print(f"  TSL Callback   : kein TSL")
        print(f"  ---")
        print(f"  PnL (Backtest) : {fmt(pnl, '%', 1, 'n/a')}")

    print()


if __name__ == '__main__':
    main()
