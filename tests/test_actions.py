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


def test_unset_token_forbids_both_mutations(tmp_path: Path):
    calls: list = []
    application, _, work = _app(tmp_path, _record(calls), CHAT_API_TOKEN="")
    with TestClient(application) as client:
        created = client.post("/api/sessions", headers=_auth(), json=_body(work))
        archived = client.post(
            f"/api/sessions/{'a' * 32}/archive",
            headers=_auth(),
            json={"token": SECRET},
        )
        listed = client.get("/api/sessions")
    assert created.status_code == 403
    assert created.json() == {"error": "forbidden", "reason": "CHAT_API_TOKEN unset"}
    assert archived.status_code == 403
    assert archived.json() == created.json()
    assert calls == []
    assert listed.status_code == 200
    assert listed.json()["mutations_enabled"] is False
    assert listed.json()["available"] is True
    assert listed.json()["kinds"] == list(AGENT_START_KINDS)
    assert SECRET not in created.text
    assert SECRET not in archived.text


def test_wrong_or_missing_token_is_401_and_runner_not_called(tmp_path: Path):
    calls: list = []
    application, _, work = _app(tmp_path, _record(calls))
    with TestClient(application) as client:
        wrong = client.post("/api/sessions", headers=_auth("nope"), json=_body(work))
        missing = client.post("/api/sessions", json=_body(work))
        query = client.post(f"/api/sessions?token={SECRET}", json=_body(work))
        basic = client.post(
            "/api/sessions",
            headers={"Authorization": f"Basic {SECRET}"},
            json={"token": SECRET, **_body(work)},
        )
    expected = {"error": "unauthorized", "reason": "invalid token"}
    assert wrong.status_code == 401
    assert missing.status_code == 401
    assert query.status_code == 401
    assert basic.status_code == 401
    assert wrong.json() == expected
    assert missing.json() == expected
    assert query.json() == expected
    assert basic.json() == expected
    assert calls == []
    assert SECRET not in wrong.text


@pytest.mark.parametrize("via", ["header", "json"])
def test_create_lists_session_on_sessions_and_metrics(tmp_path: Path, via: str):
    calls: list = []
    application, settings, work = _app(tmp_path, _success(calls))
    expected_cwd = str(work.resolve())
    payload = _body(work)
    headers: dict[str, str] = {}
    if via == "header":
        headers = _auth()
    else:
        payload = {**payload, "token": SECRET}
    with TestClient(application) as client:
        created = client.post("/api/sessions", headers=headers, json=payload)
        listed = client.get("/api/sessions")
        metrics = client.get("/api/metrics")
        page = client.get("/")
    assert created.status_code == 201
    session = created.json()["session"]
    assert set(created.json()) == {"session"}
    assert session["status"] == "running"
    assert session["workspace_id"] == "ws1"
    assert session["tab_id"] == "tab1"
    assert session["pane_id"] == "pane1"
    assert session["agent_name"] == "demo"
    assert session["cwd"] == expected_cwd
    assert session["attach_command"] == "herdr session attach hermes"
    assert session["herdr_href"] == "/herdr/"
    assert "token" not in session
    assert calls == [
        (
            workspace_create_argv(settings.herdr_bin, "hermes", expected_cwd, "demo"),
            settings.herdr_timeout_seconds,
        ),
        (
            agent_start_argv(settings.herdr_bin, "hermes", "demo", "pi", "pane1"),
            AGENT_START_SUBPROCESS_TIMEOUT,
        ),
    ]
    assert all(isinstance(argv, list) for argv, _timeout in calls)
    session_id = session["id"]
    listed_row = next(row for row in listed.json()["sessions"] if row["id"] == session_id)
    metrics_row = next(
        row for row in metrics.json()["sessions"]["sessions"] if row["id"] == session_id
    )
    assert listed_row["created_relative"]
    assert metrics_row["created_relative"]
    assert listed.json()["mutations_enabled"] is True
    assert page.status_code == 200
    assert SECRET not in created.text
    assert SECRET not in listed.text
    assert SECRET not in metrics.text
    assert SECRET not in page.text


