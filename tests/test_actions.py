"""HTTP boundary for session mutations, present, and herdr argv."""

from __future__ import annotations

import ast
import json
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.formatting import format_bytes, format_duration, format_percent
from app.main import create_app
from app.sessions_policy import (
    AGENT_START_KINDS,
    AGENT_START_SUBPROCESS_TIMEOUT,
    agent_start_argv,
    display_argv,
    workspace_create_argv,
)
from app.settings import load_settings

SECRET = "chat-secret-token-value"
_CLOSED = frozenset({"close", "stop", "delete"})


class _Result:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _created_stdout() -> str:
    return json.dumps(
        {
            "result": {
                "workspace": {"workspace_id": "ws1"},
                "tab": {"tab_id": "tab1"},
                "root_pane": {"pane_id": "pane1"},
            }
        }
    )


def _collectors(
    agents=None,
    containers=None,
    host=None,
) -> dict:
    def containers_fn(**kwargs):
        if containers is not None:
            return containers(**kwargs) if callable(containers) else containers
        return {"available": True, "reason": None, "containers": []}

    def agents_fn(**kwargs):
        if agents is not None:
            return agents(**kwargs) if callable(agents) else agents
        return {
            "available": True,
            "reason": None,
            "note": "no agents detected",
            "sources": [],
            "agents": [],
            "workspaces": [],
        }

    def host_fn(**kwargs):
        if host is not None:
            return host(**kwargs) if callable(host) else host
        return {
            "available": True,
            "reason": None,
            "view": "container view",
            "cpu": {"percent": None},
            "memory": {"used_bytes": None, "total_bytes": None, "percent": None},
            "disks": [],
        }

    return {"containers": containers_fn, "agents": agents_fn, "host": host_fn}


def _settings(tmp_path: Path, **env: str):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    values = {
        "DB_PATH": str(tmp_path / "dashboard.db"),
        "CHAT_API_TOKEN": SECRET,
        "CHAT_CWD_ALLOWLIST": str(work),
        "HERDR_SESSION": "hermes",
        "HERDR_BIN": "herdr",
        "HERDR_CONFIG_DIR": str(tmp_path / "herdr-config"),
        "HERDR_TIMEOUT_SECONDS": "3",
    }
    values.update(env)
    return load_settings(values), work


def _app(tmp_path: Path, runner, collectors=None, **env: str):
    settings, work = _settings(tmp_path, **env)
    application = create_app(
        settings=settings,
        collectors=collectors or _collectors(),
        herdr_runner=runner,
    )
    return application, settings, work


def _auth(token: str = SECRET) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _body(work: Path, **extra: str) -> dict[str, str]:
    payload = {"kind": "pi", "cwd": str(work), "label": "demo"}
    payload.update(extra)
    return payload


def _record(calls: list) -> callable:
    def runner(argv, timeout):
        assert isinstance(argv, list)
        assert all(isinstance(part, str) for part in argv)
        calls.append((list(argv), timeout))
        return _Result()

    return runner


def _success(calls: list) -> callable:
    def runner(argv, timeout):
        assert isinstance(argv, list)
        assert all(isinstance(part, str) for part in argv)
        calls.append((list(argv), timeout))
        if len(calls) == 1:
            return _Result(0, _created_stdout(), "")
        return _Result(0, "not-json", "")

    return runner


def _insert_session(path: str, session_id: str, cwd: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        INSERT INTO chat_sessions (
            id, label, agent_kind, herdr_session, cwd, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            "demo",
            "pi",
            "hermes",
            cwd,
            "running",
            "2020-01-01T00:00:00+00:00",
            "2020-01-01T00:00:00+00:00",
        ),
    )
    conn.commit()
    conn.close()


