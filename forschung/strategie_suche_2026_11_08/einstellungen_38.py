# Nach PREREG_EINSTELLUNGEN_38.md
import os, sys, glob, json, itertools
from multiprocessing import Pool
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); FIB = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(FIB, 'src'))
import logging; logging.disable(logging.WARNING)
from fibot.strategy.confluence_logic import plan_both, _atr, strategy_params
from fibot.strategy import trend_filter as TFM
MAK, TAK, SLP = 0.0002, 0.0006, 0.0002
SETTINGS = list(itertools.product(('kanal', '1R', '2R'), (False, True), (False, True)))

def rd(p):
    d = pd.read_csv(p); d.index = pd.to_datetime(d[d.columns[0]], utc=True)
    return d[['open', 'high', 'low', 'close', 'volume']].astype(float).sort_index()[lambda x: ~x.index.duplicated()]

def job(f):
    cfg = json.load(open(f)); sym = cfg['market']['symbol'].replace('/', '-').replace(':', '-'); tf = cfg['market']['timeframe']
    df = rd(os.path.join(FIB, 'data', 'cache', f'{sym}_{tf}.csv'))
    df = df[df.index >= '2023-06-01']
    daily = rd(os.path.join(FIB, 'data', 'cache', f'{sym}_1d.csv'))
    tcfg = TFM.DEFAULTS
    htf = TFM.htf_trend(df, tf, tcfg); dtr = TFM.daily_trend(daily, tcfg)
    lo, sh = plan_both(df, cfg)
    o, h, l, c = (df[x].values for x in ('open', 'high', 'low', 'close'))
    n = len(df); out = []
    name = os.path.basename(f)[7:-9]
    for d, pl, sgn in (('long', lo, 1), ('short', sh, -1)):
        O, Hh, L, C = (o, h, l, c) if sgn == 1 else (-o, -l, -h, -c)
        atr = _atr(Hh, L, C, 14)
        fills = np.nonzero(pl['fill'][:n])[0]
        for (tgt, trend, mstop) in SETTINGS:
            free = 0
            for i in fills:
                if i < free or df.index[i] < pd.Timestamp('2024-01-01', tz='UTC'): continue
                lim, sl = sgn * pl['limit'][i], sgn * pl['sl'][i]; tpk = sgn * pl['tp'][i]
                D = lim - sl
                if D <= 0: continue
                if mstop and (D < atr[i - 1] or D < 0.01 * abs(lim)): continue
                if trend and not TFM.allowed(d, df.index[i], htf, dtr): continue
                tp = tpk if tgt == 'kanal' else lim + (1 if tgt == '1R' else 2) * D
                ep = min(lim, O[i])
                if L[i] <= sl: xp, j = sl, i
                else:
                    xp, j = None, i
                    for j in range(i + 1, min(n, i + 200)):
                        if L[j] <= sl: xp = O[j] if O[j] < sl else sl; break
                        if Hh[j] >= tp: xp = O[j] if O[j] > tp else tp; break
                    if xp is None: xp = C[j]
                xp -= SLP * abs(xp)
                ret = (xp - ep) / abs(ep) - MAK - TAK * abs(xp) / abs(ep)
                out.append({'cfg': name, 'set': f'{tgt}|{"T" if trend else "-"}|{"S" if mstop else "-"}', 'dir': d,
                            'entry_ts': df.index[i], 'R': ret * abs(ep) / (ep - sl)})
                free = j + 1
    return out

def boot_p(x, block=3, n=9999, seed=20261109):
    x = np.asarray(x, float); m = len(x); obs = x.mean(); cen = x - obs
    rng = np.random.default_rng(seed); nb = int(np.ceil(m / block)); cnt = 0
    for _ in range(n):
        s = np.concatenate([cen[np.arange(a, a + block) % m] for a in rng.integers(0, m, nb)])[:m]
        cnt += s.mean() >= obs
    return (cnt + 1) / (n + 1)

