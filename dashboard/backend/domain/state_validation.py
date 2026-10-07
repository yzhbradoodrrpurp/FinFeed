"""Validation shared by the private cloud state API."""
import math
import re

SYMBOL = re.compile(r'^[A-Z0-9][A-Z0-9.^=-]{0,19}$')


def validate(state):
    if not isinstance(state, dict) or set(state) != {'watchlist', 'positions'}:
        raise ValueError('无效保存格式')
    watchlist, positions = state['watchlist'], state['positions']
    if not isinstance(watchlist, list) or len(watchlist) > 128 or any(not isinstance(t, str) or not SYMBOL.fullmatch(t) for t in watchlist) or len(set(watchlist)) != len(watchlist):
        raise ValueError('无效自选股列表')
    if not isinstance(positions, list) or len(positions) > 128:
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
    if len(set(symbols)) != len(symbols) or len(set(watchlist + symbols)) > 128:
        raise ValueError('标的重复或合计超过 128 个')
    return state
