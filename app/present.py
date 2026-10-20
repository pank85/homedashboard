"""Derive display keys from raw dashboard payloads.

Pure. Imports only ``app.formatting``. ``present_dashboard`` returns a new dict
that keeps every raw key and adds the ``*_human`` / label keys the template and
JSON consumers render. It never raises: an unexpected payload is returned
unchanged so a read-only page can still render.
"""

from __future__ import annotations

from app.formatting import (
    format_bytes,
    format_duration,
    format_loadavg,
    format_percent,
    format_relative,
    health_label,
    image_short,
    state_label,
)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _level(percent: object, warn: float, crit: float) -> str:
    """Return ok/warn/crit, or "" when percent is not a number.

    Equal to a boundary is that level. Mirrors app.collectors.host.classify_threshold,
    duplicated here because this module imports only app.formatting.
    """
    if isinstance(percent, bool) or not isinstance(percent, (int, float)):
        return ""
    if percent >= crit:
        return "crit"
    if percent >= warn:
        return "warn"
    return "ok"


def _present_container(
    row: object,
    *,
    cpu_warn: float = 75.0,
    cpu_crit: float = 90.0,
    mem_warn: float = 75.0,
    mem_crit: float = 90.0,
) -> object:
    if not isinstance(row, dict):
        return row
    out = dict(row)
    if "uptime_seconds" in row:
        out["uptime_human"] = format_duration(row["uptime_seconds"])
    if "cpu_percent" in row:
        out["cpu_percent_human"] = format_percent(row["cpu_percent"])
    cpu_level = _level(row.get("cpu_percent"), cpu_warn, cpu_crit)
    if cpu_level:
        out["cpu_level"] = cpu_level
    else:
        out.pop("cpu_level", None)
    if "memory_used_bytes" in row:
        out["memory_used_human"] = format_bytes(row["memory_used_bytes"])
    if "memory_limit_bytes" in row:
        out["memory_limit_human"] = format_bytes(row["memory_limit_bytes"])
    if "image" in row:
        out["image_short"] = image_short(row["image"])
    if "state" in row:
        out["state_label"] = state_label(row["state"])
    if "health" in row:
        out["health_label"] = health_label(row["health"])
    used = row.get("memory_used_bytes")
    limit = row.get("memory_limit_bytes")
    memory_percent = row.get("memory_percent")
    if _is_int(used) and _is_int(limit) and limit > 0:
        memory_percent = used / limit * 100.0
        out["memory_percent"] = memory_percent
        out["memory_percent_human"] = format_percent(memory_percent)
    memory_level = _level(memory_percent, mem_warn, mem_crit)
    if memory_level:
        out["memory_level"] = memory_level
    else:
        out.pop("memory_level", None)
    return out


def _present_disk(disk: object) -> object:
    if not isinstance(disk, dict):
        return disk
    out = dict(disk)
    if "used_bytes" in disk:
        out["used_human"] = format_bytes(disk["used_bytes"])
    if "total_bytes" in disk:
        out["total_human"] = format_bytes(disk["total_bytes"])
    if "percent" in disk:
        out["percent_human"] = format_percent(disk["percent"])
    return out


def _present_host(host: object) -> object:
    if not isinstance(host, dict):
        return host
    out = dict(host)
    cpu = out.get("cpu")
    if isinstance(cpu, dict):
        cpu_out = dict(cpu)
        if "percent" in cpu:
            cpu_out["percent_human"] = format_percent(cpu["percent"])
        if "loadavg" in cpu:
            cpu_out["loadavg_human"] = format_loadavg(cpu["loadavg"])
        out["cpu"] = cpu_out
    memory = out.get("memory")
    if isinstance(memory, dict):
        memory_out = dict(memory)
        if "used_bytes" in memory:
            memory_out["used_human"] = format_bytes(memory["used_bytes"])
        if "total_bytes" in memory:
            memory_out["total_human"] = format_bytes(memory["total_bytes"])
        if "percent" in memory:
            memory_out["percent_human"] = format_percent(memory["percent"])
        out["memory"] = memory_out
    disks = out.get("disks")
    if isinstance(disks, list):
        out["disks"] = [_present_disk(disk) for disk in disks]
    return out


def _present_agent(row: object) -> object:
    if not isinstance(row, dict):
        return row
    out = dict(row)
    if "elapsed_seconds" in row:
        out["elapsed_human"] = format_duration(row["elapsed_seconds"])
    if "rss_bytes" in row:
        out["rss_human"] = format_bytes(row["rss_bytes"])
    if "cpu_percent" in row:
        out["cpu_percent_human"] = format_percent(row["cpu_percent"])
    return out


def _present_session(row: object) -> object:
    if not isinstance(row, dict):
        return row
    out = dict(row)
    if "created_at" in row:
        out["created_relative"] = format_relative(row["created_at"])
    if "updated_at" in row:
        out["updated_relative"] = format_relative(row["updated_at"])
    return out


def _present_list(
    container: dict,
    key: str,
    presenter,
    *,
    cpu_warn: float = 75.0,
    cpu_crit: float = 90.0,
    mem_warn: float = 75.0,
    mem_crit: float = 90.0,
) -> dict:
    rows = container.get(key)
    if isinstance(rows, list):
        if presenter is _present_container:
            container[key] = [
                presenter(
                    row,
                    cpu_warn=cpu_warn,
                    cpu_crit=cpu_crit,
                    mem_warn=mem_warn,
                    mem_crit=mem_crit,
                )
                for row in rows
            ]
        else:
            container[key] = [presenter(row) for row in rows]
    return container


def _present_project(row: object) -> object:
    if not isinstance(row, dict):
        return row
    out = dict(row)
    if "commit_at" in row:
        out["commit_relative"] = format_relative(row["commit_at"])
    return out


def _present(
    payload: dict,
    *,
    cpu_warn: float = 75.0,
    cpu_crit: float = 90.0,
    mem_warn: float = 75.0,
    mem_crit: float = 90.0,
) -> dict:
    out = dict(payload)
    git = out.get("git")
    if isinstance(git, dict):
        projects = git.get("projects")
        if isinstance(projects, list):
            git = dict(git)
            git["projects"] = [_present_project(project) for project in projects]
            out["git"] = git
    containers = out.get("containers")
    if isinstance(containers, dict):
        out["containers"] = _present_list(
            dict(containers),
            "containers",
            _present_container,
            cpu_warn=cpu_warn,
            cpu_crit=cpu_crit,
            mem_warn=mem_warn,
            mem_crit=mem_crit,
        )
    host = out.get("host")
    if isinstance(host, dict):
        out["host"] = _present_host(host)
    agents = out.get("agents")
    if isinstance(agents, dict):
        out["agents"] = _present_list(dict(agents), "agents", _present_agent)
    sessions = out.get("sessions")
    if isinstance(sessions, dict):
        out["sessions"] = _present_list(dict(sessions), "sessions", _present_session)
    return out


def present_dashboard(
    payload: dict,
    *,
    cpu_warn: float = 75.0,
    cpu_crit: float = 90.0,
    mem_warn: float = 75.0,
    mem_crit: float = 90.0,
) -> dict:
    """Return a copy of ``payload`` with human display keys added."""
    try:
        return _present(
            payload,
            cpu_warn=cpu_warn,
            cpu_crit=cpu_crit,
            mem_warn=mem_warn,
            mem_crit=mem_crit,
        )
    except Exception:
        return payload
