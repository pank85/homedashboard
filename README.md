# homedashboard

## What it is

A single self-hosted container that serves one web page: Docker containers, running AI coding agents, host CPU / RAM / disk, and a one-click **Open Herdr Web** entry point. A stranger can run it with only a published port. Configuration is environment variables. There is no login screen and no host CLI to install by hand.

v1 is read-only and will not start or stop containers. The app issues Docker GET requests only. Missing docker, herdr, `/proc`, or host root degrades that panel to `unavailable: <reason>`. The process still serves the page. Neither HTML nor JSON includes a traceback.

One published port: **8080**. The internal herdr UI on `127.0.0.1:7317` is not published. `REFRESH_SECONDS=0` disables polling (default `5`). Warn/crit thresholds default to **75/90**.

The page is server-rendered (FastAPI, Uvicorn, Jinja2) with a small amount of vanilla JS and CSS. No npm, no CDN, dark theme, readable on a phone. The HTML page and `GET /api/metrics` use the same collectors.

| Endpoint | Role |
| --- | --- |
| `GET /` | The dashboard page |
| `GET /api/health` | Liveness. Always 200 when the process is up. Does not call collectors. |
| `GET /api/metrics` | Full dashboard payload |
| `GET /api/containers` | Containers panel |
| `GET /api/agents` | Agents panel |
| `GET /api/host` | Host CPU, RAM, and disk |

Agents come from herdr and, as a fallback, a `/proc` process scan. Both sources may be combined. Rows are not deduped; `source` distinguishes them. Empty from both is `no agents detected`, not an error.

## Quick start

Nothing mounted. The page loads; panels that need a socket or a host mount say they are unavailable.

```bash
docker build -t homedashboard:local .
docker run --rm -p 8080:8080 homedashboard:local
```

Optional mounts. These copy-paste blocks use `/var/run/docker.sock` and `/` only. Do not add `--pid=host`. Do not publish `7317`.

```bash
docker run --rm -p 8080:8080 \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /:/host:ro \
  homedashboard:local
```

The image runs as root. `EXPOSE 8080`. `ENTRYPOINT ["/entrypoint.sh"]`. There is no `USER` line: the docker socket group id differs by host, and hardcoding a GID would not be portable. v1 does not drop privileges. The socket mount is read-only.

Herdr, Bun, and the `devswha.herdr-web-ui` plugin are installed at image build, best-effort (`https://herdr.dev/install.sh`, then `herdr plugin install devswha/herdr-web-ui --yes` when `herdr` is on `PATH`). A failed install does not fail the image build. The entrypoint does not retry the installer and does not refuse to start when the binary is absent.

## Configuring it

Configuration is environment variables. No host CLI install. The published port stays `8080`.

`docker run --env-file .env` passes a file into the container. The file is optional for a bare run: omit `--env-file` when you have nothing to set (see Quick start). A missing file is not required. Committed files must not contain a real token. Leave `HERDR_WEB_TOKEN` empty in anything you commit.

```bash
docker run --rm --env-file .env -p 8080:8080 homedashboard:local
```

Compose reads `.env` next to `docker-compose.yml` into the container via `env_file` (`path: .env`, `required: false`). That is not Compose interpolation. Interpolation substitutes `${DASHBOARD_PUBLISH_PORT}`, `${DOCKER_SOCKET}`, `${HOST_ROOT_SOURCE}`, and `${HERDR_CONFIG_SOURCE}` into the compose file before the container starts. `env_file` injects variables into the container process. One `.env` can hold both. Absence of the file is not an error.

Attach to an existing host herdr Web UI with placeholders only. This does not start a second herdr server. The button opens that existing UI. Do not publish `7317` from this container.

```
HERDR_MODE=external
HERDR_WEB_URL=http://<host>:7317
HERDR_WEB_TOKEN=<token-from-that-existing-ui>
```

If the token is set, the page button is still `/herdr/` and the server proxy adds Authorization.

