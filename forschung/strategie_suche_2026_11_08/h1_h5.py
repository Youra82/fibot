# H1-H5 nach PREREG_H1_H5.md (sha256 22a09c05...). Aufruf: ../../.venv/Scripts/python h1_h5.py
import numpy as np
import pandas as pd
import harness as H

TP_FEE = H.TAKER          # TP als getriggerter Market (Codex-Vorgabe)
PAUSE = 6


def wilder_atr(df, n=20):
    h, l, c = df.high.values, df.low.values, df.close.values
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    tr[0] = h[0] - l[0]
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().values


def run(df, entries, max_bars):
    """entries: (i_entry, sl_mult, tp_mult, A) -> Einstieg Open i_entry; SL/TP relativ zum Fill."""
    o, h, l, c = df.open.values, df.high.values, df.low.values, df.close.values
    n, out, free_from = len(df), [], 0
    for (i, slm, tpm, A) in sorted(entries):
        if i < free_from or i >= n or not np.isfinite(A) or A <= 0:
            continue
        ep = o[i] * (1 + H.SLIP)
        sl, tp = ep - slm * A, ep + tpm * A
        res, xp, j = None, None, i
        for j in range(i, min(n, i + max_bars)):
            if l[j] <= sl:
                xp = (o[j] if (o[j] < sl and j > i) else sl) * (1 - H.SLIP); res = 'sl'; break
            if h[j] >= tp and j > i:
                xp = tp * (1 - H.SLIP); res = 'tp'; break
        if res is None:
            j = min(n - 1, i + max_bars - 1); xp = c[j] * (1 - H.SLIP); res = 'time'
        bars = j - i + 1
        ret = xp / ep - 1 - H.TAKER - (TP_FEE if res == 'tp' else H.TAKER)
        out.append({'entry_ts': df.index[i], 'exit_ts': df.index[j], 'ret': ret, 'res': res, 'bars': bars,
                    'risk_pct': slm * A / ep * 100})
        free_from = j + 1 + PAUSE
    return out


def h1(df, G, A20, sma20):
    c, h, l = df.close.values, df.high.values, df.low.values
    thr = sma20 + 3 * A20
    above = c > thr
    ent, i, n = [], 1, len(df)
    while i < n - 10:
        if above[i] and not above[i - 1] and G[i] == 1:
            b, Ab = i, A20[i]
            p = slice(b + 1, b + 4)
            if np.all(c[p] > c[b] - Ab) and (h[p].max() - l[p].min()) <= 2 * Ab:
                lvl = h[b:b + 4].max()
                for t in range(b + 4, min(n - 1, b + 10)):
                    if c[t] > lvl:
                        if G[t] == 1:
                            ent.append((t + 1, 3, 12, A20[t]))
                        break
            i = b + 10          # ein aktives Setup je Coin
            continue
        i += 1
    return ent, 60


def h2(df, G, A20):
    c, h, l = df.close.values, df.high.values, df.low.values
    D = pd.Series(h).shift(1).rolling(20).max().values     # Hoch der 20 Kerzen vor b
    ent, i, n = [], 21, len(df)
    while i < n - 7:
        if c[i] > D[i] and c[i - 1] <= D[i] and G[i] == 1:
            b, Db, Ab = i, D[i], A20[i]
            for t in range(b + 1, min(n - 1, b + 7)):
                if l[t] < Db - Ab or c[t] < Db - Ab:
                    break
                if l[t] <= Db and c[t] > Db:
                    if G[t] == 1:
                        ent.append((t + 1, 3, 9, A20[t]))
                    break
            i = b + 7
            continue
        i += 1
    return ent, 42


