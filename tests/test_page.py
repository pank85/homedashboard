import re
import sqlite3
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


def _panel(html: str, panel_id: str) -> str:
    marker = f'id="{panel_id}"'
    start = html.index(marker)
    open_at = html.rfind("<section", 0, start)
    close_at = html.find("</section>", start)
    assert open_at != -1 and close_at != -1
    return html[open_at:close_at]


def _tag(html: str, element_id: str) -> str:
    match = re.search(rf'<[^>]*id="{element_id}"[^>]*>', html)
    assert match is not None, element_id
    return match.group(0)


def _js_function(source: str, name: str) -> str:
    marker = "function " + name
    start = source.index(marker)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError("unclosed " + name)


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
    monkeypatch.setenv("DB_PATH", "")
    monkeypatch.delenv("CHAT_API_TOKEN", raising=False)
    application = create_app(collectors=_unavailable_collectors())
    with TestClient(application) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "unavailable:" in page.text
        assert "docker socket not reachable: /var/run/docker.sock" in page.text
        assert "No agents detected." in page.text
        assert "proc stat not readable: /proc/stat" in page.text
        assert "container view" in page.text
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
        assert 'id="panel-sessions"' in page.text
        assert 'id="sessions-body"' in page.text
        assert 'id="herdr-block"' in page.text
        assert 'id="container-filter-text"' in page.text
        assert 'id="container-filter-state"' in page.text
        assert 'id="container-filter-hide-healthy"' in page.text
        assert 'id="container-filter-count"' in page.text
        assert 'id="new-session-form"' in page.text
        assert 'src="/static/container_filters.js"' in page.text
        assert page.text.index('src="/static/container_filters.js"') < page.text.index('src="/static/app.js"')
        assert (
            "Archive only updates this dashboard. It does not stop or delete the herdr workspace, tab, or agent."
            in page.text
        )
        warning = "herdr --session &lt;name&gt; attach is not a working command on herdr 0.9.5."
        assert warning in page.text
        assert page.text.replace(warning, "").count("herdr --session") == 0
        assert "undefined" not in page.text
        assert "CHAT_API_TOKEN unset" in page.text
        password = _tag(page.text, "session-token")
        assert 'type="password"' in password
        assert "value=" not in password
        for panel_id in ("panel-containers", "panel-agents", "panel-host", "panel-sessions"):
            assert "unavailable" in _panel(page.text, panel_id)
        for control in ("session-kind", "session-cwd", "session-label", "session-token", "session-submit"):
            assert "disabled" in _tag(page.text, control)
        agents_panel = _panel(page.text, "panel-agents")
        assert agents_panel.index('id="herdr-block"') < agents_panel.index('id="agents-body"')
        containers_panel = _panel(page.text, "panel-containers")
        assert containers_panel.index('id="container-filter-text"') < containers_panel.index('id="containers-body"')
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
        assert "filterContainers(" in script.text
        assert "homedashboard.chatApiToken" in script.text
        assert "/api/sessions" in script.text
        assert "clipboard.writeText" in script.text
        filters = client.get("/static/container_filters.js")
        assert filters.status_code == 200
        assert "fetch(" not in filters.text
        assert "https://" not in filters.text
        assert "http://" not in filters.text
        assert "innerHTML" not in filters.text
        assert "@import" not in style.text
        assert "url(http" not in style.text
        assert "#0f1419" in style.text
        assert "#e7ecf1" in style.text
        assert "#1a2332" in style.text
        assert "#3dd68c" in style.text
        assert "#e6b35a" in style.text
        assert "#f07178" in style.text
        assert "max-width: 640px" in style.text
        assert "grid-template-columns: 1fr" in style.text
        assert "repeat(auto-fill, minmax(16rem, 1fr))" in style.text
        assert "min-width: 641px" in style.text

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
    assert "No agents detected." in page.text
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
    assert "No agents detected." in page.text
    assert "Traceback" not in page.text
    assert "super-secret-token" not in page.text
    assert 'data-refresh="0"' in page.text
    assert 'id="herdr-embed"' not in page.text


