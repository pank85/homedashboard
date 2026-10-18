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
    assert "globalThis.renderHostView = function" in source
    assert "createElement" in source
    assert "textContent" in source
    for forbidden in ("innerHTML", "http://", "https://", "fetch("):
        assert forbidden not in source


def test_render_host_view_matches_server_strings() -> None:
    host = _host()
    containers = _containers()
    agents = _agents()
    server = _render(host, containers, agents)
    required = [CPU_LINE, RAM_LINE, DISK_LINE, "2 running containers", "3 CLI AI agents / 2 running"]
    for line in required:
        assert line in server

    script = r"""
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
function serialize(node) {
  if (node.nodeType === 3) return node.textContent;
  const tag = node.tagName.toLowerCase();
  let attrs = "";
  if (node.id) attrs += ` id="${node.id}"`;
  if (node.className) attrs += ` class="${node.className}"`;
  return `<${tag}${attrs}>${node.childNodes.map(serialize).join("")}</${tag}>`;
}
globalThis.document = { createElement: (tag) => new Element(tag) };
const source = fs.readFileSync(process.argv[1], "utf8");
eval(source);
const body = globalThis.document.createElement("div");
globalThis.renderHostView(body, HOST, CONTAINERS, AGENTS);
const html = serialize(body);
for (const text of REQUIRED) {
  if (!html.includes(text)) throw new Error("missing " + text + " in " + html);
}
if (!html.includes('id="host-summary"')) throw new Error("missing host-summary");
for (const text of ["innerHTML", "used_bytes", "total_bytes", "per_core", "cpu0", "2147483648", "1073741824"]) {
  if (html.includes(text)) throw new Error("leaked " + text);
}
console.log("ok");
"""
    prefix = (
        "var HOST = " + json.dumps(host) + ";\n"
        "var CONTAINERS = " + json.dumps(containers) + ";\n"
        "var AGENTS = " + json.dumps(agents) + ";\n"
        "var REQUIRED = " + json.dumps(required) + ";\n"
    )
    completed = subprocess.run(
        ["node", "-e", prefix + script, str(VIEW_JS)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "ok" in completed.stdout