Drive a host herdr session from the container by mounting the host herdr config read-only at `/herdr-config` and setting `HERDR_CONFIG_DIR=/herdr-config` only when that mount holds a real config. Compose does not set `HERDR_CONFIG_DIR` by itself, because an empty mount must not hide an in-container config. `~/.config/herdr` is an example path only, not a product default, and not a command to copy unchanged.

Embedded mode sees only the container's own herdr sessions, not the host user's sessions. Host agents need external mode, or `HERDR_CONFIG_DIR` pointed at the host herdr config.

## Compose

```bash
docker compose up --build
```

`docker-compose.yml` is the stranger-facing path: one published port, three mounts, no `pid: host`. It does not publish `7317`. It does not set `HERDR_CONFIG_DIR` in `environment` (an empty mount must not hide an in-container config). Image `homedashboard:local`. `restart: unless-stopped`. No `container_name`, no registry host. `env_file` is long syntax `path: .env`, `required: false`. A missing `.env` is not an error. Compose does not activate `pid: host`.

```yaml
services:
  dashboard:
    build: .
    image: homedashboard:local
    restart: unless-stopped
    ports:
      - "${DASHBOARD_PUBLISH_PORT:-8080}:8080"
    env_file:
      - path: .env
        required: false
    # PID namespace: default is the container namespace. The FR2 process scan
    # then sees only this container's processes. Host CPU/RAM from /proc/stat
    # and /proc/meminfo are still host-wide. Opt in only if you accept the
    # privilege (uncomment next line):
    # pid: "host"
    volumes:
      - ${DOCKER_SOCKET:-/var/run/docker.sock}:/var/run/docker.sock:ro
      - ${HOST_ROOT_SOURCE:-/}:/host:ro
      - ${HERDR_CONFIG_SOURCE:-./docker/empty-herdr}:/herdr-config:ro
```

The published mapping is host `${DASHBOARD_PUBLISH_PORT:-8080}` to container port `8080`. The process listens on `DASHBOARD_PORT` (default `8080`). Keep those the same.

`docker compose up` fails if the host docker socket path does not exist, because that bind is in the default file. `docker run -p 8080:8080` with no volumes is the nothing-mounted path.

## Environment variables

The app reads these through `load_settings`. Defaults are generic. No hostnames, user names, or home directories. Tokens stay empty in the repo; set `HERDR_WEB_TOKEN` at runtime.