def _collectors(containers: dict, agents: dict | None = None) -> dict:
    quiet = _unavailable_collectors()

    def collect_containers(**kwargs):
        return containers

    def collect_agents(**kwargs):
        if agents is None:
            return quiet["agents"](**kwargs)
        return agents

    return {
        "containers": collect_containers,
        "agents": collect_agents,
        "host": quiet["host"],
    }


def _container_row(**overrides) -> dict:
    row = {
        "name": "web-1",
        "compose_service": "web",
        "id_short": "abc123",
        "image": "ghcr.io/example/web:latest",
        "state": "running",
        "health": "healthy",
        "uptime_seconds": 120,
        "restart_count": 2,
        "cpu_percent": 12.5,
        "memory_used_bytes": 512,
        "memory_limit_bytes": 1024,
    }
    row.update(overrides)
    return row


def test_container_cards_badges_and_herdr_groups(monkeypatch):
    monkeypatch.setenv("HERDR_WEB_TOKEN", "super-secret-token")
    monkeypatch.setenv("DB_PATH", "")
    monkeypatch.delenv("CHAT_API_TOKEN", raising=False)
    containers = {
        "available": True,
        "reason": None,
        "refreshed_at": "2020-01-01T00:00:00+00:00",
        "containers": [
            _container_row(),
            _container_row(
                name="old-1",
                compose_service="",
                id_short="def456",
                image=None,
                state="exited",
                health=None,
                uptime_seconds=None,
                restart_count=None,
                cpu_percent=None,
                memory_used_bytes=None,
                memory_limit_bytes=None,
            ),
        ],
    }
    agents = {
        "available": True,
        "reason": None,
        "note": "",
        "refreshed_at": "2020-01-01T00:00:00+00:00",
        "sources": [
            {
                "name": "herdr",
                "used": False,
                "refreshed_at": "2020-01-01T00:00:00+00:00",
                "error": "herdr config not mounted",
            },
            {
                "name": "proc",
                "used": True,
                "refreshed_at": "2020-01-01T00:00:00+00:00",
                "error": None,
            },
        ],
        "herdr": {
            "reachable": False,
            "version": None,
            "session": None,
            "refused": False,
            "reason": "herdr config not mounted",
            "workspace_count": 1,
            "tab_count": 1,
            "agent_count": 2,
            "command": "",
        },
        "agents": [
            {
                "source": "herdr",
                "kind": "pi",
                "workspace_label": "lab",
                "tab_label": "tab-a",
                "status": "working",
                "cwd": "/work",
                "elapsed_seconds": 90,
                "elapsed_source": "herdr",
            },
            {
                "source": "proc",
                "kind": "claude",
                "workspace_label": "",
                "tab_label": "",
                "status": "running",
                "cwd": "/tmp",
                "elapsed_seconds": 5,
                "elapsed_source": "proc",
            },
            {
                "source": "herdr",
                "kind": "codex",
                "workspace_label": "",
                "tab_label": "tab-b",
                "status": "idle",
                "cwd": "/other",
                "elapsed_seconds": None,
                "elapsed_source": "herdr",
            },
        ],
    }
    application = create_app(collectors=_collectors(containers, agents))
    with TestClient(application) as client:
        page = client.get("/")
    assert page.status_code == 200
    assert "Traceback" not in page.text
    assert "super-secret-token" not in page.text
    assert "undefined" not in page.text
    assert "None" not in page.text
    panel = _panel(page.text, "panel-containers")
    assert panel.count("<article") == 2
    assert "container-grid" in panel
    assert ">web-1</h3>" in panel
    assert ">old-1</h3>" in panel
    assert "abc123" in panel
    assert "def456" in panel
    assert "web:latest" in panel
    assert ">running</span>" in panel
    assert ">healthy</span>" in panel
    assert ">exited</span>" in panel
    assert ">none</span>" in panel
    assert "unknown" in panel
    assert 'style="width: 12.5%"' in panel
    assert 'style="width: 50.0%"' in panel
    agents_panel = _panel(page.text, "panel-agents")
    assert "herdr config not mounted" in agents_panel
    assert "unavailable: herdr config not mounted" in agents_panel
    assert "<h3>lab</h3>" in agents_panel
    assert "<h3>proc</h3>" in agents_panel
    assert "<h3>unknown</h3>" in agents_panel
    assert ">pi</span>" in agents_panel
    assert ">working</span>" in agents_panel
    assert ">tab-a</h3>" in agents_panel
    assert "cwd /work" in agents_panel
    assert "elapsed 1m 30s" in agents_panel
    assert "elapsed unknown" in agents_panel
    assert "5s" not in agents_panel
    assert ">herdr</span>" in agents_panel
    assert ">proc</span>" in agents_panel


