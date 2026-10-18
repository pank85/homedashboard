import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.container_filters import (
    filter_containers,
    filter_count,
    group_containers,
    sort_containers,
    sort_key,
)


def _row(name, state="running", health=None, **extra):
    row = {"name": name, "state": state, "health": health}
    row.update(extra)
    return row


def test_sort_key_ranks_restarting_and_unhealthy_first():
    assert sort_key(_row("b", state="restarting"))[0] == 0
    assert sort_key(_row("b", health="unhealthy"))[0] == 0


def test_sort_key_ranks_running_second():
    assert sort_key(_row("b", state="running"))[0] == 1


def test_sort_key_ranks_other_states_last():
    assert sort_key(_row("b", state="exited"))[0] == 2
    assert sort_key(_row("b", state="paused"))[0] == 2
    assert sort_key(_row("b", state=None))[0] == 2


def test_sort_key_uses_name_and_tolerates_missing_name():
    assert sort_key(_row("alpha")) == (1, "alpha")
    assert sort_key({"state": "running"}) == (1, "")
    assert sort_key({"state": "running", "name": None}) == (1, "")


def test_sort_containers_orders_by_rank_then_name():
    rows = [
        _row("zeta"),
        _row("beta", state="exited"),
        _row("alpha", health="unhealthy"),
        _row("gamma", state="restarting"),
    ]
    assert [row["name"] for row in sort_containers(rows)] == [
        "alpha",
        "gamma",
        "zeta",
        "beta",
    ]


def test_sort_containers_does_not_mutate_input():
    rows = [_row("b"), _row("a")]
    ordered = sort_containers(rows)
    assert ordered is not rows
    assert [row["name"] for row in rows] == ["b", "a"]


def test_filter_containers_preserves_input_order():
    rows = [_row("c"), _row("a"), _row("b")]
    assert [row["name"] for row in filter_containers(rows)] == ["c", "a", "b"]


def test_filter_containers_text_matches_name_case_insensitively():
    rows = [_row("web-app"), _row("db")]
    assert [row["name"] for row in filter_containers(rows, text="WEB")] == [
        "web-app"
    ]
    assert [row["name"] for row in filter_containers(rows, text="zzz")] == []


def test_filter_containers_text_matches_image_and_image_short():
    rows = [
        _row("one", image="ghcr.io/org/app:1.2", image_short="app:1.2"),
        _row("two", image="redis:7", image_short="redis:7"),
    ]
    assert [row["name"] for row in filter_containers(rows, text="APP")] == ["one"]
    assert [row["name"] for row in filter_containers(rows, text="redis")] == [
        "two"
    ]


def test_filter_containers_text_matches_compose_service():
    rows = [_row("proj-api-1", compose_service="api"), _row("proj-db-1", compose_service="db")]
    assert [row["name"] for row in filter_containers(rows, text="svc")] == []
    assert [row["name"] for row in filter_containers(rows, text="api")] == [
        "proj-api-1"
    ]


def test_filter_containers_text_tolerates_missing_and_non_string_fields():
    rows = [{"name": "only-name"}]
    assert filter_containers(rows, text="image") == []
    assert filter_containers(rows, text="only") == rows


def test_filter_containers_state_running():
    rows = [_row("a", state="running"), _row("b", state="exited")]
    assert [row["name"] for row in filter_containers(rows, state="Running")] == ["a"]


def test_filter_containers_state_stopped_includes_restarting():
    rows = [
        _row("a", state="running"),
        _row("b", state="exited"),
        _row("c", state="restarting"),
        _row("d", state="created"),
    ]
    assert [row["name"] for row in filter_containers(rows, state="Stopped")] == [
        "b",
        "c",
        "d",
    ]


def test_filter_containers_unknown_state_means_all():
    rows = [_row("a", state="running"), _row("b", state="exited")]
    assert filter_containers(rows, state="All") == rows
    assert filter_containers(rows, state="bogus") == rows
    assert filter_containers(rows, state="") == rows
    assert filter_containers(rows, state="running") == rows


def test_filter_containers_hide_healthy_drops_only_healthy():
    rows = [
        _row("healthy-row", health="healthy"),
        _row("healthy-label", health=None, health_label="healthy"),
        _row("no-health", health=None),
        _row("unhealthy", health="unhealthy"),
        _row("starting", health="starting"),
    ]
    assert [row["name"] for row in filter_containers(rows, hide_healthy=True)] == [
        "no-health",
        "unhealthy",
        "starting",
    ]


