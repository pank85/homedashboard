"""Session mutation validation and herdr argv builders.

This module never spawns a process, opens a socket, or invokes a shell.
Callers execute the returned argv lists themselves.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path

AGENT_START_KINDS: tuple[str, ...] = (
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

LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
PANE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,63}$")
SESSION_ID_RE = re.compile(r"^[a-f0-9]{32}$")
AGENT_START_TIMEOUT_MS = "30000"
AGENT_START_SUBPROCESS_TIMEOUT = 45.0

_NO_PANE = "herdr workspace create returned no pane"


class PolicyError(Exception):
    """Rejected input. ``reason`` is the exact client-facing string."""

    reason: str

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def token_status(expected: str, authorization: str | None, form_token: str | None) -> str:
    """Return ``unset``, ``ok``, or ``invalid``.

    A blank expected token is ``unset`` and the provided credential is ignored.
    A present Authorization header must be ``Bearer`` (scheme case-insensitive).
    A bad or non-Bearer header is ``invalid`` and does not fall back to the form token.
    Digests are compared so unequal credential lengths stay the same width.
    """
    secret = expected.strip()
    if secret == "":
        return "unset"
    candidate = _credential(authorization, form_token)
    if candidate == "":
        return "invalid"
    expected_digest = hashlib.sha256(secret.encode("utf-8")).digest()
    provided_digest = hashlib.sha256(candidate.encode("utf-8")).digest()
    if hmac.compare_digest(expected_digest, provided_digest):
        return "ok"
    return "invalid"


def validate_session_name(name: str) -> str:
    cleaned = name.strip()
    if cleaned.casefold() == "default":
        raise PolicyError("refusing session default")
    if SESSION_NAME_RE.fullmatch(cleaned) is None:
        raise PolicyError("invalid HERDR_SESSION")
    return cleaned


def validate_kind(kind: str) -> str:
    if kind not in AGENT_START_KINDS:
        raise PolicyError("unknown agent kind")
    return kind


def validate_label(label: str | None, *, kind: str, now: datetime | None = None) -> str:
    if label is None or label.strip() == "":
        moment = _as_utc(now)
        return f"{kind}-{moment.strftime('%Y%m%d%H%M%S')}"
    if LABEL_RE.fullmatch(label) is None:
        raise PolicyError("invalid label")
    return label


def validate_cwd(cwd: str, allowlist: tuple[str, ...]) -> str:
    """Return the resolved cwd if it is the prefix or a descendant of one.

    The lexical path must be absolute before resolve, so a relative ``../x``
    cannot land inside an allowlist entry by normalization. Allowlist prefixes
    are resolved with ``strict=False``. Membership is path equality or
    ``relative_to``, never a string prefix (``/proj`` must not allow ``/proj-evil``).
    An empty allowlist is rejected before any filesystem access.
    """
    configured = tuple(item.strip() for item in allowlist if item.strip())
    if not configured:
        raise PolicyError("CHAT_CWD_ALLOWLIST unset")
    try:
        expanded = Path(cwd).expanduser()
    except ValueError as exc:
        raise PolicyError("cwd not readable") from exc
    if not expanded.is_absolute():
        raise PolicyError("cwd must be absolute")
    try:
        resolved = expanded.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PolicyError("cwd does not exist") from exc
    except OSError as exc:
        raise PolicyError("cwd not readable") from exc
    except ValueError as exc:
        raise PolicyError("cwd not readable") from exc
    for raw_prefix in configured:
        try:
            prefix_path = Path(raw_prefix).expanduser()
        except ValueError:
            continue
        if not prefix_path.is_absolute():
            continue
        try:
            prefix = prefix_path.resolve(strict=False)
        except (OSError, ValueError):
            continue
        if _is_under(resolved, prefix):
            return str(resolved)
    raise PolicyError("cwd outside allowlist")


def validate_session_id(session_id: str) -> str:
    if SESSION_ID_RE.fullmatch(session_id) is None:
        raise PolicyError("invalid session id")
    return session_id


def workspace_create_argv(bin: str, session: str, cwd: str, label: str) -> list[str]:
    return [
        bin,
        "--session",
        session,
        "workspace",
        "create",
        "--cwd",
        cwd,
        "--label",
        label,
        "--no-focus",
    ]


def agent_start_argv(bin: str, session: str, name: str, kind: str, pane_id: str) -> list[str]:
    return [
        bin,
        "--session",
        session,
        "agent",
        "start",
        name,
        "--kind",
        kind,
        "--pane",
        pane_id,
        "--timeout",
        AGENT_START_TIMEOUT_MS,
    ]


def attach_command(session: str) -> str:
    cleaned = validate_session_name(session)
    return f"herdr session attach {cleaned}"


def parse_workspace_created(stdout: str) -> dict[str, str]:
    """Read workspace, tab, and root pane ids from one JSON object."""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise PolicyError(_NO_PANE) from exc
    workspace_id = _string_at(payload, "result", "workspace", "workspace_id")
    tab_id = _string_at(payload, "result", "tab", "tab_id")
    pane_id = _string_at(payload, "result", "root_pane", "pane_id")
    if pane_id is None or PANE_ID_RE.fullmatch(pane_id) is None:
        raise PolicyError(_NO_PANE)
    if workspace_id is None or tab_id is None:
        raise PolicyError(_NO_PANE)
    return {
        "workspace_id": workspace_id,
        "tab_id": tab_id,
        "pane_id": pane_id,
    }


def display_argv(argv: list[str]) -> str:
    return " ".join(shlex.quote(slot) for slot in argv)


def _credential(authorization: str | None, form_token: str | None) -> str:
    if authorization is None:
        return form_token or ""
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1]


def _as_utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _is_under(resolved: Path, prefix: Path) -> bool:
    if resolved == prefix:
        return True
    try:
        resolved.relative_to(prefix)
    except ValueError:
        return False
    return True


def _string_at(payload: object, *keys: str) -> str | None:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    if isinstance(current, str) and current != "":
        return current
    return None