def test_container_empty_and_single_card(monkeypatch):
    monkeypatch.setenv("DB_PATH", "")
    monkeypatch.delenv("CHAT_API_TOKEN", raising=False)
    empty = {
        "available": True,
        "reason": None,
        "refreshed_at": "2020-01-01T00:00:00+00:00",
        "containers": [],
    }
    application = create_app(collectors=_collectors(empty))
    with TestClient(application) as client:
        page = client.get("/")
    panel = _panel(page.text, "panel-containers")
    assert "No containers." in panel
    assert panel.count("<article") == 0

    one = {
        "available": True,
        "reason": None,
        "refreshed_at": "2020-01-01T00:00:00+00:00",
        "containers": [_container_row(name="only", compose_service="")],
    }
    application = create_app(collectors=_collectors(one))
    with TestClient(application) as client:
        page = client.get("/")
    panel = _panel(page.text, "panel-containers")
    assert panel.count("<article") == 1
    assert ">only</h3>" in panel


def _insert_session(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        INSERT INTO chat_sessions (
            id, label, agent_kind, herdr_session, workspace_id, cwd, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "a" * 32,
            "demo",
            "pi",
            "hermes",
            "ws-1",
            "/work",
            "running",
            "2020-01-01T00:00:00+00:00",
            "2020-01-01T00:00:00+00:00",
        ),
    )
    conn.commit()
    conn.close()


def test_sessions_form_disabled_without_token(monkeypatch, tmp_path):
    db_path = tmp_path / "dash.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.delenv("CHAT_API_TOKEN", raising=False)
    monkeypatch.setenv("HERDR_WEB_TOKEN", "super-secret-token")
    application = create_app(collectors=_unavailable_collectors())
    _insert_session(str(db_path))
    with TestClient(application) as client:
        page = client.get("/")
    assert page.status_code == 200
    assert "CHAT_API_TOKEN unset" in page.text
    assert "super-secret-token" not in page.text
    for control in ("session-kind", "session-cwd", "session-label", "session-token", "session-submit"):
        assert "disabled" in _tag(page.text, control)
    password = _tag(page.text, "session-token")
    assert 'type="password"' in password
    assert "value=" not in password
    archive = re.search(r'<button[^>]*class="archive-session"[^>]*>', page.text)
    assert archive is not None
    assert "disabled" in archive.group(0)
    assert "herdr session attach hermes" in page.text


