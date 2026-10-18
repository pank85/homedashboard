"""Dashboard routes, page, and degrade-on-collector-failure shell.

Collectors are imported only when ``collectors`` is None, and only when a
data route runs. A collector exception becomes that panel's unavailable
object. ``herdr_web_token`` and ``chat_api_token`` are never placed in a
response body.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.agent_pages import agent_page_data

_LOGGER = logging.getLogger("homedashboard")
_APP_DIR = Path(__file__).resolve().parent
_SNAPSHOT_STATUSES = frozenset({"working", "idle", "blocked", "done"})


class _TokenRedactFilter(logging.Filter):
    """Rewrite known Herdr tokens to ``[redacted]`` before a record is emitted."""

    def __init__(self) -> None:
        super().__init__()
        self.tokens: list[str] = []

    def add(self, token: str) -> None:
        if token and token not in self.tokens:
            self.tokens.append(token)

    def filter(self, record: logging.LogRecord) -> bool:
        tokens = [token for token in self.tokens if token]
        if not tokens:
            return True
        if isinstance(record.msg, str):
            record.msg = _redact(record.msg, tokens)
        if record.args:
            record.args = _redact_args(record.args, tokens)
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_info:
            record.exc_info = None
        if isinstance(record.exc_text, str):
            record.exc_text = _redact(record.exc_text, tokens)
        if isinstance(record.stack_info, str):
            record.stack_info = _redact(record.stack_info, tokens)
        return True


_REDACT = _TokenRedactFilter()
if _REDACT not in _LOGGER.filters:
    _LOGGER.addFilter(_REDACT)


def _default_herdr_runner(argv: list[str], timeout: float):
    """Spawn herdr. ``argv`` is a list; this runner never uses a shell."""
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _redact(text: str, tokens: list[str]) -> str:
    for token in tokens:
        text = text.replace(token, "[redacted]")
    return text


def _redact_value(value: Any, tokens: list[str]) -> Any:
    if isinstance(value, str):
        return _redact(value, tokens)
    return value


def _redact_args(args: Any, tokens: list[str]) -> Any:
    if isinstance(args, dict):
        return {key: _redact_value(value, tokens) for key, value in args.items()}
    if isinstance(args, tuple):
        return tuple(_redact_value(value, tokens) for value in args)
    return _redact_value(args, tokens)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _containers_fallback(generated_at: str) -> dict[str, Any]:
    return {
        "available": False,
        "reason": "collector error",
        "refreshed_at": generated_at,
        "containers": [],
    }


def _agents_fallback(generated_at: str) -> dict[str, Any]:
    return {
        "available": True,
        "reason": None,
        "note": "no agents detected",
        "refreshed_at": generated_at,
        "sources": [],
        "agents": [],
    }


def _host_fallback(generated_at: str) -> dict[str, Any]:
    return {
        "available": False,
        "reason": "collector error",
        "refreshed_at": generated_at,
        "view": "container view",
        "cpu": {
            "available": False,
            "reason": "collector error",
            "percent": None,
            "per_core": [],
            "loadavg": None,
            "cores": None,
            "level": None,
        },
        "memory": {
            "available": False,
            "reason": "collector error",
            "used_bytes": None,
            "total_bytes": None,
            "percent": None,
            "level": None,
        },
        "disks": [],
    }


def create_app(
    settings: Any = None,
    collectors: dict[str, Callable[..., Any]] | None = None,
    herdr_runner: Callable[[list[str], float], Any] | None = None,
) -> FastAPI:
    """Build the dashboard app. Collector imports wait until a data request."""
    from app.aggregate import build_dashboard
    from app.db import open_db
    from app.present import present_dashboard
    from app.proxy import mount_herdr_proxy
    from app.settings import herdr_embed_src, load_settings, public_herdr_href

    if settings is None:
        settings = load_settings()
    _REDACT.add(settings.herdr_web_token)
    _REDACT.add(settings.chat_api_token)

    try:
        db = open_db(
            settings.db_path,
            retention_days=settings.herdr_snapshot_retention_days,
        )
    except Exception:
        _LOGGER.exception("db open failed")
        db = open_db("")

    # Swagger and ReDoc pull a CDN. The dashboard page must stay offline.
    app = FastAPI(docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(_APP_DIR / "templates"))
    app.mount(
        "/static",
        StaticFiles(directory=str(_APP_DIR / "static")),
        name="static",
    )
    mount_herdr_proxy(
        app,
        upstream=settings.herdr_upstream,
        token=settings.herdr_web_token,
        tls_verify=settings.herdr_upstream_tls_verify,
        max_bytes=settings.herdr_proxy_max_bytes,
    )

    resolved = collectors
    run = herdr_runner if herdr_runner is not None else _default_herdr_runner

    def get_collectors() -> dict[str, Callable[..., Any]]:
        nonlocal resolved
        if resolved is None:
            from app.collectors.agents import collect_agents
            from app.collectors.docker import collect_containers
            from app.collectors.git import collect_git
            from app.collectors.host import collect_host

            resolved = {
                "containers": collect_containers,
                "agents": collect_agents,
                "host": collect_host,
                "git": collect_git,
            }
        return resolved

    def call_containers(generated_at: str) -> dict[str, Any]:
        try:
            return get_collectors()["containers"](
                socket_path=settings.docker_socket,
                api_version=settings.docker_api_version,
                timeout=settings.docker_timeout_seconds,
            )
        except Exception:
            _LOGGER.exception("containers collector failed")
            return _containers_fallback(generated_at)

    def call_agents(generated_at: str) -> dict[str, Any]:
        try:
            return get_collectors()["agents"](
                herdr_bin=settings.herdr_bin,
                herdr_timeout=settings.herdr_timeout_seconds,
                herdr_session=settings.herdr_session,
                herdr_config_dir=settings.herdr_config_dir,
                patterns=settings.agent_process_patterns,
                proc_root=settings.proc_root,
                cpu_sample_seconds=settings.cpu_sample_seconds,
                config_home=str(Path.home()),
            )
        except Exception:
            _LOGGER.exception("agents collector failed")
            return _agents_fallback(generated_at)

    def call_host(generated_at: str) -> dict[str, Any]:
        try:
            return get_collectors()["host"](
                proc_root=settings.proc_root,
                host_root=settings.host_root,
                disk_paths=settings.disk_paths,
                cpu_sample_seconds=settings.cpu_sample_seconds,
                cpu_warn=settings.cpu_warn,
                cpu_crit=settings.cpu_crit,
                mem_warn=settings.mem_warn,
                mem_crit=settings.mem_crit,
                disk_warn=settings.disk_warn,
                disk_crit=settings.disk_crit,
            )
        except Exception:
            _LOGGER.exception("host collector failed")
            return _host_fallback(generated_at)

    def call_git(generated_at: str) -> dict[str, Any]:
        collect = get_collectors().get("git")
        if collect is None:
            return {
                "available": True,
                "reason": "",
                "note": "git collector not configured",
                "scanned": False,
                "roots": [],
                "truncated": False,
                "refreshed_at": "",
                "projects": [],
            }
        try:
            return collect(
                roots=settings.git_scan_roots,
                max_depth=settings.git_scan_max_depth,
                max_repos=settings.git_scan_max_repos,
            )
        except Exception:
            _LOGGER.exception("git collector failed")
            return {
                "available": False,
                "reason": "collector error",
                "note": "",
                "scanned": False,
                "roots": [],
                "truncated": False,
                "refreshed_at": generated_at,
                "projects": [],
            }

    def herdr_fields() -> tuple[str, str]:
        try:
            return public_herdr_href(settings), herdr_embed_src(settings)
        except Exception:
            _LOGGER.exception("herdr href failed")
            return "", ""

    def normalize_herdr_status(value: object) -> str:
        try:
            from app.collectors.agents import normalize_status
        except Exception:
            return "unknown"
        if not isinstance(value, str):
            return "unknown"
        try:
            status = normalize_status(value)
        except Exception:
            return "unknown"
        if status in _SNAPSHOT_STATUSES:
            return status
        return "unknown"

    def text_field(value: object) -> str:
        return value if isinstance(value, str) else ""

    def herdr_agent_rows(payload: object) -> list[dict]:
        if not isinstance(payload, dict):
            return []
        rows = payload.get("agents")
        if not isinstance(rows, list):
            return []
        return [
            row
            for row in rows
            if isinstance(row, dict) and row.get("source") == "herdr"
        ]

    def snapshot_rows(payload: object) -> list[dict]:
        agents = herdr_agent_rows(payload)
        if agents:
            return [
                {
                    "herdr_session": settings.herdr_session,
                    "workspace_id": text_field(row.get("workspace_id")),
                    "workspace_label": text_field(row.get("workspace_label")),
                    "tab_id": text_field(row.get("tab_id")),
                    "tab_label": text_field(row.get("tab_label")),
                    "pane_id": text_field(row.get("pane_id")),
                    "agent_kind": text_field(row.get("kind")),
                    "agent_label": text_field(row.get("label")),
                    "status": normalize_herdr_status(row.get("status")),
                    "cwd": text_field(row.get("cwd")),
                }
                for row in agents
            ]
        if not isinstance(payload, dict):
            return []
        workspaces = payload.get("workspaces")
        if not isinstance(workspaces, list):
            return []
        rows: list[dict] = []
        for item in workspaces:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "herdr_session": settings.herdr_session,
                    "workspace_id": text_field(item.get("workspace_id")),
                    "workspace_label": text_field(item.get("label")),
                    "tab_id": "",
                    "tab_label": "",
                    "pane_id": "",
                    "agent_kind": "",
                    "agent_label": "",
                    "status": normalize_herdr_status(item.get("agent_status")),
                    "cwd": "",
                }
            )
        return rows

    def sync_herdr(payload: object) -> None:
        if not db.available:
            return
        try:
            db.insert_snapshots(snapshot_rows(payload))
        except Exception:
            _LOGGER.exception("snapshot insert failed")

    def present_section(key: str, body: Any) -> Any:
        if not isinstance(body, dict):
            return body
        try:
            presented = present_dashboard({key: body})
        except Exception:
            _LOGGER.exception("present failed")
            return body
        if not isinstance(presented, dict):
            return body
        section = presented.get(key, body)
        return section if isinstance(section, dict) else body

    def dashboard() -> dict[str, Any]:
        generated_at = _now()
        containers = call_containers(generated_at)
        agents = call_agents(generated_at)
        host = call_host(generated_at)
        git = call_git(generated_at)
        href, embed_src = herdr_fields()
        try:
            payload = build_dashboard(
                containers=containers,
                agents=agents,
                host=host,
                herdr_href=href,
                herdr_embed=settings.herdr_web_embed,
                herdr_embed_src=embed_src,
                herdr_mode=settings.herdr_mode,
                refresh_seconds=settings.refresh_seconds,
                generated_at=generated_at,
                git=git,
            )
        except Exception:
            _LOGGER.exception("dashboard build failed")
            payload = {
                "generated_at": generated_at,
                "refresh_seconds": settings.refresh_seconds,
                "herdr": {
                    "mode": settings.herdr_mode,
                    "href": "",
                    "embed": False,
                    "embed_src": "",
                    "proxy_path": "/herdr/",
                },
                "containers": containers,
                "agents": agents,
                "host": host,
                "git": git,
            }
        try:
            sync_herdr(agents)
        except Exception:
            _LOGGER.exception("herdr persistence failed")
        try:
            presented = present_dashboard(payload)
        except Exception:
            _LOGGER.exception("present failed")
            return payload
        if not isinstance(presented, dict):
            return payload
        return presented

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/metrics")
    def metrics() -> dict[str, Any]:
        return dashboard()

    @app.get("/api/containers")
    def containers_route() -> Any:
        return present_section("containers", call_containers(_now()))

    @app.get("/api/agents")
    def agents_route() -> Any:
        return present_section("agents", call_agents(_now()))

    @app.get("/api/host")
    def host_route() -> Any:
        return present_section("host", call_host(_now()))

    @app.get("/")
    def index(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=dashboard(),
        )

    @app.get("/m")
    def mobile(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=dashboard(),
        )

    @app.get("/agents/{agent_key}")
    def agent_page(agent_key: str, request: Request):
        data = agent_page_data(
            present_section("agents", call_agents(_now())),
            {"available": True, "sessions": []},
            agent_key,
        )
        return templates.TemplateResponse(
            request=request,
            name="agent.html",
            context={
                "refresh_seconds": settings.refresh_seconds,
                "agent": data,
            },
            status_code=200 if data is not None else 404,
        )

    return app


app = create_app()
