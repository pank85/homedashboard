"""Configuration loading for the home dashboard.

Collectors must not import this module; only ``app.main`` and
``tests/test_settings`` depend on it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

VALID_HERDR_MODES = ("embedded", "external", "off")

DEFAULT_HERDR_SESSION = "hermes"
DEFAULT_DB_PATH = "/data/dashboard.db"
DEFAULT_SNAPSHOT_RETENTION_DAYS = 7

DEFAULT_AGENT_PROCESS_PATTERNS = (
    "claude",
    "opencode",
    "pi",
    "muse",
    "codex",
    "aider",
    "gemini",
    "hermes",
)

DEFAULT_DISK_PATHS = ("/host", "/host/home")

_TRUE_VALUES = ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    dashboard_host: str
    dashboard_port: int
    refresh_seconds: int
    docker_socket: str
    docker_api_version: str
    docker_timeout_seconds: float
    container_fetch_workers: int
    herdr_bin: str
    herdr_timeout_seconds: float
    herdr_mode: str
    herdr_config_dir: str
    herdr_web_url: str
    herdr_web_token: str
    herdr_web_embed: bool
    herdr_upstream: str
    herdr_web_bind: str
    herdr_web_port: int
    herdr_upstream_tls_verify: bool
    herdr_proxy_max_bytes: int
    agent_process_patterns: tuple[str, ...]
    proc_root: str
    host_root: str
    disk_paths: tuple[str, ...]
    cpu_sample_seconds: float
    cpu_warn: float
    cpu_crit: float
    mem_warn: float
    mem_crit: float
    disk_warn: float
    disk_crit: float
    herdr_session: str = DEFAULT_HERDR_SESSION
    chat_api_token: str = field(default="", repr=False)
    chat_cwd_allowlist: tuple[str, ...] = ()
    db_path: str = DEFAULT_DB_PATH
    herdr_snapshot_retention_days: int = DEFAULT_SNAPSHOT_RETENTION_DAYS


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in _TRUE_VALUES


def _parse_int(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return default


def _parse_float(value: str | None, default: float) -> float:
    if value is None or value.strip() == "":
        return default
    try:
        return float(value.strip())
    except (TypeError, ValueError):
        return default


def _parse_csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None or value.strip() == "":
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _parse_session(value: str | None) -> str:
    session = (value or "").strip()
    if session == "":
        return DEFAULT_HERDR_SESSION
    if session.casefold() == "default":
        return "default"
    return session


def _parse_retention_days(value: str | None) -> int:
    days = _parse_int(value, DEFAULT_SNAPSHOT_RETENTION_DAYS)
    return days if days >= 1 else DEFAULT_SNAPSHOT_RETENTION_DAYS


def _parse_db_path(env: dict[str, str]) -> str:
    """Blank ``DB_PATH`` disables persistence; a missing key uses the default."""
    if "DB_PATH" not in env:
        return DEFAULT_DB_PATH
    return env["DB_PATH"].strip()


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ

    raw_mode = env.get("HERDR_MODE", "").strip()
    herdr_mode = raw_mode if raw_mode in VALID_HERDR_MODES else "embedded"

    return Settings(
        dashboard_host=env.get("DASHBOARD_HOST", "0.0.0.0"),
        dashboard_port=_parse_int(env.get("DASHBOARD_PORT"), 8080),
        refresh_seconds=_parse_int(env.get("REFRESH_SECONDS"), 5),
        docker_socket=env.get("DOCKER_SOCKET", "/var/run/docker.sock"),
        docker_api_version=env.get("DOCKER_API_VERSION", "v1.41"),
        docker_timeout_seconds=_parse_float(
            env.get("DOCKER_TIMEOUT_SECONDS"), 3.0
        ),
        container_fetch_workers=max(
            1, _parse_int(env.get("CONTAINER_FETCH_WORKERS"), 8)
        ),
        herdr_bin=env.get("HERDR_BIN", "herdr"),
        herdr_timeout_seconds=_parse_float(env.get("HERDR_TIMEOUT_SECONDS"), 3.0),
        herdr_mode=herdr_mode,
        herdr_config_dir=env.get("HERDR_CONFIG_DIR", ""),
        herdr_web_url=env.get("HERDR_WEB_URL", ""),
        herdr_web_token=env.get("HERDR_WEB_TOKEN", ""),
        herdr_web_embed=_parse_bool(env.get("HERDR_WEB_EMBED"), False),
        herdr_upstream=env.get("HERDR_UPSTREAM", "http://127.0.0.1:7317"),
        herdr_web_bind=env.get("HERDR_WEB_BIND", "127.0.0.1"),
        herdr_web_port=_parse_int(env.get("HERDR_WEB_PORT"), 7317),
        herdr_upstream_tls_verify=_parse_bool(
            env.get("HERDR_UPSTREAM_TLS_VERIFY"), False
        ),
        herdr_proxy_max_bytes=_parse_int(
            env.get("HERDR_PROXY_MAX_BYTES"), 33554432
        ),
        agent_process_patterns=_parse_csv(
            env.get("AGENT_PROCESS_PATTERNS"), DEFAULT_AGENT_PROCESS_PATTERNS
        ),
        proc_root=env.get("PROC_ROOT", "/proc"),
        host_root=env.get("HOST_ROOT", "/host"),
        disk_paths=_parse_csv(env.get("DISK_PATHS"), DEFAULT_DISK_PATHS),
        cpu_sample_seconds=_parse_float(env.get("CPU_SAMPLE_SECONDS"), 0.2),
        cpu_warn=_parse_float(env.get("CPU_WARN"), 75.0),
        cpu_crit=_parse_float(env.get("CPU_CRIT"), 90.0),
        mem_warn=_parse_float(env.get("MEM_WARN"), 75.0),
        mem_crit=_parse_float(env.get("MEM_CRIT"), 90.0),
        disk_warn=_parse_float(env.get("DISK_WARN"), 75.0),
        disk_crit=_parse_float(env.get("DISK_CRIT"), 90.0),
        herdr_session=_parse_session(env.get("HERDR_SESSION")),
        chat_api_token=env.get("CHAT_API_TOKEN", "").strip(),
        chat_cwd_allowlist=_parse_csv(env.get("CHAT_CWD_ALLOWLIST"), ()),
        db_path=_parse_db_path(env),
        herdr_snapshot_retention_days=_parse_retention_days(
            env.get("HERDR_SNAPSHOT_RETENTION_DAYS")
        ),
    )


def public_herdr_href(settings: Settings) -> str:
    """Return the only URL the template may emit for the Herdr Web control."""
    if settings.herdr_web_token:
        return "/herdr/"
    if settings.herdr_web_url:
        return settings.herdr_web_url
    if settings.herdr_mode == "embedded":
        return "/herdr/"
    return ""


def herdr_embed_src(settings: Settings) -> str:
    """Return the iframe src, or ``""`` when the embed is disabled."""
    if not settings.herdr_web_embed:
        return ""
    return public_herdr_href(settings)