def test_create_stores_human_label_and_starts_slug_agent_name(tmp_path: Path):
    calls: list = []
    application, settings, work = _app(tmp_path, _success(calls))
    label = "Hermes Probe \u30bb\u30c3\u30b7\u30e7\u30f3"
    expected_cwd = str(work.resolve())
    with TestClient(application) as client:
        created = client.post(
            "/api/sessions",
            headers=_auth(),
            json=_body(work, kind="hermes", label=label),
        )
    assert created.status_code == 201
    session = created.json()["session"]
    assert session["label"] == label
    assert calls[0] == (
        workspace_create_argv(settings.herdr_bin, "hermes", expected_cwd, label),
        settings.herdr_timeout_seconds,
    )
    start_argv, start_timeout = calls[1]
    agent_name = start_argv[5]
    assert start_timeout == AGENT_START_SUBPROCESS_TIMEOUT
    assert re.fullmatch(r"[a-z][a-z0-9-]{0,31}", agent_name)
    assert agent_name != label
    assert session["agent_name"] == agent_name
    assert start_argv == agent_start_argv(
        settings.herdr_bin,
        "hermes",
        agent_name,
        "hermes",
        "pane1",
    )
    conn = sqlite3.connect(settings.db_path)
    stored = conn.execute("SELECT label, agent_name FROM chat_sessions").fetchone()
    conn.close()
    assert stored == (label, agent_name)


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda body, work: body.__setitem__("kind", "nope"), "unknown agent kind"),
        (lambda body, work: body.__setitem__("label", "bad;label"), "invalid label"),
        (
            lambda body, work: body.__setitem__("cwd", str(work.parent / "outside")),
            "cwd outside allowlist",
        ),
        (lambda body, work: body.pop("cwd"), "cwd must be absolute"),
        (
            lambda body, work: body.__setitem__("cwd", str(work / ".." / "outside")),
            "cwd outside allowlist",
        ),
    ],
)
def test_invalid_session_input_is_400_and_runner_not_called(
    tmp_path: Path,
    mutate,
    reason: str,
):
    (tmp_path / "outside").mkdir()
    calls: list = []
    application, _, work = _app(tmp_path, _record(calls))
    body = _body(work)
    mutate(body, work)
    with TestClient(application) as client:
        response = client.post("/api/sessions", headers=_auth(), json=body)
    assert response.status_code == 400
    assert response.json() == {"error": "invalid", "reason": reason}
    assert calls == []


def test_form_token_is_accepted(tmp_path: Path):
    calls: list = []
    application, settings, work = _app(tmp_path, _success(calls))
    expected_cwd = str(work.resolve())
    with TestClient(application) as client:
        created = client.post(
            "/api/sessions",
            data={"token": SECRET, "kind": "pi", "cwd": str(work), "label": "demo"},
        )
    assert created.status_code == 201
    assert calls[0][0] == workspace_create_argv(
        settings.herdr_bin,
        "hermes",
        expected_cwd,
        "demo",
    )
    assert len(calls) == 2
    assert SECRET not in created.text


def test_default_herdr_session_is_refused(tmp_path: Path):
    calls: list = []
    application, _, work = _app(tmp_path, _record(calls), HERDR_SESSION="default")
    with TestClient(application) as client:
        response = client.post("/api/sessions", headers=_auth(), json=_body(work))
    assert response.status_code == 400
    assert response.json() == {"error": "invalid", "reason": "refusing session default"}
    assert calls == []


def test_unwritable_db_is_503_and_runner_not_called(tmp_path: Path):
    parent = tmp_path / "not-a-dir"
    parent.write_text("x")
    target = str(parent / "dashboard.db")
    calls: list = []
    application, _, work = _app(tmp_path, _record(calls), DB_PATH=target)
    with TestClient(application) as client:
        created = client.post("/api/sessions", headers=_auth(), json=_body(work))
        archived = client.post(
            f"/api/sessions/{'a' * 32}/archive",
            headers=_auth(),
        )
        page = client.get("/")
        metrics = client.get("/api/metrics")
    assert created.status_code == 503
    assert created.json() == {
        "error": "unavailable",
        "reason": f"db path not writable: {target}",
    }
    assert archived.status_code == 503
    assert archived.json()["error"] == "unavailable"
    assert calls == []
    assert page.status_code == 200
    assert metrics.status_code == 200
    sessions = metrics.json()["sessions"]
    assert sessions["available"] is False
    assert sessions["sessions"] == []
    assert sessions["mutations_enabled"] is True
    assert SECRET not in page.text
    assert SECRET not in metrics.text
    assert SECRET not in created.text


def test_runner_failure_marks_failed_and_does_not_close(tmp_path: Path):
    calls: list = []

    def runner(argv, timeout):
        assert isinstance(argv, list)
        calls.append(list(argv))
        if len(calls) == 1:
            return _Result(0, _created_stdout(), "")
        return _Result(3, "", "start failed")

    application, _, work = _app(tmp_path, runner)
    with TestClient(application) as client:
        response = client.post("/api/sessions", headers=_auth(), json=_body(work))
        listed = client.get("/api/sessions")
    assert response.status_code == 502
    body = response.json()
    assert body["error"] == "herdr"
    assert body["session"]["status"] == "failed"
    assert body["session"]["pane_id"] == "pane1"
    assert body["reason"] == f"{display_argv(calls[1])}: start failed"
    assert body["session"]["last_error"] == body["reason"]
    assert SECRET not in response.text
    assert len(calls) == 2
    for argv in calls:
        assert _CLOSED.isdisjoint(argv)
    assert listed.json()["sessions"][0]["status"] == "failed"


