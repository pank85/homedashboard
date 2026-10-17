import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import datetime, timezone

import pytest

from app.collectors.host import (
    classify_threshold,
    collect_host,
    cpu_percent_from_stat_text,
    mem_from_meminfo,
)

TOL = 1e-6

# Normative /proc/stat fixture from the host-collector contract.
CPU_FIRST = """\
cpu  100 0 0 100 0 0 0 0 0 0
cpu0 50 0 0 50 0 0 0 0 0 0
cpu1 50 0 0 50 0 0 0 0 0 0
"""

CPU_SECOND = """\
cpu  200 0 100 200 0 0 0 0 0 0
cpu0 150 0 50 50 0 0 0 0 0 0
cpu1 50 0 50 150 0 0 0 0 0 0
"""

NOW = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)


class _Vfs:
    def __init__(self, frsize, blocks, bfree, bavail, bsize=None):
        self.f_frsize = frsize
        self.f_bsize = frsize if bsize is None else bsize
        self.f_blocks = blocks
        self.f_bfree = bfree
        self.f_bavail = bavail


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _proc(tmp_path: Path, *, stat=CPU_FIRST, meminfo="MemTotal: 1000 kB\nMemAvailable: 400 kB\n", mounts="", loadavg="0.1 0.2 0.3 1/2 3\n"):
    root = tmp_path / "proc"
    if stat is not None:
        _write(root / "stat", stat)
    if meminfo is not None:
        _write(root / "meminfo", meminfo)
    if mounts is not None:
        _write(root / "mounts", mounts)
    if loadavg is not None:
        _write(root / "loadavg", loadavg)
    return root


def test_classify_threshold_boundaries():
    assert classify_threshold(74.9, 75, 90) == "ok"
    assert classify_threshold(75, 75, 90) == "warn"
    assert classify_threshold(89.9, 75, 90) == "warn"
    assert classify_threshold(90, 75, 90) == "crit"
    assert classify_threshold(0, 75, 90) == "ok"


def test_cpu_percent_from_normative_fixture():
    parsed = cpu_percent_from_stat_text(CPU_FIRST, CPU_SECOND)

    # Aggregate busy delta 200 / total delta 300. cpu0 busy delta 150 / 150.
    assert parsed["percent"] == pytest.approx(200 / 300 * 100, abs=TOL)
    assert parsed["percent"] == pytest.approx(66.6666666667, abs=TOL)
    assert parsed["per_core"][0] == {"id": "cpu0", "percent": pytest.approx(100.0, abs=TOL)}
    # cpu1 fields: total delta 150, idle delta 100. Normative formula is
    # (total_delta - idle_delta) / total_delta = 50/150. The contract prose
    # writes 100/150 (idle_delta / total_delta); that is the idle share.
    assert parsed["per_core"][1]["id"] == "cpu1"
    assert parsed["per_core"][1]["percent"] == pytest.approx(50 / 150 * 100, abs=TOL)
    assert parsed["per_core"][1]["percent"] != pytest.approx(100 / 150 * 100, abs=TOL)
    assert parsed["cores"] == 2
    assert parsed["load_fields_unused"] is True


def test_cpu_percent_counts_iowait_once_as_idle():
    first = "cpu 0 0 0 0 100 0 0 0 0 0\n"
    second = "cpu 0 0 0 0 200 0 0 0 0 0\n"
    assert cpu_percent_from_stat_text(first, second)["percent"] == 0.0


def test_cpu_percent_does_not_add_guest_fields():
    # guest rose by 30 and is already inside user. Adding it again would
    # inflate total_delta from 50 to 80 and change the percent.
    first = "cpu 100 0 0 100 0 0 0 0 10 0\n"
    second = "cpu 150 0 0 100 0 0 0 0 40 0\n"
    assert cpu_percent_from_stat_text(first, second)["percent"] == pytest.approx(100.0, abs=TOL)


