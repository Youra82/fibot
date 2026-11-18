"""Teil 4: Regler ueber die Wirkung -- taeglich die Parameter, die in den letzten W Tagen am besten liefen.

Regeln siehe README.md, Abschnitt "Teil 4" (vorab festgelegt).
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
from marktlage import Runner
from run import LABELS, TARGET, TOP_FRAC, UNSEEN_START, metrics

HERE = Path(__file__).resolve().parent
OUT_ROOT = HERE / 'ergebnisse_regler'
WINDOWS = (14, 30, 60, 90)
N_PLACEBO = 10
TIEBREAK_DAYS = 365


def regulate(eng, cs, pv_gpu, first_day, nday, W, K, lag=0):
    """Tagesweise Parameter. cs = kumulierte Netto-R je Ausstiegstag (GPU). Gibt {Tag: Kombi} und Werte."""
    cp = eng.cp
    combos, values = {}, {}
    for d in range(first_day, nday):
        end = d - 1 - lag
        if end < 0:
            continue
        a = cs[:, end] - (cs[:, end - W] if end - W >= 0 else 0)
        b = cs[:, end] - (cs[:, end - TIEBREAK_DAYS] if end - TIEBREAK_DAYS >= 0 else 0)
        score = a + 1e-4 * b
        top = cp.argpartition(-score, K)[:K]
        target = cp.asnumpy(pv_gpu[top].mean(0))
        combos[d] = eng.combo_from_values(target)
        values[d] = target
    return combos, values


def analyze(coin, tf, rng):
    t0 = time.time()
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
    day0 = df.index[0].floor('D')
    day_of_bar = ((df.index.floor('D') - day0).days).to_numpy().astype(np.int64)
    nday = int(day_of_bar.max()) + 1
    first_day = int((months[0].to_timestamp().tz_localize('UTC') - day0).days)
    print(f'== {setup.name}: {nday} Tage, Regler ab Tag {first_day}', flush=True)

    eng = Engine(setup, df, mob, len(months), log=lambda *a: None)
    cp = eng.cp
    K = max(1, int(eng.ncombo * TOP_FRAC))
    daily = eng.aggregate_exit_gpu(day_of_bar, nday)
    cs = cp.cumsum(daily, axis=1)
    del daily
    pv_gpu = cp.asarray(eng.pv)
    runner = Runner(eng, mob)
    live = eng.combo_index(setup.live)
    fixed = runner.run({0: live}, np.zeros_like(day_of_bar))
    ref = json.loads((HERE / 'ergebnisse' / setup.name / 'summary.json').read_text(encoding='utf-8'))
    assert abs(metrics(fixed, unseen)['net_r'] - ref['results']['feste Live-Config']['unseen']['net_r']) < 1e-3

    scan, runs = [], {}
    for W in WINDOWS:
        combos, values = regulate(eng, cs, pv_gpu, first_day, nday, W, K)
        tr = runner.run(combos, day_of_bar)
        runs[W] = (combos, values, tr)
        scan.append({'W': W, 'dev': metrics(tr, dev), 'unseen': metrics(tr, unseen),
                     'distinct_combos': len(set(combos.values()))})
        s = scan[-1]
        print(f"  W={W:>2} T: Entw. R {s['dev']['net_r']:+6.1f} Quote {s['dev']['hit_rate']:.0%} | "
              f"ungesehen R {s['unseen']['net_r']:+5.1f} Tr {s['unseen']['trades']} "
              f"Quote {s['unseen']['hit_rate']:.0%} | {s['distinct_combos']} versch. Kombis", flush=True)
    ok = [s for s in scan if s['dev']['hit_rate'] >= TARGET]
    chosen = max(ok or scan, key=lambda s: s['dev']['net_r'])
    W = chosen['W']
    combos, values, trades = runs[W]

    placebo = []
    for _ in range(N_PLACEBO):
        lag = int(rng.integers(120, 366))
        c_p, _ = regulate(eng, cs, pv_gpu, first_day, nday, W, K, lag=lag)
        placebo.append(metrics(runner.run(c_p, day_of_bar), unseen)['net_r'])
    placebo = np.array(placebo)
    u = chosen['unseen']
    res = {'Regler': {'dev': chosen['dev'], 'unseen': u},
           'feste Live-Config': {'dev': metrics(fixed, dev), 'unseen': metrics(fixed, unseen)},
           'Monats-Kurve (Teil 1)': ref['results']['Kurve']}
    changes = sum(combos[d] != combos[d - 1] for d in list(combos)[1:])
    print(f"  gewaehlt W={W}: ungesehen R {u['net_r']:+.1f} | fest {res['feste Live-Config']['unseen']['net_r']:+.1f} | "
          f"Monats-Kurve {res['Monats-Kurve (Teil 1)']['unseen']['net_r']:+.1f} | veralteter Regler Median "
          f"{np.median(placebo):+.1f} (Rang {np.mean(placebo < u['net_r']):.0%}) | Wechsel an {changes / len(combos):.0%} der Tage",
          flush=True)

    # Grafik 1: Regler-Kurven je Parameter (taeglich)
    days = sorted(values)
    dates = [day0 + pd.Timedelta(days=d) for d in days]
    unseen_x = months[nd].to_timestamp().tz_localize('UTC')
    fig, axes = plt.subplots(4, 3, figsize=(17, 15), sharex=True)
    for ax, key in zip(axes.flat, PARAMS):
        k = PARAMS.index(key)
        ax.axvspan(unseen_x, dates[-1], color='#f4d9a6', alpha=.5, lw=0)
        ax.plot(dates, [values[d][k] for d in days], color='#adb5bd', lw=.8, label='Top-1-%-Mittel (taeglich)')
        ax.step(dates, [eng.pv[combos[d], k] for d in days], where='post', color='#2b8a3e', lw=1.2,
                label='verwendeter Wert')
        ax.axhline(enc(setup.live[key]), color='#c92a2a', ls=':', lw=1.3, label='feste Live-Config')
        ax.set_title(LABELS[key] + (' (9 = keine)' if NO_AGE in setup.grid[key] else ''), fontsize=11)
        ax.grid(alpha=.3)
    info = axes.flat[-1]
    h, l = axes.flat[0].get_legend_handles_labels()
    info.axis('off'); info.legend(h, l, loc='upper left', frameon=False)
    info.text(0, .45, f'{coin} {tf}: Regler, Fenster {W} Tage\ntaeglich neu aus geschlossenen Trades\n'
              f'gelb = ungesehen', fontsize=11, va='top')
    fig.suptitle(f'fibot {coin} {tf} - Regler-Kurven (taeglich angepasst)', fontsize=15)
    fig.tight_layout(); fig.savefig(out / 'regler_kurven.png', dpi=100); plt.close(fig)

    # Grafik 2: Ergebnis
    fig, axes = plt.subplots(1, 3, figsize=(20, 5.5))
    ax = axes[0]
    for name, tr, c in (('Regler', trades, '#2b8a3e'), ('feste Live-Config', fixed, '#c92a2a')):
        eqc = np.cumprod(1 + 0.01 * tr['r'].to_numpy())
        ax.plot(df.index[tr['x'].to_numpy()], (eqc - 1) * 100, color=c, lw=1.8, label=name)
    ax.axvline(unseen_x, color='k', ls='--', lw=1)
    ax.set_title('Kontoverlauf % (1 % Risiko), rechts ungesehen'); ax.legend(); ax.grid(alpha=.3)
    ax = axes[1]
    xs = np.arange(len(scan))
    ax.bar(xs - .2, [s['dev']['net_r'] for s in scan], .4, color='#1f5fbf', label='Entwicklung')
    ax.bar(xs + .2, [s['unseen']['net_r'] for s in scan], .4, color='#d9480f', label='ungesehen')
    ax.set_xticks(xs, [f'{s["W"]} T' for s in scan]); ax.axhline(0, color='k', lw=.8)
    ax.set_title(f'Netto-R je Fenster (gewaehlt {W} T)'); ax.legend(); ax.grid(alpha=.3)
    ax = axes[2]
    ax.hist(placebo, bins=8, color='#adb5bd', label='veralteter Regler')
    for name, v, c in (('Regler', u['net_r'], '#2b8a3e'),
                       ('fest', res['feste Live-Config']['unseen']['net_r'], '#c92a2a'),
                       ('Monats-Kurve', res['Monats-Kurve (Teil 1)']['unseen']['net_r'], '#1f5fbf')):
        ax.axvline(v, color=c, lw=2.2, label=f'{name}: {v:+.1f} R')
    ax.set_title('Ungesehen: Netto-R'); ax.legend(); ax.grid(alpha=.3)
    fig.suptitle(f'fibot {coin} {tf} - Regler', fontsize=14)
    fig.tight_layout(); fig.savefig(out / 'ergebnis_regler.png', dpi=100); plt.close(fig)

    summary = {'created_at': datetime.now().isoformat(), 'coin': coin, 'tf': tf, 'combos': eng.ncombo,
               'chosen_W': W, 'scan': scan, 'results': res, 'placebo_unseen_r': placebo.tolist(),
               'share_days_with_change': changes / len(combos),
               'today_params': {key: float(eng.pv[combos[days[-1]], k]) for k, key in enumerate(PARAMS)},
               'runtime_s': time.time() - t0}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    del cs, pv_gpu
    eng.free()
    return summary


def main():
    OUT_ROOT.mkdir(exist_ok=True)
    rng = np.random.default_rng(20261118)
    targets = [a.split('_') for a in sys.argv[1:]] or [['APT', '30m'], ['SHIB', '30m'], ['BAT', '1h'], ['DOT', '2h']]
    results = {f'{c}_{t}': analyze(c, t, rng) for c, t in targets}
    names = list(results)
    fig, ax = plt.subplots(figsize=(12, 5.5))
    x = np.arange(len(names))
    for k, (label, key, c) in enumerate((('Regler', 'Regler', '#2b8a3e'),
                                         ('Monats-Kurve', 'Monats-Kurve (Teil 1)', '#1f5fbf'),
                                         ('fest', 'feste Live-Config', '#c92a2a'))):
        ax.bar(x + (k - 1) * .25, [results[n]['results'][key]['unseen']['net_r'] for n in names], .25, color=c, label=label)
    ax.scatter(x - .25, [np.median(results[n]['placebo_unseen_r']) for n in names], marker='_', s=600,
               color='k', zorder=3, label='veralteter Regler (Median)')
    ax.set_xticks(x, [n.replace('_', ' ') for n in names]); ax.axhline(0, color='k', lw=.8)
    ax.set_title('Ungesehen (05/2026 - 11/2026): Netto-R'); ax.legend(); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(OUT_ROOT / 'uebersicht_regler.png', dpi=110); plt.close(fig)


if __name__ == '__main__':
    main()
