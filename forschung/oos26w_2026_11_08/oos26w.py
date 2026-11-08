# 30 Fibo-Wick-Konfluenz-Strategien: Auswahl bis 09.05.2026, OOS 10.05.2026 - Datenende (PREREG.md).
#   python oos26w.py auswahl <DATEN>   -> laedt nur Daten < T0, schreibt auswahl.json + auswahl.sha256
#   python oos26w.py oos <DATEN>       -> prueft Freeze, rechnet OOS fuer alle Kandidaten, Bericht
import hashlib, json, os, sys
from multiprocessing import Pool
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
T_TRAIN = pd.Timestamp('2024-05-10', tz='UTC'); T0 = pd.Timestamp('2026-05-10', tz='UTC')
HALVES = [pd.Timestamp(x, tz='UTC') for x in ('2024-05-10', '2024-11-10', '2025-05-10', '2025-11-10', '2026-05-10')]
TFS = {'30m': .5, '1h': 1, '2h': 2, '4h': 4, '6h': 6}
DEPTHS = (5, 7, 9, 11); RULES = ('FIB', 'R25'); FIB = (.618, .786, 1.272, 1.618)
MAK, TAK, SLP, FUND = .0002, .0006, .0002, .0001
RISK, LEV = .15, 3.0
EXCLUDE = {'USDC', 'XAUT', 'PAXG', 'XAU', 'XAG', 'BTCDOM', 'DEFI', 'EUR', 'GBP'}


def rd(p, until=None):
    d = pd.read_csv(p); d.index = pd.to_datetime(d.iloc[:, 0], utc=True)
    d = d[['open', 'high', 'low', 'close']].astype(float).sort_index(); d = d[~d.index.duplicated(keep='last')]
    return d[d.index < until] if until is not None else d


def btc_gate(daily):
    c = daily.close; ok = ((c > c.rolling(200).mean()) & (c > c.rolling(50).mean())).astype(float)
    ok.index = ok.index + pd.Timedelta(days=1); return ok


def simulate(d, gate, h, depth, rule, start, end):
    """Ein Konto (Start 1,0). Rueckgabe: Liste Trades (entry_ts, exit_ts, ret_konto, eq_vor, eq_min, eq_nach)."""
    native = pd.date_range(d.index.min(), d.index.max(), freq=pd.Timedelta(hours=h)); d = d.reindex(native)
    o, hi_, lo_, c = (d[k].to_numpy() for k in ('open', 'high', 'low', 'close'))
    pc = np.roll(c, 1); pc[0] = np.nan
    tr = np.nanmax(np.vstack([hi_ - lo_, np.abs(hi_ - pc), np.abs(lo_ - pc)]), axis=0)
    atr = pd.Series(tr).rolling(14).mean().shift().to_numpy()
    mid = ((pd.Series(hi_).rolling(5).max() + pd.Series(lo_).rolling(5).min()) / 2).shift().to_numpy()
    H = pd.Series(hi_).rolling(42).max().shift().to_numpy(); L = pd.Series(lo_).rolling(42).min().shift().to_numpy()
    g = gate.reindex(d.index, method='ffill').to_numpy()
    band = mid * (1 - depth / 100)
    with np.errstate(invalid='ignore', divide='ignore'):
        delta = np.minimum.reduce([np.abs(H - x * (H - L) - band) for x in FIB])
        m = (g == 1) & np.isfinite(atr) & (atr > 0) & (delta <= .25 * atr) & (lo_ <= band)
        if rule == 'R25':
            unit = 10. ** (np.floor(np.log10(np.maximum(band, 1e-20))) - 1)
            m &= np.abs(band - np.round(band / unit) * unit) <= .25 * atr
    ts = d.index; ok_t = (ts >= start) & (ts < end); m &= ok_t
    m[:43] = False
    out, eq, i, n = [], 1.0, 0, len(c)
    cand = np.flatnonzero(m)
    k = 0
    while k < len(cand):
        i = cand[k]
        ep = min(o[i], band[i]) if np.isfinite(o[i]) else band[i]
        dist = max(.10 * ep, atr[i], .01 * ep); sl = ep - dist
        loss = dist / ep + MAK + TAK + SLP
        notional = min(eq * RISK / loss, eq * LEV)
        q = notional / ep
        res = None; jmin = lo_[i]; last = min(n - 1, i + 59)
        for j in range(i, last + 1):
            if not np.isfinite(lo_[j]):
                continue
            if ts[j] >= end:                          # Fensterende: zum Open schliessen (offene Position bewertet)
                xp = o[j]; fee = TAK; res = 'end'; break
            jmin = min(jmin, lo_[j])
            if lo_[j] <= sl:
                xp = (o[j] if (j > i and o[j] < sl) else sl) * (1 - SLP); fee = TAK; res = 'sl'; break
            if j > i and np.isfinite(mid[j]) and hi_[j] >= mid[j]:
                xp = max(o[j], mid[j]); fee = MAK; res = 'tp'; break
        if res is None:
            j = last; xp = c[j] * (1 - SLP) if np.isfinite(c[j]) else ep; fee = TAK; res = 'time'
        held_8h = (j - i + 1) * h / 8
        pnl = q * (xp - ep) - notional * MAK - q * xp * fee - notional * FUND * held_8h
        eq_min = eq + q * (min(jmin, sl) - ep) if res == 'sl' else eq + q * (jmin - ep)
        out.append((ts[i], ts[j], pnl / eq, eq, max(eq_min, 0.), eq + pnl))
        eq = max(eq + pnl, 0.)
        if eq <= 0:
            break
        nxt = np.searchsorted(cand, j + 1); k = nxt
    return out


