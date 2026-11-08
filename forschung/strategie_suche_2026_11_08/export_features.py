# Konfluenz-K0-Trades mit Merkmalen zum Order-Zeitpunkt (nur Daten bis i-1) -> Suchdaten fuer Codex (nur Segment S).
import os, sys
from multiprocessing import Pool
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', '..', 'src'))
import harness as H, konfluenz_k as K
from fibot.strategy.confluence_logic import _atr

def job(coin):
    df = H._read(os.path.join(H.GEO, f'{coin}-USDT-USDT_4h.csv'))
    o, h, l, c, v = (df[x].values for x in ('open', 'high', 'low', 'close', 'volume'))
    out = []
    for side, (O, Hh, L, C) in ((1, (o, h, l, c)), (-1, (-o, -l, -h, -c))):
        ev = K.touch_events(O, Hh, L, C, v)
        atr = _atr(Hh, L, C, 14)
        sma50 = pd.Series(C).rolling(50).mean().values
        evd = {e['i']: e for e in ev}
        for t in K.simulate(O, Hh, L, C, ev, 'K0', np.zeros(len(C), bool)):
            e = evd[t['i0']]; i = t['i0']; j = i - 1; A_, B_ = e['A'], e['B']
            a = atr[j]
            # Verlauf nach Einstieg: max. Plus in R vor Ausstieg
            seg_h = Hh[i:t['j'] + 1]
            mfe = (seg_h.max() - e['limit']) / (e['limit'] - e['sl'])
            out.append({'coin': coin, 'side': 'long' if side == 1 else 'short', 'entry_ts': df.index[i], 'ret': t['ret'], 'R': t['R'],
                'res': t['res'], 'bars': t['bars'], 'mfe_R': mfe,
                'stop_pct': abs(e['limit'] - e['sl']) / abs(e['limit']) * 100, 'stop_atr': abs(e['limit'] - e['sl']) / a,
                'rr': (e['tp'] - e['limit']) / (e['limit'] - e['sl']), 'atr_pct': a / abs(C[j]) * 100,
                'impuls_atr': (Hh[B_] - L[A_]) / a, 'impuls_kerzen': B_ - A_, 'alter_seit_B': i - B_,
                'rueck_rel_alter': (i - B_) / max(1, B_ - A_), 'beruehrungen': e['touches'], 'vol_ok': e['vol_ok'],
                'trend_sma50': float(C[j] > sma50[j]) if np.isfinite(sma50[j]) else np.nan,
                'abstand_close_limit_atr': (C[j] - e['limit']) / a,
                'fallgeschw_3k_atr': (C[j - 3] - C[j]) / a if j >= 3 else np.nan,
                'fill_kerze_unter_sl': bool(L[i] <= e['sl'])})
    return out

if __name__ == '__main__':
    U = H.load_universe('4h'); A, B = H.split_coins(U); reg = H.btc_regime()
    with Pool(6) as p: parts = p.map(job, list(U), chunksize=2)
    T = pd.DataFrame([r for x in parts for r in x])
    T['btc_regime'] = H.at(reg, pd.DatetimeIndex(T.entry_ts))
    T['segment'] = np.where(T.coin.isin(A) & (T.entry_ts < H.DISC_END), 'S', 'gesperrt')
    T.to_pickle(os.path.join(HERE, 'k0_features_alle.pkl'))
    S = T[T.segment == 'S'].drop(columns=['segment'])
    S.to_csv(os.path.join(HERE, 'k0_features_SUCHE.csv'), index=False)
    print(len(T), 'gesamt,', len(S), 'Suche S'); print(S.describe().T.round(2).to_string())
