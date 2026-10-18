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


def _row_name(row: dict) -> str:
    name = row.get("name")
    return name if isinstance(name, str) else ""


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _name_sort_key(row: dict) -> tuple[int, str]:
    name = _row_name(row)
    if not name:
        return (1, "")
    return (0, name.casefold())


def _cpu_value(row: dict):
    value = row.get("cpu_percent")
    return float(value) if _is_number(value) else None


def _memory_value(row: dict):
    percent = row.get("memory_percent")
    if _is_number(percent):
        return float(percent)
    used = row.get("memory_used_bytes")
    limit = row.get("memory_limit_bytes")
    if _is_number(used) and _is_number(limit) and limit > 0:
        return used / limit * 100.0
    return None


def _descending_key(value_of):
    def key(row: dict) -> tuple[int, float, str]:
        value = value_of(row)
        name = _row_name(row).casefold()
        if value is None:
            return (1, 0.0, name)
        return (0, -value, name)

    return key


_SORT_KEYS = {
    "status": sort_key,
    "name": _name_sort_key,
    "cpu": _descending_key(_cpu_value),
    "memory": _descending_key(_memory_value),
}


def sort_containers(rows: list[dict], mode: str = "status") -> list[dict]:
    key = _SORT_KEYS.get(mode, sort_key)
    return sorted(rows, key=key)


def _project_name(row: dict) -> str:
    project = row.get("compose_project")
    if isinstance(project, str) and project:
        return project
    return "Other"


def group_containers(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(_project_name(row), []).append(row)
    order = sorted(groups, key=lambda name: (name == "Other", name.casefold()))
    return [(name, groups[name]) for name in order]


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
