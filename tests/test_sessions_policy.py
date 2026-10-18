"""Tests for app.sessions_policy.

No herdr binary, no network, no process spawn.
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.sessions_policy as sessions_policy
from app.sessions_policy import (
    AGENT_START_KINDS,
    AGENT_START_SUBPROCESS_TIMEOUT,
    AGENT_START_TIMEOUT_MS,
    PolicyError,
    agent_name_from_label,
    agent_start_argv,
    attach_command,
    display_argv,
    parse_workspace_created,
    token_status,
    validate_cwd,
    validate_kind,
    validate_label,
    validate_session_id,
    validate_session_name,
    workspace_create_argv,
)

_KINDS = (
    "pi",
    "claude",
    "codex",
    "gemini",
    "cursor",
    "devin",
    "agy",
    "cline",
    "opencode",
    "copilot",
    "kimi",
    "kiro",
    "droid",
    "amp",
    "grok",
    "hermes",
    "kilo",
    "qodercli",
    "qwen",
    "letta",
    "maki",
    "muse",
)


def test_agent_start_kinds_are_the_22_in_order():
    assert AGENT_START_KINDS == _KINDS
    assert len(AGENT_START_KINDS) == 22
    assert len(set(AGENT_START_KINDS)) == 22
    assert "omp" not in AGENT_START_KINDS
    assert "mastracode" not in AGENT_START_KINDS


@pytest.mark.parametrize("kind", _KINDS)
def test_validate_kind_accepts_allowlist(kind: str):
    assert validate_kind(kind) == kind


@pytest.mark.parametrize("kind", ["omp", "mastracode", "Pi", "claude;id", "", "CLAUDE", "claude "])
def test_validate_kind_rejects_unknown(kind: str):
    with pytest.raises(PolicyError) as exc:
        validate_kind(kind)
    assert exc.value.reason == "unknown agent kind"


def test_token_unset_ignores_provided_credentials():
    assert token_status("", "Bearer secret", "secret") == "unset"
    assert token_status("   ", "Basic nope", "nope") == "unset"
    assert token_status("\n", None, None) == "unset"


def test_token_ok_from_bearer_or_form():
    assert token_status("s3cret", "Bearer s3cret", None) == "ok"
    assert token_status("s3cret", "bearer s3cret", "wrong") == "ok"
    assert token_status("s3cret", "BEARER   s3cret", "wrong") == "ok"
    assert token_status("s3cret", None, "s3cret") == "ok"


def test_bad_or_non_bearer_authorization_does_not_fall_back():
    assert token_status("s3cret", "Basic s3cret", "s3cret") == "invalid"
    assert token_status("s3cret", "Bearer wrong", "s3cret") == "invalid"
    assert token_status("s3cret", "s3cret", "s3cret") == "invalid"
    assert token_status("s3cret", "", "s3cret") == "invalid"
    assert token_status("s3cret", "Bearer", "s3cret") == "invalid"
    assert token_status("s3cret", "Bearer s3cret extra", "s3cret") == "invalid"


def test_missing_credential_is_invalid_when_token_configured():
    assert token_status("s3cret", None, None) == "invalid"
    assert token_status("s3cret", None, "") == "invalid"


def test_token_compare_uses_sha256_digests_when_lengths_differ():
    assert token_status("short", None, "a-much-longer-wrong-token") == "invalid"
    expected = hashlib.sha256(b"short").digest()
    provided = hashlib.sha256(b"a-much-longer-wrong-token").digest()
    assert len(expected) == len(provided) == 32
    assert hmac.compare_digest(expected, provided) is False
    source = Path(sessions_policy.__file__).read_text(encoding="utf-8")
    assert "hmac.compare_digest" in source
    assert "sha256" in source


def test_validate_session_name_refuses_default():
    for name in ("default", "Default", "DEFAULT", " default "):
        with pytest.raises(PolicyError) as exc:
            validate_session_name(name)
        assert exc.value.reason == "refusing session default"


@pytest.mark.parametrize("name", ["", "has space", "semi;", "../x", "-lead", "a" * 65, "has.dot"])
def test_validate_session_name_charset(name: str):
    with pytest.raises(PolicyError) as exc:
        validate_session_name(name)
    assert exc.value.reason == "invalid HERDR_SESSION"


def test_validate_session_name_returns_stripped():
    assert validate_session_name("hermes") == "hermes"
    assert validate_session_name(" Hermes ") == "Hermes"
    assert validate_session_name("a_b-c") == "a_b-c"


def test_blank_label_uses_utc_timestamp():
    now = datetime(2026, 10, 17, 22, 39, 27, tzinfo=timezone.utc)
    assert validate_label(None, kind="claude", now=now) == "claude-20261017223927"
    assert validate_label("", kind="pi", now=now) == "pi-20261017223927"
    assert validate_label("  \n", kind="hermes", now=now) == "hermes-20261017223927"
    shifted = datetime(2026, 10, 17, 18, 39, 27, tzinfo=timezone(timedelta(hours=-4)))
    assert validate_label(None, kind="pi", now=shifted) == "pi-20261017223927"
    naive = datetime(2026, 10, 17, 22, 39, 27)
    assert validate_label(None, kind="muse", now=naive) == "muse-20261017223927"


def test_generated_label_matches_pattern_without_clock_injection():
    label = validate_label(None, kind="opencode")
    assert label.startswith("opencode-")
    stamp = label.split("-", 1)[1]
    parsed = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - parsed).total_seconds()) < 5


@pytest.mark.parametrize(
    "label",
    ["a;b", "a`b", "a$b", "a|b", "a\nb", "-leading", "has\r", " " + "ok", "x" * 65],
)
def test_label_rejects_metacharacters_and_leading_hyphen(label: str):
    with pytest.raises(PolicyError) as exc:
        validate_label(label, kind="pi")
    assert exc.value.reason == "invalid label"


def test_label_accepts_safe_punctuation():
    assert validate_label("my-label", kind="pi") == "my-label"
    assert validate_label("My Label", kind="pi") == "My Label"
    assert validate_label("a.b_c", kind="pi") == "a.b_c"
    assert validate_label("a" + "b" * 63, kind="pi") == "a" + "b" * 63


def test_label_accepts_unicode_letters_verbatim():
    label = "Hermes Probe \u30bb\u30c3\u30b7\u30e7\u30f3"
    assert validate_label(label, kind="hermes") == label
    assert validate_label("\u30bb\u30c3\u30b7\u30e7\u30f3", kind="hermes") == "\u30bb\u30c3\u30b7\u30e7\u30f3"
    assert validate_label("\u30bb" * 64, kind="hermes") == "\u30bb" * 64


@pytest.mark.parametrize("label", ["ok\U0001f600", "Hermes;\u30bb\u30c3\u30b7\u30e7\u30f3", "\u30bb" * 65])
def test_label_rejects_non_letters_and_overlong_unicode(label: str):
    with pytest.raises(PolicyError) as exc:
        validate_label(label, kind="pi")
    assert exc.value.reason == "invalid label"


def test_agent_name_from_label_slugifies_probe_session():
    assert agent_name_from_label("hermes probe session", kind="hermes") == "hermes-probe-session"


def test_agent_name_from_label_drops_case_spaces_and_unicode():
    label = "Hermes Probe \u30bb\u30c3\u30b7\u30e7\u30f3"
    name = agent_name_from_label(label, kind="hermes")
    assert re.fullmatch(r"[a-z][a-z0-9-]{0,31}", name)
    assert name != label
    assert name == "hermes-probe"
    assert agent_name_from_label("A.B_C", kind="pi") == "a-b-c"
    assert agent_name_from_label("a" * 40, kind="pi") == "a" * 32


def test_agent_name_from_label_falls_back_when_slug_unusable():
    now = datetime(2026, 10, 17, 22, 39, 27, tzinfo=timezone.utc)
    assert agent_name_from_label("", kind="pi", now=now) == "pi-20261017223927"
    assert agent_name_from_label("\u30bb\u30c3\u30b7\u30e7\u30f3", kind="hermes", now=now) == validate_label(
        None, kind="hermes", now=now
    )
    assert agent_name_from_label("123 session", kind="claude", now=now) == "claude-20261017223927"


def test_cwd_empty_allowlist_does_not_require_a_path(tmp_path: Path):
    missing = tmp_path / "missing"
    with pytest.raises(PolicyError) as exc:
        validate_cwd(str(missing), ())
    assert exc.value.reason == "CHAT_CWD_ALLOWLIST unset"
    with pytest.raises(PolicyError) as blank:
        validate_cwd("../x", ("", "  "))
    assert blank.value.reason == "CHAT_CWD_ALLOWLIST unset"


def test_cwd_relative_rejected_before_resolve(tmp_path: Path):
    proj = tmp_path / "proj"
    inside = proj / "inside"
    inside.mkdir(parents=True)
    with pytest.raises(PolicyError) as exc:
        validate_cwd("inside", (str(proj),))
    assert exc.value.reason == "cwd must be absolute"
    with pytest.raises(PolicyError) as escaped:
        validate_cwd("../x", (str(proj),))
    assert escaped.value.reason == "cwd must be absolute"


def test_cwd_missing_rejected(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with pytest.raises(PolicyError) as exc:
        validate_cwd(str(proj / "missing"), (str(proj),))
    assert exc.value.reason == "cwd does not exist"


def test_cwd_dotdot_outside_rejected(tmp_path: Path):
    proj = tmp_path / "proj"
    outside = tmp_path / "outside"
    proj.mkdir()
    outside.mkdir()
    escaped = proj / ".." / "outside"
    assert escaped.is_absolute()
    with pytest.raises(PolicyError) as exc:
        validate_cwd(str(escaped), (str(proj),))
    assert exc.value.reason == "cwd outside allowlist"


def test_cwd_symlink_to_outside_rejected(tmp_path: Path):
    proj = tmp_path / "proj"
    outside = tmp_path / "outside"
    proj.mkdir()
    outside.mkdir()
    link = proj / "link"
    link.symlink_to(outside)
    with pytest.raises(PolicyError) as exc:
        validate_cwd(str(link), (str(proj),))
    assert exc.value.reason == "cwd outside allowlist"


def test_cwd_string_prefix_trap_rejected(tmp_path: Path):
    proj = tmp_path / "proj"
    evil = tmp_path / "proj-evil"
    proj.mkdir()
    evil.mkdir()
    assert str(evil).startswith(str(proj))
    with pytest.raises(PolicyError) as exc:
        validate_cwd(str(evil), (str(proj),))
    assert exc.value.reason == "cwd outside allowlist"


def test_cwd_happy_path_returns_resolved_path(tmp_path: Path):
    proj = tmp_path / "proj"
    nested = proj / "app"
    nested.mkdir(parents=True)
    lexical = proj / "app" / ".." / "app"
    assert validate_cwd(str(proj), (str(proj),)) == str(proj.resolve())
    assert validate_cwd(str(nested), (str(proj),)) == str(nested.resolve())
    assert validate_cwd(str(lexical), (str(proj),)) == str(nested.resolve())
    other = tmp_path / "other"
    other.mkdir()
    assert validate_cwd(str(nested), (str(other), str(proj))) == str(nested.resolve())


def test_cwd_expanduser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    proj = home / "work"
    proj.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    assert validate_cwd("~/work", (str(proj),)) == str(proj.resolve())
    assert validate_cwd(str(proj), ("~/work",)) == str(proj.resolve())


def test_cwd_symlink_inside_returns_target(tmp_path: Path):
    proj = tmp_path / "proj"
    real = proj / "real"
    real.mkdir(parents=True)
    link = proj / "link"
    link.symlink_to(real)
    assert validate_cwd(str(link), (str(proj),)) == str(real.resolve())


def test_cwd_oserror_is_not_readable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    proj = tmp_path / "proj"
    child = proj / "child"
    child.mkdir(parents=True)
    real_resolve = Path.resolve

    def boom(self: Path, *args: object, **kwargs: object) -> Path:
        if self == Path(child):
            raise PermissionError("denied")
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", boom)
    with pytest.raises(PolicyError) as exc:
        validate_cwd(str(child), (str(proj),))
    assert exc.value.reason == "cwd not readable"


def test_cwd_null_byte_is_not_readable():
    with pytest.raises(PolicyError) as exc:
        validate_cwd("/tmp/\x00nope", ("/tmp",))
    assert exc.value.reason == "cwd not readable"


def test_workspace_create_argv_exact():
    argv = workspace_create_argv(
        "/usr/bin/herdr",
        "hermes",
        "/proj/app",
        "claude-20261017223927",
    )
    assert argv == [
        "/usr/bin/herdr",
        "--session",
        "hermes",
        "workspace",
        "create",
        "--cwd",
        "/proj/app",
        "--label",
        "claude-20261017223927",
        "--no-focus",
    ]
    assert isinstance(argv, list)
    assert "--" not in argv
    assert "shell" not in argv
    assert "--focus" not in argv
    assert "close" not in argv
    assert "delete" not in argv
    assert "stop" not in argv


def test_agent_start_argv_exact():
    argv = agent_start_argv("herdr", "hermes", "claude-20261017223927", "claude", "wC:p1")
    assert argv == [
        "herdr",
        "--session",
        "hermes",
        "agent",
        "start",
        "claude-20261017223927",
        "--kind",
        "claude",
        "--pane",
        "wC:p1",
        "--timeout",
        "30000",
    ]
    assert argv[-2] == "--timeout"
    assert argv[-1] == AGENT_START_TIMEOUT_MS == "30000"
    assert isinstance(argv[-1], str)
    assert "--" not in argv
    assert "shell" not in argv
    assert AGENT_START_SUBPROCESS_TIMEOUT == 45.0


@pytest.mark.parametrize("name", ["Hermes Probe", "hermes probe session", "1demo", "has_underscore", "a" * 33])
def test_agent_start_argv_rejects_unsafe_name(name: str):
    with pytest.raises(PolicyError) as exc:
        agent_start_argv("herdr", "hermes", name, "hermes", "wC:p1")
    assert exc.value.reason == "invalid agent name"


def test_attach_command_hermes():
    assert attach_command("hermes") == "herdr session attach hermes"
    assert "--session" not in attach_command("hermes")


def test_attach_command_refuses_default():
    with pytest.raises(PolicyError) as exc:
        attach_command("default")
    assert exc.value.reason == "refusing session default"


def test_parse_workspace_created_scout_shape():
    stdout = """
    {"id":"cli:workspace:create","result":{
      "root_pane":{"agent_status":"unknown","cwd":"...","pane_id":"wC:p1","tab_id":"ignored-tab","workspace_id":"ignored-ws"},
      "tab":{"agent_status":"unknown","label":"1","number":1,"pane_count":1,"tab_id":"wC:t1","workspace_id":"wC"},
      "type":"workspace_created",
      "workspace":{"active_tab_id":"wC:t1","agent_status":"unknown","label":"homedashboard","number":8,"pane_count":1,"tab_count":1,"workspace_id":"wC"}
    }}
    """
    parsed = parse_workspace_created(stdout)
    assert parsed == {"workspace_id": "wC", "tab_id": "wC:t1", "pane_id": "wC:p1"}
    assert set(parsed) == {"workspace_id", "tab_id", "pane_id"}


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "not-json",
        "[]",
        "{}",
        '{"result":{}}',
        '{"result":{"workspace":{"workspace_id":"wC"},"tab":{"tab_id":"wC:t1"}}}',
        '{"result":{"workspace":{"workspace_id":"wC"},"tab":{"tab_id":"wC:t1"},"root_pane":{}}}',
        '{"result":{"workspace":{"workspace_id":"wC"},"tab":{"tab_id":"wC:t1"},"root_pane":{"pane_id":null}}}',
        '{"result":{"workspace":{"workspace_id":"wC"},"tab":{"tab_id":"wC:t1"},"root_pane":{"pane_id":""}}}',
        '{"result":{"workspace":{"workspace_id":"wC"},"tab":{"tab_id":"wC:t1"},"root_pane":{"pane_id":"-p1"}}}',
        '{"result":{"workspace":{"workspace_id":"wC"},"tab":{"tab_id":"wC:t1"},"root_pane":{"pane_id":"../x"}}}',
        '{"result":{"workspace":{"workspace_id":"wC"},"tab":{"tab_id":"wC:t1"},"root_pane":{"pane_id":"a;b"}}}',
        '{"result":{"workspace":{"workspace_id":1},"tab":{"tab_id":"wC:t1"},"root_pane":{"pane_id":"wC:p1"}}}',
        '{"result":{"tab":{"tab_id":"wC:t1"},"root_pane":{"pane_id":"wC:p1"}}}',
    ],
)
def test_parse_workspace_created_rejects_missing_or_unsafe_pane(stdout: str):
    with pytest.raises(PolicyError) as exc:
        parse_workspace_created(stdout)
    assert exc.value.reason == "herdr workspace create returned no pane"


def test_display_argv_quotes_for_display_only():
    assert display_argv(["herdr", "--label", "a;b"]) == "herdr --label 'a;b'"
    assert display_argv(["herdr", "--session", "hermes"]) == "herdr --session hermes"


def test_validate_session_id():
    good = "0123456789abcdef0123456789abcdef"
    assert validate_session_id(good) == good
    assert validate_session_id("a" * 32) == "a" * 32
    for bad in ("", "A" * 32, good.upper(), "g" * 32, good + "a", good[:-1], good[:8] + "-" + good[8:]):
        with pytest.raises(PolicyError) as exc:
            validate_session_id(bad)
        assert exc.value.reason == "invalid session id"


def test_module_has_no_subprocess_import_or_os_system():
    source_path = Path(sessions_policy.__file__)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "subprocess"
                assert not alias.name.startswith("subprocess")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module != "subprocess"
            assert not module.startswith("subprocess.")
            if module == "os":
                for alias in node.names:
                    assert alias.name != "system"
        elif isinstance(node, ast.Attribute) and node.attr == "system":
            owner = node.value
            if isinstance(owner, ast.Name):
                assert owner.id != "os"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "__import__" or not _call_mentions_subprocess(node)
        elif isinstance(node, ast.Attribute) and node.attr == "startswith":
            raise AssertionError("path checks must not use str.startswith")
    assert "import subprocess" not in source
    assert "os.system" not in source
    assert "shell=True" not in source
    assert "Popen" not in source


def _call_mentions_subprocess(node: ast.Call) -> bool:
    for arg in node.args:
        if isinstance(arg, ast.Constant) and arg.value == "subprocess":
            return True
    return False
