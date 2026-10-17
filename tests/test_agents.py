import json
import subprocess
from pathlib import Path

from app.collectors.agents import (
    collect_agents,
    normalize_status,
    parse_herdr_agent_list,
    parse_herdr_snapshot,
    parse_herdr_workspace_list,
    process_cpu_percent,
)

AGENT_LIST = """
{"id":"cli:agent:list","result":{"type":"agent_list","agents":[{"agent":"claude","agent_session":{"agent":"claude","kind":"session","source":"file","value":"sess-1"},"agent_status":"working","cwd":"/work","foreground_cwd":"/work/sub","pane_id":"p1","tab_id":"t1","terminal_title":"Claude","terminal_title_stripped":"Claude","workspace_id":"ws1"}]}}
""".strip()

WORKSPACE_LIST = """
{"id":"cli:workspace:list","result":{"type":"workspace_list","workspaces":[{"active_tab_id":"t1","agent_status":"working","focused":true,"label":"demo","number":1,"pane_count":1,"tab_count":1,"workspace_id":"ws1"}]}}
""".strip()

SNAPSHOT = """
{"id":"cli:api:snapshot","result":{"snapshot":{"agents":[{"agent":"codex","agent_status":"idle","cwd":"/tmp","workspace_id":"ws2","terminal_title_stripped":"Codex"}]}}}
""".strip()

EMPTY_AGENT_LIST = json.dumps(
    {"id": "cli:agent:list", "result": {"type": "agent_list", "agents": []}}
)

EMPTY_SNAPSHOT = json.dumps(
    {"id": "cli:api:snapshot", "result": {"snapshot": {"agents": []}}}
)

READONLY = (
    ("workspace", "list"),
    ("agent", "list"),
    ("api", "snapshot"),
)


class Result:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _runner(responses: dict[tuple[str, ...], object], calls: list[list[str]]):
    def run(argv, timeout):
        calls.append(list(argv))
        assert timeout == 3.0
        assert tuple(argv[1:]) in READONLY
        assert "prompt" not in argv
        assert "send-keys" not in argv
        assert "start" not in argv
        assert "pane" not in argv
        key = tuple(argv[1:])
        value = responses[key]
        if isinstance(value, Exception):
            raise value
        return value

    return run


def _stat_line(pid: int, comm: str, ppid: int, utime: int, stime: int, starttime: int, rss: int) -> str:
    tail = [
        "S",
        str(ppid),
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        str(utime),
        str(stime),
        "0",
        "0",
        "20",
        "0",
        "1",
        "0",
        str(starttime),
        "0",
        str(rss),
    ]
    return f"{pid} ({comm}) " + " ".join(tail) + "\n"


def _write_pid(
    proc_root: Path,
    pid: int,
    comm: str,
    ppid: int,
    rss: int,
    *,
    utime: int = 0,
    stime: int = 0,
    starttime: int = 100,
    argv0: str | None = None,
    stat_comm: str | None = None,
) -> None:
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir(parents=True, exist_ok=True)
    (pid_dir / "comm").write_text(comm + "\n", encoding="utf-8")
    (pid_dir / "cmdline").write_bytes((argv0 or comm).encode() + b"\0")
    (pid_dir / "stat").write_text(
        _stat_line(pid, stat_comm or comm, ppid, utime, stime, starttime, rss),
        encoding="utf-8",
    )


def _write_cpu(proc_root: Path, total: int, ncpu: int = 2) -> None:
    lines = [f"cpu {total} 0 0 0 0 0 0 0"]
    lines.extend(f"cpu{index} 0 0 0 0 0 0 0" for index in range(ncpu))
    (proc_root / "stat").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_cpu_iowait(proc_root: Path, iowait: int, ncpu: int = 2) -> None:
    # Host total sums the eight fields once. iowait 50 is total 50, not 100.
    lines = [f"cpu 0 0 0 0 {iowait} 0 0 0"]
    lines.extend(f"cpu{index} 0 0 0 0 0 0 0 0" for index in range(ncpu))
    (proc_root / "stat").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_uptime(proc_root: Path, seconds: float = 1000.0) -> None:
    (proc_root / "uptime").write_text(f"{seconds} 0.0\n", encoding="utf-8")


