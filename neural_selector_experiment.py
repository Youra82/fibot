#!/usr/bin/env python3
"""CUDA backpropagation experiment for routing FiBot confluence variants.

The core channel/Fibonacci strategy stays unchanged.  The neural network only
scores already generated, risk-policy-compliant candidate signals.
"""

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import random
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))

from fibot.analysis.backtester import load_ohlcv
from fibot.strategy.risk_policy import ROUND_TRIP_COST_PCT
from fibot.strategy.signals import precompute_signals


STATE_FEATURES = (
    'ret_1', 'ret_3', 'ret_10', 'ret_20',
    'ema20_atr', 'ema50_atr', 'ema200_atr',
    'ema20_slope_atr', 'ema50_slope_atr',
    'atr_frac', 'relative_atr', 'efficiency_20', 'choppiness_14',
    'volume_ratio', 'range_position', 'close_position',
    'body_atr', 'range_atr', 'lower_wick', 'upper_wick',
)

SIGNAL_FEATURES = (
    'direction', 'entry_vs_close_atr', 'risk_atr', 'reward_atr',
    'rr', 'signal_score', 'instant_fill_stop',
)

CONFIG_FEATURES = (
    'pivot_k', 'window', 'min_upper_touches', 'max_break_frac',
    'min_width_atr', 'fib_lo', 'fib_hi', 'fib_sl', 'zone_tol_atr',
    'sl_buf_atr', 'min_rr', 'max_age_mult', 'b_near_upper_atr',
    'tp_upper', 'leverage', 'risk_per_entry_pct',
)


