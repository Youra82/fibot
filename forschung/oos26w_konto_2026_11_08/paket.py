# Gesamtpaket mit >= 1 Trade/Tag (PREREG.md).  python paket.py auswahl <DATEN> | python paket.py oos <DATEN>
import gc, hashlib, json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', '..', 'src'))
from fibot.strategy import wick_mtf as W  # noqa: E402
from fibot.analysis.wick_mtf_backtest import simulate  # noqa: E402

T_TRAIN = pd.Timestamp('2024-05-10', tz='UTC'); T0 = pd.Timestamp('2026-05-10', tz='UTC')
WARM = pd.Timestamp('2024-03-01', tz='UTC')
TFS5 = (.5, 1, 2, 4, 6)
VARIANTS = {
    'V0': dict(strategies=[(h, 'R25', d) for h in (1, 2, 4) for d in (7, 11)], mtf=True, btc50=True),
    'V1': dict(strategies=[(h, 'R25', d) for h in TFS5 for d in (5, 7, 11)], mtf=True, btc50=True),
    'V2': dict(strategies=[(h, 'R25', d) for h in TFS5 for d in (5, 7, 11)], mtf=True, btc50=False),
    'V3': dict(strategies=[(h, 'FIB', d) for h in TFS5 for d in (5, 7, 11)], mtf=True, btc50=True),
    'V4': dict(strategies=[(h, 'FIB', d) for h in TFS5 for d in (5, 7, 11)], mtf=True, btc50=False),
    'V5': dict(strategies=[(h, 'FIB', d) for h in TFS5 for d in (5, 7, 11)], mtf=False, btc50=True),
    'V6': dict(strategies=[(h, 'FIB', d) for h in TFS5 for d in (5, 7, 11)], mtf=False, btc50=False),
}


def rd(p, lo, hi):
    d = pd.read_csv(p); d.index = pd.to_datetime(d.iloc[:, 0], utc=True)
    d = d[(d.index >= lo) & (d.index < hi)] if hi is not None else d[d.index >= lo]
    d = d[['open', 'high', 'low', 'close']].astype(float).sort_index()
    return d[~d.index.duplicated(keep='last')]


def universe(root):
    sets = [{f.split('-')[0] for f in os.listdir(os.path.join(root, f'daten_voll_{tf}'))} for tf in ('30m', '1h', '2h', '4h', '6h')]
    return sorted(set.intersection(*sets) - W.EXCLUDE)


def load(root, hi):
    names = universe(root); raw, natives = {}, {}
    for n in names:
        d = rd(os.path.join(root, 'daten_voll_30m', f'{n}-USDT-USDT_30m.csv'), WARM, hi)
        if len(d) < 200:
            continue
        raw[n] = d
        for tf in ('1h', '2h', '4h', '6h'):
            natives[n, tf] = rd(os.path.join(root, f'daten_voll_{tf}', f'{n}-USDT-USDT_{tf}.csv'), WARM - pd.Timedelta(days=20), hi)
    daily = rd(os.path.join(root, 'daten_voll_BTC_1d.csv'), pd.Timestamp('2020-01-01', tz='UTC'), hi)
    end = max(d.index.max() for d in raw.values()) + pd.Timedelta(minutes=30)
    idx = pd.date_range(min(d.index.min() for d in raw.values()), end - pd.Timedelta(minutes=30), freq='30min')
    return raw, natives, daily, idx, end


def run(raw, natives, daily, idx, cfg, start, end):
    data = W.build_arrays(raw, natives, daily, idx, **cfg)
    res, cv, led = simulate(data, start, end)
    days = (end - start).total_seconds() / 86400
    res['fills_per_day'] = res['trades'] / days; res['names'] = len(data['names'])
    del data; gc.collect()
    return res, cv, led


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


if __name__ == '__main__':
    mode, root = sys.argv[1], sys.argv[2]
    if mode == 'auswahl':
        assert not os.path.exists(os.path.join(HERE, 'auswahl.json'))
        raw, natives, daily, idx, end = load(root, T0)
        assert end <= T0 + pd.Timedelta(minutes=30) and idx[-1] < T0
        out = {}
        for vid, cfg in VARIANTS.items():
            r, cv, led = run(raw, natives, daily, idx, cfg, T_TRAIN, T0)
            out[vid] = {k: r[k] for k in ('end', 'cagr_pct', 'dd_pct', 'trades', 'fills_per_day', 'exits', 'liquidations', 'names')}
            cv.to_csv(os.path.join(HERE, f'train_{vid}_equity.csv'), index=False); led.to_csv(os.path.join(HERE, f'train_{vid}_trades.csv'), index=False)
            print(vid, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out[vid].items()}, flush=True)
        ok = [v for v, r in out.items() if r['dd_pct'] <= 30 and r['fills_per_day'] >= 1 and r['cagr_pct'] > 0]
        rule = 'primaer'
        if not ok:
            ok = [v for v, r in out.items() if r['dd_pct'] <= 30 and r['cagr_pct'] > 10]; rule = 'ersatz (max Fills/Tag)'
            ok.sort(key=lambda v: (-out[v]['fills_per_day'], out[v]['dd_pct'], v))
        else:
            ok.sort(key=lambda v: (-out[v]['cagr_pct'], out[v]['dd_pct'], v))
        sel = ok[0] if ok else None
        json.dump(dict(t0=str(T0), selected=sel, rule=rule, train=out, config=VARIANTS.get(sel),
                       code_sha256=sha(__file__), prereg_sha256=sha(os.path.join(HERE, 'PREREG.md'))),
                  open(os.path.join(HERE, 'auswahl.json'), 'w'), indent=1, default=str)
        open(os.path.join(HERE, 'auswahl.sha256'), 'w').write(sha(os.path.join(HERE, 'auswahl.json')))
        print('AUSWAHL:', sel, rule)
    else:
        A = json.load(open(os.path.join(HERE, 'auswahl.json')))
        assert sha(os.path.join(HERE, 'auswahl.json')) == open(os.path.join(HERE, 'auswahl.sha256')).read().strip()
        assert A['code_sha256'] == sha(__file__) and A['prereg_sha256'] == sha(os.path.join(HERE, 'PREREG.md'))
        assert A['selected'], 'keine Auswahl -> kein OOS'
        raw, natives, daily, idx, end = load(root, None)
        r, cv, led = run(raw, natives, daily, idx, VARIANTS[A['selected']], T0, end)
        cv.to_csv(os.path.join(HERE, 'oos_equity.csv'), index=False); led.to_csv(os.path.join(HERE, 'oos_trades.csv'), index=False)
        ret = r['end'] / 34 - 1
        passed = ret > .10 and r['dd_pct'] <= 30 and r['trades'] >= 182
        cv['m'] = pd.to_datetime(cv.ts, utc=True).dt.strftime('%Y-%m')
        monthly = cv.groupby('m').equity.last().pct_change().fillna(cv.groupby('m').equity.last().iloc[0] / 34 - 1)
        res = dict(selected=A['selected'], ret_pct=100 * ret, dd_pct=r['dd_pct'], fills=r['trades'], fills_per_day=r['fills_per_day'],
                   exits=r['exits'], liquidations=r['liquidations'], winners=float((led.pnl > 0).mean()) if len(led) else None,
                   monthly_pct=(monthly * 100).round(2).to_dict(), bestanden=bool(passed), end=r['end_time'])
        json.dump(res, open(os.path.join(HERE, 'oos_ergebnis.json'), 'w'), indent=1, default=str)
        print(json.dumps(res, indent=1, default=str))