def test_filter_containers_hide_healthy_false_keeps_everything():
    rows = [_row("a", health="healthy"), _row("b", health=None)]
    assert filter_containers(rows, hide_healthy=False) == rows


def test_filter_containers_combines_text_state_and_health():
    rows = [
        _row("web", state="running", health="healthy", image="app"),
        _row("web-old", state="exited", health=None, image="app"),
        _row("db", state="running", health=None, image="postgres"),
    ]
    result = filter_containers(
        rows, text="web", state="Running", hide_healthy=True
    )
    assert result == []


def test_filter_count_string():
    assert filter_count(12, 38) == "12 of 38 shown"
    assert filter_count(0, 0) == "0 of 0 shown"


def test_filters_on_empty_input():
    assert sort_containers([]) == []
    assert filter_containers([]) == []


def test_sort_containers_status_is_default_and_fallback():
    rows = [_row("b"), _row("a", state="exited")]
    assert sort_containers(rows) == sort_containers(rows, "status")
    assert sort_containers(rows, "bogus") == sort_containers(rows, "status")


def test_sort_containers_by_name_casefold_empty_last():
    rows = [_row("Zeta"), _row("alpha"), {"state": "running"}, _row("beta")]
    assert [row.get("name") for row in sort_containers(rows, "name")] == [
        "alpha",
        "beta",
        "Zeta",
        None,
    ]


def test_sort_containers_by_cpu_descending_missing_last():
    rows = [
        _row("low", cpu_percent=1.0),
        _row("none"),
        _row("high", cpu_percent=90.0),
        _row("mid", cpu_percent=50.0),
    ]
    assert [row["name"] for row in sort_containers(rows, "cpu")] == [
        "high",
        "mid",
        "low",
        "none",
    ]


def test_sort_containers_cpu_ties_fall_back_to_name():
    rows = [_row("b", cpu_percent=50.0), _row("a", cpu_percent=50.0)]
    assert [row["name"] for row in sort_containers(rows, "cpu")] == ["a", "b"]


def test_sort_containers_by_memory_percent_then_ratio():
    rows = [
        _row("ratio", memory_used_bytes=512, memory_limit_bytes=1024),
        _row("percent", memory_percent=80.0),
        _row("none"),
        _row("low", memory_percent=5.0),
    ]
    assert [row["name"] for row in sort_containers(rows, "memory")] == [
        "percent",
        "ratio",
        "low",
        "none",
    ]


def test_sort_containers_memory_missing_without_usable_ratio():
    rows = [
        _row("has", memory_percent=10.0),
        _row("no-limit", memory_used_bytes=512, memory_limit_bytes=0),
        _row("no-ratio", memory_used_bytes=512),
    ]
    assert [row["name"] for row in sort_containers(rows, "memory")] == [
        "has",
        "no-limit",
        "no-ratio",
    ]


def test_group_containers_other_last_sorted_and_stable():
    rows = [
        _row("z", compose_project="Zeta"),
        _row("n"),
        _row("a", compose_project="alpha"),
        _row("n2", compose_project=None),
        _row("m", compose_project=""),
    ]
    groups = group_containers(rows)
    assert [name for name, _ in groups] == ["alpha", "Zeta", "Other"]
    assert [row["name"] for row in groups[0][1]] == ["a"]
    assert [row["name"] for row in groups[-1][1]] == ["n", "n2", "m"]


def test_group_containers_preserves_input_order_within_a_group():
    rows = [_row("b", compose_project="p"), _row("a", compose_project="p")]
    assert [row["name"] for _, group in group_containers(rows) for row in group] == [
        "b",
        "a",
    ]


def test_group_containers_empty_input():
    assert group_containers([]) == []


def test_js_module_exports_and_bans_forbidden_text():
    source = (ROOT / "app" / "static" / "container_filters.js").read_text()
    assert "globalThis.filterContainers" in source
    assert "globalThis.filterCount" in source
    assert "globalThis.sortContainers" in source
    assert "globalThis.groupContainers" in source
    assert "innerHTML" not in source
    assert "http://" not in source
    assert "https://" not in source