def test_cpu_percent_non_positive_delta_is_zero():
    same = "cpu  100 0 0 100 0 0 0 0 0 0\ncpu0 1 0 0 1 0 0 0 0 0 0\n"
    assert cpu_percent_from_stat_text(same, same)["percent"] == 0.0
    backwards = "cpu  50 0 0 50 0 0 0 0 0 0\n"
    assert cpu_percent_from_stat_text(same, backwards)["percent"] == 0.0


def test_mem_from_meminfo_subtracts_available_not_free():
    text = "MemTotal: 8000000 kB\nMemFree: 100 kB\nMemAvailable: 2000000 kB\n"
    parsed = mem_from_meminfo(text)
    assert parsed["total_bytes"] == 8000000 * 1024
    assert parsed["used_bytes"] == 6000000 * 1024
    assert parsed["percent"] == pytest.approx(75.0, abs=TOL)


def test_collect_host_normative_cpu_loadavg_and_timestamp(tmp_path):
    proc = _proc(
        tmp_path,
        mounts="/dev/sda1 /host ext4 rw 0 0\n",
        loadavg="1.25 0.50 0.10 2/100 99\n",
    )
    sleeps = []

    def sleeper(seconds):
        sleeps.append(seconds)
        (proc / "stat").write_text(CPU_SECOND, encoding="utf-8")

    result = collect_host(
        proc_root=str(proc),
        host_root="/host",
        disk_paths=("/host",),
        cpu_sample_seconds=0.2,
        sleep=sleeper,
        statvfs_fn=lambda _path: _Vfs(4096, 1000, 400, 350),
        now=NOW,
    )

    assert sleeps == [0.2]
    assert result["refreshed_at"] == NOW.isoformat()
    assert result["view"] == "host"
    assert result["available"] is True
    assert result["reason"] is None
    assert result["cpu"]["available"] is True
    assert result["cpu"]["percent"] == pytest.approx(66.6666666667, abs=TOL)
    assert result["cpu"]["cores"] == 2
    assert result["cpu"]["loadavg"] == [1.25, 0.5, 0.10]
    assert result["cpu"]["level"] == "ok"
    assert result["cpu"]["per_core"][0]["id"] == "cpu0"
    assert result["cpu"]["per_core"][1]["percent"] == pytest.approx(50 / 150 * 100, abs=TOL)


def test_cpu_threshold_boundaries_via_collect(tmp_path):
    cases = [
        ("cpu  0 0 0 100 0 0 0 0 0 0\n", "cpu  75 0 0 125 0 0 0 0 0 0\n", "warn"),
        ("cpu  0 0 0 100 0 0 0 0 0 0\n", "cpu  90 0 0 110 0 0 0 0 0 0\n", "crit"),
        ("cpu  0 0 0 100 0 0 0 0 0 0\n", "cpu  0 0 0 100 0 0 0 0 0 0\n", "ok"),
    ]
    for first, second, level in cases:
        proc = _proc(tmp_path / level, stat=first, mounts="/dev/sda1 /host ext4 rw 0 0\n")

        def sleeper(_seconds, proc=proc, second=second):
            (proc / "stat").write_text(second, encoding="utf-8")

        result = collect_host(
            proc_root=str(proc),
            host_root="/host",
            disk_paths=(),
            cpu_sample_seconds=0,
            sleep=sleeper,
            statvfs_fn=lambda _path: _Vfs(1, 1, 1, 1),
        )
        assert result["cpu"]["level"] == level


