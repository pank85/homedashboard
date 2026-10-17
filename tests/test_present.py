"""Tests for app.present. Imports only app.present."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.present import present_dashboard  # noqa: E402


def _payload():
    return {
        "containers": {
            "available": True,
            "containers": [
                {
                    "name": "web",
                    "image": "ghcr.io/org/app:1.2",
                    "state": "running",
                    "health": "healthy",
                    "uptime_seconds": 42,
                    "restart_count": 1,
                    "cpu_percent": 12.5,
                    "memory_used_bytes": 524288000,
                    "memory_limit_bytes": 1073741824,
                },
                {
                    "name": "db",
                    "image": "redis",
                    "state": "exited",
                    "health": None,
                    "uptime_seconds": None,
                    "cpu_percent": None,
                    "memory_used_bytes": None,
                    "memory_limit_bytes": None,
                },
            ],
        },
        "agents": {
            "agents": [
                {"source": "herdr", "label": "one", "elapsed_seconds": 42},
                {"source": "proc", "label": "two", "elapsed_seconds": None},
            ],
        },
        "host": {
            "available": True,
            "cpu": {"percent": 25.0, "cores": 4},
            "memory": {
                "used_bytes": 2147483648,
                "total_bytes": 8589934592,
                "percent": 25.0,
            },
            "disks": [
                {
                    "used_bytes": 1073741824,
                    "total_bytes": 2147483648,
                    "percent": 50.0,
                }
            ],
        },
        "sessions": {
            "available": True,
            "sessions": [
                {
                    "id": "abc",
                    "created_at": "2024-06-01T00:00:00Z",
                    "updated_at": "2024-06-01T00:00:12Z",
                }
            ],
        },
    }


def test_present_dashboard_empty_does_not_raise():
    assert present_dashboard({}) == {}


def test_present_dashboard_non_dict_does_not_raise():
    present_dashboard(None)


def test_present_container_adds_human_keys_and_keeps_raw_bytes():
    out = present_dashboard(_payload())
    row = out["containers"]["containers"][0]
    assert row["uptime_human"] == "42s"
    assert row["cpu_percent_human"] == "12.5%"
    assert row["memory_used_human"] == "500.0 MiB"
    assert row["memory_limit_human"] == "1.0 GiB"
    assert row["image_short"] == "app:1.2"
    assert row["state_label"] == "running"
    assert row["health_label"] == "healthy"
    assert row["memory_used_bytes"] == 524288000
    assert row["memory_limit_bytes"] == 1073741824
    assert row["memory_percent_human"] == "48.8%"
    assert 48.8 < row["memory_percent"] < 48.9


def test_present_container_exited_null_stats():
    out = present_dashboard(_payload())
    row = out["containers"]["containers"][1]
    assert row["uptime_human"] == "unknown"
    assert row["cpu_percent_human"] == "unknown"
    assert row["memory_used_human"] == "unknown"
    assert row["memory_limit_human"] == "unknown"
    assert row["health_label"] == "none"
    assert row["image_short"] == "redis"
    assert "memory_percent" not in row


def test_present_host_adds_human_keys():
    out = present_dashboard(_payload())
    host = out["host"]
    assert host["cpu"]["percent_human"] == "25.0%"
    assert host["memory"]["used_human"] == "2.0 GiB"
    assert host["memory"]["total_human"] == "8.0 GiB"
    assert host["memory"]["percent_human"] == "25.0%"
    assert host["disks"][0]["used_human"] == "1.0 GiB"
    assert host["disks"][0]["total_human"] == "2.0 GiB"
    assert host["disks"][0]["percent_human"] == "50.0%"


def test_present_agent_elapsed_human():
    out = present_dashboard(_payload())
    rows = out["agents"]["agents"]
    assert rows[0]["elapsed_human"] == "42s"
    assert rows[1]["elapsed_human"] == "unknown"


def test_present_sessions_relative_fields():
    out = present_dashboard(_payload())
    row = out["sessions"]["sessions"][0]
    assert row["created_relative"].endswith("ago")
    assert row["updated_relative"].endswith("ago")
    assert row["created_at"] == "2024-06-01T00:00:00Z"


def test_present_dashboard_is_idempotent():
    once = present_dashboard(_payload())
    twice = present_dashboard(once)
    assert once == twice


def test_present_dashboard_does_not_mutate_input():
    payload = _payload()
    before = payload["containers"]["containers"][0].copy()
    present_dashboard(payload)
    assert payload["containers"]["containers"][0] == before


def test_present_dashboard_passes_partial_payloads_through():
    assert present_dashboard({"containers": None})["containers"] is None
    assert present_dashboard({"host": {}})["host"] == {}


def test_present_dashboard_retains_generated_keys():
    payload = _payload()
    payload["generated_at"] = "2024-06-01T00:00:00Z"
    out = present_dashboard(payload)
    assert out["generated_at"] == "2024-06-01T00:00:00Z"
