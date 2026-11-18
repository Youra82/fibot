"""Teil 5: Uebergeordneter Zeitrahmen (Tageskerzen) regelt die Fib-Zone, monatlicher Walk-forward.

Regeln siehe README.md, Abschnitt "Teil 5" (vorab festgelegt).
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
from marktlage import Runner
from run import LABELS, UNSEEN_START, metrics

HERE = Path(__file__).resolve().parent
OUT_ROOT = HERE / 'ergebnisse_htf'
ZONE = ('fib_lo', 'fib_hi', 'zone_tol_atr')
STATE_NAMES = ('nah am Extrem (stark)', 'mittel', 'weit weg (schwach)')
MIN_TRADES = 10
WARMUP_MONTHS = 6
N_PLACEBO = 20


def htf_states(coin, df):
    d = read_cache(coin, '1d')
    hi90 = d['high'].rolling(90).max()
    lo90 = d['low'].rolling(90).min()
    near_long = (d['close'] / hi90 - 1).rolling(365, min_periods=120).rank(pct=True)
    near_short = (-(d['close'] / lo90 - 1)).rolling(365, min_periods=120).rank(pct=True)
    known = d.index + pd.Timedelta(days=1)
    pos = known.searchsorted(df.index, side='right') - 1

    def to_state(series):
        v = np.full(len(df), np.nan)
        ok = pos >= 0
        v[ok] = series.to_numpy()[pos[ok]]
        s = np.full(len(df), -1, dtype=np.int64)
        f = np.isfinite(v)
        s[f] = np.where(v[f] > 2 / 3, 0, np.where(v[f] > 1 / 3, 1, 2))
        return s
    return to_state(near_long), to_state(near_short)


def select(score_cum, cnt_cum, cand, live):
    eligible = cnt_cum >= MIN_TRADES
    if not eligible.any():
        return live
    s = np.where(eligible, score_cum, -np.inf)
    return int(cand[int(np.argmax(s))])


def evaluate(eng, runner, cand, live, stL, stS, mob, nmonth, first_eval):
    """Walk-forward mit HTF-Lage. Gibt Trades und Wahl je Monat/Lage zurueck."""
    labL = np.where((stL >= 0) & (mob >= 0), stL * nmonth + mob, -1)
    labS = np.where((stS >= 0) & (mob >= 0), stS * nmonth + mob, -1)
    ssum, scnt = eng.aggregate(labL, 3 * nmonth, labS)
    ssum = ssum[cand].reshape(len(cand), 3, nmonth)
    scnt = scnt[cand].reshape(len(cand), 3, nmonth)
    choice = {}
    for m in range(first_eval, nmonth):
        choice[m] = {s: select(ssum[:, s, :m].sum(1), scnt[:, s, :m].sum(1), cand, live) for s in range(3)}
    rows = []
    for m, per_state in choice.items():
        for s in (-1, 0, 1, 2):
            combo = live if s == -1 else per_state[s]
            ev = runner.events(combo)
            ev = ev[ev['m'] == m]
            if ev.empty:
                continue
            idx = ev['i'].to_numpy()
            st = np.where(ev['d'].to_numpy() == 1, stL[idx], stS[idx])
            rows.append(ev[st == s])
    ev = pd.concat(rows).sort_values('i', kind='stable')
    return busy(ev), choice


def busy(ev):
    last, rows = -1, []
    for i, x, r, m in ev[['i', 'x', 'r', 'm']].itertuples(index=False):
        if i <= last or x < 0 or m < 0:
            continue
        last = x
        rows.append((int(i), int(x), float(r), int(m)))
    return pd.DataFrame(rows, columns=['i', 'x', 'r', 'm'])


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
    first_eval = WARMUP_MONTHS
    wf_dev, unseen, wf_all = list(range(first_eval, nd)), list(range(nd, nm)), list(range(first_eval, nm))
    print(f'== {setup.name}: Walk-forward {months[first_eval]} - {months[-1]}', flush=True)

    eng = Engine(setup, df, mob, nm, log=lambda *a: None)
    live_enc = np.array([enc(setup.live[k]) for k in PARAMS])
    other = [k for k, key in enumerate(PARAMS) if key not in ZONE]
    cand = np.flatnonzero(np.all(np.isclose(eng.pv[:, other], live_enc[other]), axis=1))
    live = eng.combo_index(setup.live)
    runner = Runner(eng, mob)
    stL, stS = htf_states(coin, df)

    tr_htf, choice = evaluate(eng, runner, cand, live, stL, stS, mob, nm, first_eval)

    # ohne Lage: gleiche monatliche Neuwahl der Zone, nur eine Lage
    msum, mcnt = eng.msum[cand], eng.mcnt[cand]
    rows = []
    for m in range(first_eval, nm):
        ev = runner.events(select(msum[:, :m].sum(1), mcnt[:, :m].sum(1), cand, live))
        rows.append(ev[ev['m'] == m])
    tr_plain = busy(pd.concat(rows).sort_values('i', kind='stable'))
    ev_live = runner.events(live)
    tr_fixed = busy(ev_live[ev_live['m'] >= first_eval])

    bar_h = pd.Timedelta(tf) / pd.Timedelta('1h')
    placebo = []
    for _ in range(N_PLACEBO):
        sh = int(rng.integers(int(60 * 24 / bar_h), int(300 * 24 / bar_h)))
        tr_p, _ = evaluate(eng, runner, cand, live, np.roll(stL, sh), np.roll(stS, sh), mob, nm, first_eval)
        placebo.append(metrics(tr_p, wf_all)['net_r'])
    placebo = np.array(placebo)

    res = {}
    for name, tr in (('HTF-Regler', tr_htf), ('ohne Lage', tr_plain), ('feste Live-Config', tr_fixed)):
        res[name] = {'wf_gesamt': metrics(tr, wf_all), 'wf_entwicklung': metrics(tr, wf_dev),
                     'ungesehen': metrics(tr, unseen)}
    h, p, f = (res[n] for n in ('HTF-Regler', 'ohne Lage', 'feste Live-Config'))
    print(f"  WF gesamt R: HTF {h['wf_gesamt']['net_r']:+6.1f} | ohne Lage {p['wf_gesamt']['net_r']:+6.1f} | "
          f"fest {f['wf_gesamt']['net_r']:+6.1f} (in-sample) | Gegentest Median {np.median(placebo):+6.1f} "
          f"(Rang HTF {np.mean(placebo < h['wf_gesamt']['net_r']):.0%})", flush=True)
    print(f"  ungesehen R: HTF {h['ungesehen']['net_r']:+5.1f} ({h['ungesehen']['trades']} Tr) | ohne Lage "
          f"{p['ungesehen']['net_r']:+5.1f} | fest {f['ungesehen']['net_r']:+5.1f} | WF-Entw. HTF "
          f"{h['wf_entwicklung']['net_r']:+.1f} vs ohne Lage {p['wf_entwicklung']['net_r']:+.1f}", flush=True)

    # Grafiken
    dates = months.to_timestamp()
    fig, axes = plt.subplots(2, 2, figsize=(17, 11))
    colors = ('#2b8a3e', '#f08c00', '#c92a2a')
    for ax, key in zip(axes.flat[:3], ZONE):
        k = PARAMS.index(key)
        for s in range(3):
            ax.step(dates[first_eval:], [eng.pv[choice[m][s], k] for m in range(first_eval, nm)], where='post',
                    color=colors[s], lw=1.8, label=STATE_NAMES[s])
        ax.axhline(enc(setup.live[key]), color='k', ls=':', lw=1.2, label='Live-Config')
        ax.axvspan(dates[nd], dates[-1] + pd.offsets.MonthEnd(1), color='#f4d9a6', alpha=.5, lw=0)
        ax.set_title(f'{LABELS[key]} je HTF-Lage (nur aus Vergangenheit gewaehlt)'); ax.grid(alpha=.3)
    axes.flat[0].legend(fontsize=9)
    ax = axes.flat[3]
    for name, tr, c in (('HTF-Regler', tr_htf, '#2b8a3e'), ('ohne Lage', tr_plain, '#1f5fbf'),
                        ('feste Live-Config (in-sample bis 04/2026)', tr_fixed, '#c92a2a')):
        eqc = np.cumprod(1 + 0.01 * tr['r'].to_numpy())
        ax.plot(df.index[tr['x'].to_numpy()], (eqc - 1) * 100, color=c, lw=1.6, label=name)
    ax.axvline(dates[nd], color='k', ls='--', lw=1)
    ax.set_title(f'Walk-forward Kontoverlauf % (1 % Risiko); Gegentest-Median {np.median(placebo):+.1f} R')
    ax.legend(fontsize=9); ax.grid(alpha=.3)
    fig.suptitle(f'fibot {coin} {tf} - uebergeordneter Zeitrahmen regelt die Fib-Zone', fontsize=15)
    fig.tight_layout(); fig.savefig(out / 'htf_ergebnis.png', dpi=100); plt.close(fig)

    summary = {'created_at': datetime.now().isoformat(), 'coin': coin, 'tf': tf, 'zone_candidates': len(cand),
               'results': res, 'placebo_wf_total_r': placebo.tolist(),
               'state_share': {STATE_NAMES[s]: float(np.mean(stL[mob >= 0] == s)) for s in range(3)},
               'current_choice': {STATE_NAMES[s]: {key: float(eng.pv[choice[nm - 1][s], PARAMS.index(key)])
                                                    for key in ZONE} for s in range(3)},
               'runtime_s': time.time() - t0}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    eng.free()
    return summary


def main():
    OUT_ROOT.mkdir(exist_ok=True)
    rng = np.random.default_rng(20261118)
    targets = [a.split('_') for a in sys.argv[1:]] or [['APT', '30m'], ['SHIB', '30m'], ['BAT', '1h'], ['DOT', '2h']]
    results = {f'{c}_{t}': analyze(c, t, rng) for c, t in targets}
    names = list(results)
    fig, axes = plt.subplots(1, 2, figsize=(16, 5.5))
    x = np.arange(len(names))
    for ax, part, title in ((axes[0], 'wf_gesamt', 'Walk-forward gesamt'), (axes[1], 'ungesehen', 'ungesehen ab 05/2026')):
        for k, (key, c) in enumerate((('HTF-Regler', '#2b8a3e'), ('ohne Lage', '#1f5fbf'), ('feste Live-Config', '#c92a2a'))):
            ax.bar(x + (k - 1) * .25, [results[n]['results'][key][part]['net_r'] for n in names], .25, color=c, label=key)
        if part == 'wf_gesamt':
            ax.scatter(x - .25, [np.median(results[n]['placebo_wf_total_r']) for n in names], marker='_', s=600,
                       color='k', zorder=3, label='Gegentest-Median')
        ax.set_xticks(x, [n.replace('_', ' ') for n in names]); ax.axhline(0, color='k', lw=.8)
        ax.set_title(f'{title}: Netto-R'); ax.legend(fontsize=9); ax.grid(alpha=.3)
    fig.suptitle('fibot: HTF-Lage regelt Fib-Zone (feste Config bis 04/2026 in-sample)', fontsize=13)
    fig.tight_layout(); fig.savefig(OUT_ROOT / 'uebersicht_htf.png', dpi=110); plt.close(fig)


if __name__ == '__main__':
    main()
