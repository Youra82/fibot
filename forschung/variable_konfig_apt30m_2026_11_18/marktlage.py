"""Teil 2: Parameter je aktueller Marktlage (Schwankung x Trend), Wechsel bei jeder Kerze.

Regeln siehe README.md, Abschnitt "Teil 2" (vorab festgelegt).
"""

from datetime import datetime
import json
from pathlib import Path
import sys
import time

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from engine import NO_AGE, PARAMS, Engine, enc, read_cache, setup_from_config
from run import LABELS, TOP_FRAC, UNSEEN_START, metrics, snap

HERE = Path(__file__).resolve().parent
OUT_ROOT = HERE / 'ergebnisse_marktlage'
N_PLACEBO = 20
VOL_NAMES = ('ruhig', 'normal', 'unruhig')
TREND_NAMES = ('seitwaerts', 'mittel', 'Trend')


def market_state(df: pd.DataFrame, tf: str, dev_mask: np.ndarray):
    bar_h = pd.Timedelta(tf) / pd.Timedelta('1h')
    n48, n30d, n72 = (max(2, int(round(h / bar_h))) for h in (48, 720, 72))
    close = df['close'].astype(float)
    ret = np.log(close).diff()
    vol = (ret.rolling(n48).std() / ret.rolling(n30d).std()).shift(1)
    er = ((close - close.shift(n72)).abs() / close.diff().abs().rolling(n72).sum()).shift(1)
    vol, er = vol.to_numpy(), er.to_numpy()
    ok = np.isfinite(vol) & np.isfinite(er)
    vq = np.nanquantile(vol[dev_mask & ok], [1 / 3, 2 / 3])
    eq = np.nanquantile(er[dev_mask & ok], [1 / 3, 2 / 3])
    state = np.full(len(df), -1, dtype=np.int64)
    state[ok] = np.searchsorted(vq, vol[ok]) * 3 + np.searchsorted(eq, er[ok])
    return state, vol, er, vq, eq


class Runner:
    def __init__(self, eng, month_of_bar):
        self.eng, self.mob, self.cache = eng, month_of_bar, {}

    def events(self, combo):
        if combo not in self.cache:
            ev = self.eng.merged_events(combo)
            ev['m'] = self.mob[ev['i'].to_numpy()]
            self.cache[combo] = ev
        return self.cache[combo]

    def run(self, combo_by_state: dict, state: np.ndarray) -> pd.DataFrame:
        parts = []
        for s, combo in combo_by_state.items():
            ev = self.events(combo)
            parts.append(ev[state[ev['i'].to_numpy()] == s])
        ev = pd.concat(parts).sort_values('i', kind='stable')
        busy, rows = -1, []
        for i, x, r, m in ev[['i', 'x', 'r', 'm']].itertuples(index=False):
            if i <= busy or x < 0 or m < 0:
                continue
            busy = x
            rows.append((int(i), int(x), float(r), int(m)))
        return pd.DataFrame(rows, columns=['i', 'x', 'r', 'm'])


def learn(eng, state, dev_mask, grid, K):
    labels = np.where(dev_mask, state, -1)
    ssum, scnt = eng.aggregate(labels, 9)
    dev_total = ssum.sum(1)
    raw, combo_by_state = np.zeros((9, len(PARAMS))), {}
    for s in range(9):
        top = np.lexsort((-dev_total, -ssum[:, s]))[:K]
        raw[s] = eng.pv[top].mean(0)
        snapped = {key: snap(np.array([raw[s, k]]), grid[key])[0] for k, key in enumerate(PARAMS)}
        combo_by_state[s] = eng.combo_index(snapped)
    return raw, combo_by_state


