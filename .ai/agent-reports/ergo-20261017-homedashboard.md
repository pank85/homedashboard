# homedashboard — ergo run report (2026-10-17)

Pipeline: **Pi `/ergo`** in a Herdr workspace (`--session hermes`, workspace `w9`), Hermes as outer
orchestrator. RUN_DIR `.orchestration/ergo-20261017T112603Z` (deleted at land).

## Routes

| Role | Model |
|---|---|
| Scout | `opencode-go/deepseek-v4.1-flash` (thinking low) |
| Architect | `xai/grok-4.7` (high) |
| Workers T01, T02, T07, T11, T12, T14 | `opencode-go/deepseek-v4.1-flash` |
| Workers T03–T06, T08, T09, T10, T13 | `xai/grok-4.7` (high) |
| Reviewer (all passes) | `xai/grok-4.7` (high) |

Both routes smoke-tested (`PI-OK`) before the run.

## Shape

14 disjoint tasks, one plan approval gate, one full review pass, **three** scoped fix-verification
cycles. All three cycles ended `APPROVE` with zero remaining findings. No commit was made by any
agent; the orchestrator landed one commit.

## Findings caught and fixed

1. **P1 (reviewer, closed cycle 1)** — `app/collectors/agents.py::_cpu_sample` counted `iowait`
   twice in the aggregate CPU total (`idle_with_io = idle + iowait` then `+ iowait` again), while
   `app/collectors/host.py` (and plan line 370) define the total as the eight `/proc/stat` fields
   summed once. `tests/test_agents.py` had locked the wrong expected value. Fixed; the test now
   asserts total delta 50 → `cpu_percent == 40.0`.
2. **Orchestrator finding (closed cycle 2)** — the documented deployment paths had no way to pass
   runtime configuration into the container: `docker-compose.yml` had no `environment`/`env_file`
   key and the README never showed `docker run --env-file`, so `HERDR_MODE=external`,
   `HERDR_WEB_URL` and `HERDR_WEB_TOKEN` were unreachable for a deployer. Added an optional
   `env_file` (long syntax, `required: false`) plus a `## Configuring it` README section.
   Deliberate deviation from plan line 891, recorded as such.
3. **Image defects found by actually building and running the image (closed cycle 3)** — the static
   review could not see these:
   - `herdr plugin install devswha/herdr-web-ui --yes` **silently failed at image build**: the
     plugin's `scripts/preflight.sh` requires Node ≥ 18, and the image installed bun only. Result:
     `herdr plugin list` → "No plugins installed", so the embedded Herdr Web could never start.
     Fixed by installing `nodejs` in the same apt layer.
   - `herdr status server` **exits 0 even when it prints `status: not running`**. The entrypoint
     treated that exit code as readiness, so the container logged "herdr server already running",
     never started a server, and skipped the web UI. Fixed by parsing the output.
   - `herdr plugin action invoke --plugin devswha.herdr-web-ui start` is rejected by herdr 0.9.5
     (`unknown option: devswha.herdr-web-ui`). Correct form verified against the installed build:
     `herdr plugin action invoke devswha.herdr-web-ui.start`.
   - `HERDR_WEB_BIND`/`HERDR_WEB_PORT` are now written into the plugin's own `env` file
     (`herdr plugin config-dir devswha.herdr-web-ui`), because the plugin reads its settings there,
     not from the ambient environment.

## Independent verification by the orchestrator

- `pytest` in an isolated Python 3.12.3 venv with the pinned requirements:
  **94 passed, 0 failed** (the host's `PYTHONPATH` points at a Python 3.14 env — it must be cleared
  or the suite runs against the wrong dependencies).
- `docker build -t homedashboard:local .` — succeeds.
- `docker run -p 18080:8080` **with nothing mounted**: `/api/health` 200; `/api/metrics` returns
  `containers` unavailable with `docker socket not reachable: /var/run/docker.sock`, `agents` and
  `host` available. Degradation contract (spec C2) holds.
- With the socket and host root mounted: `containers` listed **39 containers** with state, health
  status, CPU % and memory; `host` reported `view: host`, memory 82.6 % `warn` (matches the host's
  real `MemAvailable`), `loadavg [2.06, 2.03, 2.58]` matching `/proc/loadavg`.
- Embedded Herdr Web in the rebuilt image: `herdr server` → `status: running`; plugin
  `action invoke devswha.herdr-web-ui.status` → `running`.
- FR4 through the dashboard: `GET /herdr/` → **200** (4855 bytes, proxy shim injected),
  `GET /herdr/api/health` → **200**, button `href="/herdr/"`, and **no `Bearer`/token string in the
  served HTML**.

## Known limitations (documented in the README, not hidden)

- A herdr server inside the container manages sessions **inside the container**. To interact with
  the host's own agents use `HERDR_MODE=external` pointing at the host's herdr-web-ui, or mount
  `~/.config/herdr` via `HERDR_CONFIG_DIR`.
- The default compose/`docker run` does **not** set `pid: host`, so the `/proc` agent fallback sees
  only container processes. Host CPU/RAM are still host-wide (`/proc/stat`, `/proc/meminfo` are not
  namespaced). `pid: host` is a commented opt-in.
- Disk percentage follows the spec formula `used = total - f_bfree` over `total`, so it reads a few
  points below `df`'s `Use%` (which divides by `used + avail`). Same numbers, different denominator.
- v1 is read-only: no container start/stop/restart, no log streaming, no auth.
