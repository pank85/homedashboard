import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _missing(module_name: str) -> bool:
    try:
        __import__(module_name)
    except ImportError:
        return True
    return False


def _install_contract_stubs() -> None:
    """Install contract stubs only for modules that are not importable."""
    import types

    if _missing("app.settings"):
        settings_mod = types.ModuleType("app.settings")

        from dataclasses import dataclass

        @dataclass(frozen=True)
        class Settings:
            dashboard_host: str
            dashboard_port: int
            refresh_seconds: int
            docker_socket: str
            docker_api_version: str
            docker_timeout_seconds: float
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

        def _parse_bool(value: str | None, default: bool) -> bool:
            if value is None or value.strip() == "":
                return default
            return value.strip().lower() in {"1", "true", "yes", "on"}

        def _parse_int(value: str | None, default: int) -> int:
            if value is None or value.strip() == "":
                return default
            try:
                return int(value)
            except ValueError:
                return default

        def _parse_float(value: str | None, default: float) -> float:
            if value is None or value.strip() == "":
                return default
            try:
                return float(value)
            except ValueError:
                return default

        def _parse_csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
            if value is None or value.strip() == "":
                return default
            return tuple(part.strip() for part in value.split(",") if part.strip())

        def load_settings(environ: dict[str, str] | None = None) -> Settings:
            import os

            env = os.environ if environ is None else environ
            mode = env.get("HERDR_MODE", "embedded") or "embedded"
            if mode not in {"embedded", "external", "off"}:
                mode = "embedded"
            patterns = (
                "claude",
                "opencode",
                "pi",
                "muse",
                "codex",
                "aider",
                "gemini",
                "hermes",
            )
            return Settings(
                dashboard_host=env.get("DASHBOARD_HOST", "0.0.0.0") or "0.0.0.0",
                dashboard_port=_parse_int(env.get("DASHBOARD_PORT"), 8080),
                refresh_seconds=_parse_int(env.get("REFRESH_SECONDS"), 5),
                docker_socket=env.get("DOCKER_SOCKET", "/var/run/docker.sock") or "/var/run/docker.sock",
                docker_api_version=env.get("DOCKER_API_VERSION", "v1.41") or "v1.41",
                docker_timeout_seconds=_parse_float(env.get("DOCKER_TIMEOUT_SECONDS"), 3.0),
                herdr_bin=env.get("HERDR_BIN", "herdr") or "herdr",
                herdr_timeout_seconds=_parse_float(env.get("HERDR_TIMEOUT_SECONDS"), 3.0),
                herdr_mode=mode,
                herdr_config_dir=env.get("HERDR_CONFIG_DIR", "") or "",
                herdr_web_url=env.get("HERDR_WEB_URL", "") or "",
                herdr_web_token=env.get("HERDR_WEB_TOKEN", "") or "",
                herdr_web_embed=_parse_bool(env.get("HERDR_WEB_EMBED"), False),
                herdr_upstream=env.get("HERDR_UPSTREAM", "http://127.0.0.1:7317") or "http://127.0.0.1:7317",
                herdr_web_bind=env.get("HERDR_WEB_BIND", "127.0.0.1") or "127.0.0.1",
                herdr_web_port=_parse_int(env.get("HERDR_WEB_PORT"), 7317),
                herdr_upstream_tls_verify=_parse_bool(env.get("HERDR_UPSTREAM_TLS_VERIFY"), False),
                herdr_proxy_max_bytes=_parse_int(env.get("HERDR_PROXY_MAX_BYTES"), 33554432),
                agent_process_patterns=_parse_csv(env.get("AGENT_PROCESS_PATTERNS"), patterns),
                proc_root=env.get("PROC_ROOT", "/proc") or "/proc",
                host_root=env.get("HOST_ROOT", "/host") or "/host",
                disk_paths=_parse_csv(env.get("DISK_PATHS"), ("/host", "/host/home")),
                cpu_sample_seconds=_parse_float(env.get("CPU_SAMPLE_SECONDS"), 0.2),
                cpu_warn=_parse_float(env.get("CPU_WARN"), 75.0),
                cpu_crit=_parse_float(env.get("CPU_CRIT"), 90.0),
                mem_warn=_parse_float(env.get("MEM_WARN"), 75.0),
                mem_crit=_parse_float(env.get("MEM_CRIT"), 90.0),
                disk_warn=_parse_float(env.get("DISK_WARN"), 75.0),
                disk_crit=_parse_float(env.get("DISK_CRIT"), 90.0),
            )

        def public_herdr_href(settings: Settings) -> str:
            if settings.herdr_web_token:
                return "/herdr/"
            if settings.herdr_web_url:
                return settings.herdr_web_url
            if settings.herdr_mode == "embedded":
                return "/herdr/"
            return ""

        def herdr_embed_src(settings: Settings) -> str:
            if not settings.herdr_web_embed:
                return ""
            return public_herdr_href(settings)

        settings_mod.Settings = Settings
        settings_mod.load_settings = load_settings
        settings_mod.public_herdr_href = public_herdr_href
        settings_mod.herdr_embed_src = herdr_embed_src
        sys.modules["app.settings"] = settings_mod

    if _missing("app.aggregate"):
        aggregate_mod = types.ModuleType("app.aggregate")

        def build_dashboard(
            *,
            containers: dict,
            agents: dict,
            host: dict,
            herdr_href: str,
            herdr_embed: bool,
            herdr_embed_src: str,
            herdr_mode: str,
            refresh_seconds: int,
            generated_at: str,
        ) -> dict:
            return {
                "generated_at": generated_at,
                "refresh_seconds": refresh_seconds,
                "herdr": {
                    "mode": herdr_mode,
                    "href": herdr_href,
                    "embed": bool(herdr_embed) and bool(herdr_embed_src),
                    "embed_src": herdr_embed_src if herdr_embed else "",
                    "proxy_path": "/herdr/",
                },
                "containers": containers,
                "agents": agents,
                "host": host,
            }

        aggregate_mod.build_dashboard = build_dashboard
        sys.modules["app.aggregate"] = aggregate_mod

    if _missing("app.proxy"):
        proxy_mod = types.ModuleType("app.proxy")

        def upstream_url(upstream: str, path: str) -> str:
            base = upstream.rstrip("/")
            if path == "":
                return base + "/"
            return base + "/" + path.lstrip("/")

        def to_ws_url(url: str) -> str:
            if url.startswith("https://"):
                return "wss://" + url[len("https://") :]
            if url.startswith("http://"):
                return "ws://" + url[len("http://") :]
            return url

        def hop_request_headers(headers: dict, token: str) -> dict:
            drop = {
                "host",
                "authorization",
                "cookie",
                "x-forwarded-for",
                "x-forwarded-host",
                "forwarded",
                "x-real-ip",
                "content-length",
                "transfer-encoding",
                "connection",
                "upgrade",
            }
            hopped = {key: value for key, value in headers.items() if key.lower() not in drop}
            if token:
                hopped["authorization"] = f"Bearer {token}"
            return hopped

        def filter_response_headers(headers: dict, token: str) -> dict:
            return {key: value for key, value in headers.items() if key.lower() != "set-cookie"}

        def rewrite_html(html: str, prefix: str = "/herdr") -> str:
            return html

        def mount_herdr_proxy(
            app,
            *,
            upstream: str,
            token: str,
            tls_verify: bool = False,
            max_bytes: int = 33554432,
        ) -> None:
            return None

        proxy_mod.upstream_url = upstream_url
        proxy_mod.to_ws_url = to_ws_url
        proxy_mod.hop_request_headers = hop_request_headers
        proxy_mod.filter_response_headers = filter_response_headers
        proxy_mod.rewrite_html = rewrite_html
        proxy_mod.mount_herdr_proxy = mount_herdr_proxy
        sys.modules["app.proxy"] = proxy_mod