def test_memory_threshold_boundaries(tmp_path):
    cases = [
        ("MemTotal: 1000 kB\nMemAvailable: 251 kB\n", 74.9, "ok", 749 * 1024),
        ("MemTotal: 1000 kB\nMemAvailable: 250 kB\n", 75.0, "warn", 750 * 1024),
        ("MemTotal: 1000 kB\nMemAvailable: 101 kB\n", 89.9, "warn", 899 * 1024),
        ("MemTotal: 1000 kB\nMemAvailable: 100 kB\n", 90.0, "crit", 900 * 1024),
    ]
    for text, percent, level, used in cases:
        proc = _proc(tmp_path / level, meminfo=text, mounts="/dev/sda1 /host ext4 rw 0 0\n")
        result = collect_host(
            proc_root=str(proc),
            host_root="/host",
            disk_paths=(),
            cpu_sample_seconds=0,
            sleep=lambda _seconds: None,
            statvfs_fn=lambda _path: _Vfs(1, 1, 1, 1),
        )
        assert result["memory"]["percent"] == pytest.approx(percent, abs=TOL)
        assert result["memory"]["level"] == level
        assert result["memory"]["used_bytes"] == used
        assert result["memory"]["total_bytes"] == 1000 * 1024


def test_statvfs_fixtures_and_boundary_levels(tmp_path):
    fixtures = {
        "/host": _Vfs(4096, 1000, 400, 350),
        "/host/warn": _Vfs(1, 100, 25, 25),
        "/host/crit": _Vfs(1, 100, 10, 10),
    }
    calls = []

    def vfs(path):
        calls.append(path)
        return fixtures[path]

    proc = _proc(tmp_path, mounts="/dev/sda1 /host ext4 rw 0 0\n")
    result = collect_host(
        proc_root=str(proc),
        host_root="/host",
        disk_paths=("/host", "/host/warn", "/host/crit"),
        cpu_sample_seconds=0,
        sleep=lambda _seconds: None,
        statvfs_fn=vfs,
    )

    assert result["view"] == "host"
    assert calls == ["/host", "/host/warn", "/host/crit"]
    ok, warn, crit = result["disks"]
    assert ok["total_bytes"] == 4096000
    assert ok["used_bytes"] == 2457600
    assert ok["avail_bytes"] == 1433600
    assert ok["percent"] == pytest.approx(60.0, abs=TOL)
    assert ok["level"] == "ok"
    assert warn["percent"] == pytest.approx(75.0, abs=TOL)
    assert warn["level"] == "warn"
    assert crit["percent"] == pytest.approx(90.0, abs=TOL)
    assert crit["level"] == "crit"


def test_host_view_statvfs_called_with_disk_paths(tmp_path):
    calls = []

    def vfs(path):
        calls.append(path)
        return _Vfs(4096, 1000, 400, 350)

    proc = _proc(
        tmp_path,
        mounts=(
            "/dev/sda1 /host ext4 rw,relatime 0 0\n"
            "/dev/sda2 /host/extra ext4 rw 0 0\n"
            "tmpfs /tmp tmpfs rw 0 0\n"
        ),
    )
    result = collect_host(
        proc_root=str(proc),
        host_root="/host",
        disk_paths=("/host", "/host/home"),
        cpu_sample_seconds=0,
        sleep=lambda _seconds: None,
        statvfs_fn=vfs,
    )

    assert result["view"] == "host"
    assert calls == ["/host", "/host/home"]


def test_container_view_uses_filtered_fstypes_not_disk_paths(tmp_path):
    calls = []

    def vfs(path):
        calls.append(path)
        return _Vfs(1, 100, 50, 40)

    proc = _proc(
        tmp_path,
        mounts=(
            "sysfs /sys sysfs rw 0 0\n"
            "proc /proc proc rw 0 0\n"
            "tmpfs /tmp tmpfs rw 0 0\n"
            "overlay / overlay rw 0 0\n"
            "/dev/sda1 /var/lib/docker ext4 rw 0 0\n"
            "/dev/sdb1 /mnt/my\\040disk xfs rw 0 0\n"
            "/dev/sdc1 /mnt/win fuse.ntfs-3g rw 0 0\n"
            "/dev/sdd1 /mnt/ntfs3 ntfs3 rw 0 0\n"
            "/dev/sde1 /mnt/fat vfat rw 0 0\n"
        ),
    )
    result = collect_host(
        proc_root=str(proc),
        host_root="/host",
        disk_paths=("/host", "/host/home"),
        cpu_sample_seconds=0,
        sleep=lambda _seconds: None,
        statvfs_fn=vfs,
    )

    assert result["view"] == "container view"
    assert calls == ["/", "/var/lib/docker", "/mnt/my disk", "/mnt/win", "/mnt/fat"]
    assert "/host" not in calls
    assert "/host/home" not in calls


