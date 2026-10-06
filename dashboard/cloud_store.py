"""Private PostgreSQL storage; SQLite is injected only by local tests."""
from contextlib import contextmanager
import atexit
import hashlib
import json
import secrets
import sqlite3
import time
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from state import validate

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
        self.database_url = database_url
        self.sqlite_path = sqlite_path
        self.pool = None if sqlite_path else ConnectionPool(
            database_url, kwargs={"row_factory":dict_row,"connect_timeout":30,"sslmode":"require","prepare_threshold":None},
            min_size=1, max_size=4, timeout=30, open=True, check=ConnectionPool.check_connection)
        if self.pool:
            atexit.register(self.pool.close)
        with self.transaction() as connection:
            if not sqlite_path:
                # Both Render services can start during one Git push. Serialize
                # schema/privilege migrations across processes and instances;
                # PostgreSQL releases this lock when initialization commits.
                connection.execute("SELECT pg_advisory_xact_lock(1179209286,1396918349)")
                connection.execute("CREATE SCHEMA IF NOT EXISTS finfeed_private")
                connection.execute("REVOKE ALL ON SCHEMA finfeed_private FROM PUBLIC")
                connection.execute("SET search_path TO finfeed_private")
            for statement in SCHEMA.split(";"):
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
    def transaction(self) -> Iterator[Any]:
        """Commit or roll back one operation; return PostgreSQL connections to the pool."""
        if not self.sqlite_path:
            with self.pool.connection() as connection:
                connection.execute("SET LOCAL search_path TO finfeed_private")
                yield connection
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

    def session(self, connection: Any, token: str) -> dict | None:
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
        with self.transaction() as connection:
            row = self.execute(connection, "SELECT payload,updated FROM cache WHERE id=?", (key,)).fetchone()
            return (json.loads(row["payload"]), row["updated"]) if row else None

    def set_cache(self, key: str, payload: dict) -> None:
        with self.transaction() as connection:
            self.execute(connection, "INSERT INTO cache VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated=excluded.updated",
                         (key, json.dumps(payload, ensure_ascii=False, allow_nan=False), time.time()))

    def get_cached_quotes(self, symbols: list[str]) -> dict:
        """Read tracked snapshots in one database round trip, without a provider call."""
        if not symbols:
            return {}
        keys = ["quote:" + symbol for symbol in symbols]
        with self.transaction() as connection:
            rows = self.execute(connection, "SELECT id,payload,updated FROM cache WHERE id IN (" + ",".join("?" for _ in keys) + ")", keys).fetchall()
        return {row["id"][6:]: {**json.loads(row["payload"]), "cached": True,
                                "cache_age_seconds": round(max(0, time.time() - row["updated"]))}
                for row in rows}

    def update_state(self, patch: dict, *, require_empty: bool = False, user_id=None) -> dict:
        if not isinstance(patch, dict) or set(patch) - {"watchlist", "positions", "initialize"}:
            raise ValueError("无效保存字段")
        with self.transaction() as connection:
            owner = self.account(connection, user_id)
            current = json.loads(owner["state"]) if owner["state"] else None
            if require_empty and current is not None:
                raise ValueError("云端已有记录，拒绝覆盖；请通过登录后的导入功能操作")
            if patch.get("initialize") and current is not None:
                return current
            state = validate({**(current or {"watchlist": [], "positions": []}),
                              **{key: value for key, value in patch.items() if key != "initialize"}})
            if current == state:
                return state
            revision = owner["revision"] + 1
            if current is not None:
                self.execute(connection, "INSERT INTO account_history VALUES (?,?,?,?)", (owner["id"], owner["revision"], json.dumps(current), time.time()))
                self.execute(connection, "DELETE FROM account_history WHERE user_id=? AND revision<?", (owner["id"], revision - 50))
            self.execute(connection, "UPDATE accounts SET state=?,revision=? WHERE id=?", (json.dumps(state, ensure_ascii=False, allow_nan=False), revision, owner["id"]))
            return state
