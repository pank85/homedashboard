"""Detected-agent page helpers, route, templates, and static assets."""

import re
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent_pages import (  # noqa: E402
    agent_identity,
    agent_is_live,
    agent_key,
    agent_page_data,
    agent_rows_for_key,
    detected_agent_rows,
    matching_sessions,
    primary_agent_row,
    running_signal,
    session_is_running,
)
from app.main import create_app  # noqa: E402

BLOCKED = (
    "Skills, commands, crons, and markdown are not available. "
    "No on-disk source is configured."
)
PARTIALS = ("agents_desktop.html", "agents_mobile.html")
ENV = Environment(
    loader=FileSystemLoader(ROOT / "app" / "templates"),
    autoescape=select_autoescape(["html"]),
)


def _agents_payload():
    return {
        "available": True,
        "reason": None,
        "note": "",
        "herdr": {"reachable": False, "agent_count": 3},
        "agents": [
            {
                "source": "herdr",
                "kind": "pi",
                "label": "pi",
                "workspace_label": "lab",
                "tab_label": "tab-a",
                "status": "working",
                "cwd": "/work",
            },
            {
                "source": "proc",
                "kind": "",
                "label": "claude",
                "workspace_label": "",
                "status": "unknown",
                "cwd": "/tmp",
            },
            {
                "source": "herdr",
                "kind": "Bad Label!",
                "label": "bad",
                "workspace_label": "",
                "status": "idle",
                "cwd": "/other",
            },
        ],
    }


def _sessions_payload():
    return {
        "available": True,
        "sessions": [
            {"label": "one", "agent_kind": "pi", "workspace_id": "ws-1", "status": "running", "cwd": "/work"},
            {"label": "two", "agent_kind": "claude", "workspace_id": "ws-2", "status": "idle", "cwd": "/tmp"},
            {"label": "three", "agent_kind": "Pi", "workspace_id": "ws-3", "status": "running", "cwd": "/work"},
        ],
    }


def _collectors(agents):
    def collect_agents(**kwargs):
        return agents

    return {"agents": collect_agents}


def _insert_session(path, *, agent_kind, status, label, workspace_id, cwd):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        INSERT INTO chat_sessions (
            id, label, agent_kind, herdr_session, workspace_id, cwd, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            label * 32,
            label,
            agent_kind,
            "hermes",
            workspace_id,
            cwd,
            status,
            "2020-01-01T00:00:00+00:00",
            "2020-01-01T00:00:00+00:00",
        ),
    )
    conn.commit()
    conn.close()


def _app(monkeypatch, tmp_path, agents):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "dash.db"))
    monkeypatch.setenv("HERDR_WEB_TOKEN", "super-secret-token")
    monkeypatch.delenv("CHAT_API_TOKEN", raising=False)
    return create_app(collectors=_collectors(agents))


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_agent_key_accepts_only_lowercase_letter_digit_dash():
    assert agent_key("pi") == "pi"
    assert agent_key("Claude") == "claude"
    assert agent_key("a") == "a"
    assert agent_key("a" * 32) == "a" * 32
    assert agent_key("a-b9") == "a-b9"
    assert agent_key("a" * 33) == ""
    assert agent_key("9abc") == ""
    assert agent_key("-abc") == ""
    assert agent_key("ab_c") == ""
    assert agent_key("has space") == ""
    assert agent_key("") == ""
    assert agent_key(None) == ""


def test_agent_identity_prefers_kind_then_label():
    assert agent_identity({"kind": "pi", "label": "x"}) == "pi"
    assert agent_identity({"kind": "", "label": "claude"}) == "claude"
    assert agent_identity({"kind": None, "label": "claude"}) == "claude"
    assert agent_identity({"kind": "  ", "label": "claude"}) == "claude"
    assert agent_identity({"kind": "", "label": ""}) == ""
    assert agent_identity({}) == ""
    assert agent_identity(None) == ""