def test_host_root_prefix_is_not_a_mount_match(tmp_path):
    calls = []
    proc = _proc(
        tmp_path,
        mounts=(
            "/dev/sda1 /host-backup ext4 rw 0 0\n"
            "/dev/sda2 /host/extra ext4 rw 0 0\n"
        ),
    )
    result = collect_host(
        proc_root=str(proc),
        host_root="/host",
        disk_paths=("/should-not-be-used",),
        cpu_sample_seconds=0,
        sleep=lambda _seconds: None,
        statvfs_fn=lambda path: calls.append(path) or _Vfs(1, 10, 5, 4),
    )
    assert result["view"] == "container view"
    assert calls == ["/host-backup", "/host/extra"]


def test_escaped_host_root_mountpoint_is_host_view(tmp_path):
    calls = []
    proc = _proc(tmp_path, mounts="/dev/sda1 /host\\040root ext4 rw 0 0\n")
    result = collect_host(
        proc_root=str(proc),
        host_root="/host root",
        disk_paths=("/host root", "/host root/home"),
        cpu_sample_seconds=0,
        sleep=lambda _seconds: None,
        statvfs_fn=lambda path: calls.append(path) or _Vfs(1, 10, 5, 4),
    )
    assert result["view"] == "host"
    assert calls == ["/host root", "/host root/home"]


def test_missing_stat_does_not_sleep(tmp_path):
    proc = _proc(tmp_path, stat=None, mounts="/dev/sda1 /host ext4 rw 0 0\n")
    sleeps = []
    result = collect_host(
        proc_root=str(proc),
        host_root="/host",
        disk_paths=("/host",),
        cpu_sample_seconds=5,
        sleep=lambda seconds: sleeps.append(seconds),
        statvfs_fn=lambda _path: _Vfs(1, 10, 5, 4),
        now=NOW,
    )
    stat_path = str(proc / "stat")
    assert sleeps == []
    assert result["cpu"]["available"] is False
    assert result["cpu"]["reason"].startswith("proc stat not readable:")
    assert result["cpu"]["reason"] == f"proc stat not readable: {stat_path}"
    assert result["cpu"]["percent"] is None
    assert result["cpu"]["level"] is None
    assert result["cpu"]["loadavg"] == [0.1, 0.2, 0.3]
    assert result["available"] is True
    assert result["reason"] is None
    assert result["refreshed_at"] == NOW.isoformat()


def test_missing_meminfo_reason(tmp_path):
    proc = _proc(tmp_path, meminfo=None, mounts="/dev/sda1 /host ext4 rw 0 0\n")
    result = collect_host(
        proc_root=str(proc),
        host_root="/host",
        disk_paths=("/host",),
        cpu_sample_seconds=0,
        sleep=lambda _seconds: None,
        statvfs_fn=lambda _path: _Vfs(1, 10, 5, 4),
    )
    mem_path = str(proc / "meminfo")
    assert result["memory"]["available"] is False
    assert result["memory"]["reason"].startswith("proc meminfo not readable:")
    assert result["memory"]["reason"] == f"proc meminfo not readable: {mem_path}"
    assert result["memory"]["used_bytes"] is None
    assert result["available"] is True
    assert result["reason"] is None