@dataclass
class Event:
    variant: str
    entry_idx: int
    exit_idx: int
    entry_time: str
    exit_time: str
    features: list
    net_r: float
    win_r: float
    loss_r: float
    risk_pct: float
    won: bool


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def market_features(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Causal market state; every value is shifted by one completed candle."""
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)
    open_ = df['open'].astype(float)
    volume = df['volume'].astype(float)
    previous = close.shift(1)
    true_range = pd.concat((
        high - low, (high - previous).abs(), (low - previous).abs()), axis=1).max(axis=1)
    atr = true_range.ewm(span=14, min_periods=14, adjust=False).mean()
    ema20 = close.ewm(span=20, min_periods=20, adjust=False).mean()
    ema50 = close.ewm(span=50, min_periods=50, adjust=False).mean()
    ema200 = close.ewm(span=200, min_periods=200, adjust=False).mean()
    change = close.diff().abs()
    high14, low14 = high.rolling(14).max(), low.rolling(14).min()
    high20, low20 = high.rolling(20).max(), low.rolling(20).min()
    candle_range = (high - low).replace(0, np.nan)
    bars_90d = max(200, int(pd.Timedelta(days=90) / pd.Timedelta(timeframe)))
    atr_frac = atr / close
    output = pd.DataFrame(index=df.index)
    for period in (1, 3, 10, 20):
        output[f'ret_{period}'] = close.pct_change(period, fill_method=None)
    output['ema20_atr'] = (close - ema20) / atr
    output['ema50_atr'] = (close - ema50) / atr
    output['ema200_atr'] = (close - ema200) / atr
    output['ema20_slope_atr'] = (ema20 - ema20.shift(5)) / atr
    output['ema50_slope_atr'] = (ema50 - ema50.shift(5)) / atr
    output['atr_frac'] = atr_frac
    output['relative_atr'] = atr_frac / atr_frac.rolling(
        bars_90d, min_periods=200).median()
    output['efficiency_20'] = (close - close.shift(20)).abs() / change.rolling(20).sum()
    output['choppiness_14'] = (
        100 * np.log10(true_range.rolling(14).sum() / (high14 - low14).replace(0, np.nan))
        / np.log10(14))
    output['volume_ratio'] = volume / volume.rolling(20).median()
    output['range_position'] = (close - low20) / (high20 - low20).replace(0, np.nan)
    output['close_position'] = (close - low) / candle_range
    output['body_atr'] = (close - open_).abs() / atr
    output['range_atr'] = candle_range / atr
    output['lower_wick'] = (np.minimum(open_, close) - low) / candle_range
    output['upper_wick'] = (high - np.maximum(open_, close)) / candle_range
    return output.replace([np.inf, -np.inf], np.nan).shift(1)


def config_vector(config: dict) -> list:
    strategy, risk = config['strategy'], config['risk']
    return [
        float(strategy['pivot_k']), float(strategy['window']),
        float(strategy['min_upper_touches']), float(strategy['max_break_frac']),
        float(strategy['min_width_atr']), float(strategy['fib_lo']),
        float(strategy['fib_hi']), float(strategy['fib_sl']),
        float(strategy['zone_tol_atr']), float(strategy['sl_buf_atr']),
        float(strategy['min_rr']), float(strategy.get('max_age_mult') or 0.0),
        float(strategy['b_near_upper_atr']),
        float(strategy.get('tp_mode') == 'upper'),
        float(risk['leverage']), float(risk['risk_per_entry_pct']),
    ]


def signal_exit(df: pd.DataFrame, signals: pd.DataFrame, index: int):
    direction = int(signals['_sig_dir'].iat[index])
    entry = float(signals['_sig_entry'].iat[index])
    stop = float(signals['_sig_sl'].iat[index])
    target = float(signals['_sig_tp1'].iat[index])
    risk = abs(entry - stop)
    if direction not in (1, 2) or not all(map(math.isfinite, (entry, stop, target, risk))) or risk <= 0:
        return None
    sign = 1.0 if direction == 1 else -1.0
    instant = bool(signals['_sig_instant'].iat[index])
    if instant:
        exit_index, exit_price = index, stop
    else:
        exit_index = None
        for position in range(index + 1, len(df)):
            if direction == 1:
                stop_hit = float(df['low'].iat[position]) <= stop
                target_hit = float(df['high'].iat[position]) >= target
            else:
                stop_hit = float(df['high'].iat[position]) >= stop
                target_hit = float(df['low'].iat[position]) <= target
            if stop_hit or target_hit:
                # Conservative and identical to the backtest fallback.
                exit_index = position
                exit_price = stop if stop_hit else target
                break
        if exit_index is None:
            return None
    gross_r = (exit_price - entry) * sign / risk
    cost_r = entry * ROUND_TRIP_COST_PCT / risk
    return exit_index, float(gross_r - cost_r), gross_r > 0


def build_events(df: pd.DataFrame, state: pd.DataFrame, signals: pd.DataFrame,
                 config: dict, variant: str) -> list[Event]:
    events = []
    vector = config_vector(config)
    atr = state['atr_frac'] * df['close'].shift(1)
    for index in np.flatnonzero(signals['_sig_dir'].to_numpy()):
        state_values = state.iloc[index].to_numpy(dtype=float)
        atr_value = float(atr.iloc[index])
        if not np.isfinite(state_values).all() or not math.isfinite(atr_value) or atr_value <= 0:
            continue
        outcome = signal_exit(df, signals, index)
        if outcome is None:
            continue
        exit_index, net_r, won = outcome
        direction = int(signals['_sig_dir'].iat[index])
        sign = 1.0 if direction == 1 else -1.0
        entry = float(signals['_sig_entry'].iat[index])
        stop = float(signals['_sig_sl'].iat[index])
        target = float(signals['_sig_tp1'].iat[index])
        risk = abs(entry - stop)
        reward = abs(target - entry)
        cost_r = entry * ROUND_TRIP_COST_PCT / risk
        signal_values = [
            sign, (entry - float(df['close'].shift(1).iat[index])) * sign / atr_value,
            risk / atr_value, reward / atr_value, reward / risk,
            float(signals['_sig_score'].iat[index]),
            float(signals['_sig_instant'].iat[index]),
        ]
        events.append(Event(
            variant=variant, entry_idx=int(index), exit_idx=int(exit_index),
            entry_time=df.index[index].isoformat(),
            exit_time=df.index[exit_index].isoformat(),
            features=[*state_values.tolist(), *signal_values, *vector],
            net_r=float(net_r), win_r=float(reward / risk - cost_r),
            loss_r=float(-1.0 - cost_r),
            risk_pct=float(config['risk']['risk_per_entry_pct']),
            won=bool(won),
        ))
    return events


def split_events(events: list[Event], validation_from: str, oos_from: str):
    validation_ts = pd.Timestamp(validation_from, tz='UTC')
    oos_ts = pd.Timestamp(oos_from, tz='UTC')
    train, validation, test = [], [], []
    for event in events:
        entry, exit_ = pd.Timestamp(event.entry_time), pd.Timestamp(event.exit_time)
        if entry < validation_ts and exit_ < validation_ts:
            train.append(event)
        elif validation_ts <= entry < oos_ts and exit_ < oos_ts:
            validation.append(event)
        elif entry >= oos_ts:
            test.append(event)
    return train, validation, test


def route_metrics(events: list[Event], predictions: np.ndarray | None,
                  variant: str | None = None, threshold: float = -math.inf) -> dict:
    candidates = defaultdict(list)
    for position, event in enumerate(events):
        if variant is None or event.variant == variant:
            candidates[event.entry_idx].append((position, event))
    equity, peak, max_dd, busy_until = 1.0, 1.0, 0.0, -1
    trades, wins, choices = 0, 0, defaultdict(int)
    for entry_index in sorted(candidates):
        if entry_index <= busy_until:
            continue
        group = candidates[entry_index]
        if predictions is None:
            chosen_position, chosen = group[0]
            score = math.inf
        else:
            chosen_position, chosen = max(group, key=lambda item: predictions[item[0]])
            score = float(predictions[chosen_position])
        if score < threshold:
            continue
        equity *= max(0.0, 1.0 + chosen.risk_pct / 100.0 * chosen.net_r)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak > 0 else 100.0)
        busy_until = chosen.exit_idx
        trades += 1
        wins += chosen.net_r > 0
        choices[chosen.variant] += 1
    return {
        'pnl_pct': (equity - 1.0) * 100.0, 'max_drawdown_pct': max_dd,
        'trades': trades, 'win_rate': wins / trades * 100 if trades else 0.0,
        'choices': dict(choices),
    }


def train_ensemble(train: list[Event], validation: list[Event], test: list[Event],
                   output: Path, seeds=(11, 23, 37, 51, 71),
                   objective: str = 'net_r', architecture: str = 'mlp'):
    import torch
    from torch import nn

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    x_train = np.asarray([event.features for event in train], dtype=np.float32)
    target = ((lambda event: float(event.won)) if objective == 'win'
              else (lambda event: event.net_r))
    y_train = np.asarray([target(event) for event in train], dtype=np.float32)
    x_validation = np.asarray([event.features for event in validation], dtype=np.float32)
    y_validation = np.asarray([target(event) for event in validation], dtype=np.float32)
    x_test = np.asarray([event.features for event in test], dtype=np.float32)
    mean = x_train.mean(axis=0)
    scale = x_train.std(axis=0)
    scale[scale < 1e-6] = 1.0
    x_train = (x_train - mean) / scale
    x_validation = (x_validation - mean) / scale
    x_test = (x_test - mean) / scale

    class Model(nn.Module):
        def __init__(self, width):
            super().__init__()
            if architecture == 'linear':
                self.network = nn.Linear(width, 1)
            else:
                self.network = nn.Sequential(
                    nn.Linear(width, 64), nn.SiLU(), nn.Dropout(0.15),
                    nn.Linear(64, 32), nn.SiLU(), nn.Dropout(0.10),
                    nn.Linear(32, 1),
                )

        def forward(self, values):
            return self.network(values).squeeze(-1)

    tx = torch.tensor(x_train, device=device)
    ty = torch.tensor(y_train, device=device)
    vx = torch.tensor(x_validation, device=device)
    vy = torch.tensor(y_validation, device=device)
    sx = torch.tensor(x_test, device=device)
    validation_predictions, test_predictions = [], []
    histories = []
    output.mkdir(parents=True, exist_ok=True)
    for seed in seeds:
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        model = Model(tx.shape[1]).to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=0.002, weight_decay=1e-3)
        if objective == 'win':
            positives = max(1.0, float(ty.sum().cpu()))
            negatives = max(1.0, float(len(ty) - positives))
            loss_function = nn.BCEWithLogitsLoss(
                reduction='none', pos_weight=torch.tensor(negatives / positives, device=device))
        else:
            loss_function = nn.SmoothL1Loss(reduction='none')
        best_loss, best_state, stale = math.inf, None, 0
        generator = torch.Generator(device='cpu').manual_seed(seed)
        for epoch in range(500):
            order = torch.randperm(len(tx), generator=generator).to(device)
            model.train()
            for start in range(0, len(order), 64):
                positions = order[start:start + 64]
                prediction = model(tx[positions])
                raw_loss = loss_function(prediction, ty[positions])
                if objective == 'win':
                    loss = raw_loss.mean()
                else:
                    weights = torch.where(ty[positions] < 0, 1.25, 1.0)
                    loss = (raw_loss * weights).mean()
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
                optimizer.step()
            model.eval()
            with torch.no_grad():
                validation_loss = float(loss_function(model(vx), vy).mean().cpu())
            if validation_loss < best_loss - 1e-5:
                best_loss = validation_loss
                best_state = {key: value.detach().cpu().clone()
                              for key, value in model.state_dict().items()}
                stale = 0
            else:
                stale += 1
            if stale >= 50:
                break
        model.load_state_dict(best_state)
        model.eval()
        with torch.no_grad():
            validation_output = model(vx)
            test_output = model(sx)
            if objective == 'win':
                validation_output = torch.sigmoid(validation_output)
                test_output = torch.sigmoid(test_output)
            validation_predictions.append(validation_output.cpu().numpy())
            test_predictions.append(test_output.cpu().numpy())
        torch.save({'state_dict': best_state, 'mean': mean, 'scale': scale,
                    'objective': objective, 'architecture': architecture,
                    'input_features': [*STATE_FEATURES, *SIGNAL_FEATURES, *CONFIG_FEATURES]},
                   output / f'model_seed_{seed}.pt')
        histories.append({'seed': seed, 'best_validation_loss': best_loss,
                          'epochs': epoch + 1})
    return (np.mean(validation_predictions, axis=0),
            np.mean(test_predictions, axis=0), histories, str(device))


def routing_scores(events: list[Event], predictions: np.ndarray, objective: str) -> np.ndarray:
    if objective != 'win':
        return predictions
    return np.asarray([
        probability * event.win_r + (1.0 - probability) * event.loss_r
        for event, probability in zip(events, predictions)
    ], dtype=float)


def threshold_from_validation(events: list[Event], predictions: np.ndarray) -> tuple[float, dict]:
    candidates = [-math.inf]
    candidates.extend(float(value) for value in np.quantile(
        predictions, np.linspace(0.1, 0.8, 15)))
    best_threshold, best = -math.inf, route_metrics(events, predictions)
    best_score = best['pnl_pct'] if best['max_drawdown_pct'] <= 30 and best['trades'] >= 3 else -math.inf
    for threshold in candidates[1:]:
        metrics = route_metrics(events, predictions, threshold=threshold)
        score = metrics['pnl_pct'] if metrics['max_drawdown_pct'] <= 30 and metrics['trades'] >= 3 else -math.inf
        if score > best_score:
            best_threshold, best, best_score = threshold, metrics, score
    return best_threshold, best


def walk_forward_gate(events: list[Event], baseline_variant: str, output: Path,
                      objective: str, architecture: str) -> dict:
    """Decide neural-vs-fixed using only rolling windows before the OOS boundary."""
    windows = (
        ('2024-05-01', '2024-11-01'),
        ('2024-11-01', '2025-05-01'),
        ('2025-05-01', '2025-11-02'),
        ('2025-11-02', '2026-05-01'),
    )
    folds = []
    for number, (validation_from, validation_to) in enumerate(windows, 1):
        start = pd.Timestamp(validation_from, tz='UTC')
        end = pd.Timestamp(validation_to, tz='UTC')
        train = [event for event in events
                 if pd.Timestamp(event.entry_time) < start
                 and pd.Timestamp(event.exit_time) < start]
        validation = [event for event in events
                      if start <= pd.Timestamp(event.entry_time) < end
                      and pd.Timestamp(event.exit_time) < end]
        if len(train) < 60 or len(validation) < 10:
            folds.append({
                'validation_from': validation_from, 'validation_to': validation_to,
                'status': 'insufficient_samples', 'train_samples': len(train),
                'validation_samples': len(validation),
            })
            continue
        prediction, _, histories, _ = train_ensemble(
            train, validation, validation, output / f'fold_{number}',
            seeds=(101, 131, 151), objective=objective, architecture=architecture)
        prediction = routing_scores(validation, prediction, objective)
        fixed = route_metrics(validation, None, variant=baseline_variant)
        neural = route_metrics(validation, prediction)
        folds.append({
            'validation_from': validation_from, 'validation_to': validation_to,
            'status': 'ok', 'train_samples': len(train),
            'validation_samples': len(validation), 'fixed': fixed, 'neural': neural,
            'pnl_delta': neural['pnl_pct'] - fixed['pnl_pct'],
            'model_histories': histories,
        })
    usable = [fold for fold in folds if fold['status'] == 'ok']
    positive = sum(fold['pnl_delta'] > 0 for fold in usable)
    mean_delta = float(np.mean([fold['pnl_delta'] for fold in usable])) if usable else -math.inf
    required = max(3, math.ceil(len(usable) * 0.75))
    enabled = len(usable) >= 3 and positive >= required and mean_delta > 0
    return {
        'folds': folds, 'usable_folds': len(usable), 'positive_folds': positive,
        'required_positive_folds': required, 'mean_pnl_delta': mean_delta,
        'neural_enabled': enabled,
    }


def run_group(paths: list[Path], output: Path, validation_from: str, oos_from: str,
              end_date: str, objective: str, architecture: str) -> dict:
    configs = [(path, json.loads(path.read_text(encoding='utf-8'))) for path in paths]
    symbol = configs[0][1]['market']['symbol']
    timeframe = configs[0][1]['market']['timeframe']
    start_date = min(config['_backtest']['start_date'] for _, config in configs)
    df = load_ohlcv(symbol, timeframe, start_date, end_date)
    state = market_features(df, timeframe)
    all_events = []
    for path, config in configs:
        signals = precompute_signals(
            df.copy(), config,
            cache_key=(symbol, timeframe, 'NEURAL_SELECTOR', len(df)))
        all_events.extend(build_events(df, state, signals, config, path.name))
    train, validation, test = split_events(all_events, validation_from, oos_from)
    if min(len(train), len(validation), len(test)) == 0:
        raise ValueError(f'empty temporal split for {symbol} {timeframe}')
    baseline_variant = paths[0].name
    gate = walk_forward_gate(
        all_events, baseline_variant, output / 'walk_forward', objective, architecture)
    val_prediction, test_prediction, histories, device = train_ensemble(
        train, validation, test, output, objective=objective, architecture=architecture)
    val_prediction = routing_scores(validation, val_prediction, objective)
    test_prediction = routing_scores(test, test_prediction, objective)
    threshold, validation_filtered = threshold_from_validation(validation, val_prediction)
    fixed_oos = route_metrics(test, None, variant=baseline_variant)
    neural_oos = route_metrics(test, test_prediction)
    filtered_oos = route_metrics(test, test_prediction, threshold=threshold)
    result = {
        'symbol': symbol, 'timeframe': timeframe, 'device': device,
        'objective': objective, 'architecture': architecture,
        'samples': {'train': len(train), 'validation': len(validation), 'test': len(test)},
        'model_histories': histories,
        'walk_forward_gate': gate,
        'validation': {
            'fixed': route_metrics(validation, None, variant=baseline_variant),
            'neural_always': route_metrics(validation, val_prediction),
            'neural_filtered': validation_filtered,
            'chosen_threshold': threshold if math.isfinite(threshold) else None,
        },
        'oos': {
            'fixed': fixed_oos,
            'neural_always': neural_oos,
            'neural_filtered': filtered_oos,
            'guarded_hybrid': neural_oos if gate['neural_enabled'] else fixed_oos,
            'guard_decision': 'neural' if gate['neural_enabled'] else 'fixed',
        },
    }
    atomic_json(output / 'result.json', result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description='FiBot neural config selector experiment')
    parser.add_argument('--library', default=(
        'src/fibot/strategy/config_library/risk_v2_20_20261118'))
    parser.add_argument('--validation-from', default='2025-11-02')
    parser.add_argument('--oos-from', default='2026-05-01')
    parser.add_argument('--to', default='2026-11-17')
    parser.add_argument('--output', default=(
        'artifacts/optimization/neural_selector_20261118'))
    parser.add_argument('--objective', choices=('net_r', 'win'), default='net_r')
    parser.add_argument('--architecture', choices=('mlp', 'linear'), default='mlp')
    args = parser.parse_args()

    from fibot.analysis.cuda_channels import install_cuda_channels

    channel_device = install_cuda_channels()
    library = Path(args.library)
    groups = defaultdict(list)
    for path in sorted(library.glob('config_*.json')):
        config = json.loads(path.read_text(encoding='utf-8'))
        groups[(config['market']['symbol'], config['market']['timeframe'])].append(path)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for (symbol, timeframe), paths in groups.items():
        key = symbol.split('/')[0] + '_' + timeframe
        print(f'{key}: {len(paths)} Varianten', flush=True)
        result = run_group(paths, output / key, args.validation_from,
                           args.oos_from, args.to, args.objective, args.architecture)
        results.append(result)
        fixed = result['oos']['fixed']
        neural = result['oos']['neural_always']
        filtered = result['oos']['neural_filtered']
        hybrid = result['oos']['guarded_hybrid']
        print(f"  OOS fest {fixed['pnl_pct']:+.2f}% | neural {neural['pnl_pct']:+.2f}% "
              f"| neural+Schwelle {filtered['pnl_pct']:+.2f}% "
              f"| Gate {result['oos']['guard_decision']} {hybrid['pnl_pct']:+.2f}%", flush=True)
    summary = {
        'created_at': datetime.now().isoformat(), 'channel_cuda': channel_device,
        'method': (f'{args.architecture} ensemble trained by backpropagation; '
                   'core strategy unchanged'),
        'objective': args.objective,
        'architecture': args.architecture,
        'validation_from': args.validation_from, 'oos_from': args.oos_from,
        'end_date': args.to, 'feature_names': [*STATE_FEATURES, *SIGNAL_FEATURES, *CONFIG_FEATURES],
        'groups': results,
    }
    atomic_json(output / 'summary.json', summary)
    print(f'Fertig: {output}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
