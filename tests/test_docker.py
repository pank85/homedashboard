import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
import os
import socket
import threading
import time
from datetime import datetime, timezone

from app.collectors.docker import collect_containers, cpu_percent_from_stats

NOW = datetime(2024, 6, 1, 0, 1, 30, tzinfo=timezone.utc)


class _StatusError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"docker API error: {status}")
        self.status = status


class FakeClient:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, dict | None]] = []

    def get_json(self, path: str, params: dict | None = None):
        self.calls.append((path, params))
        result = self.handler(path, params)
        if isinstance(result, Exception):
            raise result
        return result


def _stats(
    *,
    total: int = 300,
    prev_total: int = 200,
    system: int = 500,
    prev_system: int = 300,
    online: int | None = 2,
    percpu: list | None = None,
    usage: int | None = 10,
    limit: int | None = 20,
    cache: int | None = 7,
    include_precpu: bool = True,
) -> dict:
    cpu_usage: dict = {"total_usage": total}
    if percpu is not None:
        cpu_usage["percpu_usage"] = percpu
    cpu_stats: dict = {"cpu_usage": cpu_usage, "system_cpu_usage": system}
    if online is not None:
        cpu_stats["online_cpus"] = online
    payload: dict = {"cpu_stats": cpu_stats}
    if include_precpu:
        payload["precpu_stats"] = {
            "cpu_usage": {"total_usage": prev_total},
            "system_cpu_usage": prev_system,
        }
    mem: dict = {}
    if usage is not None:
        mem["usage"] = usage
    if limit is not None:
        mem["limit"] = limit
    if cache is not None:
        mem["stats"] = {"cache": cache, "inactive_file": 3}
    payload["memory_stats"] = mem
    return payload


def _inspect(
    name: str,
    status: str,
    *,
    health: str | None = None,
    started_at: str | None = "2024-06-01T00:00:00.123456789Z",
    restart_count: int = 0,
) -> dict:
    state: dict = {"Status": status}
    if started_at is not None:
        state["StartedAt"] = started_at
    if health is not None:
        state["Health"] = {"Status": health}
    return {"Name": "/" + name, "State": state, "RestartCount": restart_count}


def test_missing_socket_degrades(tmp_path):
    socket_path = str(tmp_path / "missing.sock")
    result = collect_containers(socket_path=socket_path)

    assert result["available"] is False
    assert result["containers"] == []
    assert result["reason"] == f"docker socket not reachable: {socket_path}"
    assert result["refreshed_at"]


def test_malformed_json_degrades():
    def handler(path, params):
        raise json.JSONDecodeError("Expecting value", "not-json", 0)

    result = collect_containers(
        socket_path="/does/not/matter.sock",
        client=FakeClient(handler),
        now=NOW,
    )

    assert result["available"] is False
    assert result["containers"] == []
    assert result["reason"] == "malformed JSON from docker API"
    assert result["refreshed_at"] == NOW.isoformat()


def test_list_http_500_degrades_with_empty_containers():
    def handler(path, params):
        raise _StatusError(500)

    result = collect_containers(
        socket_path=str(Path("/tmp") / "not-a-socket"),
        client=FakeClient(handler),
    )

    assert result["available"] is False
    assert result["containers"] == []
    assert result["reason"] == "docker API error: 500"


def test_sort_unhealthy_and_restarting_before_running_by_name():
    # Required order is five names, so the fixture has five rows: unhealthy
    # running `a`, restarting `c`, running healthy `a2` and `b`, exited `d`.
    specs = {
        "d": ("exited", None),
        "b": ("running", "healthy"),
        "a2": ("running", "healthy"),
        "c": ("restarting", None),
        "a": ("running", "unhealthy"),
    }

    def handler(path, params):
        if path.endswith("/containers/json"):
            assert params == {"all": "1"}
            return [
                {
                    "Id": f"id-{name}",
                    "Names": ["/" + name],
                    "Image": f"img:{name}",
                    "State": status,
                }
                for name, (status, _health) in specs.items()
            ]
        for name in specs:
            if path.endswith(f"/containers/id-{name}/json"):
                status, health = specs[name]
                return _inspect(name, status, health=health, restart_count=1)
            if path.endswith(f"/containers/id-{name}/stats"):
                return _stats()
        raise AssertionError(path)

    result = collect_containers(
        socket_path="/injected.sock",
        client=FakeClient(handler),
        now=NOW,
    )

    assert result["available"] is True
    assert result["reason"] is None
    assert [row["name"] for row in result["containers"]] == ["a", "c", "a2", "b", "d"]
    by_name = {row["name"]: row for row in result["containers"]}
    assert by_name["a"]["health"] == "unhealthy"
    assert by_name["a"]["state"] == "running"
    assert by_name["c"]["state"] == "restarting"
    assert by_name["c"]["cpu_percent"] is None
    assert by_name["a2"]["health"] == "healthy"
    assert by_name["d"]["state"] == "exited"
    assert by_name["d"]["uptime_seconds"] is None