_install_contract_stubs()

import logging

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

_EMBED_LIMIT = (
    "If the frame is blank, the upstream refused to be embedded "
    "(X-Frame-Options or frame-ancestors). Accept the self-signed or "
    "self-hosted origin in a new tab, or use the proxied /herdr/ path."
)


def _unavailable_collectors() -> dict:
    def containers(**kwargs):
        return {
            "available": False,
            "reason": "docker socket not reachable: /var/run/docker.sock",
            "refreshed_at": "2020-01-01T00:00:00+00:00",
            "containers": [],
        }

    def agents(**kwargs):
        return {
            "available": True,
            "reason": None,
            "note": "no agents detected",
            "refreshed_at": "2020-01-01T00:00:00+00:00",
            "sources": [
                {
                    "name": "herdr",
                    "used": False,
                    "refreshed_at": None,
                    "error": "herdr not found: herdr",
                    "count": 0,
                }
            ],
            "agents": [],
        }

    def host(**kwargs):
        return {
            "available": False,
            "reason": "proc not readable: /proc",
            "refreshed_at": "2020-01-01T00:00:00+00:00",
            "view": "container view",
            "cpu": {
                "available": False,
                "reason": "proc stat not readable: /proc/stat",
                "percent": None,
                "per_core": [],
                "loadavg": None,
                "cores": None,
                "level": None,
            },
            "memory": {
                "available": False,
                "reason": "proc meminfo not readable: /proc/meminfo",
                "used_bytes": None,
                "total_bytes": None,
                "percent": None,
                "level": None,
            },
            "disks": [],
        }

    return {"containers": containers, "agents": agents, "host": host}


