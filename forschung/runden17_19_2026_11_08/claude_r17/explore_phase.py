# Erkundung (nur Entwicklungsdaten < 10.05.2026): Phasentor aus bereits ABGESCHLOSSENEN Trades.
# Suche: Coin-Haelfte A bis 2025; Pruefung: Coin-Haelfte B bis 2025 und alle Coins 2026-01-01..2026-05-09.
import sys
import numpy as np, pandas as pd
sys.path.insert(0, '.')
import claude_filter as F

T = pd.read_pickle('../codex_ws/runde17/events_dev.pkl').sort_values('ts').reset_index(drop=True)
T = T[T.eligible].reset_index(drop=True)
b = pd.read_csv('../codex_ws/runde17/btc_1d_dev.csv')
C26 = pd.Timestamp('2026-01-01', tz='UTC')
coins = np.array(sorted(T.coin.unique())); perm = np.random.default_rng(17).permutation(coins); A = set(perm[:len(perm) // 2])

# --- globales Phasentor: mittleres net_R aller Trades mit Ausstieg in [ts - W, ts)
ex = T.sort_values('exit_ts'); et = ex.exit_ts.values.astype('datetime64[ns]').astype(np.int64); cs = np.r_[0, np.cumsum(ex.net_R.values)]
ts = T.ts.values.astype('datetime64[ns]').astype(np.int64)
def glob(days):
    hi = np.searchsorted(et, ts, side='left'); lo = np.searchsorted(et, ts - int(days * 86400e9), side='left')
    n = hi - lo; s = cs[hi] - cs[lo]
    return np.where(n >= 30, s / np.maximum(n, 1), np.nan), n
# --- Config-Phasentor: mittleres net_R der letzten k abgeschlossenen Trades derselben Config
def cfg_gate(k):
    out = np.full(len(T), np.nan)
    for cfg, g in T.groupby('cfg'):
        gx = g.sort_values('exit_ts'); e = gx.exit_ts.values; r = np.r_[0, np.cumsum(gx.net_R.values)]
        hi = np.searchsorted(e, g.ts.values, side='left'); lo = np.maximum(hi - k, 0)
        out[g.index] = np.where(hi >= k, (r[hi] - r[lo]) / k, np.nan)
    return out

def replay(T, m):
    busy = {}; keep = []
    for i in np.flatnonzero(m):
        c = T.coin.iat[i]
        if c in busy and T.ts.iat[i] <= busy[c]: continue
        busy[c] = T.exit_ts.iat[i]; keep.append(i)
    return T.iloc[keep]

def show(name, m):
    t = replay(T, m); a = t[t.coin.isin(A) & (t.ts < C26)]; bb = t[~t.coin.isin(A) & (t.ts < C26)]; z = t[t.ts >= C26]
    print(f'{name:28s} A<2026 {a.net_R.mean():+.3f} ({len(a):5d}) | B<2026 {bb.net_R.mean():+.3f} ({len(bb):5d}) | 2026 {z.net_R.mean():+.3f} ({len(z):4d}) | stress {t.stress_R.mean():+.3f}', flush=True)

base = np.ones(len(T), bool); stop2 = (T.stop_atr >= 2).values
show('BASE', base); show('STOP2', stop2)
for d in (7, 14, 30):
    g, n = glob(d)
    show(f'GLOBAL_{d}d>0', g > 0); show(f'GLOBAL_{d}d>0 & STOP2', (g > 0) & stop2)
for k in (5, 10, 20):
    c = cfg_gate(k)
    show(f'CFG_last{k}>0', c > 0); show(f'CFG_last{k}>0 & STOP2', (c > 0) & stop2)
g, _ = glob(14); c = cfg_gate(10)
show('GLOBAL14 & CFG10', (g > 0) & (c > 0)); show('GLOBAL14 & CFG10 & STOP2', (g > 0) & (c > 0) & stop2)