def _snapshots(path: str) -> list[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM herdr_snapshots").fetchall()
    conn.close()
    return [dict(row) for row in rows]


















def test_metrics_and_section_routes_include_human_keys(tmp_path: Path):
    def containers(**kwargs):
        return {
            "available": True,
            "containers": [{"name": "web", "memory_used_bytes": 1048576}],
        }

    def agents(**kwargs):
        return {
            "available": True,
            "agents": [{"label": "pi", "elapsed_seconds": 90}],
            "sources": [],
        }

    def host(**kwargs):
        return {
            "available": True,
            "memory": {"used_bytes": 2048, "total_bytes": 4096, "percent": 50.0},
            "cpu": {"percent": 1.5},
            "disks": [],
        }

    application, _, _work = _app(
        tmp_path,
        _record([]),
        collectors=_collectors(agents=agents, containers=containers, host=host),
    )
    with TestClient(application) as client:
        metrics = client.get("/api/metrics")
        containers_body = client.get("/api/containers")
        agents_body = client.get("/api/agents")
        host_body = client.get("/api/host")
    assert metrics.status_code == 200
    row = metrics.json()["containers"]["containers"][0]
    assert row["memory_used_bytes"] == 1048576
    assert row["memory_used_human"] == format_bytes(1048576)
    assert containers_body.json()["containers"][0]["memory_used_human"] == format_bytes(
        1048576
    )
    assert agents_body.json()["agents"][0]["elapsed_human"] == format_duration(90)
    assert host_body.json()["memory"]["used_human"] == format_bytes(2048)
    assert host_body.json()["cpu"]["percent_human"] == format_percent(1.5)
    assert metrics.json()["host"]["memory"]["used_human"] == format_bytes(2048)


def test_call_agents_receives_herdr_session_and_config_dir(tmp_path: Path):
    seen: list[dict] = []

    def agents(**kwargs):
        seen.append(kwargs)
        return {"available": True, "agents": [], "sources": [], "workspaces": []}

    application, settings, _work = _app(
        tmp_path,
        _record([]),
        collectors=_collectors(agents=agents),
    )
    with TestClient(application) as client:
        assert client.get("/api/agents").status_code == 200
        assert client.get("/api/metrics").status_code == 200
        assert client.get("/").status_code == 200
    assert len(seen) == 3
    for kwargs in seen:
        assert kwargs["herdr_session"] == settings.herdr_session == "hermes"
        assert kwargs["herdr_config_dir"] == settings.herdr_config_dir
        assert kwargs["config_home"] == str(Path.home())




def test_snapshots_use_herdr_rows_not_proc(tmp_path: Path):
    def agents(**kwargs):
        return {
            "available": True,
            "agents": [
                {
                    "source": "herdr",
                    "workspace_id": "ws-h",
                    "workspace_label": "lab",
                    "tab_id": "tab-h",
                    "pane_id": "pane-h",
                    "kind": "pi",
                    "label": "agent-h",
                    "status": "working",
                    "cwd": "/work",
                },
                {
                    "source": "proc",
                    "workspace_id": "ws-p",
                    "pane_id": "pane-p",
                    "status": "working",
                    "kind": "pi",
                    "label": "proc-agent",
                },
            ],
            "workspaces": [
                {"workspace_id": "ws-ignored", "label": "nope", "agent_status": "idle"}
            ],
            "sources": [],
        }

    application, settings, _work = _app(
        tmp_path,
        _record([]),
        collectors=_collectors(agents=agents),
    )
    with TestClient(application) as client:
        assert client.get("/api/metrics").status_code == 200
    rows = _snapshots(settings.db_path)
    assert len(rows) == 1
    assert rows[0]["workspace_id"] == "ws-h"
    assert rows[0]["pane_id"] == "pane-h"
    assert rows[0]["status"] == "working"
    assert rows[0]["herdr_session"] == "hermes"


def test_empty_herdr_agents_snapshot_workspaces(tmp_path: Path):
    def agents(**kwargs):
        return {
            "available": True,
            "agents": [{"source": "proc", "pane_id": "pane-p", "status": "working"}],
            "workspaces": [
                {"workspace_id": "ws-w", "label": "Lab", "agent_status": "idle"}
            ],
            "sources": [],
        }

    application, settings, _work = _app(
        tmp_path,
        _record([]),
        collectors=_collectors(agents=agents),
    )
    with TestClient(application) as client:
        assert client.get("/api/metrics").status_code == 200
    rows = _snapshots(settings.db_path)
    assert len(rows) == 1
    assert rows[0]["workspace_id"] == "ws-w"
    assert rows[0]["workspace_label"] == "Lab"
    assert rows[0]["pane_id"] == ""
    assert rows[0]["tab_id"] == ""
    assert rows[0]["status"] == "idle"


def test_chat_token_absent_from_html_and_json(tmp_path: Path):
    application, _, work = _app(tmp_path, _success([]))
    with TestClient(application) as client:
        page = client.get("/")
        metrics = client.get("/api/metrics")
    assert page.status_code == 200
    assert SECRET not in page.text
    assert SECRET not in metrics.text
    assert "chat_api_token" not in metrics.text
    assert "chat_api_token" not in page.text


def test_main_source_spawns_with_list_argv_only():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "os.system" not in source
    tree = ast.parse(source)
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        ):
            continue
        found = True
        assert node.args, "subprocess call missing argv"
        first = node.args[0]
        assert isinstance(first, ast.Name)
        assert _name_resolves_to_list(tree, node, first.id)
        keywords = {item.arg for item in node.keywords}
        assert "shell" not in keywords
    assert found


def _name_resolves_to_list(tree: ast.AST, call: ast.Call, name: str) -> bool:
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(child is call for child in ast.walk(fn)):
            continue
        for arg in fn.args.args:
            if arg.arg == name and _annotation_is_list(arg.annotation):
                return True
        for stmt in ast.walk(fn):
            if (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.target.id == name
                and _annotation_is_list(stmt.annotation)
            ):
                return True
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id == name
                        and isinstance(stmt.value, (ast.List, ast.ListComp))
                    ):
                        return True
    return False


def _annotation_is_list(node: ast.AST | None) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "list"
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        return node.value.id == "list"
    return False
