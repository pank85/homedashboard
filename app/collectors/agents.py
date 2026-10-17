"""Read-only herdr agent parser and /proc fallback.

Without a session, herdr argv is limited to ``workspace list``, ``agent list``,
and ``api snapshot`` (the last only when the agent list parsed and was empty).
A configured session also runs ``tab list`` and a separate ``--version``. This
module never emits workspace create, agent start, close, stop, delete, prompt,
or send-keys. Process names match patterns exactly: ``pi`` does not match
``python``. Descendant RSS rolls into the nearest matching ancestor; matching
descendants are not separate rows.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from datetime import datetime, timezone
from typing import Callable

_STATUSES = frozenset({"working", "idle", "blocked", "done"})
_SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_DURATION_MS_KEYS = ("elapsed_ms", "state_duration_ms", "duration_ms")
_SINCE_KEYS = ("state_since", "status_since", "state_changed_at")
_EPOCH_SECONDS_MIN = 1_000_000_000
_REASON_LIMIT = 500
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


def _seconds_from_ms(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0:
        return None
    return int(value // 1000)


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value <= _EPOCH_SECONDS_MIN:
            return None
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        number = None
    else:
        if isinstance(number, bool) or number <= _EPOCH_SECONDS_MIN:
            return None
        return datetime.fromtimestamp(number, tz=timezone.utc)
    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _seconds_since(value: object, now: datetime) -> int | None:
    stamp = _parse_timestamp(value)
    if stamp is None:
        return None
    moment = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    delta = (moment - stamp).total_seconds()
    if delta < 0:
        return None
    return int(delta)


def elapsed_from_herdr(
    item: dict,
    now: datetime | None = None,
) -> tuple[int | None, str]:
    """Duration from herdr fields, never from ``state_change_seq``.

    Millisecond fields are truncated to whole seconds. Epoch seconds must be
    greater than 1_000_000_000. A future timestamp is unknown.
    """
    if not isinstance(item, dict):
        return None, "unknown"
    for key in _DURATION_MS_KEYS:
        if key not in item or item[key] is None:
            continue
        seconds = _seconds_from_ms(item[key])
        if seconds is not None:
            return seconds, "herdr"
    moment = now if now is not None else datetime.now(timezone.utc)
    for key in _SINCE_KEYS:
        if key not in item or item[key] is None:
            continue
        seconds = _seconds_since(item[key], moment)
        if seconds is not None:
            return seconds, "herdr"
    return None, "unknown"


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


def _kind_of(item: dict) -> str:
    agent = _as_text(item.get("agent"))
    if agent:
        return agent
    session = item.get("agent_session")
    if isinstance(session, dict):
        return _as_text(session.get("agent"))
    return ""


def _nonneg_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    if value < 0:
        return 0
    return value


def _id_text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _agent_record(item: dict, now: datetime | None = None) -> dict:
    elapsed_seconds, elapsed_source = elapsed_from_herdr(item, now)
    return {
        "workspace_id": _id_text(item.get("workspace_id")),
        "tab_id": _id_text(item.get("tab_id")),
        "pane_id": _id_text(item.get("pane_id")),
        "kind": _kind_of(item),
        "label": _first_text(
            item,
            ("terminal_title_stripped", "terminal_title", "agent", "tab_id"),
        )
        or "agent",
        "status": normalize_status(item.get("agent_status")),
        "cwd": _first_text(item, ("cwd", "foreground_cwd")),
        "session": _session_of(item.get("agent_session")),
        "elapsed_seconds": elapsed_seconds,
        "elapsed_source": elapsed_source,
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


def parse_herdr_agent_list(stdout: str, now: datetime | None = None) -> list[dict]:
    payload = json.loads(stdout)
    return [
        _agent_record(item, now)
        for item in _object_list(payload, "result", "agents")
        if isinstance(item, dict)
    ]


def parse_herdr_workspace_list(stdout: str) -> list[dict]:
    payload = json.loads(stdout)
    rows: list[dict] = []
    for item in _object_list(payload, "result", "workspaces"):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "workspace_id": _id_text(item.get("workspace_id")),
                "label": _as_text(item.get("label")),
                "agent_status": normalize_status(item.get("agent_status")),
                "tab_count": _nonneg_int(item.get("tab_count")),
                "pane_count": _nonneg_int(item.get("pane_count")),
            }
        )
    return rows


def parse_herdr_tab_list(stdout: str) -> list[dict]:
    payload = json.loads(stdout)
    rows: list[dict] = []
    for item in _object_list(payload, "result", "tabs"):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "tab_id": _id_text(item.get("tab_id")),
                "workspace_id": _id_text(item.get("workspace_id")),
                "label": _as_text(item.get("label")),
                "agent_status": normalize_status(item.get("agent_status")),
                "pane_count": _nonneg_int(item.get("pane_count")),
            }
        )
    return rows


def parse_herdr_snapshot(stdout: str, now: datetime | None = None) -> list[dict]:
    payload = json.loads(stdout)
    return [
        _agent_record(item, now)
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


def _herdr_row(record: dict, labels: dict[str, str], tab_labels: dict[str, str]) -> dict:
    workspace_id = record.get("workspace_id") or ""
    tab_id = record.get("tab_id") or ""
    elapsed_seconds = record.get("elapsed_seconds")
    return {
        "source": "herdr",
        "workspace_id": workspace_id,
        "workspace_label": _workspace_label(workspace_id, labels),
        "label": record["label"],
        "tab_id": tab_id,
        "tab_label": tab_labels.get(tab_id, "") if tab_id else "",
        "pane_id": record.get("pane_id") or "",
        "kind": record.get("kind") or "",
        "status": record["status"],
        "cwd": record["cwd"],
        "session": record["session"],
        "pid": None,
        "rss_bytes": None,
        "cpu_percent": None,
        "elapsed_seconds": elapsed_seconds,
        "elapsed_source": record.get("elapsed_source") or "unknown",
    }


class _HerdrFailure(Exception):
    def __init__(
        self,
        message: str,
        *,
        argv: list[str] | None = None,
        stderr: str = "",
        enrich: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.argv = argv
        self.stderr = stderr
        self.enrich = enrich


class _HerdrOutcome:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.workspaces: list[dict] = []
        self.error: str | None = None
        self.reason: str | None = None
        self.command: str | None = None
        self.reachable = False
        self.version: str | None = None
        self.tab_count = 0
        self.refused = False
        self.session = ""


def _quote_argv(argv: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)


def _stderr_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return ""


def _block_reason(
    message: str,
    argv: list[str] | None,
    stderr: str,
    enrich: bool,
) -> tuple[str, str | None]:
    quoted = _quote_argv(argv) if argv else None
    if enrich and quoted is not None:
        return f"{message}: {quoted}: {stderr}"[:_REASON_LIMIT], quoted
    return message, quoted


def _herdr_block(outcome: _HerdrOutcome) -> dict:
    return {
        "reachable": outcome.reachable,
        "version": outcome.version,
        "session": outcome.session,
        "refused": outcome.refused,
        "reason": outcome.reason,
        "workspace_count": len(outcome.workspaces),
        "tab_count": outcome.tab_count,
        "agent_count": len(outcome.rows),
        "command": outcome.command,
    }


def _refuse(outcome: _HerdrOutcome, reason: str, *, refused: bool) -> _HerdrOutcome:
    outcome.error = reason
    outcome.reason = reason
    outcome.command = None
    outcome.reachable = False
    outcome.refused = refused
    outcome.rows = []
    return outcome


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
        raise _HerdrFailure(
            f"herdr not found: {argv[0]}",
            argv=argv,
        ) from None
    except subprocess.TimeoutExpired as exc:
        raise _HerdrFailure(
            "herdr timed out",
            argv=argv,
            stderr=_stderr_text(getattr(exc, "stderr", None)),
            enrich=True,
        ) from None
    returncode = getattr(result, "returncode", 1)
    if returncode != 0:
        raise _HerdrFailure(
            f"herdr exited {returncode}",
            argv=argv,
            stderr=_stderr_text(getattr(result, "stderr", None)),
            enrich=True,
        )
    stdout = getattr(result, "stdout", None)
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    if not isinstance(stdout, str):
        raise _HerdrFailure("malformed JSON from herdr", argv=argv)
    return stdout


def _load_json(runner: Callable, argv: list[str], timeout: float) -> str:
    stdout = _run_herdr(runner, argv, timeout)
    try:
        json.loads(stdout)
    except json.JSONDecodeError:
        raise _HerdrFailure("malformed JSON from herdr", argv=argv) from None
    return stdout


def _version_text(stdout: str) -> str | None:
    if not stdout:
        return None
    line = stdout.splitlines()[0].strip()
    return line or None


def _read_version(runner: Callable, herdr_bin: str, timeout: float) -> str | None:
    try:
        stdout = _run_herdr(runner, [herdr_bin, "--version"], timeout)
    except _HerdrFailure:
        return None
    except Exception as exc:
        if isinstance(exc, AssertionError):
            raise
        return None
    return _version_text(stdout)


def _tab_labels(tabs: list[dict]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for tab in tabs:
        tab_id = tab.get("tab_id") or ""
        if tab_id:
            labels[tab_id] = tab.get("label") or ""
    return labels


def _join_rows(
    records: list[dict],
    workspaces: list[dict],
    tab_labels: dict[str, str] | None = None,
) -> list[dict]:
    labels = {
        item["workspace_id"]: item.get("label") or ""
        for item in workspaces
        if item.get("workspace_id")
    }
    joined = tab_labels or {}
    return [_herdr_row(record, labels, joined) for record in records]


def _apply_failure(outcome: _HerdrOutcome, failure: _HerdrFailure) -> _HerdrOutcome:
    outcome.error = failure.message
    outcome.rows = []
    outcome.reachable = False
    outcome.reason, outcome.command = _block_reason(
        failure.message,
        failure.argv,
        failure.stderr,
        failure.enrich,
    )
    return outcome


def _collect_herdr(
    runner: Callable,
    herdr_bin: str,
    timeout: float,
    *,
    herdr_session: str | None,
    herdr_config_dir: str,
    now: datetime | None,
) -> _HerdrOutcome:
    outcome = _HerdrOutcome()
    session: str | None = None
    if herdr_session is not None:
        stripped = herdr_session.strip()
        outcome.session = stripped
        if stripped.casefold() == "default":
            return _refuse(outcome, "refusing session default", refused=True)
        if _SESSION_NAME_RE.fullmatch(stripped) is None:
            return _refuse(outcome, "invalid HERDR_SESSION", refused=False)
        if herdr_config_dir and not os.path.isfile(
            os.path.join(herdr_config_dir, "config.toml")
        ):
            return _refuse(outcome, "herdr config not mounted", refused=False)
        session = stripped
    prefix = [herdr_bin] if session is None else [herdr_bin, "--session", session]
    try:
        workspace_stdout = _load_json(runner, prefix + ["workspace", "list"], timeout)
        outcome.workspaces = parse_herdr_workspace_list(workspace_stdout)
        tab_labels: dict[str, str] = {}
        if session is not None:
            tab_stdout = _load_json(runner, prefix + ["tab", "list"], timeout)
            tabs = parse_herdr_tab_list(tab_stdout)
            outcome.tab_count = len(tabs)
            tab_labels = _tab_labels(tabs)
        agent_stdout = _load_json(runner, prefix + ["agent", "list"], timeout)
        agents = parse_herdr_agent_list(agent_stdout, now)
        if not agents:
            snapshot_stdout = _load_json(runner, prefix + ["api", "snapshot"], timeout)
            agents = parse_herdr_snapshot(snapshot_stdout, now)
        outcome.rows = _join_rows(agents, outcome.workspaces, tab_labels)
        outcome.reachable = True
        outcome.error = None
        outcome.reason = None
        outcome.command = None
        if session is not None:
            outcome.version = _read_version(runner, herdr_bin, timeout)
        return outcome
    except _HerdrFailure as exc:
        return _apply_failure(outcome, exc)


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
        elapsed_seconds = _elapsed_seconds(
            uptime,
            current[pid]["starttime"],
            clock_ticks,
        )
        rows.append(
            {
                "source": "proc",
                "workspace_id": "",
                "workspace_label": "",
                "label": matching[pid],
                "tab_id": "",
                "tab_label": "",
                "pane_id": "",
                "kind": "",
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
                "elapsed_seconds": elapsed_seconds,
                "elapsed_source": "proc" if elapsed_seconds is not None else "unknown",
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
    herdr_session: str | None = None,
    herdr_config_dir: str = "",
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
        herdr = _collect_herdr(
            run,
            herdr_bin,
            herdr_timeout,
            herdr_session=herdr_session,
            herdr_config_dir=herdr_config_dir,
            now=now,
        )
    except Exception as exc:
        if isinstance(exc, AssertionError):
            raise
        herdr = _HerdrOutcome()
        herdr.error = "collector error"
        herdr.reason = "collector error"
        if herdr_session is not None:
            herdr.session = herdr_session.strip()
    herdr_rows = herdr.rows
    herdr_error = herdr.error
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
        "herdr": _herdr_block(herdr),
        "workspaces": list(herdr.workspaces),
    }
