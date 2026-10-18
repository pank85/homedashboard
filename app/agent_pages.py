"""Pure helpers for detected-agent pages.

No I/O, no settings, no collectors. Identity is the row's non-empty ``kind``
when present, otherwise its ``label``. A page key is that identity
lowercased and is accepted only when it matches ``^[a-z][a-z0-9-]{0,31}$``.
Anything else gets no key, no link, and no route. Pages are built only from
rows that are present in the current agents payload; ``AGENT_START_KINDS``
entries that were never detected are never invented here.
"""

from __future__ import annotations

import re
from typing import Any

_KEY_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def agent_identity(row: object) -> str:
    """Return the row's non-empty ``kind``, else its ``label``."""
    if not isinstance(row, dict):
        return ""
    kind = _text(row.get("kind"))
    if kind:
        return kind
    return _text(row.get("label"))


def agent_key(identity: object) -> str:
    """Return the lowercased key for an identity, or ``""`` when invalid."""
    text = _text(identity).lower()
    if _KEY_RE.fullmatch(text) is None:
        return ""
    return text


def _agents_list(payload: object) -> list:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("agents")
    return rows if isinstance(rows, list) else []


def _sessions_list(payload: object) -> list:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("sessions")
    return rows if isinstance(rows, list) else []


def detected_agent_rows(payload: object) -> list[dict]:
    """Return the payload's agent rows that have a valid page key."""
    rows: list[dict] = []
    for row in _agents_list(payload):
        if not isinstance(row, dict):
            continue
        if agent_key(agent_identity(row)):
            rows.append(row)
    return rows


def agent_rows_for_key(payload: object, key: object) -> list[dict]:
    """Return every payload row whose identity key equals ``key``."""
    wanted = agent_key(key)
    if not wanted:
        return []
    return [
        row
        for row in detected_agent_rows(payload)
        if agent_key(agent_identity(row)) == wanted
    ]


def primary_agent_row(rows: object) -> dict:
    """Prefer the herdr row, then the first row."""
    if not isinstance(rows, list) or not rows:
        return {}
    for row in rows:
        if isinstance(row, dict) and row.get("source") == "herdr":
            return row
    return rows[0]


def agent_is_live(row: object) -> bool:
    """A live agent row is ``working``, or a ``proc`` row."""
    if not isinstance(row, dict):
        return False
    return row.get("status") == "working" or row.get("source") == "proc"


def session_is_running(row: object) -> bool:
    return isinstance(row, dict) and row.get("status") == "running"


def running_signal(rows: object, sessions: object) -> str | None:
    """``"session"`` when a chat is running, else ``"agent"`` when live."""
    session_rows = sessions if isinstance(sessions, list) else []
    if any(session_is_running(row) for row in session_rows):
        return "session"
    row_list = rows if isinstance(rows, list) else []
    if any(agent_is_live(row) for row in row_list):
        return "agent"
    return None


def matching_sessions(payload: object, key: object) -> list[dict]:
    """Return chat rows whose ``agent_kind`` equals ``key``."""
    wanted = agent_key(key)
    if not wanted:
        return []
    return [
        row
        for row in _sessions_list(payload)
        if isinstance(row, dict) and agent_key(row.get("agent_kind")) == wanted
    ]


def agent_page_data(
    agents_payload: object,
    sessions_payload: object,
    key: object,
) -> dict[str, Any] | None:
    """Return the page payload for ``key``, or ``None`` when unknown."""
    wanted = agent_key(key)
    if not wanted:
        return None
    rows = agent_rows_for_key(agents_payload, wanted)
    if not rows:
        return None
    primary = primary_agent_row(rows)
    sessions = matching_sessions(sessions_payload, wanted)
    return {
        "key": wanted,
        "title": agent_identity(primary),
        "status": _text(primary.get("status")),
        "cwd": _text(primary.get("cwd")),
        "source": _text(primary.get("source")),
        "running": running_signal(rows, sessions),
        "sessions": sessions,
        "row_count": len(rows),
    }
