"""Read-only Docker Engine API collector over a unix socket.

GET only. A missing socket, a non-JSON body, or an HTTP error on the list
call degrades to an unavailable payload and is not raised to the route.
"""

from __future__ import annotations

import json
import socket
import urllib.parse
from datetime import datetime, timezone
from http.client import HTTPConnection
from typing import Any


def cpu_percent_from_stats(stats: dict) -> float | None:
    """CPU percent from one stats payload (precpu_stats already included).

    Missing keys yield None. A non-positive system delta yields 0.0.
    ``online_cpus`` wins, else the percpu length, else 1.
    """
    try:
        cpu_stats = stats["cpu_stats"]
        precpu_stats = stats["precpu_stats"]
        cpu_delta = (
            cpu_stats["cpu_usage"]["total_usage"]
            - precpu_stats["cpu_usage"]["total_usage"]
        )
        system_delta = cpu_stats["system_cpu_usage"] - precpu_stats["system_cpu_usage"]
        if system_delta <= 0:
            return 0.0
        online = cpu_stats.get("online_cpus") or _percpu_count(cpu_stats) or 1
        return (cpu_delta / system_delta) * online * 100.0
    except (KeyError, TypeError, IndexError, ZeroDivisionError):
        return None


def collect_containers(
    *,
    socket_path: str,
    api_version: str = "v1.41",
    timeout: float = 3.0,
    now: datetime | None = None,
    client: Any | None = None,
) -> dict:
    """List containers. Never raises; list failures set ``available`` false."""
    moment = datetime.now(timezone.utc)
    try:
        moment = _as_utc(now)
        api = client if client is not None else _SocketClient(socket_path, timeout)
        version = api_version.strip("/")
        try:
            listed = api.get_json(f"/{version}/containers/json", {"all": "1"})
        except json.JSONDecodeError:
            return _unavailable(moment, "malformed JSON from docker API")
        except Exception as exc:
            return _list_failure(moment, socket_path, exc)
        if not isinstance(listed, list):
            return _unavailable(moment, "malformed JSON from docker API")
        rows: list[dict] = []
        for item in listed:
            if not isinstance(item, dict):
                continue
            try:
                rows.append(_one_container(api, version, item, moment))
            except Exception:
                rows.append(_row_from_list(item))
        rows.sort(key=_sort_key)
        return {
            "available": True,
            "reason": None,
            "refreshed_at": moment.isoformat(),
            "containers": rows,
        }
    except Exception:
        return _unavailable(moment, "collector error")


class _DockerHTTPError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"docker API error: {status}")
        self.status = status


class _UnixHTTPConnection(HTTPConnection):
    """HTTPConnection that dials a unix socket instead of TCP."""

    def __init__(self, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self._socket_path)
        except OSError:
            sock.close()
            raise
        self.sock = sock


class _SocketClient:
    """Stdlib GET client. Raises JSONDecodeError or an error with ``.status``."""

    def __init__(self, socket_path: str, timeout: float) -> None:
        self._socket_path = socket_path
        self._timeout = timeout

    def get_json(self, path: str, params: dict | None = None) -> Any:
        url = path
        if params:
            url = f"{path}?{urllib.parse.urlencode(params)}"
        conn = _UnixHTTPConnection(self._socket_path, self._timeout)
        try:
            conn.request("GET", url)
            response = conn.getresponse()
            body = response.read()
            status = response.status
        finally:
            conn.close()
        if status >= 400:
            raise _DockerHTTPError(status)
        return json.loads(body)


def _percpu_count(cpu_stats: dict) -> int:
    usage = cpu_stats.get("cpu_usage")
    if not isinstance(usage, dict):
        return 0
    percpu = usage.get("percpu_usage")
    if not isinstance(percpu, (list, tuple)):
        return 0
    return len(percpu)