def analyze(coin, tf, rng):
    t_start = time.time()
    setup = setup_from_config(coin, tf)
    out = OUT_ROOT / setup.name
    out.mkdir(parents=True, exist_ok=True)
    df = read_cache(coin, tf)
    periods = df.index.tz_convert(None).to_period('M')
    dev_start = (df.index[0].tz_convert(None) + pd.Timedelta(days=60)).to_period('M') + 1
    months = pd.period_range(dev_start, periods.max(), freq='M')
    pos = {p: k for k, p in enumerate(months)}
    mob = np.array([pos.get(p, -1) for p in periods], dtype=np.int64)
    nd = pos[UNSEEN_START]
    dev, unseen = list(range(nd)), list(range(nd, len(months)))
    dev_mask = (mob >= 0) & (mob < nd)
    print(f'== {setup.name}', flush=True)
    eng = Engine(setup, df, mob, len(months), log=lambda *a: None)
    K = max(1, int(eng.ncombo * TOP_FRAC))
    state, vol, er, vq, eq = market_state(df, tf, dev_mask)
    runner = Runner(eng, mob)

    raw, cbs = learn(eng, state, dev_mask, setup.grid, K)
    trades = runner.run(cbs, state)
    live = eng.combo_index(setup.live)
    fixed = runner.run({0: live}, np.zeros_like(state))
    ref = curve_check = json.loads((HERE / 'ergebnisse' / setup.name / 'summary.json').read_text(encoding='utf-8'))
    assert abs(metrics(fixed, unseen)['net_r'] - ref['results']['feste Live-Config']['unseen']['net_r']) < 1e-3
    res = {'Marktlage': {'dev': metrics(trades, dev), 'unseen': metrics(trades, unseen)},
           'feste Live-Config': {'dev': metrics(fixed, dev), 'unseen': metrics(fixed, unseen)}}
    curve_summary = json.loads((HERE / 'ergebnisse' / setup.name / 'summary.json').read_text(encoding='utf-8'))
    res['Monats-Kurve (Teil 1)'] = curve_summary['results']['Kurve']

    # Gegentest: ganze Prozedur mit zirkulaer verschobener Marktlage
    bar_h = pd.Timedelta(tf) / pd.Timedelta('1h')
    lo_shift, hi_shift = int(30 * 24 / bar_h), int(300 * 24 / bar_h)
    placebo = []
    for _ in range(N_PLACEBO):
        shifted = np.roll(state, int(rng.integers(lo_shift, hi_shift)))
        _, cbs_p = learn(eng, shifted, dev_mask, setup.grid, K)
        tr_p = runner.run(cbs_p, shifted)
        placebo.append(metrics(tr_p, unseen)['net_r'])
    placebo = np.array(placebo)
    u = res['Marktlage']['unseen']
    run_len = np.diff(np.flatnonzero(np.diff(state[dev_mask]) != 0)).mean() * bar_h
    print(f"  Marktlage   Entw. R {res['Marktlage']['dev']['net_r']:+6.1f} Quote {res['Marktlage']['dev']['hit_rate']:.0%} | "
          f"ungesehen R {u['net_r']:+5.1f} Tr {u['trades']} Quote {u['hit_rate']:.0%} DD {u['max_dd_pct']:.1f}%")
    print(f"  fest        ungesehen R {res['feste Live-Config']['unseen']['net_r']:+5.1f} | "
          f"Monats-Kurve {res['Monats-Kurve (Teil 1)']['unseen']['net_r']:+5.1f} | "
          f"Gegentest Median {np.median(placebo):+5.1f} (Rang Marktlage {np.mean(placebo < u['net_r']):.0%}) | "
          f"Lage wechselt im Schnitt alle {run_len:.1f} h", flush=True)

    # Grafik 1: Parameter je Marktlage (3x3)
    fig, axes = plt.subplots(4, 3, figsize=(15, 17))
    for ax, key in zip(axes.flat, PARAMS):
        k = PARAMS.index(key)
        grid_vals = np.array(setup.grid[key])
        vals = np.array([snap(np.array([raw[s, k]]), setup.grid[key])[0] for s in range(9)]).reshape(3, 3)
        ax.imshow(raw[:, k].reshape(3, 3), cmap='coolwarm', vmin=grid_vals.min(), vmax=grid_vals.max())
        for a in range(3):
            for b in range(3):
                txt = 'keine' if vals[a, b] == NO_AGE else f'{vals[a, b]:g}'
                ax.text(b, a, txt, ha='center', va='center', fontsize=12, weight='bold')
        lv = enc(setup.live[key])
        ax.set_title(f"{LABELS[key]}\n(fest live: {'keine' if lv == NO_AGE else f'{lv:g}'})", fontsize=10)
        ax.set_xticks(range(3), TREND_NAMES); ax.set_yticks(range(3), VOL_NAMES)
    info = axes.flat[-1]
    info.axis('off')
    info.text(0, .9, f'{coin} {tf}: Parameter je Marktlage\n\nZeilen: Schwankung (48 h / 30 T)\n'
              f'Spalten: Trend (Effizienz 72 h)\n\nZahl = verwendeter Rasterwert\nFarbe = Mittel der Top 1 %\n'
              f'gelernt nur aus {months[0]} - {months[nd - 1]}', fontsize=11, va='top')
    fig.suptitle(f'fibot {coin} {tf} - Parameter nach Marktlage', fontsize=15)
    fig.tight_layout(); fig.savefig(out / 'parameter_marktlage.png', dpi=100); plt.close(fig)

    # Grafik 2: Ergebnis
    fig, axes = plt.subplots(2, 2, figsize=(17, 11))
    ax = axes[0, 0]
    for name, tr, c in (('Marktlage', trades, '#2b8a3e'), ('feste Live-Config', fixed, '#c92a2a')):
        eqc = np.cumprod(1 + 0.01 * tr['r'].to_numpy())
        ax.plot(df.index[tr['x'].to_numpy()], (eqc - 1) * 100, color=c, lw=1.8, label=name)
    ax.axvline(months[nd].to_timestamp(), color='k', ls='--', lw=1)
    ax.set_title('Kontoverlauf (1 % Risiko, Zinseszins) %, rechts der Linie ungesehen'); ax.legend(); ax.grid(alpha=.3)
    ax = axes[0, 1]
    ax.hist(placebo, bins=12, color='#adb5bd', label='Gegentest (verschobene Marktlage)')
    for name, v, c in (('Marktlage', u['net_r'], '#2b8a3e'),
                       ('feste Live-Config', res['feste Live-Config']['unseen']['net_r'], '#c92a2a'),
                       ('Monats-Kurve', res['Monats-Kurve (Teil 1)']['unseen']['net_r'], '#1f5fbf')):
        ax.axvline(v, color=c, lw=2.2, label=f'{name}: {v:+.1f} R')
    ax.set_title('Ungesehen: Netto-R'); ax.legend(); ax.grid(alpha=.3)
    ax = axes[1, 0]
    last = df.index >= df.index[-1] - pd.Timedelta(days=30)
    ax.step(df.index[last], state[last], where='post', color='#495057', lw=1)
    ax.set_yticks(range(9), [f'{VOL_NAMES[s // 3]}/{TREND_NAMES[s % 3]}' for s in range(9)], fontsize=8)
    ax.set_title('Marktlage der letzten 30 Tage (wechselt laufend)'); ax.grid(alpha=.3)
    ax = axes[1, 1]
    for key, c in (('sl_buf_atr', '#d9480f'), ('min_rr', '#1f5fbf'), ('zone_tol_atr', '#2b8a3e')):
        series = np.array([enc(eng.pv[cbs[s], PARAMS.index(key)]) if s >= 0 else np.nan for s in state[last]])
        ax.step(df.index[last], series, where='post', color=c, lw=1.4, label=LABELS[key])
    ax.set_title('Beispiel: Parameter der letzten 30 Tage'); ax.legend(); ax.grid(alpha=.3)
    fig.suptitle(f'fibot {coin} {tf} - Parameter nach Marktlage, ungesehener Zeitraum', fontsize=15)
    fig.tight_layout(); fig.savefig(out / 'ergebnis_marktlage.png', dpi=100); plt.close(fig)

    summary = {'created_at': datetime.now().isoformat(), 'coin': coin, 'tf': tf, 'combos': eng.ncombo,
               'vol_terciles': vq.tolist(), 'trend_terciles': eq.tolist(),
               'mean_state_duration_h': float(run_len), 'results': res,
               'placebo_unseen_r': placebo.tolist(),
               'params_by_state': {f'{VOL_NAMES[s // 3]}/{TREND_NAMES[s % 3]}':
                                   {key: float(eng.pv[cbs[s], PARAMS.index(key)]) for key in PARAMS}
                                   for s in range(9)},
               'runtime_s': time.time() - t_start}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    eng.free()
    return summary