def test_sessions_list_and_enabled_form(monkeypatch, tmp_path):
    db_path = tmp_path / "dash.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("CHAT_API_TOKEN", "session-secret")
    monkeypatch.setenv("HERDR_WEB_TOKEN", "super-secret-token")
    application = create_app(collectors=_unavailable_collectors())
    _insert_session(str(db_path))
    with TestClient(application) as client:
        page = client.get("/")
    assert page.status_code == 200
    assert "session-secret" not in page.text
    assert "super-secret-token" not in page.text
    assert "undefined" not in page.text
    panel = _panel(page.text, "panel-sessions")
    assert "<p>Name demo</p>" in panel
    assert "<p>Agent pi</p>" in panel
    assert "<p>Workspace ws-1</p>" in panel
    assert "<p>Status running</p>" in panel
    assert "<p>Folder /work</p>" in panel
    assert "ago" in panel
    assert "Attaching that name opens the whole Herdr session, not this one chat." in panel
    assert "Herdr session: hermes." in panel
    assert "herdr session attach hermes" in panel
    assert "Open Herdr Web" in panel
    assert 'href="/herdr/"' in panel
    submit = _tag(page.text, "session-submit")
    assert "disabled" not in submit
    password = _tag(page.text, "session-token")
    assert "value=" not in password
    archive = re.search(r'<button[^>]*class="archive-session"[^>]*>', page.text)
    assert archive is not None
    assert "disabled" not in archive.group(0)
    from app.sessions_policy import AGENT_START_KINDS

    for kind in AGENT_START_KINDS:
        assert f'value="{kind}"' in panel


def test_tick_render_path_reapplies_filters():
    source = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    tick = _js_function(source, "tick")
    assert "renderContainers(" in tick
    render = _js_function(source, "renderContainers")
    assert "filterContainers(" in render
    assert "container-filter-text" in render
    assert "container-filter-state" in render
    assert "container-filter-hide-healthy" in render
    assert ".value =" not in tick
    filters = (ROOT / "app/static/container_filters.js").read_text(encoding="utf-8")
    assert "function filterContainers" in filters
    assert "function filterCount" in filters
    assert "fetch(" not in filters
    assert "http://" not in filters
    assert "https://" not in filters
    assert "innerHTML" not in source
    assert "http://" not in source
    assert "https://" not in source
    create = _js_function(source, "onCreate")
    assert "chatToken()" in create
    assert create.index("if (typed)") < create.index(
        'localStorage.setItem("homedashboard.chatApiToken", typed)'
    )
    assert 'setItem("homedashboard.chatApiToken", token)' not in create
    assert 'setItem("homedashboard.chatApiToken", "")' not in create
    assert "token=" not in create
    refresh = source.index('var raw = body.getAttribute("data-refresh")')
    assert source.index("tick();", refresh) < source.index('raw === "0"', refresh)
    assert source.index("tick();", refresh) < source.index("setInterval(tick", refresh)


_EMBED_PROXY = (
    "The proxied /herdr/ path strips upstream X-Frame-Options and "
    "Content-Security-Policy so the dashboard iframe and path shim can run. "
    "Service workers are not supported through the proxy. A direct external "
    "embed can still be blank."
)


