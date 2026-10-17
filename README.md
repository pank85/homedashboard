# homedashboard

## What it is

A single self-hosted container that serves one web page: Docker containers, running AI coding agents, host CPU / RAM / disk, and a one-click **Open Herdr Web** entry point. A stranger can run it with only a published port. Configuration is environment variables. There is no login screen and no host CLI to install by hand.

Containers are read-only: the app issues Docker GET requests only and will not start or stop them. The other writes are this dashboard's own chat session records, which are token-gated (see [Chat sessions](#chat-sessions-round-2)). Missing docker, herdr, `/proc`, or host root degrades that panel to `unavailable: <reason>`. The process still serves the page. Neither HTML nor JSON includes a traceback.

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
| `GET /api/sessions` | Chat session records. Not token-gated. |
| `POST /api/sessions` | Create a herdr workspace plus one agent in it and record the session. Token-gated. |
| `POST /api/sessions/{id}/archive` | Mark this dashboard's session `archived`. Token-gated. No herdr call. |

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

Compose reads `.env` next to `docker-compose.yml` into the container via `env_file` (`path: .env`, `required: false`). That is not Compose interpolation. Interpolation substitutes `${DASHBOARD_PUBLISH_PORT}`, `${DOCKER_SOCKET}`, `${HOST_ROOT_SOURCE}`, and `${HERDR_CONFIG_SOURCE}` into the compose file before the container starts, and `${HERDR_SESSION}`, `${DB_PATH}`, and `${HERDR_SNAPSHOT_RETENTION_DAYS}` into its `environment` block. `${HERDR_HOST_CONFIG_SOURCE}` and `${DASHBOARD_DATA_SOURCE}` appear only on commented volume lines, so they are never required. `env_file` injects variables into the container process. One `.env` can hold both. Absence of the file is not an error.

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

`docker-compose.yml` is the stranger-facing path: one published port, three live mounts, two commented mounts, no `pid: host`. It does not publish `7317`. It does not set `HERDR_CONFIG_DIR` in `environment` (an empty mount must not hide an in-container config). It sets only `HERDR_SESSION`, `DB_PATH`, and `HERDR_SNAPSHOT_RETENTION_DAYS` in `environment`, and deliberately not `CHAT_API_TOKEN` or `CHAT_CWD_ALLOWLIST` (an empty interpolation there would override `env_file`). Image `homedashboard:local`. `restart: unless-stopped`. No `container_name`, no registry host. `env_file` is long syntax `path: .env`, `required: false`. A missing `.env` is not an error. Compose does not activate `pid: host`. The two extra mounts stay comments so a stranger with no herdr and no data directory can still `docker compose up`.

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
    # Safe defaults for the round-2 keys, overridable from the shell or .env.
    # CHAT_API_TOKEN and CHAT_CWD_ALLOWLIST are deliberately absent: an empty
    # interpolation here would override the value from env_file. They ride
    # env_file only.
    environment:
      HERDR_SESSION: ${HERDR_SESSION:-hermes}
      DB_PATH: ${DB_PATH:-/data/dashboard.db}
      HERDR_SNAPSHOT_RETENTION_DAYS: ${HERDR_SNAPSHOT_RETENTION_DAYS:-7}
    # PID namespace: default is the container namespace. The FR2 process scan
    # then sees only this container's processes. Host CPU/RAM from /proc/stat
    # and /proc/meminfo are still host-wide. Opt in only if you accept the
    # privilege (uncomment next line):
    # pid: "host"
    volumes:
      - ${DOCKER_SOCKET:-/var/run/docker.sock}:/var/run/docker.sock:ro
      - ${HOST_ROOT_SOURCE:-/}:/host:ro
      - ${HERDR_CONFIG_SOURCE:-./docker/empty-herdr}:/herdr-config:ro
      # Host herdr config at herdr's default path. This image runs as root, so the
      # default path inside the container is /root/.config/herdr. Leave commented
      # if you have no herdr; the empty /herdr-config mount above still works.
      # - ${HERDR_HOST_CONFIG_SOURCE}:/root/.config/herdr:ro
      # SQLite bind. Leave commented to keep an ephemeral /data (sessions die with the container).
      # - ${DASHBOARD_DATA_SOURCE}:/data
