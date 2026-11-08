# Plausibilitaet (Zufallseinstiege) + Referenz Ausbruch-Long H5 (bestanden 04.10.2026)
import numpy as np, pandas as pd, time
from harness import *
t0 = time.time()
U = load_universe('4h'); A, B = split_coins(U)
reg = btc_regime()
print(f"{len(U)} Coins, A {len(A)}, B {len(B)}, BTC-Regime ab {reg.index[0].date()}  ({time.time()-t0:.0f}s)")
rng = np.random.default_rng(1)
rand, brk = [], []
for coin, df in U.items():
    a = atr(df, 14); c = df.close.values; sma = df.close.rolling(20).mean().values
    up = at(reg, df.index)
    # Zufall: 2 % der Kerzen, Long, SL 3 ATR, TP 3 ATR
    ent = [(i + 1, None, c[i] - 3 * a[i], c[i] + 3 * a[i]) for i in np.where(rng.random(len(df)) < 0.02)[0] if i > 30 and i + 1 < len(df)]
    for t in run_trades(df, ent, 1, 60): rand.append({**t, 'coin': coin})
    # H5: Close > SMA20 + 3 ATR, nur BTC>SMA200, Einstieg Open naechste Kerze, SL 3 ATR, TP 12 ATR, max 60
    sig = np.where((c > sma + 3 * a) & (up == 1))[0]
    ent = [(i + 1, None, c[i] - 3 * a[i], c[i] + 12 * a[i]) for i in sig if i + 1 < len(df)]
    for t in run_trades(df, ent, 1, 60): brk.append({**t, 'coin': coin})
R, Bk = pd.DataFrame(rand), pd.DataFrame(brk)
print('--- Zufall Long (erwartet ~ -0,16 % Kosten + Drift) ---')
for k, s in segments(R, A, B).items(): evaluate(s, k)
print('--- Referenz Ausbruch-Long H5 ---')
for k, s in segments(Bk, A, B).items(): evaluate(s, k)
Bk.to_pickle('ref_breakout.pkl')
