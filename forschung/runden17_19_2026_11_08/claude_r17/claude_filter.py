# Claudes 5 eigene Filter fuer Runde 17, VOR jeder Rechnung festgelegt und ohne Auswahl eingefroren.
# Mechanismus: (a) Docht-Rueckkehr braucht Luft -> weiter Stop, nahes Ziel; (b) die alte Strategie handelte Long und
# Short gegen den Markt -> Richtung am BTC-Regime ausrichten; (c) EMA200 des eigenen Coins in Handelsrichtung.
import numpy as np
import pandas as pd


def btc_regime(T, btc_daily):
    """+1 = BTC-Vortagesschluss > SMA200, -1 = darunter, 0 = unbekannt. Nur Tage VOR dem Einstiegstag."""
    b = btc_daily.copy(); b.index = pd.to_datetime(b.iloc[:, 0], utc=True); c = b['close'].astype(float)
    reg = np.sign(c - c.rolling(200).mean()).where(c.rolling(200).mean().notna(), 0)
    reg.index = reg.index + pd.Timedelta(days=1)                      # gilt ab dem Folgetag
    day = T.ts.dt.floor('D')
    return reg.reindex(day, method='ffill').fillna(0).to_numpy()


def masks(T, btc_daily):
    reg = btc_regime(T, btc_daily)
    btc_dir = np.where(T['dir'].eq('long'), reg > 0, reg < 0)
    stop2 = (T.stop_atr >= 2).to_numpy()
    out = {
        'C1_EMA_STOP2': T.ema_ok.to_numpy() & stop2,
        'C2_BTC_DIR': btc_dir,
        'C3_BTC_DIR_STOP2': btc_dir & stop2,
        'C4_WIDE_NEAR': stop2 & (T.rr <= 3).to_numpy(),
        'C5_BTC_DIR_EMA_STOP2': btc_dir & T.ema_ok.to_numpy() & stop2,
    }
    el = T.eligible.to_numpy()
    return {k: v & el for k, v in out.items()}
