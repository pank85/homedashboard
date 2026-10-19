"""Client-side container paging: slice of 5, desktop first paint, pager chrome.

Jinja plus source reads plus a small node check. Does not import app.main
or app.container_filters.
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
APP_JS = STATIC / "app.js"
INDEX = TEMPLATES / "index.html"
PAGING_JS = STATIC / "container_paging.js"
PAGER_CSS = STATIC / "container_pager.css"

UNAVAILABLE_BRANCH = """{% if not containers.available %}
    <p>unavailable: {{ containers.reason }}</p>
    {% elif not rows %}
    <div class="empty"><p class="empty-title">No containers.</p></div>"""


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html", "xml"]),
    )


def _render(name: str, containers: dict) -> str:
    return _env().get_template(f"partials/{name}").render(containers=containers)


def _row(name: str, project: str = "site") -> dict:
    return {
        "name": name,
        "compose_project": project,
        "state": "running",
        "health": "healthy",
    }


def _payload(*rows: dict, available: bool = True, reason: str = "") -> dict:
    return {
        "available": available,
        "reason": reason,
        "containers": list(rows),
    }


def _button(html: str, element_id: str) -> str:
    match = re.search(rf'<button[^>]*id="{element_id}"[^>]*>', html)
    assert match, element_id
    return match.group(0)


def _js_function(source: str, name: str) -> str:
    marker = "function " + name
    start = source.index(marker)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError("unclosed " + name)


def test_page_containers_slices_clamps_and_keeps_empty_on_one_page() -> None:
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
eval(source);
const rows = [{ name: "a" }, { name: "b" }, { name: "c" }, { name: "d" }, { name: "e" }, { name: "f" }];
const first = globalThis.pageContainers(rows, 0, 5);
if (first.rows.length !== 5) throw new Error("page0 len " + first.rows.length);
if (first.rows[0] !== rows[0] || first.rows[4] !== rows[4]) throw new Error("page0 slice");
if (first.page !== 0 || first.pages !== 2 || first.total !== 6 || first.size !== 5) throw new Error("page0 meta");
if (rows.length !== 6) throw new Error("mutated input");
const second = globalThis.pageContainers(rows, 1, 5);
if (second.rows.length !== 1 || second.rows[0] !== rows[5]) throw new Error("page1 " + JSON.stringify(second));
if (second.page !== 1) throw new Error("page1 index");
const clamped = globalThis.pageContainers(rows, 9, 5);
if (clamped.page !== 1 || clamped.rows.length !== 1 || clamped.rows[0] !== rows[5]) {
  throw new Error("clamp " + JSON.stringify(clamped));
}
const empty = globalThis.pageContainers([], 4, 5);
if (empty.pages !== 1 || empty.page !== 0 || empty.rows.length !== 0) throw new Error("empty " + JSON.stringify(empty));
const invalid = globalThis.pageContainers(rows, 0, 0);
if (invalid.size !== 5 || invalid.rows.length !== 5) throw new Error("invalid size");
if (globalThis.containerPage() !== 0) throw new Error("default page");
globalThis.setContainerPage(2);
if (globalThis.containerPage() !== 2) throw new Error("set page");
globalThis.setContainerPage(-1);
if (globalThis.containerPage() !== 2) throw new Error("stored negative");
globalThis.setContainerPage(1.5);
if (globalThis.containerPage() !== 2) throw new Error("stored float");
globalThis.resetContainerPage();
if (globalThis.containerPage() !== 0) throw new Error("reset");
if (globalThis.CONTAINER_PAGE_SIZE !== 5) throw new Error("size");
console.log("ok");
"""
    completed = subprocess.run(
        ["node", "-e", script, str(PAGING_JS)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "ok" in completed.stdout


def test_desktop_first_page_keeps_full_summary_and_one_heading() -> None:
    rows = [_row(f"row-{index}") for index in range(1, 7)]
    html = _render("containers_desktop.html", _payload(*rows))
    assert html.count("<article") == 5
    assert html.count('class="project-heading"') == 1
    assert ">site</h3>" in html
    assert "6 running · 0 stopped · 0 unhealthy" in html
    assert "6 of 6 shown" in html
    assert "Page 1 of 2" in html
    assert "row-6" not in html
    assert ">row-1</h3>" in html
    prev = _button(html, "container-pager-prev")
    nxt = _button(html, "container-pager-next")
    assert 'type="button"' in prev
    assert 'type="button"' in nxt
    assert "disabled" in prev
    assert "disabled" not in nxt
    assert html.index('id="containers-body"') < html.index('id="container-pager"')
    assert "container-pager" not in html.split('id="container-pager"', 1)[0].split('id="containers-body"', 1)[1]


def test_desktop_short_list_is_one_page() -> None:
    rows = [_row(f"row-{index}") for index in range(1, 5)]
    html = _render("containers_desktop.html", _payload(*rows))
    assert html.count("<article") == 4
    assert "4 of 4 shown" in html
    assert "Page 1 of 1" in html
    assert "disabled" in _button(html, "container-pager-next")


def test_unavailable_partial_has_no_none_and_a_single_page() -> None:
    html = _render(
        "containers_desktop.html",
        {"available": False, "reason": "docker socket not reachable", "containers": []},
    )
    assert "unavailable: docker socket not reachable" in html
    assert "0 of 0 shown" in html
    assert "None" not in html
    assert "undefined" not in html
    assert "Page 1 of 1" in html
    assert "disabled" in _button(html, "container-pager-prev")
    assert "disabled" in _button(html, "container-pager-next")


def test_empty_partial_keeps_empty_state() -> None:
    html = _render("containers_desktop.html", _payload())
    assert '<div class="empty"><p class="empty-title">No containers.</p></div>' in html
    source = DESKTOP.read_text(encoding="utf-8")
    assert UNAVAILABLE_BRANCH in source
    assert "{% if containers.available %}{{ rows|length }} of {{ rows|length }} shown{% else %}0 of 0 shown{% endif %}" in source
    assert "{{ counts.running }} running · {{ counts.stopped }} stopped · {{ counts.unhealthy }} unhealthy" in source
    assert source.count("{% for row in rows %}") == 1
    assert "{% for row in page_rows %}" in source


def test_mobile_partial_is_not_paged() -> None:
    rows = [_row(f"row-{index}") for index in range(1, 7)]
    html = _render("containers_mobile.html", _payload(*rows))
    assert html.count("<article") == 6
    assert "row-6" in html
    assert "container-pager" not in MOBILE.read_text(encoding="utf-8")


def test_app_resets_on_filter_change_and_not_on_tick() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    render = _js_function(source, "renderContainers")
    tick = _js_function(source, "tick")
    on_filter = _js_function(source, "onFilterChange")
    assert "pageContainers(" in render
    assert "setContainerPage" in render
    assert "resetContainerPage" in on_filter
    assert "resetContainerPage" not in tick
    assert "resetContainerPage" not in render
    assert ".value =" not in tick
    assert ".value =" not in render
    assert "renderContainers(data.containers)" in tick
    assert "syncContainerPager(0, 1)" in render


def test_index_loads_paging_script_between_filters_and_app() -> None:
    source = INDEX.read_text(encoding="utf-8")
    filters = source.index('src="/static/container_filters.js"')
    paging = source.index('src="/static/container_paging.js"')
    app = source.index('src="/static/app.js"')
    assert filters < paging < app
    assert source.index('href="/static/containers.css"') < source.index('href="/static/container_pager.css"')


def test_paging_assets_have_no_innerhtml_or_http() -> None:
    for path in (PAGING_JS, PAGER_CSS):
        text = path.read_text(encoding="utf-8")
        assert "innerHTML" not in text
        assert "http://" not in text
        assert "https://" not in text
    script = PAGING_JS.read_text(encoding="utf-8")
    assert "fetch(" not in script
    assert "document" not in script
    css = PAGER_CSS.read_text(encoding="utf-8")
    assert "white" not in css.lower()
    assert not re.findall(r"#[0-9a-fA-F]{3,8}", css)
    assert "min-height: 44px" in css
    assert "#container-pager" in css
    assert "flex-wrap: wrap" in css
    assert "gap:" in css
    for token in (
        "var(--tblr-body-bg)",
        "var(--tblr-body-color)",
        "var(--tblr-border-color)",
        "var(--tblr-primary)",
    ):
        assert token in css
    assert ".container-card" not in css
    assert ".container-grid" not in css