def test_embed_iframe_survives_agents_herdr_without_embed(monkeypatch):
    monkeypatch.setenv("HERDR_WEB_EMBED", "true")
    monkeypatch.setenv("HERDR_WEB_TOKEN", "super-secret-token")
    monkeypatch.setenv("DB_PATH", "")
    monkeypatch.delenv("CHAT_API_TOKEN", raising=False)
    agent_herdr = {
        "reachable": False,
        "version": "0.9.5",
        "session": "ops",
        "refused": False,
        "reason": "agents block only",
        "workspace_count": 4,
        "tab_count": 5,
        "agent_count": 6,
        "command": "",
    }
    assert "embed" not in agent_herdr
    assert "embed_src" not in agent_herdr
    agents = {
        "available": True,
        "reason": None,
        "note": "",
        "refreshed_at": "2020-01-01T00:00:00+00:00",
        "sources": [],
        "herdr": agent_herdr,
        "agents": [],
    }
    containers = {
        "available": False,
        "reason": "docker socket not reachable: /var/run/docker.sock",
        "refreshed_at": "2020-01-01T00:00:00+00:00",
        "containers": [],
    }
    application = create_app(collectors=_collectors(containers, agents))
    with TestClient(application) as client:
        page = client.get("/")
        metrics = client.get("/api/metrics")
    assert page.status_code == 200
    assert metrics.status_code == 200
    body = metrics.json()
    assert body["herdr"]["embed"] is True
    assert body["herdr"]["embed_src"] == "/herdr/"
    assert "embed" not in body["agents"]["herdr"]
    assert "embed_src" not in body["agents"]["herdr"]
    assert body["agents"]["herdr"]["session"] == "ops"
    assert "super-secret-token" not in page.text
    assert "super-secret-token" not in metrics.text
    assert "Traceback" not in page.text
    iframe = _tag(page.text, "herdr-embed")
    assert 'src="/herdr/"' in iframe
    assert "sandbox" not in iframe
    frame = _panel(page.text, "herdr-frame")
    assert 'id="herdr-embed"' in frame
    assert _EMBED_LIMIT in frame
    assert _EMBED_PROXY in frame
    agents_panel = _panel(page.text, "panel-agents")
    assert 'id="herdr-embed"' not in agents_panel
    assert "session ops" in agents_panel
    assert "version 0.9.5" in agents_panel
    assert "workspaces 4" in agents_panel
    assert "tabs 5" in agents_panel
    assert "agents 6" in agents_panel
    assert "agents block only" in agents_panel
    assert 'href="/herdr/"' in page.text
    template = (ROOT / "app/templates/index.html").read_text(encoding="utf-8")
    assert '{% include "partials/agents_desktop.html" %}' in template
    agents_src = (ROOT / "app/templates/partials/agents_desktop.html").read_text(encoding="utf-8")
    assert "{% set agent_herdr" in agents_src
    assert "{% set herdr" not in template
    assert "{{ herdr." not in agents_src
    frame_src = _panel(template, "herdr-frame")
    assert "{% if herdr.embed %}" in frame_src
    assert "herdr.embed_src" in frame_src


def test_mobile_page_nav_and_desktop_link(monkeypatch):
    monkeypatch.setenv("DB_PATH", "")
    monkeypatch.delenv("CHAT_API_TOKEN", raising=False)
    application = create_app(collectors=_unavailable_collectors())
    with TestClient(application) as client:
        page = client.get("/m")
        desktop = client.get("/")
    assert page.status_code == 200
    assert desktop.status_code == 200
    for text in (page.text, desktop.text):
        assert 'href="/m"' not in text
        assert 'href="/"' not in text
        assert "view-switch" not in text
        nav = re.search(r'<nav[^>]*data-view-nav[^>]*>.*?</nav>', text, re.S)
        assert nav is not None
        nav_html = nav.group(0)
        assert nav_html.count("<button") == 6
        assert 'data-burger' in nav_html
        assert 'aria-controls="view-menu"' in nav_html
        assert 'aria-expanded' in nav_html
        assert 'id="view-menu"' in nav_html
        assert 'data-menu-open' in nav_html
        assert 'role="tablist"' in nav_html
        assert nav_html.count('role="tab"') == 5
        sections = re.findall(r'data-section="([a-z]+)"', nav_html)
        assert sections == ["host", "containers", "agents", "git", "sessions"]
        labels = re.findall(r'<button[^>]*data-section="[^"]*"[^>]*>([^<]+)</button>', nav_html)
        assert labels == ["Host", "Containers", "Agents", "Git", "Chats"]
        assert nav_html.count('aria-selected="true"') == 1
        assert nav_html.count('aria-selected="false"') == 4
        panels = re.findall(r'<(?:section|div)[^>]*data-mobile-panel[^>]*>', text)
        assert len(panels) == 5
        for panel_tag in panels:
            section = re.search(r'data-section="([a-z]+)"', panel_tag).group(1)
            if section == "host":
                assert "hidden" not in panel_tag
            else:
                assert "hidden" in panel_tag
        for panel_id in ("panel-host", "panel-containers", "panel-agents", "panel-git", "panel-sessions"):
            assert f'id="{panel_id}"' in text
        assert 'id="host-body"' in text
        assert 'id="sessions-body"' in text
        assert 'id="herdr-frame"' in text
        assert 'id="herdr-embed"' not in text
        assert "<iframe" not in text
        for element_id in (
            "new-session-form",
            "session-kind",
            "session-cwd",
            "session-label",
            "session-token",
            "session-submit",
        ):
            assert f'id="{element_id}"' in text


