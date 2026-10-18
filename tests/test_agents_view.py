"""Render agent partials with Jinja2. Does not import app.main."""

import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"
PARTIALS = ("agents_desktop.html", "agents_mobile.html")

ENV = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(["html"]),
)


def _agents():
    return {
        "available": True,
        "reason": None,
        "note": "",
        "herdr": {
            "reachable": False,
            "version": None,
            "session": None,
            "reason": "herdr config not mounted",
            "workspace_count": 1,
            "tab_count": 1,
            "agent_count": 2,
        },
        "agents": [
            {
                "source": "herdr",
                "kind": "pi",
                "agent": "pi",
                "workspace_label": "lab",
                "tab_label": "tab-a",
                "status": "working",
                "cwd": "/work",
                "elapsed_seconds": 90,
                "elapsed_human": "1m 30s",
                "elapsed_source": "herdr",
            },
            {
                "source": "proc",
                "kind": "claude",
                "workspace_label": "",
                "tab_label": "",
                "status": "running",
                "cwd": "/tmp",
                "elapsed_seconds": 5,
                "elapsed_human": "5s",
                "elapsed_source": "proc",
                "cpu_percent_human": "1.0%",
                "rss_human": "12.0 MiB",
            },
            {
                "source": "herdr",
                "kind": "codex",
                "workspace_label": "",
                "tab_label": "tab-b",
                "status": "idle",
                "cwd": "/other",
                "elapsed_seconds": None,
                "elapsed_source": "herdr",
            },
        ],
    }


def render(name, agents):
    return ENV.get_template(f"partials/{name}").render(agents=agents)


def _panel(html, panel_id):
    start = html.index(f'id="{panel_id}"')
    start = html.rindex("<section", 0, start)
    end = html.index("</section>", start) + len("</section>")
    return html[start:end]


def _between(html, start_id, end_id):
    start = html.index(f'id="{start_id}"')
    end = html.index(f'id="{end_id}"')
    return html[start:end]


def _articles(html):
    return re.findall(r"<article\b[\s\S]*?</article>", html)


@pytest.mark.parametrize("name", PARTIALS)
def test_partial_is_agents_section(name):
    html = render(name, _agents())
    panel = _panel(html, "panel-agents")
    assert panel.startswith("<section")
    assert 'id="panel-agents"' in panel
    assert panel.index('id="herdr-block"') < panel.index('id="agents-body"')
    assert panel.count('class="herdr-summary"') == 1
    assert "<p>reachable" not in panel
    assert "<p>version" not in panel


@pytest.mark.parametrize("name", PARTIALS)
def test_herdr_summary_line_counts_and_unavailable_reason(name):
    html = render(name, _agents())
    block = _between(html, "herdr-block", "agents-body")
    assert "reachable false" in block
    assert "version unknown" in block
    assert "session unknown" in block
    assert "workspaces 1" in block
    assert "tabs 1" in block
    assert "agents 2" in block
    assert "herdr config not mounted" in block
    assert "unavailable: herdr config not mounted" in block
    assert block.count("<p") == 3


@pytest.mark.parametrize("name", PARTIALS)
def test_reachable_herdr_keeps_reason_without_unavailable(name):
    agents = _agents()
    agents["herdr"] = {
        "reachable": True,
        "version": "0.9.5",
        "session": "ops",
        "reason": "agents block only",
        "workspace_count": 4,
        "tab_count": 5,
        "agent_count": 6,
    }
    html = render(name, agents)
    block = _between(html, "herdr-block", "agents-body")
    assert "reachable true" in block
    assert "version 0.9.5" in block
    assert "session ops" in block
    assert "workspaces 4" in block
    assert "tabs 5" in block
    assert "agents 6" in block
    assert "agents block only" in block
    assert "unavailable:" not in block


