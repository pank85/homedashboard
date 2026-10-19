"""Render the host partial and check the host view script contract.

Jinja and node only. Does not import app.main, app.present, or any collector.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"
VIEW_JS = ROOT / "app" / "static" / "host_view.js"

CPU_LINE = "CPU 12.5% · 8 cores · load 1.3 · 0.5 · 0.1"
RAM_LINE = "RAM 2.0 GiB / 8.0 GiB · 25.0%"
DISK_LINE = "disk /host · 50.0% · 1.0 GiB / 2.0 GiB"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html", "xml"]),
    )


def _render(host: dict, containers: dict, agents: dict) -> str:
    return _env().get_template("partials/host.html").render(
        host=host, containers=containers, agents=agents
    )


def _host(available: bool = True, reason: str | None = None) -> dict:
    return {
        "available": available,
        "reason": reason,
        "view": "host view",
        "cpu": {
            "available": True,
            "percent": 12.5,
            "percent_human": "12.5%",
            "cores": 8,
            "loadavg": [1.25, 0.5, 0.1],
            "loadavg_human": "1.3 · 0.5 · 0.1",
            "per_core": [{"id": "cpu0", "percent": 10.0}],
            "level": "ok",
        },
        "memory": {
            "available": True,
            "used_bytes": 2147483648,
            "used_human": "2.0 GiB",
            "total_bytes": 8589934592,
            "total_human": "8.0 GiB",
            "percent": 25.0,
            "percent_human": "25.0%",
            "level": "ok",
        },
        "disks": [
            {
                "available": True,
                "path": "/host",
                "percent": 50.0,
                "percent_human": "50.0%",
                "used_bytes": 1073741824,
                "used_human": "1.0 GiB",
                "total_bytes": 2147483648,
                "total_human": "2.0 GiB",
                "level": "ok",
            }
        ],
    }


def _containers(available: bool = True) -> dict:
    return {
        "available": available,
        "reason": "" if available else "docker socket not reachable",
        "containers": [
            {"state": "running"},
            {"state": "running"},
            {"state": "exited"},
            {"state": "paused"},
        ],
    }


def _agents() -> dict:
    return {
        "available": True,
        "agents": [
            {"kind": "claude", "label": "x", "status": "working", "source": "herdr"},
            {"kind": "claude", "label": "x", "status": "idle", "source": "herdr"},
            {"kind": "", "label": "node", "status": "unknown", "source": "proc"},
            {"kind": "codex", "label": "y", "status": "blocked", "source": "herdr"},
        ],
    }


def test_server_host_lines_use_human_strings() -> None:
    html = _render(_host(), _containers(), _agents())
    assert CPU_LINE in html
    assert RAM_LINE in html
    assert DISK_LINE in html
    assert 'id="panel-host"' in html
    assert 'id="host-body"' in html


def test_server_host_hides_raw_digits_and_per_core() -> None:
    html = _render(_host(), _containers(), _agents())
    for raw in ("used_bytes", "total_bytes", "per_core", "cpu0"):
        assert raw not in html
    for raw in ("2147483648", "8589934592", "1073741824", "2147483648"):
        assert raw not in html
    # Human keys are rendered, not the raw float/int fields.
    assert "12.5%" in html
    assert "1.3 · 0.5 · 0.1" in html
    assert "2.0 GiB" in html


def test_server_host_unavailable_keeps_reasons() -> None:
    host = _host(available=False, reason="proc not readable: /proc")
    host["cpu"]["available"] = False
    host["cpu"]["reason"] = "proc stat not readable: /proc/stat"
    host["memory"]["available"] = False
    host["memory"]["reason"] = "proc meminfo not readable: /proc/meminfo"
    host["disks"] = [{"available": False, "path": "/host", "reason": "statvfs failed"}]
    html = _render(host, _containers(available=False), _agents())
    assert "unavailable: proc not readable: /proc" in html
    assert "unavailable: proc stat not readable: /proc/stat" in html
    assert "unavailable: proc meminfo not readable: /proc/meminfo" in html
    assert "unavailable: statvfs failed" in html
    assert CPU_LINE not in html
    assert RAM_LINE not in html


def test_server_summary_container_sentence() -> None:
    html = _render(_host(), _containers(), _agents())
    assert 'id="host-summary"' in html
    assert "2 running containers" in html
    unavailable = _render(_host(), _containers(available=False), _agents())
    assert "containers unavailable" in unavailable


def test_server_summary_agent_identity_and_running() -> None:
    html = _render(_host(), _containers(), _agents())
    assert "3 CLI AI agents / 2 running" in html


def test_server_summary_agent_empty_and_missing() -> None:
    empty = _render(_host(), _containers(), {"agents": []})
    assert "0 CLI AI agents / 0 running" in empty
    missing = _render(_host(), _containers(), {})
    assert "agents unavailable" in missing
    not_list = _render(_host(), _containers(), {"agents": {"herdr": 4}})
    assert "agents unavailable" in not_list


def test_host_view_js_contract() -> None:
    source = VIEW_JS.read_text(encoding="utf-8")
    assert "globalThis.renderHostView = function (hostBody, host, containers, agents)" in source
    assert "createElement" in source
    assert "textContent" in source
    assert "removeChild" in source
    for forbidden in ("innerHTML", "http://", "https://", "fetch(", "used_bytes", "total_bytes", "per_core"):
        assert forbidden not in source


_VIEW_HARNESS = r"""
const fs = require("fs");
function TextNode(text) {
  this.nodeType = 3;
  this.textContent = String(text);
  this.childNodes = [];
}
function Element(tag) {
  this.nodeType = 1;
  this.tagName = String(tag).toUpperCase();
  this.childNodes = [];
  this.className = "";
  this.id = "";
  this.style = {};
  this.attributes = {};
}
Object.defineProperty(Element.prototype, "textContent", {
  get() {
    return this.childNodes.map((child) => child.textContent || "").join("");
  },
  set(value) {
    this.childNodes = [new TextNode(value)];
  },
});
Object.defineProperty(Element.prototype, "firstChild", {
  get() {
    return this.childNodes[0] || null;
  },
});
Element.prototype.appendChild = function (child) {
  this.childNodes.push(child);
  return child;
};
Element.prototype.removeChild = function (child) {
  const index = this.childNodes.indexOf(child);
  if (index >= 0) this.childNodes.splice(index, 1);
  return child;
};
Element.prototype.setAttribute = function (name, value) {
  this.attributes[name] = String(value);
};
function serialize(node) {
  if (node.nodeType === 3) return node.textContent;
  const tag = node.tagName.toLowerCase();
  let attrs = "";
  if (node.id) attrs += ` id="${node.id}"`;
  if (node.className) attrs += ` class="${node.className}"`;
  return `<${tag}${attrs}>${node.childNodes.map(serialize).join("")}</${tag}>`;
}
function collectClass(node, className, out) {
  if (node.nodeType === 1 && node.className && String(node.className).split(/\s+/).includes(className)) {
    out.push(node);
  }
  (node.childNodes || []).forEach((child) => collectClass(child, className, out));
}
globalThis.document = { createElement: (tag) => new Element(tag) };
const source = fs.readFileSync(process.argv[1], "utf8");
eval(source);
const body = globalThis.document.createElement("div");
globalThis.renderHostView(body, HOST, CONTAINERS, AGENTS);
const html = serialize(body);
"""


def _run_view(
    host: dict,
    containers: dict,
    agents: dict,
    trailer: str,
    required: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    prefix = (
        "var HOST = " + json.dumps(host) + ";\n"
        "var CONTAINERS = " + json.dumps(containers) + ";\n"
        "var AGENTS = " + json.dumps(agents) + ";\n"
        "var REQUIRED = " + json.dumps(required or []) + ";\n"
    )
    return subprocess.run(
        ["node", "-e", prefix + _VIEW_HARNESS + trailer, str(VIEW_JS)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_render_host_view_matches_server_strings() -> None:
    host = _host()
    containers = _containers()
    agents = _agents()
    server = _render(host, containers, agents)
    required = [CPU_LINE, RAM_LINE, DISK_LINE, "2 running containers", "3 CLI AI agents / 2 running"]
    for line in required:
        assert line in server

    completed = _run_view(
        host,
        containers,
        agents,
        r"""