def test_parse_contract_fixtures_join_workspace_label():
    agents = parse_herdr_agent_list(AGENT_LIST + "\n")
    workspaces = parse_herdr_workspace_list(WORKSPACE_LIST + "\n")
    assert workspaces[0]["workspace_id"] == "ws1"
    assert workspaces[0]["label"] == "demo"
    assert agents[0]["workspace_id"] == "ws1"
    assert agents[0]["label"] == "Claude"
    assert agents[0]["status"] == "working"
    assert agents[0]["cwd"] == "/work"
    assert agents[0]["session"] == "sess-1"
    labels = {item["workspace_id"]: item["label"] for item in workspaces}
    assert labels[agents[0]["workspace_id"]] == "demo"

    calls: list[list[str]] = []
    payload = collect_agents(
        runner=_runner(
            {
                ("workspace", "list"): Result(WORKSPACE_LIST),
                ("agent", "list"): Result(AGENT_LIST),
            },
            calls,
        ),
        proc_root="/proc-not-used-for-parse",
        sleep=lambda _seconds: None,
        page_size=4096,
        clock_ticks=100,
    )
    row = payload["agents"][0]
    assert set(row) == {
        "source",
        "workspace_label",
        "label",
        "status",
        "cwd",
        "session",
        "pid",
        "rss_bytes",
        "cpu_percent",
        "elapsed_seconds",
    }
    assert row["source"] == "herdr"
    assert row["workspace_label"] == "demo"
    assert row["label"] == "Claude"
    assert row["status"] == "working"
    assert row["cwd"] == "/work"
    assert row["session"] == "sess-1"
    assert row["pid"] is None
    assert ("api", "snapshot") not in [tuple(call[1:]) for call in calls]


def test_status_sleeping_is_unknown_and_empty_titles_use_agent():
    assert normalize_status("sleeping") == "unknown"
    assert normalize_status(" Working ") == "working"
    assert normalize_status(None) == "unknown"
    stdout = json.dumps(
        {
            "id": "cli:agent:list",
            "result": {
                "type": "agent_list",
                "agents": [
                    {
                        "agent": "claude",
                        "agent_status": "sleeping",
                        "terminal_title": "",
                        "terminal_title_stripped": "   ",
                        "tab_id": "t9",
                        "cwd": "",
                        "foreground_cwd": "/work/sub",
                    }
                ],
            },
        }
    )
    row = parse_herdr_agent_list(stdout)[0]
    assert row["status"] == "unknown"
    assert row["label"] == "claude"
    assert row["cwd"] == "/work/sub"


def test_malformed_json_still_scans_proc(tmp_path: Path):
    _write_cpu(tmp_path, 100)
    _write_uptime(tmp_path)
    _write_pid(tmp_path, 20, "claude", 1, rss=4)
    calls: list[list[str]] = []

    def run(argv, timeout):
        calls.append(list(argv))
        return Result("not-json")

    payload = collect_agents(
        runner=run,
        proc_root=str(tmp_path),
        sleep=lambda _seconds: None,
        page_size=4096,
        clock_ticks=100,
        cpu_sample_seconds=0,
    )
    herdr = payload["sources"][0]
    proc = payload["sources"][1]
    assert herdr["name"] == "herdr"
    assert herdr["error"] == "malformed JSON from herdr"
    assert herdr["used"] is False
    assert herdr["count"] == 0
    assert proc["used"] is True
    assert proc["count"] == 1
    assert payload["agents"][0]["source"] == "proc"
    assert payload["agents"][0]["pid"] == 20
    assert payload["available"] is True
    assert payload["reason"] is None
    assert all(call[1:] != ["api", "snapshot"] for call in calls)


def test_herdr_not_found(tmp_path: Path):
    def run(argv, timeout):
        raise FileNotFoundError(argv[0])

    payload = collect_agents(
        herdr_bin="missing-herdr",
        runner=run,
        proc_root=str(tmp_path),
        sleep=lambda _seconds: None,
        page_size=4096,
        clock_ticks=100,
    )
    assert payload["sources"][0]["error"] == "herdr not found: missing-herdr"
    assert payload["sources"][0]["used"] is False
    assert payload["sources"][1]["name"] == "proc"
    assert payload["sources"][1]["used"] is True
    assert payload["available"] is True
    assert payload["note"] == "no agents detected"


def test_herdr_timeout_and_nonzero_exit(tmp_path: Path):
    def timeout_runner(argv, timeout):
        raise subprocess.TimeoutExpired(argv, timeout)

    timed_out = collect_agents(
        runner=timeout_runner,
        proc_root=str(tmp_path),
        sleep=lambda _seconds: None,
        page_size=4096,
        clock_ticks=100,
    )
    assert timed_out["sources"][0]["error"] == "herdr timed out"

    exited = collect_agents(
        runner=lambda argv, timeout: Result("not-json", returncode=2),
        proc_root=str(tmp_path),
        sleep=lambda _seconds: None,
        page_size=4096,
        clock_ticks=100,
    )
    assert exited["sources"][0]["error"] == "herdr exited 2"
    assert exited["available"] is True


