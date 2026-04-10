from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any

from .config import DB_PATH

log = logging.getLogger(__name__)

# Module-level connection cache: one WAL connection per db_path, reused across classes.
_connections: dict[str, sqlite3.Connection] = {}


def _get_connection(db_path: str) -> sqlite3.Connection:
    cx = _connections.get(db_path)
    if cx is not None:
        return cx
    cx = sqlite3.connect(db_path)
    try:
        cx.execute("PRAGMA journal_mode=WAL")
        cx.execute("PRAGMA synchronous=NORMAL")
        cx.execute("PRAGMA temp_store=MEMORY")
    except Exception:
        pass
    _connections[db_path] = cx
    return cx


class TokenCache:
    def __init__(self, db_path: str = DB_PATH):
        self._cx = _get_connection(db_path)
        self._cx.execute(
            """
            CREATE TABLE IF NOT EXISTS token_cache (
              env TEXT NOT NULL,
              company_id TEXT NOT NULL,
              username TEXT NOT NULL,
              scope TEXT,
              access_token TEXT NOT NULL,
              refresh_token TEXT,
              expires_at REAL NOT NULL,
              updated_at REAL NOT NULL,
              PRIMARY KEY(env, company_id, username, scope)
            )
            """
        )
        self._cx.commit()

    def get(self, env: str, company_id: str, username: str, scope: str) -> dict[str, Any] | None:
        cur = self._cx.execute(
            "SELECT access_token, refresh_token, expires_at FROM token_cache WHERE env=? AND company_id=? AND username=? AND IFNULL(scope,'')=IFNULL(?, '')",
            (env, company_id, username, scope or ""),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"access_token": row[0], "refresh_token": row[1], "expires_at": row[2]}

    def put(self, env: str, company_id: str, username: str, scope: str, access_token: str, refresh_token: str | None, expires_at: float) -> None:
        self._cx.execute(
            "REPLACE INTO token_cache(env, company_id, username, scope, access_token, refresh_token, expires_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (env, company_id, username, scope or "", access_token, refresh_token, expires_at, time.time()),
        )
        self._cx.commit()

    def clear(self, env: str, company_id: str, username: str, scope: str) -> None:
        self._cx.execute(
            "DELETE FROM token_cache WHERE env=? AND company_id=? AND username=? AND IFNULL(scope,'')=IFNULL(?, '')",
            (env, company_id, username, scope or ""),
        )
        self._cx.commit()


class IDMapper:
    def __init__(self, db_path: str = DB_PATH):
        self._cx = _get_connection(db_path)
        self._cx.execute(
            """
            CREATE TABLE IF NOT EXISTS id_map(
              kind TEXT NOT NULL,
              prod_id TEXT NOT NULL,
              dev_id TEXT NOT NULL,
              created_at REAL NOT NULL,
              PRIMARY KEY(kind, prod_id)
            )
            """
        )

    def get(self, kind: str, prod_id: str) -> str | None:
        cur = self._cx.execute(
            "SELECT dev_id FROM id_map WHERE kind=? AND prod_id=?",
            (kind, prod_id),
        )
        r = cur.fetchone()
        return r[0] if r else None

    def put(self, kind: str, prod_id: str, dev_id: str) -> None:
        self._cx.execute(
            "INSERT OR REPLACE INTO id_map(kind, prod_id, dev_id, created_at) VALUES(?,?,?,?)",
            (kind, prod_id, dev_id, time.time()),
        )
        self._cx.commit()


class DevIndex:
    """Persistent Dev ID -> key index to speed lookups."""

    def __init__(self, db_path: str = DB_PATH):
        self._cx = _get_connection(db_path)
        self._cx.execute(
            """
            CREATE TABLE IF NOT EXISTS dev_index(
              kind TEXT NOT NULL,
              object_id TEXT NOT NULL,
              dev_key TEXT,
              updated_at REAL NOT NULL,
              PRIMARY KEY(kind, object_id)
            )
            """
        )
        self._cx.commit()

    def get(self, kind: str, object_id: str) -> str | None:
        cur = self._cx.execute(
            "SELECT dev_key FROM dev_index WHERE kind=? AND object_id=?",
            (kind, object_id),
        )
        r = cur.fetchone()
        return r[0] if r else None

    def put(self, kind: str, object_id: str, dev_key: str | None) -> None:
        self._cx.execute(
            "INSERT OR REPLACE INTO dev_index(kind, object_id, dev_key, updated_at) VALUES(?,?,?,?)",
            (kind, object_id, dev_key or "", time.time()),
        )
        self._cx.commit()


class UoMGroupMap:
    """Persistent map: Prod UoM Group id -> Dev id + key."""

    def __init__(self, db_path: str = DB_PATH):
        self._cx = _get_connection(db_path)
        self._cx.execute(
            """
            CREATE TABLE IF NOT EXISTS uom_group_map(
              prod_id TEXT PRIMARY KEY,
              dev_id TEXT NOT NULL,
              dev_key TEXT
            )
            """
        )
        self._cx.commit()

    def get(self, prod_id: str) -> tuple[str | None, str | None]:
        cur = self._cx.execute(
            "SELECT dev_id, dev_key FROM uom_group_map WHERE prod_id=?",
            (prod_id,),
        )
        row = cur.fetchone()
        if not row:
            return None, None
        return str(row[0] or ""), str(row[1] or "")

    def put(self, prod_id: str, dev_id: str, dev_key: str | None) -> None:
        self._cx.execute(
            "INSERT OR REPLACE INTO uom_group_map(prod_id, dev_id, dev_key) VALUES(?,?,?)",
            (prod_id, dev_id, dev_key or ""),
        )
        self._cx.commit()


class LocationMap:
    """Persistent map: Prod Location id -> Dev Location id."""

    def __init__(self, db_path: str = DB_PATH):
        self._cx = _get_connection(db_path)
        self._cx.execute(
            """
            CREATE TABLE IF NOT EXISTS location_map(
              prod_id TEXT PRIMARY KEY,
              dev_id TEXT NOT NULL
            )
            """
        )
        self._cx.commit()

    def get(self, prod_id: str) -> str | None:
        cur = self._cx.execute(
            "SELECT dev_id FROM location_map WHERE prod_id=?",
            (prod_id,),
        )
        row = cur.fetchone()
        return (row[0] if row else None) or None

    def put(self, prod_id: str, dev_id: str) -> None:
        self._cx.execute(
            "INSERT OR REPLACE INTO location_map(prod_id, dev_id) VALUES(?,?)",
            (prod_id, dev_id),
        )
        self._cx.commit()
