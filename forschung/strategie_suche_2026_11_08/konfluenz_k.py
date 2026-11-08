# Konfluenz K0-K5 nach PREREG_KONFLUENZ_K0_K5.md (sha256 34d5a251...). Aufruf: ../../.venv/Scripts/python konfluenz_k.py
import os
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'src'))
import harness as H                                    # noqa: E402
from h1_h5 import block_bootstrap_p                    # noqa: E402
from fibot.strategy.confluence_logic import DEFAULTS, V2, find_channel, _atr, _pivots   # noqa: E402

P = {**DEFAULTS, **V2}
MAXBARS = 120
VARIANTS = ('K0', 'K1', 'K2', 'K3', 'K4', 'K5')


def touch_events(o, h, l, c, v):
    """Wie _plan_one_direction (Long-Raum): fuer jede Kerze i Plan aus Daten bis i-1; Ereignis wenn Tief i <= Limit."""
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
        sl = min(f786, limit) - p['sl_buf_atr'] * a
        tp = ch.upper(i)
        if limit - sl <= 0 or (tp - limit) / (limit - sl) < p['min_rr']:
            continue
        if l[i] <= limit:
            used_b.add(B)
            vol_imp = v[A:B + 1].mean()
            vol_pb = v[B + 1:i].mean() if i - 1 >= B + 1 else np.nan
            ev.append({'i': i, 'limit': limit, 'sl': sl, 'tp': tp, 'A': A, 'B': B, 'touches': ch.touches,
                       'vol_ok': bool(np.isfinite(vol_pb) and vol_imp > vol_pb)})
    return ev


def _exit(o, h, l, c, i0, ep, sl, tp, first_tp_bar):
    n = len(c)
    for j in range(i0, min(n, i0 + MAXBARS)):
        if l[j] <= sl:
            xp = o[j] if (o[j] < sl and j > i0) else sl
            return xp - H.SLIP * abs(xp), j, 'sl'
        if h[j] >= tp and j >= first_tp_bar:
            return tp - H.SLIP * abs(tp), j, 'tp'
    j = min(n - 1, i0 + MAXBARS - 1)
    return c[j] - H.SLIP * abs(c[j]), j, 'time'


def simulate(o, h, l, c, ev, variant, liquid):
    trades, free_from = [], 0
    for e in ev:
        i = e['i']
        if i < free_from:
            continue
        f2 = variant in ('K2', 'K5')
        f3 = variant in ('K3', 'K5')
        f4 = variant in ('K4', 'K5')
        if f2 and not e['vol_ok']:
            continue
        if f3 and e['touches'] < 3:
            continue
        if f4 and (not liquid[i] or abs(e['limit'] - e['sl']) < 0.01 * abs(e['limit'])):
            continue
        sl, tp = e['sl'], e['tp']
        if variant in ('K1', 'K5'):
            if l[i] <= sl:
                continue
            entry_bar = None
            for u in range(i, min(len(c) - 1, i + 4)):
                if u > i and l[u] <= sl:
                    break
                if c[u] > e['limit'] and c[u] > o[u]:
                    entry_bar = u + 1
                    break
            if entry_bar is None or entry_bar >= len(c):
                continue
            ep = o[entry_bar] + H.SLIP * abs(o[entry_bar])
            if ep <= sl or (tp - ep) / (ep - sl) < 1.0:
                continue
            fee_in = H.TAKER + H.SLIP * 0  # Schlupf schon im Preis
            xp, j, res = _exit(o, h, l, c, entry_bar, ep, sl, tp, entry_bar + 1)
            i0 = entry_bar
        else:
            ep = min(e['limit'], o[i])
            fee_in = H.MAKER
            if l[i] <= sl:
                xp, j, res = sl - H.SLIP * abs(sl), i, 'sl'
            else:
                xp, j, res = _exit(o, h, l, c, i, ep, sl, tp, i + 1)
            i0 = i
        ret = (xp - ep) / abs(ep) - fee_in - H.TAKER
        trades.append({'i0': i0, 'j': j, 'ret': ret, 'res': res, 'R': (xp - ep) / (ep - sl),
                       'risk_pct': (ep - sl) / abs(ep) * 100, 'bars': j - i0 + 1})
        free_from = j + 1
    return trades


