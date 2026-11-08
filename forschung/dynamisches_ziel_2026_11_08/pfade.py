# Datenbasis: jeder gefuellte Konfluenz-Einstieg mit Ergebnis fuer alle Ziele (1/1,5/2/3 R, Struktur) x Stop (S, A2)
# und Merkmalen beim Einstieg. Detektor unveraendert (plan_both). Siehe PREREG.md.
import glob, json, logging, os, sys
from multiprocessing import Pool
import numpy as np, pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')); sys.path.insert(0, os.path.join(ROOT, 'src'))
HERE = os.path.dirname(os.path.abspath(__file__))
CAND = os.path.join(ROOT, 'src', 'fibot', 'strategy', 'configs_fibot2')
if not os.path.isdir(CAND):
    CAND = os.path.join(ROOT, 'forschung', 'konfluenz', 'search', 'candidates')
FEE, LOSS_EXTRA = .0006, .0002
TARGETS = {'R10': 1., 'R15': 1.5, 'R20': 2., 'R30': 3., 'K': None}


def load(sym, tf):
    d = pd.read_csv(os.path.join(ROOT, 'data', 'cache', sym.replace('/', '-').replace(':', '-') + f'_{tf}.csv'))
    d.index = pd.to_datetime(d.iloc[:, 0], utc=True)
    d = d[['open', 'high', 'low', 'close']].astype(float).sort_index()
    return d[~d.index.duplicated()]


def outcome(H, L, i, n, ent, sl, tp):
    """Long-Sicht (Short gespiegelt): Stop zuerst, kein Ziel in der Fuellkerze. Rueckgabe (R_brutto, exit_pos) oder None."""
    if L[i] <= sl:
        return -1., i
    for k in range(i + 1, n):
        if L[k] <= sl:
            return -1., k
        if H[k] >= tp:
            return (tp - ent) / (ent - sl), k
    return None


def job(path):
    logging.disable(logging.WARNING)
    from fibot.strategy.confluence_logic import plan_both
    cfg = json.load(open(path)); sym, tf = cfg['market']['symbol'], cfg['market']['timeframe']
    if tf == '5m':
        return []
    try:
        df = load(sym, tf)
    except FileNotFoundError:
        return []
    is_start = pd.Timestamp(cfg.get('_backtest', {}).get('start_date', '2023-04-01'), tz='UTC')
    warm = pd.Timedelta(tf) * (int(cfg['strategy'].get('window', 150)) + 4 * 200 + 20)
    df = df[df.index >= is_start - warm]
    n = len(df); h, l, c = df.high.values, df.low.values, df.close.values
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().values
    atr_pct = 100 * atr / c
    rank = pd.Series(atr_pct).rolling(500, min_periods=200).rank(pct=True).values
    lo, sh = plan_both(df, cfg)
    rows = []
    for dname, pl, sgn in (('long', lo, 1), ('short', sh, -1)):
        H, L = (h, l) if sgn == 1 else (-l, -h)
        for i in np.nonzero(pl['fill'][:n])[0]:
            ts = df.index[i]
            if ts < is_start or i < 1:
                continue
            lim, sl, tp = pl['limit'][i], pl['sl'][i], pl['tp'][i]
            E, SL, TPs = sgn * lim, sgn * sl, sgn * tp
            a = atr[i - 1]
            if not np.isfinite(a) or E - SL <= 0:
                continue
            A, B = int(pl['A'][i]), int(pl['B'][i])
            imp = abs(h[B] - l[A]) if sgn == 1 else abs(h[A] - l[B])
            row = dict(cfg=f"{sym.split('/')[0]}USDTUSDT_{tf}", coin=sym.split('/')[0], tf=tf, dir=dname, ts=ts,
                       atr_rank=rank[i - 1], stop_atr=(E - SL) / a, rr_struct=(TPs - E) / (E - SL), impuls_atr=imp / a,
                       risk_pct=abs(lim - sl) / abs(lim) * 100)
            for sname, SLx in (('S', SL), ('A2', min(SL, E - 2 * a))):
                risk = E - SLx
                for tname, k in TARGETS.items():
                    tpx = TPs if k is None else E + k * risk
                    res = outcome(H, L, i, n, E, SLx, tpx)
                    if res is None:
                        row[f'{sname}_{tname}'] = np.nan; continue
                    r, kx = res
                    cost = FEE * 2 * abs(E) / risk + (0 if r > 0 else LOSS_EXTRA * abs(E) / risk)
                    row[f'{sname}_{tname}'] = r - cost
                    row[f'{sname}_{tname}_exit'] = df.index[kx]
            rows.append(row)
    return rows


if __name__ == '__main__':
    files = sorted(glob.glob(os.path.join(CAND, '*.json')))
    with Pool(6) as p:
        parts = p.map(job, files, chunksize=2)
    P = pd.DataFrame([r for x in parts for r in x])
    F = pd.read_pickle(os.path.join(ROOT, 'forschung', 'gewinner_filter_2026_11_08', 'features.pkl'))[['cfg', 'ts', 'dir', 'trend_ok', 'eligible', 'net_R']]
    P = P.merge(F, on=['cfg', 'ts', 'dir'], how='left')
    P.to_pickle(os.path.join(HERE, 'pfade.pkl'))
    chk = P.dropna(subset=['net_R'])
    print(f'{len(P)} Einstiege, {P.cfg.nunique()} Configs | Abgleich S_K vs Forschungs-net_R: max |diff| {np.nanmax(np.abs(chk.S_K - chk.net_R)):.6f}, n={len(chk)}')
