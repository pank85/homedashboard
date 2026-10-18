"""Read-only git project collector.

File reads only. Does not load the settings module or other collectors, does not spawn
a process, and does not parse packfiles. Unreadable directories are skipped.
This function does not raise; reasons are fixed literals.
"""

from __future__ import annotations

import os
import re
import stat
import zlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

_SKIP_NAMES = frozenset(
    {"node_modules", ".git", "vendor", "__pycache__", ".venv", "venv"}
)
_PROGRESS = (
    ("merge", "MERGE_HEAD"),
    ("rebase", "rebase-merge"),
    ("rebase", "rebase-apply"),
    ("cherry-pick", "CHERRY_PICK_HEAD"),
    ("revert", "REVERT_HEAD"),
    ("bisect", "BISECT_LOG"),
)
_SHA = re.compile(r"^[0-9a-fA-F]{40}$|^[0-9a-fA-F]{64}$")
_COMMITTER_TIME = re.compile(r" (\d+)(?:\s+[+-]\d{4})?\s*$")
_QUERY_TOKENS = ("token", "access_token", "password", "secret")
_SUBJECT_LIMIT = 120
_NOTE_EMPTY = "GIT_SCAN_ROOTS is empty"
_NOTE_UNREADABLE = "no readable git roots"
_REASON_ERROR = "collector error"
_REF_LIMIT = 8


def collect_git(
    *,
    roots: tuple[str, ...] | list[str],
    max_depth: int,
    max_repos: int,
) -> dict:
    """Scan roots for git work trees. Does not raise."""
    try:
        return _collect(roots=roots, max_depth=max_depth, max_repos=max_repos)
    except Exception:
        return _error_payload()


def _collect(
    *,
    roots: tuple[str, ...] | list[str],
    max_depth: int,
    max_repos: int,
) -> dict:
    if not isinstance(roots, (tuple, list)):
        return _error_payload()
    if not roots:
        return _empty_payload()
    root_list = [item for item in roots if isinstance(item, str)]
    if not root_list:
        return _empty_payload()

    cap = max_repos if isinstance(max_repos, int) and max_repos > 0 else 0
    depth_limit = max_depth if isinstance(max_depth, int) else 0
    state: dict = {
        "projects": [],
        "seen": set(),
        "skip": set(),
        "truncated": False,
    }
    readable = 0
    for root in root_list:
        if state["truncated"]:
            break
        if cap > 0 and len(state["projects"]) >= cap:
            state["truncated"] = True
            break
        if not _readable_dir(root):
            continue
        readable += 1
        _walk(root, depth_limit, cap, state)
    note = _NOTE_UNREADABLE if readable == 0 else ""
    return {
        "available": True,
        "reason": "",
        "note": note,
        "scanned": True,
        "roots": root_list,
        "truncated": state["truncated"],
        "refreshed_at": _timestamp(),
        "projects": state["projects"],
    }


def _empty_payload() -> dict:
    return {
        "available": True,
        "reason": "",
        "note": _NOTE_EMPTY,
        "scanned": False,
        "roots": [],
        "truncated": False,
        "refreshed_at": "",
        "projects": [],
    }


def _error_payload() -> dict:
    return {
        "available": False,
        "reason": _REASON_ERROR,
        "note": "",
        "scanned": False,
        "roots": [],
        "truncated": False,
        "refreshed_at": _timestamp(),
        "projects": [],
    }


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _readable_dir(path: str) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        return False
    try:
        with os.scandir(path):
            return True
    except OSError:
        return False


def _walk(root: str, max_depth: int, cap: int, state: dict) -> None:
    stack = [(os.path.normpath(root), 0)]
    while stack:
        path, depth = stack.pop()
        if path in state["skip"]:
            continue
        if cap > 0 and len(state["projects"]) >= cap:
            state["truncated"] = True
            return
        if _consider(path, state, cap) == "stop":
            state["truncated"] = True
            return
        if depth >= max_depth:
            continue
        children = _list_children(path, state["skip"])
        if len(state["projects"]) >= cap and children:
            state["truncated"] = True
            return
        for child in reversed(children):
            stack.append((child, depth + 1))


def _consider(path: str, state: dict, cap: int) -> str:
    meta = os.path.join(path, ".git")
    try:
        info = os.lstat(meta)
    except OSError:
        return "skip"
    if stat.S_ISLNK(info.st_mode):
        return "skip"
    gitdir = ""
    if stat.S_ISDIR(info.st_mode):
        gitdir = meta
    elif stat.S_ISREG(info.st_mode):
        gitdir = _gitdir_from_file(path, meta)
    else:
        return "skip"
    if gitdir:
        state["skip"].add(os.path.normpath(gitdir))
    stored = os.path.normpath(path)
    if stored in state["seen"]:
        return "skip"
    if len(state["projects"]) >= cap:
        return "stop"
    state["seen"].add(stored)
    state["projects"].append(_load_project(stored, gitdir))
    if len(state["projects"]) >= cap:
        return "stop"
    return "added"