def job(args):
    coin, liquid_days = args
    df = H._read(os.path.join(H.GEO, f'{coin}-USDT-USDT_4h.csv'))
    o, h, l, c, v = (df[x].values for x in ('open', 'high', 'low', 'close', 'volume'))
    day = df.index.floor('D')
    liquid = np.asarray(pd.Series(day).map(liquid_days).fillna(False).values, dtype=bool)
    out = []
    for side, arr in ((1, (o, h, l, c)), (-1, (-o, -l, -h, -c))):
        O, Hh, L, C = arr
        ev = touch_events(O, Hh, L, C, v)
        for var in VARIANTS:
            for t in simulate(O, Hh, L, C, ev, var, liquid):
                out.append({**t, 'coin': coin, 'variant': var, 'side': 'long' if side == 1 else 'short',
                            'entry_ts': df.index[t['i0']], 'exit_ts': df.index[t['j']]})
    return out


def liquidity_flags(U):
    """Je Coin und Tag: oberes Drittel nach 30-Tage-Median des Tages-Quote-Volumens (bekannt ab Folgetag)."""
    qv = {}
    for coin, df in U.items():
        d = (df.close * df.volume).resample('1D').sum()
        qv[coin] = d.rolling(30, min_periods=20).median().shift(1)
    Q = pd.DataFrame(qv)
    pct = Q.rank(axis=1, pct=True)
    flags = pct >= 2 / 3
    return {coin: flags[coin].to_dict() for coin in U}


def main():
    U = H.load_universe('4h'); A, B = H.split_coins(U)
    flags = liquidity_flags(U)
    with Pool(6) as pool:
        parts = pool.map(job, [(coin, flags[coin]) for coin in U], chunksize=2)
    T = pd.DataFrame([r for p in parts for r in p])
    T.to_pickle(os.path.join(HERE, 'trades_konfluenz_k.pkl'))
    res = {}
    for var in VARIANTS:
        tr = T[T.variant == var]
        print(f"\n===== {var} ({len(tr)} Trades, Long {int((tr.side=='long').sum())} / Short {int((tr.side=='short').sum())}) =====")
        seg = H.segments(tr, A, B)
        out = {k: H.evaluate(s, k) for k, s in seg.items()}
        p1 = seg['PRUEF  B bis 14.10.26']
        daym = {k: (s.groupby(pd.to_datetime(s.entry_ts, utc=True).dt.floor('D')).ret.mean().mean() * 100 if len(s) else np.nan)
                for k, s in seg.items()}
        pval = block_bootstrap_p(p1) if len(p1) else np.nan
        pc = p1.groupby('coin').ret.agg(['sum', 'size']); pc5 = pc[pc['size'] >= 5]
        breite = (pc5['sum'] > 0).mean() * 100 if len(pc5) else np.nan
        stress = (p1.ret - 0.0015 - 0.0001 * np.ceil(p1.bars / 2)).mean() * 100 if len(p1) else np.nan
        print('  Tagesmittel %: ' + ' | '.join(f"{k.strip()} {v:+.3f}" for k, v in daym.items()))
        print(f"  R/Trade: " + ' | '.join(f"{k.strip()} {s.R.mean():+.3f}" for k, s in seg.items() if len(s)))
        print(f"  P1 p = {pval:.4f} | Breite {breite:.0f} % | Stress {stress:+.3f} %/Trade | Long/Short P1 "
              f"{p1[p1.side=='long'].ret.mean()*100:+.3f} / {p1[p1.side=='short'].ret.mean()*100:+.3f}")
        res[var] = dict(p=pval, daym=daym, breite=breite, stress=stress,
                        wo5=(out['PRUEF  B bis 14.10.26'] or {}).get('ohne_top5_pct', np.nan))
    order = sorted([k for k in res if np.isfinite(res[k]['p'])], key=lambda k: res[k]['p'])
    holm, still = {}, True
    for r_, k in enumerate(order):
        ok = still and res[k]['p'] <= 0.05 / (len(order) - r_)
        holm[k] = ok
        still = still and ok
    print("\n===== Gesamturteil (Holm 5 % ueber K0-K5) =====")
    for k in VARIANTS:
        r_ = res[k]; d = r_['daym']
        c1 = all(np.isfinite(x) and x > 0 for kk, x in d.items() if not kk.startswith('ENDTEST'))
        c3 = (r_['breite'] >= 55) and (r_['wo5'] > 0)
        c4 = r_['stress'] > 0
        ok = c1 and holm.get(k, False) and c3 and c4
        print(f"{k}: Tagesmittel>0 {'ja' if c1 else 'nein'} | Holm {'ja' if holm.get(k) else 'nein'} (p {r_['p']:.4f}) | "
              f"Breite/Top5 {'ja' if c3 else 'nein'} | Stress {'ja' if c4 else 'nein'} -> {'BESTANDEN' if ok else 'nicht bestanden'}")


if __name__ == '__main__':
    main()
