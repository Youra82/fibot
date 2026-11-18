#!/usr/bin/env python3
"""Find additional robust FiBot configs without training on the fixed OOS period."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def config_name(symbol: str, timeframe: str) -> str:
    market = symbol.replace('/', '').replace(':', '')
    return f'config_{market}_{timeframe}_fib.json'


def optimize_one(job: dict) -> dict:
    """Process-isolated CUDA optimization for one predeclared market."""
    try:
        from fibot.analysis.cuda_channels import install_cuda_channels
        from fibot.analysis.optimizer import optimize_confluence

        install_cuda_channels()
        config = optimize_confluence(
            job['symbol'], job['timeframe'], job['start_date'],
            job['oos_from'], job['end_date'], capital=job['capital'],
            n_trials=job['trials'], max_dd=job['max_dd'], min_wr=0.0,
            seed=job['seed'], verbose=False,
        )
        if config is None:
            return {**job, 'status': 'no_robust_config'}
        oos = config['_backtest']['oos']
        passed = (
            oos['pnl_pct'] > 0
            and oos['max_drawdown'] <= job['max_dd']
            and oos['total_trades'] >= job['min_oos_trades']
        )
        return {
            **job, 'status': 'pass' if passed else 'oos_fail',
            'config': config,
            'is_pnl_pct': config['_backtest']['pnl_pct'],
            'is_max_dd': config['_backtest']['max_drawdown'],
            'is_trades': config['_backtest']['total_trades'],
            'validation': config['_backtest']['validation'],
            'oos': oos,
        }
    except Exception as error:
        return {**job, 'status': 'error',
                'error': f'{type(error).__name__}: {error}'}


def history_start(row: dict) -> str | None:
    if row.get('ab_2023_04'):
        return '2023-04-08'
    if row.get('ab_2024_04'):
        return '2024-04-01'
    if row.get('ab_2025_04'):
        return '2025-04-01'
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description='CUDA search for 20 robust FiBot configs')
    parser.add_argument('--target', type=int, default=20)
    parser.add_argument('--trials', type=int, default=120)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--max-candidates', type=int, default=180)
    parser.add_argument('--oos-from', default='2026-05-01')
    parser.add_argument('--to', default='2026-11-17')
    parser.add_argument('--capital', type=float, default=100.0)
    parser.add_argument('--max-dd', type=float, default=30.0)
    parser.add_argument('--min-oos-trades', type=int, default=5)
    parser.add_argument('--output', required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--seed-summary', default=(
        'artifacts/optimization/risk_policy_v2_full_20261117/summary.json'))
    args = parser.parse_args()

    output = Path(args.output)
    selected_dir = output / 'selected_configs'
    screening_dir = output / 'screening_configs'
    selected_dir.mkdir(parents=True, exist_ok=True)
    screening_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output / 'summary.json'

    if args.resume and summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
        expected = (args.target, args.trials, args.oos_from, args.to,
                    args.max_dd, args.min_oos_trades)
        actual = tuple(summary.get(key) for key in (
            'target', 'trials', 'oos_from', 'end_date',
            'max_dd', 'min_oos_trades'))
        if actual != expected:
            parser.error(f'--resume parameters differ: saved={actual}, requested={expected}')
    else:
        summary = {
            'started_at': datetime.now().isoformat(),
            'target': args.target, 'trials': args.trials,
            'oos_from': args.oos_from, 'end_date': args.to,
            'max_dd': args.max_dd, 'min_oos_trades': args.min_oos_trades,
            'selection_rule': 'pre-OOS robust AND OOS pnl>0, dd<=limit, trades>=minimum',
            'seeded': [], 'results': [], 'selected': [],
        }

        seed_path = Path(args.seed_summary)
        if seed_path.exists():
            seed = json.loads(seed_path.read_text(encoding='utf-8'))
            source_configs = seed_path.parent / 'configs'
            for row in seed.get('results', []):
                oos = row.get('oos') or {}
                if (row.get('status') == 'ok' and oos.get('pnl_pct', 0) > 0
                        and oos.get('max_drawdown', 10**9) <= args.max_dd
                        and oos.get('total_trades', 0) >= args.min_oos_trades):
                    source = source_configs / row['file']
                    if source.exists():
                        shutil.copy2(source, selected_dir / row['file'])
                        seeded = {**row, 'source': str(seed_path), 'stage': 'seeded'}
                        summary['seeded'].append(seeded)
                        summary['selected'].append(seeded)
        atomic_json(summary_path, summary)

    universe_path = ROOT / 'forschung' / 'konfluenz' / 'universe.json'
    universe = json.loads(universe_path.read_text(encoding='utf-8'))
    source_dir = ROOT / 'src' / 'fibot' / 'strategy' / 'configs'
    existing_pairs = set()
    for path in source_dir.glob('config_*_fib.json'):
        try:
            config = json.loads(path.read_text(encoding='utf-8'))
            existing_pairs.add((config['market']['symbol'], config['market']['timeframe']))
        except (KeyError, ValueError):
            pass

    completed = {(row['symbol'], row['timeframe']) for row in summary['results']}
    timeframe_order = ('2h', '1h', '4h', '30m', '6h')
    pool = []
    for market in universe:
        for timeframe in timeframe_order:
            start = history_start(market)
            if start is None:
                continue
            symbol = f"{market['coin']}/USDT:USDT"
            pair = (symbol, timeframe)
            cache = ROOT / 'data' / 'cache' / f"{market['coin']}-USDT-USDT_{timeframe}.csv"
            if pair in existing_pairs or pair in completed or not cache.exists():
                continue
            seed = int(hashlib.sha256(
                f'{symbol}|{timeframe}|risk-v2-screen'.encode()).hexdigest()[:8], 16)
            pool.append({
                'symbol': symbol, 'timeframe': timeframe, 'start_date': start,
                'oos_from': args.oos_from, 'end_date': args.to,
                'capital': args.capital, 'trials': args.trials,
                'max_dd': args.max_dd, 'min_oos_trades': args.min_oos_trades,
                'seed': seed, 'volume_mio': market.get('vol_mio'),
            })
    pool = pool[:args.max_candidates]

    print(f"Startbestand: {len(summary['selected'])}/{args.target}; "
          f"Pool: {len(pool)}; CUDA-Prozesse: {args.workers}", flush=True)
    if len(summary['selected']) >= args.target:
        return 0

    with ProcessPoolExecutor(max_workers=args.workers,
                             max_tasks_per_child=8) as executor:
        for offset in range(0, len(pool), args.workers):
            batch = pool[offset:offset + args.workers]
            for result in executor.map(optimize_one, batch):
                config = result.pop('config', None)
                name = config_name(result['symbol'], result['timeframe'])
                result['file'] = name
                if config is not None:
                    atomic_json(screening_dir / name, config)
                if (result['status'] == 'pass'
                        and len(summary['selected']) < args.target):
                    shutil.copy2(screening_dir / name, selected_dir / name)
                    selected = {key: value for key, value in result.items()
                                if key not in ('capital', 'seed')}
                    selected['stage'] = 'screening'
                    summary['selected'].append(selected)
                summary['results'].append(result)
                oos = result.get('oos', {})
                print(f"[{len(summary['results']):03d}] {result['symbol']} "
                      f"{result['timeframe']}: {result['status']} "
                      f"OOS {oos.get('pnl_pct', '-')}% / "
                      f"DD {oos.get('max_drawdown', '-')}% | "
                      f"gesamt {len(summary['selected'])}/{args.target}", flush=True)
            summary['updated_at'] = datetime.now().isoformat()
            atomic_json(summary_path, summary)
            if len(summary['selected']) >= args.target:
                break

    summary['finished_at'] = datetime.now().isoformat()
    summary['counts'] = {
        status: sum(row['status'] == status for row in summary['results'])
        for status in ('pass', 'oos_fail', 'no_robust_config', 'error')
    }
    summary['target_reached'] = len(summary['selected']) >= args.target
    atomic_json(summary_path, summary)
    print(f"Fertig: {len(summary['selected'])}/{args.target} | {summary['counts']}", flush=True)
    return 0 if summary['target_reached'] and not summary['counts']['error'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
