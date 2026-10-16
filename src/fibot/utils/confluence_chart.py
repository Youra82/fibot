# src/fibot/utils/confluence_chart.py
# Chart der Konfluenz-Strategie (Telegram bei neuer Order und show_chart.py).

import os

import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
TMP_DIR = os.path.join(PROJECT_ROOT, 'artifacts', 'tmp')


def confluence_chart(df, config: dict, symbol: str, timeframe: str):
    """Chart der Konfluenz-Strategie: aktueller Kanal (Stand letzte geschlossene Kerze)
    und -- falls ein Setup besteht -- die Limit-Order fuer die laufende Kerze mit SL/TP."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from fibot.strategy.confluence_logic import plan_both, plan_next_order

    from fibot.strategy.confluence_logic import strategy_params

    plan = plan_next_order(df, config)
    lo, sh = plan_both(df, config)
    n = len(df)
    imp = None   # Impuls A->B des aktuellen Setups (Indizes + Preise)
    if plan:
        pl = lo if plan['direction'] == 'long' else sh
        A, B = int(pl['A'][n]), int(pl['B'][n])
        if plan['direction'] == 'long':
            imp = (A, B, float(df['low'].iloc[A]), float(df['high'].iloc[B]))
        else:
            imp = (A, B, float(df['high'].iloc[A]), float(df['low'].iloc[B]))
    x0 = max(0, min(n - 160, (imp[0] - 10) if imp else n))
    view = df.iloc[x0:]
    fig, ax = plt.subplots(figsize=(11, 5), dpi=110)
    for k, (o, h, l, c) in enumerate(view[['open', 'high', 'low', 'close']].values):
        col = '#26a69a' if c >= o else '#ef5350'
        ax.plot([k, k], [l, h], color=col, lw=0.8)
        ax.add_patch(plt.Rectangle((k - 0.3, min(o, c)), 0.6, max(abs(c - o), 1e-12), color=col))
    drew = False
    for d, pl in (('long', lo), ('short', sh)):
        ch = pl['ch']
        j = n - 1
        if not ch['valid'][j]:
            continue
        a0, sl_, ic, w = int(ch['a_pos'][j]), ch['slope'][j], ch['icpt'][j], ch['width'][j]
        xs = np.array([max(a0, x0), n])
        base = ic + sl_ * xs
        lower, upper = (base, base + w) if d == 'long' else (-(base + w), -base)
        for ys in (lower, upper):
            ax.plot(xs - x0, ys, color='#2c3340' if d == 'long' else '#8e44ad', lw=1.8)
        drew = True
    title = f"FIBOT Konfluenz | {symbol} ({timeframe})"
    if plan:
        k = n - x0
        p = strategy_params(config)
        A, B, Ap, Bp = imp
        diff = Bp - Ap                      # Long: positiv (Tief A -> Hoch B), Short: negativ
        lvl = lambda r: Bp - r * diff
        z_a, z_b = sorted((lvl(p['fib_lo']), lvl(p['fib_hi'])))
        ax.fill_between([B - x0, k + 2], z_a, z_b, color='#f6e7c4', alpha=0.7, zorder=0)
        for r in (p['fib_lo'], p['fib_hi'], p['fib_sl']):
            ax.plot([B - x0, k + 2], [lvl(r), lvl(r)], color='#c98500', ls='--', lw=1)
            ax.text(B - x0 + 0.5, lvl(r), f'{r * 100:.1f} %', color='#c98500', fontsize=8, va='bottom')
        ax.plot([A - x0, B - x0], [Ap, Bp], color='#555555', ls=':', lw=1.2)
        span = abs(diff)
        for idx, price, lab, below in ((A, Ap, 'A', plan['direction'] == 'long'),
                                       (B, Bp, 'B', plan['direction'] != 'long')):
            ax.scatter([idx - x0], [price], color='#15171b', s=28, zorder=6)
            ax.text(idx - x0, price + (-0.07 if below else 0.04) * span, lab, ha='center',
                    fontsize=13, fontweight='bold', color='#15171b', zorder=6)
        for price, col, lab in ((plan['tp'], '#0ca30c', 'TP'), (plan['limit'], '#2a78d6', 'Limit'),
                                (plan['sl'], '#d03b3b', 'SL')):
            ax.plot([k - 6, k + 2], [price, price], color=col, lw=2.2)
            ax.text(k + 2.5, price, f' {lab} {price:.6g}', color=col, va='center', fontsize=9)
        title += f" | {plan['direction'].upper()} Limit {plan['limit']:.6g}  R:R {plan['rr']:.2f}"
    else:
        title += ' | kein Setup fuer die laufende Kerze' + ('' if drew else ' (kein gueltiger Kanal)')
    ax.set_title(title, fontsize=10, loc='left')
    ax.set_xlim(-1, len(view) + 14)
    ax.grid(alpha=0.2)
    os.makedirs(TMP_DIR, exist_ok=True)
    path = os.path.join(TMP_DIR, f"konfluenz_{symbol.replace('/', '').replace(':', '')}_{timeframe}.png")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path, plan
