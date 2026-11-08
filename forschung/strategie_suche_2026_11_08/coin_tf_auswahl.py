# Nach PREREG_COIN_TF_AUSWAHL.md
import os, sys
from multiprocessing import Pool
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', '..', 'src'))
import harness as H, konfluenz_k as K
from runde3 import sim_one, leg_ret, stop_ok
from fibot.strategy.confluence_logic import _atr

def job(args):
    coin, tf = args
    p = os.path.join(H.GEO, f'{coin}-USDT-USDT_{tf}.csv')
    if not os.path.exists(p): return []
    df = H._read(p)
    if len(df) < 600: return []
    o, h, l, c, v = (df[x].values for x in ('open', 'high', 'low', 'close', 'volume'))
    out = []
    for side, (O, Hh, L, C) in ((1, (o, h, l, c)), (-1, (-o, -l, -h, -c))):
        atr = _atr(Hh, L, C, 14); free = 0
        for e in K.touch_events(O, Hh, L, C, v):
            i = e['i']
            if i < free: continue
            ep = min(e['limit'], O[i])
            if not stop_ok(e['limit'], e['sl'], atr[i - 1], ep): continue
            x, j, res = sim_one(O, Hh, L, C, i, ep, e['sl'], e['tp'], i + 1)
            ret = leg_ret(ep, x)
            out.append({'combo': f'{coin}_{tf}', 'tf': tf, 'entry_ts': df.index[i], 'exit_ts': df.index[j], 'R': ret * abs(ep) / (ep - e['sl'])})
            free = j + 1
    return out

def boot_p(x, block=3, n=9999, seed=20261109):
    x = np.asarray(x, float); m = len(x); obs = x.mean(); cen = x - obs
    rng = np.random.default_rng(seed); nb = int(np.ceil(m / block)); cnt = 0
    for _ in range(n):
        st = rng.integers(0, m, nb)
        s = np.concatenate([cen[(np.arange(a, a + block)) % m] for a in st])[:m]
        cnt += s.mean() >= obs
    return (cnt + 1) / (n + 1)

if __name__ == '__main__':
    coins = sorted({f.split('-')[0] for f in os.listdir(H.GEO) if f.endswith('_4h.csv')} - H.EXCLUDE)
    tasks = [(c, tf) for tf in ('2h', '4h', '6h') for c in coins]
    with Pool(6) as pool: parts = pool.map(job, tasks, chunksize=3)
    T = pd.DataFrame([r for p in parts for r in p]); T.to_pickle(os.path.join(HERE, 'trades_coin_tf.pkl'))
    print(len(T), 'Trades,', T.combo.nunique(), 'Kombinationen')
    rows = []
    for M in pd.date_range('2023-01-01', '2026-10-01', freq='MS', tz='UTC'):
        M1 = M + pd.offsets.MonthBegin(1)
        hist = T[(T.exit_ts >= M - pd.DateOffset(months=6)) & (T.exit_ts < M)]
        st = hist.groupby('combo').R.agg(['mean', 'size']); st = st[(st['size'] >= 5) & (st['mean'] > 0)]
        sel = set(st.sort_values('mean', ascending=False).index[:20])
        cur = T[(T.entry_ts >= M) & (T.entry_ts < M1)]
        s = cur[cur.combo.isin(sel)]
        rows.append({'M': M, 'n_sel': len(sel), 'n_tr': len(s), 'R_sel': s.R.mean() if len(s) else np.nan,
                     'R_alle': cur.R.mean() if len(cur) else np.nan})
    Mo = pd.DataFrame(rows); print(Mo.round(3).to_string())
    v = Mo.dropna(subset=['R_sel', 'R_alle'])
    d = v.R_sel - v.R_alle
    p1, p2 = boot_p(v.R_sel), boot_p(d)
    h1, h2 = v[v.M < '2025-01-01'].R_sel.mean(), v[v.M >= '2025-01-01'].R_sel.mean()
    print(f"\nMonate {len(v)} | Auswahl R/Trade (Monatsmittel) {v.R_sel.mean():+.3f} p {p1:.4f} | alle {v.R_alle.mean():+.3f} | "
          f"Differenz {d.mean():+.3f} p {p2:.4f} | Haelften {h1:+.3f} / {h2:+.3f} | Trades Auswahl gesamt {int(v.n_tr.sum())}")
    ok = v.R_sel.mean() > 0 and p1 <= 0.05 and d.mean() > 0 and p2 <= 0.05 and h1 > 0 and h2 > 0
    print('ERGEBNIS:', 'BESTANDEN' if ok else 'nicht bestanden')
    late = T[T.entry_ts >= '2026-10-15']; print('ab 15.10. alle', round(late.R.mean(), 3), len(late))