def _as_utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _unavailable(moment: datetime, reason: str) -> dict:
    return {
        "available": False,
        "reason": reason,
        "refreshed_at": moment.isoformat(),
        "containers": [],
    }


def _list_failure(moment: datetime, socket_path: str, exc: Exception) -> dict:
    status = getattr(exc, "status", None)
    if isinstance(status, int) and not isinstance(status, bool) and status >= 400:
        return _unavailable(moment, f"docker API error: {status}")
    if isinstance(exc, OSError):
        return _unavailable(moment, f"docker socket not reachable: {socket_path}")
    return _unavailable(moment, "collector error")


def _one_container(api: Any, version: str, item: dict, moment: datetime) -> dict:
    row = _row_from_list(item)
    container_id = row["id"]
    if not container_id:
        return row
    safe_id = urllib.parse.quote(container_id, safe="")
    inspected = _get_optional(api, f"/{version}/containers/{safe_id}/json")
    if isinstance(inspected, dict):
        _apply_inspect(row, inspected, moment)
    if row["state"] == "running":
        stats = _get_optional(
            api,
            f"/{version}/containers/{safe_id}/stats",
            {"stream": "false"},
        )
        if isinstance(stats, dict):
            row["cpu_percent"] = cpu_percent_from_stats(stats)
            used, limit = _memory_bytes(stats)
            row["memory_used_bytes"] = used
            row["memory_limit_bytes"] = limit
    return row


def _get_optional(api: Any, path: str, params: dict | None = None) -> Any:
    try:
        return api.get_json(path, params)
    except Exception:
        return None


def _row_from_list(item: dict) -> dict:
    raw_id = item.get("Id")
    names = item.get("Names")
    name = ""
    if isinstance(names, list) and names and isinstance(names[0], str):
        name = _strip_one_slash(names[0])
    image = item.get("Image")
    state = item.get("State")
    return {
        "id": raw_id if isinstance(raw_id, str) else "",
        "name": name,
        "image": image if isinstance(image, str) else "",
        "state": state if isinstance(state, str) else "",
        "health": None,
        "uptime_seconds": None,
        "restart_count": 0,
        "cpu_percent": None,
        "memory_used_bytes": None,
        "memory_limit_bytes": None,
    }


def _apply_inspect(row: dict, inspected: dict, moment: datetime) -> None:
    raw_name = inspected.get("Name")
    if isinstance(raw_name, str) and raw_name:
        row["name"] = _strip_one_slash(raw_name)
    state_obj = inspected.get("State")
    if isinstance(state_obj, dict):
        status = state_obj.get("Status")
        if isinstance(status, str) and status:
            row["state"] = status
        health_obj = state_obj.get("Health")
        if isinstance(health_obj, dict):
            health = health_obj.get("Status")
            row["health"] = health if isinstance(health, str) and health else None
        if row["state"] == "running":
            started = _parse_started_at(state_obj.get("StartedAt"))
            if started is not None:
                row["uptime_seconds"] = max(
                    0, int((moment - started).total_seconds())
                )
    row["restart_count"] = _as_restart_count(inspected.get("RestartCount"))


def _memory_bytes(stats: dict) -> tuple[int | None, int | None]:
    # usage/limit only. Do not subtract cache or inactive_file.
    mem = stats.get("memory_stats")
    if not isinstance(mem, dict):
        return None, None
    return _as_int(mem.get("usage")), _as_int(mem.get("limit"))


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _as_restart_count(value: object) -> int:
    parsed = _as_int(value)
    return 0 if parsed is None else parsed


def _strip_one_slash(name: str) -> str:
    if name.startswith("/"):
        return name[1:]
    return name


def _parse_started_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dot = text.find(".")
    if dot != -1:
        end = dot + 1
        while end < len(text) and text[end].isdigit():
            end += 1
        frac = text[dot + 1 : end][:6]
        text = text[:dot] + (("." + frac) if frac else "") + text[end:]
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _sort_key(row: dict) -> tuple[int, str]:
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