def test_statvfs_oserror_degrades_disk_not_panel(tmp_path):
    proc = _proc(tmp_path, mounts="/dev/sda1 /host ext4 rw 0 0\n")

    def vfs(path):
        if path == "/host/home":
            raise OSError("not mounted")
        return _Vfs(4096, 1000, 400, 350)

    result = collect_host(
        proc_root=str(proc),
        host_root="/host",
        disk_paths=("/host", "/host/home"),
        cpu_sample_seconds=0,
        sleep=lambda _seconds: None,
        statvfs_fn=vfs,
    )
    assert result["available"] is True
    assert result["reason"] is None
    assert result["disks"][0]["available"] is True
    failed = result["disks"][1]
    assert failed["available"] is False
    assert failed["reason"].startswith("statvfs failed:")
    assert failed["reason"] == "statvfs failed: /host/home"
    assert failed["percent"] is None
    assert failed["level"] is None


def test_missing_path_inside_mounted_host_root(tmp_path):
    proc = _proc(tmp_path, mounts="/dev/sda1 /host ext4 rw 0 0\n")

    def vfs(path):
        raise FileNotFoundError(path)

    result = collect_host(
        proc_root=str(proc),
        host_root="/host",
        disk_paths=("/host/missing",),
        cpu_sample_seconds=0,
        sleep=lambda _seconds: None,
        statvfs_fn=vfs,
    )
    assert result["view"] == "host"
    assert result["available"] is True
    assert result["disks"][0]["available"] is False
    assert result["disks"][0]["reason"] == "statvfs failed: /host/missing"