```

The published mapping is host `${DASHBOARD_PUBLISH_PORT:-8080}` to container port `8080`. The process listens on `DASHBOARD_PORT` (default `8080`). Keep those the same.

`docker compose up` fails if the host docker socket path does not exist, because that bind is in the default file. `docker run -p 8080:8080` with no volumes is the nothing-mounted path.

The `environment` block interpolates `${DB_PATH:-/data/dashboard.db}`, so a blank `DB_PATH` in the Compose `.env` falls back to the default instead of disabling persistence. To disable persistence under Compose, pass `DB_PATH=` explicitly with `docker run -e DB_PATH=` or set the `environment` value in an override file.

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
| `CONTAINER_FETCH_WORKERS` | `8` | int. Parallel per-container Docker API fetches; minimum `1`. |
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
| `HERDR_SESSION` | `hermes` | str. Named herdr session the dashboard operates on. Blank becomes `hermes`. A `default` value (any case) is stored as given and refused at use. |
| `CHAT_API_TOKEN` | empty | str. Unset or blank disables the mutating routes (`403`) and the New session control. Never written into the page. Leave empty in files you commit. |
| `CHAT_CWD_ALLOWLIST` | empty | csv. Absolute path prefixes a new session may start in. Empty rejects every create (fail closed). No host path in this file. |
| `DB_PATH` | `/data/dashboard.db` | str. Container path, not a host path. Omitting the key uses the default; setting it blank or whitespace **disables** persistence, the one key where blank does not mean default. The page still loads. |
| `HERDR_SNAPSHOT_RETENTION_DAYS` | `7` | int. Snapshot rows older than this are deleted on the next write. Invalid or `< 1` falls back to `7`; `0` does not mean "keep forever". |
| `HERDR_HOST_CONFIG_SOURCE` | empty | compose-only. App does not read it. Host directory for the commented default-path mount at `/root/.config/herdr`. Empty means do not use. |
| `DASHBOARD_DATA_SOURCE` | empty | compose-only. App does not read it. Host directory for the commented `/data` bind. |

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

## Chat sessions (round 2)

The page can create one herdr workspace per chat session and archive this dashboard's own record of it. Nothing else is writable: containers stay read-only and existing read-only endpoints stay read-only.

| Endpoint | Behavior |
| --- | --- |
| `GET /api/sessions` | Session records. Not token-gated, read-only. |
| `POST /api/sessions` | Validate, run `herdr workspace create`, then `herdr agent start` in the new root pane, and record the session. |
| `POST /api/sessions/{id}/archive` | Set this dashboard's session status to `archived`. No herdr call. |

### Token gate

- `CHAT_API_TOKEN` unset or blank: every mutating request is `403` with reason `CHAT_API_TOKEN unset`, and the New session control is disabled in the page. Nothing is spawned.
- Token set, request missing the token or carrying a wrong one: `401` with reason `invalid token`. Missing and wrong are the same status, so the endpoint does not confirm which tokens exist. `403` never means a bad token.
- Validation failures are `400` with `{"error":"invalid","reason":"..."}`. The token is checked before cwd checks, so an unauthenticated caller cannot probe the filesystem.
- The token is never rendered into the HTML or the JS source. The operator types it once into a password field; the page stores it in `localStorage` under the key `homedashboard.chatApiToken` and sends `Authorization: Bearer <token>`. Any script served from this origin can read that key, so treat the dashboard origin as trusted. There is no cookie and no query-string token.
- `CHAT_CWD_ALLOWLIST` is the only source of permitted working directories. Empty rejects every create (`CHAT_CWD_ALLOWLIST unset`, fail closed). Entries are absolute path prefixes; `..` and symlinks that resolve outside a prefix are rejected. Prefix matching is path-based, so `/proj` does not allow `/proj-evil`.

### Session name and scope

`HERDR_SESSION` names the herdr session the dashboard operates on (default `hermes`). The herdr session `default` is always refused with the reason `refusing session default` before any process is spawned, so a misconfiguration cannot touch an operator's default session. Never operate on herdr session `default`: set `HERDR_SESSION` to a dedicated named session.

One workspace per chat session. The dashboard calls `workspace create` (which already returns the root tab and pane) and then `agent start --pane <root pane>`. It never calls `tab create`, `workspace close`, `session stop`, or `session delete`.

### Attach command

```bash
herdr session attach hermes
```

Replace `hermes` with your `HERDR_SESSION`. `herdr --session <name> attach` is **not** a working command on herdr 0.9.5: it only prints top-level help. The page states that mismatch next to the copy control.

`herdr session attach <name>` attaches the whole herdr session, not one workspace. The page shows the workspace id beside the Herdr Web link so a human can find the right workspace inside Herdr Web. Click-through is always `/herdr/`; there is no per-workspace deep link.

### Archive and failure

Archive only updates this dashboard. It does not stop, close, or delete anything in herdr: not the session, not the workspace, not the tab, not the agent.

If `workspace create` or `agent start` fails, the dashboard records `failed` for its own row and returns `502`. It does not close the herdr workspace it just created; the page says so, and closing is out of scope for this product. If the database is unavailable, a create returns `503` without spawning anything, so no untracked workspace is made.

Session rows live in SQLite at `DB_PATH` (container path, default `/data/dashboard.db`). Without a `/data` bind the database is ephemeral and records die with the container. Setting `DB_PATH` to an empty string disables persistence; the sessions panel then reports itself unavailable and the other panels still render.

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

Running as root is a privilege tradeoff, not a hidden default. v1 does not drop privileges. The socket mount is read-only. The app issues Docker GET requests only; the sole writes are its own chat session records.

Containers stay read-only: the app will not start, stop, or delete them. Also out of scope: restart, delete, log streaming, authenticating the whole dashboard (only the mutating session endpoints are token-gated), alerting, multi-host, historical graphs, Kubernetes, and Windows-native deployment.

One published port: 8080. The internal herdr UI on 127.0.0.1:7317 is not published. `REFRESH_SECONDS=0` disables polling. Thresholds default 75/90.

## What to mount

| want | mount | env | notes |
| --- | --- | --- | --- |
| containers | `/var/run/docker.sock` read-only onto `/var/run/docker.sock` | `DOCKER_SOCKET` | Read-only socket. Docker GET only. Unset or missing: the containers panel is unavailable and the page still loads. |
| host disk | `/` to `/host`, read-only | `HOST_ROOT`, `DISK_PATHS` | Host root inside the container is `HOST_ROOT` (default `/host`). Disks are `DISK_PATHS` (default `/host,/host/home`) when `PROC_ROOT`/`mounts` lists that mountpoint; otherwise the panel is container view. |
| host herdr | host config directory, read-only, onto `/herdr-config` | `HERDR_CONFIG_SOURCE` and `HERDR_CONFIG_DIR=/herdr-config` | Compose mounts `HERDR_CONFIG_SOURCE` (default `./docker/empty-herdr`) and does not set `HERDR_CONFIG_DIR`. Set `HERDR_CONFIG_DIR=/herdr-config` only when the mount holds a real config, so the bundled CLI talks to the host server socket. A user-owned config directory is often `~/.config/herdr`. That path is an example in this note only, not a product default, and not a command to copy unchanged. |
| host process scan | optional `pid: host` | no extra env | Privileged. Uncomment `# pid: "host"` in compose if you accept that. Not the default. Without it the agent process scan sees only the container's processes. |
| host herdr, default path | host config directory, read-only, onto `/root/.config/herdr` (commented in compose) | `HERDR_HOST_CONFIG_SOURCE` | The verified approach (2026-10-17) for reaching the host CLI socket: mount the host config at herdr's default path inside the container. The image runs as root, so that path is `/root/.config/herdr`. A read-only mount is enough for listing; creating a session also needs a running host herdr server on that socket. Leave the compose line commented if you have no herdr. |
| session persistence | host directory onto `/data` (commented in compose) | `DASHBOARD_DATA_SOURCE`, `DB_PATH` | Session records live in `DB_PATH` (default `/data/dashboard.db`). Compose leaves the `/data` bind commented, so without it `/data` is ephemeral and records die with the container. Setting `DB_PATH` empty disables persistence instead. |

