"""Tests for app.settings.

Imports only app.settings: no collectors, main, or proxy.
"""

from app.settings import (
    DEFAULT_AGENT_PROCESS_PATTERNS,
    Settings,
    herdr_embed_src,
    load_settings,
    public_herdr_href,
)


def test_defaults_when_environ_empty():
    settings = load_settings({})

    assert settings.dashboard_host == "0.0.0.0"
    assert settings.dashboard_port == 8080
    assert settings.refresh_seconds == 5
    assert settings.docker_socket == "/var/run/docker.sock"
    assert settings.docker_api_version == "v1.41"
    assert settings.docker_timeout_seconds == 3.0
    assert settings.herdr_bin == "herdr"
    assert settings.herdr_timeout_seconds == 3.0
    assert settings.herdr_mode == "embedded"
    assert settings.herdr_config_dir == ""
    assert settings.herdr_web_url == ""
    assert settings.herdr_web_token == ""
    assert settings.herdr_web_embed is False
    assert settings.herdr_upstream == "http://127.0.0.1:7317"
    assert settings.herdr_web_bind == "127.0.0.1"
    assert settings.herdr_web_port == 7317
    assert settings.herdr_upstream_tls_verify is False
    assert settings.herdr_proxy_max_bytes == 33554432
    assert settings.agent_process_patterns == (
        "claude",
        "opencode",
        "pi",
        "muse",
        "codex",
        "aider",
        "gemini",
        "hermes",
    )
    assert settings.proc_root == "/proc"
    assert settings.host_root == "/host"
    assert settings.disk_paths == ("/host", "/host/home")
    assert settings.cpu_sample_seconds == 0.2
    assert (settings.cpu_warn, settings.cpu_crit) == (75.0, 90.0)
    assert (settings.mem_warn, settings.mem_crit) == (75.0, 90.0)
    assert (settings.disk_warn, settings.disk_crit) == (75.0, 90.0)


def test_default_patterns_when_unset():
    assert load_settings({}).agent_process_patterns == DEFAULT_AGENT_PROCESS_PATTERNS
    assert len(DEFAULT_AGENT_PROCESS_PATTERNS) == 8


def test_bool_parser():
    assert load_settings({"HERDR_WEB_EMBED": "false"}).herdr_web_embed is False
    assert load_settings({"HERDR_WEB_EMBED": "FALSE"}).herdr_web_embed is False
    assert load_settings({"HERDR_WEB_EMBED": ""}).herdr_web_embed is False
    for truthy in ("1", "true", "TRUE", "Yes", "on", " on "):
        assert load_settings({"HERDR_WEB_EMBED": truthy}).herdr_web_embed is True


def test_unknown_mode_becomes_embedded():
    assert load_settings({"HERDR_MODE": "nope"}).herdr_mode == "embedded"
    assert load_settings({"HERDR_MODE": "EXTERNAL"}).herdr_mode == "embedded"
    for mode in ("embedded", "external", "off"):
        assert load_settings({"HERDR_MODE": mode}).herdr_mode == mode


def test_invalid_port_falls_back():
    assert load_settings({"DASHBOARD_PORT": "abc"}).dashboard_port == 8080
    assert load_settings({"HERDR_WEB_PORT": "nope"}).herdr_web_port == 7317
    assert load_settings({"DASHBOARD_PORT": "not-a-number"}).dashboard_port == 8080


def test_invalid_float_falls_back():
    settings = load_settings({"CPU_WARN": "abc", "DOCKER_TIMEOUT_SECONDS": "x"})
    assert settings.cpu_warn == 75.0
    assert settings.docker_timeout_seconds == 3.0


def test_token_forces_herdr_href():
    settings = load_settings(
        {"HERDR_WEB_TOKEN": "secret", "HERDR_WEB_URL": "http://example.test:7317"}
    )
    assert public_herdr_href(settings) == "/herdr/"


def test_url_returned_unchanged_when_token_unset():
    settings = load_settings({"HERDR_WEB_URL": "http://example.test:7317"})
    assert public_herdr_href(settings) == "http://example.test:7317"
    assert public_herdr_href(settings) == settings.herdr_web_url


def test_off_mode_with_no_url_returns_empty():
    settings = load_settings({"HERDR_MODE": "off"})
    assert public_herdr_href(settings) == ""


def test_embedded_mode_default_href_is_herdr_path():
    assert public_herdr_href(load_settings({})) == "/herdr/"


def test_embed_src_disabled_is_empty():
    settings = load_settings({"HERDR_WEB_EMBED": "false"})
    assert herdr_embed_src(settings) == ""


def test_embed_src_enabled_matches_href():
    settings = load_settings({"HERDR_WEB_EMBED": "true"})
    assert herdr_embed_src(settings) == public_herdr_href(settings) == "/herdr/"

    external = load_settings(
        {"HERDR_WEB_EMBED": "true", "HERDR_WEB_URL": "http://example.test:7317"}
    )
    assert herdr_embed_src(external) == external.herdr_web_url


def test_csv_parsing_strips_and_drops_empty():
    settings = load_settings({"AGENT_PROCESS_PATTERNS": " a , b ,, c "})
    assert settings.agent_process_patterns == ("a", "b", "c")

    disks = load_settings({"DISK_PATHS": "/a,, /b "})
    assert disks.disk_paths == ("/a", "/b")


def test_token_never_in_public_helpers():
    settings = load_settings(
        {
            "HERDR_WEB_TOKEN": "super-secret-token",
            "HERDR_WEB_URL": "http://example.test:7317",
            "HERDR_WEB_EMBED": "true",
        }
    )
    assert "super-secret-token" not in public_herdr_href(settings)
    assert "super-secret-token" not in herdr_embed_src(settings)


def test_load_settings_none_reads_os_environ(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PORT", "9999")
    assert load_settings().dashboard_port == 9999


def test_settings_is_frozen():
    settings: Settings = load_settings({})
    try:
        settings.dashboard_port = 1  # type: ignore[misc]
    except Exception as error:  # dataclasses.FrozenInstanceError
        assert type(error).__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("Settings should be frozen")
