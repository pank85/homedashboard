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


def test_present_agent_adds_rss_and_cpu_human():
    payload = {
        "agents": {
            "agents": [
                {
                    "source": "proc",
                    "rss_bytes": 524288000,
                    "cpu_percent": 12.5,
                },
                {
                    "source": "proc",
                    "rss_bytes": None,
                    "cpu_percent": None,
                },
            ]
        }
    }
    rows = present_dashboard(payload)["agents"]["agents"]
    assert rows[0]["rss_human"] == "500.0 MiB"
    assert rows[0]["cpu_percent_human"] == "12.5%"
    assert rows[0]["rss_bytes"] == 524288000
    assert rows[0]["cpu_percent"] == 12.5
    assert rows[1]["rss_human"] == "unknown"
    assert rows[1]["cpu_percent_human"] == "unknown"


def test_present_agent_omits_rss_and_cpu_human_when_absent():
    payload = {"agents": {"agents": [{"source": "herdr"}]}}
    row = present_dashboard(payload)["agents"]["agents"][0]
    assert "rss_human" not in row
    assert "cpu_percent_human" not in row


def test_present_git_projects_add_commit_relative():
    payload = {
        "git": {
            "available": True,
            "projects": [
                {
                    "name": "repo",
                    "commit_at": "2024-06-01T00:00:00Z",
                },
                {
                    "name": "packed",
                    "commit_at": "",
                },
            ],
        }
    }
    out = present_dashboard(payload)
    projects = out["git"]["projects"]
    assert projects[0]["commit_relative"].endswith("ago")
    assert projects[1]["commit_relative"] == "unknown"
    assert projects[0]["commit_at"] == "2024-06-01T00:00:00Z"


def test_present_git_missing_key_unchanged():
    out = present_dashboard({"generated_at": "2024-06-01T00:00:00Z"})
    assert "git" not in out


def test_present_git_non_dict_unchanged():
    out = present_dashboard({"git": None})
    assert out == {"git": None}


def test_present_git_non_list_projects_unchanged():
    out = present_dashboard({"git": {"projects": None}})
    assert out["git"] == {"projects": None}


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


def test_present_container_levels_use_default_thresholds():
    rows = present_dashboard(_payload())["containers"]["containers"]
    assert rows[0]["cpu_level"] == "ok"
    assert rows[0]["memory_level"] == "ok"
    assert "cpu_level" not in rows[1]
    assert "memory_level" not in rows[1]


def test_present_container_level_boundaries():
    for cpu, word in ((90.0, "crit"), (89.9, "warn"), (75.0, "warn"), (74.9, "ok")):
        payload = {"containers": {"available": True, "containers": [{"cpu_percent": cpu}]}}
        row = present_dashboard(payload)["containers"]["containers"][0]
        assert row["cpu_level"] == word, cpu
    for memory, word in ((90.0, "crit"), (89.9, "warn"), (75.0, "warn"), (74.9, "ok")):
        payload = {
            "containers": {
                "available": True,
                "containers": [
                    {
                        "memory_used_bytes": int(round(memory * 10)),
                        "memory_limit_bytes": 1000,
                    }
                ],
            }
        }
        row = present_dashboard(payload)["containers"]["containers"][0]
        assert row["memory_level"] == word, memory
        assert abs(row["memory_percent"] - memory) < 1e-9


def test_present_container_levels_custom_thresholds():
    payload = _payload()
    rows = payload["containers"]["containers"]
    rows[0]["cpu_percent"] = 65.0
    rows[1]["cpu_percent"] = 85.0
    default = present_dashboard(payload)["containers"]["containers"]
    assert default[0]["cpu_level"] == "ok"
    assert default[1]["cpu_level"] == "warn"
    custom = present_dashboard(payload, cpu_warn=60.0, cpu_crit=80.0)
    custom_rows = custom["containers"]["containers"]
    assert custom_rows[0]["cpu_level"] == "warn"
    assert custom_rows[1]["cpu_level"] == "crit"
    memory_payload = {
        "containers": {
            "available": True,
            "containers": [
                {"memory_used_bytes": 650, "memory_limit_bytes": 1000},
                {"memory_used_bytes": 850, "memory_limit_bytes": 1000},
            ],
        }
    }
    memory_rows = present_dashboard(
        memory_payload, mem_warn=60.0, mem_crit=80.0
    )["containers"]["containers"]
    assert memory_rows[0]["memory_level"] == "warn"
    assert memory_rows[1]["memory_level"] == "crit"


def test_present_container_levels_omit_keys_for_unknown_stats():
    rows = present_dashboard(_payload())["containers"]["containers"]
    assert "cpu_level" not in rows[1]
    assert "memory_level" not in rows[1]
    payload = {
        "containers": {
            "available": True,
            "containers": [{"cpu_percent": "unknown"}],
        }
    }
    row = present_dashboard(payload)["containers"]["containers"][0]
    assert "cpu_level" not in row
    assert row["cpu_percent_human"] == "unknown"


def test_present_module_stays_pure():
    source = (ROOT / "app" / "present.py").read_text(encoding="utf-8")
    assert "import settings" not in source
    assert "app.settings" not in source
    assert "from app.collectors" not in source
