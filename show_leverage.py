#!/usr/bin/env python3
"""Zeigt Hebel, SL, Risiko und Backtest-Parameter aller aktiven fibot-Strategien."""
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(PROJECT_ROOT, 'settings.json')
CONFIGS_DIR   = os.path.join(PROJECT_ROOT, 'src', 'fibot', 'strategy', 'configs')


def fmt(val, suffix='', decimals=2, fallback='n/a'):
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
    rows = []

    for s in live.get('active_strategies', []):
        if not isinstance(s, dict) or not s.get('active', True):
            continue
        symbol_clean = s['symbol'].replace('/', '').replace(':', '')
        tf = s['timeframe']
        candidate = f"config_{symbol_clean}_{tf}_fib.json"
        full_path = os.path.join(CONFIGS_DIR, candidate)
        if not os.path.exists(full_path):
            print(f"  WARN  Config fuer {s['symbol']} {tf} nicht gefunden.")
            continue

        with open(full_path) as f:
            cfg = json.load(f)

        risk      = cfg.get('risk', {})
        strat_cfg = cfg.get('strategy', {})
        bt        = cfg.get('_backtest', {})
        mkt       = cfg.get('market', {})

        symbol   = mkt.get('symbol', '').split('/')[0]
        label    = f"{symbol}/{tf}"
        leverage = fmt(risk.get('leverage'), 'x', 0)
        risk_pct = fmt(risk.get('risk_per_entry_pct'), '%')
        min_rr   = fmt(strat_cfg.get('min_rr'), '', 2)
        margin   = risk.get('margin_mode', 'n/a')
        fib_sl   = strat_cfg.get('fib_sl_level')
        atr_mult = strat_cfg.get('atr_sl_multiplier')
        pnl      = fmt(bt.get('pnl_pct'), '%', 1, 'n/a')

        if isinstance(fib_sl, (int, float)) and isinstance(atr_mult, (int, float)):
            sl_str = f"Fib {fib_sl:.3f} / ATR x{atr_mult:.2f}"
        elif isinstance(fib_sl, (int, float)):
            sl_str = f"Fib {fib_sl:.3f}"
        elif isinstance(atr_mult, (int, float)):
            sl_str = f"ATR x{atr_mult:.2f}"
        else:
            sl_str = 'n/a'

        rows.append({
            'Strategie':    label,
            'Hebel':        leverage,
            'Risiko':       risk_pct,
            'Min R:R':      min_rr,
            'Margin':       margin,
            'SL':           sl_str,
            'TSL Akt.':     'kein TSL',
            'TSL Callback': 'kein TSL',
            'PnL Backtest': pnl,
        })

    if not rows:
        print("Keine aktiven Konfigurationen gefunden.")
        sys.exit(0)

    # Spaltenbreiten berechnen
    cols = list(rows[0].keys())
    widths = {c: len(c) for c in cols}
    for r in rows:
        for c in cols:
            widths[c] = max(widths[c], len(str(r[c])))

    sep   = '+-' + '-+-'.join('-' * widths[c] for c in cols) + '-+'
    header = '| ' + ' | '.join(c.ljust(widths[c]) for c in cols) + ' |'

    print()
    print(f"  Modus: Manuell (settings.json)  |  Strategien: {len(rows)}")
    print()
    print('  ' + sep)
    print('  ' + header)
    print('  ' + sep)
    for r in rows:
        line = '| ' + ' | '.join(str(r[c]).ljust(widths[c]) for c in cols) + ' |'
        print('  ' + line)
    print('  ' + sep)
    print()


if __name__ == '__main__':
    main()