def h3(df, G, A20, btc_ret):
    c, h, l, v = df.close.values, df.high.values, df.low.values, df.volume.values
    sma50 = pd.Series(c).rolling(50).mean().values
    D = pd.Series(l).shift(1).rolling(12).min().values
    vmed = pd.Series(v).shift(1).rolling(20).median().values
    ent = []
    for t in range(51, len(df) - 1):
        Ap = A20[t - 1]
        if not (c[t - 1] > sma50[t - 1] and G[t] == 1 and np.isfinite(Ap)):
            continue
        rng = h[t] - l[t]
        if rng <= 0:
            continue
        if (l[t] < D[t] and l[t] <= c[t - 1] - 3 * Ap and c[t] > D[t] and c[t] >= l[t] + 0.65 * rng
                and v[t] >= 2 * vmed[t] and btc_ret[t] > -0.01):
            ent.append((t + 1, 3, 4.5, Ap))
    return ent, 6


def h4(df, G, A20, mkt):
    c = df.close.values
    r = np.r_[np.nan, c[1:] / c[:-1] - 1]
    ent, t, n = [], 1, len(df)
    while t < n - 2:
        if mkt[t] <= -0.04 and G[t] == 1 and r[t] <= -0.06:
            P, Ap = c[t - 1], A20[t - 1]
            for u in range(t + 1, min(n - 1, t + 7)):
                if c[u] > P and c[u - 1] <= P:
                    if G[u] == 1:
                        ent.append((u + 1, 3, 6, Ap))
                    break
            t += 7
            continue
        t += 1
    return ent, 12


def h5(df, A20, sma20, windows):
    c = df.close.values
    above = c > sma20 + 3 * A20
    ent = []
    for (w0, w1) in windows:
        idx = np.where((df.index >= w0) & (df.index < w1))[0]
        for i in idx:
            if i > 0 and above[i] and not above[i - 1]:
                if i + 1 < len(df):
                    ent.append((i + 1, 3, 12, A20[i]))
                break
    return ent, 60


def regime_windows():
    d = H.btc_daily()
    sma = d.close.rolling(200).mean()
    up = (d.close > sma) & sma.notna()
    wins = []
    for k in range(10, len(d)):
        if up.iloc[k] and not up.iloc[k - 10:k].any():
            day = d.index[k]
            w0 = day + pd.Timedelta(days=1)
            if wins and w0 < wins[-1][1]:
                continue
            wins.append((w0, w0 + pd.Timedelta(days=20)))
    return wins


