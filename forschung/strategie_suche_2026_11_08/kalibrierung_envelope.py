# Kalibrierung: belegter ltbbot-Mechanismus (RT-Envelope Long, BTC>SMA200) durch dasselbe Protokoll.
# Mitte = Donchian-Mitte 5 (geshiftet), Limit-Kauf bei mid*(1-e), TP = laufende Mitte, SL 30 %, max 60 Kerzen.
import numpy as np, pandas as pd
import harness as H
from h1_h5 import block_bootstrap_p
U = H.load_universe('4h'); A, B = H.split_coins(U); reg = H.btc_regime()
for e in (0.07, 0.11, 0.15):
    rows = []
    for coin, df in U.items():
        o, h, l, c = df.open.values, df.high.values, df.low.values, df.close.values
        mid = ((df.high.rolling(5).max() + df.low.rolling(5).min()) / 2).shift(1).values
        G = H.at(reg, df.index)               # bekannt zum Kerzenbeginn (Order liegt waehrend der Kerze)
        n, i = len(df), 6
        while i < n:
            band = mid[i] * (1 - e)
            if G[i] == 1 and np.isfinite(band) and l[i] <= band:
                ep = min(band, o[i]); res = None
                for j in range(i, min(n, i + 60)):
                    sl = ep * 0.70
                    if l[j] <= sl: xp = min(sl, o[j]) * (1 - H.SLIP); fee = H.TAKER; res = 'sl'; break
                    if j > i and h[j] >= mid[j]: xp = max(mid[j], o[j]) if o[j] > mid[j] else mid[j]; fee = H.MAKER; res = 'tp'; break
                if res is None:
                    j = min(n - 1, i + 59); xp = c[j] * (1 - H.SLIP); fee = H.TAKER
                rows.append({'coin': coin, 'entry_ts': df.index[i], 'ret': xp / ep - 1 - H.MAKER - fee, 'bars': j - i + 1})
                i = j + 1
            else:
                i += 1
    tr = pd.DataFrame(rows)
    print(f'\n===== Envelope e={e:.0%} ({len(tr)} Trades) =====')
    seg = H.segments(tr, A, B)
    for k, s in seg.items(): H.evaluate(s, k)
    for k, s in seg.items():
        if len(s): print(f"  Tagesmittel {k.strip()}: {s.groupby(pd.to_datetime(s.entry_ts, utc=True).dt.floor('D')).ret.mean().mean()*100:+.3f} %")
    print(f"  P1 Block-Bootstrap p = {block_bootstrap_p(seg['PRUEF  B bis 14.10.26']):.4f}")