def test_metrics_includes_git_when_collectors_omit_it(monkeypatch):
    monkeypatch.setenv("DB_PATH", "")
    monkeypatch.delenv("CHAT_API_TOKEN", raising=False)
    application = create_app(collectors=_unavailable_collectors())
    with TestClient(application) as client:
        page = client.get("/")
        metrics = client.get("/api/metrics")
    assert page.status_code == 200
    assert metrics.status_code == 200
    git = metrics.json()["git"]
    assert git["available"] is True
    assert git["note"] == "git collector not configured"
    assert git["scanned"] is False
    assert git["projects"] == []


def test_injected_git_collector_renders_redacted_url(monkeypatch):
    monkeypatch.setenv("DB_PATH", "")
    monkeypatch.delenv("CHAT_API_TOKEN", raising=False)
    planted = "ghp_PlantedRawToken9f3a"
    redacted = "https://github.com/org/demo.git"

    def collect_git(**kwargs):
        return {
            "available": True,
            "reason": "",
            "note": "",
            "scanned": True,
            "roots": ["/repos"],
            "truncated": False,
            "refreshed_at": "2020-01-01T00:00:00+00:00",
            "projects": [
                {
                    "name": "demo",
                    "path": "/repos/demo",
                    "branch": "main",
                    "detached": False,
                    "head_short": "abc1234",
                    "upstream": "origin/main",
                    "remote_url": redacted,
                    "in_progress": [],
                    "commit_subject": "hello",
                    "commit_at": "",
                }
            ],
        }

    collectors = _unavailable_collectors()
    collectors["git"] = collect_git
    application = create_app(collectors=collectors)
    with TestClient(application) as client:
        page = client.get("/")
        mobile = client.get("/m")
        metrics = client.get("/api/metrics")
    assert page.status_code == 200
    assert mobile.status_code == 200
    assert redacted in page.text
    assert redacted in mobile.text
    assert planted not in page.text
    assert planted not in mobile.text
    assert planted not in metrics.text
    assert metrics.json()["git"]["projects"][0]["remote_url"] == redacted


def test_tick_does_not_assign_filter_value_and_still_filters():
    source = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    tick = _js_function(source, "tick")
    render = _js_function(source, "renderContainers")
    assert ".value =" not in tick
    assert ".value =" not in render
    assert "filterContainers(" in render
    assert "renderGitView" in tick
    assert "data.git" in tick


def test_linked_view_assets_have_no_innerhtml_or_http(monkeypatch):
    monkeypatch.setenv("DB_PATH", "")
    monkeypatch.delenv("CHAT_API_TOKEN", raising=False)
    names = (
        "containers.css",
        "agents.css",
        "git.css",
        "desktop.css",
        "mobile.css",
        "containers_view.js",
        "agents_view.js",
        "git_view.js",
        "view_nav.js",
        "host_view.js",
        "sessions_view.js",
    )
    application = create_app(collectors=_unavailable_collectors())
    with TestClient(application) as client:
        desktop = client.get("/")
        mobile = client.get("/m")
        linked = desktop.text + mobile.text
        for name in names:
            href = "/static/" + name
            assert href in linked
            asset = client.get(href)
            assert asset.status_code == 200
            assert "innerHTML" not in asset.text
            assert "http://" not in asset.text
            assert "https://" not in asset.text
