"""fibot: variable Config -> Parameter-Kurven -> ungesehener Zeitraum (je Coin).

Regeln siehe README.md (vorab festgelegt).
"""

from datetime import datetime
import json
import math
from pathlib import Path
import time

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import sys

from engine import NO_AGE, PARAMS, Engine, enc, read_cache, setup_from_config

HERE = Path(__file__).resolve().parent
UNSEEN_START = pd.Period('2026-05', 'M')
BANDWIDTHS = (1, 1.5, 2, 3, 4, 6, 9, 12)
TARGET = 0.60
TOP_FRAC = 0.01
LABELS = {
    'pivot_k': 'Pivot-Breite k', 'window': 'Kanal-Fenster (Kerzen)',
    'max_break_frac': 'erlaubte Bruch-Quote', 'fib_lo': 'Fib-Zone Anfang',
    'fib_hi': 'Fib-Zone Ende', 'fib_sl': 'Fib-Stop-Level', 'zone_tol_atr': 'Zonen-Toleranz (ATR)',
    'sl_buf_atr': 'Stop-Puffer (ATR)', 'min_rr': 'Mindest-CRV', 'max_age_mult': 'max. Alter (x Impuls)',
    'b_near_upper_atr': 'B nahe Oberkante (ATR)'}


def local_linear(t_obs, y, t0, h):
    w = np.exp(-0.5 * ((t_obs - t0) / h) ** 2)
    X = np.column_stack([np.ones_like(t_obs), t_obs - t0])
    WX = X * w[:, None]
    b = np.linalg.lstsq(WX.T @ X, WX.T @ y, rcond=None)[0]
    return b[0], b[1]


def curve(t_obs, y, t_all, h):
    """Glatte Kurve ueber die Entwicklung, danach lineare Verlaengerung vom Ende."""
    t_end = t_obs[-1]
    end_level, end_slope = local_linear(t_obs, y, t_end, h)
    out = []
    for t in t_all:
        if t <= t_end:
            out.append(local_linear(t_obs, y, t, h)[0])
        else:
            out.append(end_level + end_slope * (t - t_end))
    return np.array(out)


def snap(values, grid):
    grid = np.array(grid, dtype=float)
    v = np.clip(values, grid.min(), grid.max())
    return grid[np.abs(v[:, None] - grid[None, :]).argmin(1)]


def metrics(trades: pd.DataFrame, months: list[int]) -> dict:
    sub = trades[trades['m'].isin(months)]
    per_month = sub.groupby('m')['r'].sum()
    active = len(per_month)
    good = int((per_month > 0).sum())
    eq, peak, dd = 1.0, 1.0, 0.0
    for r in sub['r']:
        eq *= max(0.0, 1 + 0.01 * r)
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak)
    return {'months': len(months), 'months_with_trades': active, 'months_positive': good,
            'hit_rate': good / active if active else 0.0, 'trades': len(sub),
            'net_r': float(sub['r'].sum()), 'win_rate': float((sub['r'] > 0).mean()) if len(sub) else 0.0,
            'pnl_pct_1pct_risk': (eq - 1) * 100, 'max_dd_pct': dd * 100}


class Stitcher:
    def __init__(self, eng, month_of_bar):
        self.eng, self.mob, self.cache = eng, month_of_bar, {}

    def events(self, combo):
        if combo not in self.cache:
            ev = self.eng.merged_events(combo)
            ev['m'] = self.mob[ev['i'].to_numpy()]
            self.cache[combo] = ev
        return self.cache[combo]

    def run(self, combo_per_month: dict) -> pd.DataFrame:
        busy, rows = -1, []
        for m in sorted(combo_per_month):
            ev = self.events(combo_per_month[m])
            for i, x, r in ev.loc[ev['m'] == m, ['i', 'x', 'r']].itertuples(index=False):
                if i <= busy or x < 0:
                    continue
                busy = x
                rows.append((int(i), int(x), float(r), m))
        return pd.DataFrame(rows, columns=['i', 'x', 'r', 'm'])


