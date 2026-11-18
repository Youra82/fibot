"""Teil 7: Langsame Anpassung weniger Parameter -- Gruppen x Gedaechtnis x Regel im Walk-forward.

Regeln siehe README.md, Abschnitt "Teil 7" (vorab festgelegt).
"""

from datetime import datetime
from itertools import product
import json
from pathlib import Path
import time

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from engine import PARAMS, Engine, enc, read_cache, setup_from_config
from run import LABELS, UNSEEN_START, Stitcher, metrics

HERE = Path(__file__).resolve().parent
OUT = HERE / 'ergebnisse_langsam'
COINS = [('APT', '30m'), ('SHIB', '30m'), ('BAT', '1h'), ('DOT', '2h')]
WARMUP = 12
GROUPS = {
    'Zone': ('fib_lo', 'fib_hi', 'zone_tol_atr'),
    'Stop': ('fib_sl', 'sl_buf_atr'),
    'Ziel/Filter': ('min_rr', 'max_age_mult'),
    'Zone+Stop': ('fib_lo', 'fib_hi', 'zone_tol_atr', 'fib_sl', 'sl_buf_atr'),
    'Zone+Stop+Ziel': ('fib_lo', 'fib_hi', 'zone_tol_atr', 'fib_sl', 'sl_buf_atr', 'min_rr', 'max_age_mult'),
    'alle 11': tuple(PARAMS),
}
MEMORY = {'alles': None, '24 M': 24, '12 M': 12, 'HWZ 12 M': 'decay'}
RULES = {'max R (>=10 Tr)': ('sum', 10), 'max R/Trade (>=20 Tr)': ('mean', 20)}


def weights(m, memory):
    w = np.zeros(m)
    if memory is None:
        w[:] = 1
    elif memory == 'decay':
        w[:] = 0.5 ** ((m - 1 - np.arange(m)) / 12)
    else:
        w[max(0, m - memory):] = 1
    return w


def choose(msum, mcnt, cand, live, m, memory, rule):
    w = weights(m, memory)
    r = msum[cand, :m] @ w
    n = mcnt[cand, :m] @ w
    kind, min_n = rule
    ok = n >= min_n
    if not ok.any():
        return live
    score = r if kind == 'sum' else r / np.maximum(n, 1e-9)
    return int(cand[int(np.argmax(np.where(ok, score, -np.inf)))])


def run_coin(coin, tf):
    setup = setup_from_config(coin, tf)
    df = read_cache(coin, tf)
    periods = df.index.tz_convert(None).to_period('M')
    dev_start = (df.index[0].tz_convert(None) + pd.Timedelta(days=60)).to_period('M') + 1
    months = pd.period_range(dev_start, periods.max(), freq='M')
    pos = {p: k for k, p in enumerate(months)}
    mob = np.array([pos.get(p, -1) for p in periods], dtype=np.int64)
    nm, nd = len(months), pos[UNSEEN_START]
    wf_all, wf_dev, unseen = list(range(WARMUP, nm)), list(range(WARMUP, nd)), list(range(nd, nm))
    eng = Engine(setup, df, mob, nm, log=lambda *a: None)
    st = Stitcher(eng, mob)
    live = eng.combo_index(setup.live)
    live_enc = np.array([enc(setup.live[k]) for k in PARAMS])
    rows, picks = [], {}
    fixed = st.run({m: live for m in wf_all})
    rows.append({'coin': setup.name, 'variante': 'feste Live-Config', 'gruppe': '-', 'gedaechtnis': '-', 'regel': '-',
                 'wf_dev': metrics(fixed, wf_dev)['net_r'], 'unseen': metrics(fixed, unseen)['net_r'],
                 'wf_all': metrics(fixed, wf_all)['net_r'], 'trades': len(fixed),
                 'dd': metrics(fixed, wf_all)['max_dd_pct']})
    for (g, keys), (mname, mem), (rname, rule) in product(GROUPS.items(), MEMORY.items(), RULES.items()):
        other = [i for i, k in enumerate(PARAMS) if k not in keys]
        cand = np.flatnonzero(np.all(np.isclose(eng.pv[:, other], live_enc[other]), axis=1)) if other \
            else np.arange(eng.ncombo)
        cpm = {m: choose(eng.msum, eng.mcnt, cand, live, m, mem, rule) for m in wf_all}
        tr = st.run(cpm)
        name = f'{g} | {mname} | {rname}'
        picks[name] = cpm
        mt = metrics(tr, wf_all)
        rows.append({'coin': setup.name, 'variante': name, 'gruppe': g, 'gedaechtnis': mname, 'regel': rname,
                     'wf_dev': metrics(tr, wf_dev)['net_r'], 'unseen': metrics(tr, unseen)['net_r'],
                     'wf_all': mt['net_r'], 'trades': mt['trades'], 'dd': mt['max_dd_pct']})
    print(f'{setup.name}: {len(rows) - 1} Varianten gerechnet', flush=True)
    info = {'eng': eng, 'picks': picks, 'months': months, 'nd': nd, 'st': st, 'df': df, 'live': live,
            'wf_all': wf_all, 'setup': setup}
    return rows, info


