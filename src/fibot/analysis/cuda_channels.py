"""Optional exact CUDA acceleration for the confluence channel search."""

import os
from pathlib import Path
import sys

import numpy as np

from fibot.strategy import confluence_logic as logic


_DLL_HANDLES = []
_CP = None
_KERNEL = None
_ORIGINAL = logic._channel_series


def _load_cupy():
    global _CP
    if _CP is not None:
        return _CP
    if os.name == 'nt':
        site = Path(sys.prefix) / 'Lib' / 'site-packages' / 'nvidia'
        for part in ('cuda_runtime', 'cuda_nvrtc'):
            binary = site / part / 'bin'
            if binary.exists():
                _DLL_HANDLES.append(os.add_dll_directory(str(binary)))
                os.environ['PATH'] = str(binary) + os.pathsep + os.environ.get('PATH', '')
        runtime = site / 'cuda_runtime'
        if runtime.exists():
            os.environ.setdefault('CUDA_PATH', str(runtime))
    import cupy as cp
    _CP = cp
    return cp


def _kernel():
    global _KERNEL
    cp = _load_cupy()
    if _KERNEL is None:
        source = Path(__file__).with_name('channel_kernel.cu').read_text(encoding='utf-8')
        _KERNEL = cp.RawKernel(source, 'channels', options=('--fmad=false',))
    return _KERNEL


def gpu_channel_series(h, l, c, p, cache_key=None):
    """Drop-in, bit-for-bit replacement for confluence_logic._channel_series."""
    ck = None
    if cache_key is not None:
        ck = (cache_key, tuple(p[key] for key in logic.CHANNEL_KEYS))
        if ck in logic._CHANNEL_CACHE:
            return logic._CHANNEL_CACHE[ck]
    cp = _load_cupy()
    n = len(c)
    k = int(p['pivot_k'])
    max_pivots = int(p['max_pivots'])
    if max_pivots > 64:
        raise ValueError('CUDA channel search supports at most 64 pivot anchors')
    atr = logic._atr(h, l, c, int(p['atr_period']))
    lows = logic._pivots(l, k, 'low')
    highs = logic._pivots(h, k, 'high')
    low_mask = np.zeros(n, dtype=np.int32)
    high_mask = np.zeros(n, dtype=np.int32)
    low_mask[lows] = 1
    high_mask[highs] = 1
    arrays = [cp.asarray(np.ascontiguousarray(value))
              for value in (h, l, c, atr, low_mask, high_mask)]
    output = cp.zeros((n, 5), dtype=cp.float64)
    args = (*arrays, np.int32(n), np.int32(k), np.int32(p['window']),
            np.int32(max_pivots), np.int32(p['min_span']),
            np.float64(p['break_atr']), np.float64(p['max_break_frac']),
            np.float64(p['touch_atr']), np.float64(p['min_width_atr']),
            np.int32(p['min_upper_touches']), output)
    _kernel()(((n + 127) // 128,), (128,), args)
    result = cp.asnumpy(output)
    value = {
        'atr': atr, 'pl': lows, 'ph': highs,
        'valid': result[:, 0].astype(bool),
        'a_pos': result[:, 1].astype(np.int64),
        'slope': result[:, 2], 'icpt': result[:, 3], 'width': result[:, 4],
    }
    if ck is not None:
        if len(logic._CHANNEL_CACHE) > 400:
            logic._CHANNEL_CACHE.clear()
        logic._CHANNEL_CACHE[ck] = value
    return value


def install_cuda_channels() -> dict:
    """Install the CUDA path for this process and return device metadata."""
    cp = _load_cupy()
    _kernel()
    logic._channel_series = gpu_channel_series
    props = cp.cuda.runtime.getDeviceProperties(0)
    name = props['name']
    if isinstance(name, bytes):
        name = name.decode('utf-8', errors='replace')
    return {'device': name, 'cuda_runtime': cp.cuda.runtime.runtimeGetVersion()}


def uninstall_cuda_channels():
    logic._channel_series = _ORIGINAL