def test_cpu_percent_from_stats_delta_and_memory_copied():
    stats = _stats()
    assert cpu_percent_from_stats(stats) == 100.0

    seen = {}

    def handler(path, params):
        if path.endswith("/containers/json"):
            return [
                {
                    "Id": "id-web",
                    "Names": ["/web"],
                    "Image": "nginx:1.25",
                    "State": "running",
                }
            ]
        if path.endswith("/json"):
            return _inspect("web", "running", health="healthy", restart_count=4)
        if path.endswith("/stats"):
            assert params == {"stream": "false"}
            seen["stats"] = True
            return stats
        raise AssertionError(path)

    result = collect_containers(
        socket_path="/injected.sock",
        client=FakeClient(handler),
        now=NOW,
    )

    row = result["containers"][0]
    assert seen["stats"] is True
    assert row["cpu_percent"] == 100.0
    assert row["memory_used_bytes"] == 10
    assert row["memory_limit_bytes"] == 20
    assert row["restart_count"] == 4
    assert row["name"] == "web"
    assert row["image"] == "nginx:1.25"
    assert row["id"] == "id-web"
    # 90s minus the truncated 0.123456 fractional second.
    assert row["uptime_seconds"] == 89


def test_cpu_percent_missing_keys_null_and_non_positive_delta_zero():
    assert cpu_percent_from_stats({}) is None
    assert cpu_percent_from_stats({"cpu_stats": {}, "precpu_stats": {}}) is None
    assert (
        cpu_percent_from_stats(
            _stats(total=5, prev_total=5, system=5, prev_system=5, online=1)
        )
        == 0.0
    )
    assert (
        cpu_percent_from_stats(
            _stats(total=9, prev_total=1, system=1, prev_system=5, online=2)
        )
        == 0.0
    )
    # online_cpus missing: four percpu entries, delta 100 / system 200.
    percpu = cpu_percent_from_stats(
        _stats(online=None, percpu=[1, 1, 1, 1], total=100, prev_total=0, system=200, prev_system=0)
    )
    assert percpu == 200.0
    # online_cpus wins over a longer percpu list.
    assert (
        cpu_percent_from_stats(
            _stats(online=2, percpu=[1, 1, 1, 1], total=100, prev_total=0, system=200, prev_system=0)
        )
        == 100.0
    )


def test_missing_precpu_stats_keeps_container_with_null_cpu():
    def handler(path, params):
        if path.endswith("/containers/json"):
            return [
                {
                    "Id": "id-web",
                    "Names": ["/web"],
                    "Image": "nginx:1",
                    "State": "running",
                }
            ]
        if path.endswith("/json"):
            return _inspect("web", "running")
        if path.endswith("/stats"):
            return _stats(include_precpu=False)
        raise AssertionError(path)

    result = collect_containers(
        socket_path="/injected.sock",
        client=FakeClient(handler),
        now=NOW,
    )

    assert result["available"] is True
    assert len(result["containers"]) == 1
    row = result["containers"][0]
    assert row["name"] == "web"
    assert row["cpu_percent"] is None
    assert row["memory_used_bytes"] == 10
    assert row["memory_limit_bytes"] == 20


