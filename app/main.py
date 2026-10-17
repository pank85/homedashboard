"""Dashboard routes, page, and degrade-on-collector-failure shell.

Collectors are imported only when ``collectors`` is None, and only when a
data route runs. A collector exception becomes that panel's unavailable
object. ``herdr_web_token`` and ``chat_api_token`` are never placed in a
response body. Session mutations fail closed and spawn herdr with an argv
list only.
"""

from __future__ import annotations

import json
import logging
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

_LOGGER = logging.getLogger("homedashboard")
_APP_DIR = Path(__file__).resolve().parent
_HERDR_HREF = "/herdr/"
_SESSION_COLUMNS = (
    "id",
    "label",
    "agent_kind",
    "herdr_session",
    "workspace_id",
    "tab_id",
    "pane_id",
    "agent_name",
    "cwd",
    "status",
    "last_error",
    "created_at",
    "updated_at",
)
_CLOSED_SESSION_STATUSES = frozenset({"archived", "failed", "starting"})
_POLL_STATUSES = frozenset({"running", "idle", "blocked", "done"})
_SNAPSHOT_STATUSES = frozenset({"working", "idle", "blocked", "done"})
_LAST_ERROR_LIMIT = 500


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


class _Spawn:
    def __init__(
        self,
        returncode: int | None,
        stdout: str,
        stderr: str,
        *,
        timed_out: bool,
        crashed: bool,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.crashed = crashed

    @property
    def ok(self) -> bool:
        return not self.timed_out and not self.crashed and self.returncode == 0


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


def _json(status: int, payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=payload)


def _as_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return ""


def _json_object(raw: bytes) -> dict[str, Any]:
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _form_object(raw: bytes) -> dict[str, Any]:
    parsed = parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[0] for key, values in parsed.items() if values}


