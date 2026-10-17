"""Host CPU, memory, and disk collector.

Stdlib only. Does not import other app modules. Unreadable proc files and
statvfs failures become ``available: false`` with a reason; they do not raise.

CPU and RAM come from ``{proc_root}/stat``, ``loadavg``, and ``meminfo``.
Those counters are not PID-namespaced, so they are host values even inside
a container. Disk view is ``host`` only when ``{proc_root}/mounts`` lists
``host_root``; otherwise disks are the container's own matching mounts and
``view`` is ``container view``.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

# Container-view fallback. Host view uses DISK_PATHS instead of this filter.
_CONTAINER_FSTYPES = frozenset(
    {
        "ext2",
        "ext3",
        "ext4",
        "xfs",
        "btrfs",
        "zfs",
        "bcachefs",
        "overlay",
        "f2fs",
        "vfat",
        "exfat",
        "ntfs",
        "fuseblk",
        "fuse.ntfs-3g",
    }
)


def classify_threshold(percent: float, warn: float, crit: float) -> str:
    """Return ok/warn/crit. Equal to a boundary is that level."""
    if percent >= crit:
        return "crit"
    if percent >= warn:
        return "warn"
    return "ok"


def cpu_percent_from_stat_text(first: str, second: str) -> dict:
    """CPU percent from two ``/proc/stat`` samples.

    Fields after the cpu token, indexes 0..7, are user, nice, system, idle,
    iowait, irq, softirq, steal. guest and guest_nice are not added. Idle for
    the delta is idle + iowait. Total is the sum of those eight fields once
    (iowait is not counted twice). ``total_delta <= 0`` yields 0.0.
    """
    first_cpus = _parse_stat(first)
    second_cpus = _parse_stat(second)
    if "cpu" not in first_cpus or "cpu" not in second_cpus:
        raise ValueError("cpu line missing")
    per_core = []
    for name, fields in first_cpus.items():
        if name == "cpu" or name not in second_cpus:
            continue
        per_core.append(
            {"id": name, "percent": _cpu_percent(fields, second_cpus[name])}
        )
    return {
        "percent": _cpu_percent(first_cpus["cpu"], second_cpus["cpu"]),
        "per_core": per_core,
        "cores": len(per_core),
        "load_fields_unused": True,
    }


def mem_from_meminfo(text: str) -> dict:
    """RAM from MemTotal minus MemAvailable. Values are kB; bytes are kB * 1024."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.split()
        if not parts:
            continue
        try:
            values[key] = int(parts[0])
        except ValueError:
            continue
    if "MemTotal" not in values or "MemAvailable" not in values:
        raise ValueError("missing MemTotal or MemAvailable")
    total_kb = values["MemTotal"]
    used_kb = total_kb - values["MemAvailable"]
    percent = (used_kb / total_kb * 100.0) if total_kb else 0.0
    return {
        "used_bytes": used_kb * 1024,
        "total_bytes": total_kb * 1024,
        "percent": percent,
    }


def collect_host(
    *,
    proc_root: str = "/proc",
    host_root: str = "/host",
    disk_paths: tuple[str, ...] = ("/host", "/host/home"),
    cpu_sample_seconds: float = 0.2,
    cpu_warn: float = 75.0,
    cpu_crit: float = 90.0,
    mem_warn: float = 75.0,
    mem_crit: float = 90.0,
    disk_warn: float = 75.0,
    disk_crit: float = 90.0,
    sleep: Callable[[float], None] | None = None,
    statvfs_fn: Callable | None = None,
    now: datetime | None = None,
) -> dict:
    """Collect host CPU, RAM, and disk. Missing sources degrade; this does not raise."""
    refreshed_at = (now if now is not None else datetime.now(timezone.utc)).isoformat()
    sleeper = time.sleep if sleep is None else sleep
    vfs = os.statvfs if statvfs_fn is None else statvfs_fn

    view, paths = _disk_view(proc_root, host_root, disk_paths)
    cpu = _collect_cpu(
        proc_root,
        cpu_sample_seconds,
        cpu_warn,
        cpu_crit,
        sleeper,
    )
    memory = _collect_memory(proc_root, mem_warn, mem_crit)
    disks = [_collect_disk(path, vfs, disk_warn, disk_crit) for path in paths]

    succeeded = (
        cpu["available"]
        or memory["available"]
        or any(disk["available"] for disk in disks)
    )
    return {
        "available": succeeded,
        "reason": None if succeeded else _failure_reason(cpu, memory, disks),
        "refreshed_at": refreshed_at,
        "view": view,
        "cpu": cpu,
        "memory": memory,
        "disks": disks,
    }


