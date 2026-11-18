"""Teil 6: Monats-Kurve aus Teil 1 im echten Walk-forward (jeden Monat nur mit Vergangenheit neu angepasst).

Regeln siehe README.md, Abschnitt "Teil 6" (vorab festgelegt).
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

from engine import PARAMS, Engine, enc, read_cache, setup_from_config
from htf import ZONE, select
from run import LABELS, TOP_FRAC, UNSEEN_START, Stitcher, local_linear, metrics, snap

HERE = Path(__file__).resolve().parent
OUT_ROOT = HERE / 'ergebnisse_wf_kurve'
H_MAIN, H_SENS = 3, (1.5, 6)
WARMUP = 12
N_RANDOM = 20


def plan(eng, msum, K, first_eval, nm, h):
    """{Monat: Kombi} fuer Kurve (fortgesetzt) und flach, nur mit Daten < m."""
    out_curve, out_flat, values = {}, {}, {}
    for m in range(first_eval, nm):
        tiebreak = msum[:, :m].sum(1)
        raw = np.zeros((m, len(PARAMS)))
        for t in range(m):
            score = msum[:, max(0, t - 1):min(m, t + 2)].sum(1) + 1e-6 * tiebreak
            top = np.argpartition(-score, K)[:K]
            raw[t] = eng.pv[top].mean(0)
        t_obs = np.arange(m, dtype=float)
        nxt, flat = np.zeros(len(PARAMS)), np.zeros(len(PARAMS))
        for k in range(len(PARAMS)):
            level, slope = local_linear(t_obs, raw[:, k], m - 1.0, h)
            nxt[k], flat[k] = level + slope, level
        sn = np.array([snap(np.array([nxt[k]]), eng.setup.grid[key])[0] for k, key in enumerate(PARAMS)])
        sf = np.array([snap(np.array([flat[k]]), eng.setup.grid[key])[0] for k, key in enumerate(PARAMS)])
        out_curve[m], out_flat[m], values[m] = eng.combo_from_values(sn), eng.combo_from_values(sf), sn
    return out_curve, out_flat, values


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
    nm, nd = len(months), pos[UNSEEN_START]
    first_eval = WARMUP
    wf_all, wf_dev, unseen = list(range(first_eval, nm)), list(range(first_eval, nd)), list(range(nd, nm))
    print(f'== {setup.name}: Walk-forward {months[first_eval]} - {months[-1]}', flush=True)
    eng = Engine(setup, df, mob, nm, log=lambda *a: None)
    K = max(1, int(eng.ncombo * TOP_FRAC))
    msum = eng.msum
    st = Stitcher(eng, mob)
    live = eng.combo_index(setup.live)

    res, trades = {}, {}
    curve_c, flat_c, values = plan(eng, msum, K, first_eval, nm, H_MAIN)
    trades['Kurve h=3'] = st.run(curve_c)
    trades['Kurve flach h=3'] = st.run(flat_c)
    for h in H_SENS:
        c, _, _ = plan(eng, msum, K, first_eval, nm, h)
        trades[f'Kurve h={h}'] = st.run(c)
    trades['feste Live-Config'] = st.run({m: live for m in range(first_eval, nm)})
    live_enc = np.array([enc(setup.live[key]) for key in PARAMS])
    other = [i for i, key in enumerate(PARAMS) if key not in ZONE]
    cand = np.flatnonzero(np.all(np.isclose(eng.pv[:, other], live_enc[other]), axis=1))
    trades['ohne Lage'] = st.run({m: select(msum[cand, :m].sum(1), eng.mcnt[cand, :m].sum(1), cand, live)
                                  for m in range(first_eval, nm)})
    random_r = []
    for _ in range(N_RANDOM):
        cpm = {}
        for m in range(first_eval, nm):
            pick = rng.choice(eng.ncombo, K, replace=False)
            v = eng.pv[pick].mean(0)
            cpm[m] = eng.combo_from_values(np.array(
                [snap(np.array([v[k]]), setup.grid[key])[0] for k, key in enumerate(PARAMS)]))
        random_r.append(metrics(st.run(cpm), wf_all)['net_r'])
    random_r = np.array(random_r)
    for name, tr in trades.items():
        res[name] = {'wf_gesamt': metrics(tr, wf_all), 'wf_entwicklung': metrics(tr, wf_dev),
                     'ungesehen': metrics(tr, unseen)}
    plain = res['ohne Lage']
    k = res['Kurve h=3']
    print(f"  Kurve h=3: WF gesamt {k['wf_gesamt']['net_r']:+6.1f} R ({k['wf_gesamt']['trades']} Tr, DD "
          f"{k['wf_gesamt']['max_dd_pct']:.1f}%) | vor 05/2026 {k['wf_entwicklung']['net_r']:+6.1f} | ungesehen "
          f"{k['ungesehen']['net_r']:+5.1f}", flush=True)
    print(f"  Vergleich WF gesamt: flach {res['Kurve flach h=3']['wf_gesamt']['net_r']:+.1f} | h=1.5 "
          f"{res['Kurve h=1.5']['wf_gesamt']['net_r']:+.1f} | h=6 {res['Kurve h=6']['wf_gesamt']['net_r']:+.1f} | "
          f"ohne Lage {plain['wf_gesamt']['net_r']:+.1f} | "
          f"Zufall Median {np.median(random_r):+.1f} (Rang {np.mean(random_r < k['wf_gesamt']['net_r']):.0%}) | "
          f"fest {res['feste Live-Config']['wf_gesamt']['net_r']:+.1f}", flush=True)

    dates = months.to_timestamp()
    fig, axes = plt.subplots(4, 3, figsize=(17, 15), sharex=True)
    ms = sorted(values)
    for ax, key in zip(axes.flat, PARAMS):
        kk = PARAMS.index(key)
        ax.step(dates[ms], [values[m][kk] for m in ms], where='post', color='#1f5fbf', lw=1.8,
                label='Wert je Monat (nur aus Vergangenheit)')
        ax.axhline(float(eng.pv[live, kk]), color='#c92a2a', ls=':', lw=1.3, label='feste Live-Config')
        ax.axvspan(dates[nd], dates[-1] + pd.offsets.MonthEnd(1), color='#f4d9a6', alpha=.5, lw=0)
        ax.set_title(LABELS[key]); ax.grid(alpha=.3)
    ax = axes.flat[-1]
    for name, c in (('Kurve h=3', '#1f5fbf'), ('Kurve flach h=3', '#7048e8'), ('feste Live-Config', '#c92a2a')):
        tr = trades[name]
        eqc = np.cumprod(1 + 0.01 * tr['r'].to_numpy())
        ax.plot(df.index[tr['x'].to_numpy()], (eqc - 1) * 100, color=c, lw=1.5, label=name)
    ax.axvline(dates[nd], color='k', ls='--', lw=1); ax.legend(fontsize=8); ax.grid(alpha=.3)
    ax.set_title('Walk-forward Kontoverlauf % (1 % Risiko)')
    axes.flat[0].legend(fontsize=8)
    fig.suptitle(f'fibot {coin} {tf} - Monats-Kurve im Walk-forward (jeden Monat nur mit Vergangenheit)', fontsize=14)
    fig.tight_layout(); fig.savefig(out / 'wf_kurve.png', dpi=100); plt.close(fig)

    summary = {'created_at': datetime.now().isoformat(), 'coin': coin, 'tf': tf, 'first_eval': str(months[first_eval]),
               'results': res, 'random_wf_total_r': random_r.tolist(), 
               'next_month_params': {key: float(values[nm - 1][k]) for k, key in enumerate(PARAMS)},
               'runtime_s': time.time() - t0}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    eng.free()
    return summary


def main():
    OUT_ROOT.mkdir(exist_ok=True)
    rng = np.random.default_rng(20261118)
    targets = [a.split('_') for a in sys.argv[1:]] or [['APT', '30m'], ['SHIB', '30m'], ['BAT', '1h'], ['DOT', '2h']]
    for c, t in targets:
        analyze(c, t, rng)


if __name__ == '__main__':
    main()
