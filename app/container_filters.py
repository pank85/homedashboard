"""Pure container filter and sort rules.

Mirrors the ordering the docker collector already applies (``_sort_key``) and
the state/text rules the browser applies in ``app/static/container_filters.js``.
No I/O, no collector imports.
"""

TEXT_FIELDS = ("name", "compose_service", "image", "image_short")


def sort_key(row: dict) -> tuple[int, str]:
    state = row.get("state")
    health = row.get("health")
    if state == "restarting" or health == "unhealthy":
        rank = 0
    elif state == "running":
        rank = 1
    else:
        rank = 2
    name = row.get("name")
    return (rank, name if isinstance(name, str) else "")


def sort_containers(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=sort_key)


def _field(row: dict, key: str) -> str:
    value = row.get(key)
    return value if isinstance(value, str) else ""


def _matches_text(row: dict, needle: str) -> bool:
    for key in TEXT_FIELDS:
        if needle in _field(row, key).lower():
            return True
    return False


def _matches_state(row: dict, state: str) -> bool:
    if state == "Running":
        return row.get("state") == "running"
    if state == "Stopped":
        return row.get("state") != "running"
    return True


def _is_healthy(row: dict) -> bool:
    return row.get("health") == "healthy" or row.get("health_label") == "healthy"


def filter_containers(
    rows: list[dict],
    *,
    text: str = "",
    state: str = "All",
    hide_healthy: bool = False,
) -> list[dict]:
    needle = text.strip().lower()
    return [
        row
        for row in rows
        if _matches_state(row, state)
        and (not needle or _matches_text(row, needle))
        and not (hide_healthy and _is_healthy(row))
    ]


def filter_count(shown: int, total: int) -> str:
    return f"{shown} of {total} shown"
