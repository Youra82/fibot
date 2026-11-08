"""Erzeugt die Status-Grafiken der README aus den Forschungsdaten vom 08.11.2026.

    .venv/Scripts/python.exe docs/make_status_plots.py

Quellen (alle unter forschung/):
- kontostand_2026_11_08/ergebnis_pool38.txt       -> DD bei Config-Risiko (1-3 %)
- kontostand_2026_11_08/ergebnis_bremse_1pct.txt  -> DD bei 1 % fest und 1 % + Kontoverlauf
- dynamisches_ziel_2026_11_08/pfade.pkl           -> R je Trade nach Stop-Abstand (erzeugt von pfade.py)

Ausgabe: docs/img/risikosteuerung.png, docs/img/edge_verfall.png
"""
import re
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
F = ROOT / 'forschung'
IMG = ROOT / 'docs' / 'img'

# Referenz-Palette (kategorisch, feste Reihenfolge), Text in Texttönen
S1, S2, S3 = '#2a78d6', '#eb6834', '#1baf7a'
FG, FG2, GRID, BG = '#0b0b0b', '#52514e', '#e6e5e1', '#fcfcfb'
PERIODS = ['2024', '2025', '01.01.-09.05.2026', 'OOS 10.05.-08.11.2026', 'ab 15.10.2026']
PLABEL = ['2024', '2025', '01–05/2026', '10.05.–08.11.\n2026 (OOS)', 'ab 15.10.\n(live-Zeitraum)']

plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.edgecolor': GRID,
                     'axes.labelcolor': FG2, 'xtick.color': FG2, 'ytick.color': FG2,
                     'axes.spines.top': False, 'axes.spines.right': False})


def _dd_config_risk():
    txt = (F / 'kontostand_2026_11_08' / 'ergebnis_pool38.txt').read_text(encoding='utf-8')
    out = {}
    for p in PERIODS:
        block = txt.split('\n' + p + '\n', 1)[1]
        m = re.search(r'Config-Risiko \(1-3 %\)\s+\S+\s+\S+ %\s+(\d+) %', block)
        out[p] = int(m.group(1))
    return out


def _dd_1pct():
    txt = (F / 'kontostand_2026_11_08' / 'ergebnis_bremse_1pct.txt').read_text(encoding='utf-8')
    pool = txt.split('pool38.py', 1)[1].split('live17.py', 1)[0]
    fest, dyn = {}, {}
    for p in PERIODS:
        m = re.search(re.escape(p) + r'\s+1 % fest:\s+\S+ % DD\s+(\d+) % \| 1 % \+ Bremse:\s+\S+ % DD\s+(\d+) %', pool)
        fest[p], dyn[p] = int(m.group(1)), int(m.group(2))
    return fest, dyn


def risikosteuerung():
    cfg = _dd_config_risk()
    fest, dyn = _dd_1pct()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.3), gridspec_kw={'width_ratios': [1, 2.1]})
    fig.patch.set_facecolor(BG)
    for a in (a1, a2):
        a.set_facecolor(BG)
        a.grid(axis='y', color=GRID, lw=0.8)
        a.set_axisbelow(True)

    # links: Kontoverlauf-Faktor = max(0,25; 1 - DD/30 %)
    dd = np.linspace(0, 40, 401)
    fac = np.maximum(0.25, 1 - dd / 30)
    a1.plot(dd, fac, color=S1, lw=2)
    for x, lab in ((0, '1 % Risiko'), (15, '0,5 %'), (22.5, '0,25 %')):
        y = max(0.25, 1 - x / 30)
        a1.plot(x, y, 'o', ms=7, color=S1, mec=BG, mew=2)
        a1.annotate(lab, (x, y), xytext=(6, 6), textcoords='offset points', color=FG, fontsize=9)
    a1.set_xlim(0, 40)
    a1.set_ylim(0, 1.1)
    a1.set_xlabel('Abstand vom Konto-Höchststand (%)')
    a1.set_ylabel('Faktor auf das 1-%-Risiko')
    a1.set_title('Kontoverlauf-Faktor', loc='left', color=FG, fontsize=11, fontweight='bold')

    # rechts: max. Drawdown je Zeitraum, Pool 38 Configs
    x = np.arange(len(PERIODS))
    w = 0.26
    series = [('Config-Risiko (1–3 %)', cfg, S1), ('1 % fest', fest, S2), ('1 % + Kontoverlauf', dyn, S3)]
    for k, (lab, vals, c) in enumerate(series):
        v = [vals[p] for p in PERIODS]
        bars = a2.bar(x + (k - 1) * w, v, w - 0.03, color=c, label=lab, edgecolor=BG, linewidth=1)
        for b, val in zip(bars, v):
            a2.text(b.get_x() + b.get_width() / 2, val + 1, f'{val}', ha='center', va='bottom', fontsize=8, color=FG2)
    a2.set_xticks(x, PLABEL, fontsize=9)
    a2.set_ylabel('max. Drawdown (%)')
    a2.set_ylim(0, 70)
    a2.legend(frameon=False, loc='upper left', ncol=3, fontsize=9)
    a2.set_title('Max. Drawdown je Zeitraum (38 Konfluenz-Configs, ein Konto)',
                 loc='left', color=FG, fontsize=11, fontweight='bold')
    fig.text(0.01, 0.01, 'Vereinfachte Kontorechnung (forschung/kontostand_2026_11_08). Configs mit Rückblick gewählt: '
             'Renditen dort überzeichnet, aussagekräftig ist der DD-Vergleich.', fontsize=8, color=FG2)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(IMG / 'risikosteuerung.png', dpi=130, facecolor=BG)
    plt.close(fig)


