#!/usr/bin/env python3
"""Re-optimize every current confluence market with a fixed untouched OOS split."""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))

from fibot.analysis.cuda_channels import install_cuda_channels
from fibot.analysis.optimizer import optimize_confluence


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description='FiBot CUDA safety-policy optimizer')
    parser.add_argument('--trials', type=int, default=250)
    parser.add_argument('--oos-from', default='2026-05-01')
    parser.add_argument('--to', default=datetime.now().date().isoformat())
    parser.add_argument('--capital', type=float, default=100.0)
    parser.add_argument('--max-dd', type=float, default=30.0)
    parser.add_argument('--output', default='')
    parser.add_argument('--resume', action='store_true',
                        help='Continue an interrupted run in --output')
    parser.add_argument('--only', nargs='*', default=[],
                        help='Optional filename fragments, for example JUPUSDTUSDT_1h')
    args = parser.parse_args()

    device = install_cuda_channels()
    print(f"CUDA: {device['device']} (Runtime {device['cuda_runtime']})", flush=True)

    source_dir = ROOT / 'src' / 'fibot' / 'strategy' / 'configs'
    sources = sorted(source_dir.glob('config_*_fib.json'))
    if args.only:
        wanted = [value.upper() for value in args.only]
        sources = [path for path in sources
                   if any(value in path.name.upper() for value in wanted)]
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output = Path(args.output) if args.output else ROOT / 'artifacts' / 'optimization' / f'risk_policy_v2_{stamp}'
    candidates = output / 'configs'
    candidates.mkdir(parents=True, exist_ok=True)
    summary_path = output / 'summary.json'
    if args.resume and summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
        expected = (args.trials, args.oos_from, args.to)
        actual = (summary.get('trials'), summary.get('oos_from'), summary.get('end_date'))
        if actual != expected:
            parser.error(f'--resume parameters differ: saved={actual}, requested={expected}')
        summary.pop('finished_at', None)
        summary.pop('counts', None)
    else:
        summary = {
            'started_at': datetime.now().isoformat(), 'cuda': device,
            'trials': args.trials, 'oos_from': args.oos_from, 'end_date': args.to,
            'results': [],
        }
        atomic_json(summary_path, summary)

    completed = {row['file']: row for row in summary['results']}

    for number, path in enumerate(sources, 1):
        previous = completed.get(path.name)
        if previous is not None and (
                previous.get('status') == 'no_robust_config'
                or (previous.get('status') == 'ok' and (candidates / path.name).exists())):
            print(f"\n[{number}/{len(sources)}] {path.name}: bereits abgeschlossen, uebersprungen",
                  flush=True)
            continue
        if previous is not None:
            summary['results'] = [row for row in summary['results']
                                  if row.get('file') != path.name]
        old = json.loads(path.read_text(encoding='utf-8'))
        market = old['market']
        symbol, timeframe = market['symbol'], market['timeframe']
        start = old.get('_backtest', {}).get('start_date') or '2024-04-01'
        seed = int(hashlib.sha256(f'{symbol}|{timeframe}|risk-v2'.encode()).hexdigest()[:8], 16)
        print(f"\n[{number}/{len(sources)}] {symbol} {timeframe} | "
              f"train {start}..{args.oos_from} | test {args.oos_from}..{args.to}", flush=True)
        try:
            config = optimize_confluence(
                symbol, timeframe, start, args.oos_from, args.to,
                capital=args.capital, n_trials=args.trials, max_dd=args.max_dd,
                min_wr=0.0, seed=seed, verbose=False,
            )
            if config is None:
                row = {'file': path.name, 'symbol': symbol, 'timeframe': timeframe,
                       'status': 'no_robust_config'}
                print('  KEINE robuste Pre-OOS-Config', flush=True)
            else:
                atomic_json(candidates / path.name, config)
                bt, oos = config['_backtest'], config['_backtest']['oos']
                row = {
                    'file': path.name, 'symbol': symbol, 'timeframe': timeframe,
                    'status': 'ok', 'is_pnl_pct': bt['pnl_pct'],
                    'is_max_dd': bt['max_drawdown'], 'is_trades': bt['total_trades'],
                    'validation': bt['validation'], 'oos': oos,
                }
                print(f"  IS {bt['pnl_pct']:+.2f}% / DD {bt['max_drawdown']:.2f}% | "
                      f"OOS {oos['pnl_pct']:+.2f}% / DD {oos['max_drawdown']:.2f}%", flush=True)
        except Exception as error:
            row = {'file': path.name, 'symbol': symbol, 'timeframe': timeframe,
                   'status': 'error', 'error': f'{type(error).__name__}: {error}'}
            print(f"  FEHLER: {row['error']}", flush=True)
        summary['results'].append(row)
        summary['updated_at'] = datetime.now().isoformat()
        atomic_json(summary_path, summary)

    summary['finished_at'] = datetime.now().isoformat()
    summary['counts'] = {
        key: sum(row['status'] == key for row in summary['results'])
        for key in ('ok', 'no_robust_config', 'error')
    }
    atomic_json(summary_path, summary)
    print(f"\nFertig: {output}\n{summary['counts']}", flush=True)
    return 0 if not summary['counts']['error'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