| Env | Default | Type / notes |
| --- | --- | --- |
| `DASHBOARD_HOST` | `0.0.0.0` | str. Bind address inside the container. |
| `DASHBOARD_PORT` | `8080` | int. Listen port. The one published port. |
| `REFRESH_SECONDS` | `5` | int. `0` disables polling. |
| `DOCKER_SOCKET` | `/var/run/docker.sock` | str. Also the host-side socket path in compose. |
| `DOCKER_API_VERSION` | `v1.41` | str. Override if the engine differs. |
| `DOCKER_TIMEOUT_SECONDS` | `3` | float. |
| `HERDR_BIN` | `herdr` | str. |
| `HERDR_TIMEOUT_SECONDS` | `3` | float. |
| `HERDR_MODE` | `embedded` | `embedded` \| `external` \| `off`. Settings: any other value becomes `embedded` (href default only). Entrypoint: unknown does not start herdr. |
| `HERDR_CONFIG_DIR` | empty | str. Empty means unset. App and entrypoint. |
| `HERDR_WEB_URL` | empty | str. Empty means `/herdr/` when mode is embedded. A set token forces the button to `/herdr/` regardless of this value. |
| `HERDR_WEB_TOKEN` | empty | str. Never written into the page. Leave empty in files you commit. |
| `HERDR_WEB_EMBED` | `false` | bool. Iframe only when true and the href is non-empty. |
| `HERDR_UPSTREAM` | `http://127.0.0.1:7317` | str. Fixed at startup. Must track `HERDR_WEB_BIND` and `HERDR_WEB_PORT`. The app does not synthesize this from bind/port. |
| `HERDR_WEB_BIND` | `127.0.0.1` | str. Entrypoint; still parsed. Not published. |
| `HERDR_WEB_PORT` | `7317` | int. Entrypoint; still parsed. Not published. |
| `HERDR_UPSTREAM_TLS_VERIFY` | `false` | bool. Verify a self-signed upstream only when `true`. The browser never sees that cert on the proxy path. |
| `HERDR_PROXY_MAX_BYTES` | `33554432` | int. Larger upstream bodies become HTTP 502. |
| `AGENT_PROCESS_PATTERNS` | `claude,opencode,pi,muse,codex,aider,gemini,hermes` | csv. Fallback process names. |
| `PROC_ROOT` | `/proc` | str. Tests may point this at a fake tree. |
| `HOST_ROOT` | `/host` | str. Mount point of the host root inside the container. |
| `DISK_PATHS` | `/host,/host/home` | csv. Used when `HOST_ROOT` is mounted. |
| `CPU_SAMPLE_SECONDS` | `0.2` | float. Gap between `/proc/stat` samples. `0` is legal. |
| `CPU_WARN` | `75` | float. |
| `CPU_CRIT` | `90` | float. |
| `MEM_WARN` | `75` | float. |
| `MEM_CRIT` | `90` | float. |
| `DISK_WARN` | `75` | float. |
| `DISK_CRIT` | `90` | float. |
| `DASHBOARD_PUBLISH_PORT` | `8080` | compose-only. App does not read it. Host side of the published port. |
| `HOST_ROOT_SOURCE` | `/` | compose-only. App does not read it. Host path mounted at `/host`. |
| `HERDR_CONFIG_SOURCE` | `./docker/empty-herdr` | compose-only. App does not read it. Host path mounted at `/herdr-config`. |

Bool: empty or missing uses the default. Otherwise true only for `1`, `true`, `yes`, `on` (case-insensitive, stripped). The string `false` is false.

Int and float: invalid or missing uses the default. The parser does not raise.

CSV: missing or blank uses the default tuple. Otherwise split on comma, strip, and drop empties.

Thresholds: `percent >= crit` is `crit`; else `percent >= warn` is `warn`; else `ok`. Equal to the boundary is that level. Applies to host CPU, RAM, and each disk. Not to container rows.

If `PROC_ROOT`/`mounts` has a mountpoint equal to `HOST_ROOT`, the panel view is `host` and disks are `DISK_PATHS`. Otherwise the view is `container view` and disks are the container's own mountpoints. A missing path inside an otherwise mounted `HOST_ROOT` is that disk unavailable, not a panel crash.

## Herdr modes

`HERDR_MODE=embedded|external|off` (default `embedded`). Owned by `entrypoint.sh`, not by Python. Background herdr logs go to `/tmp/herdr-server.log` and `/tmp/herdr-web.log`. The script never exits non-zero because herdr failed. The last step is always `exec uvicorn`.