for (const text of REQUIRED) {
  if (!html.includes(text)) throw new Error("missing " + text + " in " + html);
}
if (!html.includes('id="host-summary"')) throw new Error("missing host-summary");
for (const text of ["innerHTML", "used_bytes", "total_bytes", "per_core", "cpu0", "2147483648", "1073741824"]) {
  if (html.includes(text)) throw new Error("leaked " + text);
}
console.log("ok");
""",
        required,
    )
    assert completed.returncode == 0, completed.stderr
    assert "ok" in completed.stdout


def test_server_host_uses_tabler_cards_and_meters() -> None:
    html = _render(_host(), _containers(), _agents())
    assert html.startswith(
        '<section id="panel-host" class="card" data-mobile-panel data-section="host" role="tabpanel">'
    )
    assert "hidden" not in html.split(">", 1)[0]
    assert '<h2 class="card-title">Host</h2>' in html
    assert '<div id="host-body" class="card-body">' in html
    assert html.index('<div id="host-body" class="card-body">') < html.index("<p")
    assert 'class="text-secondary">host view</p>' in html
    assert 'class="row-cards"' in html
    assert html.count('class="card card-sm"') == 2
    assert html.count('class="card-status-top level-ok"') == 2
    assert f'<p class="level-ok">{CPU_LINE}</p>' in html
    assert f'<p class="level-ok">{RAM_LINE}</p>' in html
    assert f'aria-label="{CPU_LINE}"' in html
    assert f'aria-label="{RAM_LINE}"' in html
    assert f'aria-label="{DISK_LINE}"' in html
    assert 'role="img"' in html
    assert 'class="progress-bar level-ok" style="width: 12.5%"' in html
    assert 'class="progress-bar level-ok" style="width: 25.0%"' in html
    assert 'class="progress-bar level-ok" style="width: 50.0%"' in html
    assert '<table class="table table-vcenter card-table">' in html
    assert f'<td class="level-ok">{DISK_LINE}</td>' in html
    summary = html.split('id="host-summary">', 1)[1].split("</div>", 1)[0]
    assert summary.count("<p>") == 2
    assert "<article" not in summary
    assert html.count('class="progress"') == 3


def test_server_host_levels_and_disk_order() -> None:
    host = _host()
    host["cpu"]["level"] = "warn"
    host["memory"]["level"] = "crit"
    host["disks"] = [
        {
            "available": True,
            "path": "/a",
            "percent": 10,
            "percent_human": "10.0%",
            "used_human": "1.0 GiB",
            "total_human": "10.0 GiB",
            "level": "ok",
        },
        {"available": False, "path": "/missing", "reason": "statvfs failed"},
        {
            "available": True,
            "path": "/b",
            "percent": 90,
            "percent_human": "90.0%",
            "used_human": "9.0 GiB",
            "total_human": "10.0 GiB",
            "level": "crit",
        },
    ]
    html = _render(host, _containers(), _agents())
    assert 'class="card-status-top level-warn"' in html
    assert 'class="card-status-top level-crit"' in html
    assert 'class="progress-bar level-warn"' in html
    assert 'class="progress-bar level-crit"' in html
    first = html.index("disk /a · 10.0% · 1.0 GiB / 10.0 GiB")
    missing = html.index("unavailable: statvfs failed")
    second = html.index("disk /b · 90.0% · 9.0 GiB / 10.0 GiB")
    assert first < missing < second
    missing_row = html.split("unavailable: statvfs failed", 1)[0].rsplit("<tr>", 1)[1]
    assert "progress" not in missing_row
    assert html.count('class="progress"') == 4


def test_server_host_omits_bars_when_unavailable_or_percent_not_number() -> None:
    host = _host(available=False, reason="proc not readable: /proc")
    host["cpu"]["available"] = False
    host["cpu"]["reason"] = "proc stat not readable: /proc/stat"
    host["memory"]["available"] = False
    host["memory"]["reason"] = "proc meminfo not readable: /proc/meminfo"
    host["disks"] = [{"available": False, "path": "/host", "reason": "statvfs failed"}]
    html = _render(host, _containers(available=False), {})
    assert "progress" not in html
    assert "style=" not in html
    assert "card-status-top" not in html
    assert "unavailable: proc not readable: /proc" in html

    partial = _host()
    partial["cpu"]["percent"] = "12.5"
    partial["memory"]["percent"] = None
    partial["disks"][0]["percent"] = {"nope": True}
    partial["cpu"]["level"] = ""
    partial["memory"]["level"] = None
    partial["disks"][0]["level"] = "nope"
    rendered = _render(partial, _containers(), _agents())
    assert "progress" in rendered
    assert "style=" not in rendered
    assert "card-status-top" not in rendered
    assert "level-" not in rendered
    assert CPU_LINE in rendered
    assert RAM_LINE in rendered
    assert DISK_LINE in rendered


def test_server_host_clamps_numeric_percent() -> None:
    host = _host()
    host["cpu"]["percent"] = 140
    host["memory"]["percent"] = -4
    host["disks"][0]["percent"] = 50
    html = _render(host, _containers(), _agents())
    assert 'style="width: 100%"' in html
    assert 'style="width: 0%"' in html
    assert 'style="width: 50%"' in html
    assert 'style="width: 140%"' not in html
    assert 'style="width: -4%"' not in html
    for raw in ("used_bytes", "total_bytes", "per_core", "cpu0", "2147483648", "1073741824"):
        assert raw not in html


def test_render_host_view_meters_match_sentences() -> None:
    completed = _run_view(
        _host(),
        _containers(),
        _agents(),
        r"""