def test_inspect_failure_uses_list_fields_and_keeps_siblings():
    def handler(path, params):
        if path.endswith("/containers/json"):
            return [
                {
                    "Id": "id-bad",
                    "Names": ["/from-list"],
                    "Image": "img:1",
                    "State": "running",
                },
                {
                    "Id": "id-good",
                    "Names": ["/ok"],
                    "Image": "img:2",
                    "State": "exited",
                },
            ]
        if path.endswith("/containers/id-bad/json"):
            raise RuntimeError("inspect down")
        if path.endswith("/containers/id-bad/stats"):
            raise RuntimeError("stats down")
        if path.endswith("/containers/id-good/json"):
            return _inspect("ok", "exited", restart_count=3, started_at=None)
        raise AssertionError(path)

    result = collect_containers(
        socket_path="/injected.sock",
        client=FakeClient(handler),
        now=NOW,
    )

    assert result["available"] is True
    assert result["reason"] is None
    by_name = {row["name"]: row for row in result["containers"]}
    bad = by_name["from-list"]
    assert bad["id"] == "id-bad"
    assert bad["image"] == "img:1"
    assert bad["state"] == "running"
    assert bad["health"] is None
    assert bad["uptime_seconds"] is None
    assert bad["restart_count"] == 0
    assert bad["cpu_percent"] is None
    assert bad["memory_used_bytes"] is None
    assert bad["memory_limit_bytes"] is None
    assert by_name["ok"]["restart_count"] == 3
    assert by_name["ok"]["state"] == "exited"


def test_strip_one_leading_slash_and_invalid_started_at():
    def handler(path, params):
        if path.endswith("/containers/json"):
            return [
                {
                    "Id": "id-x",
                    "Names": ["//weird"],
                    "Image": "img:x",
                    "State": "running",
                }
            ]
        if path.endswith("/json"):
            inspected = _inspect("ignored", "running", started_at="not-a-timestamp")
            inspected["Name"] = "//weird"
            return inspected
        if path.endswith("/stats"):
            return _stats(usage=0, limit=20, cache=99)
        raise AssertionError(path)

    result = collect_containers(
        socket_path="/injected.sock",
        client=FakeClient(handler),
        now=NOW,
    )
    row = result["containers"][0]
    assert row["name"] == "/weird"
    assert row["uptime_seconds"] is None
    assert row["memory_used_bytes"] == 0


def test_future_started_at_uptime_is_zero():
    def handler(path, params):
        if path.endswith("/containers/json"):
            return [{"Id": "id-x", "Names": ["/x"], "Image": "img", "State": "running"}]
        if path.endswith("/json"):
            return _inspect("x", "running", started_at="2024-06-01T00:05:00Z")
        if path.endswith("/stats"):
            return _stats()
        raise AssertionError(path)

    result = collect_containers(
        socket_path="/injected.sock",
        client=FakeClient(handler),
        now=NOW,
    )
    assert result["containers"][0]["uptime_seconds"] == 0


def test_collector_source_is_read_only_and_has_no_host_paths():
    text = (ROOT / "app" / "collectors" / "docker.py").read_text()
    assert "app.settings" not in text
    assert "app.main" not in text
    assert "/var/run/docker.sock" not in text
    assert "/home/" not in text
    assert "import httpx" not in text
    assert not (ROOT / "app" / "collectors" / "__init__.py").exists()
    assert not (ROOT / "app" / "__init__.py").exists()


class _UnixHTTPStub:
    def __init__(self, path: Path, handler):
        self.path = str(path)
        self.handler = handler
        self.requests: list[tuple[str, str]] = []
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if path.exists():
            path.unlink()
        self._sock.bind(self.path)
        self._sock.listen(16)
        self._sock.settimeout(0.1)
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=2)
        self._sock.close()
        try:
            Path(self.path).unlink()
        except OSError:
            pass

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                self._handle(conn)
            finally:
                conn.close()

    def _handle(self, conn: socket.socket) -> None:
        data = b""
        conn.settimeout(1)
        while b"\r\n\r\n" not in data and len(data) < 65536:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
        line = data.split(b"\r\n", 1)[0].decode("ascii", "replace")
        parts = line.split(" ")
        method = parts[0] if parts else ""
        target = parts[1] if len(parts) > 1 else ""
        self.requests.append((method, target))
        status, body = self.handler(method, target)
        if isinstance(body, str):
            body = body.encode()
        header = (
            f"HTTP/1.1 {status} X\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")
        conn.sendall(header + body)


def _bindable_sock(tmp_path: Path, name: str) -> Path:
    candidate = tmp_path / name
    if len(str(candidate).encode()) <= 100:
        return candidate
    short_dir = Path("/tmp") / f"t03-{os.getpid()}"
    short_dir.mkdir(exist_ok=True)
    return short_dir / name