def test_page_renders_with_every_source_unavailable(monkeypatch):
    monkeypatch.setenv("HERDR_WEB_TOKEN", "super-secret-token")
    application = create_app(collectors=_unavailable_collectors())
    with TestClient(application) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "unavailable:" in page.text
        assert "docker socket not reachable: /var/run/docker.sock" in page.text
        assert "no agents detected" in page.text
        assert "proc stat not readable: /proc/stat" in page.text
        assert "container view" in page.text
        assert "herdr not found: herdr" in page.text
        assert "Traceback" not in page.text
        assert "super-secret-token" not in page.text
        assert _EMBED_LIMIT in page.text
        assert '<html lang="en">' in page.text
        assert 'name="viewport"' in page.text
        assert 'name="color-scheme" content="dark"' in page.text
        assert 'href="/static/style.css"' in page.text
        assert 'src="/static/app.js"' in page.text
        assert 'id="last-updated"' in page.text
        assert 'id="herdr-button"' in page.text
        assert 'href="/herdr/"' in page.text
        assert 'target="_blank"' in page.text
        assert 'rel="noopener noreferrer"' in page.text
        assert "Open Herdr Web" in page.text
        assert 'id="panel-containers"' in page.text
        assert 'id="containers-body"' in page.text
        assert 'id="panel-agents"' in page.text
        assert 'id="agents-body"' in page.text
        assert 'id="panel-host"' in page.text
        assert 'id="host-body"' in page.text
        assert 'id="herdr-embed"' not in page.text
        assert "sandbox" not in page.text

        metrics = client.get("/api/metrics")
        assert metrics.status_code == 200
        body = metrics.json()
        assert body["containers"]["reason"] == "docker socket not reachable: /var/run/docker.sock"
        assert body["agents"]["note"] == "no agents detected"
        assert body["agents"]["sources"][0]["error"] == "herdr not found: herdr"
        assert body["host"]["cpu"]["reason"] == "proc stat not readable: /proc/stat"
        assert body["host"]["view"] == "container view"
        assert "super-secret-token" not in metrics.text
        assert "herdr_web_token" not in metrics.text
        assert "Traceback" not in metrics.text

        containers = client.get("/api/containers")
        agents = client.get("/api/agents")
        host = client.get("/api/host")
        assert containers.status_code == 200
        assert agents.status_code == 200
        assert host.status_code == 200
        assert containers.json()["reason"] == "docker socket not reachable: /var/run/docker.sock"
        assert agents.json()["note"] == "no agents detected"
        assert host.json()["view"] == "container view"
        assert "super-secret-token" not in containers.text
        assert "super-secret-token" not in agents.text
        assert "super-secret-token" not in host.text

        script = client.get("/static/app.js")
        style = client.get("/static/style.css")
        assert script.status_code == 200
        assert style.status_code == 200
        assert "https://" not in script.text
        assert "http://" not in script.text
        assert "https://" not in style.text
        assert "http://" not in style.text
        assert "innerHTML" not in script.text
        assert "@import" not in style.text
        assert "url(http" not in style.text
        assert "#0f1419" in style.text
        assert "#e7ecf1" in style.text
        assert "#1a2332" in style.text
        assert "#3dd68c" in style.text
        assert "#e6b35a" in style.text
        assert "#f07178" in style.text
        assert "max-width: 640px" in style.text

    calls: list[str] = []

    def fail(name: str):
        def _fail(**kwargs):
            calls.append(name)
            raise AssertionError("collector called")

        return _fail

    health_app = create_app(
        collectors={
            "containers": fail("containers"),
            "agents": fail("agents"),
            "host": fail("host"),
        }
    )
    with TestClient(health_app) as client:
        health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert calls == []


