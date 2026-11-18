#!/usr/bin/env python3
"""Build diverse, robust config variants for FiBot's proven markets using CUDA."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))


MARKETS = (
    ('APT/USDT:USDT', '30m', '2023-04-08', 'config_APTUSDTUSDT_30m_fib.json'),
    ('APT/USDT:USDT', '1h', '2023-04-08', 'config_APTUSDTUSDT_1h_fib.json'),
    ('BAT/USDT:USDT', '1h', '2023-04-08', 'config_BATUSDTUSDT_1h_fib.json'),
    ('DOT/USDT:USDT', '2h', '2023-04-08', 'config_DOTUSDTUSDT_2h_fib.json'),
)


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def base_params(config: dict) -> dict:
    strategy = config['strategy']
    return {
        'fib_hi': strategy['fib_hi'], 'fib_sl': strategy['fib_sl'],
        'max_age_mult': strategy.get('max_age_mult') or 0.0,
        'pivot_k': strategy['pivot_k'], 'window': strategy['window'],
        'min_upper_touches': strategy['min_upper_touches'],
        'max_break_frac': strategy['max_break_frac'],
        'min_width_atr': strategy['min_width_atr'],
        'fib_lo': strategy['fib_lo'], 'zone_tol_atr': strategy['zone_tol_atr'],
        'sl_buf_atr': strategy['sl_buf_atr'], 'min_rr': strategy['min_rr'],
        'b_near_upper_atr': strategy['b_near_upper_atr'],
        'tp_mode': strategy['tp_mode'],
        'leverage': config['risk']['leverage'],
        'risk_per_entry_pct': config['risk']['risk_per_entry_pct'],
    }


def trade_fingerprint(trades, oos_ts) -> tuple:
    values = []
    for trade in trades:
        timestamp = trade.timestamp
        if timestamp < oos_ts:
            continue
        values.append((
            timestamp.isoformat(), trade.direction,
            round(float(trade.entry), 10), round(float(trade.sl), 10),
            round(float(trade.tp1), 10), round(float(trade.exit_price), 10),
        ))
    return tuple(values)


def parameter_distance(left: dict, right: dict) -> int:
    keys = set(left) | set(right)
    return sum(left.get(key) != right.get(key) for key in keys)


def optimize_market(job: dict) -> dict:
    import optuna
    import pandas as pd

    from fibot.analysis.cuda_channels import install_cuda_channels
    from fibot.analysis.backtester import load_ohlcv, run_backtest
    from fibot.analysis.optimizer import (
        _CONF_MIN_TRADES, _confluence_config, _suggest_confluence, segment_stats,
    )

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    device = install_cuda_channels()
    symbol, timeframe = job['symbol'], job['timeframe']
    output = Path(job['output'])
    market_key = symbol.split('/')[0] + '_' + timeframe
    market_dir = output / 'markets' / market_key
    config_dir = market_dir / 'configs'
    config_dir.mkdir(parents=True, exist_ok=True)

    df_all = load_ohlcv(symbol, timeframe, job['start_date'], job['end_date'])
    oos_ts = pd.Timestamp(job['oos_from'], tz='UTC')
    df_is = df_all[df_all.index < oos_ts]
    validation_ts = oos_ts - pd.Timedelta(days=180)
    if validation_ts <= df_is.index[0]:
        validation_ts = df_is.index[int(len(df_is) * 0.7)]
    min_trades = _CONF_MIN_TRADES.get(timeframe, 20)
    min_validation_trades = max(3, min_trades // 10)
    cache_key = (symbol, timeframe, 'VARIANT_IS', len(df_is))

    def objective(trial):
        strategy = _suggest_confluence(trial)
        leverage = trial.suggest_int('leverage', 3, 10)
        risk_pct = trial.suggest_float('risk_per_entry_pct', 0.5, 3.0, step=0.25)
        config = _confluence_config(symbol, timeframe, strategy, risk_pct, leverage)
        try:
            result = run_backtest(df_is, config, job['capital'], symbol, timeframe,
                                  cache_key=cache_key)
        except Exception:
            return -999.0
        if result.total_trades < min_trades or result.max_drawdown_pct > job['max_dd']:
            return -999.0
        train = segment_stats(result.trades, end_ts=validation_ts)
        validation = segment_stats(result.trades, start_ts=validation_ts)
        if (validation['trades'] < min_validation_trades
                or train['pnl_pct'] <= 0 or validation['pnl_pct'] <= 0
                or validation['max_dd'] > job['max_dd']):
            return -999.0
        return (0.35 * train['pnl_pct'] + 0.65 * validation['pnl_pct']
                + math.log1p(result.total_trades) * 5.0
                - 0.2 * max(train['max_dd'], validation['max_dd']))

    db_path = (market_dir / 'study.sqlite3').resolve().as_posix()
    study = optuna.create_study(
        study_name=f'risk_v2_{market_key}', direction='maximize',
        sampler=optuna.samplers.TPESampler(seed=job['seed']),
        storage=f'sqlite:///{db_path}', load_if_exists=True,
    )
    if not study.trials:
        base = json.loads(Path(job['base_config']).read_text(encoding='utf-8'))
        study.enqueue_trial(base_params(base))
    remaining = max(0, job['trials'] - len(study.trials))
    if remaining:
        study.optimize(objective, n_trials=remaining, show_progress_bar=False)

    eligible = sorted(
        (trial for trial in study.trials
         if trial.value is not None and trial.value > -999.0),
        key=lambda trial: trial.value, reverse=True,
    )
    selected = []
    fingerprints = set()
    evaluated = 0
    for trial in eligible:
        if evaluated >= job['max_evaluations'] or len(selected) >= job['max_variants']:
            break
        evaluated += 1
        fixed = optuna.trial.FixedTrial(trial.params)
        strategy = _suggest_confluence(fixed)
        config = _confluence_config(
            symbol, timeframe, strategy,
            trial.params['risk_per_entry_pct'], trial.params['leverage'])
        result = run_backtest(df_all, config, job['capital'], symbol, timeframe)
        is_stats = segment_stats(result.trades, end_ts=oos_ts)
        train = segment_stats(result.trades, end_ts=validation_ts)
        validation = segment_stats(result.trades, start_ts=validation_ts, end_ts=oos_ts)
        oos = segment_stats(result.trades, start_ts=oos_ts)
        if (oos['pnl_pct'] <= 0 or oos['max_dd'] > job['max_dd']
                or oos['trades'] < job['min_oos_trades']):
            continue
        fingerprint = trade_fingerprint(result.trades, oos_ts)
        if fingerprint in fingerprints:
            continue
        if any(parameter_distance(trial.params, item['params']) < 2 for item in selected):
            continue
        fingerprints.add(fingerprint)
        config['_backtest'] = {
            'pnl_pct': round(is_stats['pnl_pct'], 2),
            'win_rate': round(is_stats['win_rate'], 1),
            'total_trades': is_stats['trades'],
            'max_drawdown': round(is_stats['max_dd'], 2),
            'start_date': job['start_date'], 'end_date': job['oos_from'],
            'capital': job['capital'], 'risk_policy_version': 2,
            'selection_score': round(float(trial.value), 4),
            'validation': {
                'start_date': validation_ts.strftime('%Y-%m-%d'),
                'pnl_pct': round(validation['pnl_pct'], 2),
                'max_drawdown': round(validation['max_dd'], 2),
                'total_trades': validation['trades'],
                'win_rate': round(validation['win_rate'], 1),
            },
            'oos': {
                'start_date': job['oos_from'], 'end_date': job['end_date'],
                'pnl_pct': round(oos['pnl_pct'], 2),
                'max_drawdown': round(oos['max_dd'], 2),
                'total_trades': oos['trades'],
                'win_rate': round(oos['win_rate'], 1),
            },
            'variant_trial': trial.number,
        }
        number = len(selected) + 1
        filename = f'config_{symbol.replace("/", "").replace(":", "")}_{timeframe}_v{number:02d}.json'
        atomic_json(config_dir / filename, config)
        selected.append({
            'file': filename, 'params': trial.params,
            'selection_score': round(float(trial.value), 4),
            'is': config['_backtest'], 'fingerprint_size': len(fingerprint),
        })

    summary = {
        'symbol': symbol, 'timeframe': timeframe, 'device': device,
        'target_trials': job['trials'], 'completed_trials': len(study.trials),
        'eligible_pre_oos_trials': len(eligible), 'evaluated_full': evaluated,
        'variants': selected, 'updated_at': datetime.now().isoformat(),
    }
    atomic_json(market_dir / 'summary.json', summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description='CUDA FiBot variant library builder')
    parser.add_argument('--trials', type=int, default=1500)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--max-variants', type=int, default=10)
    parser.add_argument('--max-evaluations', type=int, default=200)
    parser.add_argument('--target-total', type=int, default=20)
    parser.add_argument('--oos-from', default='2026-05-01')
    parser.add_argument('--to', default='2026-11-17')
    parser.add_argument('--capital', type=float, default=100.0)
    parser.add_argument('--max-dd', type=float, default=30.0)
    parser.add_argument('--min-oos-trades', type=int, default=5)
    parser.add_argument('--output', required=True)
    parser.add_argument('--finalize-only', action='store_true',
                        help='Rebuild the balanced manifest from completed market summaries')
    args = parser.parse_args()

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    base_dir = ROOT / 'artifacts' / 'optimization' / 'risk_policy_v2_full_20261117' / 'configs'
    jobs = []
    for symbol, timeframe, start_date, base_name in MARKETS:
        jobs.append({
            'symbol': symbol, 'timeframe': timeframe, 'start_date': start_date,
            'base_config': str(base_dir / base_name), 'output': str(output),
            'oos_from': args.oos_from, 'end_date': args.to,
            'capital': args.capital, 'max_dd': args.max_dd,
            'min_oos_trades': args.min_oos_trades, 'trials': args.trials,
            'max_variants': args.max_variants,
            'max_evaluations': args.max_evaluations,
            'seed': int(hashlib.sha256(
                f'{symbol}|{timeframe}|variant-v2'.encode()).hexdigest()[:8], 16),
        })

    summaries = []
    if args.finalize_only:
        for symbol, timeframe, _, _ in MARKETS:
            market_key = symbol.split('/')[0] + '_' + timeframe
            summary_path = output / 'markets' / market_key / 'summary.json'
            if not summary_path.exists():
                parser.error(f'completed market summary missing: {summary_path}')
            summaries.append(json.loads(summary_path.read_text(encoding='utf-8')))
    else:
        print(f'{len(jobs)} CUDA-Maerkte, {args.trials} Trials je Markt', flush=True)
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            for summary in executor.map(optimize_market, jobs):
                summaries.append(summary)
                print(f"{summary['symbol']} {summary['timeframe']}: "
                      f"{len(summary['variants'])} Varianten aus "
                      f"{summary['eligible_pre_oos_trials']} Pre-OOS-Kandidaten", flush=True)

    variants = []
    for summary in summaries:
        for row in summary['variants']:
            variants.append({
                'symbol': summary['symbol'], 'timeframe': summary['timeframe'], **row,
            })
    # A pure global ranking fills every slot with APT.  Select round-robin from
    # the pre-OOS ranking of each proven market so the library retains regime
    # and market diversity without consulting OOS magnitude.
    by_market = {}
    for row in variants:
        key = (row['symbol'], row['timeframe'])
        by_market.setdefault(key, []).append(row)
    for rows in by_market.values():
        rows.sort(key=lambda row: row['selection_score'], reverse=True)
    market_order = [(symbol, timeframe) for symbol, timeframe, _, _ in MARKETS]
    selected = []
    offset = 0
    while len(selected) < args.target_total:
        added = False
        for key in market_order:
            rows = by_market.get(key, [])
            if offset < len(rows):
                selected.append(rows[offset])
                added = True
                if len(selected) >= args.target_total:
                    break
        if not added:
            break
        offset += 1

    selected_dir = output / 'selected_configs'
    selected_dir.mkdir(parents=True, exist_ok=True)
    for stale in selected_dir.glob('*.json'):
        stale.unlink()
    for row in selected:
        market_key = row['symbol'].split('/')[0] + '_' + row['timeframe']
        source = output / 'markets' / market_key / 'configs' / row['file']
        shutil.copy2(source, selected_dir / row['file'])
    final = {
        'created_at': datetime.now().isoformat(), 'target': args.target_total,
        'found': len(variants), 'target_reached': len(selected) >= args.target_total,
        'selection_rule': 'balanced round-robin by pre-OOS selection_score',
        'markets': summaries, 'selected': selected,
    }
    atomic_json(output / 'summary.json', final)
    print(f"Bibliothek: {len(variants)} gefunden, {len(selected)}/{args.target_total} ausgewaehlt",
          flush=True)
    return 0 if final['target_reached'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