def test_default_client_malformed_json(tmp_path):
    sock = _bindable_sock(tmp_path, "bad.sock")

    def handler(method, target):
        return 200, b"not-json"

    with _UnixHTTPStub(sock, handler) as stub:
        result = collect_containers(socket_path=str(sock), timeout=2, now=NOW)

    assert result["available"] is False
    assert result["reason"] == "malformed JSON from docker API"
    assert result["containers"] == []
    assert stub.requests
    assert all(method == "GET" for method, _target in stub.requests)


def test_default_client_http_500(tmp_path):
    sock = _bindable_sock(tmp_path, "err.sock")

    def handler(method, target):
        return 500, b"not-json"

    with _UnixHTTPStub(sock, handler):
        result = collect_containers(socket_path=str(sock), timeout=2, now=NOW)

    assert result["available"] is False
    assert result["reason"] == "docker API error: 500"
    assert result["containers"] == []


def test_default_client_get_only_round_trip(tmp_path):
    sock = _bindable_sock(tmp_path, "ok.sock")
    listed = [
        {"Id": "abc", "Names": ["/web"], "Image": "nginx:1.25", "State": "running"}
    ]
    inspected = _inspect("web", "running", health="healthy", restart_count=2)
    stats = _stats()

    def handler(method, target):
        path = target.split("?", 1)[0]
        if path.endswith("/containers/json"):
            return 200, json.dumps(listed)
        if path.endswith("/containers/abc/json"):
            return 200, json.dumps(inspected)
        if path.endswith("/containers/abc/stats"):
            return 200, json.dumps(stats)
        return 404, b"{}"

    with _UnixHTTPStub(sock, handler) as stub:
        result = collect_containers(
            socket_path=str(sock),
            api_version="v1.41",
            timeout=2,
            now=NOW,
        )

    assert result["available"] is True
    assert result["reason"] is None
    row = result["containers"][0]
    assert row["id"] == "abc"
    assert row["name"] == "web"
    assert row["cpu_percent"] == 100.0
    assert row["memory_used_bytes"] == 10
    assert row["memory_limit_bytes"] == 20
    assert row["uptime_seconds"] == 89
    assert row["health"] == "healthy"
    assert [method for method, _target in stub.requests] == ["GET", "GET", "GET"]
    targets = [target for _method, target in stub.requests]
    assert any(
        target.startswith("/v1.41/containers/json?") and "all=1" in target
        for target in targets
    )
    assert any("stream=false" in target for target in targets)
    assert not any(method != "GET" for method, _target in stub.requests)


def test_rows_identical_across_worker_counts(monkeypatch):
    specs = {
        "d": ("exited", None),
        "b": ("running", "healthy"),
        "a2": ("running", "healthy"),
        "c": ("restarting", None),
        "a": ("running", "unhealthy"),
    }

    def handler(path, params):
        if path.endswith("/containers/json"):
            assert params == {"all": "1"}
            return [
                {
                    "Id": f"id-{name}",
                    "Names": ["/" + name],
                    "Image": f"img:{name}",
                    "State": status,
                }
                for name, (status, _health) in specs.items()
            ]
        for name in specs:
            if path.endswith(f"/containers/id-{name}/json"):
                status, health = specs[name]
                return _inspect(name, status, health=health, restart_count=1)
            if path.endswith(f"/containers/id-{name}/stats"):
                return _stats()
        raise AssertionError(path)

    monkeypatch.setenv("CONTAINER_FETCH_WORKERS", "1")
    sequential = collect_containers(
        socket_path="/injected.sock",
        client=FakeClient(handler),
        now=NOW,
    )
    monkeypatch.setenv("CONTAINER_FETCH_WORKERS", "8")
    concurrent = collect_containers(
        socket_path="/injected.sock",
        client=FakeClient(handler),
        now=NOW,
    )

    assert sequential["available"] is True
    assert concurrent["available"] is True
    # Contents AND order must match: concurrency must not reorder rows.
    assert sequential["containers"] == concurrent["containers"]
    assert [row["name"] for row in concurrent["containers"]] == [
        "a",
        "c",
        "a2",
        "b",
        "d",
    ]


