# homedashboard — implementation spec (authoritative)

Repo: `pank85/homedashboard` (GitHub, public, empty) + GitLab mirror `pank85/homedashboard` (private, id 27,
container registry enabled) — GitLab CI builds the image.
This file is the requirements source for the ergo Architect. Code is the source of truth for patterns.

## Product in one line

A single self-hosted container that serves one web page showing: Docker **containers**, running **AI coding
agents**, host **CPU / RAM / disk**, and a one-click **Herdr Web** entry point — generic enough that a stranger
can `docker run` it on their own PC.

## Hard constraints

- C1 **Generic.** No hardcoded hostnames, IPs, usernames, ports or absolute host paths outside env defaults.
  Everything configurable via environment variables, all documented in `.env.example` + README table.
- C2 **Degrade, never crash.** Every data source (docker socket, herdr, /proc, host root mount) is optional.
  A missing source produces an explicit "unavailable: <reason>" state in its panel, never a 500 and never a
  traceback in the UI. The app must start and serve the page with *nothing* mounted.
- C3 **Read-only.** v1 must not start/stop/restart/remove containers or mutate anything. Read-only socket mount.
- C4 **No secrets in the repo or image.** Tokens/URLs come from env at runtime.
- C5 Docker-only deployment, web-UI-only administration (this user's environment): configuration is
  environment variables, never a host CLI the deployer must install by hand.
- C6 Single image, single container, one published HTTP port (default 8080).

## Functional requirements

FR1 **Containers panel** — from the Docker Engine API over the unix socket (`DOCKER_SOCKET`, default
`/var/run/docker.sock`, mounted read-only):
name, image, state (`running`/`exited`/`restarting`/`created`), health status when a healthcheck exists,
uptime (from `State.StartedAt`), restart count (`RestartCount`), and for running containers CPU % and
memory used/limit (from `/containers/{id}/stats?stream=false`, computed from the `cpu_stats`/
`precpu_stats` deltas and `memory_stats.usage`). Sort: unhealthy/restarting first, then running by name.
Source unavailable → panel says docker socket not reachable + the configured path.

FR2 **AI agents panel** — list running AI coding agents, with the source that produced the list shown:
- Primary: **herdr**. Read workspaces/tabs/agents (label, agent status, cwd, session) via the herdr CLI
  (`HERDR_BIN`, default `herdr`) or its socket API. Show per agent: workspace label, tab/agent label,
  status (`working` / `idle` / `blocked` / `done` / unknown), pane cwd.
- Fallback (when herdr is absent or returns nothing): process scan of `/proc` for known agent binaries
  (`AGENT_PROCESS_PATTERNS`, default a comma list: `claude,opencode,pi,muse,codex,aider,gemini`, plus
  `hermes`), reporting pid, matched name, RSS, CPU %, and elapsed time; children rolled into the parent.
- Both sources may be combined; the panel must state which it used and when each was last refreshed.
- When neither yields anything: "no agents detected" — not an error.

FR3 **Host resources panel** — CPU, RAM, disk.
- CPU: total utilisation % (from two samples of `/proc/stat`), per-core % optional, load average 1/5/15,
  core count. These are **host** values even inside a container (procfs is not namespaced) — state this in
  the README so users do not misread them.
- RAM: used/total/percent from `/proc/meminfo` (MemTotal minus MemAvailable).
- Disk: per mount point from `statvfs`, over `HOST_ROOT` (default `/host`, documented as the mount point of
  the host root, mount it read-only to see the host's real filesystems) with `DISK_PATHS` (default
  `/host,/host/home`) — when `HOST_ROOT` is not mounted, fall back to the container's own mounts and label
  the panel as "container view".
- Warn/crit thresholds via `CPU_WARN`/`CPU_CRIT`, `MEM_WARN`/`MEM_CRIT`, `DISK_WARN`/`DISK_CRIT`
  (defaults 75/90) drive a colour state (ok/warn/crit) per metric.

FR4 **Herdr Web entry point** — a prominent button, "Open Herdr Web", that opens `HERDR_WEB_URL` in a new
browser tab, plus an optional inline embed (`HERDR_WEB_EMBED=true`, default false) rendering the same URL in
an iframe below the panels. When `HERDR_WEB_TOKEN` is set, the dashboard must NOT leak it into the HTML or
into client-side JS; a server-side reverse-proxy path under `/herdr/*` that injects the credential is the
acceptable mechanism (document whichever mechanism is chosen; do not put the token in the page source).
Instruct the user to accept the self-signed/self-hosted origin in the embed case (the iframe must not be
broken by `X-Frame-Options` — document the limitation rather than pretending it works).

FR5 **Embedded vs external Herdr** — `HERDR_MODE=embedded|external|off` (default `embedded`):
- `embedded` (default, what makes the image self-contained for strangers): the container itself runs a
  herdr server and the `devswha.herdr-web-ui` plugin, so `HERDR_WEB_URL` defaults to the container's own
  instance and the page works out of the box with zero host setup.
- `external`: the user points `HERDR_WEB_URL` at an existing herdr-web-ui instance (e.g. their host's
  `http://<host>:7317`). The bundled herdr is not started. Document that this is the mode that shows a
  real user's own agents.
- `off`: no herdr process management; FR4 still renders whatever `HERDR_WEB_URL` says.
- **Documented limitation (must appear in the README, not be hidden):** a herdr server running inside the
  container manages sessions *inside the container* and therefore cannot see the herdr sessions of the
  host. To see host agents, either use `external` mode, or mount the host's herdr directory
  (`~/.config/herdr`) into the container (`HERDR_CONFIG_DIR`) so the bundled CLI talks to the host server.

FR6 **Refresh** — the page refreshes its data periodically without a full reload (poll a JSON endpoint,
default `REFRESH_SECONDS=5`, `0` disables) and shows "last updated".

FR7 **Machine-readable endpoints** — `GET /api/health` (liveness, always 200 when the process is up),
`GET /api/metrics` (the full dashboard payload as JSON; the HTML page must be rendered from the same
collector so the two never disagree), `GET /api/containers`, `GET /api/agents`, `GET /api/host`.

FR8 **UI** — one page, no build step, no npm, no CDN dependency at runtime (offline-capable): server-side
templates + a small amount of vanilla JS/CSS. Dark theme by default, readable on a phone (the user opens
this from a phone browser).

## Deliverables

1. Application source (Python; FastAPI + Uvicorn + Jinja2 templates is the expected shape, but the
   Architect may justify a smaller stdlib-only alternative — no heavyweight deps).
2. `Dockerfile` — single image containing the app **and** herdr + bun + the `devswha.herdr-web-ui` plugin
   (herdr install: `https://herdr.dev/install.sh`; bun ≥ 1.4; the plugin is installed with
   `herdr plugin install devswha/herdr-web-ui --yes`, which clones + builds it). Multi-stage or a slim
   final stage; pin what can be pinned. The image must still run when herdr install failed at build time
   (FR5 `off`/`external` must work in that case) — no build-time hard dependency in the entrypoint.
3. `docker-compose.yml` — the documented path for a stranger: dashboard + the three optional mounts
   (docker socket read-only, host root read-only, herdr config dir) with the minimum viable default.
4. `.env.example` — every variable FR1–FR8 uses, with defaults and one-line comments.
5. `README.md` — quick start (`docker run` and compose), the full env table, the two Herdr modes, the
   procfs/cgroup caveat, the herdr-in-container limitation, and a "what to mount for what" table.
6. `.gitlab-ci.yml` — build the image and push to the project's GitLab container registry
   (`$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA` + `:latest` on the default branch). Must work on the existing
   GitLab CE + `gitlab-runner` container on this host. Do not require a paid feature.
7. `LICENSE` (MIT) and `.gitignore`.
8. Tests (`pytest`) covering the collectors with mocked inputs: docker API responses (including the
   socket-missing and malformed-JSON paths), `/proc` samples for the CPU delta maths, `statvfs` results,
   the herdr-output parser, threshold classification at the boundary values, and one test asserting the
   page renders with **every** source unavailable (FR2/C2).

## Out of scope for v1 (state in the plan's "will not change" list)

Container start/stop/restart/delete or log streaming; authentication/login; alerting or notifications;
multi-host; historical data, graphs or retention; Kubernetes; Windows-native deployment.

## Definition of done

- `docker build` succeeds and `docker run -p 8080:8080` serves the dashboard with only the port mapped.
- The same image with the docker socket and `/host` mounted shows real containers and real host disk.
- `pytest` green.
- GitLab CI pipeline green and the image visible in the project's registry.
- Committed and pushed to both GitHub (`origin`) and GitLab (`gitlab`).
