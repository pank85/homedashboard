"""Pure display formatting helpers.

Stdlib only. No I/O, no imports from other app modules. Every helper accepts
``object`` and returns a display string instead of raising, so collectors may
pass a partially-populated payload through untouched.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

_BYTE_UNITS = ("B", "KiB", "MiB", "GiB", "TiB")
_ONE_DECIMAL = Decimal("0.1")
_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600
_SECONDS_PER_DAY = 86400
_EPOCH_FLOOR = 1_000_000_000


def _is_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return not isinstance(value, float) or math.isfinite(value)
    return isinstance(value, Decimal) and value.is_finite()


def _one_decimal(value: Decimal) -> str:
    return str(value.quantize(_ONE_DECIMAL, rounding=ROUND_HALF_UP))


def _parse_iso(text: str) -> datetime | None:
    candidate = text.strip()
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _as_utc(moment: datetime | None) -> datetime:
    if moment is None:
        return datetime.now(timezone.utc)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def format_bytes(value: object) -> str:
    """Human byte size; ``unknown`` for missing or negative values."""
    if not _is_number(value) or value < 0:
        return "unknown"
    if value < 1024:
        return f"{int(value)} B"
    size = Decimal(value)
    index = 0
    while index < len(_BYTE_UNITS) - 1 and size >= 1024:
        size = size / 1024
        index += 1
    return f"{_one_decimal(size)} {_BYTE_UNITS[index]}"


def format_duration(seconds: object) -> str:
    """Truncated human duration; ``unknown`` for missing or negative values."""
    if not _is_number(seconds) or seconds < 0:
        return "unknown"
    total = int(seconds)
    if total >= _SECONDS_PER_DAY:
        return f"{total // _SECONDS_PER_DAY}d {(total % _SECONDS_PER_DAY) // _SECONDS_PER_HOUR}h"
    if total >= _SECONDS_PER_HOUR:
        return f"{total // _SECONDS_PER_HOUR}h {(total % _SECONDS_PER_HOUR) // _SECONDS_PER_MINUTE}m"
    if total >= _SECONDS_PER_MINUTE:
        return f"{total // _SECONDS_PER_MINUTE}m {total % _SECONDS_PER_MINUTE}s"
    return f"{total}s"


def format_percent(value: object) -> str:
    """One-decimal percent string; ``unknown`` for missing values."""
    if not _is_number(value):
        return "unknown"
    return f"{_one_decimal(Decimal(value))}%"


def format_relative(timestamp: str | None, now: datetime | None = None) -> str:
    """Relative age of an ISO timestamp; ``unknown`` if absent or future."""
    if not isinstance(timestamp, str) or not timestamp.strip():
        return "unknown"
    parsed = _parse_iso(timestamp)
    if parsed is None:
        return "unknown"
    delta = (_as_utc(now) - parsed).total_seconds()
    if delta < 0:
        return "unknown"
    total = int(delta)
    if total < _SECONDS_PER_MINUTE:
        return f"{total}s ago"
    if total < _SECONDS_PER_HOUR:
        return f"{total // _SECONDS_PER_MINUTE}m ago"
    if total < _SECONDS_PER_DAY:
        return f"{total // _SECONDS_PER_HOUR}h ago"
    return f"{total // _SECONDS_PER_DAY}d ago"


def image_short(image: str | None) -> str:
    """Image reference without a registry host or ``@sha256:`` digest."""
    if not isinstance(image, str):
        return ""
    text = image.strip()
    if not text:
        return ""
    digest_at = text.find("@sha256:")
    if digest_at != -1:
        text = text[:digest_at]
    if "/" in text:
        text = text.rsplit("/", 1)[1]
    return text


def health_label(health: str | None) -> str:
    """Docker health word; ``none`` when absent or literally none/null."""
    if not isinstance(health, str):
        return "none"
    text = health.strip()
    if not text or text.lower() in ("none", "null"):
        return "none"
    return text


def state_label(state: str | None) -> str:
    """Docker state word; ``unknown`` when absent or blank."""
    if not isinstance(state, str):
        return "unknown"
    text = state.strip()
    if not text:
        return "unknown"
    return text


def _timestamp_seconds(value: object, now: datetime | None) -> int | None:
    if _is_number(value):
        if value > _EPOCH_FLOOR:
            delta = _as_utc(now).timestamp() - float(value)
            return int(delta) if delta >= 0 else None
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = _parse_iso(value)
    if parsed is None:
        return None
    delta = (_as_utc(now) - parsed).total_seconds()
    if delta < 0:
        return None
    return int(delta)


def elapsed_from_herdr(
    item: dict, now: datetime | None = None
) -> tuple[int | None, str]:
    """Elapsed seconds from a herdr agent object, per decision 8.

    Only explicit durations or timestamps count; ``state_change_seq`` is a
    sequence number, never time. Returns ``(seconds, "herdr")`` or
    ``(None, "unknown")``.
    """
    if not isinstance(item, dict):
        return (None, "unknown")
    for key in ("elapsed_ms", "state_duration_ms", "duration_ms"):
        value = item.get(key)
        if _is_number(value) and value >= 0:
            return (int(value // 1000), "herdr")
    for key in ("state_since", "status_since", "state_changed_at"):
        seconds = _timestamp_seconds(item.get(key), now)
        if seconds is not None:
            return (seconds, "herdr")
    return (None, "unknown")
