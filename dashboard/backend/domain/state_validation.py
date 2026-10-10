"""Validation shared by the private cloud state API."""
import math
import re

SYMBOL = re.compile(r'^[A-Z0-9][A-Z0-9.^=-]{0,19}$')


GROUP_ORDER = ['security', 'price', 'eps', 'valuation', 'volume', 'revenue', 'debt', 'fcf', 'gross_margin', 'operating_margin', 'capex']
SECTOR_ORDER = ['XLC', 'XLY', 'XLP', 'XLE', 'XLF', 'XLV', 'XLI', 'XLB', 'XLRE', 'XLK', 'XLU']


def validate_preferences(preferences):
    if not isinstance(preferences, dict) or set(preferences) - {'watchlistGroupOrder', 'homeSectorOrder'}:
        raise ValueError('无效展示设置')
    for key, allowed in (('watchlistGroupOrder', GROUP_ORDER), ('homeSectorOrder', SECTOR_ORDER)):
        if key in preferences:
            value = preferences[key]
            if not isinstance(value, list) or len(value) != len(allowed) or any(not isinstance(item, str) for item in value) or set(value) != set(allowed):
                raise ValueError('展示顺序必须包含全部项目且不能重复')
    return preferences


def display_preferences(state):
    return {'watchlistGroupOrder': GROUP_ORDER.copy(), 'homeSectorOrder': SECTOR_ORDER.copy(),
            **validate_preferences((state or {}).get('uiPreferences', {}))}


def validate(state):
    if not isinstance(state, dict) or not {'watchlist', 'positions'} <= set(state) or set(state) - {'watchlist', 'positions', 'watchlistFavorites', 'uiPreferences'}:
        raise ValueError('无效保存格式')
    if 'uiPreferences' in state:
        validate_preferences(state['uiPreferences'])
    watchlist, positions = state['watchlist'], state['positions']
    if not isinstance(watchlist, list) or len(watchlist) > 128 or any(not isinstance(t, str) or not SYMBOL.fullmatch(t) for t in watchlist) or len(set(watchlist)) != len(watchlist):
        raise ValueError('无效自选股列表')
    favorites = state.get('watchlistFavorites', [])
    if not isinstance(favorites, list) or len(favorites) > 128 or any(not isinstance(t, str) or t not in watchlist for t in favorites) or len(set(favorites)) != len(favorites):
        raise ValueError('无效特别关注列表')
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
