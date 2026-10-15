# fibot/docs/make_illustrations.py
# Erzeugt die README-Illustrationen (SVG, eigenstaendig, heller Hintergrund fuer
# helles und dunkles GitHub-Theme).  Aufruf:  python docs/make_illustrations.py

import os
import random

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'img')
os.makedirs(OUT, exist_ok=True)

C = {
    'bg': '#ffffff', 'card': '#f7f8fa', 'fg': '#15171b', 'fg2': '#4b505a', 'muted': '#7d838e',
    'grid': '#eceef2', 'candle': '#5b616c', 'chan': '#2c3340', 'fib': '#c98500', 'zone': '#f6e7c4',
    'entry': '#2a78d6', 'sl': '#d03b3b', 'tp': '#0ca30c', 'line': '#d9dde3',
}
FONT = "font-family=\"'Segoe UI', 'Helvetica Neue', Arial, sans-serif\""


def svg(w, h, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" {FONT}>'
            f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="14" fill="{C["bg"]}" stroke="{C["line"]}"/>'
            f'{body}</svg>')


def t(x, y, s, size=13, color=None, weight=400, anchor='start'):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color or C["fg2"]}" '
            f'font-weight="{weight}" text-anchor="{anchor}">{s}</text>')


# ---------------------------------------------------------------------------
# 1) Konfluenz-Prinzip
# ---------------------------------------------------------------------------
def konfluenz():
    W, H = 1000, 520
    PL, PR, PT, PB = 30, 250, 70, 40
    L = lambda tt: 100 + 0.5 * tt
    U = lambda tt: L(tt) + 32.5
    A, B = (6, 103.2), (30, 147.3)
    diff = B[1] - A[1]
    f = lambda r: B[1] - r * diff
    tC, ENTRY = 40, L(40)
    SL = min(f(0.786), L(40)) - 1.4
    TP = U(56)
    t0, t1, p0, p1 = -22, 62, 86, 170
    x = lambda tt: PL + (tt - t0) / (t1 - t0) * (W - PL - PR)
    y = lambda p: PT + (p1 - p) / (p1 - p0) * (H - PT - PB)
    key = [(-22, 104), (-18, 91.6), (-6, 129.6), (6, 103.6), (30, 146.8), (34, 138), (37, 129), (40, 120.6),
           (44, 128), (50, 141), (56, 159.6), (60, 154)]

    def lerp(tt):
        for (a, pa), (b, pb) in zip(key, key[1:]):
            if tt <= b:
                return pa + (pb - pa) * (tt - a) / (b - a)
        return key[-1][1]
    rnd = random.Random(7)
    out = [t(30, 38, 'Fibo-Kanal-Konfluenz', 22, C['fg'], 700),
           t(30, 58, 'Long im steigenden Kanal (Short spiegelbildlich im fallenden Kanal)', 13, C['muted'])]
    for p in range(90, 171, 10):
        out.append(f'<line x1="{PL}" x2="{W - PR}" y1="{y(p):.1f}" y2="{y(p):.1f}" stroke="{C["grid"]}"/>')
    out.append(f'<rect x="{x(B[0]):.1f}" y="{y(f(0.5)):.1f}" width="{x(60) - x(B[0]):.1f}" '
               f'height="{y(f(0.618)) - y(f(0.5)):.1f}" fill="{C["zone"]}"/>')
    for fn in (L, U):
        out.append(f'<line x1="{x(-22):.1f}" x2="{x(60):.1f}" y1="{y(fn(-22)):.1f}" y2="{y(fn(60)):.1f}" '
                   f'stroke="{C["chan"]}" stroke-width="2.2"/>')
    for tt, p in ((-18, L(-18)), (6, L(6)), (-6, U(-6)), (30, U(30))):
        out.append(f'<circle cx="{x(tt):.1f}" cy="{y(p):.1f}" r="6" fill="none" stroke="{C["chan"]}" stroke-width="1.6"/>')
    for r, lab, strong in ((0.5, '50 %', False), (0.618, '61,8 %', True), (0.786, '78,6 %', False)):
        p = f(r)
        out.append(f'<line x1="{x(A[0]):.1f}" x2="{x(60):.1f}" y1="{y(p):.1f}" y2="{y(p):.1f}" stroke="{C["fib"]}" '
                   f'stroke-width="{2 if strong else 1.2}" {"" if strong else "stroke-dasharray=\"6 5\""}/>')
        out.append(t(x(B[0]) + 4, y(p) - 5, f'{lab}', 12, C['fib'], 700 if strong else 400))
    prev = lerp(-22)
    cw = (x(1) - x(0)) * 0.56
    for tt in range(-21, 61):
        c = lerp(tt) + rnd.uniform(-1.1, 1.1)
        o = prev
        hi = max(o, c) + abs(rnd.uniform(0, 1.2)) + 0.3
        lo = min(o, c) - abs(rnd.uniform(0, 1.2)) - 0.3
        if tt == 40:
            lo = 119.8
        if tt == 56:
            hi = max(hi, TP + 0.4)
        cx = x(tt)
        out.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(hi):.1f}" y2="{y(lo):.1f}" stroke="{C["candle"]}"/>')
        top, bh = y(max(o, c)), max(1.0, abs(y(o) - y(c)))
        out.append(f'<rect x="{cx - cw / 2:.1f}" y="{top:.1f}" width="{cw:.1f}" height="{bh:.1f}" '
                   f'fill="{C["bg"] if c >= o else C["candle"]}" stroke="{C["candle"]}"/>')
        prev = c
    out.append(f'<line x1="{x(A[0]):.1f}" x2="{x(B[0]):.1f}" y1="{y(A[1]):.1f}" y2="{y(B[1]):.1f}" '
               f'stroke="{C["fg2"]}" stroke-dasharray="3 3"/>')
    for (tt, p), lab, dy in ((A, 'A', 22), (B, 'B', -12)):
        out.append(f'<circle cx="{x(tt):.1f}" cy="{y(p):.1f}" r="4.5" fill="{C["fg"]}"/>')
        out.append(t(x(tt) - 5, y(p) + dy, lab, 16, C['fg'], 800))
    out.append(f'<line x1="{x(B[0] + 1):.1f}" x2="{x(tC):.1f}" y1="{y(ENTRY):.1f}" y2="{y(ENTRY):.1f}" '
               f'stroke="{C["entry"]}" stroke-width="2.2" stroke-dasharray="8 5"/>')
    te = 56
    out.append(f'<rect x="{x(tC):.1f}" y="{y(TP):.1f}" width="{x(te) - x(tC):.1f}" height="{y(ENTRY) - y(TP):.1f}" '
               f'fill="{C["tp"]}" fill-opacity="0.12"/>')
    out.append(f'<rect x="{x(tC):.1f}" y="{y(ENTRY):.1f}" width="{x(te) - x(tC):.1f}" height="{y(SL) - y(ENTRY):.1f}" '
               f'fill="{C["sl"]}" fill-opacity="0.12"/>')
    for p, col in ((TP, C['tp']), (SL, C['sl']), (ENTRY, C['entry'])):
        out.append(f'<line x1="{x(tC):.1f}" x2="{x(te):.1f}" y1="{y(p):.1f}" y2="{y(p):.1f}" stroke="{col}" stroke-width="2"/>')
    out.append(t(x(te) + 6, y(TP) - 6, 'TP', 12, C['tp'], 700))
    out.append(t(x(te) + 6, y(ENTRY) + 4, 'Entry', 12, C['entry'], 700))
    out.append(t(x(te) + 6, y(SL) + 4, 'SL', 12, C['sl'], 700))
    rr = (TP - ENTRY) / (ENTRY - SL)
    cx, cy = x(tC), y(ENTRY)
    out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="14" fill="none" stroke="{C["entry"]}" stroke-width="2.4"/>')
    out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" fill="{C["entry"]}"/>')
    out.append(t(x(-21), y(U(-21)) - 10, 'obere Kanallinie', 13, C['fg'], 700))
    out.append(t(x(-12), y(L(-12)) + 24, 'untere Kanallinie', 13, C['fg'], 700))

    def step(n, sx, sy):
        return (f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="12" fill="{C["entry"]}"/>'
                + t(sx, sy + 4.5, str(n), 13, '#ffffff', 800, 'middle'))
    out += [step(1, x(18), y((A[1] + B[1]) / 2) - 16), step(2, x(-12), y(U(-12)) - 30),
            step(3, cx - 30, cy + 28), step(4, x(te) - 16, y(TP) - 18)]
    # Legende rechts
    lx = W - PR + 40
    out.append(f'<line x1="{lx - 20}" x2="{lx - 20}" y1="{PT}" y2="{H - PB}" stroke="{C["line"]}"/>')
    items = [(1, 'Impuls', ['Swing-Tief A → Swing-Hoch B']),
             (2, 'Kanal', ['je Linie ≥ 2 Berührungen,', 'kein Schlusskurs außerhalb']),
             (3, 'Konfluenz', ['61,8 % trifft die untere', 'Kanallinie: dort wartet', 'eine Limit-Order im Voraus']),
             (4, 'Ausstieg', ['TP an der oberen Kanallinie,', 'SL unter 78,6 % / Linie'])]
    yy = PT + 10
    for n, head, lines in items:
        out.append(step(n, lx + 2, yy))
        out.append(t(lx + 22, yy + 5, head, 14, C['fg'], 700))
        for k, ln in enumerate(lines):
            out.append(t(lx + 22, yy + 25 + k * 18, ln, 12, C['fg2']))
        yy += 34 + 18 * len(lines) + 14
    out.append(t(lx - 6, yy + 10, f'Chance-Risiko im Bild ≈ {rr:.1f} : 1'.replace('.', ','), 13, C['fg'], 700))
    return svg(W, H, ''.join(out))


