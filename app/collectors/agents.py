"""Read-only herdr agent parser and /proc fallback.

Herdr argv is limited to ``workspace list``, ``agent list``, and ``api snapshot``
(the last only when the agent list parsed and was empty). Process names match
patterns exactly: ``pi`` does not match ``python``. Descendant RSS rolls into
the nearest matching ancestor; matching descendants are not separate rows.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from typing import Callable

_STATUSES = frozenset({"working", "idle", "blocked", "done"})
_DEFAULT_PATTERNS = (
    "claude",
    "opencode",
    "pi",
    "muse",
    "codex",
    "aider",
    "gemini",
    "hermes",
)


def normalize_status(value: str | None) -> str:
    if not isinstance(value, str):
        return "unknown"
    status = value.strip().lower()
    if status in _STATUSES:
        return status
    return "unknown"


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _first_text(item: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        text = _as_text(item.get(key))
        if text:
            return text
    return ""


def _session_of(raw: object) -> str:
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        value = _as_text(raw.get("value"))
        if value:
            return value
        return _as_text(raw.get("agent"))
    return ""


def _agent_record(item: dict) -> dict:
    workspace_id = item.get("workspace_id")
    return {
        "workspace_id": workspace_id if isinstance(workspace_id, str) else "",
        "label": _first_text(
            item,
            ("terminal_title_stripped", "terminal_title", "agent", "tab_id"),
        )
        or "agent",
        "status": normalize_status(item.get("agent_status")),
        "cwd": _first_text(item, ("cwd", "foreground_cwd")),
        "session": _session_of(item.get("agent_session")),
    }


def _object_list(payload: object, *keys: str) -> list:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return []
        current = current.get(key)
    if not isinstance(current, list):
        return []
    return current


def parse_herdr_agent_list(stdout: str) -> list[dict]:
    payload = json.loads(stdout)
    return [
        _agent_record(item)
        for item in _object_list(payload, "result", "agents")
        if isinstance(item, dict)
    ]


def parse_herdr_workspace_list(stdout: str) -> list[dict]:
    payload = json.loads(stdout)
    rows: list[dict] = []
    for item in _object_list(payload, "result", "workspaces"):
        if not isinstance(item, dict):
            continue
        workspace_id = item.get("workspace_id")
        rows.append(
            {
                "workspace_id": workspace_id if isinstance(workspace_id, str) else "",
                "label": _as_text(item.get("label")),
            }
        )
    return rows


def parse_herdr_snapshot(stdout: str) -> list[dict]:
    payload = json.loads(stdout)
    return [
        _agent_record(item)
        for item in _object_list(payload, "result", "snapshot", "agents")
        if isinstance(item, dict)
    ]


def process_cpu_percent(
    prev_ticks: int,
    curr_ticks: int,
    prev_total: int,
    curr_total: int,
    ncpu: int,
) -> float:
    total_delta = curr_total - prev_total
    if total_delta <= 0:
        return 0.0
    return ((curr_ticks - prev_ticks) / total_delta) * ncpu * 100.0


def _workspace_label(workspace_id: str, labels: dict[str, str]) -> str:
    if workspace_id:
        label = labels.get(workspace_id) or ""
        if label:
            return label
        return workspace_id
    return "unknown"


def _herdr_row(record: dict, labels: dict[str, str]) -> dict:
    return {
        "source": "herdr",
        "workspace_label": _workspace_label(record.get("workspace_id") or "", labels),
        "label": record["label"],
        "status": record["status"],
        "cwd": record["cwd"],
        "session": record["session"],
        "pid": None,
        "rss_bytes": None,
        "cpu_percent": None,
        "elapsed_seconds": None,
    }


class _HerdrFailure(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _default_runner(argv: list[str], timeout: float):
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _run_herdr(runner: Callable, argv: list[str], timeout: float) -> str:
    try:
        result = runner(argv, timeout)
    except FileNotFoundError:
        raise _HerdrFailure(f"herdr not found: {argv[0]}") from None
    except subprocess.TimeoutExpired:
        raise _HerdrFailure("herdr timed out") from None
    returncode = getattr(result, "returncode", 1)
    if returncode != 0:
        raise _HerdrFailure(f"herdr exited {returncode}")
    stdout = getattr(result, "stdout", None)
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    if not isinstance(stdout, str):
        raise _HerdrFailure("malformed JSON from herdr")
    return stdout


def _join_rows(records: list[dict], workspaces: list[dict]) -> list[dict]:
    labels = {
        item["workspace_id"]: item.get("label") or ""
        for item in workspaces
        if item.get("workspace_id")
    }
    return [_herdr_row(record, labels) for record in records]


def _collect_herdr(
    runner: Callable,
    herdr_bin: str,
    timeout: float,
) -> tuple[list[dict], str | None]:
    try:
        workspace_stdout = _run_herdr(runner, [herdr_bin, "workspace", "list"], timeout)
        workspaces = parse_herdr_workspace_list(workspace_stdout)
        agent_stdout = _run_herdr(runner, [herdr_bin, "agent", "list"], timeout)
        agents = parse_herdr_agent_list(agent_stdout)
        if not agents:
            snapshot_stdout = _run_herdr(runner, [herdr_bin, "api", "snapshot"], timeout)
            agents = parse_herdr_snapshot(snapshot_stdout)
        return _join_rows(agents, workspaces), None
    except _HerdrFailure as exc:
        return [], exc.message
    except json.JSONDecodeError:
        return [], "malformed JSON from herdr"


def _read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def _cpu_sample(stat_text: str) -> tuple[int, int]:
    """Aggregate ``cpu`` total as defined for host CPU, plus ``cpuN`` count.

    Indexes 0..7 after the token are user, nice, system, idle, iowait, irq,
    softirq, steal. Guest fields are not added. Total is the sum of those
    eight fields once (iowait is not counted twice), matching the host
    collector formula.
    """
    total = 0
    ncpu = 0
    saw_cpu = False
    for line in stat_text.splitlines():
        parts = line.split()
        if not parts:
            continue
        name = parts[0]
        if name == "cpu":
            nums = [int(part) for part in parts[1:9]]
            if len(nums) < 8:
                nums.extend([0] * (8 - len(nums)))
            user, nice, system, idle, iowait, irq, softirq, steal = nums[:8]
            total = user + nice + system + idle + iowait + irq + softirq + steal
            saw_cpu = True
        elif name.startswith("cpu") and name[3:].isdigit():
            ncpu += 1
    return total, max(ncpu, 1) if saw_cpu or ncpu else 1


def _read_cpu(proc_root: str) -> tuple[int, int]:
    text = _read_text(os.path.join(proc_root, "stat"))
    if not text:
        return 0, 1
    try:
        return _cpu_sample(text)
    except ValueError:
        return 0, 1


def _read_uptime(proc_root: str) -> float | None:
    text = _read_text(os.path.join(proc_root, "uptime"))
    if not text:
        return None
    parts = text.split()
    if not parts:
        return None
    try:
        return float(parts[0])
    except ValueError:
        return None


def _parse_proc_stat(text: str) -> dict | None:
    """Split the tail after the last ``)`` that closes comm.

    tail[1] ppid, tail[11] utime, tail[12] stime, tail[19] starttime,
    tail[21] rss pages.
    """
    end = text.rfind(")")
    if end < 0:
        return None
    tail = text[end + 1 :].split()
    if len(tail) < 22:
        return None
    try:
        return {
            "ppid": int(tail[1]),
            "utime": int(tail[11]),
            "stime": int(tail[12]),
            "starttime": int(tail[19]),
            "rss": int(tail[21]),
        }
    except ValueError:
        return None


def _argv0_basename(pid_dir: str) -> str:
    path = os.path.join(pid_dir, "cmdline")
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return ""
    if not raw:
        return ""
    first = raw.split(b"\0", 1)[0]
    if not first:
        return ""
    return os.path.basename(first.decode("utf-8", errors="replace"))


def _comm_of(pid_dir: str, stat_text: str) -> str:
    text = _read_text(os.path.join(pid_dir, "comm"))
    if text is not None and text.strip():
        return text.strip()
    end = stat_text.rfind(")")
    start = stat_text.find("(")
    if start >= 0 and end > start:
        return stat_text[start + 1 : end].strip()
    return ""


def _matched_pattern(comm: str, argv0: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        if comm == pattern:
            return pattern
    if argv0:
        for pattern in patterns:
            if argv0 == pattern:
                return pattern
    return None


def _scan_procs(proc_root: str) -> dict[int, dict]:
    found: dict[int, dict] = {}
    try:
        entries = list(os.scandir(proc_root))
    except OSError:
        raise
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        pid = int(entry.name)
        stat_text = _read_text(os.path.join(entry.path, "stat"))
        if stat_text is None:
            continue
        parsed = _parse_proc_stat(stat_text)
        if parsed is None:
            continue
        parsed["comm"] = _comm_of(entry.path, stat_text)
        parsed["argv0"] = _argv0_basename(entry.path)
        found[pid] = parsed
    return found


def _matching_ancestor(pid: int, procs: dict[int, dict], matching: set[int]) -> int | None:
    seen: set[int] = set()
    current = procs[pid]["ppid"]
    while current and current not in seen:
        seen.add(current)
        if current in matching:
            return current
        parent = procs.get(current)
        if parent is None:
            return None
        current = parent["ppid"]
    return None


def _descendant_rss(pid: int, children: dict[int, list[int]], procs: dict[int, dict], seen: set[int]) -> int:
    if pid in seen or pid not in procs:
        return 0
    seen.add(pid)
    total = procs[pid]["rss"]
    for child in children.get(pid, ()):
        total += _descendant_rss(child, children, procs, seen)
    return total


def _elapsed_seconds(uptime: float | None, starttime: int, clock_ticks: int | None) -> int | None:
    if uptime is None or not clock_ticks:
        return None
    raw = uptime - (starttime / clock_ticks)
    if raw < 0:
        return 0
    return int(raw)


def _proc_cwd(proc_root: str, pid: int) -> str:
    try:
        return os.readlink(os.path.join(proc_root, str(pid), "cwd"))
    except OSError:
        return ""


def _proc_rows(
    current: dict[int, dict],
    previous: dict[int, dict],
    prev_total: int,
    curr_total: int,
    ncpu: int,
    patterns: tuple[str, ...],
    page_size: int,
    clock_ticks: int | None,
    uptime: float | None,
    proc_root: str,
) -> list[dict]:
    matching: dict[int, str] = {}
    for pid, proc in current.items():
        pattern = _matched_pattern(proc["comm"], proc["argv0"], patterns)
        if pattern is not None:
            matching[pid] = pattern
    children: dict[int, list[int]] = {}
    for pid, proc in current.items():
        children.setdefault(proc["ppid"], []).append(pid)
    rows: list[dict] = []
    for pid in sorted(matching):
        if _matching_ancestor(pid, current, set(matching)) is not None:
            continue
        pages = _descendant_rss(pid, children, current, set())
        prev = previous.get(pid)
        prev_ticks = (prev["utime"] + prev["stime"]) if prev else 0
        curr_ticks = current[pid]["utime"] + current[pid]["stime"]
        rows.append(
            {
                "source": "proc",
                "workspace_label": "",
                "label": matching[pid],
                "status": "unknown",
                "cwd": _proc_cwd(proc_root, pid),
                "session": "",
                "pid": pid,
                "rss_bytes": pages * page_size,
                "cpu_percent": process_cpu_percent(
                    prev_ticks,
                    curr_ticks,
                    prev_total,
                    curr_total,
                    ncpu,
                ),
                "elapsed_seconds": _elapsed_seconds(
                    uptime,
                    current[pid]["starttime"],
                    clock_ticks,
                ),
            }
        )
    return rows


def _collect_proc(
    proc_root: str,
    patterns: tuple[str, ...],
    pause: Callable[[float], None],
    cpu_sample_seconds: float,
    clock_ticks: int | None,
    page_size: int,
) -> tuple[list[dict], str | None]:
    if not os.path.isdir(proc_root):
        return [], f"proc not readable: {proc_root}"
    try:
        previous = _scan_procs(proc_root)
        prev_total, _prev_ncpu = _read_cpu(proc_root)
        pause(cpu_sample_seconds)
        current = _scan_procs(proc_root)
        curr_total, ncpu = _read_cpu(proc_root)
    except OSError:
        return [], f"proc not readable: {proc_root}"
    if ncpu < 1:
        ncpu = 1
    uptime = _read_uptime(proc_root)
    rows = _proc_rows(
        current,
        previous,
        prev_total,
        curr_total,
        ncpu,
        patterns,
        page_size,
        clock_ticks,
        uptime,
        proc_root,
    )
    return rows, None


def _source(name: str, error: str | None, count: int, refreshed_at: str) -> dict:
    return {
        "name": name,
        "used": error is None,
        "refreshed_at": refreshed_at,
        "error": error,
        "count": count,
    }


def _timestamp(now: datetime | None) -> str:
    moment = now if now is not None else datetime.now(timezone.utc)
    return moment.isoformat()


def collect_agents(
    *,
    herdr_bin: str = "herdr",
    herdr_timeout: float = 3.0,
    patterns: tuple[str, ...] = _DEFAULT_PATTERNS,
    proc_root: str = "/proc",
    now: datetime | None = None,
    runner: Callable | None = None,
    sleep: Callable[[float], None] | None = None,
    cpu_sample_seconds: float = 0.2,
    clock_ticks: int | None = None,
    page_size: int | None = None,
) -> dict:
    refreshed_at = _timestamp(now)
    if clock_ticks is None:
        try:
            clock_ticks = int(os.sysconf("SC_CLK_TCK"))
        except (OSError, ValueError):
            clock_ticks = None
    page_size_known = page_size
    if page_size_known is None:
        try:
            page_size_known = int(os.sysconf("SC_PAGE_SIZE"))
        except (OSError, ValueError):
            page_size_known = None
    run = runner if runner is not None else _default_runner
    pause = sleep if sleep is not None else time.sleep
    try:
        herdr_rows, herdr_error = _collect_herdr(run, herdr_bin, herdr_timeout)
    except Exception as exc:
        if isinstance(exc, AssertionError):
            raise
        herdr_rows, herdr_error = [], "collector error"
    if page_size_known is None:
        proc_rows, proc_error = [], f"proc not readable: {proc_root}"
    else:
        try:
            proc_rows, proc_error = _collect_proc(
                proc_root,
                patterns,
                pause,
                cpu_sample_seconds,
                clock_ticks,
                page_size_known,
            )
        except Exception as exc:
            if isinstance(exc, AssertionError):
                raise
            proc_rows, proc_error = [], f"proc not readable: {proc_root}"
    agents = list(herdr_rows) + list(proc_rows)
    return {
        "available": True,
        "reason": None,
        "note": None if agents else "no agents detected",
        "refreshed_at": refreshed_at,
        "sources": [
            _source("herdr", herdr_error, len(herdr_rows), refreshed_at),
            _source("proc", proc_error, len(proc_rows), refreshed_at),
        ],
        "agents": agents,
    }
