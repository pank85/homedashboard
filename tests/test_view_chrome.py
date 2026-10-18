import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
TEMPLATES = ROOT / "app" / "templates"

DESKTOP_CSS = STATIC / "desktop.css"
MOBILE_CSS = STATIC / "mobile.css"
VIEW_NAV_JS = STATIC / "view_nav.js"
APP_JS = STATIC / "app.js"
HOST_VIEW_JS = STATIC / "host_view.js"
SESSIONS_VIEW_JS = STATIC / "sessions_view.js"
INDEX_HTML = TEMPLATES / "index.html"
HOST_PARTIAL = TEMPLATES / "partials" / "host.html"
SESSIONS_PARTIAL = TEMPLATES / "partials" / "sessions.html"
MOBILE_TEMPLATE = TEMPLATES / "mobile.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_view_nav_source_contract() -> None:
    source = _read(VIEW_NAV_JS)
    assert "initViewNav" in source
    assert "data-section" in source
    assert "hidden" in source
    assert "innerHTML" not in source


def test_view_nav_scopes_to_nav_and_panels() -> None:
    source = _read(VIEW_NAV_JS)
    assert "[data-view-nav]" in source
    assert "[data-mobile-panel]" in source
    assert "globalThis.initViewNav" in source


def test_view_nav_is_idempotent() -> None:
    source = _read(VIEW_NAV_JS)
    # A bound marker makes a second initViewNav() call a no-op.
    assert "data-view-nav-bound" in source


def test_view_nav_has_no_network_or_html_injection() -> None:
    source = _read(VIEW_NAV_JS)
    assert "http://" not in source
    assert "https://" not in source
    assert "fetch(" not in source
    assert "innerHTML" not in source


def test_desktop_css_lays_out_named_classes() -> None:
    source = _read(DESKTOP_CSS)
    for selector in (".project-group", ".container-card", ".agent-card", ".git-list"):
        assert selector in source


def test_desktop_css_does_not_touch_page_palette() -> None:
    source = _read(DESKTOP_CSS)
    # Layout only: no root background override, so the dark palette from style.css wins.
    assert "html" not in source
    assert "body" not in source
    assert "background" not in source
    assert "#fff" not in source.lower()
    assert "white" not in source.lower()


def test_desktop_css_has_no_urls() -> None:
    source = _read(DESKTOP_CSS)
    assert "http://" not in source
    assert "https://" not in source


def test_mobile_css_hides_hidden_panels() -> None:
    source = _read(MOBILE_CSS)
    assert "[hidden]" in source
    assert "display: none" in source


def test_mobile_css_stacks_cards() -> None:
    source = _read(MOBILE_CSS)
    for selector in (".container-card", ".agent-card", ".session-card"):
        assert selector in source
    assert "flex-direction: column" in source


def test_mobile_css_sets_44px_tap_targets() -> None:
    source = _read(MOBILE_CSS)
    assert ".view-nav button" in source
    assert ".filters input" in source
    assert ".filters select" in source
    assert "#new-session-form button" in source
    assert ".session-card button" in source
    assert "min-height: 44px" in source


def test_mobile_css_has_no_urls() -> None:
    source = _read(MOBILE_CSS)
    assert "http://" not in source
    assert "https://" not in source


def test_breakpoint_is_767px_in_css_and_js() -> None:
    assert "@media (max-width: 767px)" in _read(MOBILE_CSS)
    assert "@media (min-width: 768px)" in _read(DESKTOP_CSS)
    assert 'matchMedia("(max-width: 767px)")' in _read(APP_JS)
    assert 'matchMedia("(min-width: 768px)")' not in _read(APP_JS)


def test_mobile_css_hides_herdr_frame() -> None:
    source = _read(MOBILE_CSS)
    mobile_block = source[source.index("@media (max-width: 767px)"):]
    assert "#herdr-frame" in mobile_block
    assert "display: none" in mobile_block


def test_view_nav_has_burger_and_menu() -> None:
    source = _read(VIEW_NAV_JS)
    assert "data-burger" in source
    assert "aria-expanded" in source
    assert 'getElementById("view-menu")' in source
    assert "data-menu-open" in source
    assert 'aria-controls="view-menu"' in _read(INDEX_HTML)


def test_view_nav_selects_section_from_hash() -> None:
    source = _read(VIEW_NAV_JS)
    assert "hashchange" in source
    assert "location.hash" in source