## Homeserver compose fragment (not applied by this repo)

The live file `~/homeserver/docker-compose/homedashboard` is outside this checkout. Workers and CI in this repository do not edit it and this repository does not apply these settings. An operator copies the fragment below into that file by hand.

The absolute paths are EXAMPLE ONLY, for one host. They are not product defaults, they are not in this repository's uncommented compose values, and they are not Python defaults. Do not uncomment host-specific mounts in the committed `docker-compose.yml`; a stranger without those directories would fail to start.

```yaml
# EXAMPLE ONLY. Not applied by this repository.
volumes:
  - /home/pank/.config/herdr:/root/.config/herdr:ro
  - /home/pank/docker-data/homedashboard:/data
environment:
  HERDR_SESSION: hermes
  DB_PATH: /data/dashboard.db
  HERDR_SNAPSHOT_RETENTION_DAYS: "7"
  CHAT_CWD_ALLOWLIST: /home/pank/projects
  CHAT_API_TOKEN: ${CHAT_API_TOKEN}
```

`CHAT_API_TOKEN` comes from the homeserver `.env`, never committed. Quote `HERDR_SNAPSHOT_RETENTION_DAYS` in YAML so it is not read as a number by tooling that expects a string.

## Development

Python 3.12.

```bash
pip install -r requirements-dev.txt && PYTHONPATH=. pytest
```

Tests mock the docker API, `/proc`, and herdr output. They do not need a running daemon or a published port.