def test_detected_agent_rows_filters_invalid_identities():
    rows = detected_agent_rows(_agents_payload())
    keys = [agent_key(agent_identity(row)) for row in rows]
    assert keys == ["pi", "claude"]
    assert agent_key(agent_identity(rows[1])) == "claude"


def test_agent_rows_for_key_groups_rows_and_unknown_is_empty():
    payload = _agents_payload()
    assert len(agent_rows_for_key(payload, "pi")) == 1
    assert agent_rows_for_key(payload, "PI") == agent_rows_for_key(payload, "pi")
    assert agent_rows_for_key(payload, "nope") == []
    assert agent_rows_for_key(payload, "9bad") == []


def test_primary_agent_row_prefers_herdr_then_first():
    payload = _agents_payload()
    rows = agent_rows_for_key(payload, "pi")
    assert primary_agent_row(rows)["source"] == "herdr"
    proc_only = agent_rows_for_key(payload, "claude")
    assert primary_agent_row(proc_only)["source"] == "proc"
    assert primary_agent_row([]) == {}


def test_running_signal_session_beats_agent():
    rows = agent_rows_for_key(_agents_payload(), "pi")
    sessions = matching_sessions(_sessions_payload(), "pi")
    assert running_signal(rows, sessions) == "session"
    assert running_signal(rows, []) == "agent"
    assert running_signal(agent_rows_for_key(_agents_payload(), "claude"), []) == "agent"
    assert running_signal([], []) is None
    assert session_is_running({"status": "running"}) is True
    assert agent_is_live({"status": "working", "source": "herdr"}) is True
    assert agent_is_live({"status": "unknown", "source": "proc"}) is True
    assert agent_is_live({"status": "idle", "source": "herdr"}) is False


def test_matching_sessions_matches_agent_kind_case_insensitively():
    sessions = matching_sessions(_sessions_payload(), "pi")
    assert [row["label"] for row in sessions] == ["one", "three"]
    assert matching_sessions(_sessions_payload(), "claude")[0]["label"] == "two"
    assert matching_sessions(_sessions_payload(), "nope") == []


def test_agent_page_data_none_for_unknown_or_invalid_key():
    assert agent_page_data(_agents_payload(), _sessions_payload(), "nope") is None
    assert agent_page_data(_agents_payload(), _sessions_payload(), "9bad") is None
    assert agent_page_data(None, None, "pi") is None


def test_agent_page_data_returns_status_cwd_source_and_chats():
    data = agent_page_data(_agents_payload(), _sessions_payload(), "pi")
    assert data["key"] == "pi"
    assert data["title"] == "pi"
    assert data["status"] == "working"
    assert data["cwd"] == "/work"
    assert data["source"] == "herdr"
    assert data["running"] == "session"
    assert [row["label"] for row in data["sessions"]] == ["one", "three"]


def test_agent_pages_module_does_not_import_settings_or_collectors():
    source = (ROOT / "app" / "agent_pages.py").read_text(encoding="utf-8")
    assert "app.settings" not in source
    assert "app.collectors" not in source
    assert "from app" not in source


# ---------------------------------------------------------------------------
# Partials
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", PARTIALS)
def test_agent_cards_link_valid_identities_only(name):
    agents = _agents_payload()
    html = ENV.get_template(f"partials/{name}").render(agents=agents)
    assert 'href="/agents/pi"' in html
    assert 'href="/agents/claude"' in html
    assert "agent-card-link" in html
    assert 'href="/agents/bad' not in html
    assert "http://" not in html
    assert "https://" not in html
    assert "innerHTML" not in html


@pytest.mark.parametrize("name", PARTIALS)
def test_agent_card_link_keeps_existing_card_fields(name):
    html = ENV.get_template(f"partials/{name}").render(agents=_agents_payload())
    articles = re.findall(r"<article\b[\s\S]*?</article>", html)
    assert len(articles) == 3
    assert ">tab-a</h3>" in articles[0]
    assert ">working</span>" in articles[0]
    assert 'href="/agents/pi"' in articles[0]


