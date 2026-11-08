# Erkundung 2 (nur < 10.05.2026): Phasentor getrennt nach Richtung bzw. Zeitebene
import numpy as np, pandas as pd
from explore_phase import T, A, C26, replay, show, glob
from claude_filter_phase import _global_gate
stop2 = (T.stop_atr >= 2).values
def grouped(col, days):
    out = np.full(len(T), np.nan)
    for _, g in T.groupby(col):
        v = _global_gate(g, days, min_n=15); out[g.index] = v
    return out
for d in (7, 14):
    gd = grouped('dir', d); gt = grouped('tf', d); gg, _ = glob(d)
    show(f'DIR_{d}d>0', gd > 0); show(f'DIR_{d}d>0 & STOP2', (gd > 0) & stop2)
    show(f'TF_{d}d>0', gt > 0); show(f'TF_{d}d>0 & STOP2', (gt > 0) & stop2)
    show(f'GLOBAL_{d}d>0.1 & STOP2', (gg > .1) & stop2)