def main():
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    all_rows, infos = [], {}
    for coin, tf in COINS:
        rows, info = run_coin(coin, tf)
        all_rows += rows
        infos[f'{coin}_{tf}'] = info
    tab = pd.DataFrame(all_rows)
    tab.to_csv(OUT / 'alle_varianten.csv', index=False, float_format='%.2f')
    piv = tab.pivot_table(index='variante', columns='coin', values=['wf_dev', 'unseen', 'wf_all'], aggfunc='first')
    summ = pd.DataFrame({'wf_dev_summe': piv['wf_dev'].sum(1), 'unseen_summe': piv['unseen'].sum(1),
                         'wf_all_summe': piv['wf_all'].sum(1),
                         'coins_wf_dev_pos': (piv['wf_dev'] > 0).sum(1)})
    for c in piv['unseen'].columns:
        summ[f'unseen_{c}'] = piv['unseen'][c]
        summ[f'wf_dev_{c}'] = piv['wf_dev'][c]
    summ = summ.sort_values('wf_dev_summe', ascending=False)
    pd.set_option('display.width', 250); pd.set_option('display.max_rows', 60)
    show = summ[['wf_dev_summe', 'coins_wf_dev_pos', 'unseen_summe', 'wf_all_summe']]
    print(show.head(15).to_string(float_format=lambda v: f'{v:+.1f}'))
    fixed = summ.loc['feste Live-Config']
    base = summ.loc['Zone | alles | max R (>=10 Tr)']
    cands = summ.drop(index='feste Live-Config')
    chosen = cands.index[0]
    ch = summ.loc[chosen]
    coins = list(piv['unseen'].columns)
    better = sum(ch[f'unseen_{c}'] >= fixed[f'unseen_{c}'] for c in coins)
    passed = ch['unseen_summe'] > fixed['unseen_summe'] and better >= 3
    n_beat_base = int((cands['wf_dev_summe'] > base['wf_dev_summe']).sum())
    n_beat_fixed_unseen = int((cands['unseen_summe'] > fixed['unseen_summe']).sum())
    print(f'\nGewaehlt (nur nach WF vor 05/2026): {chosen}')
    print(f"  WF vor 05/2026 Summe {ch['wf_dev_summe']:+.1f} | ungesehen Summe {ch['unseen_summe']:+.1f} "
          f"vs fest {fixed['unseen_summe']:+.1f} | Coins >= fest ungesehen {better}/4 -> "
          f"{'BESTANDEN' if passed else 'nicht bestanden'}")
    print(f"  {n_beat_base}/48 Varianten schlagen die Zonen-Neuwahl vor 05/2026; "
          f"{n_beat_fixed_unseen}/48 schlagen fest ungesehen (Summe)")
    print(f"  Mittel nach Gruppe (WF vor 05/2026 Summe):")
    grp = tab[tab['gruppe'] != '-'].groupby(['gruppe'])['wf_dev'].sum() / 8
    print((grp.sort_values(ascending=False)).to_string(float_format=lambda v: f'{v:+.1f}'))
    mem = tab[tab['gruppe'] != '-'].groupby(['gedaechtnis'])['wf_dev'].sum() / 12
    print(f"  Mittel nach Gedaechtnis:\n{mem.sort_values(ascending=False).to_string(float_format=lambda v: f'{v:+.1f}')}")

    # Grafiken
    fig, axes = plt.subplots(1, 2, figsize=(18, 7))
    ax = axes[0]
    xs = cands['wf_dev_summe'].to_numpy(); ys = cands['unseen_summe'].to_numpy()
    groups = [v.split(' | ')[0] for v in cands.index]
    cols = dict(zip(GROUPS, ('#2b8a3e', '#d9480f', '#7048e8', '#1f5fbf', '#e64980', '#868e96')))
    for g in GROUPS:
        sel = [i for i, gg in enumerate(groups) if gg == g]
        ax.scatter(xs[sel], ys[sel], s=40, color=cols[g], label=g)
    ax.scatter([fixed['wf_dev_summe']], [fixed['unseen_summe']], marker='*', s=300, color='#c92a2a', label='fest (in-sample)')
    ax.scatter([ch['wf_dev_summe']], [ch['unseen_summe']], marker='o', s=260, facecolors='none', edgecolors='k', lw=2,
               label='gewaehlt')
    ax.axhline(fixed['unseen_summe'], color='#c92a2a', ls=':', lw=1); ax.axvline(0, color='k', lw=.8)
    ax.set_xlabel('Walk-forward vor 05/2026, Summe 4 Coins (R)'); ax.set_ylabel('ungesehen ab 05/2026, Summe (R)')
    ax.set_title('48 Varianten: Entwicklung vs. ungesehen'); ax.legend(fontsize=9); ax.grid(alpha=.3)
    ax = axes[1]
    for name, c in ((chosen, '#2b8a3e'), ('feste Live-Config', '#c92a2a'), ('Zone | alles | max R (>=10 Tr)', '#1f5fbf')):
        tot = []
        for n, info in infos.items():
            tr = info['st'].run({m: info['live'] for m in info['wf_all']}) if name == 'feste Live-Config' \
                else info['st'].run(info['picks'][name])
            tot.append(pd.Series(tr['r'].to_numpy(), index=info['df'].index[tr['x'].to_numpy()]))
        s = pd.concat(tot).sort_index()
        ax.plot(s.index, s.cumsum(), lw=1.8, color=c, label=name)
    ax.axvline(pd.Timestamp('2026-05-01', tz='UTC'), color='k', ls='--', lw=1)
    ax.set_title('Summe 4 Coins: kumuliertes Netto-R (Walk-forward)'); ax.legend(fontsize=9); ax.grid(alpha=.3)
    fig.suptitle('fibot Teil 7 - langsame Anpassung weniger Parameter', fontsize=14)
    fig.tight_layout(); fig.savefig(OUT / 'langsam_uebersicht.png', dpi=100); plt.close(fig)

    # aktuelle Werte der gewaehlten Variante je Coin
    current = {}
    for n, info in infos.items():
        cpm = info['picks'][chosen]
        last = cpm[max(cpm)]
        current[n] = {k: float(info['eng'].pv[last, i]) for i, k in enumerate(PARAMS)}
        info['eng'].free()
    summary = {'created_at': datetime.now().isoformat(), 'chosen': chosen, 'passed': bool(passed),
               'chosen_row': ch.to_dict(), 'fixed_row': fixed.to_dict(), 'zone_baseline_row': base.to_dict(),
               'n_beat_zone_baseline_dev': n_beat_base, 'n_beat_fixed_unseen': n_beat_fixed_unseen,
               'current_params_chosen': current, 'runtime_s': time.time() - t0}
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=float), encoding='utf-8')
    summ.to_csv(OUT / 'varianten_summen.csv', float_format='%.2f')
    print(f'fertig in {time.time() - t0:.0f}s')


if __name__ == '__main__':
    main()
