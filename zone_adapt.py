#!/usr/bin/env python3
"""FiBot Zonen-Anpassung (monatlich, Desktop mit CUDA).

Langsame Anpassung weniger Parameter, getestet in
forschung/variable_konfig_apt30m_2026_11_18 (Teil 7, vorab festgelegt, bestanden):

- Angepasst werden NUR fib_lo, fib_hi, zone_tol_atr. Alle anderen Parameter bleiben
  auf den Basiswerten der Config.
- Gedaechtnis: die letzten 12 vollen Monate vor dem laufenden Monat.
- Regel: hoechster Netto-R pro Trade unter den Einstellungen mit >= 20 Trades im
  Fenster (Trendfilter + eine Position zur Zeit, Kosten wie live). Sonst Basiswerte.
- Die Basiswerte werden beim ersten Lauf in `_zone_adapt.base_zone` gespeichert und
  bei jedem weiteren Lauf von dort genommen (kein Weiterwandern ohne Daten).

Aufruf (gpu-venv mit cupy):  python zone_adapt.py            # alle Configs
                             python zone_adapt.py APT_30m    # einzelne
Danach Configs committen/pushen; der VPS uebernimmt sie per update.sh.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

from fibot.analysis.zone_adapt.engine import (  # noqa: E402
    NO_AGE, PARAMS, Engine, enc, read_cache, setup_from_dict)

CONFIGS = ROOT / 'src' / 'fibot' / 'strategy' / 'configs'
ZONE = ('fib_lo', 'fib_hi', 'zone_tol_atr')
WINDOW_MONTHS = 12
MIN_TRADES = 20
VERSION = 1


def adapt(path: Path, now: pd.Timestamp) -> dict:
    cfg = json.loads(path.read_text(encoding='utf-8'))
    meta = cfg.get('_zone_adapt', {})
    base_zone = meta.get('base_zone') or {k: cfg['strategy'][k] for k in ZONE}
    setup = setup_from_dict(cfg, vary=ZONE, base=base_zone)
    coin, tf = setup.coin, setup.tf
    df = read_cache(coin, tf)
    current = now.tz_convert(None).to_period('M')
    window = pd.period_range(current - WINDOW_MONTHS, current - 1, freq='M')
    periods = df.index.tz_convert(None).to_period('M')
    pos = {p: k for k, p in enumerate(window)}
    mob = np.array([pos.get(p, -1) for p in periods], dtype=np.int64)
    eng = Engine(setup, df, mob, len(window), log=lambda *a: None)
    r = eng.msum.sum(1)
    n = eng.mcnt.sum(1)
    base_idx = eng.combo_index({**setup.live})
    ok = n >= MIN_TRADES
    if ok.any():
        per_trade = np.where(ok, r / np.maximum(n, 1), -np.inf)
        best = int(np.argmax(per_trade))
    else:
        best = base_idx
    chosen = {k: float(eng.pv[best, PARAMS.index(k)]) for k in ZONE}
    data_months = sorted({str(p) for p in periods if p in pos})
    eng.free()

    old = {k: cfg['strategy'][k] for k in ZONE}
    for k, v in chosen.items():
        cfg['strategy'][k] = round(v, 6)
    cfg['_zone_adapt'] = {
        'version': VERSION,
        'updated': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'valid_for_month': str(current),
        'window': [str(window[0]), str(window[-1])],
        'months_with_data': len(data_months),
        'rule': f'max Netto-R/Trade, >= {MIN_TRADES} Trades in {WINDOW_MONTHS} Monaten, sonst Basis',
        'base_zone': base_zone,
        'chosen_zone': chosen,
        'fallback_to_base': bool(not ok.any()),
        'window_trades': int(n[best]), 'window_net_r': round(float(r[best]), 2),
        'window_r_per_trade': round(float(r[best] / max(n[best], 1)), 3),
        'base_window_trades': int(n[base_idx]), 'base_window_net_r': round(float(r[base_idx]), 2),
        'research': 'forschung/variable_konfig_apt30m_2026_11_18/README.md (Teil 7)',
    }
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return {'config': path.name, 'old': old, 'new': chosen, **{k: cfg['_zone_adapt'][k] for k in (
        'fallback_to_base', 'window_trades', 'window_net_r', 'base_window_trades', 'base_window_net_r',
        'months_with_data')}}


def main() -> int:
    now = pd.Timestamp(datetime.now(timezone.utc))
    wanted = sys.argv[1:]
    paths = sorted(CONFIGS.glob('config_*_fib.json'))
    if wanted:
        paths = [p for p in paths if any(p.name == f"config_{w.split('_')[0]}USDTUSDT_{w.split('_')[1]}_fib.json"
                                          for w in wanted)]
        if not paths:
            print('Keine passende Config gefunden.', file=sys.stderr)
            return 1
    rows = []
    for path in paths:
        row = adapt(path, now)
        rows.append(row)
        changed = any(abs(float(row['old'][k]) - row['new'][k]) > 1e-9 for k in ZONE)
        zone_txt = ' '.join(f'{k}={row["new"][k]:g}' for k in ZONE)
        print(f"{row['config']:38s} {'NEU ' if changed else 'gleich'} "
              f"{zone_txt} | 12M: {row['window_trades']} Tr "
              f"{row['window_net_r']:+.1f} R (Basis {row['base_window_trades']} Tr {row['base_window_net_r']:+.1f} R)"
              f"{' | Fallback Basis' if row['fallback_to_base'] else ''}", flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
