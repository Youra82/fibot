"""Wovon hingen die Monats-Stuetzpunkte (Teil 1) ab?

Je Coin: Stuetzpunkt je Entwicklungsmonat (Mittel der Top-1-%-Parameter im Fenster Vormonat/Monat/
Folgemonat) gegen Marktmerkmale desselben 3-Monats-Fensters. Spearman-Korrelation, Signifikanz per
Permutation mit Blockverschiebung (Autokorrelation der Zeitreihe bleibt erhalten).
Gepoolt: je Coin standardisiert, dann alle 4 Coins zusammen.
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from engine import PARAMS, read_cache
from run import LABELS

HERE = Path(__file__).resolve().parent
OUT = HERE / 'ergebnisse_abhaengigkeit'
COINS = [('APT', '30m'), ('SHIB', '30m'), ('BAT', '1h'), ('DOT', '2h')]
FEATURES = {
    'zeit': 'Zeit (Monatsindex)',
    'vol': 'Schwankung (Tagesrenditen-Std.)',
    'vol_trend': 'Schwankung vs. 6 Monate davor',
    'ret': 'Richtung (Fenster-Rendite)',
    'eff': 'Trend vs. Seitwaerts (Effizienz Tageskurse)',
    'atr': 'ATR % (Strategie-TF)',
    'volume': 'Volumen vs. 6 Monate davor',
    'dd': 'Abstand zum 90-Tage-Hoch',
    'wick': 'Dochtanteil der Kerzen',
}
N_PERM = 2000


def month_features(coin, tf, months):
    df = read_cache(coin, tf)
    day = read_cache(coin, '1d')
    day.index = day.index.tz_convert(None)
    d = df.copy()
    d.index = d.index.tz_convert(None)
    prev = d['close'].shift(1)
    tr = np.maximum.reduce([d['high'] - d['low'], (d['high'] - prev).abs(), (d['low'] - prev).abs()])
    d['atr_pct'] = tr / d['close']
    rng = (d['high'] - d['low']).replace(0, np.nan)
    d['wick'] = 1 - (d['close'] - d['open']).abs() / rng
    dret = np.log(day['close']).diff()
    hi90 = day['high'].rolling(90, min_periods=20).max()
    rows = []
    for m in months:
        a = (m - 1).to_timestamp()
        b = (m + 2).to_timestamp()
        sel_d = (day.index >= a) & (day.index < b)
        sel = (d.index >= a) & (d.index < b)
        prev6 = (day.index >= (m - 7).to_timestamp()) & (day.index < a)
        c = day['close'][sel_d]
        r = dret[sel_d]
        rows.append({
            'vol': r.std(),
            'vol_trend': r.std() / dret[prev6].std(),
            'ret': float(np.log(c.iloc[-1] / c.iloc[0])),
            'eff': abs(np.log(c.iloc[-1] / c.iloc[0])) / r.abs().sum(),
            'atr': d['atr_pct'][sel].mean(),
            'volume': (day['volume'][sel_d].mean() * day['close'][sel_d].mean())
                      / (day['volume'][prev6].mean() * day['close'][prev6].mean()),
            'dd': float((c / hi90[sel_d] - 1).mean()),
            'wick': d['wick'][sel].mean(),
        })
    f = pd.DataFrame(rows, index=[str(m) for m in months])
    f.insert(0, 'zeit', np.arange(len(months), dtype=float))
    return f


def perm_p(x, y, rho, rng):
    n = len(x)
    hits = 0
    for _ in range(N_PERM):
        s = rng.integers(3, n - 3)
        r = spearmanr(x, np.roll(y, s))[0]
        hits += abs(r) >= abs(rho)
    return (hits + 1) / (N_PERM + 1)


def main():
    OUT.mkdir(exist_ok=True)
    rng = np.random.default_rng(20261118)
    per_coin, pooled_x, pooled_y = {}, [], []
    for coin, tf in COINS:
        s = json.loads((HERE / 'ergebnisse' / f'{coin}_{tf}' / 'summary.json').read_text(encoding='utf-8'))
        months = pd.PeriodIndex(s['dev_months'], freq='M')
        y = pd.DataFrame({k: s['raw_points'][k] for k in PARAMS}, index=[str(m) for m in months])
        x = month_features(coin, tf, months)
        ok = x.notna().all(1)
        x, y = x[ok], y[ok]
        rho = pd.DataFrame(index=PARAMS, columns=list(FEATURES), dtype=float)
        p = rho.copy()
        for pk in PARAMS:
            for fk in FEATURES:
                if y[pk].std() == 0:
                    continue
                r = spearmanr(x[fk], y[pk])[0]
                rho.loc[pk, fk] = r
                p.loc[pk, fk] = perm_p(x[fk].to_numpy(), y[pk].to_numpy(), r, rng)
        per_coin[f'{coin}_{tf}'] = {'rho': rho, 'p': p, 'n': len(x)}
        z = lambda t: (t - t.mean()) / t.std(ddof=0).replace(0, np.nan)
        pooled_x.append(z(x).assign(coin=coin)); pooled_y.append(z(y).assign(coin=coin))
        print(f'{coin} {tf}: {len(x)} Monate', flush=True)

    px, py = pd.concat(pooled_x), pd.concat(pooled_y)
    pooled = pd.DataFrame(index=PARAMS, columns=list(FEATURES), dtype=float)
    consistent = pooled.copy()
    for pk in PARAMS:
        for fk in FEATURES:
            ok = px[fk].notna() & py[pk].notna()
            pooled.loc[pk, fk] = spearmanr(px.loc[ok, fk], py.loc[ok, pk])[0]
            signs = [np.sign(per_coin[c]['rho'].loc[pk, fk]) for c in per_coin
                     if np.isfinite(per_coin[c]['rho'].loc[pk, fk])]
            consistent.loc[pk, fk] = max(signs.count(1.0), signs.count(-1.0))

    # Ausgabe: staerkste Zusammenhaenge
    rows = []
    for pk in PARAMS:
        for fk in FEATURES:
            sig = sum(per_coin[c]['p'].loc[pk, fk] < 0.05 for c in per_coin)
            rows.append({'parameter': pk, 'merkmal': fk, 'rho_gepoolt': pooled.loc[pk, fk],
                         'gleiche_richtung': int(consistent.loc[pk, fk]), 'coins_p<0.05': int(sig),
                         **{f'rho_{c}': per_coin[c]['rho'].loc[pk, fk] for c in per_coin}})
    table = pd.DataFrame(rows).sort_values('rho_gepoolt', key=np.abs, ascending=False)
    table.to_csv(OUT / 'zusammenhaenge.csv', index=False, float_format='%.3f')
    pd.set_option('display.width', 250)
    print(table.head(25).to_string(index=False, float_format=lambda v: f'{v:+.2f}'))

    # Zufallserwartung fuer gepoolte |rho|: Merkmale je Coin zirkulaer verschoben
    null = []
    for _ in range(200):
        parts = []
        for coin in px['coin'].unique():
            xs = px[px['coin'] == coin].drop(columns='coin')
            parts.append(pd.DataFrame(np.roll(xs.to_numpy(), rng.integers(3, len(xs) - 3), axis=0),
                                      columns=xs.columns))
        sx = pd.concat(parts).reset_index(drop=True)
        sy = py.drop(columns='coin').reset_index(drop=True)
        null.append(max(abs(spearmanr(sx[fk], sy[pk], nan_policy='omit')[0])
                        for pk in PARAMS for fk in FEATURES if fk != 'zeit'))
    print(f'\nZufall: groesstes gepooltes |rho| (ohne Zeit) im Median {np.median(null):.2f}, '
          f'95-%-Grenze {np.quantile(null, .95):.2f}')

    fig, axes = plt.subplots(1, 5, figsize=(26, 7), sharey=True)
    for ax, (name, mat) in zip(axes, [('alle 4 Coins (gepoolt)', pooled)] +
                               [(c, per_coin[c]['rho']) for c in per_coin]):
        im = ax.imshow(mat.to_numpy(dtype=float), cmap='coolwarm', vmin=-.8, vmax=.8)
        for a in range(len(PARAMS)):
            for b in range(len(FEATURES)):
                v = mat.iloc[a, b]
                if np.isfinite(v):
                    star = ''
                    if name in per_coin and per_coin[name]['p'].iloc[a, b] < 0.05:
                        star = '*'
                    ax.text(b, a, f'{v:+.2f}{star}', ha='center', va='center', fontsize=7)
        ax.set_xticks(range(len(FEATURES)), list(FEATURES), rotation=60, fontsize=8)
        ax.set_yticks(range(len(PARAMS)), [LABELS[k] for k in PARAMS], fontsize=8)
        ax.set_title(name.replace('_', ' '))
    fig.colorbar(im, ax=axes, shrink=.6, label='Spearman rho (* = p<0,05 Permutation)')
    fig.suptitle('Wovon hingen die besten Parameter je Monat ab? (Stuetzpunkte Teil 1 vs. Marktmerkmale)', fontsize=14)
    fig.savefig(OUT / 'abhaengigkeit_heatmap.png', dpi=100, bbox_inches='tight'); plt.close(fig)

    top = table[table['merkmal'] != 'zeit'].head(6)
    fig, axes = plt.subplots(2, 3, figsize=(17, 10))
    colors = {'APT': '#1f5fbf', 'SHIB': '#d9480f', 'BAT': '#2b8a3e', 'DOT': '#7048e8'}
    for ax, (_, row) in zip(axes.flat, top.iterrows()):
        for coin in colors:
            sel = px['coin'] == coin
            ax.scatter(px.loc[sel, row['merkmal']], py.loc[sel, row['parameter']], s=18, color=colors[coin], label=coin)
        ax.set_xlabel(FEATURES[row['merkmal']] + ' (z je Coin)'); ax.set_ylabel(LABELS[row['parameter']] + ' (z je Coin)')
        ax.set_title(f"rho gepoolt {row['rho_gepoolt']:+.2f}, gleiche Richtung {row['gleiche_richtung']}/4")
        ax.grid(alpha=.3)
    axes.flat[0].legend()
    fig.suptitle('Staerkste Zusammenhaenge (ohne Zeit)', fontsize=14)
    fig.tight_layout(); fig.savefig(OUT / 'staerkste_zusammenhaenge.png', dpi=100); plt.close(fig)


if __name__ == '__main__':
    main()