def test_empty_agent_list_uses_snapshot(tmp_path: Path):
    calls: list[list[str]] = []
    payload = collect_agents(
        runner=_runner(
            {
                ("workspace", "list"): Result(WORKSPACE_LIST),
                ("agent", "list"): Result(EMPTY_AGENT_LIST),
                ("api", "snapshot"): Result(SNAPSHOT + "\n"),
            },
            calls,
        ),
        proc_root=str(tmp_path),
        sleep=lambda _seconds: None,
        page_size=4096,
        clock_ticks=100,
    )
    assert [call[1:] for call in calls] == [
        ["workspace", "list"],
        ["agent", "list"],
        ["api", "snapshot"],
    ]
    parsed = parse_herdr_snapshot(SNAPSHOT)
    assert parsed[0]["label"] == "Codex"
    assert parsed[0]["status"] == "idle"
    row = payload["agents"][0]
    assert row["source"] == "herdr"
    assert row["label"] == "Codex"
    assert row["status"] == "idle"
    assert row["cwd"] == "/tmp"
    assert row["workspace_label"] == "ws2"
    assert row["session"] == ""


def test_proc_rolls_child_rss_and_pi_does_not_match_python(tmp_path: Path):
    _write_cpu(tmp_path, 100)
    _write_uptime(tmp_path, 1000.0)
    _write_pid(tmp_path, 20, "claude", 1, rss=10, utime=1, stime=0, starttime=100, stat_comm="cla)ude")
    _write_pid(tmp_path, 21, "python", 20, rss=5, argv0="/usr/bin/python")
    _write_pid(tmp_path, 30, "spider", 1, rss=9, argv0="spider")
    slept: list[float] = []

    payload = collect_agents(
        runner=lambda argv, timeout: Result(EMPTY_AGENT_LIST if argv[1] != "api" else EMPTY_SNAPSHOT)
        if argv[1:] != ["workspace", "list"]
        else Result(WORKSPACE_LIST),
        proc_root=str(tmp_path),
        patterns=("claude", "opencode", "pi", "muse", "codex", "aider", "gemini", "hermes"),
        sleep=slept.append,
        cpu_sample_seconds=0,
        page_size=4096,
        clock_ticks=100,
    )
    proc_rows = [row for row in payload["agents"] if row["source"] == "proc"]
    assert [row["pid"] for row in proc_rows] == [20]
    assert 21 not in [row["pid"] for row in proc_rows]
    assert proc_rows[0]["rss_bytes"] == (10 + 5) * 4096
    assert proc_rows[0]["label"] == "claude"
    assert proc_rows[0]["status"] == "unknown"
    assert proc_rows[0]["workspace_label"] == ""
    assert proc_rows[0]["session"] == ""
    assert proc_rows[0]["elapsed_seconds"] == 999
    assert slept == [0]
    assert payload["sources"][1]["count"] == 1
    assert payload["sources"][1]["used"] is True


def test_process_cpu_percent_and_proc_sample():
    assert process_cpu_percent(10, 20, 100, 200, 2) == 20.0
    assert process_cpu_percent(1, 1, 5, 5, 2) == 0.0


def test_proc_cpu_uses_two_samples(tmp_path: Path):
    # iowait 50 → total 50; iowait 100 → total 100. Delta 50, ticks 10, ncpu 2
    # → cpu_percent 40.0. Double-counting iowait would report 20.0.
    _write_cpu_iowait(tmp_path, 50, ncpu=2)
    _write_uptime(tmp_path, 50.0)
    _write_pid(tmp_path, 20, "claude", 1, rss=1, utime=10, stime=0, starttime=0)
    cwd = tmp_path / "20" / "cwd"
    cwd.symlink_to("/work")

    def pause(_seconds: float) -> None:
        _write_cpu_iowait(tmp_path, 100, ncpu=2)
        _write_pid(tmp_path, 20, "claude", 1, rss=1, utime=20, stime=0, starttime=0)
        if not cwd.exists() and not cwd.is_symlink():
            cwd.symlink_to("/work")

    payload = collect_agents(
        runner=lambda argv, timeout: Result(EMPTY_AGENT_LIST if argv[1:] != ["api", "snapshot"] else EMPTY_SNAPSHOT),
        proc_root=str(tmp_path),
        sleep=pause,
        cpu_sample_seconds=0.2,
        page_size=100,
        clock_ticks=100,
        patterns=("claude", "pi"),
    )
    row = payload["agents"][0]
    assert row["pid"] == 20
    assert row["cpu_percent"] == 40.0
    assert row["label"] == "claude"
    assert row["cwd"] == "/work"


