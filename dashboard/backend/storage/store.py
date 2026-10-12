"""Private PostgreSQL storage; SQLite is injected only by local tests."""
from contextlib import contextmanager
from datetime import datetime
import atexit
import os
import hashlib
import json
import secrets
import sqlite3
import time
import threading
from copy import deepcopy
from collections import OrderedDict
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from backend.domain.state_validation import validate
from backend.infrastructure.failure_log import failure
from backend.storage.notifications import SCHEMA as NOTIFICATION_SCHEMA


class BoundedConnection(psycopg.Connection):
    """Do not let a silent socket retain a pool slot indefinitely.

    Pool checkout/connect timeouts do not bound reads on an established socket.
    SQL timeouts also cannot protect the checkout probe or a lost response.
    Close an uncertain connection instead of replaying a possibly committed write.
    """
    response_timeout = 8.0

    def wait(self, gen, interval=0.1, timeout=None):
        limit = self.response_timeout if timeout is None else min(timeout, self.response_timeout)
        try:
            return super().wait(gen, interval=interval, timeout=limit)
        except psycopg.OperationalError:
            self.close()
            raise

SCHEMA = """
CREATE TABLE IF NOT EXISTS owner (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    user_handle TEXT NOT NULL,
    state TEXT,
    revision INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS credentials (
    id TEXT PRIMARY KEY, public_key TEXT NOT NULL,
    sign_count BIGINT NOT NULL, label TEXT NOT NULL, created DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, created DOUBLE PRECISION NOT NULL, expires DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS flows (
    id TEXT PRIMARY KEY, payload TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS state_history (
    revision INTEGER PRIMARY KEY, state TEXT NOT NULL, created DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS disabled_accounts (
    id TEXT PRIMARY KEY, created DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS revoked_passkeys (
    id TEXT PRIMARY KEY, created DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS invitations (
    id TEXT PRIMARY KEY, created DOUBLE PRECISION NOT NULL, expires DOUBLE PRECISION NOT NULL,
    used_by TEXT
);
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, state TEXT, revision INTEGER NOT NULL DEFAULT 0,
    created DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS account_history (
    user_id TEXT NOT NULL, revision INTEGER NOT NULL, state TEXT NOT NULL, created DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (user_id, revision)
);
CREATE TABLE IF NOT EXISTS cache (
    id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL
);
"""