def test_collector_exception_is_unavailable_not_traceback(monkeypatch, caplog):
    monkeypatch.setenv("HERDR_WEB_TOKEN", "super-secret-token")

    def boom(**kwargs):
        raise RuntimeError("super-secret-token leaked")

    application = create_app(
        collectors={"containers": boom, "agents": boom, "host": boom}
    )
    with caplog.at_level(logging.ERROR, logger="homedashboard"):
        with TestClient(application) as client:
            page = client.get("/")
            metrics = client.get("/api/metrics")
    assert page.status_code == 200
    assert "unavailable: collector error" in page.text
    assert "no agents detected" in page.text
    assert "Traceback" not in page.text
    assert "super-secret-token" not in page.text
    assert metrics.status_code == 200
    assert metrics.json()["containers"]["reason"] == "collector error"
    assert metrics.json()["agents"]["note"] == "no agents detected"
    assert metrics.json()["host"]["reason"] == "collector error"
    assert "super-secret-token" not in metrics.text
    assert "super-secret-token" not in caplog.text
    assert "[redacted]" in caplog.text


def test_page_real_collectors_missing_sources(monkeypatch, tmp_path):
    pytest.importorskip("app.collectors.docker")
    pytest.importorskip("app.collectors.agents")
    pytest.importorskip("app.collectors.host")
    missing = tmp_path / "missing"
    monkeypatch.setenv("DOCKER_SOCKET", str(missing / "docker.sock"))
    monkeypatch.setenv("HERDR_BIN", str(missing / "herdr"))
    monkeypatch.setenv("PROC_ROOT", str(missing / "proc"))
    monkeypatch.setenv("HOST_ROOT", str(missing / "host"))
    monkeypatch.setenv("HERDR_MODE", "off")
    monkeypatch.setenv("HERDR_WEB_TOKEN", "super-secret-token")
    monkeypatch.setenv("HERDR_WEB_EMBED", "false")
    monkeypatch.setenv("CPU_SAMPLE_SECONDS", "0")
    monkeypatch.setenv("REFRESH_SECONDS", "0")
    application = create_app(collectors=None)
    with TestClient(application) as client:
        page = client.get("/")
    assert page.status_code == 200
    assert "unavailable:" in page.text
    assert "no agents detected" in page.text
    assert "Traceback" not in page.text
    assert "super-secret-token" not in page.text
    assert 'data-refresh="0"' in page.text
    assert 'id="herdr-embed"' not in page.text