def test_all_sources_failing_available_false(tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    _write(
        proc / "mounts",
        "overlay / overlay rw 0 0\n/dev/sda1 /data ext4 rw 0 0\n",
    )
    sleeps = []

    def vfs(path):
        raise OSError(path)

    result = collect_host(
        proc_root=str(proc),
        host_root="/host",
        disk_paths=("/host", "/host/home"),
        cpu_sample_seconds=1,
        sleep=lambda seconds: sleeps.append(seconds),
        statvfs_fn=vfs,
        now=NOW,
    )
    assert sleeps == []
    assert result["available"] is False
    assert result["reason"]
    assert result["view"] == "container view"
    assert result["refreshed_at"] == NOW.isoformat()
    assert result["cpu"]["available"] is False
    assert result["memory"]["available"] is False
    assert result["disks"]
    assert all(not disk["available"] for disk in result["disks"])
    assert all(disk["reason"].startswith("statvfs failed:") for disk in result["disks"])
    assert "/host" not in [disk["path"] for disk in result["disks"]]


def test_loadavg_missing_cpu_still_available(tmp_path):
    proc = _proc(tmp_path, loadavg=None, mounts="/dev/sda1 /host ext4 rw 0 0\n")
    result = collect_host(
        proc_root=str(proc),
        host_root="/host",
        disk_paths=(),
        cpu_sample_seconds=0,
        sleep=lambda _seconds: None,
        statvfs_fn=lambda _path: _Vfs(1, 1, 1, 1),
    )
    assert result["cpu"]["available"] is True
    assert result["cpu"]["loadavg"] is None
    assert result["cpu"]["percent"] == 0.0


def test_malformed_loadavg_is_null(tmp_path):
    proc = _proc(tmp_path, loadavg="not-a-loadavg\n", mounts="/dev/sda1 /host ext4 rw 0 0\n")
    result = collect_host(
        proc_root=str(proc),
        host_root="/host",
        disk_paths=(),
        cpu_sample_seconds=0,
        sleep=lambda _seconds: None,
        statvfs_fn=lambda _path: _Vfs(1, 1, 1, 1),
    )
    assert result["cpu"]["loadavg"] is None
    assert result["cpu"]["available"] is True


def test_sleep_zero_is_called_when_stat_present(tmp_path):
    proc = _proc(tmp_path, mounts="/dev/sda1 /host ext4 rw 0 0\n")
    sleeps = []
    collect_host(
        proc_root=str(proc),
        host_root="/host",
        disk_paths=(),
        cpu_sample_seconds=0,
        sleep=lambda seconds: sleeps.append(seconds),
        statvfs_fn=lambda _path: _Vfs(1, 1, 1, 1),
    )
    assert sleeps == [0]


def test_f_frsize_zero_uses_f_bsize(tmp_path):
    proc = _proc(tmp_path, mounts="/dev/sda1 /host ext4 rw 0 0\n")
    result = collect_host(
        proc_root=str(proc),
        host_root="/host",
        disk_paths=("/host",),
        cpu_sample_seconds=0,
        sleep=lambda _seconds: None,
        statvfs_fn=lambda _path: _Vfs(0, 100, 25, 20, bsize=512),
    )
    disk = result["disks"][0]
    assert disk["total_bytes"] == 51200
    assert disk["used_bytes"] == 38400
    assert disk["percent"] == pytest.approx(75.0, abs=TOL)
    assert disk["level"] == "warn"


def test_default_statvfs_on_real_directory(tmp_path):
    disk = tmp_path / "disk"
    disk.mkdir()
    proc = _proc(tmp_path, mounts=f"{disk} {disk} ext4 rw 0 0\n")
    result = collect_host(
        proc_root=str(proc),
        host_root=str(disk),
        disk_paths=(str(disk),),
        cpu_sample_seconds=0,
        sleep=lambda _seconds: None,
        now=NOW,
    )
    assert result["view"] == "host"
    assert result["disks"][0]["available"] is True
    assert result["disks"][0]["total_bytes"] > 0
    assert result["disks"][0]["level"] in {"ok", "warn", "crit"}


def test_missing_proc_root_does_not_raise(tmp_path):
    missing = tmp_path / "absent-proc"
    result = collect_host(
        proc_root=str(missing),
        host_root="/host",
        disk_paths=("/host",),
        cpu_sample_seconds=3,
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep called")),
        statvfs_fn=lambda _path: (_ for _ in ()).throw(AssertionError("statvfs called")),
        now=NOW,
    )
    assert result["available"] is False
    assert result["view"] == "container view"
    assert result["disks"] == []
    assert result["cpu"]["reason"].startswith("proc stat not readable:")
    assert result["memory"]["reason"].startswith("proc meminfo not readable:")
    assert result["reason"]
    assert "no disks" in result["reason"]


def test_undecodable_proc_files_do_not_raise(tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    for name in ("stat", "meminfo", "loadavg", "mounts"):
        (proc / name).write_bytes(b"\xff\xfe not utf-8")
    sleeps = []
    result = collect_host(
        proc_root=str(proc),
        host_root="/host",
        disk_paths=("/host",),
        cpu_sample_seconds=1,
        sleep=lambda seconds: sleeps.append(seconds),
        statvfs_fn=lambda _path: (_ for _ in ()).throw(AssertionError("statvfs called")),
        now=NOW,
    )
    assert sleeps == []
    assert result["available"] is False
    assert result["view"] == "container view"
    assert result["cpu"]["reason"].startswith("proc stat not readable:")
    assert result["memory"]["reason"].startswith("proc meminfo not readable:")
    assert result["cpu"]["loadavg"] is None
    assert result["disks"] == []


def test_malformed_proc_files_do_not_raise(tmp_path):
    proc = _proc(
        tmp_path,
        stat="not stat\n",
        meminfo="MemFree: 10 kB\n",
        mounts="/dev/sda1 /host ext4 rw 0 0\n",
    )
    result = collect_host(
        proc_root=str(proc),
        host_root="/host",
        disk_paths=("/host",),
        cpu_sample_seconds=0,
        sleep=lambda _seconds: None,
        statvfs_fn=lambda _path: _Vfs(1, 10, 9, 9),
    )
    assert result["cpu"]["available"] is False
    assert result["cpu"]["reason"].startswith("proc stat not readable:")
    assert result["memory"]["available"] is False
    assert result["memory"]["reason"].startswith("proc meminfo not readable:")
    assert result["available"] is True
