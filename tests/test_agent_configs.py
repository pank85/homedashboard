import json
from pathlib import Path

from app.agent_configs import discover_agent_configs
from app.collectors.agents import collect_agents

ROOT = Path(__file__).resolve().parents[1]


def _write(tmp_path: Path, relative: str, text: str) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _rows_by_kind(rows: list[dict]) -> dict[str, dict]:
    return {row["kind"]: row for row in rows}


def test_four_files_present_under_tmp_path(tmp_path):
    _write(tmp_path, ".claude/settings.json", json.dumps({"model": "claude-sonnet"}))
    _write(
        tmp_path,
        ".pi/agent/settings.json",
        json.dumps({"defaultModel": "gpt-5.1", "defaultProvider": "openai"}),
    )
    _write(
        tmp_path, ".config/opencode/opencode.json", json.dumps({"model": "opencode-go/x"})
    )
    _write(
        tmp_path,
        ".hermes/config.yaml",
        "model:\n  default: hermes-3\n  provider: local\n",
    )
    rows = discover_agent_configs(str(tmp_path))
    assert [row["kind"] for row in rows] == ["claude", "pi", "opencode", "hermes"]
    for row in rows:
        assert row["source"] == "config"
        assert row["workspace_label"] == "installed"
        assert row["label"] == row["tab_label"]
        assert row["status"] == "installed"
        assert row["config_present"] is True
        assert row["pid"] is None
        assert row["rss_bytes"] is None
        assert row["cpu_percent"] is None
        assert row["elapsed_seconds"] is None
        assert row["elapsed_source"] == "unknown"


def test_four_files_absent_under_tmp_path(tmp_path):
    rows = discover_agent_configs(str(tmp_path))
    assert [row["kind"] for row in rows] == ["claude", "pi", "opencode", "hermes"]
    for row in rows:
        assert row["status"] == "absent"
        assert row["config_present"] is False
        assert row["model"] == ""
        assert row["provider"] == ""


def test_claude_model_kept_and_env_token_not_kept(tmp_path):
    _write(
        tmp_path,
        ".claude/settings.json",
        json.dumps(
            {
                "model": "claude-sonnet",
                "env": {"ANTHROPIC_AUTH_TOKEN": "super-secret-token"},
            }
        ),
    )
    rows = discover_agent_configs(str(tmp_path))
    row = _rows_by_kind(rows)["claude"]
    assert row["model"] == "claude-sonnet"
    assert row["config_path"] == ".claude/settings.json"
    assert "super-secret-token" not in json.dumps(rows)


def test_pi_default_model_kept_and_device_id_not_kept(tmp_path):
    _write(
        tmp_path,
        ".pi/agent/settings.json",
        json.dumps(
            {
                "defaultModel": "gpt-5.1",
                "defaultProvider": "openai",
                "deviceId": "device-secret-value",
            }
        ),
    )
    rows = discover_agent_configs(str(tmp_path))
    row = _rows_by_kind(rows)["pi"]
    assert row["model"] == "gpt-5.1"
    assert row["provider"] == "openai"
    assert "device-secret-value" not in json.dumps(rows)


def test_opencode_provider_api_key_not_kept(tmp_path):
    _write(
        tmp_path,
        ".config/opencode/opencode.json",
        json.dumps(
            {
                "model": "opencode-go/x",
                "providers": {"litellm": {"apiKey": "super-secret-token"}},
            }
        ),
    )
    rows = discover_agent_configs(str(tmp_path))
    row = _rows_by_kind(rows)["opencode"]
    assert row["model"] == "opencode-go/x"
    assert "super-secret-token" not in json.dumps(rows)


def test_hermes_model_block_read_and_provider_secret_not_kept(tmp_path):
    _write(
        tmp_path,
        ".hermes/config.yaml",
        "model:\n  default: hermes-3\n  provider: local\n"
        "providers:\n  api_key: super-secret-token\n",
    )
    rows = discover_agent_configs(str(tmp_path))
    row = _rows_by_kind(rows)["hermes"]
    assert row["model"] == "hermes-3"
    assert row["provider"] == "local"
    assert "super-secret-token" not in json.dumps(rows)


def test_secret_prefixed_model_becomes_empty(tmp_path):
    _write(tmp_path, ".claude/settings.json", json.dumps({"model": "sk-live-secret"}))
    rows = discover_agent_configs(str(tmp_path))
    assert _rows_by_kind(rows)["claude"]["model"] == ""


def test_malformed_json_does_not_raise_and_hides_bad_text(tmp_path):
    _write(tmp_path, ".claude/settings.json", "{not json at all")
    rows = discover_agent_configs(str(tmp_path))
    row = _rows_by_kind(rows)["claude"]
    assert row["config_present"] is True
    assert row["model"] == ""
    assert "not json at all" not in json.dumps(row)


def test_agent_configs_module_has_no_forbidden_imports():
    source = (ROOT / "app" / "agent_configs.py").read_text(encoding="utf-8")
    assert "app.settings" not in source
    assert "app.collectors" not in source


def test_collect_agents_with_config_home_appends_config_source(tmp_path):
    def runner(argv, timeout):
        raise FileNotFoundError(argv[0])

    result = collect_agents(
        config_home=str(tmp_path),
        proc_root=str(tmp_path / "missing-proc"),
        runner=runner,
    )
    assert [row["kind"] for row in result["agents"]] == [
        "claude",
        "pi",
        "opencode",
        "hermes",
    ]
    assert [source["name"] for source in result["sources"]] == [
        "herdr",
        "proc",
        "config",
    ]
    assert result["sources"][2]["name"] == "config"
    assert result["note"] is None


def test_collect_agents_without_config_home_has_no_config_source(tmp_path):
    def runner(argv, timeout):
        raise FileNotFoundError(argv[0])

    result = collect_agents(proc_root=str(tmp_path / "missing-proc"), runner=runner)
    assert [source["name"] for source in result["sources"]] == ["herdr", "proc"]
    assert all(row["source"] != "config" for row in result["agents"])