def _list_children(path: str, skip: set[str]) -> list[str]:
    try:
        with os.scandir(path) as scan:
            entries = list(scan)
    except OSError:
        return []
    children: list[str] = []
    for entry in entries:
        if entry.name in _SKIP_NAMES:
            continue
        try:
            # follow_symlinks=False: symlink directories are not descended into.
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        child = os.path.normpath(entry.path)
        if child in skip:
            continue
        children.append(child)
    children.sort()
    return children


def _gitdir_from_file(work_tree: str, git_file: str) -> str:
    text = _read_text(git_file)
    if not text:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("gitdir:"):
            continue
        raw = stripped[len("gitdir:") :].strip()
        if not raw:
            return ""
        if os.path.isabs(raw):
            return os.path.normpath(raw)
        return os.path.normpath(os.path.join(work_tree, raw))
    return ""


def _load_project(work_tree: str, gitdir: str) -> dict:
    branch = ""
    detached = False
    head = ""
    bases = _git_bases(gitdir)
    if gitdir:
        head_text = _read_text(os.path.join(gitdir, "HEAD"))
        if head_text:
            branch, detached, ref_or_sha = _parse_head(head_text)
            if detached:
                head = ref_or_sha
            elif ref_or_sha:
                head = _resolve_sha(bases, ref_or_sha)
    remote_url = ""
    upstream = ""
    config_text = _first_text(bases, "config")
    if config_text:
        remote_url, upstream = _from_config(config_text, branch)
    if head:
        subject, commit_at, available = _read_loose_commit(bases, head)
    else:
        subject, commit_at, available = "", "", False
    return {
        "name": os.path.basename(work_tree) or work_tree,
        "path": work_tree,
        "branch": branch,
        "detached": detached,
        "head": head,
        "head_short": head[:7] if head else "",
        "upstream": upstream,
        "remote_url": remote_url,
        "in_progress": _in_progress(gitdir),
        "commit_subject": subject,
        "commit_at": commit_at,
        "object_available": available,
    }


def _parse_head(text: str) -> tuple[str, bool, str]:
    lines = text.splitlines()
    line = lines[0].strip() if lines else ""
    if line.startswith("ref:"):
        ref = line[4:].strip()
        if ref.startswith("refs/heads/"):
            branch = ref[len("refs/heads/") :]
            if branch:
                return branch, False, ref
        return "", False, ref if _safe_ref(ref) else ""
    if _SHA.fullmatch(line):
        return "", True, line.lower()
    return "", False, ""


def _safe_ref(ref: str) -> bool:
    if not ref or ref.startswith("/") or "\\" in ref:
        return False
    parts = ref.split("/")
    if ".." in parts or "" in parts:
        return False
    return parts[0] == "refs"


def _resolve_sha(bases: list[str], ref: str, seen: set[str] | None = None) -> str:
    if seen is None:
        seen = set()
    if ref in seen or len(seen) >= _REF_LIMIT or not _safe_ref(ref):
        return ""
    seen.add(ref)
    for base in bases:
        text = _read_text(os.path.join(base, ref))
        if not text:
            continue
        line = text.splitlines()[0].strip()
        if _SHA.fullmatch(line):
            return line.lower()
        if line.startswith("ref:"):
            return _resolve_sha(bases, line[4:].strip(), seen)
    for base in bases:
        sha = _packed_ref(base, ref)
        if sha:
            return sha
    return ""


def _packed_ref(base: str, ref: str) -> str:
    """Read a text packed-refs list. This is not packfile parsing."""
    text = _read_text(os.path.join(base, "packed-refs"))
    if not text:
        return ""
    for line in text.splitlines():
        if not line or line[0] in "#^":
            continue
        sha, sep, name = line.partition(" ")
        if not sep:
            continue
        if name.strip() == ref and _SHA.fullmatch(sha.strip()):
            return sha.strip().lower()
    return ""


def _read_loose_commit(bases: list[str], sha: str) -> tuple[str, str, bool]:
    if not _SHA.fullmatch(sha):
        return "", "", False
    relative = os.path.join("objects", sha[:2], sha[2:])
    for base in bases:
        data = _read_bytes(os.path.join(base, relative))
        if data is None:
            continue
        try:
            payload = zlib.decompress(data)
        except zlib.error:
            return "", "", False
        parsed = _parse_commit(payload)
        if parsed is None:
            return "", "", False
        subject, commit_at = parsed
        return subject, commit_at, True
    return "", "", False


def _parse_commit(payload: bytes) -> tuple[str, str] | None:
    nul = payload.find(b"\0")
    if nul < 0 or not payload[:nul].startswith(b"commit "):
        return None
    text = payload[nul + 1 :].decode("utf-8", errors="replace")
    header, sep, message = text.partition("\n\n")
    subject = ""
    if sep and message:
        lines = message.splitlines()
        if lines:
            subject = _strip_controls(lines[0])[:_SUBJECT_LIMIT]
    commit_at = ""
    for line in header.splitlines():
        if line.startswith("committer "):
            commit_at = _committer_time(line)
            break
    return subject, commit_at


