"""Render container partials and check the view script contract.

Jinja only. Does not import app.container_filters or app.main.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"
STATIC = ROOT / "app" / "static"
DESKTOP = TEMPLATES / "partials" / "containers_desktop.html"
MOBILE = TEMPLATES / "partials" / "containers_mobile.html"
VIEW_JS = STATIC / "containers_view.js"
VIEW_CSS = STATIC / "containers.css"

SUMMARY = "{running} running · {stopped} stopped · {unhealthy} unhealthy"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html", "xml"]),
    )


def _render(name: str, containers: dict) -> str:
    return _env().get_template(f"partials/{name}").render(containers=containers)


def _web_row() -> dict:
    return {
        "name": "web-1",
        "compose_service": "web",
        "compose_project": "site",
        "id_short": "abc123",
        "image": "ghcr.io/example/web:latest",
        "image_short": "web:latest",
        "state": "running",
        "state_label": "running",
        "health": "healthy",
        "health_label": "healthy",
        "uptime_human": "2m 0s",
        "restart_count": 2,
        "cpu_percent": 12.5,
        "cpu_percent_human": "12.5%",
        "memory_used_bytes": 512,
        "memory_limit_bytes": 1024,
        "memory_used_human": "512 B",
        "memory_limit_human": "1.0 KiB",
    }


def _old_row() -> dict:
    return {
        "name": "old-1",
        "compose_service": "",
        "compose_project": "",
        "id_short": "def456",
        "image": None,
        "state": "exited",
        "state_label": "exited",
        "health": None,
        "health_label": "none",
        "uptime_seconds": None,
        "restart_count": None,
        "cpu_percent": None,
        "cpu_percent_human": "unknown",
        "memory_used_bytes": None,
        "memory_limit_bytes": None,
        "memory_used_human": "unknown",
        "memory_limit_human": "unknown",
    }


def _payload(*rows: dict, available: bool = True, reason: str = "") -> dict:
    return {
        "available": available,
        "reason": reason,
        "containers": list(rows),
    }


def _articles(html: str) -> list[str]:
    return re.findall(r'<article class="container-card">.*?</article>', html, re.S)


def _select(html: str, element_id: str) -> str:
    match = re.search(rf'<select id="{element_id}">.*?</select>', html, re.S)
    assert match, element_id
    return match.group(0)


def test_desktop_fixture_headings_meters_and_details() -> None:
    html = _render("containers_desktop.html", _payload(_web_row(), _old_row()))
    assert html.startswith("<section") or "<section id=\"panel-containers\">" in html
    assert 'id="panel-containers"' in html
    assert ">web-1</h3>" in html
    assert ">old-1</h3>" in html
    assert ">web</h3>" not in html
    assert 'class="container-subtitle">web</p>' in html
    assert "web:latest" in html
    assert 'style="width: 12.5%"' in html
    assert 'style="width: 50.0%"' in html
    assert ">running</span>" in html
    assert ">healthy</span>" in html
    assert ">exited</span>" in html
    assert ">none</span>" in html
    assert "unknown" in html
    assert "container-grid" in html
    for short_id in ("abc123", "def456"):
        article = next(item for item in _articles(html) if short_id in item)
        head, details = article.split("<details>", 1)
        assert short_id not in head
        assert short_id in details
        assert "<summary>Details</summary>" in details
        assert "id " + short_id in details


def test_desktop_memory_percent_passthrough_is_one_decimal() -> None:
    row = _web_row()
    row.pop("memory_used_bytes")
    row.pop("memory_limit_bytes")
    row["memory_percent"] = 50.0
    html = _render("containers_desktop.html", _payload(row))
    assert 'style="width: 12.5%"' in html
    assert 'style="width: 50.0%"' in html


def test_summary_counts_restarting_as_stopped_and_unhealthy() -> None:
    rows = [
        {"name": "up", "state": "running", "health": "healthy"},
        {"name": "down", "state": "exited", "health": "none"},
        {"name": "loop", "state": "restarting", "health": "healthy"},
        {"name": "bad", "state": "running", "health": "unhealthy"},
    ]
    html = _render("containers_desktop.html", _payload(*rows))
    assert 'id="container-summary"' in html
    assert SUMMARY.format(running=2, stopped=2, unhealthy=2) in html
    assert "4 of 4 shown" in html
    assert html.count("<article") == 4


def test_server_html_is_unfiltered_incoming_order_grouped() -> None:
    rows = [
        {"name": "z-first", "compose_project": "zeta", "state": "exited", "health": None, "id_short": "z1"},
        {"name": "a-card", "compose_project": "Alpha", "state": "running", "health": "healthy", "id_short": "a1"},
        {"name": "loose", "compose_project": "", "state": "running", "health": "healthy", "id_short": "o1"},
        {"name": "z-second", "compose_project": "zeta", "state": "running", "health": "unhealthy", "id_short": "z2"},
        {"name": "lower", "compose_project": "alpha", "state": "restarting", "health": "healthy", "id_short": "a2"},
    ]
    html = _render("containers_mobile.html", _payload(*rows))
    assert SUMMARY.format(running=3, stopped=2, unhealthy=2) in html
    assert "5 of 5 shown" in html
    headings = re.findall(r'<h3 class="project-heading">(.*?)</h3>', html)
    assert headings == ["Alpha", "alpha", "zeta", "Other"]
    zeta = html.split('<h3 class="project-heading">zeta</h3>', 1)[1].split('<h3 class="project-heading">', 1)[0]
    assert zeta.index(">z-first</h3>") < zeta.index(">z-second</h3>")
    for name in ("z-first", "a-card", "loose", "z-second", "lower"):
        assert f">{name}</h3>" in html


def test_missing_name_is_unknown_not_compose_service() -> None:
    row = {"name": "", "compose_service": "web", "state": "running", "health": "healthy"}
    html = _render("containers_desktop.html", _payload(row))
    assert ">unknown</h3>" in html
    assert ">web</h3>" not in html
    assert 'class="container-subtitle">web</p>' in html


def test_filter_controls_sort_options_and_empty_states() -> None:
    html = _render("containers_desktop.html", _payload())
    assert 'id="container-filter-text"' in html
    assert 'id="container-filter-state"' in html
    assert 'id="container-filter-hide-healthy"' in html
    assert 'id="container-filter-count"' in html
    assert 'id="container-filter-sort"' in html
    assert 'id="container-summary"' in html
    assert 'id="containers-body"' in html
    assert html.index('id="container-filter-text"') < html.index('id="containers-body"')
    state = _select(html, "container-filter-state")
    for word in ("All", "Running", "Stopped"):
        assert f'value="{word}"' in state
        assert f">{word}</option>" in state
    sort = _select(html, "container-filter-sort")
    for word in ("status", "name", "cpu", "memory"):
        assert f'value="{word}"' in sort
        assert f">{word}</option>" in sort
    assert 'value="status" selected' in sort
    assert "0 of 0 shown" in html
    assert SUMMARY.format(running=0, stopped=0, unhealthy=0) in html
    assert "No containers." in html

    unavailable = _render(
        "containers_desktop.html",
        {"available": False, "reason": "docker socket not reachable", "containers": []},
    )
    assert "unavailable: docker socket not reachable" in unavailable
    assert "0 of 0 shown" in unavailable
    assert "None" not in unavailable


def test_mobile_card_is_one_line_without_meters() -> None:
    html = _render("containers_mobile.html", _payload(_web_row(), _old_row()))
    assert 'id="panel-containers"' in html
    assert ">web-1</h3>" in html
    assert ">old-1</h3>" in html
    assert ">web</h3>" not in html
    assert 'class="container-subtitle">web</p>' in html
    assert "meter" not in html
    assert "width:" not in html
    assert "<details>" in html
    assert not re.search(r"<details[^>]*\sopen[\s>]", html)
    scan = re.search(r'<div class="container-scan">.*?</div>', html, re.S)
    assert scan
    line = scan.group(0)
    assert ">web-1</h3>" in line
    assert ">running</span>" in line
    assert "cpu 12.5%" in line
    assert "memory 512 B / 1.0 KiB" in line
    web = next(item for item in _articles(html) if "abc123" in item)
    details = web.split("<details>", 1)[1]
    assert "web:latest" in details
    assert "uptime 2m 0s" in details
    assert "restarts 2" in details
    assert "id abc123" in details
    assert "abc123" not in web.split("<details>", 1)[0]


def test_partials_copy_macros_and_do_not_call_filter_globals() -> None:
    for path in (DESKTOP, MOBILE):
        source = path.read_text(encoding="utf-8")
        assert "{% macro human(value) -%}" in source
        assert "{% macro health_word(value) -%}" in source
        assert "{% macro bar_width(value) -%}" in source
        assert "group_containers" not in source
        assert "sort_containers" not in source
        assert "innerHTML" not in source
        assert "http://" not in source
        assert "https://" not in source


def test_css_uses_dark_palette_and_tap_targets() -> None:
    css = VIEW_CSS.read_text(encoding="utf-8")
    assert not re.findall(r"#[0-9a-fA-F]{3,8}", css)
    assert "var(--tblr-body-bg)" in css
    assert "min-height: 44px" in css
    assert "http://" not in css
    assert "https://" not in css
    assert "white" not in css.lower()


def test_view_script_source_contract() -> None:
    source = VIEW_JS.read_text(encoding="utf-8")
    assert "globalThis.renderContainersView" in source
    assert "globalThis.groupContainers" in source
    assert "function renderContainersView(root, rows, view)" in source
    assert "containers-body" in source
    assert "container-filter" not in source
    assert "container-summary" not in source
    assert ".value" not in source
    assert "innerHTML" not in source
    assert "http://" not in source
    assert "https://" not in source
    assert "createElement" in source
    assert "textContent" in source


def test_render_containers_view_groups_without_touching_filters() -> None:
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
  this.attributes = {};
  this.className = "";
  this.id = "";
  this.style = {};
}
Object.defineProperty(Element.prototype, "textContent", {
  get() {
    return this.childNodes.map((child) => child.textContent || "").join("");
  },
  set(value) {
    const text = new TextNode(value);
    text.parentNode = this;
    this.childNodes = [text];
  },
});
Object.defineProperty(Element.prototype, "firstChild", {
  get() {
    return this.childNodes[0] || null;
  },
});
Element.prototype.appendChild = function (child) {
  child.parentNode = this;
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
  if (name === "id") this.id = String(value);
};
function findId(node, id) {
  if (!node || node.nodeType !== 1) return null;
  if (node.id === id) return node;
  for (const child of node.childNodes) {
    const found = findId(child, id);
    if (found) return found;
  }
  return null;
}
Element.prototype.querySelector = function (selector) {
  if (selector === "#containers-body") return findId(this, "containers-body");
  return null;
};
function serialize(node) {
  if (node.nodeType === 3) return node.textContent;
  const tag = node.tagName.toLowerCase();
  let attrs = "";
  if (node.id) attrs += ` id="${node.id}"`;
  if (node.className) attrs += ` class="${node.className}"`;
  for (const key of Object.keys(node.attributes)) {
    if (key === "id") continue;
    attrs += ` ${key}="${node.attributes[key]}"`;
  }
  if (node.style && node.style.width) attrs += ` style="width: ${node.style.width}"`;
  const inner = node.childNodes.map(serialize).join("");
  return `<${tag}${attrs}>${inner}</${tag}>`;
}
const lookedUp = [];
const document = {
  createElement: (tag) => new Element(tag),
  createTextNode: (text) => new TextNode(text),
  getElementById: (id) => {
    lookedUp.push(id);
    return null;
  },
};
global.document = document;
global.lookedUp = lookedUp;
global.serialize = serialize;
"""
    body = r"""
const source = fs.readFileSync(process.argv[1], "utf8");
eval(source);
const rows = [
  { name: "z-first", compose_project: "zeta", state: "exited", id_short: "z1" },
  { name: "a-card", compose_project: "Alpha", state: "running", state_label: "running", id_short: "a1" },
  { name: "loose", compose_project: "", state: "running", id_short: "o1" },
];
const panel = document.createElement("section");
const summary = document.createElement("p");
summary.id = "container-summary";
summary.textContent = "keep me";
panel.appendChild(summary);
const body = document.createElement("div");
body.id = "containers-body";
body.textContent = "old";
panel.appendChild(body);
renderContainersView(panel, rows, "desktop");
if (summary.textContent !== "keep me") throw new Error("summary changed");
if (lookedUp.length) throw new Error("looked up " + lookedUp.join(","));
const html = serialize(body);
if (html.indexOf(">Alpha</h3>") > html.indexOf(">zeta</h3>")) throw new Error("group order " + html);
if (!html.includes(">Other</h3>")) throw new Error("missing Other");
if (html.indexOf(">a-card</h3>") > html.indexOf(">z-first</h3>")) throw new Error("card order");
if (!html.includes("abc") && !html.includes("id z1")) throw new Error("missing id");
if (!html.includes('class="meter"')) throw new Error("desktop meter missing");
const mobile = document.createElement("div");
mobile.id = "containers-body";
renderContainersView(mobile, [{ name: "web-1", compose_service: "web", state: "running", cpu_percent_human: "12.5%", memory_used_human: "512 B", memory_limit_human: "1.0 KiB", id_short: "abc123", image_short: "web:latest" }], "mobile");
const mobileHtml = serialize(mobile);
if (mobileHtml.includes("meter")) throw new Error("mobile meter");
if (!mobileHtml.includes(">web-1</h3>")) throw new Error("mobile title");
if (mobileHtml.includes(">web</h3>")) throw new Error("service used as title");
if (!mobileHtml.includes("abc123")) throw new Error("mobile id");
const calls = [];
globalThis.groupContainers = function (passed) {
  calls.push(passed);
  return [{ project: "zeta", rows: [passed[1]] }, { project: "Alpha", rows: [passed[0]] }];
};
const forced = document.createElement("div");
forced.id = "containers-body";
renderContainersView(forced, rows, "desktop");
const forcedHtml = serialize(forced);
if (calls.length !== 1) throw new Error("groupContainers calls " + calls.length);
if (forcedHtml.indexOf(">zeta</h3>") > forcedHtml.indexOf(">Alpha</h3>")) throw new Error("resorted helper groups");
if (forcedHtml.includes(">Other</h3>")) throw new Error("fallback regrouped");
delete globalThis.groupContainers;
renderContainersView(forced, [], "desktop");
if (!serialize(forced).includes("No containers.")) throw new Error("empty message");
console.log("ok");
"""
    completed = subprocess.run(
        ["node", "-e", script + "\n" + body, str(VIEW_JS)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "ok" in completed.stdout
