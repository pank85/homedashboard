"""Optional SQLite persistence for chat sessions and herdr snapshots.

Stdlib ``sqlite3`` only. ``open_db`` never raises: an empty path, an unwritable
path, or a journal that will not stay in WAL leaves ``available`` false and a
reason string. One connection per instance; every public method holds the
instance ``RLock`` for the whole call.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SNAPSHOT_COLUMNS = (
    "observed_at",
    "herdr_session",
    "workspace_id",
    "workspace_label",
    "tab_id",
    "tab_label",
    "pane_id",
    "agent_kind",
    "agent_label",
    "status",
    "cwd",
)


# Applied only when PRAGMA user_version is 0, then user_version is set to 1.
# CREATE IF NOT EXISTS so a crash before the version bump can retry safely.
SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS herdr_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at TEXT NOT NULL,
    herdr_session TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    workspace_label TEXT NOT NULL DEFAULT '',
    tab_id TEXT NOT NULL DEFAULT '',
    tab_label TEXT NOT NULL DEFAULT '',
    pane_id TEXT NOT NULL DEFAULT '',
    agent_kind TEXT NOT NULL DEFAULT '',
    agent_label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    cwd TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_herdr_snapshots_observed_at
    ON herdr_snapshots (observed_at);
"""


def _format_timestamp(moment: datetime) -> str:
    """UTC seconds timestamp. Text order matches time order."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    else:
        moment = moment.astimezone(timezone.utc)
    return moment.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _now_text() -> str:
    return _format_timestamp(datetime.now(timezone.utc))


def _snapshot_text(row: dict, key: str) -> str:
    if key not in row or row[key] is None:
        return ""
    value = row[key]
    if not isinstance(value, str):
        raise ValueError(f"snapshot field {key} must be str")
    return value


def _disable(db: DashboardDb, conn: sqlite3.Connection | None, reason: str) -> DashboardDb:
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error:
            pass
    db._conn = None
    db.available = False
    db.reason = reason
    return db


def _migrate(conn: sqlite3.Connection) -> None:
    row = conn.execute("PRAGMA user_version").fetchone()
    version = 0 if row is None else int(row[0])
    if version != 0:
        return
    conn.executescript(SCHEMA_V1)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()


class DashboardDb:
    available: bool
    reason: str | None

    def __init__(self, retention_days: int = 7) -> None:
        self.available = False
        self.reason = "persistence unavailable"
        self.retention_days = retention_days
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    def insert_snapshots(self, rows: list[dict], *, now: datetime | None = None) -> int:
        """Insert, then delete rows with ``observed_at`` strictly older than the cutoff.

        Returns the deleted count. Empty input still prunes. Unavailable DB
        returns 0 and does not raise. Snapshot status is stored as given,
        including herdr words ``working`` and ``unknown``.
        """
        with self._lock:
            conn = self._conn
            if conn is None or not self.available:
                return 0
            anchor = now if now is not None else datetime.now(timezone.utc)
            stamp = _format_timestamp(anchor)
            # retention_days 0 deletes strictly older than now; it does not mean keep forever.
            cutoff = _format_timestamp(anchor - timedelta(days=self.retention_days))
            try:
                for row in rows:
                    self._insert_snapshot(conn, row, stamp)
                deleted = conn.execute(
                    "DELETE FROM herdr_snapshots WHERE observed_at < ?",
                    (cutoff,),
                ).rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return deleted

    def close(self) -> None:
        with self._lock:
            conn = self._conn
            self._conn = None
            if conn is not None:
                self.available = False
                if self.reason is None:
                    self.reason = "persistence unavailable"
                conn.close()

    def _usable(self) -> bool:
        return self.available and self._conn is not None

    def _require_usable(self) -> sqlite3.Connection:
        if not self._usable():
            raise RuntimeError(self.reason or "persistence unavailable")
        conn = self._conn
        assert conn is not None
        return conn

    def _insert_snapshot(self, conn: sqlite3.Connection, row: dict, stamp: str) -> None:
        observed = row.get("observed_at")
        if observed is None:
            observed_at = stamp
        elif isinstance(observed, str):
            observed_at = observed
        else:
            raise ValueError("snapshot field observed_at must be str")
        values = {"observed_at": observed_at}
        for column in _SNAPSHOT_COLUMNS:
            if column == "observed_at":
                continue
            values[column] = _snapshot_text(row, column)
        names = ", ".join(_SNAPSHOT_COLUMNS)
        placeholders = ", ".join("?" for _ in _SNAPSHOT_COLUMNS)
        conn.execute(
            f"INSERT INTO herdr_snapshots ({names}) VALUES ({placeholders})",
            [values[column] for column in _SNAPSHOT_COLUMNS],
        )


def open_db(path: str, *, retention_days: int = 7) -> DashboardDb:
    """Open one WAL connection, or return an unavailable DB. Never raises."""
    try:
        return _open_db(path, retention_days=retention_days)
    except Exception:
        db = DashboardDb(retention_days if isinstance(retention_days, int) else 7)
        db.available = False
        try:
            db.reason = "persistence unavailable" if path == "" else f"db path not writable: {path}"
        except Exception:
            db.reason = "persistence unavailable"
        return db


def _open_db(path: str, *, retention_days: int) -> DashboardDb:
    db = DashboardDb(retention_days)
    if path == "":
        return db
    conn: sqlite3.Connection | None = None
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False, timeout=5.0)
        mode_row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        mode = "" if mode_row is None else str(mode_row[0]).lower()
        if mode != "wal":
            return _disable(db, conn, "journal_mode is not wal")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        _migrate(conn)
        conn.execute("DROP TABLE IF EXISTS chat_sessions")
        conn.commit()
    except OSError:
        return _disable(db, conn, f"db path not writable: {path}")
    except sqlite3.Error:
        return _disable(db, conn, f"db path not writable: {path}")
    except Exception:
        return _disable(db, conn, "persistence unavailable")
    db._conn = conn
    db.available = True
    db.reason = None
    return db