# ---------------------------------------------------------------------------
# 2) Gesamtablauf: Pipeline -> Ergebnisse -> woechentlicher Optimizer -> Live
# ---------------------------------------------------------------------------
def box(x, y, w, h, title, lines, accent):
    s = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{C["card"]}" stroke="{C["line"]}"/>',
         f'<rect x="{x}" y="{y}" width="6" height="{h}" rx="3" fill="{accent}"/>',
         t(x + 20, y + 30, title, 16, C['fg'], 700)]
    for i, ln in enumerate(lines):
        s.append(t(x + 20, y + 56 + i * 21, ln, 13, C['fg2']))
    return ''.join(s)


def arrow(x1, y1, x2, y2, label=None):
    s = [f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{C["muted"]}" stroke-width="2" marker-end="url(#ah)"/>']
    if label:
        s.append(t((x1 + x2) / 2, (y1 + y2) / 2 - 8, label, 12, C['muted'], 400, 'middle'))
    return ''.join(s)


DEFS = (f'<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
        f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{C["muted"]}"/></marker></defs>')


def ablauf():
    W, H = 1000, 460
    o = [DEFS, t(30, 38, 'Ablauf: von der Optimierung bis zum Live-Trade', 22, C['fg'], 700)]
    o.append(box(30, 70, 290, 165, 'run_pipeline.sh', [
        'Optuna je Coin / Timeframe', 'optimiert NUR auf In-Sample', 'testet danach unverändert auf OOS',
        '→ configs/config_*.json'], C['entry']))
    o.append(box(355, 70, 290, 165, 'show_results.sh', [
        '1  Einzel-Analyse', '2  Manuelles Portfolio', '3  Auto-Portfolio (greedy, Calmar)',
        '4  Interaktive Charts mit Kanal'], C['fib']))
    o.append(box(680, 70, 290, 165, 'Auto-Optimizer (wöchentl.)', [
        'auto_optimizer_scheduler.py', 'Modus 3 auf allen Configs', 'schreibt active_strategies',
        'Telegram: Portfolio + Excel'], C['tp']))
    o.append(box(30, 275, 940, 165, 'Live: master_runner.py alle 15 Minuten', [
        'je aktiver Strategie: abgeschlossene Kerzen laden → plan_next_order() (dieselbe Funktion wie im Backtest)',
        'kein Setup → nichts tun   |   Setup → Limit-Order mit angehängtem SL + TP legen',
        'neue Kerze → Order auf die neue Kanalposition nachziehen   |   Fill → Bitget aktiviert SL/TP sofort',
        'Position läuft → Self-Repair prüft SL/TP   |   Position zu → aufräumen, nächster Impuls'], C['sl']))
    o.append(arrow(320, 152, 352, 152))
    o.append(arrow(645, 152, 677, 152))
    o.append(arrow(825, 235, 825, 272))
    o.append(t(835, 258, 'settings.json', 12, C['muted']))
    return svg(W, H, ''.join(o))


# ---------------------------------------------------------------------------
# 3) Live-Orderzyklus einer Strategie
# ---------------------------------------------------------------------------
def zyklus():
    W, H = 1000, 340
    o = [DEFS, t(30, 34, 'Live-Zyklus einer Strategie (alle 15 Minuten)', 22, C['fg'], 700)]
    nodes = [
        (30, 'Kein Setup', ['plan_next_order()', 'liefert nichts'], C['muted']),
        (270, 'Order wartet', ['Limit am Konfluenz-', 'punkt + SL/TP'], C['entry']),
        (510, 'Position offen', ['SL/TP von Bitget', 'Self-Repair prüft'], C['tp']),
        (750, 'Geschlossen', ['TP oder SL', 'Impuls B verbraucht'], C['sl']),
    ]
    for x, title, lines, col in nodes:
        o.append(box(x, 80, 196, 120, title, lines, col))
    o.append(arrow(228, 140, 268, 140))
    o.append(arrow(468, 140, 508, 140))
    o.append(arrow(708, 140, 748, 140))
    o.append(f'<path d="M848,200 C848,290 128,290 128,202" fill="none" stroke="{C["muted"]}" stroke-width="2" '
             f'stroke-dasharray="5 4" marker-end="url(#ah)"/>')
    o.append(t(500, 300, 'nächster Impuls / nächstes Setup', 12, C['muted'], 400, 'middle'))
    o.append(f'<path d="M340,80 C340,58 420,58 420,78" fill="none" stroke="{C["entry"]}" stroke-width="2" marker-end="url(#ah)"/>')
    o.append(t(380, 52, 'neue Kerze: Preis nachziehen', 12, C['entry'], 400, 'middle'))
    o.append(t(248, 128, 'Setup', 11, C['muted'], 400, 'middle'))
    o.append(t(488, 128, 'Fill', 11, C['muted'], 400, 'middle'))
    o.append(t(728, 128, 'TP/SL', 11, C['muted'], 400, 'middle'))
    return svg(W, H, ''.join(o))


for name, fn in (('konfluenz.svg', konfluenz), ('ablauf.svg', ablauf), ('live_zyklus.svg', zyklus)):
    with open(os.path.join(OUT, name), 'w', encoding='utf-8') as fh:
        fh.write(fn())
    print('geschrieben:', name)
