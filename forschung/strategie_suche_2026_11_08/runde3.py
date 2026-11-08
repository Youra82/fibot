# Runde 3 nach PREREG_KONFLUENZ_RUNDE3.md (sha256 df2e1f68...). Aufruf: ../../.venv/Scripts/python runde3.py
import os
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'src'))
import harness as H                                    # noqa: E402
import konfluenz_k as K                                # noqa: E402
from h1_h5 import block_bootstrap_p                    # noqa: E402
from fibot.strategy.confluence_logic import DEFAULTS, V2, find_channel, _atr, _pivots   # noqa: E402

P = {**DEFAULTS, **V2}
MAXB = 120
RULES = ('C1', 'C2', 'C3', 'KS')


def ks_events(o, h, l, c):
    """Wie touch_events, aber Order auf f786; Impuls erst beim f786-Fill verbraucht."""
    p = P
    n, k = len(c), int(p['pivot_k'])
    atr = _atr(h, l, c, int(p['atr_period']))
    pl, ph = _pivots(l, k, 'low'), _pivots(h, k, 'high')
    used_b, ev = set(), []
    for i in range(int(p['window']) + k + 1, n):
        j = i - 1
        ch = find_channel(j, l, h, c, atr, pl, ph, p)
        if ch is None:
            continue
        a = atr[j]
        lp = pl[(pl >= ch.a_pos) & (pl <= j - k)]
        touch = lp[np.abs(l[lp] - ch.lower(lp)) <= p['touch_atr'] * a]
        if len(touch) == 0:
            continue
        A = int(touch[-1])
        hp = ph[(ph > A) & (ph <= j - k)]
        if len(hp) == 0:
            continue
        B = int(hp[np.argmax(h[hp])])
        if B in used_b or h[B] < ch.upper(B) - p['b_near_upper_atr'] * a:
            continue
        hi, lo = h[B], l[A]
        if np.max(h[B:j + 1]) > hi:
            continue
        diff = hi - lo
        f50, f618, f786 = hi - p['fib_lo'] * diff, hi - p['fib_hi'] * diff, hi - p['fib_sl'] * diff
        if np.min(c[B:j + 1]) < f786:
            used_b.add(B)
            continue
        if p['max_age_mult'] is not None and i - B > p['max_age_mult'] * (B - A):
            continue
        limit = ch.lower(i)
        tol = p['zone_tol_atr'] * a
        if not (f618 - tol <= limit <= f50 + tol) or c[j] <= limit:
            continue
        sl0 = min(f786, limit) - p['sl_buf_atr'] * a
        if limit - sl0 <= 0 or (ch.upper(i) - limit) / (limit - sl0) < p['min_rr']:
            continue
        if l[i] <= f786:
            used_b.add(B)
            ev.append({'i': i, 'entry_lvl': f786, 'sl': lo - 0.25 * a, 'tp': f50, 'atr': a})
    return ev


def sim_one(o, h, l, c, i, ep, sl, tp, first_tp):
    n = len(c)
    if l[i] <= sl:
        return sl - H.SLIP * abs(sl), i, 'sl'
    for j in range(first_tp, min(n, i + MAXB)):
        if l[j] <= sl:
            xp = o[j] if o[j] < sl else sl
            return xp - H.SLIP * abs(xp), j, 'sl'
        if h[j] >= tp:
            xp = o[j] if o[j] > tp else tp
            return xp - H.SLIP * abs(xp), j, 'tp'
    j = min(n - 1, i + MAXB - 1)
    return c[j] - H.SLIP * abs(c[j]), j, 'time'


def leg_ret(ep, xp):
    return (xp - ep) / abs(ep) - H.MAKER - H.TAKER * abs(xp) / abs(ep)


def stop_ok(lvl, sl, a, ep=None):
    for x in (lvl, ep) if ep is not None else (lvl,):
        d = x - sl
        if d < 1.0 * a or d < 0.01 * abs(x):
            return False
    return True


