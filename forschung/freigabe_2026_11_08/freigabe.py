# Handelsfreigabe aus Codex' Edge-Diagnose (Analyse 14) -- vorab festgelegt, VOR der Rechnung eingefroren (PREREG.sha256).
# Bot: 17 aktive Configs des alten fibot (Stand 3d3385e), Trendfilter an (trend_ok), eine Position je Coin.
# G1 Edge-Ampel: Einstieg nur, wenn das Mittel der letzten 50 bereits bekannten Trades (Ausstiegskerze abgeschlossen) > 0;
#    weniger als 50 bekannte Trades -> erlaubt (keine Information).
# G2 Marktphase: BTC-Tagesregime nach edge_state.market_states (Trend up/down/range, am Folgetag bekannt).
#    Erlaubt sind die Trend-Zustaende mit positivem Mittel-R auf der Entwicklung (01.01.2025-09.05.2026, n>=100).
# Bewertung: Entwicklung und OOS 10.05.-08.11.2026 getrennt; Mittel-R behalten vs. Kontrolle, Mittel-R der AUSSORTIERTEN
# Trades mit 28-Tage-Blockbootstrap (Freigabe hilft nur, wenn Aussortierte negativ sind), Konto 34 USDT / 1 % Risiko.
# Grenze: Die 17 Configs wurden am 31.10.2026 auf diesem OOS-Zeitraum ausgewaehlt (Selection Bias fuer beide Seiten);
# aussagekraeftig ist der gepaarte Unterschied, nicht das absolute Niveau.
import os, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')); sys.path.insert(0, os.path.join(ROOT, 'src'))
from fibot.analysis.edge_state import market_states

ACTIVE = ['DOTUSDTUSDT_2h', 'BATUSDTUSDT_1h', 'APTUSDTUSDT_1h', 'JUPUSDTUSDT_1h', 'PYTHUSDTUSDT_4h', 'OPUSDTUSDT_1h',
          'SANDUSDTUSDT_1h', 'SHIBUSDTUSDT_1h', 'MAGICUSDTUSDT_15m', 'SIRENUSDTUSDT_30m', 'FILUSDTUSDT_15m', 'WALUSDTUSDT_1h',
          'TAOUSDTUSDT_30m', 'UNIUSDTUSDT_1h', 'PENGUUSDTUSDT_15m', 'XLMUSDTUSDT_30m', 'TRUMPUSDTUSDT_15m']
D0, T0, T1 = (pd.Timestamp(x, tz='UTC') for x in ('2025-01-01', '2026-05-10', '2026-11-09'))

T = pd.read_pickle(os.path.join(ROOT, 'forschung', 'gewinner_filter_2026_11_08', 'features.pkl'))
T = T[T.cfg.isin(ACTIVE) & T.eligible & (T.trend_ok == True)].sort_values('ts').reset_index(drop=True)
T['known_at'] = T.exit_ts + T.tf.map(pd.Timedelta)

# G1: letzte 50 bekannte Trades des 17er-Stroms (alle Signale, nicht nur gehandelte -- wie das Dashboard)
k = T.sort_values('known_at'); kt = k.known_at.values; kr = k.net_R.values
g1 = []
for ts in T.ts.values:
    n = np.searchsorted(kt, ts, side='right')
    g1.append(True if n < 50 else kr[n - 50:n].mean() > 0)
T['g1'] = g1

# G2: BTC-Trendzustand
b = pd.read_csv(os.path.join(ROOT, 'data', 'cache', 'BTC-USDT-USDT_1d.csv')); b.index = pd.to_datetime(b.iloc[:, 0], utc=True)
b = b[['open', 'high', 'low', 'close']].astype(float).sort_index(); b = b[~b.index.duplicated()]
S = market_states(b)
pos = S.index.searchsorted(pd.DatetimeIndex(T.ts), side='right') - 1
T['trend'] = np.where(pos >= 0, S.trend.values[np.maximum(pos, 0)], 'unknown')
devm = T[(T.ts >= D0) & (T.exit_ts < T0)].groupby('trend').net_R.agg(['size', 'mean'])
ok_states = [s for s, r in devm.iterrows() if r['size'] >= 100 and r['mean'] > 0]
T['g2'] = T.trend.isin(ok_states)


def replay(t):
    busy = {}; keep = []
    for i, r in enumerate(t.itertuples()):
        if r.coin in busy and r.ts <= busy[r.coin]: continue
        busy[r.coin] = r.exit_ts; keep.append(i)
    return t.iloc[keep]


def block_ci(t, n=2000):
    if len(t) < 20: return (np.nan, np.nan)
    d = t.groupby(t.ts.dt.floor('D')).net_R.agg(['sum', 'size'])
    blk = (d.index - d.index[0]).days // 28; g = [d[blk == x] for x in np.unique(blk)]
    rng = np.random.default_rng(20261108); m = []
    for _ in range(n):
        s = pd.concat([g[j] for j in rng.integers(0, len(g), len(g))]); m.append(s['sum'].sum() / s['size'].sum())
    return tuple(np.quantile(m, [.025, .975]))


def konto(t, a, b_, eq0=34., r=.01, lev=10.):
    t = t[(t.ts >= a) & (t.ts < b_)]; eq = eq0; peak = eq0; dd = 0.; op = []
    for x in t.itertuples():
        for o in [o for o in op if o[0] <= x.ts]:
            eq += o[2]; op.remove(o); peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
        notional = eq * r / (x.risk_pct / 100)
        if sum(o[1] for o in op) + notional > lev * eq: continue
        op.append((x.exit_ts, notional, eq * r * x.net_R))
    for o in sorted(op): eq += o[2]; peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
    return eq, dd


if __name__ == '__main__':
    print('Entwicklung je BTC-Trend:', devm.round(3).to_dict('index'), '-> erlaubt:', ok_states)
    ctrl = replay(T)
    for seg, (a, b_) in {'Entwicklung 01.01.2025-09.05.2026': (D0, T0), 'OOS 10.05.-08.11.2026': (T0, T1)}.items():
        c = ctrl[(ctrl.ts >= a) & (ctrl.ts < b_)]; ec, dc = konto(ctrl, a, b_)
        print(f'\n{seg}: Kontrolle n={len(c)} R {c.net_R.mean():+.3f} | Konto 34->{ec:.2f} DD {100*dc:.1f} %')
        for g in ('g1', 'g2'):
            kept = replay(T[T[g]]); kk = kept[(kept.ts >= a) & (kept.ts < b_)]
            rem = c[~c[g]]; lo, hi = block_ci(rem); ek, dk = konto(kept, a, b_)
            print(f'  {g.upper()}: behalten n={len(kk)} R {kk.net_R.mean():+.3f} | aussortiert n={len(rem)} R {rem.net_R.mean():+.3f} '
                  f'(95 % {lo:+.3f} .. {hi:+.3f}) | Konto 34->{ek:.2f} DD {100*dk:.1f} %')
