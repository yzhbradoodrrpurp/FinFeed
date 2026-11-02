"""Private per-account chart annotations, separate from public market snapshots."""
from datetime import date
import hashlib
import json
import math
import re
import time


def validate_line(line):
    if not isinstance(line, dict) or set(line) != {'id', 'points'} or not isinstance(line['id'], str) or not re.fullmatch(r'[a-f0-9]{32}', line['id']):
        raise ValueError('无效划线标识')
    if not isinstance(line['points'], list) or len(line['points']) != 2:
        raise ValueError('划线需要两个端点')
    for point in line['points']:
        if not isinstance(point, dict) or set(point) != {'time', 'price'}:
            raise ValueError('无效划线端点')
        stamp, price = point['time'], point['price']
        if not isinstance(stamp, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', stamp):
            raise ValueError('无效划线日期')
        try:
            day = date.fromisoformat(stamp)
        except ValueError:
            raise ValueError('无效划线日期') from None
        if not 1970 <= day.year <= 2100 or isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or not 0 < price <= 1e12:
            raise ValueError('无效划线价格或日期')
    if line['points'][0]['time'] == line['points'][1]['time']:
        raise ValueError('请选择不同日期的两个端点')
    return line


def record(store, user_id, symbol, operation=None):
    # Use private DB transactions, never Store.get_cache/set_cache or hot/public caches.
    prefix = 'private:chart-drawings:v1:' + hashlib.sha256(user_id.encode()).hexdigest() + ':'
    key = prefix + symbol
    with store.transaction() as connection:
        store.account(connection, user_id, lock=operation is not None)
        row = store.execute(connection, 'SELECT payload FROM cache WHERE id=?', (key,)).fetchone()
        value = json.loads(row['payload']) if row else {'revision': 0, 'lines': [], 'adjustment': 'ForwardAdjust'}
        if operation is None:
            return value
        if not isinstance(operation, dict):
            raise ValueError('无效划线操作')
        lines = value['lines']
        if operation.get('operation') == 'add' and set(operation) == {'operation', 'line'}:
            line = validate_line(operation['line'])
            existing = next((item for item in lines if item['id'] == line['id']), None)
            if existing is not None:
                if existing != line:
                    raise ValueError('划线标识已存在，请重新绘制')
                return value  # An uncertain network response can be retried safely.
            if len(lines) >= 100:
                raise ValueError('每个标的最多保存 100 条线，请先清除部分划线')
            if row is None:
                count = store.execute(connection, 'SELECT COUNT(*) AS n FROM cache WHERE id LIKE ?', (prefix + '%',)).fetchone()['n']
                if count >= 128:
                    raise ValueError('最多保存 128 个标的的划线')
            lines = [*lines, line]
        elif operation.get('operation') == 'delete' and set(operation) == {'operation', 'ids'}:
            ids = operation['ids']
            if not isinstance(ids, list) or len(ids) > 100 or any(not isinstance(item, str) or not re.fullmatch(r'[a-f0-9]{32}', item) for item in ids):
                raise ValueError('无效删除标识')
            lines = [line for line in lines if line['id'] not in ids]
            if lines == value['lines']:
                return value
        else:
            raise ValueError('无效划线操作')
        value = {'revision': value['revision'] + 1, 'lines': lines, 'adjustment': 'ForwardAdjust', 'updated_at': time.time()}
        store.execute(connection, 'INSERT INTO cache(id,payload,updated) VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated=excluded.updated',
                      (key, json.dumps(value, allow_nan=False), time.time()))
        return value
