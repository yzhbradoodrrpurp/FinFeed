"""Private local state, validated and atomically persisted outside the static root."""
import json
import math
import os
import re
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / '.local' / 'state.json'
LOCK = threading.Lock()
SYMBOL = re.compile(r'^[A-Z0-9][A-Z0-9.^=-]{0,19}$')


def validate(state):
    if not isinstance(state, dict) or set(state) != {'watchlist', 'positions'}:
        raise ValueError('无效保存格式')
    watchlist, positions = state['watchlist'], state['positions']
    if not isinstance(watchlist, list) or len(watchlist) > 40 or any(not isinstance(t, str) or not SYMBOL.fullmatch(t) for t in watchlist) or len(set(watchlist)) != len(watchlist):
        raise ValueError('无效自选股列表')
    if not isinstance(positions, list) or len(positions) > 40:
        raise ValueError('无效持仓列表')
    symbols = []
    for p in positions:
        if not isinstance(p, dict) or not isinstance(p.get('ticker'), str) or not SYMBOL.fullmatch(p['ticker']):
            raise ValueError('无效持仓 ticker')
        for key in ('quantity', 'averageCost'):
            n = p.get(key)
            if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n < 0 or n > 1e12 or (key == 'quantity' and n == 0):
                raise ValueError('无效持仓数量或成本')
        if not isinstance(p.get('currency'), str) or not re.fullmatch('[A-Z]{3}', p['currency']):
            raise ValueError('无效成本币种')
        symbols.append(p['ticker'])
    if len(set(symbols)) != len(symbols) or len(set(watchlist + symbols)) > 40:
        raise ValueError('标的重复或合计超过 40 个')
    return state


def read_state():
    if not STATE_PATH.exists():
        return None
    return validate(json.loads(STATE_PATH.read_text()))


def update_state(patch):
    with LOCK:
        current = read_state()
        if patch.get('initialize') and current is not None:
            return current
        if not isinstance(patch, dict) or set(patch) - {'watchlist', 'positions', 'initialize'}:
            raise ValueError('无效保存字段')
        state = validate({**(current or {'watchlist': [], 'positions': []}), **{k: v for k, v in patch.items() if k != 'initialize'}})
        STATE_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if current is not None and current != state:
            backup = STATE_PATH.parent / 'backups' / f'state-{time.time_ns()}.json'
            backup.parent.mkdir(mode=0o700, exist_ok=True)
            with open(backup, 'x', encoding='utf-8') as f:
                os.chmod(backup, 0o600)
                json.dump(current, f, ensure_ascii=False, allow_nan=False, indent=2)
        temporary = STATE_PATH.with_suffix('.tmp')
        with open(temporary, 'w', encoding='utf-8') as f:
            os.chmod(temporary, 0o600)
            json.dump(state, f, ensure_ascii=False, allow_nan=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, STATE_PATH)
        return state