async def _read_request_fields(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type or content_type.endswith("+json"):
        return _json_object(await request.body())
    if "application/x-www-form-urlencoded" in content_type:
        return _form_object(await request.body())
    if "multipart/form-data" in content_type:
        form = await request.form()
        return {str(key): form.get(key) for key in form.keys()}
    if content_type == "":
        raw = await request.body()
        if not raw or not raw.strip():
            return {}
        stripped = raw.lstrip()
        if stripped.startswith(b"{") or stripped.startswith(b"["):
            return _json_object(raw)
    return {}


async def _request_fields(request: Request) -> dict[str, Any]:
    try:
        return await _read_request_fields(request)
    except Exception:
        return {}


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
    from app.sessions_policy import (
        AGENT_START_KINDS,
        AGENT_START_SUBPROCESS_TIMEOUT,
        PolicyError,
        agent_start_argv,
        attach_command,
        display_argv,
        parse_workspace_created,
        token_status,
        validate_cwd,
        validate_kind,
        validate_label,
        validate_session_id,
        validate_session_name,
        workspace_create_argv,
    )
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
                herdr_session=settings.herdr_session,
                herdr_config_dir=settings.herdr_config_dir,
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

    def mutations_enabled() -> bool:
        return bool(settings.chat_api_token.strip())

    def db_reason() -> str:
        reason = db.reason
        if isinstance(reason, str) and reason:
            return reason
        return "persistence unavailable"

    def unavailable() -> JSONResponse:
        return _json(503, {"error": "unavailable", "reason": db_reason()})

    def invalid(reason: str) -> JSONResponse:
        return _json(400, {"error": "invalid", "reason": reason})

    def clip(text: str) -> str:
        redacted = text
        for secret in (settings.chat_api_token, settings.herdr_web_token):
            if secret:
                redacted = redacted.replace(secret, "[redacted]")
        return redacted[:_LAST_ERROR_LIMIT]

    def session_public(row: dict) -> dict[str, Any]:
        public = {column: row.get(column, "") for column in _SESSION_COLUMNS}
        name = public.get("herdr_session")
        if isinstance(name, str):
            try:
                public["attach_command"] = attach_command(name)
            except PolicyError:
                public["attach_command"] = ""
        else:
            public["attach_command"] = ""
        public["herdr_href"] = _HERDR_HREF
        return public

    def sessions_fallback(reason: str | None = None) -> dict[str, Any]:
        return {
            "available": False,
            "reason": reason or "persistence unavailable",
            "mutations_enabled": mutations_enabled(),
            "kinds": list(AGENT_START_KINDS),
            "sessions": [],
        }

    def sessions_object() -> dict[str, Any]:
        enabled = mutations_enabled()
        kinds = list(AGENT_START_KINDS)
        if not db.available:
            return {
                "available": False,
                "reason": db_reason(),
                "mutations_enabled": enabled,
                "kinds": kinds,
                "sessions": [],
            }
        try:
            rows = db.list_sessions()
        except Exception:
            _LOGGER.exception("session list failed")
            return sessions_fallback(db_reason())
        return {
            "available": True,
            "reason": None,
            "mutations_enabled": enabled,
            "kinds": kinds,
            "sessions": [session_public(row) for row in rows],
        }

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

    def mapped_session_status(value: object) -> str | None:
        normalized = normalize_herdr_status(value)
        if normalized == "working":
            return "running"
        if normalized in _POLL_STATUSES:
            return normalized
        return None

    def poll_open_sessions(rows: list[dict]) -> None:
        by_pane: dict[str, object] = {}
        for row in rows:
            pane = row.get("pane_id")
            if isinstance(pane, str) and pane and pane not in by_pane:
                by_pane[pane] = row.get("status")
        for session in db.list_sessions():
            if session.get("status") in _CLOSED_SESSION_STATUSES:
                continue
            pane = session.get("pane_id")
            if not isinstance(pane, str) or not pane or pane not in by_pane:
                continue
            mapped = mapped_session_status(by_pane[pane])
            if mapped is None:
                continue
            db.update_status_if_open(session["id"], mapped)

    def sync_herdr(payload: object) -> None:
        if not db.available:
            return
        try:
            db.insert_snapshots(snapshot_rows(payload))
        except Exception:
            _LOGGER.exception("snapshot insert failed")
        try:
            poll_open_sessions(herdr_agent_rows(payload))
        except Exception:
            _LOGGER.exception("session status poll failed")

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
            }
        try:
            sync_herdr(agents)
        except Exception:
            _LOGGER.exception("herdr persistence failed")
        try:
            payload["sessions"] = sessions_object()
        except Exception:
            _LOGGER.exception("sessions attach failed")
            payload["sessions"] = sessions_fallback()
        try:
            presented = present_dashboard(payload)
        except Exception:
            _LOGGER.exception("present failed")
            return payload
        if not isinstance(presented, dict):
            return payload
        return presented

    def authorize(request: Request, fields: dict[str, Any]) -> JSONResponse | None:
        form_token = fields.get("token")
        status = token_status(
            settings.chat_api_token,
            request.headers.get("authorization"),
            form_token if isinstance(form_token, str) else None,
        )
        if status == "unset":
            return _json(
                403,
                {"error": "forbidden", "reason": "CHAT_API_TOKEN unset"},
            )
        if status != "ok":
            return _json(
                401,
                {"error": "unauthorized", "reason": "invalid token"},
            )
        return None

    def kind_arg(value: object) -> str:
        return value if isinstance(value, str) else ""

    def cwd_arg(value: object) -> str:
        return value if isinstance(value, str) else ""

    def label_arg(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        raise PolicyError("invalid label")

    def spawn(argv: list[str], timeout: float) -> _Spawn:
        if not isinstance(argv, list) or any(not isinstance(part, str) for part in argv):
            return _Spawn(None, "", "", timed_out=False, crashed=True)
        try:
            result = run(argv, timeout)
        except subprocess.TimeoutExpired as exc:
            return _Spawn(
                None,
                _as_text(getattr(exc, "stdout", None)),
                _as_text(getattr(exc, "stderr", None)),
                timed_out=True,
                crashed=False,
            )
        except Exception as exc:
            if isinstance(exc, AssertionError):
                raise
            _LOGGER.exception("herdr runner failed")
            return _Spawn(None, "", "", timed_out=False, crashed=True)
        returncode = getattr(result, "returncode", 1)
        if isinstance(returncode, bool) or not isinstance(returncode, int):
            returncode = 1
        return _Spawn(
            returncode,
            _as_text(getattr(result, "stdout", None)),
            _as_text(getattr(result, "stderr", None)),
            timed_out=False,
            crashed=False,
        )

    def failure_detail(result: _Spawn) -> str:
        stderr = result.stderr.strip()
        if stderr:
            return stderr
        if result.timed_out:
            return "herdr timed out"
        if result.returncode is None:
            return "herdr runner failed"
        return f"herdr exited {result.returncode}"

    def fail_session(
        stored: dict,
        argv: list[str],
        detail: str,
        ids: dict[str, str] | None = None,
    ) -> JSONResponse:
        # Leave the herdr workspace in place. Do not close, stop, or delete it.
        last_error = clip(f"{display_argv(argv)}: {detail or 'herdr exited 1'}")
        updates: dict[str, str] = {}
        if ids:
            for key in ("workspace_id", "tab_id", "pane_id"):
                value = ids.get(key)
                if isinstance(value, str):
                    updates[key] = value
        try:
            row = db.mark_failed(stored["id"], last_error, **updates)
        except Exception:
            _LOGGER.exception("mark_failed failed")
            row = {column: stored.get(column, "") for column in _SESSION_COLUMNS}
            row["status"] = "failed"
            row["last_error"] = last_error
            row.update(updates)
        return _json(
            502,
            {
                "error": "herdr",
                "reason": last_error,
                "session": session_public(row),
            },
        )

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

    @app.get("/api/sessions")
    def sessions_route() -> Any:
        return present_section("sessions", sessions_object())

    @app.post("/api/sessions")
    async def create_session(request: Request) -> JSONResponse:
        fields = await _request_fields(request)
        denied = authorize(request, fields)
        if denied is not None:
            return denied
        try:
            session_name = validate_session_name(settings.herdr_session)
            kind = validate_kind(kind_arg(fields.get("kind")))
            label = validate_label(label_arg(fields.get("label")), kind=kind)
            cwd = validate_cwd(
                cwd_arg(fields.get("cwd")),
                settings.chat_cwd_allowlist,
            )
        except PolicyError as exc:
            return invalid(exc.reason)
        if not db.available:
            return unavailable()
        try:
            stored = db.create_session(
                {
                    "id": uuid.uuid4().hex,
                    "label": label,
                    "agent_kind": kind,
                    "herdr_session": session_name,
                    "cwd": cwd,
                    "status": "starting",
                }
            )
        except Exception:
            _LOGGER.exception("session insert failed")
            return unavailable()
        create_argv = workspace_create_argv(
            settings.herdr_bin,
            session_name,
            cwd,
            label,
        )
        created_spawn = spawn(create_argv, settings.herdr_timeout_seconds)
        if not created_spawn.ok:
            return fail_session(stored, create_argv, failure_detail(created_spawn))
        try:
            created = parse_workspace_created(created_spawn.stdout)
        except PolicyError as exc:
            return fail_session(stored, create_argv, exc.reason)
        start_argv = agent_start_argv(
            settings.herdr_bin,
            session_name,
            label,
            kind,
            created["pane_id"],
        )
        started = spawn(start_argv, AGENT_START_SUBPROCESS_TIMEOUT)
        if not started.ok:
            return fail_session(
                stored,
                start_argv,
                failure_detail(started),
                created,
            )
        try:
            running = db.mark_running(
                stored["id"],
                workspace_id=created["workspace_id"],
                tab_id=created["tab_id"],
                pane_id=created["pane_id"],
                agent_name=label,
            )
        except Exception:
            _LOGGER.exception("mark_running failed")
            return unavailable()
        return _json(201, {"session": session_public(running)})

    @app.post("/api/sessions/{session_id}/archive")
    async def archive_session(session_id: str, request: Request) -> JSONResponse:
        fields = await _request_fields(request)
        denied = authorize(request, fields)
        if denied is not None:
            return denied
        try:
            cleaned = validate_session_id(session_id)
        except PolicyError as exc:
            return invalid(exc.reason)
        if not db.available:
            return unavailable()
        try:
            row = db.archive_session(cleaned)
        except Exception:
            _LOGGER.exception("session archive failed")
            return unavailable()
        if row is None:
            return _json(
                404,
                {"error": "not_found", "reason": "session not found"},
            )
        return _json(200, {"session": session_public(row)})

    @app.get("/")
    def index(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=dashboard(),
        )

    return app


app = create_app()