def analyze(coin, tf):
    t_start = time.time()
    setup = setup_from_config(coin, tf)
    GRID = setup.grid
    LIVE = {k: enc(v) for k, v in setup.live.items()}
    OUT = HERE / 'ergebnisse' / setup.name
    OUT.mkdir(parents=True, exist_ok=True)
    df = read_cache(coin, tf)
    periods = df.index.tz_convert(None).to_period('M')
    dev_start = (df.index[0].tz_convert(None) + pd.Timedelta(days=60)).to_period('M') + 1
    months = pd.period_range(dev_start, periods.max(), freq='M')
    pos = {p: k for k, p in enumerate(months)}
    month_of_bar = np.array([pos.get(p, -1) for p in periods], dtype=np.int64)
    nd = pos[UNSEEN_START]
    dev, unseen = list(range(nd)), list(range(nd, len(months)))
    print(f'== {setup.name}: {len(df):,} Kerzen bis {df.index[-1]} | Entwicklung {len(dev)} Monate, ungesehen {len(unseen)}')

    eng = Engine(setup, df, month_of_bar, len(months))
    pv, msum = eng.pv, eng.msum
    live = eng.combo_index(LIVE)
    st = Stitcher(eng, month_of_bar)

    # Kontrolle: feste Config ueber Stitcher == Kernel-Monatssummen
    fixed_trades = st.run({m: live for m in range(len(months))})
    check = fixed_trades.groupby('m')['r'].sum().reindex(range(len(months)), fill_value=0).to_numpy()
    assert np.allclose(check, msum[live], atol=1e-3), 'Stitcher != Kernel'

    # 1) Stuetzpunkte je Entwicklungsmonat (nur Entwicklungsdaten)
    K = max(1, int(eng.ncombo * TOP_FRAC))
    print(f'Raster {eng.ncombo:,} Kombinationen, Top {K}')
    dev_total = msum[:, :nd].sum(1)
    raw = np.zeros((nd, len(PARAMS)))
    for m in dev:
        score = msum[:, max(0, m - 1):min(nd, m + 2)].sum(1)
        top = np.lexsort((-dev_total, -score))[:K]
        raw[m] = pv[top].mean(0)

    t_obs = np.arange(nd, dtype=float)
    t_all = np.arange(len(months), dtype=float)

    def plan_for(h, flat=False):
        curves, snapped = {}, {}
        for k, key in enumerate(PARAMS):
            c = curve(t_obs, raw[:, k], t_all, h)
            if flat:
                c[nd:] = c[nd - 1]
            curves[key] = c
            snapped[key] = snap(c, GRID[key])
        combo_per_month = {m: eng.combo_index({key: snapped[key][m] for key in PARAMS})
                           for m in range(len(months))}
        return curves, snapped, combo_per_month

    # 2) Bandbreite waehlen (nur Entwicklung)
    scan = []
    for h in BANDWIDTHS:
        _, _, cpm = plan_for(h)
        tr = st.run(cpm)
        scan.append({'h': h, 'dev': metrics(tr, dev), 'unseen': metrics(tr, unseen)})
        print(f"h={h:>4}: Entwicklung Quote {scan[-1]['dev']['hit_rate']:.0%} "
              f"R {scan[-1]['dev']['net_r']:+.1f}")
    ok = [s for s in scan if s['dev']['hit_rate'] >= TARGET]
    chosen = max(ok, key=lambda s: s['h']) if ok else max(scan, key=lambda s: s['dev']['hit_rate'])
    h = chosen['h']
    print(f'gewaehlt h={h} (Ziel {"erreicht" if ok else "NICHT erreicht"})')

    # 3) Anwenden
    curves, snapped, cpm = plan_for(h)
    _, snapped_flat, cpm_flat = plan_for(h, flat=True)
    trades = {'Kurve': st.run(cpm), 'Kurve flach': st.run(cpm_flat), 'feste Live-Config': fixed_trades}
    result = {name: {'dev': metrics(tr, dev), 'unseen': metrics(tr, unseen)} for name, tr in trades.items()}
    unseen_all = msum[:, nd:].sum(1)
    for name in result:
        r = result[name]['unseen']['net_r']
        result[name]['unseen']['rank_vs_all_fixed_pct'] = float((unseen_all < r).mean() * 100)
    dev_hit_all = []
    act = eng.mcnt[:, :nd] > 0
    pos_m = (msum[:, :nd] > 0) & act
    dev_hit_all = pos_m.sum(1) / np.maximum(act.sum(1), 1)
    for name, res in result.items():
        d, u = res['dev'], res['unseen']
        print(f"{name:18s} Entw.: Quote {d['hit_rate']:.0%} R {d['net_r']:+6.1f} Tr {d['trades']:3d} | "
              f"ungesehen: Quote {u['hit_rate']:.0%} ({u['months_positive']}/{u['months_with_trades']}) "
              f"R {u['net_r']:+5.1f} Tr {u['trades']} PnL {u['pnl_pct_1pct_risk']:+.1f}% "
              f"DD {u['max_dd_pct']:.1f}% Rang {u['rank_vs_all_fixed_pct']:.0f}%")
    print(f'feste Kombis mit >=60 % Entwicklungsquote: {(dev_hit_all >= TARGET).mean():.1%}')

    # 4) Grafiken
    dates = months.to_timestamp()
    unseen_x = dates[nd]
    fig, axes = plt.subplots(4, 3, figsize=(17, 15), sharex=True)
    for ax, key in zip(axes.flat, PARAMS):
        k = PARAMS.index(key)
        ax.axvspan(unseen_x, dates[-1] + pd.offsets.MonthEnd(1), color='#f4d9a6', alpha=.5, lw=0)
        ax.scatter(dates[:nd], raw[:, k], s=14, color='#888', label='Monats-Stuetzpunkt (Top 1 %)')
        ax.plot(dates[:nd], curves[key][:nd], color='#1f5fbf', lw=2.2, label=f'Kurve (h={h})')
        ax.plot(dates[nd - 1:], curves[key][nd - 1:], color='#d9480f', lw=2.2, ls='--',
                label='Kurve fortgesetzt (ungesehen)')
        ax.step(dates, snapped[key], where='mid', color='#2b8a3e', lw=1.3, label='verwendeter Rasterwert')
        ax.axhline(LIVE[key], color='#c92a2a', ls=':', lw=1.3, label='feste Live-Config')
        ax.set_title(LABELS[key] + (' (9 = keine Grenze)' if key == 'max_age_mult' and NO_AGE in GRID[key] else ''), fontsize=11)
        ax.grid(alpha=.3)
    info = axes.flat[-1]
    handles, labels = axes.flat[0].get_legend_handles_labels()
    info.axis('off')
    info.legend(handles, labels, loc='upper left', fontsize=10, frameon=False)
    info.text(0, .35, f'{coin} {tf}, {eng.ncombo:,} Kombinationen (CUDA)\n'
              f'Entwicklung {months[0]} - {months[nd - 1]}\n'
              f'ungesehen (gelb) 05/2026 - {df.index[-1]:%d.%m.%Y}', fontsize=10, va='top')
    fig.suptitle(f'fibot {coin} {tf} - Parameter-Kurven ueber die Zeit', fontsize=15)
    fig.tight_layout()
    fig.savefig(OUT / 'parameter_kurven.png', dpi=110)
    plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(17, 11))
    ax = axes[0, 0]
    colors = {'Kurve': '#1f5fbf', 'Kurve flach': '#7048e8', 'feste Live-Config': '#c92a2a'}
    for name, tr in trades.items():
        eq = np.cumprod(1 + 0.01 * tr['r'].to_numpy())
        ax.plot(df.index[tr['x'].to_numpy()], (eq - 1) * 100, color=colors[name], lw=1.8, label=name)
    ax.axvline(dates[nd], color='k', ls='--', lw=1)
    ax.text(dates[nd], ax.get_ylim()[1] * .95, ' ungesehen ->', fontsize=10)
    ax.set_title('Kontoverlauf (1 % Risiko je Trade, Zinseszins), %'); ax.grid(alpha=.3); ax.legend()

    ax = axes[0, 1]
    mr = trades['Kurve'].groupby('m')['r'].sum().reindex(range(len(months)), fill_value=0)
    ax.bar(dates, mr.to_numpy(), width=20, color=np.where(mr.to_numpy() > 0, '#2b8a3e', '#c92a2a'))
    ax.axvspan(unseen_x, dates[-1] + pd.offsets.MonthEnd(1), color='#f4d9a6', alpha=.5, lw=0)
    ax.axhline(0, color='k', lw=.8)
    ax.set_title('Kurven-Config: Netto-R je Monat (gelb = ungesehen)'); ax.grid(alpha=.3)

    ax = axes[1, 0]
    xs = np.arange(len(scan))
    ax.bar(xs - .2, [s['dev']['hit_rate'] * 100 for s in scan], .4, color='#1f5fbf', label='Entwicklung')
    ax.bar(xs + .2, [s['unseen']['hit_rate'] * 100 for s in scan], .4, color='#d9480f', label='ungesehen')
    ax.axhline(60, color='k', ls='--', lw=1)
    ax.set_xticks(xs, [f'h={s["h"]}' for s in scan])
    ax.set_title(f'Monats-Trefferquote je Glaettung (gewaehlt h={h}, nur nach Entwicklung)')
    ax.set_ylabel('% Monate im Plus'); ax.legend(); ax.grid(alpha=.3)

    ax = axes[1, 1]
    ax.hist(unseen_all, bins=80, color='#adb5bd')
    for name, res in result.items():
        ax.axvline(res['unseen']['net_r'], color=colors[name], lw=2.2, label=f"{name}: {res['unseen']['net_r']:+.1f} R")
    ax.set_title(f'Ungesehen: Netto-R aller {eng.ncombo:,} festen Kombinationen'); ax.legend(); ax.grid(alpha=.3)
    fig.suptitle(f'fibot {coin} {tf} - variable Config im ungesehenen Zeitraum', fontsize=15)
    fig.tight_layout()
    fig.savefig(OUT / 'ergebnis.png', dpi=110)
    plt.close(fig)

    summary = {
        'created_at': datetime.now().isoformat(), 'combos': eng.ncombo, 'top_k': K,
        'dev_months': [str(months[m]) for m in dev], 'unseen_months': [str(months[m]) for m in unseen],
        'data_end': str(df.index[-1]), 'bandwidth_scan': scan, 'chosen_h': h,
        'target_reached_in_dev': bool(ok), 'results': result,
        'fixed_combos_dev_hit_ge_60_pct': float((dev_hit_all >= TARGET).mean() * 100),
        'monthly_params': {str(months[m]): {key: float(snapped[key][m]) for key in PARAMS}
                           for m in range(len(months))},
        'monthly_curve': {key: [float(v) for v in curves[key]] for key in PARAMS},
        'raw_points': {key: [float(v) for v in raw[:, PARAMS.index(key)]] for key in PARAMS},
        'coin': coin, 'tf': tf, 'live': setup.live, 'grid': {k: list(v) for k, v in GRID.items()},
        'runtime_s': time.time() - t_start,
    }
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'fertig in {time.time() - t_start:.0f}s', flush=True)
    eng.free()
    return summary


def main():
    targets = [a.split('_') for a in sys.argv[1:]] or [['APT', '30m'], ['SHIB', '30m'], ['BAT', '1h'], ['DOT', '2h']]
    for coin, tf in targets:
        analyze(coin, tf)


if __name__ == '__main__':
    main()