`HERDR_CONFIG_DIR` empty means unset. If it is set and `$HERDR_CONFIG_DIR/config.toml` exists, the entrypoint exports `HERDR_CONFIG_PATH` to that file (herdr's own override). The app does not read `HERDR_CONFIG_PATH`.

### embedded

Default. If `herdr` is missing, the entrypoint logs and continues. If `herdr status server` already succeeds — typical when `HERDR_CONFIG_DIR` mounts a live host socket — it does not start a second server. Otherwise it backgrounds `herdr server`, waits up to about 10 seconds, then backgrounds `herdr plugin action invoke --plugin devswha.herdr-web-ui start` with `HOST` and `PORT` set to `HERDR_WEB_BIND` and `HERDR_WEB_PORT` (default `127.0.0.1:7317`). Any failure is logged. Uvicorn still starts.

That internal UI is not published and is not mapped in compose. With an empty `HERDR_WEB_URL`, the button is the relative path `/herdr/`, so a stranger does not publish `7317`.

A herdr server running inside the container manages sessions inside the container and cannot see the herdr sessions of the host.

To see host agents, use external mode, or mount the host herdr config directory and set HERDR_CONFIG_DIR so the bundled CLI talks to the host server.

### external

Does not start herdr. Point `HERDR_WEB_URL` at an existing herdr-web-ui, for example `http://<host>:7317`. This is the mode that shows a real user's own agents. The bundled binary is not required.

### off

Does not start herdr. The Open Herdr Web control still follows `HERDR_WEB_URL`. If that URL and the token are both empty, the control is disabled.

### Unknown mode

Settings treats an unknown value as `embedded` for the href default only. The entrypoint treats unknown as do not start, so a typo cannot spawn a server the operator did not ask for.

### Token proxy

`public_herdr_href` is the only URL the template may emit:

1. If `HERDR_WEB_TOKEN` is non-empty, return `/herdr/` (ignore `HERDR_WEB_URL`; do not append the token; do not emit the upstream URL).
2. Else if `HERDR_WEB_URL` is non-empty, return it unchanged.
3. Else if `HERDR_MODE=embedded` (unknown mode counts as embedded here), return `/herdr/`.
4. Else return `""`. The template renders a disabled control, text still "Open Herdr Web", plus "Herdr Web URL not configured".

`herdr_embed_src` is that href when `HERDR_WEB_EMBED` is true, otherwise `""`. The iframe is omitted when the src is empty. There is no `sandbox` attribute.

When HERDR_WEB_TOKEN is set, the dashboard never puts it in HTML or client-side JS. The browser opens /herdr/ and the server-side proxy adds Authorization: Bearer.

The token is not in the page source. Mechanism:

- The browser-facing path is always `/herdr/` and `/herdr/{path}`.
- Upstream is `HERDR_UPSTREAM` (default `http://127.0.0.1:7317`), fixed at startup. The request path cannot change the upstream host. Operators who change the internal port change `HERDR_WEB_BIND`, `HERDR_WEB_PORT`, and `HERDR_UPSTREAM` together.
- When the token is non-empty, the proxy adds `Authorization: Bearer <token>` on every upstream HTTP request and WebSocket handshake. herdr-web-ui accepts that header or a `herdr_web_token` cookie. Bearer only. The proxy does not set the cookie in the browser.
- It drops inbound `Authorization` and `Cookie`. The browser must not supply or observe the token.
- It drops upstream `Set-Cookie` whose name is `herdr_web_token` or whose value contains the token.
- It never writes the token into HTML, JS, logs, or error bodies.
- It does not send `X-Forwarded-For`, `X-Forwarded-Host`, or `Forwarded`, and strips those if the client sent them. A tokenless loopback upstream still counts as local; a tokened upstream is satisfied by Bearer.
- HTML responses are rewritten so root-absolute `src`, `href`, and `action` gain a `/herdr` prefix. A shim prefixes same-origin root paths in `fetch`, `XMLHttpRequest.open`, `WebSocket`, and `EventSource`.
- Upstream `X-Frame-Options` and `Content-Security-Policy` are stripped on proxied responses so the dashboard iframe and the shim can run. That strip is a CSP relaxation of the proxied document.
- Service workers (`/sw.js`) are not supported through the proxy.
- Generated proxy errors are plain text `herdr upstream unavailable` with HTTP 502, never a traceback, never the token. Bodies over `HERDR_PROXY_MAX_BYTES` become that same 502.

Self-signed upstream certs are verified only if `HERDR_UPSTREAM_TLS_VERIFY=true` (default false), because the browser never sees the upstream cert on the proxy path. A direct `HERDR_WEB_URL` of `https://...` still requires the user to accept that origin in the browser.

## Limitations

These limits are part of the product. They are not optional footnotes.

### Herdr in the container

A herdr server running inside the container manages sessions inside the container and cannot see the herdr sessions of the host.

To see host agents, use external mode, or mount the host herdr config directory and set HERDR_CONFIG_DIR so the bundled CLI talks to the host server.

### procfs/cgroup caveat

CPU and RAM from /proc/stat and /proc/meminfo are host values even inside a container because those procfs counters are not namespaced.

The dashboard reads those procfs files, not the container cgroup CPU or memory limits. Load average from the same view is a host value too. A cgroup quota does not shrink the numbers on the host panel. Do not misread them as "this container's" CPU or RAM.

### PID namespace

The process list under /proc is PID-namespaced. The default compose file does not set pid: host, so the agent process scan sees only the container's processes.

Host agents are invisible to that fallback. That is accepted. Show them with `HERDR_MODE=external`, or by mounting the host herdr config (`HERDR_CONFIG_DIR`) so the bundled CLI talks to the host server socket (the socket lives under that directory). `pid: host` is an optional, privileged opt-in, commented in compose, not the default. The default `docker run` does not pass `--pid=host`.

### X-Frame-Options and direct embeds

herdr-web-ui sends frame-ancestors 'none'. A direct embed of an external origin can be blank. The proxied /herdr/ path strips X-Frame-Options and Content-Security-Policy.

The iframe does not always work. If the frame is blank, the upstream refused to be embedded (X-Frame-Options or frame-ancestors). Accept the self-signed or self-hosted origin in a new tab, or use the proxied `/herdr/` path. Stripping `Content-Security-Policy` is the CSP relaxation that lets the same-origin iframe and the path shim run. It applies to proxied responses only.

A herdr-web-ui build that opens root-absolute URLs some other way than `src` / `href` / `action` / `fetch` / XHR / WebSocket / EventSource can still break under `/herdr/`. Service workers are unsupported.

### Install failure and root

The image still starts if the herdr install failed at build time. embedded mode then logs and serves the dashboard without herdr. external and off do not need the bundled binary.

The container runs as root so a read-only docker socket is usable without a host-specific group id.

Running as root is a privilege tradeoff, not a hidden default. v1 does not drop privileges. The socket mount is read-only. The app only issues Docker GET requests.

v1 is read-only and will not start or stop containers. Also out of scope: restart, delete, log streaming, authentication, alerting, multi-host, historical graphs, Kubernetes, and Windows-native deployment.

One published port: 8080. The internal herdr UI on 127.0.0.1:7317 is not published. `REFRESH_SECONDS=0` disables polling. Thresholds default 75/90.

## What to mount

| want | mount | env | notes |
| --- | --- | --- | --- |
| containers | `/var/run/docker.sock` read-only onto `/var/run/docker.sock` | `DOCKER_SOCKET` | Read-only socket. Docker GET only. Unset or missing: the containers panel is unavailable and the page still loads. |
| host disk | `/` to `/host`, read-only | `HOST_ROOT`, `DISK_PATHS` | Host root inside the container is `HOST_ROOT` (default `/host`). Disks are `DISK_PATHS` (default `/host,/host/home`) when `PROC_ROOT`/`mounts` lists that mountpoint; otherwise the panel is container view. |
| host herdr | host config directory, read-only, onto `/herdr-config` | `HERDR_CONFIG_SOURCE` and `HERDR_CONFIG_DIR=/herdr-config` | Compose mounts `HERDR_CONFIG_SOURCE` (default `./docker/empty-herdr`) and does not set `HERDR_CONFIG_DIR`. Set `HERDR_CONFIG_DIR=/herdr-config` only when the mount holds a real config, so the bundled CLI talks to the host server socket. A user-owned config directory is often `~/.config/herdr`. That path is an example in this note only, not a product default, and not a command to copy unchanged. |
| host process scan | optional `pid: host` | no extra env | Privileged. Uncomment `# pid: "host"` in compose if you accept that. Not the default. Without it the agent process scan sees only the container's processes. |

## Development

Python 3.12.

```bash
pip install -r requirements-dev.txt && PYTHONPATH=. pytest
```

Tests mock the docker API, `/proc`, and herdr output. They do not need a running daemon or a published port.
