# Claudes Phasentor-Kandidaten (Runde 17), auf Entwicklungsdaten < 10.05.2026 erkundet (16 Varianten, explore_phase.py),
# 3 davon eingefroren. Das Tor nutzt nur Trades, deren AUSSTIEG vor dem Einstieg des betrachteten Trades liegt.
# masks_phase(T): T = alle eligible-Ereignisse (Entwicklung + spaeter OOS gemeinsam, damit das Tor am OOS-Beginn
# die Vorgeschichte kennt). Rueckgabe: Masken ueber T.
import numpy as np
import pandas as pd


def _global_gate(T, days, min_n=30):
    ex = T.sort_values('exit_ts'); et = ex.exit_ts.values.astype('datetime64[ns]').astype(np.int64)
    cs = np.r_[0, np.cumsum(ex.net_R.values)]; ts = T.ts.values.astype('datetime64[ns]').astype(np.int64)
    hi = np.searchsorted(et, ts, side='left'); lo = np.searchsorted(et, ts - int(days * 86400e9), side='left')
    n = hi - lo
    return np.where(n >= min_n, (cs[hi] - cs[lo]) / np.maximum(n, 1), np.nan)


def _cfg_gate(T, k):
    out = np.full(len(T), np.nan)
    pos = {ix: p for p, ix in enumerate(T.index)}
    for _, g in T.groupby('cfg'):
        gx = g.sort_values('exit_ts'); e = gx.exit_ts.values; r = np.r_[0, np.cumsum(gx.net_R.values)]
        hi = np.searchsorted(e, g.ts.values, side='left'); lo = np.maximum(hi - k, 0)
        out[[pos[i] for i in g.index]] = np.where(hi >= k, (r[hi] - r[lo]) / k, np.nan)
    return out


def masks_phase(T):
    T = T[T.eligible]
    g14 = _global_gate(T, 14); g7 = _global_gate(T, 7); c10 = _cfg_gate(T, 10); stop2 = (T.stop_atr >= 2).to_numpy()
    # Nachtrag (explore_phase2.py, ebenfalls nur < 10.05.2026): Tor je Zeitebene
    tf14 = pd.Series(np.nan, index=T.index)
    for _, g in T.groupby('tf'):
        tf14.loc[g.index] = _global_gate(g, 14, min_n=15)
    tf14 = tf14.to_numpy()
    return T.index, {
        'P1_GLOBAL14_STOP2': (g14 > 0) & stop2,
        'P2_GLOBAL14_CFG10': (g14 > 0) & (c10 > 0),
        'P3_GLOBAL7_STOP2': (g7 > 0) & stop2,
        'P4_TF14': tf14 > 0,
        'P5_TF14_STOP2': (tf14 > 0) & stop2,
    }