def test_both_sources_empty_is_not_an_error(tmp_path: Path):
    calls: list[list[str]] = []
    payload = collect_agents(
        runner=_runner(
            {
                ("workspace", "list"): Result(WORKSPACE_LIST),
                ("agent", "list"): Result(EMPTY_AGENT_LIST),
                ("api", "snapshot"): Result(EMPTY_SNAPSHOT),
            },
            calls,
        ),
        proc_root=str(tmp_path),
        sleep=lambda _seconds: None,
        page_size=4096,
        clock_ticks=100,
    )
    assert payload["note"] == "no agents detected"
    assert payload["available"] is True
    assert payload["reason"] is None
    assert payload["agents"] == []
    assert payload["sources"][0]["used"] is True
    assert payload["sources"][0]["error"] is None
    assert payload["sources"][0]["count"] == 0
    assert payload["sources"][1]["used"] is True
    assert payload["sources"][1]["error"] is None
    assert payload["sources"][1]["count"] == 0
    assert payload["sources"][0]["refreshed_at"]
    assert payload["sources"][1]["refreshed_at"]
    assert [call[1:] for call in calls] == [list(item) for item in READONLY]


def test_both_sources_combined_without_dedupe(tmp_path: Path):
    _write_cpu(tmp_path, 10)
    _write_uptime(tmp_path)
    _write_pid(tmp_path, 20, "claude", 1, rss=2)
    calls: list[list[str]] = []
    payload = collect_agents(
        runner=_runner(
            {
                ("workspace", "list"): Result(WORKSPACE_LIST),
                ("agent", "list"): Result(AGENT_LIST),
            },
            calls,
        ),
        proc_root=str(tmp_path),
        sleep=lambda _seconds: None,
        page_size=4096,
        clock_ticks=100,
    )
    assert [row["source"] for row in payload["agents"]] == ["herdr", "proc"]
    assert payload["agents"][0]["label"] == "Claude"
    assert payload["agents"][1]["pid"] == 20
    assert payload["agents"][1]["label"] == "claude"
    assert payload["note"] is None
    assert payload["sources"][0]["count"] == 1
    assert payload["sources"][1]["count"] == 1
    assert ("api", "snapshot") not in [tuple(call[1:]) for call in calls]
    assert all(tuple(call[1:]) in READONLY[:2] for call in calls)


def test_runner_argv_is_readonly_and_snapshot_absent_when_agents_present():
    calls: list[list[str]] = []
    collect_agents(
        herdr_bin="herdr",
        runner=_runner(
            {
                ("workspace", "list"): Result(WORKSPACE_LIST),
                ("agent", "list"): Result(AGENT_LIST),
            },
            calls,
        ),
        proc_root="/this/proc/does/not/exist",
        sleep=lambda _seconds: None,
    )
    assert calls == [
        ["herdr", "workspace", "list"],
        ["herdr", "agent", "list"],
    ]
    flat = [part for call in calls for part in call]
    for forbidden in ("prompt", "send-keys", "start", "pane"):
        assert forbidden not in flat


def test_proc_root_missing_does_not_raise(tmp_path: Path):
    missing = tmp_path / "missing-proc"
    payload = collect_agents(
        runner=lambda argv, timeout: Result(EMPTY_AGENT_LIST if argv[1:] != ["api", "snapshot"] else EMPTY_SNAPSHOT),
        proc_root=str(missing),
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep")),
        page_size=4096,
        clock_ticks=100,
    )
    assert payload["sources"][1]["error"] == f"proc not readable: {missing}"
    assert payload["sources"][1]["used"] is False
    assert payload["available"] is True
    assert payload["note"] == "no agents detected"


def test_argv0_basename_matches_when_comm_does_not(tmp_path: Path):
    _write_cpu(tmp_path, 1)
    _write_uptime(tmp_path, 10.0)
    _write_pid(tmp_path, 7, "node", 1, rss=3, argv0="/opt/bin/claude")
    payload = collect_agents(
        runner=lambda argv, timeout: Result(EMPTY_SNAPSHOT),
        proc_root=str(tmp_path),
        sleep=lambda _seconds: None,
        page_size=10,
        clock_ticks=100,
        patterns=("claude", "pi"),
    )
    assert payload["agents"][0]["pid"] == 7
    assert payload["agents"][0]["label"] == "claude"
    assert payload["agents"][0]["rss_bytes"] == 30


def test_matching_descendant_is_not_a_separate_row(tmp_path: Path):
    _write_cpu(tmp_path, 1)
    _write_uptime(tmp_path)
    _write_pid(tmp_path, 20, "claude", 1, rss=2)
    _write_pid(tmp_path, 21, "python", 20, rss=3)
    _write_pid(tmp_path, 22, "claude", 21, rss=4)
    payload = collect_agents(
        runner=lambda argv, timeout: Result(EMPTY_SNAPSHOT),
        proc_root=str(tmp_path),
        sleep=lambda _seconds: None,
        page_size=100,
        clock_ticks=100,
        patterns=("claude",),
    )
    assert [row["pid"] for row in payload["agents"]] == [20]
    assert payload["agents"][0]["rss_bytes"] == (2 + 3 + 4) * 100
