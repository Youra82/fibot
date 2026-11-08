# Runde 17 -- EINZIGE OOS-Pruefung aller eingefrorenen Filter (Claude 10 + Codex <= 10), festgelegt VOR dem Codex-Freeze.
# OOS = Trades mit Einstieg ab 10.05.2026 (bis Datenende 08.11.2026). Das Phasentor sieht nur Ausstiege vor dem Einstieg.
# Bestanden (je Filter): mittleres net_R > 0, >= 100 Trades, einseitiger 28-Tage-Blockbootstrap-p (Anteil Mittel <= 0)
# nach Holm ueber ALLE Kandidaten < 0,05. Berichtet zusaetzlich: stress_R, ohne Top-5-Coins, ab 15.10., Vergleich BASE.
import hashlib, importlib.util, json, sys
import numpy as np, pandas as pd

S = r'C:\Users\matol\AppData\Local\Temp\claude\730956f1654d4379\fe70ee45-49b1-4380-8ac8-e10420d5a60b\scratchpad\fib'
FULL = r'C:\Users\matol\Desktop\botprojekte\fibot\forschung\gewinner_filter_2026_11_08\features.pkl'
T0 = pd.Timestamp('2026-05-10', tz='UTC'); R15 = pd.Timestamp('2026-10-15', tz='UTC')
FROZEN = {S + r'\claude_r17\claude_filter.py': 'e7039d38782295efa7d518492adcb6edb14543d07f948118e63311d0cbc8528c',
          S + r'\claude_r17\claude_filter_phase.py': '2e586fa81058965a2908ba4adea984884d0851ee08d5902f7b930274179ccf3f'}


def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def replay(T, m):
    busy = {}; keep = []
    for i in np.flatnonzero(m):
        c = T.coin.iat[i]
        if c in busy and T.ts.iat[i] <= busy[c]: continue
        busy[c] = T.exit_ts.iat[i]; keep.append(i)
    return T.iloc[keep]


def p_boot(t, n=5000):
    d = t.groupby(t.ts.dt.floor('D')).net_R.sum()
    d = d.reindex(pd.date_range(T0.floor('D'), t.ts.max().floor('D'), freq='D'), fill_value=0)
    blocks = [g.values for _, g in d.groupby(np.arange(len(d)) // 28)]; rng = np.random.default_rng(20261108)
    # zentrierter Bootstrap: Nullhypothese Mittel 0
    x = d.values - d.values.mean()
    bx = [x[np.arange(len(d)) // 28 == k] for k in range(len(blocks))]
    sims = np.array([np.concatenate([bx[j] for j in rng.integers(0, len(bx), len(bx))]).mean() for _ in range(n)])
    return float((sims >= d.values.mean()).mean())


def stats(t):
    if not len(t): return dict(n=0)
    top = t.groupby('coin').net_R.sum().nlargest(5).index; r = t[t.ts >= R15]
    return dict(n=len(t), R=float(t.net_R.mean()), stress_R=float(t.stress_R.mean()), win=float(t.win.mean()),
                ohne_top5=float(t[~t.coin.isin(top)].net_R.mean()), sum_R=float(t.net_R.sum()), coins=int(t.coin.nunique()),
                ab_15_10=float(r.net_R.mean()) if len(r) else None, n_ab_15_10=len(r))


def holm(ps):
    order = np.argsort(ps); m = len(ps); adj = np.empty(m); run = 0.
    for k, i in enumerate(order):
        run = max(run, (m - k) * ps[i]); adj[i] = min(1., run)
    return adj


if __name__ == '__main__':
    codex_dir = sys.argv[1]
    for p, h in FROZEN.items(): assert sha(p) == h, p
    cf = codex_dir + r'\filter.py'; kj = codex_dir + r'\KANDIDATEN.json'
    pre = open(codex_dir + r'\PREREG.sha256').read()
    assert sha(cf) in pre and sha(kj) in pre, 'Codex-Freeze verletzt'
    T = pd.read_pickle(FULL).sort_values('ts').reset_index(drop=True)
    T = T.drop(columns=['per', 'selected'])
    btc = pd.read_csv(S + r'\gesperrt2\daten_voll_BTC_1d.csv')
    E = T[T.eligible].reset_index(drop=True)
    masks = {'BASE': np.ones(len(E), bool)}
    CF = load(S + r'\claude_r17\claude_filter.py', 'cf'); masks.update(CF.masks(E, btc))
    CP = load(S + r'\claude_r17\claude_filter_phase.py', 'cp'); idx, mp = CP.masks_phase(E); masks.update(mp)
    CX = load(cf, 'cx'); mx = CX.masks(E, btc); masks.update({f'CODEX_{k}': np.asarray(v, bool) & E.eligible.to_numpy() for k, v in mx.items()})
    res = {}
    for k, m in masks.items():
        t = replay(E, m); o = t[t.ts >= T0]
        res[k] = stats(o); res[k]['p'] = p_boot(o) if len(o) >= 20 else 1.
    names = [k for k in res if k != 'BASE']; adj = holm(np.array([res[k]['p'] for k in names]))
    for k, a in zip(names, adj):
        res[k]['p_holm'] = float(a); r = res[k]
        r['bestanden'] = bool(r.get('n', 0) >= 100 and r.get('R', -1) > 0 and a < .05)
    json.dump(res, open(S + r'\claude_r17\oos_ergebnis_r17.json', 'w'), indent=1)
    print(pd.DataFrame(res).T[['n', 'R', 'stress_R', 'ohne_top5', 'ab_15_10', 'n_ab_15_10', 'coins', 'p', 'p_holm', 'bestanden']].to_string())