const tracks = [];
collectClass(body, "progress", tracks);
if (tracks.length !== 3) throw new Error("tracks " + tracks.length);
const expected = [
  ["CPU 12.5% · 8 cores · load 1.3 · 0.5 · 0.1", "12.5%"],
  ["RAM 2.0 GiB / 8.0 GiB · 25.0%", "25%"],
  ["disk /host · 50.0% · 1.0 GiB / 2.0 GiB", "50%"],
];
tracks.forEach((track, index) => {
  if (track.attributes.role !== "img") throw new Error("role " + index);
  if (track.attributes["aria-label"] !== expected[index][0]) {
    throw new Error("label " + track.attributes["aria-label"]);
  }
  const fill = track.childNodes.find((child) => String(child.className || "").includes("progress-bar"));
  if (!fill) throw new Error("missing fill " + index);
  if (fill.style.width !== expected[index][1]) throw new Error("width " + fill.style.width);
  if (!String(fill.className).includes("level-ok")) throw new Error("fill level " + fill.className);
});
const strips = [];
collectClass(body, "card-status-top", strips);
if (strips.length !== 2) throw new Error("strips " + strips.length);
const summary = body.childNodes.find((child) => child.id === "host-summary");
if (!summary || summary.childNodes.length !== 2) throw new Error("summary children");
if (summary.childNodes.some((child) => child.tagName !== "P")) throw new Error("summary not p");
if (body.firstChild.tagName !== "P" || body.firstChild.textContent !== "host view") {
  throw new Error("first child " + body.firstChild.tagName);
}
console.log("ok");
""",
    )
    assert completed.returncode == 0, completed.stderr
    assert "ok" in completed.stdout


def test_render_host_view_skips_bar_without_numeric_percent() -> None:
    unavailable = _host(available=False, reason="proc not readable: /proc")
    unavailable["cpu"]["available"] = False
    unavailable["cpu"]["reason"] = "proc stat not readable: /proc/stat"
    unavailable["memory"]["available"] = False
    unavailable["memory"]["reason"] = "proc meminfo not readable: /proc/meminfo"
    unavailable["disks"] = [{"available": False, "path": "/host", "reason": "statvfs failed"}]
    missing = _run_view(
        unavailable,
        _containers(available=False),
        {},
        r"""
