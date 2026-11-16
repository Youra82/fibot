"""Deterministic execution checks; no network calls or strategy optimisation."""
import json
import math
import os
from pathlib import Path
from contextlib import contextmanager
import hashlib


class CycleBusy(Exception):
    pass


def entry_client_oid(*parts):
    """Stable Bitget clientOid (32 safe characters) for one exact entry intent."""
    payload = '|'.join(str(part) for part in parts)
    return 'fb' + hashlib.sha256(payload.encode('utf-8')).hexdigest()[:30]


@contextmanager
def symbol_cycle_lock(directory, symbol):
    """One broker-mutating cycle per symbol, also across overlapping cron processes."""
    path = Path(directory) / ('cycle_' + hashlib.sha256(symbol.encode()).hexdigest()[:24] + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            if path.stat().st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise CycleBusy() from None
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CycleBusy() from None
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def consumed(path, key):
    path = Path(path)
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, list) or any(not isinstance(k, str) for k in data):
        raise ValueError('Invalid persisted impulse ledger')
    return key in data


def consume(path, key):
    """Keep fills independently of the position tracker; never silently reset damage."""
    path = Path(path)
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    if not isinstance(data, list) or any(not isinstance(k, str) for k in data):
        raise ValueError('Invalid persisted impulse ledger')
    if key in data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as output:
            json.dump(data + [key], output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def validate_bracket(side, entry, stop, target, ticker):
    """Reject invalid rounded protection or a market already beyond protection."""
    values = [float(x) for x in (entry, stop, target)]
    if side not in ('buy', 'sell') or any(not math.isfinite(x) or x <= 0 for x in values):
        raise ValueError('Invalid bracket values')
    entry, stop, target = values
    if not (stop < entry < target if side == 'buy' else target < entry < stop):
        raise ValueError('Rounded stop/entry/target have invalid geometry')
    if not isinstance(ticker, dict):
        raise ValueError('Current market quote unavailable')
    quote_key = 'ask' if side == 'buy' else 'bid'
    last = float(ticker.get('last') or 0)
    quote = float(ticker.get(quote_key) or last)
    if any(not math.isfinite(x) or x <= 0 for x in (last, quote)):
        raise ValueError('Invalid current market quote')
    low, high = sorted((last, quote))
    if side == 'buy' and not (stop < low and high < target):
        raise ValueError('Market already beyond long protection')
    if side == 'sell' and not (target < low and high < stop):
        raise ValueError('Market already beyond short protection')


def filled_quantity(order):
    """None/missing is unknown, never zero; this matters after cancellation."""
    if not isinstance(order, dict) or order.get('filled') is None:
        raise ValueError('Filled quantity unknown')
    quantity = float(order['filled'])
    if not math.isfinite(quantity) or quantity < 0:
        raise ValueError('Invalid filled quantity')
    return quantity