def test_stats_failure_soft_fails_and_stays_available(monkeypatch):
    monkeypatch.setenv("CONTAINER_FETCH_WORKERS", "8")

    def handler(path, params):
        if path.endswith("/containers/json"):
            return [
                {
                    "Id": "id-bad",
                    "Names": ["/bad"],
                    "Image": "img:bad",
                    "State": "running",
                },
                {
                    "Id": "id-ok",
                    "Names": ["/ok"],
                    "Image": "img:ok",
                    "State": "running",
                },
            ]
        if path.endswith("/containers/id-bad/json"):
            return _inspect("bad", "running", health="healthy", restart_count=2)
        if path.endswith("/containers/id-bad/stats"):
            raise RuntimeError("stats down")
        if path.endswith("/containers/id-ok/json"):
            return _inspect("ok", "running", health="healthy")
        if path.endswith("/containers/id-ok/stats"):
            return _stats()
        raise AssertionError(path)

    result = collect_containers(
        socket_path="/injected.sock",
        client=FakeClient(handler),
        now=NOW,
    )

    assert result["available"] is True
    assert result["reason"] is None
    by_name = {row["name"]: row for row in result["containers"]}
    bad = by_name["bad"]
    assert bad["health"] == "healthy"
    assert bad["restart_count"] == 2
    assert bad["cpu_percent"] is None
    assert bad["memory_used_bytes"] is None
    assert bad["memory_limit_bytes"] is None
    assert by_name["ok"]["cpu_percent"] == 100.0
    assert by_name["ok"]["memory_used_bytes"] == 10


def test_worker_exception_falls_back_to_list_only_row(monkeypatch):
    import app.collectors.docker as docker_mod

    monkeypatch.setenv("CONTAINER_FETCH_WORKERS", "4")

    def handler(path, params):
        if path.endswith("/containers/json"):
            return [
                {"Id": "id-a", "Names": ["/a"], "Image": "img:a", "State": "running"},
                {"Id": "id-b", "Names": ["/b"], "Image": "img:b", "State": "running"},
            ]
        raise AssertionError(path)

    def boom(*args, **kwargs):
        raise RuntimeError("worker blew up")

    monkeypatch.setattr(docker_mod, "_one_container", boom)

    result = collect_containers(
        socket_path="/injected.sock",
        client=FakeClient(handler),
        now=NOW,
    )

    assert result["available"] is True
    assert result["reason"] is None
    by_name = {row["name"]: row for row in result["containers"]}
    assert set(by_name) == {"a", "b"}
    for row in by_name.values():
        assert row["cpu_percent"] is None
        assert row["memory_used_bytes"] is None
        assert row["memory_limit_bytes"] is None
        assert row["uptime_seconds"] is None
        assert row["restart_count"] == 0


def test_concurrent_fetches_respect_worker_bound(monkeypatch):
    monkeypatch.setenv("CONTAINER_FETCH_WORKERS", "3")
    names = [f"c{i}" for i in range(9)]
    lock = threading.Lock()
    state = {"inflight": 0, "peak": 0}

    class TrackingClient:
        def get_json(self, path, params=None):
            with lock:
                state["inflight"] += 1
                state["peak"] = max(state["peak"], state["inflight"])
            try:
                time.sleep(0.02)
                if path.endswith("/containers/json"):
                    return [
                        {
                            "Id": f"id-{name}",
                            "Names": ["/" + name],
                            "Image": "img:1",
                            "State": "running",
                        }
                        for name in names
                    ]
                if path.endswith("/json"):
                    return _inspect("x", "running")
                if path.endswith("/stats"):
                    return _stats()
                raise AssertionError(path)
            finally:
                with lock:
                    state["inflight"] -= 1

    result = collect_containers(
        socket_path="/injected.sock",
        client=TrackingClient(),
        now=NOW,
    )

    assert result["available"] is True
    assert len(result["containers"]) == len(names)
    # Never exceeds the configured bound, and did run concurrently.
    assert state["peak"] <= 3
    assert state["peak"] >= 2


def test_worker_count_coerced_to_minimum_one(monkeypatch):
    def handler(path, params):
        if path.endswith("/containers/json"):
            return [
                {"Id": "id-a", "Names": ["/a"], "Image": "img:a", "State": "exited"}
            ]
        raise AssertionError(path)

    for raw in ("0", "-4", "not-a-number", ""):
        monkeypatch.setenv("CONTAINER_FETCH_WORKERS", raw)
        result = collect_containers(
            socket_path="/injected.sock",
            client=FakeClient(handler),
            now=NOW,
        )
        assert result["available"] is True
        assert [row["name"] for row in result["containers"]] == ["a"]
