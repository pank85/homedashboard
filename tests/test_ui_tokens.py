"""Token and component-layer contract for app/static/tabler.css.

Reads the stylesheet as text. Does not import the app.
"""

import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"
SOURCE = (STATIC_DIR / "tabler.css").read_text(encoding="utf-8")


def test_brief_token_names_present() -> None:
    for name in (
        "--bg",
        "--surface",
        "--surface-muted",
        "--fg",
        "--fg-muted",
        "--border",
        "--primary",
        "--on-primary",
        "--accent",
        "--on-accent",
        "--success",
        "--warning",
        "--danger",
        "--danger-text",
        "--info",
        "--text-xs",
        "--text-sm",
        "--text-base",
        "--text-lg",
        "--text-xl",
        "--text-2xl",
        "--space-1",
        "--space-2",
        "--space-3",
        "--space-4",
        "--space-5",
        "--space-6",
        "--radius-card",
        "--radius-control",
        "--radius-pill",
    ):
        assert name in SOURCE


def test_brief_hex_values_present_in_brief_casing() -> None:
    for token in (
        "#0F172A",
        "#1B2336",
        "#272F42",
        "#F8FAFC",
        "#94A3B8",
        "#475569",
        "#1E293B",
        "#FFFFFF",
        "#22C55E",
        "#F59E0B",
        "#EF4444",
        "#F87171",
        "#38BDF8",
    ):
        assert token in SOURCE


def test_old_palette_strings_absent() -> None:
    for old in (
        "#206bc4",
        "#151f2c",
        "#1b293a",
        "#2fb344",
        "#f76707",
        "#d63939",
        "#dce1e7",
        "#8b9bb4",
        "#243049",
        "#626976",
        "#4299e1",
        "#ffffff",
    ):
        assert old not in SOURCE


def test_hex_literals_live_only_in_the_tabler_root_block() -> None:
    tabler = STATIC_DIR / "tabler.css"
    text = tabler.read_text(encoding="utf-8")
    root_open = text.index(":root {")
    root_close = text.index("}", root_open)
    for match in re.finditer(r"#[0-9a-fA-F]{3,8}", text):
        assert root_open <= match.start() < root_close, match.group(0)
    for css in sorted(STATIC_DIR.glob("*.css")):
        if css == tabler:
            continue
        assert re.findall(r"#[0-9a-fA-F]{3,8}", css.read_text(encoding="utf-8")) == [], css.name


def test_alias_names_present() -> None:
    for alias in (
        "--tblr-body-bg",
        "--tblr-card-bg",
        "--tblr-primary",
        "--tblr-success",
        "--tblr-warning",
        "--tblr-danger",
        "--tblr-border-color",
        "--tblr-body-color",
        "--tblr-muted",
    ):
        assert alias in SOURCE


def test_alias_values_point_at_brief_tokens() -> None:
    for alias, target in (
        ("--tblr-body-bg", "var(--bg)"),
        ("--tblr-card-bg", "var(--surface)"),
        ("--tblr-body-color", "var(--fg)"),
        ("--tblr-heading-color", "var(--fg)"),
        ("--tblr-muted", "var(--fg-muted)"),
        ("--tblr-border-color", "var(--border)"),
        ("--tblr-primary", "var(--accent)"),
        ("--tblr-secondary", "var(--fg-muted)"),
        ("--tblr-success", "var(--success)"),
        ("--tblr-warning", "var(--warning)"),
        ("--tblr-danger", "var(--danger)"),
        ("--tblr-info", "var(--info)"),
    ):
        assert f"{alias}: {target}" in SOURCE


def test_component_selectors_present() -> None:
    for selector in (
        ".card",
        ".card-header",
        ".stat",
        ".btn-accent",
        ".btn-ghost",
        ".btn-danger",
        ".btn-neutral",
        ".badge-success",
        ".badge-warning",
        ".badge-danger",
        ".badge-muted",
        ".badge-info",
        ".table",
        ".nav",
        ".empty",
        ".meter",
    ):
        assert selector in SOURCE


def test_card_padding_stays_on_the_card_not_its_sections() -> None:
    # A .card that padded itself AND its .card-body doubled the padding.
    # The zero must stay on the card selectors; sections keep theirs.
    assert "section.card,\n.card {\n  padding: 0;\n}" in SOURCE
    assert ".card-sm {\n  padding: var(--space-3);" in SOURCE
    assert ".card-body {\n  padding: var(--space-4);" in SOURCE


def test_focus_ring_present_and_never_removed() -> None:
    assert "outline: 2px solid var(--accent)" in SOURCE
    assert ":focus-visible" in SOURCE
    assert "outline: none" not in SOURCE


def test_motion_and_pointer_media_queries_present() -> None:
    assert "@media (prefers-reduced-motion: no-preference)" in SOURCE
    assert "@media (pointer: coarse)" in SOURCE


def test_coarse_pointer_media_query_sets_a_44px_touch_target() -> None:
    header = "@media (pointer: coarse)"
    open_at = SOURCE.index("{", SOURCE.index(header))
    depth = 1
    close_at = open_at + 1
    while depth:
        if SOURCE[close_at] == "{":
            depth += 1
        elif SOURCE[close_at] == "}":
            depth -= 1
        close_at += 1
    assert "min-height: 44px" in SOURCE[open_at + 1 : close_at - 1]


def test_font_stack_and_dark_color_scheme() -> None:
    assert "system-ui, sans-serif" in SOURCE
    assert "color-scheme: dark" in SOURCE
    assert "color-scheme: light" not in SOURCE


def test_no_remote_or_imported_assets() -> None:
    assert "http://" not in SOURCE
    assert "https://" not in SOURCE
    assert "@import" not in SOURCE


def test_danger_fill_token_still_present_in_containers_css() -> None:
    # The exited strip and status dot paint with the danger FILL, while
    # badges use --danger-text; the fill must not silently disappear.
    css = (STATIC_DIR / "containers.css").read_text(encoding="utf-8")
    assert "var(--tblr-danger)" in css
