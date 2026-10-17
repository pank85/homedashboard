"""Dashboard routes, page, and degrade-on-collector-failure shell.

Collectors are imported only when ``collectors`` is None, and only when a
data route runs. A collector exception becomes that panel's unavailable
object. ``herdr_web_token`` is never placed in a response body.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

_LOGGER = logging.getLogger("homedashboard")
_APP_DIR = Path(__file__).resolve().parent


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
) -> FastAPI:
    """Build the dashboard app. Collector imports wait until a data request."""
    from app.aggregate import build_dashboard
    from app.proxy import mount_herdr_proxy
    from app.settings import herdr_embed_src, load_settings, public_herdr_href

    if settings is None:
        settings = load_settings()
    _REDACT.add(settings.herdr_web_token)

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

    def get_collectors() -> dict[str, Callable[..., Any]]:
        nonlocal resolved
        if resolved is None:
            from app.collectors.agents import collect_agents
            from app.collectors.docker import collect_containers
            from app.collectors.host import collect_host

            resolved = {
                "containers": collect_containers,
                "agents": collect_agents,
                "host": collect_host,
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
                patterns=settings.agent_process_patterns,
                proc_root=settings.proc_root,
                cpu_sample_seconds=settings.cpu_sample_seconds,
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

    def herdr_fields() -> tuple[str, str]:
        try:
            return public_herdr_href(settings), herdr_embed_src(settings)
        except Exception:
            _LOGGER.exception("herdr href failed")
            return "", ""

    def dashboard() -> dict[str, Any]:
        generated_at = _now()
        containers = call_containers(generated_at)
        agents = call_agents(generated_at)
        host = call_host(generated_at)
        href, embed_src = herdr_fields()
        try:
            return build_dashboard(
                containers=containers,
                agents=agents,
                host=host,
                herdr_href=href,
                herdr_embed=settings.herdr_web_embed,
                herdr_embed_src=embed_src,
                herdr_mode=settings.herdr_mode,
                refresh_seconds=settings.refresh_seconds,
                generated_at=generated_at,
            )
        except Exception:
            _LOGGER.exception("dashboard build failed")
            return {
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
            }

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/metrics")
    def metrics() -> dict[str, Any]:
        return dashboard()

    @app.get("/api/containers")
    def containers_route() -> dict[str, Any]:
        return call_containers(_now())

    @app.get("/api/agents")
    def agents_route() -> dict[str, Any]:
        return call_agents(_now())

    @app.get("/api/host")
    def host_route() -> dict[str, Any]:
        return call_host(_now())

    @app.get("/")
    def index(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=dashboard(),
        )

    return app


app = create_app()