def main():
    rng = np.random.default_rng(20261118)
    targets = [a.split('_') for a in sys.argv[1:]] or [['APT', '30m'], ['SHIB', '30m'], ['BAT', '1h'], ['DOT', '2h']]
    results = {f'{c}_{t}': analyze(c, t, rng) for c, t in targets}
    names = list(results)
    fig, ax = plt.subplots(figsize=(12, 5.5))
    x = np.arange(len(names))
    for k, (label, key, c) in enumerate((('Marktlage', 'Marktlage', '#2b8a3e'),
                                         ('Monats-Kurve', 'Monats-Kurve (Teil 1)', '#1f5fbf'),
                                         ('fest', 'feste Live-Config', '#c92a2a'))):
        ax.bar(x + (k - 1) * .25, [results[n]['results'][key]['unseen']['net_r'] for n in names], .25, color=c, label=label)
    ax.scatter(x - .25, [np.median(results[n]['placebo_unseen_r']) for n in names], marker='_', s=600,
               color='k', zorder=3, label='Gegentest-Median')
    ax.set_xticks(x, [n.replace('_', ' ') for n in names]); ax.axhline(0, color='k', lw=.8)
    ax.set_title('Ungesehen (05/2026 - 11/2026): Netto-R'); ax.legend(); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(OUT_ROOT / 'uebersicht_marktlage.png', dpi=110); plt.close(fig)


if __name__ == '__main__':
    main()