def block_bootstrap_p(tr, block_days=28, n=2000, seed=7):
    """einseitiger p-Wert H0: Mittel der Tagesmittel <= 0, Kalenderbloecke von block_days Tagen."""
    if len(tr) == 0:
        return np.nan
    d = tr.groupby(pd.to_datetime(tr.entry_ts, utc=True).dt.floor('D')).ret.mean()
    blk = ((d.index - d.index.min()).days // block_days).values
    groups = [d.values[blk == b] for b in np.unique(blk)]
    obs = d.mean()
    rng = np.random.default_rng(seed)
    cen = [g - obs for g in groups]           # unter H0 zentriert
    k = len(groups)
    sims = np.empty(n)
    for s in range(n):
        pick = rng.integers(0, k, k)
        sims[s] = np.concatenate([cen[p] for p in pick]).mean()
    return float((sims >= obs).mean())


def main():
    U = H.load_universe('4h'); A, B = H.split_coins(U)
    reg = H.btc_regime()
    btc = U['BTC']
    btc_r = (btc.close / btc.close.shift(1) - 1)
    # Marktrendite: gleichgewichtet ueber Coins mit >= 200 Kerzen Vorlauf
    rets = {}
    for coin, df in U.items():
        r = df.close / df.close.shift(1) - 1
        r[np.arange(len(r)) < 200] = np.nan
        rets[coin] = r
    R = pd.DataFrame(rets)
    cnt = R.notna().sum(axis=1)
    mkt = R.mean(axis=1).where(cnt >= 100)
    wins = regime_windows()
    print(f"Regime-Fenster H5: {[(str(a.date()), str(b.date())) for a, b in wins]}")
    allt = {k: [] for k in ('H1', 'H2', 'H3', 'H4', 'H5')}
    for coin, df in U.items():
        A20 = wilder_atr(df, 20)
        sma20 = df.close.rolling(20).mean().values
        close_t = df.index + pd.Timedelta(hours=4)
        G = H.at(reg, close_t)
        br = btc_r.reindex(df.index).values
        mk = mkt.reindex(df.index).values
        for name, (ent, mb) in (('H1', h1(df, G, A20, sma20)), ('H2', h2(df, G, A20)), ('H3', h3(df, G, A20, br)),
                                ('H4', h4(df, G, A20, mk)), ('H5', h5(df, A20, sma20, wins))):
            for t in run(df, ent, mb):
                allt[name].append({**t, 'coin': coin})
    res = {}
    for name, rows in allt.items():
        tr = pd.DataFrame(rows)
        print(f"\n===== {name} ({len(tr)} Trades) =====")
        if tr.empty:
            continue
        tr.to_pickle(f'trades_{name}.pkl')
        seg = H.segments(tr, A, B)
        out = {}
        for k, s in seg.items():
            out[k] = H.evaluate(s, k)
        p1 = seg['PRUEF  B bis 14.10.26']
        pval = block_bootstrap_p(p1)
        # Breite nur Coins mit >= 5 Trades
        pc = p1.groupby('coin').ret.agg(['sum', 'size'])
        pc5 = pc[pc['size'] >= 5]
        breite = (pc5['sum'] > 0).mean() * 100 if len(pc5) else np.nan
        # Kostenstress: +0,15 % Roundtrip und Funding 0,01 % je angefangene 8h (2 Kerzen)
        stress = (p1.ret - 0.0015 - 0.0001 * np.ceil(p1.bars / 2)).mean() * 100
        daym = {k: (s.groupby(pd.to_datetime(s.entry_ts, utc=True).dt.floor('D')).ret.mean().mean() * 100 if len(s) else np.nan)
                for k, s in seg.items()}
        print(f"  Tagesmittel %: " + ' | '.join(f"{k.strip()} {v:+.3f}" for k, v in daym.items()))
        print(f"  P1 Block-Bootstrap p = {pval:.4f} | Breite (>=5 Trades) {breite:.0f} % | Stress P1 {stress:+.3f} %/Trade")
        res[name] = dict(p=pval, daym=daym, breite=breite, stress=stress,
                         wo5=out['PRUEF  B bis 14.10.26'].get('ohne_top5_pct', np.nan) if out.get('PRUEF  B bis 14.10.26') else np.nan)
    # Holm
    names = [k for k in res if np.isfinite(res[k]['p'])]
    order = sorted(names, key=lambda k: res[k]['p'])
    m = len(order)
    print("\n===== Holm (5 %) und Gesamturteil =====")
    holm_ok, still = {}, True
    for r_, k in enumerate(order):
        thr = 0.05 / (m - r_)
        ok = still and res[k]['p'] <= thr
        holm_ok[k] = ok
        if not ok:
            still = False
    for k in ('H1', 'H2', 'H3', 'H4', 'H5'):
        if k not in res:
            print(f"{k}: keine Trades -> nicht bestanden"); continue
        r_ = res[k]; d = r_['daym']
        c1 = all(np.isfinite(v) and v > 0 for kk, v in d.items() if not kk.startswith('ENDTEST'))
        c3 = r_['breite'] >= 55 and r_['wo5'] > 0
        c4 = r_['stress'] > 0
        ok = c1 and holm_ok.get(k, False) and c3 and c4
        print(f"{k}: 1 Tagesmittel>0 {'ja' if c1 else 'nein'} | 2 Holm {'ja' if holm_ok.get(k) else 'nein'} (p {r_['p']:.4f}) | "
              f"3 Breite/Top5 {'ja' if c3 else 'nein'} | 4 Stress {'ja' if c4 else 'nein'} -> {'BESTANDEN' if ok else 'nicht bestanden'}")


if __name__ == '__main__':
    main()