@pytest.mark.parametrize("name", PARTIALS)
def test_group_headings_cards_elapsed_and_proc_fields(name):
    html = render(name, _agents())
    panel = _panel(html, "panel-agents")
    assert "<h3>lab</h3>" in panel
    assert "<h3>proc</h3>" in panel
    assert "<h3>unknown</h3>" in panel
    assert panel.index("<h3>lab</h3>") < panel.index("<h3>proc</h3>") < panel.index("<h3>unknown</h3>")
    articles = _articles(panel)
    assert len(articles) == 3
    lab, proc, unknown = articles
    assert ">tab-a</h3>" in lab
    assert ">working</span>" in lab
    assert ">herdr</span>" in lab
    assert ">pi</span>" in lab
    assert "workspace lab" in lab
    assert "cwd /work" in lab
    assert "elapsed 1m 30s" in lab
    assert "cpu " not in lab
    assert "rss " not in lab
    assert ">claude</h3>" in proc
    assert ">running</span>" in proc
    assert ">proc</span>" in proc
    assert "workspace proc" in proc
    assert "cwd /tmp" in proc
    assert "cpu 1.0%" in proc
    assert "rss 12.0 MiB" in proc
    assert "elapsed" not in proc
    assert "5s" not in proc
    assert "elapsed_seconds" not in proc
    assert ">tab-b</h3>" in unknown
    assert ">idle</span>" in unknown
    assert ">codex</span>" in unknown
    assert "workspace unknown" in unknown
    assert "cwd /other" in unknown
    assert "elapsed unknown" in unknown
    assert "5s" not in panel
    assert "elapsed_seconds" not in panel


@pytest.mark.parametrize("name", PARTIALS)
def test_title_falls_back_to_kind_then_agent(name):
    agents = {
        "herdr": {"reachable": True, "workspace_count": 0, "tab_count": 0, "agent_count": 1},
        "agents": [
            {"source": "herdr", "kind": "pi", "tab_label": "", "workspace_label": "lab", "elapsed_source": "herdr"},
            {"source": "herdr", "agent": "opus", "kind": "", "tab_label": "", "workspace_label": "", "elapsed_source": "unknown"},
        ],
    }
    html = render(name, agents)
    assert ">pi</h3>" in html
    assert ">opus</h3>" in html
    assert "<h3>unknown</h3>" in html


@pytest.mark.parametrize("name", PARTIALS)
def test_empty_list_and_note_show_no_agents_detected(name):
    empty = render(name, {"herdr": {"reachable": False}, "agents": [], "note": ""})
    assert "No agents detected." in empty
    assert "<h3>" not in _panel(empty, "panel-agents").split('id="agents-body"', 1)[1]
    noted = render(
        name,
        {
            "herdr": {"reachable": True},
            "note": "no agents detected",
            "agents": [{"source": "proc", "kind": "claude", "elapsed_seconds": 5, "elapsed_human": "5s"}],
        },
    )
    body = noted.split('id="agents-body"', 1)[1]
    assert "No agents detected." in body
    assert "5s" not in body
    assert "<article" not in body


def test_static_agents_view_has_no_inner_html_or_urls():
    script = (ROOT / "app" / "static" / "agents_view.js").read_text(encoding="utf-8")
    style = (ROOT / "app" / "static" / "agents.css").read_text(encoding="utf-8")
    for source in (script, style):
        assert "innerHTML" not in source
        assert "http://" not in source
        assert "https://" not in source
    assert "globalThis.renderHerdrBlock" in script
    assert "globalThis.renderAgentsBody" in script
    assert "createElement" in script
    assert "textContent" in script
    assert "elapsed_seconds" not in script
    for color in ("#0f1419", "#e7ecf1", "#1a2332", "#3dd68c", "#e6b35a", "#f07178"):
        assert color in style


def test_partial_sources_do_not_render_elapsed_seconds():
    for name in PARTIALS:
        source = (TEMPLATES / "partials" / name).read_text(encoding="utf-8")
        assert 'id="panel-agents"' in source
        assert 'id="herdr-block"' in source
        assert 'id="agents-body"' in source
        assert "elapsed_seconds" not in source
        assert "innerHTML" not in source
        assert "http://" not in source
        assert "https://" not in source
