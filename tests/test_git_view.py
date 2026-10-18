"""Render git panel partials with Jinja2. Does not import app.main."""

from html.parser import HTMLParser
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"
PARTIALS = ("git_desktop.html", "git_mobile.html")

ENV = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(["html"]),
)

TOKEN = "ghp_PlantedRawToken9f3a"
REDACTED_REMOTE = "https://github.com/org/repo.git"
RAW_REMOTE = "https://user:" + TOKEN + "@github.com/org/repo.git"
PATH_SENTINEL = "path-sentinel-not-rendered"
FULL_HEAD = "abcdef1SHOULD_NOT_SHOW_FULL_HEAD"
DIRTY_SENTINEL = "dirty-sentinel-not-rendered"
AHEAD_SENTINEL = "ahead-sentinel-not-rendered"
BEHIND_SENTINEL = "behind-sentinel-not-rendered"
HIDDEN_BRANCH = "hidden-branch-name"
TRUNCATED_NOTE = "The list stopped at the repo cap."


def render(name, git=None, omit_git=False):
    context = {} if omit_git else {"git": git}
    return ENV.get_template(f"partials/{name}").render(**context)


def unset_git():
    return {
        "available": True,
        "reason": "",
        "note": "git collector not configured",
        "scanned": False,
        "roots": [],
        "truncated": False,
        "refreshed_at": "",
        "projects": [],
        "unused_token": TOKEN,
    }


def empty_roots_git():
    return {
        "available": True,
        "reason": "",
        "note": "GIT_SCAN_ROOTS is empty",
        "scanned": False,
        "roots": [],
        "truncated": False,
        "refreshed_at": "",
        "projects": [],
        "unused_token": TOKEN,
    }


def scanned_empty_git():
    return {
        "available": True,
        "reason": "",
        "note": "no readable git roots",
        "scanned": True,
        "roots": ["/host/src"],
        "truncated": False,
        "refreshed_at": "",
        "projects": [],
        "unused_token": TOKEN,
    }


def project_row():
    return {
        "name": "homedashboard",
        "path": PATH_SENTINEL,
        "branch": "main",
        "detached": False,
        "head": FULL_HEAD,
        "head_short": "abcdef1",
        "upstream": "origin/main",
        "remote_url": REDACTED_REMOTE,
        "raw_remote_url": RAW_REMOTE,
        "unused_token": TOKEN,
        "in_progress": ["merge", "cherry-pick", {"token": TOKEN}],
        "commit_subject": "Ship the git panel",
        "commit_at": "2026-01-02T03:04:05Z",
        "commit_relative": "3h ago",
        "object_available": True,
        "dirty": DIRTY_SENTINEL,
        "ahead": AHEAD_SENTINEL,
        "behind": BEHIND_SENTINEL,
    }


def detached_row():
    return {
        "name": "notes",
        "path": PATH_SENTINEL,
        "branch": HIDDEN_BRANCH,
        "detached": True,
        "head": FULL_HEAD,
        "head_short": "1234567",
        "upstream": "",
        "remote_url": "",
        "raw_remote_url": RAW_REMOTE,
        "in_progress": [],
        "commit_subject": "Detach for notes",
        "commit_relative": "1d ago",
        "dirty": True,
        "ahead": 4,
        "behind": 2,
    }


def listed_git(**overrides):
    payload = {
        "available": True,
        "reason": "",
        "note": "",
        "scanned": True,
        "roots": ["/host/src"],
        "truncated": False,
        "refreshed_at": "2026-01-02T03:04:05Z",
        "projects": [project_row(), TOKEN, detached_row()],
        "unused_token": TOKEN,
    }
    payload.update(overrides)
    return payload


class DetailText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.details_depth = 0
        self.outside = []
        self.inside = []

    def handle_starttag(self, tag, attrs):
        if tag == "details":
            self.details_depth += 1

    def handle_endtag(self, tag):
        if tag == "details" and self.details_depth:
            self.details_depth -= 1

    def handle_data(self, data):
        text = " ".join(data.split())
        if not text:
            return
        if self.details_depth:
            self.inside.append(text)
        else:
            self.outside.append(text)


def _joined(parts):
    return "\n".join(parts)


@pytest.mark.parametrize("name", PARTIALS)
def test_partial_is_git_section(name):
    html = render(name, listed_git())
    assert html.count('id="panel-git"') == 1
    assert html.count('id="git-body"') == 1
    assert html.startswith("{% macro") is False
    start = html.index("<section")
    assert html[start:].startswith("<section")
    assert 'id="panel-git"' in html[start:start + 80]
    assert html.index("<h2>Git</h2>") < html.index('id="git-body"')


@pytest.mark.parametrize("name", PARTIALS)
@pytest.mark.parametrize(
    "git",
    [unset_git(), empty_roots_git(), None],
)
def test_unset_or_empty_roots(name, git):
    html = render(name, git)
    assert "No git roots configured." in html
    assert "No git projects found." not in html
    assert "unavailable:" not in html
    assert "git collector not configured" not in html
    assert "GIT_SCAN_ROOTS is empty" not in html
    assert TOKEN not in html


@pytest.mark.parametrize("name", PARTIALS)
def test_omitted_git_is_unset(name):
    html = render(name, omit_git=True)
    assert "No git roots configured." in html
    assert TOKEN not in html


