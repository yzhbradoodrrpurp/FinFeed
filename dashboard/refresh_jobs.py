"""Coalesced market refreshes with bounded response time and durable snapshots.

Provider threads cannot be forcibly stopped safely. A timed-out subscriber leaves
one shared job running; further subscribers reuse it rather than start duplicates.
"""
from copy import deepcopy
import json
import queue
import threading
import time
from failure_log import failure


class RefreshJobs:
    def __init__(self, store, deadline=25, limits=None):
        self.store = store
        self.deadline = deadline
        self.guard = threading.Lock()
        self.entries = {}
        self.capacity = threading.BoundedSemaphore(256)
        self.limits = limits or {'security': 4, 'news': 2, 'whales': 2, 'macro': 2, 'home': 2}
        self.queues = {}

    def submit(self, key, work):
        # Separate lanes keep long SEC/provider jobs from starving minute quotes.
        lane = key.split(':', 1)[0]
        with self.guard:
            if lane not in self.queues:
                pending = self.queues[lane] = queue.Queue()
                def worker():
                    while True:
                        task = pending.get()
                        try:
                            task()
                        finally:
                            pending.task_done()
                for index in range(self.limits.get(lane, 2)):
                    threading.Thread(target=worker, daemon=True,
                        name=f'refresh-{lane}-{index}').start()
            self.queues[lane].put(work)

    def events(self, key, loader, ttl, valid, persist=True, force=False):
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
            if entry['value'] is None and not entry.get('cache_checked'):
                try:
                    saved = self.store.get_cache('market:v1:' + key if persist else 'quote:' + key.split(':', 1)[1])
                    if saved and valid(saved[0]):
                        entry['value'] = saved[0]
                        entry['expires'] = time.monotonic() + max(0, ttl - (time.time() - saved[1]))
                except Exception as exc:
                    failure('database', 'market_cache_read', symbol=key, error=exc)
                entry['cache_checked'] = True
            fresh = entry['value'] is not None and not entry['failures'] and not entry['value'].get('stale') and time.monotonic() < entry['expires']
            # Concurrent tabs share a just-completed refresh; scheduled cycles bypass older caches.
            if force and time.monotonic() - entry.get('completed', float('-inf')) >= 5:
                fresh = False
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
                        # A missing finance block must not slow healthy minute quotes.
                        successful = valid(value) and not value.get('stale') and not value.get('partial') and not value.get('refreshing') and (key.startswith('security:') or not value.get('errors'))
                        with condition:
                            if successful:
                                entry['value'] = value
                                entry['expires'] = time.monotonic() + ttl
                                entry['completed'] = time.monotonic()
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
                                getattr(self.store, 'publish_cache', self.store.set_cache)('market:v1:' + key, value)
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
                self.submit(key, run)
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
                    yield {**(initial or {}), 'stale': True, 'refreshing': True, 'pending': True}
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

    def response(self, key, loader, ttl, valid, persist=True, stream=False, force=False):
        events = self.events(key, loader, ttl, valid, persist, force)
        if stream:
            from flask import Response
            return Response((json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n' for value in events),
                mimetype='application/x-ndjson', headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
        from flask import jsonify
        return jsonify(list(events)[-1])