def _cpu_percent(first: list[int], second: list[int]) -> float:
    total_delta = sum(second[:8]) - sum(first[:8])
    idle_delta = (second[3] + second[4]) - (first[3] + first[4])
    if total_delta <= 0:
        return 0.0
    return (total_delta - idle_delta) / total_delta * 100.0


def _parse_stat(text: str) -> dict[str, list[int]]:
    parsed: dict[str, list[int]] = {}
    for line in text.splitlines():
        item = _parse_cpu_line(line)
        if item is None:
            continue
        name, fields = item
        parsed[name] = fields
    return parsed


def _parse_cpu_line(line: str) -> tuple[str, list[int]] | None:
    parts = line.split()
    if not parts:
        return None
    name = parts[0]
    if name != "cpu" and not (name.startswith("cpu") and name[3:].isdigit()):
        return None
    nums: list[int] = []
    for tok in parts[1:9]:
        try:
            nums.append(int(tok))
        except ValueError:
            return None
    if len(nums) < 4:
        return None
    nums.extend([0] * (8 - len(nums)))
    return name, nums


def _proc_file(proc_root: str, name: str) -> str:
    return str(Path(proc_root) / name)


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _collect_cpu(
    proc_root: str,
    cpu_sample_seconds: float,
    warn: float,
    crit: float,
    sleeper: Callable[[float], None],
) -> dict:
    stat_path = _proc_file(proc_root, "stat")
    loadavg = _read_loadavg(_proc_file(proc_root, "loadavg"))
    try:
        first = _read_text(stat_path)
    except (OSError, UnicodeError):
        return _cpu_unavailable(f"proc stat not readable: {stat_path}", loadavg)
    sleeper(cpu_sample_seconds)
    try:
        second = _read_text(stat_path)
        parsed = cpu_percent_from_stat_text(first, second)
    except OSError:
        return _cpu_unavailable(f"proc stat not readable: {stat_path}", loadavg)
    except ValueError:
        return _cpu_unavailable(f"proc stat not readable: {stat_path}", loadavg)
    return {
        "available": True,
        "reason": None,
        "percent": parsed["percent"],
        "per_core": parsed["per_core"],
        "loadavg": loadavg,
        "cores": parsed["cores"],
        "level": classify_threshold(parsed["percent"], warn, crit),
    }


def _cpu_unavailable(reason: str, loadavg: list[float] | None) -> dict:
    return {
        "available": False,
        "reason": reason,
        "percent": None,
        "per_core": [],
        "loadavg": loadavg,
        "cores": None,
        "level": None,
    }


def _read_loadavg(path: str) -> list[float] | None:
    try:
        text = _read_text(path)
    except (OSError, UnicodeError):
        return None
    parts = text.split()
    if len(parts) < 3:
        return None
    try:
        return [float(parts[0]), float(parts[1]), float(parts[2])]
    except ValueError:
        return None