def digest(token: str) -> str:
    """Persist only a hash of session/challenge bearer tokens."""
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    """Account records, changed under a database row lock."""

    def __init__(self, database_url: str | None = None, *, sqlite_path: str | None = None):
        if not sqlite_path and not (database_url or "").startswith(("postgres://", "postgresql://")):
            raise ValueError("DATABASE_URL 必须为 PostgreSQL 连接地址")
        self._hot_cache = OrderedDict()
        self._hot_guard = threading.Lock()
        self.created_pid = os.getpid()
        self.database_url = database_url
        self.sqlite_path = sqlite_path
        self.pool = self.cache_pool = None
        if not sqlite_path:
            pool_options = dict(connection_class=BoundedConnection,
                kwargs={"row_factory":dict_row,"connect_timeout":8,
                "sslmode":"require","prepare_threshold":None,"keepalives":1,
                "keepalives_idle":10,"keepalives_interval":3,"keepalives_count":2,
                "tcp_user_timeout":10000}, timeout=8, open=True,
                check=ConnectionPool.check_connection)
            self.pool = ConnectionPool(database_url, min_size=1, max_size=4, **pool_options)
            # Bulk public cache jobs cannot consume the slots used for sessions/records.
            self.cache_pool = ConnectionPool(database_url, min_size=0, max_size=2, **pool_options)
            atexit.register(self.pool.close)
            atexit.register(self.cache_pool.close)
        with self.transaction() as connection:
            if not sqlite_path:
                # Both Render services can start during one Git push. Serialize
                # schema/privilege migrations across processes and instances;
                # PostgreSQL releases this lock when initialization commits.
                connection.execute("SELECT pg_advisory_xact_lock(1179209286,1396918349)")
                connection.execute("CREATE SCHEMA IF NOT EXISTS finfeed_private")
                connection.execute("REVOKE ALL ON SCHEMA finfeed_private FROM PUBLIC")
                connection.execute("SET search_path TO finfeed_private")
            for statement in (SCHEMA + NOTIFICATION_SCHEMA).split(";"):
                if statement.strip():
                    connection.execute(statement)
            if not sqlite_path:
                connection.execute("REVOKE ALL ON ALL TABLES IN SCHEMA finfeed_private FROM PUBLIC")
            self.execute(connection, "INSERT INTO owner (id,user_handle) VALUES (1,?) ON CONFLICT (id) DO NOTHING", (secrets.token_urlsafe(32),))
            for table in ("credentials", "sessions"):
                if sqlite_path:
                    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
                else:
                    columns = {row["column_name"] for row in connection.execute(
                        "SELECT column_name FROM information_schema.columns WHERE table_schema='finfeed_private' AND table_name=%s", (table,))}
                if "user_id" not in columns:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT")
            if sqlite_path:
                credential_columns = {row["name"] for row in connection.execute("PRAGMA table_info(credentials)")}
            else:
                credential_columns = {row["column_name"] for row in connection.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema='finfeed_private' AND table_name='credentials'")}
            if "rp_id" not in credential_columns:
                connection.execute("ALTER TABLE credentials ADD COLUMN rp_id TEXT")
            legacy = self.owner(connection)
            self.execute(connection, "INSERT INTO accounts (id,name,state,revision,created) VALUES (?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                         (legacy["user_handle"], "Liam", legacy["state"], legacy["revision"], time.time()))
            for table in ("credentials", "sessions"):
                self.execute(connection, f"UPDATE {table} SET user_id=? WHERE user_id IS NULL", (legacy["user_handle"],))
            self.execute(connection, "INSERT INTO account_history (user_id,revision,state,created) SELECT ?,revision,state,created FROM state_history WHERE 1=1 ON CONFLICT(user_id,revision) DO NOTHING", (legacy["user_handle"],))


    @contextmanager
    def transaction(self, *, cache=False) -> Iterator[Any]:
        """Commit or roll back one operation; return PostgreSQL connections to the pool."""
        if not self.sqlite_path:
            pool = self.cache_pool if cache else self.pool
            started = time.monotonic()
            try:
                with pool.connection() as connection:
                    # Bound SQL and socket waits independently of pool queueing.
                    connection.execute("SET LOCAL statement_timeout = '8s'; "
                        "SET LOCAL lock_timeout = '3s'; "
                        "SET LOCAL idle_in_transaction_session_timeout = '15s'; "
                        "SET LOCAL search_path TO finfeed_private")
                    yield connection
            except psycopg.OperationalError as exc:
                failure('database', 'pool_transaction', error=exc, started=started,
                        pool_kind='cache' if cache else 'private', pool_stats=pool.get_stats(),
                        created_pid=self.created_pid, current_pid=os.getpid(),
                        workers_alive=sum(t.is_alive() for t in pool._workers))
                raise
            return
        connection = sqlite3.connect(self.sqlite_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def execute(self, connection: Any, sql: str, parameters: tuple = ()) -> Any:
        """Use bound parameters on both production and test databases."""
        return connection.execute(sql if self.sqlite_path else sql.replace("?", "%s"), parameters)

    def owner(self, connection: Any, *, lock=True) -> dict:
        """Lock the owner row to serialize enrollment, signatures and state writes."""
        suffix = "" if self.sqlite_path or not lock else " FOR UPDATE"
        return dict(self.execute(connection, "SELECT * FROM owner WHERE id=1" + suffix).fetchone())

    def account(self, connection, user_id=None, *, lock=True):
        user_id = user_id or self.owner(connection, lock=lock)["user_handle"]
        suffix = "" if self.sqlite_path or not lock else " FOR UPDATE"
        row = self.execute(connection, "SELECT * FROM accounts WHERE id=? AND NOT EXISTS (SELECT 1 FROM disabled_accounts d WHERE d.id=accounts.id)" + suffix, (user_id,)).fetchone()
        if not row:
            raise ValueError("账户不存在")
        return dict(row)

    def accounts(self):
        with self.transaction() as connection:
            return [dict(row) for row in self.execute(connection, "SELECT a.id,a.name FROM accounts a WHERE NOT EXISTS (SELECT 1 FROM disabled_accounts d WHERE d.id=a.id) AND EXISTS (SELECT 1 FROM credentials c WHERE c.user_id=a.id AND NOT EXISTS (SELECT 1 FROM revoked_passkeys r WHERE r.id=c.id)) ORDER BY a.created").fetchall()]

    def credentials(self, connection: Any, user_id=None) -> list[dict]:
        return [dict(row) for row in self.execute(connection, "SELECT * FROM credentials WHERE NOT EXISTS (SELECT 1 FROM revoked_passkeys r WHERE r.id=credentials.id) AND NOT EXISTS (SELECT 1 FROM disabled_accounts d WHERE d.id=credentials.user_id)" + (" AND user_id=?" if user_id else "") + " ORDER BY created", (user_id,) if user_id else ()).fetchall()]

    def session(self, connection: Any, token: str, *, news=False) -> dict | None:
        if news:
            row = self.execute(connection, "SELECT s.*, a.state AS news_state FROM sessions s JOIN accounts a ON a.id=s.user_id WHERE s.id=? AND s.expires>? AND NOT EXISTS (SELECT 1 FROM disabled_accounts d WHERE d.id=s.user_id)", (digest(token), time.time())).fetchone()
            return dict(row) if row else None
        row = self.execute(connection, "SELECT * FROM sessions WHERE id=? AND expires>? AND NOT EXISTS (SELECT 1 FROM disabled_accounts d WHERE d.id=sessions.user_id)", (digest(token), time.time())).fetchone()
        return dict(row) if row else None

    def new_session(self, connection: Any, user_id=None) -> str:
        token = secrets.token_urlsafe(32)
        self.execute(connection, "INSERT INTO sessions (id,created,expires,user_id) VALUES (?,?,?,?)", (digest(token), time.time(), time.time() + 43200, user_id or self.owner(connection)["user_handle"]))
        return token

    def flow(self, connection: Any, payload: dict) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        self.execute(connection, "DELETE FROM flows WHERE expires<?", (now,))
        self.execute(connection, "DELETE FROM sessions WHERE expires<?", (now,))
        self.execute(connection, "INSERT INTO flows VALUES (?,?,?)", (digest(token), json.dumps(payload), now + 300))
        return token

    def consume_flow(self, token: str) -> dict | None:
        # Consume before verification: failed/replayed challenges cannot be retried.
        with self.transaction() as connection:
            row = self.execute(connection, "DELETE FROM flows WHERE id=? RETURNING payload, expires", (digest(token),)).fetchone()
            if row and row["expires"] > time.time():
                return json.loads(row["payload"])
        return None

    def read_state(self, user_id=None) -> dict | None:
        with self.transaction() as connection:
            row = self.account(connection, user_id, lock=False)
            return validate(json.loads(row["state"])) if row["state"] else None

    def get_cache(self, key: str) -> tuple[dict, float] | None:
        """Keep daily financial snapshots and quota counters across cloud restarts."""
        with self._hot_guard:
            item = self._hot_cache.get(key)
            if item and time.monotonic() - item[2] < 60:
                self._hot_cache.move_to_end(key)
                return deepcopy(item[:2])
        with self.transaction(cache=True) as connection:
            row = self.execute(connection, "SELECT payload,updated FROM cache WHERE id=?", (key,)).fetchone()
        if row:
            value = (json.loads(row["payload"]), row["updated"])
            self._remember_cache(key, *value)
            with self._hot_guard:
                return deepcopy(self._hot_cache[key][:2])
        return None

    def _remember_cache(self, key, payload, updated):
        with self._hot_guard:
            previous = self._hot_cache.get(key)
            if previous and previous[1] > updated:
                return
            self._hot_cache[key] = (deepcopy(payload), updated, time.monotonic())
            self._hot_cache.move_to_end(key)
            while len(self._hot_cache) > 1024:
                self._hot_cache.popitem(last=False)

    def set_cache(self, key: str, payload: dict) -> None:
        updated = time.time()
        # Public snapshot age follows collection time, never the time a cached
        # result was copied. SQL ordering also protects overlapping deployments.
        if key.startswith(('quote:', 'market:v1:', 'longbridge:v1:', 'yahoo-financial:v1:')):
            source_time = payload.get('fetched_at') or payload.get('retrieved_at')
            if source_time:
                try:
                    updated = min(updated, datetime.fromisoformat(source_time.replace('Z', '+00:00')).timestamp())
                except (ValueError, TypeError):
                    pass
        with self.transaction(cache=True) as connection:
            cursor = self.execute(connection, "INSERT INTO cache VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated=excluded.updated WHERE excluded.updated >= cache.updated",
                         (key, json.dumps(payload, ensure_ascii=False, allow_nan=False), updated))
            accepted = cursor.rowcount > 0
        if accepted:
            self._remember_cache(key, payload, updated)

    def enable_snapshot_writer(self):
        """One bounded, coalescing write lane for public snapshots only."""
        self._snapshot_pending = OrderedDict()
        self._snapshot_guard = threading.Lock()
        self._snapshot_wake = threading.Event()
        def run():
            while True:
                self._snapshot_wake.wait()
                self._snapshot_wake.clear()
                # Small window combines completions from concurrent providers.
                time.sleep(.1)
                if not self.flush_snapshots():
                    time.sleep(15)
                with self._snapshot_guard:
                    if self._snapshot_pending:
                        self._snapshot_wake.set()
        threading.Thread(target=run, daemon=True, name='snapshot-writer').start()

    def publish_cache(self, key, payload):
        if not hasattr(self, '_snapshot_pending'):
            return self.set_cache(key, payload)
        stamp = payload.get('fetched_at') or payload.get('retrieved_at')
        try:
            updated = min(time.time(), datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp())
        except (AttributeError, ValueError, TypeError):
            updated = time.time()
        self._remember_cache(key, payload, updated)
        with self._snapshot_guard:
            previous = self._snapshot_pending.get(key)
            if previous and previous[1] > updated:
                return
            self._snapshot_pending[key] = (deepcopy(payload), updated)
            if len(self._snapshot_pending) > 1024:
                self._snapshot_pending.popitem(last=False)
                failure('database', 'snapshot_queue_full', reason='public snapshot retained in memory only')
        self._snapshot_wake.set()

    def flush_snapshots(self):
        with self._snapshot_guard:
            batch = list(self._snapshot_pending.items())[:32]
        if not batch:
            return True
        try:
            with self.transaction(cache=True) as connection:
                for key, (payload, updated) in batch:
                    self.execute(connection, "INSERT INTO cache VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated=excluded.updated WHERE excluded.updated >= cache.updated",
                        (key, json.dumps(payload, ensure_ascii=False, allow_nan=False), updated))
            with self._snapshot_guard:
                for key, item in batch:
                    if self._snapshot_pending.get(key) == item:
                        del self._snapshot_pending[key]
            return True
        except Exception as exc:
            failure('database', 'snapshot_batch_write', error=exc)
            return False

    def _cached_batch(self, keys):
        found = {}
        with self._hot_guard:
            for key in keys:
                item = self._hot_cache.get(key)
                if item and time.monotonic() - item[2] < 60:
                    found[key] = deepcopy(item[:2])
        missing = [key for key in keys if key not in found]
        if missing:
            try:
                with self.transaction(cache=True) as connection:
                    rows = self.execute(connection, "SELECT id,payload,updated FROM cache WHERE id IN (" + ",".join("?" for _ in missing) + ")", missing).fetchall()
            except Exception as exc:
                failure('database', 'snapshot_batch_read', error=exc)
                rows = []
            # Even a failed database read must not discard successful in-memory
            # snapshots. Their original timestamps still govern freshness.
            with self._hot_guard:
                for key in missing:
                    if key in self._hot_cache:
                        found[key] = deepcopy(self._hot_cache[key][:2])
            for row in rows:
                self._remember_cache(row['id'], json.loads(row['payload']), row['updated'])
                with self._hot_guard:
                    found[row['id']] = deepcopy(self._hot_cache[row['id']][:2])
        return found

    def get_cached_quotes(self, symbols: list[str]) -> dict:
        """Batch only memory misses; never refetch providers on bootstrap."""
        values = self._cached_batch(['quote:' + symbol for symbol in symbols])
        return {key[6:]: {**payload, 'cached': True,
                'cache_age_seconds': round(max(0, time.time() - updated))}
                for key, (payload, updated) in values.items()}

    def get_cached_news(self, symbols: list[str]) -> dict:
        keys = ['market:v1:news:' + version + ':' + kind + ':' + symbol
                for symbol in symbols for kind in ('calls',) for version in ('v1', 'v2')]
        keys += ['market:v1:news:sec-edgar:v1:' + symbol for symbol in symbols]
        values = self._cached_batch(keys)
        return {key: {**payload, 'cached': True,
                'cache_age_seconds': round(max(0, time.time() - updated))}
                for key, (payload, updated) in values.items() if time.time() - updated <= 7 * 86400}

    def update_state(self, patch: dict, *, require_empty: bool = False, user_id=None) -> dict:
        if not isinstance(patch, dict) or set(patch) - {"watchlist", "positions", "watchlistFavorites", "uiPreferences", "initialize"}:
            raise ValueError("无效保存字段")
        with self.transaction() as connection:
            owner = self.account(connection, user_id)
            current = json.loads(owner["state"]) if owner["state"] else None
            if require_empty and current is not None:
                raise ValueError("云端已有记录，拒绝覆盖；请通过登录后的导入功能操作")
            if patch.get("initialize") and current is not None:
                return current
            merged = {**(current or {"watchlist": [], "positions": []}),
                      **{key: value for key, value in patch.items() if key != "initialize"}}
            if 'uiPreferences' in patch:
                from backend.domain.state_validation import validate_preferences
                preferences = validate_preferences(patch['uiPreferences'])
                merged['uiPreferences'] = {**(current or {}).get('uiPreferences', {}), **preferences}
            # Older clients can remove a ticker without sending the optional field.
            if isinstance(patch.get('watchlist'), list) and 'watchlistFavorites' not in patch and 'watchlistFavorites' in merged:
                merged['watchlistFavorites'] = [t for t in merged['watchlistFavorites'] if t in merged['watchlist']]
            state = validate(merged)
            if current == state:
                return state
            revision = owner["revision"] + 1
            if current is not None:
                self.execute(connection, "INSERT INTO account_history VALUES (?,?,?,?)", (owner["id"], owner["revision"], json.dumps(current), time.time()))
                self.execute(connection, "DELETE FROM account_history WHERE user_id=? AND revision<?", (owner["id"], revision - 50))
            self.execute(connection, "UPDATE accounts SET state=?,revision=? WHERE id=?", (json.dumps(state, ensure_ascii=False, allow_nan=False), revision, owner["id"]))
            return state