def _committer_time(line: str) -> str:
    match = _COMMITTER_TIME.search(line)
    if not match:
        return ""
    try:
        stamp = int(match.group(1))
    except ValueError:
        return ""
    if stamp < 0:
        return ""
    try:
        return datetime.fromtimestamp(stamp, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (OverflowError, OSError, ValueError):
        return ""


def _strip_controls(text: str) -> str:
    return "".join(ch for ch in text if ord(ch) >= 32 and ord(ch) != 127)


def _git_bases(gitdir: str) -> list[str]:
    if not gitdir:
        return []
    bases = [gitdir]
    common = _commondir(gitdir)
    if common and os.path.normpath(common) != os.path.normpath(gitdir):
        bases.append(common)
    return bases


def _commondir(gitdir: str) -> str | None:
    text = _read_text(os.path.join(gitdir, "commondir"))
    if not text:
        return None
    raw = text.splitlines()[0].strip()
    if not raw:
        return None
    if os.path.isabs(raw):
        return os.path.normpath(raw)
    return os.path.normpath(os.path.join(gitdir, raw))


def _first_text(bases: list[str], name: str) -> str | None:
    for base in bases:
        text = _read_text(os.path.join(base, name))
        if text is not None:
            return text
    return None


def _from_config(text: str, branch: str) -> tuple[str, str]:
    remotes: list[tuple[str, str]] = []
    branch_keys: dict[str, str] | None = None
    for name, subsection, keys in _parse_config(text):
        if name == "remote" and subsection and "url" in keys:
            remotes.append((subsection, keys["url"]))
        if branch and name == "branch" and subsection == branch:
            branch_keys = keys
    first = ""
    origin = ""
    for remote_name, url in remotes:
        if not first:
            first = url
        if remote_name == "origin" and not origin:
            origin = url
    upstream = ""
    if branch_keys:
        remote = branch_keys.get("remote", "")
        merge = branch_keys.get("merge", "")
        base = os.path.basename(merge.rstrip("/\\")) if merge else ""
        if remote == ".":
            upstream = base
        elif remote and base:
            upstream = f"{remote}/{base}"
    return _redact_remote_url(origin or first), upstream


def _parse_config(text: str) -> list[tuple[str, str | None, dict[str, str]]]:
    sections: list[tuple[str, str | None, dict[str, str]]] = []
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            name, subsection = _parse_section(line[1:-1].strip())
            current = {}
            sections.append((name, subsection, current))
            continue
        if current is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        current[key.strip().lower()] = _unquote(value.strip())
    return sections


def _parse_section(inner: str) -> tuple[str, str | None]:
    name, sep, rest = inner.partition(" ")
    if not sep:
        return name.lower(), None
    rest = rest.strip()
    if len(rest) >= 2 and rest[0] == '"' and rest[-1] == '"':
        rest = rest[1:-1]
    return name.lower(), rest


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        inner = value[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    return value


def _in_progress(gitdir: str) -> list[str]:
    if not gitdir:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for label, name in _PROGRESS:
        if label in seen:
            continue
        if os.path.lexists(os.path.join(gitdir, name)):
            found.append(label)
            seen.add(label)
    return found


def _redact_remote_url(url: str) -> str:
    text = url.strip()
    if not text:
        return ""
    if "://" in text:
        redacted = _redact_scheme_url(text)
    else:
        redacted = _redact_scp_url(text)
    if _leaks_userinfo(redacted):
        return ""
    return redacted


def _redact_scp_url(text: str) -> str:
    at = text.find("@")
    if at < 0 or ":" not in text[:at]:
        return text
    return text[at + 1 :]


def _redact_scheme_url(text: str) -> str:
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return ""
    if (parts.username or parts.password) and not parts.hostname:
        return ""
    query = "" if _query_has_secret(parts.query) else parts.query
    return urlunsplit(
        (parts.scheme, _netloc(parts.hostname, port), parts.path, query, parts.fragment)
    )


def _query_has_secret(query: str) -> bool:
    if not query:
        return False
    lowered = query.casefold()
    return any(token in lowered for token in _QUERY_TOKENS)


def _netloc(host: str | None, port: int | None) -> str:
    if not host:
        return ""
    if ":" in host:
        host = f"[{host}]"
    if port is None:
        return host
    return f"{host}:{port}"


def _leaks_userinfo(text: str) -> bool:
    if not text:
        return False
    if "://" not in text:
        at = text.find("@")
        return at > 0 and ":" in text[:at]
    try:
        parts = urlsplit(text)
    except ValueError:
        return True
    return bool(parts.username or parts.password)


def _read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_bytes(path: str) -> bytes | None:
    try:
        return Path(path).read_bytes()
    except OSError:
        return None