def edge_verfall():
    P = pd.read_pickle(F / 'dynamisches_ziel_2026_11_08' / 'pfade.pkl')
    P = P[(P.eligible == True) & (P.trend_ok == True)]  # noqa: E712
    edges = [pd.Timestamp(d, tz='UTC') for d in ('2023-01-01', '2025-01-01', '2026-01-01', '2026-05-10',
                                                  '2026-10-15', '2026-11-09')]
    seg = ['2023–24', '2025', '01.01.–09.05.\n2026', '10.05.–14.10.\n2026', 'ab 15.10.\n2026']
    P = P.assign(seg=pd.cut(P.ts, edges, labels=seg),
                 stop=pd.cut(P.stop_atr, [0, 1.09, 1.85, 99], labels=['eng (< 1,1 ATR)', 'mittel', 'weit (> 1,85 ATR)']))
    t = P.pivot_table(index='stop', columns='seg', values='S_K', aggfunc='mean', observed=True)
    n = P.pivot_table(index='stop', columns='seg', values='S_K', aggfunc='size', observed=True)

    fig, a = plt.subplots(figsize=(11, 4.3))
    fig.patch.set_facecolor(BG)
    a.set_facecolor(BG)
    a.grid(axis='y', color=GRID, lw=0.8)
    a.set_axisbelow(True)
    x = np.arange(len(seg))
    w = 0.26
    for k, (row, c) in enumerate(zip(t.index, (S1, S2, S3))):
        v = t.loc[row, seg].values
        bars = a.bar(x + (k - 1) * w, v, w - 0.03, color=c, label=row, edgecolor=BG, linewidth=1)
        for b, val in zip(bars, v):
            off = 0.015 if val >= 0 else -0.015
            a.text(b.get_x() + b.get_width() / 2, val + off, f'{val:+.2f}'.replace('.', ','), ha='center',
                   va='bottom' if val >= 0 else 'top', fontsize=8, color=FG2)
    a.axhline(0, color=FG2, lw=1)
    a.axvspan(2.5, 4.5, color='#f0efec', zorder=0)
    a.text(2.55, 0.43, 'Edge-Verfall seit Mai', fontsize=9, color=FG2)
    a.set_xticks(x, seg, fontsize=9)
    a.set_xlim(-0.5, 4.5)
    a.set_ylim(-0.55, 0.5)
    a.set_ylabel('Ø Netto-R je Trade')
    a.legend(frameon=False, loc='lower left', ncol=3, fontsize=9, title='Stop-Abstand', title_fontsize=9)
    a.set_title('Konfluenz-Signale (Strukturstop + Strukturziel, Trendfilter an): Ø R je Trade nach Stop-Abstand',
                loc='left', color=FG, fontsize=11, fontweight='bold')
    nmin = int(n.values.min())
    fig.text(0.01, 0.01, f'forschung/dynamisches_ziel_2026_11_08/pfade.pkl, {int(n.values.sum())} Trades, '
             f'mind. {nmin} je Balken. Enge Stopps trugen die Edge bis April – seit Mai verlieren sie am stärksten.',
             fontsize=8, color=FG2)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(IMG / 'edge_verfall.png', dpi=130, facecolor=BG)
    plt.close(fig)
    print(t.round(3).to_string())
    print(n.to_string())


if __name__ == '__main__':
    risikosteuerung()
    edge_verfall()
    print('ok:', IMG / 'risikosteuerung.png', IMG / 'edge_verfall.png')
