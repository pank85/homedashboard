"""Same-process reverse proxy for Herdr Web under ``/herdr``.

The upstream base URL is fixed when the proxy is mounted. Request paths are
appended to that base and are never parsed as a new URL, so a client cannot
move the token to another host.

When ``token`` is non-empty, every upstream HTTP request and WebSocket
handshake gets ``Authorization: Bearer <token>``. Inbound ``Authorization``
and ``Cookie`` are dropped, so the browser cannot supply or observe the
credential. Upstream ``Set-Cookie`` is dropped when its name is
``herdr_web_token`` or its value contains the token. The token is redacted
from proxied bodies and is never written into the HTML shim, error text, or
logs. This module does not read the environment.

CSP relaxation: proxied responses drop ``Content-Security-Policy``,
``Content-Security-Policy-Report-Only``, and ``X-Frame-Options``. That is
intentional and weaker than an upstream ``frame-ancestors 'none'`` policy. It
lets the dashboard iframe embed ``/herdr/`` and lets the injected same-origin
path shim run. Direct embeds of another origin can still be blank because
this proxy never sees those responses. Service workers (for example
``/sw.js``) are not supported through this proxy.

Redirects are not followed. Following them could send the bearer token to a
``Location`` on another host. Same-origin ``Location`` values are rewritten
under ``/herdr`` so the browser stays on the proxy. ``X-Forwarded-For``,
``X-Forwarded-Host``, and ``Forwarded`` are stripped and never added, so a
tokenless loopback upstream still looks local.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import re
import ssl
import zlib
from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

import httpx
import websockets
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response

_UPSTREAM_UNAVAILABLE = "herdr upstream unavailable"
_PREFIX = "/herdr"

_REQUEST_DROP = frozenset(
    {
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
)

_RESPONSE_DROP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "x-frame-options",
        "content-security-policy",
        "content-security-policy-report-only",
        "content-length",
    }
)

_WS_HANDSHAKE_DROP = frozenset(
    {
        "sec-websocket-key",
        "sec-websocket-version",
        "sec-websocket-extensions",
        "sec-websocket-protocol",
        "sec-websocket-accept",
    }
)

_HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]

_QUOTED_ATTR = re.compile(
    r"(?P<name>\b(?:src|href|action))(?P<eq>\s*=\s*)(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.IGNORECASE | re.DOTALL,
)
_HEAD_OPEN = re.compile(r"<head\b[^>]*>", re.IGNORECASE)

# Prefix is substituted as a JSON string. The script must not reference an
# external URL and must not contain the proxy token (it never receives one).
_SHIM = """(function(){
  var prefix = __PREFIX__;
  function startsWithPrefix(path) {
    return path.indexOf(prefix) === 0;
  }
  function rewrite(url) {
    if (typeof url !== "string" || !url) return url;
    if (url.charAt(0) === "/" && url.charAt(1) !== "/") {
      if (!startsWithPrefix(url)) return prefix + url;
      return url;
    }
    try {
      var loc = window.location;
      if (!loc || !loc.host) return url;
      var origin = loc.protocol + "//" + loc.host;
      if (url.indexOf(origin) !== 0) return url;
      var rest = url.slice(origin.length);
      if (rest === "" || rest.charAt(0) === "?" || rest.charAt(0) === "#") rest = "/" + rest;
      if (rest.charAt(0) === "/" && rest.charAt(1) !== "/" && !startsWithPrefix(rest)) {
        return prefix + rest;
      }
    } catch (e) {}
    return url;
  }
  if (window.fetch) {
    var origFetch = window.fetch;
    window.fetch = function(input, init) {
      if (typeof input === "string") {
        input = rewrite(input);
      } else if (input && typeof input.url === "string" && typeof Request === "function") {
        try { input = new Request(rewrite(input.url), input); } catch (e) {}
      }
      return origFetch.call(this, input, init);
    };
  }
  if (window.XMLHttpRequest && XMLHttpRequest.prototype) {
    var origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function() {
      var args = Array.prototype.slice.call(arguments);
      if (args.length > 1 && typeof args[1] === "string") args[1] = rewrite(args[1]);
      return origOpen.apply(this, args);
    };
  }
  if (window.WebSocket) {
    var OrigWS = window.WebSocket;
    var WrappedWS = function(url, protocols) {
      var next = rewrite(url);
      if (arguments.length > 1) return new OrigWS(next, protocols);
      return new OrigWS(next);
    };
    WrappedWS.prototype = OrigWS.prototype;
    WrappedWS.CONNECTING = OrigWS.CONNECTING;
    WrappedWS.OPEN = OrigWS.OPEN;
    WrappedWS.CLOSING = OrigWS.CLOSING;
    WrappedWS.CLOSED = OrigWS.CLOSED;
    window.WebSocket = WrappedWS;
  }
  if (window.EventSource) {
    var OrigES = window.EventSource;
    var WrappedES = function(url, opts) {
      if (arguments.length > 1) return new OrigES(rewrite(url), opts);
      return new OrigES(rewrite(url));
    };
    WrappedES.prototype = OrigES.prototype;
    window.EventSource = WrappedES;
  }
})();"""


def upstream_url(upstream: str, path: str) -> str:
    """Join ``path`` onto the fixed upstream base.

    Empty ``path`` returns ``base + "/"``. Otherwise the result is
    ``base.rstrip("/") + "/" + path.lstrip("/")``. ``path`` is a path
    segment, never a replacement URL.
    """
    if path == "":
        return upstream + "/"
    return upstream.rstrip("/") + "/" + path.lstrip("/")


def to_ws_url(url: str) -> str:
    """Map an HTTP(S) URL to the matching WebSocket URL."""
    if url.startswith("https://"):
        return "wss://" + url[len("https://") :]
    if url.startswith("http://"):
        return "ws://" + url[len("http://") :]
    return url


def hop_request_headers(headers: dict, token: str) -> dict:
    """Copy request headers for the upstream call.

    Drops hop-by-hop and client credential headers. When ``token`` is
    non-empty, sets ``authorization`` to ``Bearer {token}``.
    """
    cleaned: dict[str, str] = {}
    for key, value in headers.items():
        name = str(key).lower()
        if name in _REQUEST_DROP:
            continue
        cleaned[name] = value if isinstance(value, str) else str(value)
    if token:
        cleaned["authorization"] = f"Bearer {token}"
    return cleaned


def _cookie_name(value: str) -> str:
    first = value.split(";", 1)[0]
    name = first.split("=", 1)[0]
    return name.strip().lower()


def _drop_set_cookie(value: str, token: str) -> bool:
    if _cookie_name(value) == "herdr_web_token":
        return True
    return bool(token) and token in value


def _rewrite_location(value: str, upstream: str, prefix: str = _PREFIX) -> str:
    if not upstream:
        return value
    upstream_parts = urlsplit(upstream)
    if not upstream_parts.scheme or not upstream_parts.netloc:
        return value
    location_parts = urlsplit(value.strip())
    if location_parts.scheme.lower() != upstream_parts.scheme.lower():
        return value
    if location_parts.netloc.lower() != upstream_parts.netloc.lower():
        return value
    path = location_parts.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    if path == prefix or path.startswith(prefix + "/"):
        new_path = path
    else:
        new_path = prefix + path
    return urlunsplit(("", "", new_path, location_parts.query, location_parts.fragment))


def _connection_names(items: Iterable[tuple[str, str]]) -> set[str]:
    names: set[str] = set()
    for key, value in items:
        if str(key).lower() != "connection":
            continue
        for part in str(value).split(","):
            name = part.strip().lower()
            if name:
                names.add(name)
    return names


def _redact(value: str, token: str) -> str:
    if not token or token not in value:
        return value
    return value.replace(token, "")


def _filter_header_items(
    items: Iterable[tuple[str, str]],
    token: str,
    upstream: str = "",
) -> list[tuple[str, str]]:
    listed = [(str(key), "" if value is None else str(value)) for key, value in items]
    connection_drop = _connection_names(listed)
    kept: list[tuple[str, str]] = []
    for key, value in listed:
        name = key.lower()
        if name in _RESPONSE_DROP or name in connection_drop:
            continue
        if name == "set-cookie" and _drop_set_cookie(value, token):
            continue
        if name == "location":
            value = _rewrite_location(value, upstream)
        value = _redact(value, token)
        if token and token in value:
            continue
        kept.append((name, value))
    return kept


def filter_response_headers(headers: dict, token: str, upstream: str = "") -> dict:
    """Drop hop-by-hop, framing, and token cookies from an upstream response.

    ``Location`` values that start with the upstream origin are rewritten to
    the same path under ``/herdr``. ``upstream`` is optional so the
    two-argument call still drops cookies and framing headers; the mounted
    proxy passes the startup upstream.
    """
    return dict(_filter_header_items(headers.items(), token, upstream))


def _normalize_prefix(prefix: str) -> str:
    text = (prefix or _PREFIX).strip() or _PREFIX
    if not text.startswith("/"):
        text = "/" + text
    return text.rstrip("/") or _PREFIX


def _prefix_attribute(match: re.Match[str], prefix: str) -> str:
    value = match.group("value")
    if value.startswith("/") and not value.startswith("//") and not value.startswith(prefix):
        value = prefix + value
    return f"{match.group('name')}{match.group('eq')}{match.group('quote')}{value}{match.group('quote')}"


def _shim_script(prefix: str) -> str:
    encoded = json.dumps(prefix).replace("<", "\\u003c")
    return "<script>" + _SHIM.replace("__PREFIX__", encoded) + "</script>"


def rewrite_html(html: str, prefix: str = _PREFIX) -> str:
    """Prefix root-absolute ``src``/``href``/``action`` values and inject the path shim.

    Values that start with ``//`` or already start with the prefix are left
    alone. The shim is the first child of ``<head>``, or the whole document
    is prepended when there is no head. The shim does not receive the token
    and does not reference an external URL.
    """
    normalized = _normalize_prefix(prefix)
    rewritten = _QUOTED_ATTR.sub(lambda match: _prefix_attribute(match, normalized), html)
    shim = _shim_script(normalized)
    head = _HEAD_OPEN.search(rewritten)
    if head is None:
        return shim + rewritten
    index = head.end()
    return rewritten[:index] + shim + rewritten[index:]


def _unavailable(token: str = "") -> Response:
    body = _redact(_UPSTREAM_UNAVAILABLE, token)
    return Response(content=body, status_code=502, media_type="text/plain")


def _content_type(items: Iterable[tuple[str, str]]) -> str:
    for key, value in items:
        if str(key).lower() == "content-type":
            return str(value)
    return ""


def _is_html(content_type: str) -> bool:
    media = content_type.split(";", 1)[0].strip().lower()
    return media in {"text/html", "application/xhtml+xml"}


def _charset_name(content_type: str) -> str:
    for part in content_type.split(";")[1:]:
        key, sep, value = part.strip().partition("=")
        if sep and key.lower() == "charset" and value.strip():
            return value.strip().strip("\"'")
    return "utf-8"


def _decode_body(body: bytes, content_type: str) -> tuple[str, str]:
    charset = _charset_name(content_type)
    try:
        return body.decode(charset), charset
    except (LookupError, UnicodeError):
        return body.decode("utf-8", errors="replace"), "utf-8"


def _redact_bytes(body: bytes, token: str) -> bytes:
    if not token:
        return body
    token_bytes = token.encode("utf-8")
    if token_bytes:
        body = body.replace(token_bytes, b"")
    return body


def _decompress(body: bytes, encoding: str) -> tuple[bytes, bool]:
    enc = encoding.split(",")[-1].strip().lower()
    if enc in {"", "identity"}:
        return body, False
    if enc in {"gzip", "x-gzip"}:
        return gzip.decompress(body), True
    if enc == "deflate":
        try:
            return zlib.decompress(body), True
        except zlib.error:
            return zlib.decompress(body, -zlib.MAX_WBITS), True
    return body, False


def _header_value(items: Iterable[tuple[str, str]], name: str) -> str:
    for key, value in items:
        if str(key).lower() == name:
            return str(value)
    return ""


def _response(status: int, body: bytes, items: list[tuple[str, str]]) -> Response:
    response = Response(content=body, status_code=status)
    for key, value in items:
        response.headers.append(key, value)
    return response


def _ssl_context(tls_verify: bool) -> ssl.SSLContext | bool:
    if tls_verify:
        return True
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def mount_herdr_proxy(
    app: FastAPI,
    *,
    upstream: str,
    token: str,
    tls_verify: bool = False,
    max_bytes: int = 33554432,
) -> None:
    """Register ``/herdr`` HTTP and WebSocket routes on ``app``.

    ``upstream`` and ``token`` are fixed for the process. ``tls_verify`` is
    passed to the HTTP client and, for ``wss://``, to the WebSocket client.
    Upstream failure, timeout, and oversize bodies become plain text 502.
    """

    async def proxy_http(request: Request, path: str = "") -> Response:
        try:
            return await _proxy_http(request, path)
        except Exception:
            return _unavailable(token)

    async def _proxy_http(request: Request, path: str) -> Response:
        target = upstream_url(upstream, path)
        if request.url.query:
            target = f"{target}?{request.url.query}"
        headers = hop_request_headers(dict(request.headers), token)
        if "accept-encoding" not in headers:
            headers["accept-encoding"] = "identity"
        body = await request.body()
        timeout = httpx.Timeout(30.0, connect=5.0)
        async with httpx.AsyncClient(
            verify=tls_verify,
            timeout=timeout,
            follow_redirects=False,
            headers={"Accept-Encoding": "identity"},
        ) as client:
            async with client.stream(
                request.method,
                target,
                headers=headers,
                content=body,
            ) as upstream_response:
                declared = upstream_response.headers.get("content-length")
                if declared:
                    try:
                        if int(declared) > max_bytes:
                            return _unavailable(token)
                    except ValueError:
                        pass
                chunks: list[bytes] = []
                total = 0
                async for chunk in upstream_response.aiter_raw():
                    total += len(chunk)
                    if total > max_bytes:
                        return _unavailable(token)
                    chunks.append(chunk)
                raw = b"".join(chunks)
                status = upstream_response.status_code
                raw_items = [(str(key), str(value)) for key, value in upstream_response.headers.multi_items()]
        encoding = _header_value(raw_items, "content-encoding")
        try:
            decoded, did_decode = _decompress(raw, encoding)
        except Exception:
            return _unavailable(token)
        if len(decoded) > max_bytes:
            return _unavailable(token)
        if did_decode:
            raw_items = [item for item in raw_items if item[0].lower() != "content-encoding"]
        content_type = _content_type(raw_items)
        payload = _redact_bytes(decoded, token)
        if _is_html(content_type):
            text, charset = _decode_body(payload, content_type)
            text = _redact(text, token)
            text = rewrite_html(text)
            text = _redact(text, token)
            try:
                payload = text.encode(charset)
            except (LookupError, UnicodeError):
                payload = text.encode("utf-8")
            payload = _redact_bytes(payload, token)
        filtered = _filter_header_items(raw_items, token, upstream)
        return _response(status, payload, filtered)

    async def proxy_ws(websocket: WebSocket, path: str) -> None:
        try:
            await _proxy_ws(websocket, path)
        except Exception:
            await _close_quietly(websocket)

    async def _proxy_ws(websocket: WebSocket, path: str) -> None:
        target = to_ws_url(upstream_url(upstream, path))
        query = websocket.scope.get("query_string", b"")
        if isinstance(query, bytes):
            query_text = query.decode("latin-1")
        else:
            query_text = str(query)
        if query_text:
            target = f"{target}?{query_text}"
        headers = hop_request_headers(dict(websocket.headers), token)
        extra = [(key, value) for key, value in headers.items() if key not in _WS_HANDSHAKE_DROP]
        connect_kwargs: dict[str, object] = {
            "extra_headers": extra,
            "open_timeout": 5,
            "compression": None,
            "max_size": max_bytes if max_bytes > 0 else None,
        }
        if target.startswith("wss://"):
            connect_kwargs["ssl"] = _ssl_context(tls_verify)
        subprotocols = websocket.scope.get("subprotocols") or None
        if subprotocols:
            connect_kwargs["subprotocols"] = list(subprotocols)
        upstream_ws = await websockets.connect(target, **connect_kwargs)
        try:
            await websocket.accept(subprotocol=upstream_ws.subprotocol)
            await _bridge(websocket, upstream_ws, token)
        finally:
            await _close_upstream(upstream_ws)

    async def herdr_ws(websocket: WebSocket) -> None:
        await proxy_ws(websocket, "ws")

    async def herdr_ws_path(websocket: WebSocket, path: str) -> None:
        await proxy_ws(websocket, path)

    app.add_api_route("/herdr", proxy_http, methods=_HTTP_METHODS)
    app.add_api_route("/herdr/", proxy_http, methods=_HTTP_METHODS)
    app.add_api_route("/herdr/{path:path}", proxy_http, methods=_HTTP_METHODS)
    app.add_api_websocket_route("/herdr/ws", herdr_ws)
    app.add_api_websocket_route("/herdr/{path:path}", herdr_ws_path)


async def _close_quietly(websocket: WebSocket) -> None:
    try:
        await websocket.close(code=1011)
    except Exception:
        return


async def _close_upstream(upstream_ws: object) -> None:
    try:
        await upstream_ws.close()  # type: ignore[attr-defined]
    except Exception:
        return


async def _bridge(websocket: WebSocket, upstream_ws: object, token: str) -> None:
    async def client_to_upstream() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("text") is not None:
                await upstream_ws.send(message["text"])  # type: ignore[attr-defined]
            elif message.get("bytes") is not None:
                await upstream_ws.send(message["bytes"])  # type: ignore[attr-defined]

    async def upstream_to_client() -> None:
        async for message in upstream_ws:  # type: ignore[attr-defined]
            if isinstance(message, str):
                await websocket.send_text(_redact(message, token))
            else:
                await websocket.send_bytes(_redact_bytes(message, token))

    tasks = {
        asyncio.create_task(client_to_upstream()),
        asyncio.create_task(upstream_to_client()),
    }
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            try:
                task.exception()
            except asyncio.CancelledError:
                pass
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