def job(args):
    coin, G_series = args
    df = H._read(os.path.join(H.GEO, f'{coin}-USDT-USDT_4h.csv'))
    o, h, l, c, v = (df[x].values for x in ('open', 'high', 'low', 'close', 'volume'))
    G = H.at(G_series, df.index + pd.Timedelta(hours=4))   # zum Schluss der Vorkerze bekannt -> fuer Kerze i: Wert bei i-1
    out = []
    for side, (O, Hh, L, C) in ((1, (o, h, l, c)), (-1, (-o, -l, -h, -c))):
        atr = _atr(Hh, L, C, 14)
        sma50 = pd.Series(C).rolling(50).mean().values
        ev = K.touch_events(O, Hh, L, C, v)
        for rule in ('C1', 'C2', 'C3'):
            free = 0
            for e in ev:
                i = e['i']
                if i < free:
                    continue
                a = atr[i - 1]
                ep = min(e['limit'], O[i])
                if not stop_ok(e['limit'], e['sl'], a, ep):
                    continue
                if rule == 'C2':
                    g = G[i - 1]
                    if not (np.isfinite(sma50[i - 1]) and C[i - 1] > sma50[i - 1] and np.isfinite(g)
                            and g == (1.0 if side == 1 else 0.0)):
                        continue
                D = ep - e['sl']
                x1, j1, r1 = sim_one(O, Hh, L, C, i, ep, e['sl'], ep + D, i + 1)
                if rule == 'C3':
                    x2, j2, r2 = sim_one(O, Hh, L, C, i, ep, e['sl'], e['tp'], i + 1)
                    ret = 0.5 * leg_ret(ep, x1) + 0.5 * leg_ret(ep, x2); j = max(j1, j2); res = r2
                else:
                    ret, j, res = leg_ret(ep, x1), j1, r1
                out.append({'coin': coin, 'rule': rule, 'side': side, 'entry_ts': df.index[i], 'ret': ret, 'res': res,
                            'R': ret * abs(ep) / D, 'bars': j - i + 1, 'stop_pct': D / abs(ep) * 100})
                free = j + 1
        free = 0
        for e in ks_events(O, Hh, L, C):
            i = e['i']
            if i < free:
                continue
            ep = min(e['entry_lvl'], O[i])
            if not stop_ok(e['entry_lvl'], e['sl'], e['atr'], ep) or e['tp'] <= ep:
                continue
            x, j, res = sim_one(O, Hh, L, C, i, ep, e['sl'], e['tp'], i + 1)
            ret = leg_ret(ep, x)
            out.append({'coin': coin, 'rule': 'KS', 'side': side, 'entry_ts': df.index[i], 'ret': ret, 'res': res,
                        'R': ret * abs(ep) / (ep - e['sl']), 'bars': j - i + 1, 'stop_pct': (ep - e['sl']) / abs(ep) * 100})
            free = j + 1
    return out


def main():
    U = H.load_universe('4h'); A, B = H.split_coins(U); reg = H.btc_regime()
    with Pool(6) as pool:
        parts = pool.map(job, [(coin, reg) for coin in U], chunksize=2)
    T = pd.DataFrame([r for p in parts for r in p])
    T['side'] = np.where(T.side == 1, 'long', 'short')
    T.to_pickle(os.path.join(HERE, 'trades_runde3.pkl'))
    res = {}
    for rule in RULES:
        tr = T[T.rule == rule]
        print(f"\n===== {rule} ({len(tr)} Trades, Long {int((tr.side=='long').sum())} / Short {int((tr.side=='short').sum())}, "
              f"Stop Median {tr.stop_pct.median():.1f} %) =====")
        seg = H.segments(tr, A, B)
        out = {k: H.evaluate(s, k) for k, s in seg.items()}
        p1 = seg['PRUEF  B bis 14.10.26']
        daym = {k: (s.groupby(pd.to_datetime(s.entry_ts, utc=True).dt.floor('D')).ret.mean().mean() * 100 if len(s) else np.nan)
                for k, s in seg.items()}
        p_raw = block_bootstrap_p(p1, n=9999, seed=20261109) if len(p1) else 1.0
        pval = (p_raw * 9999 + 1) / 10000
        pc = p1.groupby('coin').ret.agg(['sum', 'size']); pc5 = pc[pc['size'] >= 5]
        breite = (pc5['sum'] > 0).mean() * 100 if len(pc5) else np.nan
        stress = (p1.ret - 0.0015 - 0.0001 * np.ceil(p1.bars / 2)).mean() * 100 if len(p1) else np.nan
        print('  Tagesmittel %: ' + ' | '.join(f"{k.strip()} {x:+.3f}" for k, x in daym.items()))
        print('  R/Trade: ' + ' | '.join(f"{k.strip()} {s.R.mean():+.3f}" for k, s in seg.items() if len(s)))
        print(f"  P1 p = {pval:.4f} | Breite {breite:.0f} % | Stress {stress:+.3f} %/Trade")
        res[rule] = dict(p=pval, daym=daym, breite=breite, stress=stress,
                         wo5=(out['PRUEF  B bis 14.10.26'] or {}).get('ohne_top5_pct', np.nan))
    order = sorted(RULES, key=lambda k: res[k]['p'])
    holm, still = {}, True
    for r_, k in enumerate(order):
        ok = still and res[k]['p'] <= 0.05 / (len(order) - r_)
        holm[k] = ok; still = still and ok
    print("\n===== Gesamturteil (Holm 5 % ueber C1, C2, C3, KS) =====")
    for k in RULES:
        r_ = res[k]; d = r_['daym']
        c1 = all(np.isfinite(x) and x > 0 for kk, x in d.items() if not kk.startswith('ENDTEST'))
        c3 = (r_['breite'] >= 55) and (r_['wo5'] > 0)
        c4 = r_['stress'] > 0
        ok = c1 and holm[k] and c3 and c4
        print(f"{k}: Tagesmittel>0 {'ja' if c1 else 'nein'} | Holm {'ja' if holm[k] else 'nein'} (p {r_['p']:.4f}) | "
              f"Breite/Top5 {'ja' if c3 else 'nein'} | Stress {'ja' if c4 else 'nein'} -> {'BESTANDEN' if ok else 'nicht bestanden'}")


if __name__ == '__main__':
    main()