def test_create_failure_does_not_start_or_close(tmp_path: Path):
    calls: list = []

    def runner(argv, timeout):
        calls.append(list(argv))
        raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout)

    application, _, work = _app(tmp_path, runner)
    with TestClient(application) as client:
        response = client.post("/api/sessions", headers=_auth(), json=_body(work))
    assert response.status_code == 502
    assert response.json()["session"]["status"] == "failed"
    assert "herdr timed out" in response.json()["reason"]
    assert len(calls) == 1
    assert _CLOSED.isdisjoint(calls[0])
    assert SECRET not in response.text


def test_last_error_redacts_token_and_truncates(tmp_path: Path):
    calls: list = []

    def runner(argv, timeout):
        calls.append(list(argv))
        return _Result(1, "", SECRET + ("y" * 700))

    application, _, work = _app(tmp_path, runner)
    with TestClient(application) as client:
        response = client.post("/api/sessions", headers=_auth(), json=_body(work))
    reason = response.json()["reason"]
    assert response.status_code == 502
    assert SECRET not in reason
    assert SECRET not in response.text
    assert "[redacted]" in reason
    assert len(reason) == 500
    assert _CLOSED.isdisjoint(calls[0])


def test_archive_is_db_only_and_missing_is_404(tmp_path: Path):
    calls: list = []
    application, settings, work = _app(tmp_path, _record(calls))
    session_id = "ab" * 16
    _insert_session(settings.db_path, session_id, str(work))
    with TestClient(application) as client:
        archived = client.post(
            f"/api/sessions/{session_id}/archive",
            headers=_auth(),
        )
        listed = client.get("/api/sessions")
        missing = client.post(
            f"/api/sessions/{'c' * 32}/archive",
            headers=_auth(),
        )
        invalid = client.post("/api/sessions/not-an-id/archive", headers=_auth())
        deleted = client.delete(f"/api/sessions/{session_id}")
        still = client.get("/api/sessions")
    assert archived.status_code == 200
    assert archived.json()["session"]["status"] == "archived"
    assert archived.json()["session"]["id"] == session_id
    assert calls == []
    assert any(
        row["id"] == session_id and row["status"] == "archived"
        for row in listed.json()["sessions"]
    )
    assert missing.status_code == 404
    assert missing.json() == {"error": "not_found", "reason": "session not found"}
    assert invalid.status_code == 400
    assert invalid.json()["reason"] == "invalid session id"
    assert deleted.status_code == 404
    assert any(
        row["id"] == session_id and row["status"] == "archived"
        for row in still.json()["sessions"]
    )
    assert SECRET not in archived.text


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


def test_poll_maps_herdr_status_and_miss_does_not_fail(tmp_path: Path):
    state = {
        "agents": [
            {
                "source": "herdr",
                "pane_id": "pane1",
                "status": "idle",
                "workspace_id": "ws1",
            }
        ]
    }

    def agents(**kwargs):
        return {
            "available": True,
            "agents": list(state["agents"]),
            "workspaces": [],
            "sources": [],
        }

    calls: list = []
    application, _settings_obj, work = _app(
        tmp_path,
        _success(calls),
        collectors=_collectors(agents=agents),
    )
    with TestClient(application) as client:
        created = client.post("/api/sessions", headers=_auth(), json=_body(work))
        assert created.status_code == 201
        session_id = created.json()["session"]["id"]
        assert client.get("/api/metrics").status_code == 200
        idle = client.get("/api/sessions").json()["sessions"][0]
        assert idle["id"] == session_id
        assert idle["status"] == "idle"
        state["agents"] = []
        assert client.get("/api/metrics").status_code == 200
        missed = client.get("/api/sessions").json()["sessions"][0]
        assert missed["status"] == "idle"
        state["agents"] = [{"source": "herdr", "pane_id": "pane1", "status": "working"}]
        assert client.get("/api/metrics").status_code == 200
        running = client.get("/api/sessions").json()["sessions"][0]
        assert running["status"] == "running"
        state["agents"] = [{"source": "herdr", "pane_id": "pane1", "status": "weird"}]
        assert client.get("/api/metrics").status_code == 200
        unchanged = client.get("/api/sessions").json()["sessions"][0]
        assert unchanged["status"] == "running"


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
        sessions = client.get("/api/sessions")
        created = client.post("/api/sessions", headers=_auth(), json=_body(work))
    assert page.status_code == 200
    assert SECRET not in page.text
    assert SECRET not in metrics.text
    assert SECRET not in sessions.text
    assert SECRET not in created.text
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