def stats(trades, start, end):
    if not trades:
        return dict(ret=0., dd=0., n=0)
    eq0 = trades[0][3]; peak, dd = eq0, 0.
    for _, _, _, eqb, eqm, eqa in trades:
        peak = max(peak, eqb); dd = max(dd, 1 - eqm / peak); peak = max(peak, eqa)
    return dict(ret=trades[-1][5] / eq0 - 1, dd=dd, n=len(trades))


def job(args):
    path, tf, mode, root = args
    coin = os.path.basename(path).split('-')[0]
    until = T0 if mode == 'auswahl' else None
    d = rd(path, until); gate = btc_gate(rd(os.path.join(root, 'daten_voll_BTC_1d.csv'), until))
    if len(d) < 300:
        return []
    rows = []
    for depth in DEPTHS:
        for rule in RULES:
            key = f'{coin}|{tf}|{depth}|{rule}'
            if mode == 'auswahl':
                if d.index.min() > T_TRAIN - pd.Timedelta(days=20):
                    continue                                  # muss das ganze Training abdecken
                tr = simulate(d, gate, TFS[tf], depth, rule, T_TRAIN, T0)
                s = stats(tr, T_TRAIN, T0)
                halves = []
                for a, b in zip(HALVES[:-1], HALVES[1:]):
                    sub = [x for x in tr if a <= x[0] < b]
                    halves.append(float(np.prod([1 + x[2] for x in sub]) - 1) if sub else 0.)
                rows.append(dict(key=key, coin=coin, **s, halves=halves))
            else:
                end = d.index.max() + pd.Timedelta(hours=TFS[tf])
                tr = simulate(d, gate, TFS[tf], depth, rule, T0, end)
                rows.append(dict(key=key, coin=coin, **stats(tr, T0, end)))
    return rows


def files(root):
    out = []
    for tf in TFS:
        dd = os.path.join(root, f'daten_voll_{tf}')
        out += [(os.path.join(dd, f), tf) for f in sorted(os.listdir(dd)) if f.endswith('.csv') and f.split('-')[0] not in EXCLUDE]
    return out


def run(mode, root):
    with Pool(6) as p:
        parts = p.map(job, [(f, tf, mode, root) for f, tf in files(root)], chunksize=4)
    return pd.DataFrame([r for x in parts for r in x])


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