def _collect_memory(proc_root: str, warn: float, crit: float) -> dict:
    path = _proc_file(proc_root, "meminfo")
    try:
        parsed = mem_from_meminfo(_read_text(path))
    except OSError:
        return _memory_unavailable(f"proc meminfo not readable: {path}")
    except ValueError:
        return _memory_unavailable(f"proc meminfo not readable: {path}")
    return {
        "available": True,
        "reason": None,
        "used_bytes": parsed["used_bytes"],
        "total_bytes": parsed["total_bytes"],
        "percent": parsed["percent"],
        "level": classify_threshold(parsed["percent"], warn, crit),
    }


def _memory_unavailable(reason: str) -> dict:
    return {
        "available": False,
        "reason": reason,
        "used_bytes": None,
        "total_bytes": None,
        "percent": None,
        "level": None,
    }


def _disk_view(
    proc_root: str,
    host_root: str,
    disk_paths: tuple[str, ...],
) -> tuple[str, list[str]]:
    mounts = _read_mounts(_proc_file(proc_root, "mounts"))
    if mounts is not None and any(mountpoint == host_root for mountpoint, _fstype in mounts):
        return "host", list(disk_paths)
    paths = [
        mountpoint
        for mountpoint, fstype in (mounts or [])
        if fstype in _CONTAINER_FSTYPES
    ]
    return "container view", paths


def _read_mounts(path: str) -> list[tuple[str, str]] | None:
    try:
        text = _read_text(path)
    except (OSError, UnicodeError):
        return None
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not line or line.isspace():
            continue
        fields = _mount_fields(line)
        if len(fields) < 3 or not fields[1]:
            continue
        rows.append((fields[1], fields[2]))
    return rows


def _mount_fields(line: str) -> list[str]:
    """Split a mounts line, unescaping octal sequences such as ``\\040``."""
    fields: list[str] = []
    buf: list[str] = []
    i = 0
    limit = len(line)
    while i < limit:
        if (
            line[i] == "\\"
            and i + 4 <= limit
            and all(char in "01234567" for char in line[i + 1 : i + 4])
        ):
            buf.append(chr(int(line[i + 1 : i + 4], 8)))
            i += 4
            continue
        if line[i] == " ":
            fields.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(line[i])
        i += 1
    fields.append("".join(buf))
    return fields


def _collect_disk(
    path: str,
    vfs: Callable,
    warn: float,
    crit: float,
) -> dict:
    try:
        st = vfs(path)
        return _disk_from_statvfs(path, st, warn, crit)
    except OSError:
        return _disk_unavailable(path, f"statvfs failed: {path}")
    except (AttributeError, TypeError, ValueError):
        return _disk_unavailable(path, f"statvfs failed: {path}")


def _disk_from_statvfs(path: str, st: object, warn: float, crit: float) -> dict:
    frsize = getattr(st, "f_frsize", 0) or getattr(st, "f_bsize", 0)
    total = int(getattr(st, "f_blocks") * frsize)
    free = int(getattr(st, "f_bfree") * frsize)
    avail = int(getattr(st, "f_bavail") * frsize)
    used = total - free
    percent = (used / total * 100.0) if total else 0.0
    return {
        "path": path,
        "available": True,
        "reason": None,
        "total_bytes": total,
        "used_bytes": used,
        "avail_bytes": avail,
        "percent": float(percent),
        "level": classify_threshold(percent, warn, crit),
    }


def _disk_unavailable(path: str, reason: str) -> dict:
    return {
        "path": path,
        "available": False,
        "reason": reason,
        "total_bytes": None,
        "used_bytes": None,
        "avail_bytes": None,
        "percent": None,
        "level": None,
    }


def _failure_reason(cpu: dict, memory: dict, disks: list[dict]) -> str:
    parts: list[str] = []
    if cpu.get("reason"):
        parts.append(cpu["reason"])
    if memory.get("reason"):
        parts.append(memory["reason"])
    disk_reasons = [disk["reason"] for disk in disks if disk.get("reason")]
    if disk_reasons:
        parts.extend(disk_reasons)
    elif not disks:
        parts.append("no disks")
    return "; ".join(parts) if parts else "host metrics unavailable"
