"""Tests for the server-side /herdr token proxy.

These tests build their own FastAPI app and call mount_herdr_proxy. They do
not import app.main, app.settings, or collectors.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import websockets
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.proxy import (
    filter_response_headers,
    hop_request_headers,
    mount_herdr_proxy,
    rewrite_html,
    to_ws_url,
    upstream_url,
)

TOKEN = "super-secret-token"


def test_hop_request_headers_replaces_client_credentials() -> None:
    headers = hop_request_headers(
        {
            "Authorization": "Bearer client",
            "Cookie": "herdr_web_token=nope",
            "X-Forwarded-For": "1.2.3.4",
        },
        TOKEN,
    )
    assert headers == {"authorization": f"Bearer {TOKEN}"}
    assert "cookie" not in headers
    assert "x-forwarded-for" not in headers


def test_hop_request_headers_omits_authorization_when_token_empty() -> None:
    headers = hop_request_headers(
        {"Accept": "text/html", "Authorization": "Bearer client", "Host": "evil.test"},
        "",
    )
    assert headers == {"accept": "text/html"}


def test_filter_response_headers_drops_token_cookie_and_framing() -> None:
    headers = filter_response_headers(
        {
            "Set-Cookie": f"herdr_web_token={TOKEN}",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "frame-ancestors 'none'",
            "Content-Security-Policy-Report-Only": "default-src 'none'",
            "Content-Type": "text/html",
        },
        TOKEN,
    )
    assert "set-cookie" not in headers
    assert "x-frame-options" not in headers
    assert "content-security-policy" not in headers
    assert "content-security-policy-report-only" not in headers
    assert headers["content-type"] == "text/html"
    assert TOKEN not in str(headers)


def test_filter_response_headers_drops_cookie_value_containing_token() -> None:
    leaked = filter_response_headers({"Set-Cookie": f"other=pre-{TOKEN}-post"}, TOKEN)
    assert "set-cookie" not in leaked
    kept = filter_response_headers({"Set-Cookie": "session=abc"}, TOKEN)
    assert kept["set-cookie"] == "session=abc"
    unnamed = filter_response_headers({"Set-Cookie": "herdr_web_token=whatever"}, "")
    assert "set-cookie" not in unnamed


def test_filter_response_headers_rewrites_upstream_location() -> None:
    headers = filter_response_headers(
        {"Location": "http://127.0.0.1:7317/assets/app.js?x=1"},
        TOKEN,
        upstream="http://127.0.0.1:7317",
    )
    assert headers["location"] == "/herdr/assets/app.js?x=1"
    external = filter_response_headers(
        {"Location": "http://evil.test/x"},
        TOKEN,
        upstream="http://127.0.0.1:7317",
    )
    assert external["location"] == "http://evil.test/x"


def test_rewrite_html_prefixes_root_absolute_and_omits_token() -> None:
    rewritten = rewrite_html('<head><script src="/assets/app.js"></script></head>', "/herdr")
    assert 'src="/herdr/assets/app.js"' in rewritten
    assert TOKEN not in rewritten
    assert rewritten.startswith("<head><script>")
    for needle in ("fetch", "XMLHttpRequest.prototype.open", "WebSocket", "EventSource"):
        assert needle in rewritten
    assert "http://" not in rewritten
    assert "https://" not in rewritten
    kept = rewrite_html(
        '<head><a href="//cdn.example/a"></a><a href="/herdr/ok"></a></head>',
        "/herdr",
    )
    assert 'href="//cdn.example/a"' in kept
    assert 'href="/herdr/ok"' in kept
    assert 'href="/herdr/herdr/ok"' not in kept
    assert 'href="/herdr//cdn.example/a"' not in kept
    no_head = rewrite_html('<a href="/x">', "/herdr")
    assert no_head.startswith("<script>")
    assert 'href="/herdr/x"' in no_head


def test_upstream_url_keeps_fixed_host() -> None:
    assert upstream_url("http://127.0.0.1:7317", "/etc/passwd") == "http://127.0.0.1:7317/etc/passwd"
    assert urlsplit(upstream_url("http://127.0.0.1:7317", "/etc/passwd")).netloc == "127.0.0.1:7317"
    evil = upstream_url("http://127.0.0.1:7317", "http://evil.test/x")
    parsed = urlsplit(evil)
    assert parsed.scheme == "http"
    assert parsed.netloc == "127.0.0.1:7317"
    assert "evil.test" in parsed.path
    assert upstream_url("http://127.0.0.1:7317", "") == "http://127.0.0.1:7317/"


def test_to_ws_url_maps_http_schemes() -> None:
    assert to_ws_url("https://127.0.0.1:7317/ws") == "wss://127.0.0.1:7317/ws"
    assert to_ws_url("http://127.0.0.1:7317/ws") == "ws://127.0.0.1:7317/ws"


def test_proxy_module_has_no_token_and_no_sibling_imports() -> None:
    source = Path(__file__).resolve().parents[1].joinpath("app", "proxy.py").read_text()
    assert TOKEN not in source
    assert "app.settings" not in source
    assert "app.main" not in source
    assert "app.collectors" not in source
    assert "os.environ" not in source


class _RecordingHandler(BaseHTTPRequestHandler):
    body = b""
    extra_headers: list[tuple[str, str]] = []
    seen: dict[str, str] = {}
    path_seen = ""

    def do_GET(self) -> None:  # noqa: N802
        type(self).seen = {key.lower(): value for key, value in self.headers.items()}
        type(self).path_seen = self.path
        payload = self.body
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        for key, value in self.extra_headers:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def _serve(body: bytes, extra_headers: list[tuple[str, str]]) -> tuple[ThreadingHTTPServer, threading.Thread]:
    handler = type(
        "Handler",
        (_RecordingHandler,),
        {"body": body, "extra_headers": extra_headers, "seen": {}, "path_seen": ""},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop(server: ThreadingHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


def test_http_proxy_injects_bearer_and_hides_token() -> None:
    body = f"<head><!--{TOKEN}--><script src=\"/assets/app.js\"></script></head>".encode()
    extra = [
        ("Set-Cookie", f"herdr_web_token={TOKEN}; Path=/"),
        ("Set-Cookie", "session=abc"),
        ("X-Frame-Options", "DENY"),
        ("Content-Security-Policy", "frame-ancestors 'none'"),
        ("X-Debug", TOKEN),
    ]
    server, thread = _serve(body, extra)
    host, port = server.server_address
    app = FastAPI()
    mount_herdr_proxy(
        app,
        upstream=f"http://{host}:{port}",
        token=TOKEN,
        tls_verify=False,
    )
    try:
        with TestClient(app) as client:
            response = client.get(
                "/herdr/index.html?q=1",
                headers={
                    "Authorization": "Bearer client",
                    "Cookie": "herdr_web_token=nope",
                    "X-Forwarded-For": "1.2.3.4",
                    "X-Forwarded-Host": "evil.test",
                    "Forwarded": "for=1.2.3.4",
                },
            )
        handler = server.RequestHandlerClass
        assert handler.seen.get("authorization") == f"Bearer {TOKEN}"
        assert "cookie" not in handler.seen
        assert "x-forwarded-for" not in handler.seen
        assert "x-forwarded-host" not in handler.seen
        assert "forwarded" not in handler.seen
        assert handler.path_seen.startswith("/index.html")
        assert "q=1" in handler.path_seen
    finally:
        _stop(server, thread)

    assert response.status_code == 200
    assert 'src="/herdr/assets/app.js"' in response.text
    assert TOKEN not in response.text
    assert "Traceback" not in response.text
    assert response.headers.get("x-frame-options") is None
    assert response.headers.get("content-security-policy") is None
    cookies = response.headers.get_list("set-cookie")
    assert any(cookie.startswith("session=abc") for cookie in cookies)
    assert all("herdr_web_token" not in cookie for cookie in cookies)
    header_blob = "\n".join(f"{key}: {value}" for key, value in response.headers.items())
    assert TOKEN not in header_blob


def test_upstream_connection_refused_is_plain_502() -> None:
    app = FastAPI()
    mount_herdr_proxy(app, upstream="http://127.0.0.1:9", token=TOKEN, tls_verify=False)
    with TestClient(app) as client:
        response = client.get("/herdr/")
    assert response.status_code == 502
    assert response.text == "herdr upstream unavailable"
    assert TOKEN not in response.text
    assert "Traceback" not in response.text


def test_oversize_upstream_is_plain_502() -> None:
    server, thread = _serve(b"x" * 64, [])
    host, port = server.server_address
    app = FastAPI()
    mount_herdr_proxy(
        app,
        upstream=f"http://{host}:{port}",
        token=TOKEN,
        tls_verify=False,
        max_bytes=8,
    )
    try:
        with TestClient(app) as client:
            response = client.get("/herdr/")
    finally:
        _stop(server, thread)
    assert response.status_code == 502
    assert response.text == "herdr upstream unavailable"
    assert TOKEN not in response.text


def test_websocket_handshake_gets_bearer_token() -> None:
    recorded: list[dict[str, str]] = []
    ready = threading.Event()
    stop = threading.Event()
    port_holder: dict[str, int] = {}

    async def handler(websocket: object) -> None:
        headers = {key.lower(): value for key, value in websocket.request_headers.items()}
        recorded.append(headers)
        try:
            await websocket.wait_closed()
        except Exception:
            return

    async def runner() -> None:
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            sock = next(iter(server.sockets))
            port_holder["port"] = sock.getsockname()[1]
            ready.set()
            while not stop.is_set():
                await asyncio.sleep(0.05)

    thread = threading.Thread(target=lambda: asyncio.run(runner()), daemon=True)
    thread.start()
    assert ready.wait(5)
    app = FastAPI()
    mount_herdr_proxy(
        app,
        upstream=f"http://127.0.0.1:{port_holder['port']}",
        token=TOKEN,
        tls_verify=True,
    )
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/herdr/ws") as websocket:
                websocket.close()
    finally:
        stop.set()
        thread.join(timeout=2)

    assert recorded
    assert recorded[0].get("authorization") == f"Bearer {TOKEN}"
    assert TOKEN not in recorded[0].get("cookie", "")
