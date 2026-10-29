"""Authenticated routes serve public snapshots without waiting on providers."""
from copy import deepcopy
import hashlib
import json
import time
from flask import jsonify, request, Response

# Collection/check timestamps must not turn unchanged values into new content.
VOLATILE = {'fetched_at', 'retrieved_at', 'checked_at', 'financial_checked_at',
            'financial_fetched_at', 'history_retrieved_at', 'refresh_checked_at',
            'market_fetched_at', 'cached', 'refreshing', 'cache_age_seconds',
            'cache_version', 'server_checked_at', 'client_checked_at'}


def content_version(value):
    def clean(item):
        if isinstance(item, dict):
            return {k: clean(v) for k, v in item.items() if k not in VOLATILE}
        if isinstance(item, list):
            return [clean(v) for v in item]
        return item
    return hashlib.sha256(json.dumps(clean(value), sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def response(store, key, ttl, present=None):
    saved = store.get_cache(key)
    if not saved:
        return jsonify(pending=True, refreshing=True, errors=[], cache_status='warming'), 202
    value, updated = saved
    value = deepcopy(present(value) if present else value)
    age = max(0, time.time()-updated)
    status = store.get_cache('refresh-status:' + key)
    failed = status and status[0].get('failed') and status[1] >= updated
    if age > ttl*2 or failed:
        value['stale'] = True
        value['errors'] = list(dict.fromkeys([*value.get('errors', []), '后台更新尚未成功，保留上次数据']))
    value.pop('pending', None)
    value.pop('refreshing', None)
    version = content_version(value)
    headers = {'ETag': '"'+version+'"', 'X-FinFeed-Checked-At': str(updated),
               'Cache-Control': 'no-store'}
    if request.args.get('version') == version or request.if_none_match.contains(version):
        return Response(status=304, headers=headers)
    value.update(cache_version=version, server_checked_at=updated, cached=True,
                 cache_age_seconds=round(age))
    result = jsonify(value)
    result.headers.update(headers)
    return result