def test_view_nav_closes_menu_on_escape_and_section() -> None:
    source = _read(VIEW_NAV_JS)
    assert "Escape" in source
    assert "data-menu-open" in source


def test_view_nav_tracks_tab_selection() -> None:
    source = _read(VIEW_NAV_JS)
    assert "aria-selected" in source
    assert "removeAttribute" in source
    assert "setAttribute" in source


def test_app_js_sets_data_view_and_rerenders_on_change() -> None:
    source = _read(APP_JS)
    assert 'pageView()' in source
    assert 'setAttribute("data-view"' in source
    assert 'addEventListener("change"' in source


def test_tick_uses_optional_view_hooks() -> None:
    source = _read(APP_JS)
    assert 'typeof globalThis.renderHostView === "function"' in source
    assert 'typeof globalThis.renderSessionsView === "function"' in source
    assert "renderHostView(document.getElementById(\"host-body\"), data.host, data.containers, data.agents)" in source
    assert "renderSessionsView(data.sessions)" in source
    assert "renderHost(data.host)" in source
    assert "renderSessions(data.sessions)" in source


def test_view_renderers_are_defined_and_inert() -> None:
    # p2-host-ui and p3-sessions replaced the comment-only stubs with real
    # renderers; the contract now is that they define their global hook and
    # build DOM only (no network, no URLs, no innerHTML strings).
    for stub, name in ((HOST_VIEW_JS, "renderHostView"), (SESSIONS_VIEW_JS, "renderSessionsView")):
        source = _read(stub)
        assert ("function " + name) in source or (name + " = function") in source or (
            name + " ="
        ) in source
        assert "innerHTML" not in source
        assert "fetch(" not in source
        assert "http://" not in source
        assert "https://" not in source


def test_mobile_template_is_deleted() -> None:
    assert not MOBILE_TEMPLATE.exists()


def test_index_links_view_assets_before_app_js() -> None:
    source = _read(INDEX_HTML)
    for href in (
        "/static/desktop.css",
        "/static/mobile.css",
        "/static/view_nav.js",
        "/static/host_view.js",
        "/static/sessions_view.js",
    ):
        assert href in source
    for src in (
        "/static/view_nav.js",
        "/static/host_view.js",
        "/static/sessions_view.js",
        "/static/app.js",
    ):
        assert src in source
    assert source.index('src="/static/view_nav.js"') < source.index('src="/static/host_view.js"')
    assert source.index('src="/static/host_view.js"') < source.index('src="/static/sessions_view.js"')
    assert source.index('src="/static/sessions_view.js"') < source.index('src="/static/app.js"')


def test_index_view_chrome_has_tabs_and_burger() -> None:
    source = _read(INDEX_HTML)
    assert 'role="tablist"' in source
    assert source.count('role="tab"') == 5
    assert 'data-burger' in source
    assert 'id="view-menu"' in source
    assert 'data-menu-open' in source
    nav = re.search(r'<nav[^>]*data-view-nav[^>]*>.*?</nav>', source, re.S)
    assert nav is not None
    assert re.findall(r'data-section="([a-z]+)"', nav.group(0)) == [
        "host",
        "containers",
        "agents",
        "git",
        "sessions",
    ]
    assert 'href="/m"' not in source
    assert 'href="/"' not in source
    assert "view-switch" not in source


def test_partial_panels_carry_view_chrome_attributes() -> None:
    host_partial = _read(HOST_PARTIAL)
    host_panel = re.search(r'<section id="panel-host"[^>]*>', host_partial)
    assert host_panel is not None
    assert 'data-mobile-panel' in host_panel.group(0)
    assert 'data-section="host"' in host_panel.group(0)
    assert "hidden" not in host_panel.group(0)
    sessions_partial = _read(SESSIONS_PARTIAL)
    sessions_panel = re.search(r'<section id="panel-sessions"[^>]*>', sessions_partial)
    assert sessions_panel is not None
    assert 'data-mobile-panel' in sessions_panel.group(0)
    assert 'data-section="sessions"' in sessions_panel.group(0)
    assert "hidden" in sessions_panel.group(0)
    index_source = _read(INDEX_HTML)
    for section in ("containers", "agents", "git"):
        wrapper = re.search(r'<div[^>]*data-mobile-panel[^>]*data-section="' + section + r'"[^>]*>', index_source)
        assert wrapper is not None
        assert "hidden" in wrapper.group(0)