if __name__ == '__main__':
    files = sorted(glob.glob(os.path.join(FIB, 'src', 'fibot', 'strategy', 'configs', '*.json')))
    with Pool(6) as p: parts = p.map(job, files)
    T = pd.DataFrame([r for x in parts for r in x]); T.to_pickle(os.path.join(HERE, 'trades_einstellungen_38.pkl'))
    FIX = 'kanal|T|-'
    print('=== Teil 1: Rueckblick 15.10.-08.11.2026 (In-Sample) ===')
    late = T[T.entry_ts >= '2026-10-15']
    print(late.groupby('set').R.agg(['size', 'mean', 'sum']).sort_values('sum', ascending=False).round(3).to_string())
    best = late.groupby(['cfg', 'set']).R.sum().groupby('cfg').max()
    print(f'Summe R bei je Config bester Einstellung (In-Sample): {best.sum():+.1f} R ueber {late.cfg.nunique()} Configs')
    print('\n=== Teil 2: Walk-Forward ===')
    rows = []
    for M in pd.date_range('2024-07-01', '2026-11-01', freq='MS', tz='UTC'):
        M1 = min(M + pd.offsets.MonthBegin(1), pd.Timestamp('2026-11-09', tz='UTC'))
        hist = T[(T.entry_ts >= M - pd.DateOffset(months=3)) & (T.entry_ts < M)]
        g = hist.groupby(['cfg', 'set']).R.agg(['sum', 'size']); g = g[g['size'] >= 3]
        choice = {}
        for cfg_, gg in g.groupby(level=0):
            b = gg['sum'].idxmax()
            if gg.loc[b, 'sum'] > 0: choice[cfg_] = b[1]
        cur = T[(T.entry_ts >= M) & (T.entry_ts < M1)]
        ad = cur[[choice.get(c_) == s_ for c_, s_ in zip(cur.cfg, cur.set)]]
        fx = cur[cur.set == FIX]
        rows.append({'M': M.strftime('%Y-%m'), 'n_ad': len(ad), 'R_ad': ad.R.mean() if len(ad) else 0.0,
                     'n_fix': len(fx), 'R_fix': fx.R.mean() if len(fx) else 0.0, 'configs_ad': len(choice)})
    Mo = pd.DataFrame(rows); print(Mo.round(3).to_string())
    p1, p2 = boot_p(Mo.R_ad), boot_p(Mo.R_ad - Mo.R_fix)
    print(f"\nAdaptiv R/Trade (Monatsmittel) {Mo.R_ad.mean():+.3f} p {p1:.4f} | fest {Mo.R_fix.mean():+.3f} | Differenz {(Mo.R_ad-Mo.R_fix).mean():+.3f} p {p2:.4f}")
    for lab, a, b in (('vor OOS-Auswahl 2024-07..2026-03', '2024-07', '2026-03'), ('Auswahlzeitraum 2026-04..2026-10', '2026-04', '2026-10')):
        s = Mo[(Mo.M >= a) & (Mo.M <= b)]
        print(f"  {lab}: adaptiv {s.R_ad.mean():+.3f} (Trades {s.n_ad.sum()}) | fest {s.R_fix.mean():+.3f} (Trades {s.n_fix.sum()})")
    # 15.10.-08.11. mit Auswahl auf Daten bis 15.10.
    M = pd.Timestamp('2026-10-15', tz='UTC')
    hist = T[(T.entry_ts >= M - pd.DateOffset(months=3)) & (T.entry_ts < M)]
    g = hist.groupby(['cfg', 'set']).R.agg(['sum', 'size']); g = g[g['size'] >= 3]
    choice = {c_: gg['sum'].idxmax()[1] for c_, gg in g.groupby(level=0) if gg['sum'].max() > 0}
    ad = late[[choice.get(c_) == s_ for c_, s_ in zip(late.cfg, late.set)]]; fx = late[late.set == FIX]
    print(f"  15.10.-08.11. (Wahl mit Daten bis 15.10.): adaptiv {ad.R.mean():+.3f} R/Trade ({len(ad)} Trades, Summe {ad.R.sum():+.1f}) | fest {fx.R.mean():+.3f} ({len(fx)}, Summe {fx.R.sum():+.1f})")
    print(f"  gewaehlte Einstellungen: {pd.Series(choice).value_counts().to_dict()}")
    ok = Mo.R_ad.mean() > 0 and p1 <= 0.05 and (Mo.R_ad - Mo.R_fix).mean() > 0 and p2 <= 0.05
    print('ERGEBNIS adaptives Einstellen:', 'BESTANDEN' if ok else 'nicht bestanden')