if (html.includes("progress") || html.includes("article")) throw new Error(html);
if (html.includes("card-status-top")) throw new Error("strip");
const fills = [];
collectClass(body, "progress-bar", fills);
if (fills.length !== 0) throw new Error("fills");
console.log("ok");
""",
    )
    assert missing.returncode == 0, missing.stderr

    partial = _host()
    partial["cpu"]["percent"] = "12.5"
    partial["memory"]["percent"] = None
    partial["disks"][0]["percent"] = "50"
    partial["cpu"]["level"] = "warn"
    skipped = _run_view(
        partial,
        _containers(),
        _agents(),
        r"""
const fills = [];
collectClass(body, "progress-bar", fills);
if (fills.length !== 3) throw new Error("fills " + fills.length);
if (fills.some((fill) => Object.prototype.hasOwnProperty.call(fill.style, "width"))) {
  throw new Error("fake width " + fills.map((fill) => fill.style.width).join(","));
}
console.log("ok");
""",
    )
    assert skipped.returncode == 0, skipped.stderr

    clamped = _host()
    clamped["cpu"]["percent"] = 140
    clamped["memory"]["percent"] = -4
    clamped["disks"][0]["percent"] = 50.0
    widths = _run_view(
        clamped,
        _containers(),
        _agents(),
        r"""
const fills = [];
collectClass(body, "progress-bar", fills);
const got = fills.map((fill) => fill.style.width).join(",");
if (got !== "100%,0%,50%") throw new Error(got);
console.log("ok");
""",
    )
    assert widths.returncode == 0, widths.stderr
