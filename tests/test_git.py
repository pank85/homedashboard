import ast
import hashlib
import inspect
import json
import os
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from app.collectors.git import collect_git

STAMP = 1_713_340_800
_SKIP_NAMES = ("node_modules", "vendor", "__pycache__", ".venv", "venv")


def _when(stamp: int = STAMP) -> str:
    return datetime.fromtimestamp(stamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _commit(message: str, stamp: int = STAMP) -> tuple[str, bytes]:
    body = (
        f"tree {'a' * 40}\n"
        f"author Ada <ada@example.com> {stamp} +0000\n"
        f"committer Ada <ada@example.com> {stamp} +0000\n"
        "\n"
        f"{message}\n"
    ).encode("utf-8")
    payload = f"commit {len(body)}".encode("ascii") + b"\0" + body
    return hashlib.sha1(payload).hexdigest(), zlib.compress(payload)


def _write_loose(gitdir: Path, sha: str, blob: bytes) -> None:
    path = gitdir / "objects" / sha[:2] / sha[2:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)


def _repo(
    path: Path,
    *,
    branch: str = "main",
    message: str = "Add dashboard",
    detached: bool = False,
    remote: str | None = "https://github.com/org/repo.git",
    tracking: bool = True,
    stamp: int = STAMP,
    write_object: bool = True,
) -> str:
    git = path / ".git"
    git.mkdir(parents=True, exist_ok=True)
    sha, blob = _commit(message, stamp)
    if write_object:
        _write_loose(git, sha, blob)
    if detached:
        (git / "HEAD").write_text(sha + "\n", encoding="utf-8")
    else:
        (git / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
        ref = git / "refs" / "heads" / branch
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text(sha + "\n", encoding="utf-8")
    lines: list[str] = []
    if remote is not None:
        lines.append('[remote "origin"]')
        lines.append(f"\turl = {remote}")
    if tracking and not detached and remote is not None:
        lines.append(f'[branch "{branch}"]')
        lines.append("\tremote = origin")
        lines.append(f"\tmerge = refs/heads/{branch}")
    if lines:
        (git / "config").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sha


def _by_name(result: dict, name: str) -> dict:
    matches = [row for row in result["projects"] if row["name"] == name]
    assert len(matches) == 1
    return matches[0]


def test_empty_roots_does_not_walk(monkeypatch):
    calls: list[object] = []

    def boom(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("filesystem walk")

    monkeypatch.setattr("app.collectors.git.os.scandir", boom)
    monkeypatch.setattr("app.collectors.git.os.lstat", boom)
    monkeypatch.setattr("app.collectors.git.os.listdir", boom)
    monkeypatch.setattr("app.collectors.git.Path.read_text", boom)
    monkeypatch.setattr("app.collectors.git.Path.read_bytes", boom)

    for roots in ((), []):
        result = collect_git(roots=roots, max_depth=3, max_repos=40)
        assert result["available"] is True
        assert result["scanned"] is False
        assert result["note"] == "GIT_SCAN_ROOTS is empty"
        assert result["projects"] == []
        assert result["roots"] == []
        assert result["truncated"] is False
        assert result["reason"] == ""
        assert result["refreshed_at"] == ""
    assert calls == []


def test_keyword_only_signature():
    signature = inspect.signature(collect_git)
    assert list(signature.parameters) == ["roots", "max_depth", "max_repos"]
    for param in signature.parameters.values():
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
    with pytest.raises(TypeError):
        collect_git((), 3, 40)  # type: ignore[misc]


def test_repo_with_branch_and_loose_commit(tmp_path):
    repo = tmp_path / "dashboard"
    sha = _repo(repo, message="Add dashboard")
    (repo / ".git" / "MERGE_HEAD").write_text(sha + "\n", encoding="utf-8")
    (repo / ".git" / "rebase-merge").mkdir()

    result = collect_git(roots=(str(tmp_path),), max_depth=2, max_repos=40)
    project = _by_name(result, "dashboard")

    assert result["available"] is True
    assert result["scanned"] is True
    assert result["truncated"] is False
    assert result["reason"] == ""
    assert result["note"] == ""
    assert project == {
        "name": "dashboard",
        "path": str(repo),
        "branch": "main",
        "detached": False,
        "head": sha,
        "head_short": sha[:7],
        "upstream": "origin/main",
        "remote_url": "https://github.com/org/repo.git",
        "in_progress": ["merge", "rebase"],
        "commit_subject": "Add dashboard",
        "commit_at": _when(),
        "object_available": True,
    }


def test_detached_head(tmp_path):
    repo = tmp_path / "detached"
    sha = _repo(repo, detached=True, message="Detached subject")

    result = collect_git(roots=[str(tmp_path)], max_depth=2, max_repos=40)
    project = _by_name(result, "detached")

    assert project["branch"] == ""
    assert project["detached"] is True
    assert project["head"] == sha
    assert project["head_short"] == sha[:7]
    assert project["upstream"] == ""
    assert project["commit_subject"] == "Detached subject"
    assert project["object_available"] is True
    assert project["remote_url"] == "https://github.com/org/repo.git"


def test_worktree_git_file(tmp_path):
    scan = tmp_path / "scan"
    linked = scan / "linked"
    linked.mkdir(parents=True)
    external = tmp_path / "repo.git"
    external.mkdir()
    (linked / ".git").write_text("gitdir: ../../repo.git\n", encoding="utf-8")
    sha, blob = _commit("linked subject")
    _write_loose(external, sha, blob)
    (external / "HEAD").write_text("ref: refs/heads/feature\n", encoding="utf-8")
    ref = external / "refs" / "heads" / "feature"
    ref.parent.mkdir(parents=True)
    ref.write_text(sha + "\n", encoding="utf-8")
    (external / "config").write_text(
        "\n".join(
            [
                '[remote "origin"]',
                "\turl = https://github.com/org/linked.git",
                '[branch "feature"]',
                "\tremote = origin",
                "\tmerge = refs/heads/feature",
                "",
            ]
        ),
        encoding="utf-8",
    )

    inner = scan / "inner"
    inner.mkdir()
    gitmeta = inner / "gitmeta"
    gitmeta.mkdir()
    (inner / ".git").write_text("gitdir: gitmeta\n", encoding="utf-8")
    common = tmp_path / "common.git"
    common.mkdir()
    inner_sha, inner_blob = _commit("inner subject")
    _write_loose(common, inner_sha, inner_blob)
    (gitmeta / "commondir").write_text(
        os.path.relpath(common, gitmeta) + "\n", encoding="utf-8"
    )
    (gitmeta / "HEAD").write_text("ref: refs/heads/topic\n", encoding="utf-8")
    common_ref = common / "refs" / "heads" / "topic"
    common_ref.parent.mkdir(parents=True)
    common_ref.write_text(inner_sha + "\n", encoding="utf-8")
    (common / "config").write_text(
        "\n".join(
            [
                '[remote "origin"]',
                "\turl = git@github.com:org/inner.git",
                '[branch "topic"]',
                "\tremote = origin",
                "\tmerge = refs/heads/topic",
                "",
            ]
        ),
        encoding="utf-8",
    )
    sneak = gitmeta / "sneak"
    sneak.mkdir()
    (sneak / ".git").mkdir()
    (sneak / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    nested = inner / "nested"
    _repo(nested, branch="nested", remote=None, tracking=False)

    result = collect_git(roots=(str(scan),), max_depth=3, max_repos=40)
    names = [row["name"] for row in result["projects"]]
    assert "linked" in names
    assert "inner" in names
    assert "nested" in names
    assert "sneak" not in names
    assert "gitmeta" not in names
    assert "repo.git" not in names

    linked_row = _by_name(result, "linked")
    assert linked_row["branch"] == "feature"
    assert linked_row["detached"] is False
    assert linked_row["head"] == sha
    assert linked_row["head_short"] == sha[:7]
    assert linked_row["upstream"] == "origin/feature"
    assert linked_row["remote_url"] == "https://github.com/org/linked.git"
    assert linked_row["commit_subject"] == "linked subject"
    assert linked_row["object_available"] is True
    assert os.path.normpath(os.path.join(str(linked), "../../repo.git")) == str(external)

    inner_row = _by_name(result, "inner")
    assert inner_row["branch"] == "topic"
    assert inner_row["head"] == inner_sha
    assert inner_row["upstream"] == "origin/topic"
    assert inner_row["remote_url"] == "git@github.com:org/inner.git"
    assert inner_row["object_available"] is True
    assert inner_row["commit_subject"] == "inner subject"


def test_redacts_remote_urls(tmp_path):
    cases = {
        "userinfo": (
            "https://user:token@github.com/org/repo.git",
            "https://github.com/org/repo.git",
        ),
        "token_user": (
            "https://token@github.com/org/repo.git",
            "https://github.com/org/repo.git",
        ),
        "ssh_userinfo": (
            "ssh://user:pass@example.com/repo.git",
            "ssh://example.com/repo.git",
        ),
        "query_token": (
            "https://github.com/org/repo.git?token=abc",
            "https://github.com/org/repo.git",
        ),
        "query_access": (
            "https://github.com/org/repo.git?access_token=abc",
            "https://github.com/org/repo.git",
        ),
        "query_password": (
            "https://github.com/org/repo.git?password=abc",
            "https://github.com/org/repo.git",
        ),
        "query_secret": (
            "https://github.com/org/repo.git?secret=abc",
            "https://github.com/org/repo.git",
        ),
        "query_keep": (
            "https://github.com/org/repo.git?foo=bar",
            "https://github.com/org/repo.git?foo=bar",
        ),
        "scp_clean": (
            "git@github.com:org/repo.git",
            "git@github.com:org/repo.git",
        ),
        "scp_secret": (
            "user:secret@host:org/repo.git",
            "host:org/repo.git",
        ),
        "both": (
            '"https://user:token@github.com/org/repo.git?access_token=xyz"',
            "https://github.com/org/repo.git",
        ),
        "with_port": (
            "https://user:token@github.com:8443/org/repo.git",
            "https://github.com:8443/org/repo.git",
        ),
    }
    for name, (raw, _expected) in cases.items():
        _repo(tmp_path / name, remote=raw, tracking=False)

    result = collect_git(roots=(str(tmp_path),), max_depth=2, max_repos=40)
    assert result["truncated"] is False
    by_name = {row["name"]: row for row in result["projects"]}
    assert set(by_name) == set(cases)
    for name, (_raw, expected) in cases.items():
        assert by_name[name]["remote_url"] == expected

    dumped = json.dumps(result)
    for secret in (
        "user:token",
        "token@",
        "user:pass",
        "token=abc",
        "access_token",
        "password=abc",
        "secret=abc",
        "user:secret",
        "token=xyz",
    ):
        assert secret not in dumped
    assert result["reason"] == ""
    assert result["note"] == ""


def test_packed_object_leaves_subject_empty(tmp_path):
    repo = tmp_path / "packed"
    sha = _repo(repo, message="should not be read", write_object=False)
    pack = repo / ".git" / "objects" / "pack"
    pack.mkdir(parents=True)
    (pack / "pack-test.pack").write_bytes(b"PACK\x00\x00\x00\x02garbage")
    (pack / "pack-test.idx").write_bytes(b"\xff\x74Oc")

    result = collect_git(roots=(str(tmp_path),), max_depth=2, max_repos=40)
    project = _by_name(result, "packed")

    assert project["branch"] == "main"
    assert project["head"] == sha
    assert project["head_short"] == sha[:7]
    assert project["upstream"] == "origin/main"
    assert project["commit_subject"] == ""
    assert project["commit_at"] == ""
    assert project["object_available"] is False
    assert result["available"] is True


def test_packed_refs_yield_sha_without_object(tmp_path):
    repo = tmp_path / "refs-packed"
    git = repo / ".git"
    git.mkdir(parents=True)
    sha, _blob = _commit("packed ref")
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "packed-refs").write_text(
        f"# pack-refs with: peeled fully-peeled sorted\n{sha} refs/heads/main\n^{sha}\n",
        encoding="utf-8",
    )
    (git / "config").write_text(
        "\n".join(
            [
                '[remote "origin"]',
                "\turl = git@github.com:org/repo.git",
                '[branch "main"]',
                "\tremote = origin",
                "\tmerge = refs/heads/main",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = collect_git(roots=(str(tmp_path),), max_depth=1, max_repos=5)
    project = _by_name(result, "refs-packed")
    assert project["branch"] == "main"
    assert project["detached"] is False
    assert project["head"] == sha
    assert project["upstream"] == "origin/main"
    assert project["remote_url"] == "git@github.com:org/repo.git"
    assert project["commit_subject"] == ""
    assert project["object_available"] is False


def test_corrupt_loose_object_does_not_raise(tmp_path):
    repo = tmp_path / "corrupt"
    sha = _repo(repo, write_object=False)
    path = repo / ".git" / "objects" / sha[:2] / sha[2:]
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not zlib")

    result = collect_git(roots=(str(tmp_path),), max_depth=1, max_repos=5)
    project = _by_name(result, "corrupt")
    assert project["head"] == sha
    assert project["commit_subject"] == ""
    assert project["object_available"] is False


def test_subject_strips_controls_and_limits_length(tmp_path):
    repo = tmp_path / "subject"
    _repo(repo, message="hello\x07world\x1b" + ("A" * 200), remote=None, tracking=False)

    result = collect_git(roots=(str(tmp_path),), max_depth=1, max_repos=5)
    project = _by_name(result, "subject")
    assert project["object_available"] is True
    assert project["commit_subject"] == ("helloworld" + ("A" * 200))[:120]
    assert len(project["commit_subject"]) == 120
    assert "\x07" not in project["commit_subject"]


def test_symlink_dir_skipped(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _repo(root / "real")
    outside = tmp_path / "outside"
    _repo(outside)
    (root / "link").symlink_to(outside, target_is_directory=True)
    (root / "alias").symlink_to(root / "real", target_is_directory=True)

    result = collect_git(roots=(str(root),), max_depth=2, max_repos=10)
    assert [row["name"] for row in result["projects"]] == ["real"]
    assert all("outside" not in row["path"] for row in result["projects"])


def test_skip_dir_names_and_max_depth(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _repo(root / "kept")
    for name in _SKIP_NAMES:
        _repo(root / name / "secret")
    _repo(root / "a" / "b" / "deep")

    shallow = collect_git(roots=(str(root),), max_depth=1, max_repos=20)
    assert [row["name"] for row in shallow["projects"]] == ["kept"]

    deeper = collect_git(roots=(str(root),), max_depth=3, max_repos=20)
    assert [row["name"] for row in deeper["projects"]] == ["deep", "kept"]
    assert all(row["name"] != "secret" for row in deeper["projects"])


def test_max_repos_sets_truncated(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    for name in ("a", "b", "c"):
        _repo(root / name, remote=None, tracking=False)

    capped = collect_git(roots=(str(root),), max_depth=2, max_repos=2)
    assert capped["truncated"] is True
    assert [row["name"] for row in capped["projects"]] == ["a", "b"]

    full = collect_git(roots=(str(root),), max_depth=2, max_repos=10)
    assert full["truncated"] is False
    assert [row["name"] for row in full["projects"]] == ["a", "b", "c"]


def test_permission_error_does_not_raise(tmp_path, monkeypatch):
    root = tmp_path / "locked"
    root.mkdir()
    (root / "child").mkdir()
    if os.geteuid() != 0:
        root.chmod(0)
        try:
            try:
                os.scandir(root)
                denied = False
            except PermissionError:
                denied = True
            result = collect_git(roots=(str(root),), max_depth=3, max_repos=40)
            assert result["available"] is True
            assert result["scanned"] is True
            assert result["reason"] == ""
            assert "Permission" not in json.dumps(result)
            if denied:
                assert result["projects"] == []
                assert result["note"] == "no readable git roots"
                assert result["roots"] == [str(root)]
        finally:
            root.chmod(0o755)

    sibling = tmp_path / "sibling"
    sibling.mkdir()
    _repo(sibling / "ok", remote=None, tracking=False)
    blocked = sibling / "blocked"
    blocked.mkdir()

    def deny(path):
        if os.path.basename(os.path.normpath(path)) == "blocked":
            raise PermissionError(13, "SECRET_PERMISSION_DETAIL", str(path))
        return orig_scandir(path)

    orig_scandir = os.scandir
    monkeypatch.setattr("app.collectors.git.os.scandir", deny)
    result = collect_git(roots=[str(sibling)], max_depth=2, max_repos=10)
    assert result["available"] is True
    assert _by_name(result, "ok")["name"] == "ok"
    assert "SECRET_PERMISSION_DETAIL" not in json.dumps(result)
    assert result["reason"] == ""

    lone = tmp_path / "lone"
    lone.mkdir()

    def always_deny(path):
        raise PermissionError(13, "SECRET_PERMISSION_DETAIL", str(path))

    monkeypatch.setattr("app.collectors.git.os.scandir", always_deny)
    denied_result = collect_git(roots=(str(lone),), max_depth=2, max_repos=5)
    assert denied_result["available"] is True
    assert denied_result["scanned"] is True
    assert denied_result["projects"] == []
    assert denied_result["note"] == "no readable git roots"
    assert denied_result["reason"] == ""
    assert "SECRET_PERMISSION_DETAIL" not in json.dumps(denied_result)


def test_unreadable_root_does_not_hide_readable_root(tmp_path):
    missing = tmp_path / "missing"
    present = tmp_path / "present"
    _repo(present / "proj", remote=None, tracking=False)

    result = collect_git(
        roots=(str(missing), str(present)),
        max_depth=2,
        max_repos=10,
    )
    assert result["available"] is True
    assert result["scanned"] is True
    assert result["note"] == ""
    assert result["roots"] == [str(missing), str(present)]
    assert [row["name"] for row in result["projects"]] == ["proj"]


def test_upstream_dot_remote_and_first_remote(tmp_path):
    dot = tmp_path / "dot"
    git = dot / ".git"
    git.mkdir(parents=True)
    sha, blob = _commit("dot")
    _write_loose(git, sha, blob)
    (git / "HEAD").write_text("ref: refs/heads/feature/foo\n", encoding="utf-8")
    ref = git / "refs" / "heads" / "feature" / "foo"
    ref.parent.mkdir(parents=True)
    ref.write_text(sha + "\n", encoding="utf-8")
    (git / "config").write_text(
        "\n".join(
            [
                '[remote "upstream"]',
                "\turl = git@github.com:org/dot.git",
                '[branch "feature/foo"]',
                "\tremote = .",
                "\tmerge = refs/heads/feature/foo",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = collect_git(roots=(str(tmp_path),), max_depth=1, max_repos=5)
    project = _by_name(result, "dot")
    assert project["branch"] == "feature/foo"
    assert project["upstream"] == "foo"
    assert project["remote_url"] == "git@github.com:org/dot.git"
    assert project["head"] == sha


def test_in_progress_marker_order(tmp_path):
    repo = tmp_path / "flags"
    _repo(repo, remote=None, tracking=False)
    git = repo / ".git"
    (git / "BISECT_LOG").write_text("bisect\n", encoding="utf-8")
    (git / "REVERT_HEAD").write_text("abc\n", encoding="utf-8")
    (git / "CHERRY_PICK_HEAD").write_text("abc\n", encoding="utf-8")
    (git / "rebase-apply").mkdir()
    (git / "MERGE_HEAD").write_text("abc\n", encoding="utf-8")

    result = collect_git(roots=(str(tmp_path),), max_depth=1, max_repos=5)
    assert _by_name(result, "flags")["in_progress"] == [
        "merge",
        "rebase",
        "cherry-pick",
        "revert",
        "bisect",
    ]


def test_does_not_import_subprocess_or_settings():
    source_path = ROOT / "app" / "collectors" / "git.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    assert "subprocess" not in modules
    assert not any(name.startswith("subprocess.") for name in modules)
    assert not any("settings" in name for name in modules)
    assert not any(name.startswith("app.collectors.") for name in modules)
    assert "import subprocess" not in source
    assert "app.settings" not in source
    assert "str(exc)" not in source

    import app.collectors.git as gitmod

    assert "subprocess" not in gitmod.__dict__
    assert not hasattr(gitmod, "settings")
