from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"

DESKTOP_CSS = STATIC / "desktop.css"
MOBILE_CSS = STATIC / "mobile.css"
VIEW_NAV_JS = STATIC / "view_nav.js"


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