if __name__ == '__main__':
    mode, root = sys.argv[1], sys.argv[2]
    if mode == 'auswahl':
        assert not os.path.exists(os.path.join(HERE, 'auswahl.json')), 'Auswahl existiert schon'
        T = run('auswahl', root); T.to_pickle(os.path.join(HERE, 'training.pkl'))
        T['pos_halves'] = T.halves.apply(lambda x: sum(v > 0 for v in x)); T['last_half'] = T.halves.apply(lambda x: x[-1])
        # Nachtrag 1: letztes Halbjahr ohne Handel (BTC-Filter aus) -> Gewinn in allen 3 Halbjahren mit Handel
        E = T[(T.dd <= .50) & (T.n >= 8) & T.halves.apply(lambda x: all(v > 0 for v in x[:3]))].sort_values('ret', ascending=False)
        sel = E.drop_duplicates('coin').head(30)
        json.dump(dict(t0=str(T0), keys=sel.key.tolist(), training=sel.drop(columns='halves').to_dict('records'),
                       candidates=int(len(T)), eligible=int(len(E)),
                       pool=T[T.n >= 1].key.tolist(), code_sha256=sha(__file__), prereg_sha256=sha(os.path.join(HERE, 'PREREG.md'))),
                  open(os.path.join(HERE, 'auswahl.json'), 'w'), indent=1, default=float)
        open(os.path.join(HERE, 'auswahl.sha256'), 'w').write(sha(os.path.join(HERE, 'auswahl.json')))
        print(f'Kandidaten {len(T)} | zulaessig {len(E)} | Coins {E.coin.nunique()} | gewaehlt {len(sel)}')
        print(sel[['key', 'ret', 'dd', 'n']].assign(halves=sel.halves.apply(lambda x: [round(v, 2) for v in x])).to_string())
    else:
        A = json.load(open(os.path.join(HERE, 'auswahl.json')))
        assert sha(os.path.join(HERE, 'auswahl.json')) == open(os.path.join(HERE, 'auswahl.sha256')).read().strip()
        assert A['code_sha256'] == sha(__file__) and A['prereg_sha256'] == sha(os.path.join(HERE, 'PREREG.md'))
        T = run('oos', root).set_index('key'); T.to_pickle(os.path.join(HERE, 'oos.pkl'))
        S = T.loc[A['keys']]; S['bestanden'] = (S.ret > .10) & (S.dd <= .50)
        print(S[['ret', 'dd', 'n', 'bestanden']].to_string())
        k, mean = int(S.bestanden.sum()), S.ret.mean()
        pool = T.loc[[x for x in A['pool'] if x in T.index]]; rng = np.random.default_rng(20261108)
        coins = pool.coin.unique(); ks, ms = [], []
        by = {c: pool[pool.coin == c] for c in coins}
        for _ in range(10000):
            cs = rng.choice(coins, 30, replace=False); pick = pd.concat([by[c].iloc[[rng.integers(len(by[c]))]] for c in cs])
            ks.append(((pick.ret > .10) & (pick.dd <= .50)).sum()); ms.append(pick.ret.mean())
        ks, ms = np.array(ks), np.array(ms)
        print(f'\nAuswahl: {k}/30 bestanden | mittlere OOS-Rendite {mean*100:+.1f} % | Median {S.ret.median()*100:+.1f} %')
        print(f'Zufall:  Ø {ks.mean():.1f}/30 bestanden | mittlere Rendite {ms.mean()*100:+.1f} %')
        print(f'p(bestanden) = {(ks >= k).mean():.4f} | p(Rendite) = {(ms >= mean).mean():.4f}')
        json.dump(dict(bestanden=k, mean=mean, p_k=float((ks >= k).mean()), p_mean=float((ms >= mean).mean()),
                       einzel=S.reset_index().to_dict('records')), open(os.path.join(HERE, 'oos_ergebnis.json'), 'w'), indent=1, default=float)
