"""Coalesced market refreshes with bounded response time and durable snapshots.

Provider threads cannot be forcibly stopped safely. A timed-out subscriber leaves
one shared job running; further subscribers reuse it rather than start duplicates.
"""
from copy import deepcopy
import json
import threading
import time
from failure_log import failure


class RefreshJobs:
    def __init__(self, store, deadline=30):
        self.store = store
        self.deadline = deadline
        self.guard = threading.Lock()
        self.entries = {}
        self.capacity = threading.BoundedSemaphore(1024)

    def events(self, key, loader, ttl, valid, persist=True):
        started = time.monotonic()
        with self.guard:
            if key not in self.entries and len(self.entries) >= 1024:
                for old_key in list(self.entries):
                    if not self.entries[old_key]['running']:
                        del self.entries[old_key]
                        if len(self.entries) < 1024:
                            break
            entry = self.entries.setdefault(key, {'condition': threading.Condition(),
                'running': False, 'version': 0, 'value': None, 'expires': 0,
                'retry': 0, 'failures': 0})
        condition = entry['condition']
        with condition:
            if entry['value'] is None:
                try:
                    saved = self.store.get_cache('market:v1:' + key if persist else 'quote:' + key.split(':', 1)[1])
                    if saved and valid(saved[0]):
                        entry['value'] = saved[0]
                        entry['expires'] = time.monotonic() + max(0, ttl - (time.time() - saved[1]))
                except Exception as exc:
                    failure('database', 'market_cache_read', symbol=key, error=exc)
            fresh = entry['value'] is not None and time.monotonic() < entry['expires']
            if not fresh and not entry['running'] and time.monotonic() >= entry['retry'] and self.capacity.acquire(blocking=False):
                entry['running'] = True
                def publish(value):
                    with condition:
                        entry['latest'] = deepcopy(value)
                        entry['version'] += 1
                        condition.notify_all()
                def run():
                    try:
                        value = loader(publish)
                        successful = valid(value) and not value.get('stale') and not value.get('errors')
                        with condition:
                            if successful:
                                entry['value'] = value
                                entry['expires'] = time.monotonic() + ttl
                                entry['failures'] = 0
                                entry['retry'] = 0
                            else:
                                entry['failures'] += 1
                                entry['retry'] = time.monotonic() + min(900, 60 * 2 ** min(entry['failures'] - 1, 4))
                                if valid(value):
                                    entry['value'] = value
                                    value = {**value, 'stale': True}
                                elif entry['value'] is not None:
                                    value = {**entry['value'], 'stale': True,
                                        'errors': value.get('errors') or ['本次刷新失败，保留成功缓存']}
                        publish(value)
                        if successful and persist:
                            try:
                                self.store.set_cache('market:v1:' + key, value)
                            except Exception as exc:
                                failure('database', 'market_cache_write', symbol=key, error=exc)
                    except Exception as exc:
                        failure('backend', 'market_refresh', symbol=key, error=exc, started=started)
                        with condition:
                            entry['failures'] += 1
                            entry['retry'] = time.monotonic() + min(900, 60 * 2 ** min(entry['failures'] - 1, 4))
                        publish({**(entry['value'] or {}), 'stale': True, 'errors': ['数据刷新失败，保留成功缓存']})
                    finally:
                        with condition:
                            entry['running'] = False
                            self.capacity.release()
                            condition.notify_all()
                threading.Thread(target=run, daemon=True, name='market-refresh').start()
            version = entry['version']
            initial = deepcopy(entry['value'])
            if initial is None and entry.get('latest') is not None:
                initial = deepcopy(entry['latest'])
            running = entry['running']
        if initial is not None:
            initial = {**initial, 'cached': True, 'stale': not fresh, 'refreshing': running}
            yield initial
        while running:
            with condition:
                remaining = self.deadline - (time.monotonic() - started)
                if remaining <= 0:
                    failure('backend', 'market_deadline', symbol=key, reason='whole refresh exceeded 30 seconds', started=started, fallback_available=initial is not None)
                    yield {**(initial or {}), 'stale': True, 'refreshing': False, 'errors': ['刷新超过 30 秒，保留已取得的数据']}
                    return
                condition.wait_for(lambda: entry['version'] != version or not entry['running'], remaining)
                changed = entry['version'] != version
                version = entry['version']
                running = entry['running']
                value = deepcopy(entry.get('latest'))
            if changed and value is not None:
                initial = value
                yield {**value, 'refreshing': running}
        if initial is not None and not fresh:
            yield {**initial, 'refreshing': False}
        if initial is None:
            yield {'errors': ['数据暂不可用，稍后重试'], 'stale': True}

    def response(self, key, loader, ttl, valid, persist=True, stream=False):
        events = self.events(key, loader, ttl, valid, persist)
        if stream:
            from flask import Response
            return Response((json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n' for value in events),
                mimetype='application/x-ndjson', headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
        from flask import jsonify
        return jsonify(list(events)[-1])