def test_agent_page_template_has_blocked_sentence_and_back_link():
    source = (ROOT / "app" / "templates" / "agent.html").read_text(encoding="utf-8")
    assert BLOCKED in source
    assert 'href="/#agents"' in source
    assert "http://" not in source
    assert "https://" not in source
    assert "innerHTML" not in source


def test_agent_page_loads_tabler_css_before_page_styles(monkeypatch, tmp_path):
    source = (ROOT / "app" / "templates" / "agent.html").read_text(encoding="utf-8")
    tabler = source.index('href="/static/tabler.css"')
    assert tabler < source.index('href="/static/style.css"')
    assert source.index('href="/static/style.css"') < source.index('href="/static/agents.css"')
    assert source.index('href="/static/agents.css"') < source.index('href="/static/agent_page.css"')

    application = _app(monkeypatch, tmp_path, _agents_payload())
    with TestClient(application) as client:
        found = client.get("/agents/pi")
        missing = client.get("/agents/nope")
    assert found.status_code == 200
    assert missing.status_code == 404
    for page in (found, missing):
        assert 'href="/static/tabler.css"' in page.text


def test_agent_page_js_and_css_are_clean():
    script = (ROOT / "app" / "static" / "agent_page.js").read_text(encoding="utf-8")
    style = (ROOT / "app" / "static" / "agent_page.css").read_text(encoding="utf-8")
    for source in (script, style):
        assert "innerHTML" not in source
        assert "http://" not in source
        assert "https://" not in source
    assert "createElement" in script
    assert "textContent" in script


def test_agents_view_js_builds_agent_route_links():
    script = (ROOT / "app" / "static" / "agents_view.js").read_text(encoding="utf-8")
    assert '"/agents/" + key' in script
    assert "setAttribute" in script


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def test_agent_route_200_for_detected_key(monkeypatch, tmp_path):
    application = _app(monkeypatch, tmp_path, _agents_payload())
    with TestClient(application) as client:
        page = client.get("/agents/pi")
    assert page.status_code == 200
    assert "Traceback" not in page.text
    assert "undefined" not in page.text
    assert BLOCKED in page.text
    assert 'href="/#agents"' in page.text
    assert ">working</span>" in page.text
    assert "cwd /work" in page.text
    assert ">herdr</span>" in page.text
    assert 'data-agent-key="pi"' in page.text


def test_agent_route_uppercase_key_matches_lowercased_identity(monkeypatch, tmp_path):
    application = _app(monkeypatch, tmp_path, _agents_payload())
    with TestClient(application) as client:
        page = client.get("/agents/PI")
    assert page.status_code == 200
    assert 'data-agent-key="pi"' in page.text


def test_agent_route_404_for_unknown_key(monkeypatch, tmp_path):
    application = _app(monkeypatch, tmp_path, _agents_payload())
    with TestClient(application) as client:
        page = client.get("/agents/nope")
    assert page.status_code == 404
    assert BLOCKED not in page.text


def test_agent_route_404_for_invalid_identity_key(monkeypatch, tmp_path):
    application = _app(monkeypatch, tmp_path, _agents_payload())
    with TestClient(application) as client:
        page = client.get("/agents/Bad%20Label%21")
    assert page.status_code == 404


def test_agent_route_shows_only_matching_chat_rows(monkeypatch, tmp_path):
    application = _app(monkeypatch, tmp_path, _agents_payload())
    with TestClient(application) as client:
        page = client.get("/agents/pi")
    assert page.status_code == 200
    assert 'id="agent-chats"' not in page.text
    assert "Skills, commands, crons, and markdown are not available. No on-disk source is configured." in page.text


def test_agent_route_page_has_no_file_writing_form(monkeypatch, tmp_path):
    application = _app(monkeypatch, tmp_path, _agents_payload())
    with TestClient(application) as client:
        page = client.get("/agents/pi")
    assert page.status_code == 200
    assert "<form" not in page.text
    assert "new-session-form" not in page.text
    assert "textarea" not in page.text
