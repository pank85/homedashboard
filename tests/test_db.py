"""Tests for optional SQLite persistence. tmp_path only; never /data."""

from __future__ import annotations

import ast
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import db as db_module
from app.db import open_db

TIMESTAMP_RE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$"
NOW = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
SESSION_COLUMNS = (
    "id",
    "label",
    "agent_kind",
    "herdr_session",
    "workspace_id",
    "tab_id",
    "pane_id",
    "agent_name",
    "cwd",
    "status",
    "last_error",
    "created_at",
    "updated_at",
)


def _row(**overrides: str) -> dict:
    row = {
        "id": "abc123",
        "label": "pi-20240615120000",
        "agent_kind": "pi",
        "herdr_session": "hermes",
        "cwd": "/work",
        "status": "starting",
    }
    row.update(overrides)
    return row


def _snapshots(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT workspace_id, observed_at, status FROM herdr_snapshots ORDER BY observed_at, workspace_id"
        ).fetchall()
    finally:
        conn.close()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "dashboard.db"


@pytest.fixture
def db(db_path: Path):
    opened = open_db(str(db_path))
    try:
        yield opened
    finally:
        opened.close()




def test_stdlib_sqlite_only():
    source = Path(db_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    assert modules <= {"__future__", "sqlite3", "threading", "datetime", "pathlib"}
    assert "subprocess" not in source
    assert "os.system" not in source
    assert "fastapi" not in source.lower()






def test_prune_deletes_strictly_older_rows(db, db_path: Path):
    deleted = db.insert_snapshots(
        [
            {
                "observed_at": "2024-06-08T11:59:59+00:00",
                "herdr_session": "hermes",
                "workspace_id": "old",
                "status": "working",
            },
            {
                "observed_at": "2024-06-08T12:00:00+00:00",
                "herdr_session": "hermes",
                "workspace_id": "cutoff",
                "status": "unknown",
            },
            {
                "observed_at": "2024-06-14T12:00:00+00:00",
                "herdr_session": "hermes",
                "workspace_id": "fresh",
                "status": "running",
            },
        ],
        now=NOW,
    )
    assert deleted == 1
    assert _snapshots(db_path) == [
        ("cutoff", "2024-06-08T12:00:00+00:00", "unknown"),
        ("fresh", "2024-06-14T12:00:00+00:00", "running"),
    ]

    pruned = db.insert_snapshots([], now=datetime(2024, 6, 16, 12, 0, 1, tzinfo=timezone.utc))
    assert pruned == 1
    assert _snapshots(db_path) == [("fresh", "2024-06-14T12:00:00+00:00", "running")]


def test_retention_zero_does_not_keep_forever(tmp_path: Path):
    path = tmp_path / "dashboard.db"
    opened = open_db(str(path), retention_days=0)
    try:
        deleted = opened.insert_snapshots(
            [
                {
                    "observed_at": "2024-06-15T11:59:59+00:00",
                    "herdr_session": "hermes",
                    "workspace_id": "old",
                    "status": "idle",
                },
                {
                    "observed_at": "2024-06-15T12:00:00+00:00",
                    "herdr_session": "hermes",
                    "workspace_id": "now",
                    "status": "running",
                },
            ],
            now=NOW,
        )
        assert deleted == 1
        assert _snapshots(path) == [("now", "2024-06-15T12:00:00+00:00", "running")]
    finally:
        opened.close()


def test_empty_path_is_unavailable(monkeypatch: pytest.MonkeyPatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("connect should not be called")

    monkeypatch.setattr("app.db.sqlite3.connect", boom)
    opened = open_db("")
    assert opened.available is False
    assert opened.reason == "persistence unavailable"
    assert opened.insert_snapshots([{"herdr_session": "h", "workspace_id": "w", "status": "running"}]) == 0
    opened.close()


def test_file_parent_is_unavailable(tmp_path: Path):
    parent = tmp_path / "not-a-dir"
    parent.write_text("x")
    target = str(parent / "dashboard.db")
    opened = open_db(target)
    assert opened.available is False
    assert opened.reason == f"db path not writable: {target}"
    assert opened.insert_snapshots([]) == 0
    opened.close()


def test_unwritable_directory_is_unavailable(tmp_path: Path):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o500)
    target = str(blocked / "dashboard.db")
    try:
        opened = open_db(target)
        assert opened.available is False
        assert opened.reason == f"db path not writable: {target}"
        assert not Path(target).exists()
    finally:
        blocked.chmod(0o700)




def test_journal_mode_wal_and_check_same_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    saved: dict = {}
    real_connect = sqlite3.connect

    def wrapped(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        saved["conn"] = conn
        saved["kwargs"] = kwargs
        saved["calls"] = saved.get("calls", 0) + 1
        return conn

    monkeypatch.setattr("app.db.sqlite3.connect", wrapped)
    path = tmp_path / "dashboard.db"
    opened = open_db(str(path))
    try:
        assert opened.available is True
        assert opened.reason is None
        assert saved["calls"] == 1
        assert saved["kwargs"]["check_same_thread"] is False
        assert saved["kwargs"]["timeout"] == 5.0
        assert type(opened._lock) is type(threading.RLock())
        conn = saved["conn"]
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        opened.close()

    other = sqlite3.connect(path)
    try:
        assert other.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        other.close()




class _RollbackJournal(sqlite3.Connection):
    def execute(self, sql, parameters=()):
        if isinstance(sql, str) and "journal_mode" in sql.lower():
            return super().execute("SELECT 'delete'")
        return super().execute(sql, parameters)


def test_wal_must_stick(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    real_connect = sqlite3.connect

    def wrapped(*args, **kwargs):
        kwargs["factory"] = _RollbackJournal
        return real_connect(*args, **kwargs)

    monkeypatch.setattr("app.db.sqlite3.connect", wrapped)
    path = tmp_path / "dashboard.db"
    opened = open_db(str(path))
    assert opened.available is False
    assert opened.reason == "journal_mode is not wal"
    assert opened.insert_snapshots([{"herdr_session": "h", "workspace_id": "w", "status": "running"}]) == 0
    opened.close()


def test_schema_has_only_herdr_snapshots(tmp_path: Path):
    path = tmp_path / "dashboard.db"
    opened = open_db(str(path))
    opened.close()
    conn = sqlite3.connect(path)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        assert tables == ["herdr_snapshots"]
    finally:
        conn.close()
