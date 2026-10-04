"""Private PostgreSQL storage; SQLite is injected only by local tests."""
from contextlib import contextmanager
import hashlib
import json
import secrets
import sqlite3
import time
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

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
CREATE TABLE IF NOT EXISTS cache (
    id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL
);
"""


def digest(token: str) -> str:
    """Persist only a hash of session/challenge bearer tokens."""
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    """Single-owner records, changed under a database row lock."""

    def __init__(self, database_url: str | None = None, *, sqlite_path: str | None = None):
        if not sqlite_path and not (database_url or "").startswith(("postgres://", "postgresql://")):
            raise ValueError("DATABASE_URL 必须为 PostgreSQL 连接地址")
        self.database_url = database_url
        self.sqlite_path = sqlite_path
        with self.transaction() as connection:
            if not sqlite_path:
                connection.execute("CREATE SCHEMA IF NOT EXISTS finfeed_private")
                connection.execute("REVOKE ALL ON SCHEMA finfeed_private FROM PUBLIC")
                connection.execute("SET search_path TO finfeed_private")
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    connection.execute(statement)
            if not sqlite_path:
                connection.execute("REVOKE ALL ON ALL TABLES IN SCHEMA finfeed_private FROM PUBLIC")
            self.execute(connection, "INSERT INTO owner (id,user_handle) VALUES (1,?) ON CONFLICT (id) DO NOTHING", (secrets.token_urlsafe(32),))

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """A connection per request, committed or rolled back as one operation."""
        if self.sqlite_path:
            connection = sqlite3.connect(self.sqlite_path, timeout=10)
            connection.row_factory = sqlite3.Row
        else:
            connection = psycopg.connect(self.database_url, row_factory=dict_row,
                                         connect_timeout=10, sslmode="require", prepare_threshold=None)
        try:
            if self.sqlite_path:
                connection.execute("BEGIN IMMEDIATE")
            else:
                # This schema is not exposed through Supabase's public REST API.
                connection.execute("SET search_path TO finfeed_private")
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

    def owner(self, connection: Any) -> dict:
        """Lock the owner row to serialize enrollment, signatures and state writes."""
        suffix = "" if self.sqlite_path else " FOR UPDATE"
        return dict(self.execute(connection, "SELECT * FROM owner WHERE id=1" + suffix).fetchone())

    def credentials(self, connection: Any) -> list[dict]:
        return [dict(row) for row in self.execute(connection, "SELECT * FROM credentials ORDER BY created").fetchall()]

    def session(self, connection: Any, token: str) -> dict | None:
        row = self.execute(connection, "SELECT * FROM sessions WHERE id=? AND expires>?", (digest(token), time.time())).fetchone()
        return dict(row) if row else None

    def new_session(self, connection: Any) -> str:
        token = secrets.token_urlsafe(32)
        self.execute(connection, "INSERT INTO sessions VALUES (?,?,?)", (digest(token), time.time(), time.time() + 43200))
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

    def read_state(self) -> dict | None:
        with self.transaction() as connection:
            row = self.owner(connection)
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

    def update_state(self, patch: dict, *, require_empty: bool = False) -> dict:
        if not isinstance(patch, dict) or set(patch) - {"watchlist", "positions", "initialize"}:
            raise ValueError("无效保存字段")
        with self.transaction() as connection:
            owner = self.owner(connection)
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
                self.execute(connection, "INSERT INTO state_history VALUES (?,?,?)", (owner["revision"], json.dumps(current), time.time()))
                self.execute(connection, "DELETE FROM state_history WHERE revision<?", (revision - 50,))
            self.execute(connection, "UPDATE owner SET state=?,revision=? WHERE id=1", (json.dumps(state, ensure_ascii=False, allow_nan=False), revision))
            return state