@pytest.mark.parametrize("name", PARTIALS)
def test_unavailable_reason(name):
    html = render(
        name,
        {
            "available": False,
            "reason": "collector error",
            "note": "",
            "scanned": False,
            "roots": [],
            "truncated": False,
            "projects": [],
            "unused_token": TOKEN,
        },
    )
    assert "unavailable: collector error" in html
    assert "No git roots configured." not in html
    assert "No git projects found." not in html
    assert TOKEN not in html


@pytest.mark.parametrize("name", PARTIALS)
def test_scanned_with_no_projects(name):
    html = render(name, scanned_empty_git())
    assert "No git projects found." in html
    assert "No git roots configured." not in html
    assert "no readable git roots" not in html
    assert "/host/src" not in html
    assert TOKEN not in html


@pytest.mark.parametrize("name", PARTIALS)
def test_planted_token_and_hidden_fields_are_absent(name):
    html = render(name, listed_git())
    assert REDACTED_REMOTE in html
    assert "homedashboard" in html
    assert "Ship the git panel" in html
    assert "abcdef1" in html
    assert "origin/main" in html
    assert "merge" in html
    assert "cherry-pick" in html
    assert TOKEN not in html
    assert RAW_REMOTE not in html
    assert PATH_SENTINEL not in html
    assert "SHOULD_NOT_SHOW_FULL_HEAD" not in html
    assert DIRTY_SENTINEL not in html
    assert AHEAD_SENTINEL not in html
    assert BEHIND_SENTINEL not in html
    assert HIDDEN_BRANCH not in html
    assert "dirty" not in html
    assert "ahead" not in html
    assert "behind" not in html


def test_desktop_is_compact_list_without_details():
    html = render("git_desktop.html", listed_git())
    assert 'class="git-list"' in html
    assert "<details" not in html
    assert "head abcdef1" in html
    assert "upstream origin/main" in html
    assert "remote " + REDACTED_REMOTE in html
    assert "3h ago" in html
    assert ">detached<" in html
    assert "notes" in html
    assert html.index("homedashboard") < html.index("notes")


def test_mobile_card_hides_the_rest_in_details():
    html = render("git_mobile.html", listed_git())
    assert html.count("<article") == 2
    assert html.count("<details") == 2
    assert 'class="git-list"' not in html
    parser = DetailText()
    parser.feed(html)
    outside = _joined(parser.outside)
    inside = _joined(parser.inside)
    assert "homedashboard" in outside
    assert "main" in outside
    assert "Ship the git panel" in outside
    assert "notes" in outside
    assert "detached" in outside
    assert "Detach for notes" in outside
    assert "abcdef1" not in outside
    assert "origin/main" not in outside
    assert REDACTED_REMOTE not in outside
    assert "merge" not in outside
    assert "3h ago" not in outside
    assert "head abcdef1" in inside
    assert "upstream origin/main" in inside
    assert "remote " + REDACTED_REMOTE in inside
    assert "merge" in inside
    assert "cherry-pick" in inside
    assert "3h ago" in inside
    assert "Details" in inside
    assert TOKEN not in outside
    assert TOKEN not in inside


@pytest.mark.parametrize("name", PARTIALS)
def test_truncated_note(name):
    html = render(name, listed_git(truncated=True))
    assert TRUNCATED_NOTE in html
    assert "homedashboard" in html
    assert TOKEN not in html


@pytest.mark.parametrize("name", PARTIALS)
def test_truncated_with_empty_scan_still_notes_the_cap(name):
    payload = scanned_empty_git()
    payload["truncated"] = True
    html = render(name, payload)
    assert "No git projects found." in html
    assert TRUNCATED_NOTE in html


def test_empty_remote_is_unknown_not_a_dump():
    row = project_row()
    row["remote_url"] = ""
    row["raw_remote_url"] = RAW_REMOTE
    html = render("git_desktop.html", listed_git(projects=[row]))
    assert "remote unknown" in html
    assert TOKEN not in html
    assert RAW_REMOTE not in html


def test_static_git_view_has_no_inner_html_or_urls():
    script = (ROOT / "app" / "static" / "git_view.js").read_text(encoding="utf-8")
    style = (ROOT / "app" / "static" / "git.css").read_text(encoding="utf-8")
    for source in (script, style):
        assert "innerHTML" not in source
        assert "http://" not in source
        assert "https://" not in source
    assert "globalThis.renderGitView" in script
    assert "createElement" in script
    assert "textContent" in script
    assert "No git roots configured." in script
    assert "No git projects found." in script
    assert "unavailable: " in script
    assert TRUNCATED_NOTE in script
    assert "detached" in script
    assert "ahead" not in script
    assert "behind" not in script
    assert "dirty" not in script
    assert "min-height: 44px" in style
    for color in ("#0f1419", "#e7ecf1", "#1a2332", "#3dd68c", "#e6b35a", "#f07178"):
        assert color in style


def test_partial_sources_do_not_dump_objects_or_embed_urls():
    for name in PARTIALS:
        source = (TEMPLATES / "partials" / name).read_text(encoding="utf-8")
        assert 'id="panel-git"' in source
        assert 'id="git-body"' in source
        assert "remote_url" in source
        assert "{{ project }}" not in source
        assert "{{ git }}" not in source
        assert ".items()" not in source
        assert "innerHTML" not in source
        assert "http://" not in source
        assert "https://" not in source
        assert "ahead" not in source
        assert "behind" not in source
        assert "dirty" not in source
