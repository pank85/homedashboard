"""Source contract for one-container-per-row cards at the desktop width.

Reads app/static/desktop.css as text. Does not import the app.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP_CSS = ROOT / "app" / "static" / "desktop.css"
GRID_SELECTOR = "#panel-containers .container-grid"
ROW_SELECTOR = "#panel-containers .container-card > div + div"
METER_SELECTOR = "#panel-containers .container-card .meter"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _block(source: str, opening: str) -> str:
    """Return the text inside the braces that follow `opening`."""
    start = source.index(opening)
    open_index = source.index("{", start)
    depth = 0
    for index in range(open_index, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[open_index + 1 : index]
    raise AssertionError("unbalanced braces after " + opening)


def _rule(source: str, selector: str) -> str:
    return _block(source, selector + " {")


def test_row_overrides_live_in_the_desktop_media_block() -> None:
    source = _read(DESKTOP_CSS)
    media = _block(source, "@media (min-width: 768px)")
    for selector in (GRID_SELECTOR, ROW_SELECTOR, METER_SELECTOR):
        assert selector in media
    assert "grid-template-columns: 1fr;" in _rule(media, GRID_SELECTOR)
    assert "grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));" not in media


def test_card_wrapper_is_a_wrapping_row() -> None:
    body = _rule(_read(DESKTOP_CSS), ROW_SELECTOR)
    assert "display: flex;" in body
    assert "flex-direction: row;" in body
    assert "flex-wrap: wrap;" in body
    assert "align-items: center;" in body
    assert "gap: 0.35rem 0.75rem;" in body


def test_row_children_lose_default_margins() -> None:
    source = _read(DESKTOP_CSS)
    children = ROW_SELECTOR + " > p,\n  " + ROW_SELECTOR + " > h3,\n  " + ROW_SELECTOR + " > details"
    assert "margin: 0;" in _rule(source, children)


def test_meters_stay_inline_and_require_a_width() -> None:
    meter = _rule(_read(DESKTOP_CSS), METER_SELECTOR)
    assert "flex: 1 1 6rem;" in meter
    assert "min-width: 4rem;" in meter
    assert "max-width: 8rem;" in meter
    assert "margin: 0;" in meter


def test_desktop_css_avoids_page_level_selectors() -> None:
    source = _read(DESKTOP_CSS)
    assert "html" not in source
    assert "body" not in source
    assert "background" not in source


def test_desktop_css_has_no_urls() -> None:
    source = _read(DESKTOP_CSS)
    assert "http://" not in source
    assert "https://" not in source


def test_no_new_card_classes_are_introduced() -> None:
    source = _read(DESKTOP_CSS)
    assert "card-body" not in source
    assert re.search(r"\.container-card > div \+ div", source) is not None
