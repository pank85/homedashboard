# homedashboard — perf: containers-panel latency (worker report, 2026-10-17)

Repo: `/home/pank/projects/homedashboard` · branch `main` · checkout unmodified except pre-existing
`.ai/agent-reports/ergo-20261017-homedashboard.md` (not touched by me).

Scope allowed: `app/collectors/docker.py`, `app/settings.py`, `tests/test_docker.py`, `.env.example`,
`README.md`. Nothing else.

## Problem (as given, evidence)

`GET /api/containers` took **73.1 s** on the deployed instance against the live Docker daemon (39
containers). `collect_containers()` (`app/collectors/docker.py`) iterates the list sequentially and
per container calls `_one_container()`: `GET /containers/<id>/json` then
`GET /containers/<id>/stats?stream=false`. The `stats` call costs ~1.5–1.8 s/container on this daemon.
N × ~1.8 s = ~73 s. `_SocketClient.get_json()` opens a fresh `_UnixHTTPConnection` per call and holds
no shared state → safe to call from multiple threads.

## Report log

### 1. Inspection (done)

- `app/collectors/docker.py` — read in full. `collect_containers()` builds `api`, does the list call
  first, then `for item in listed: rows.append(_one_container(...))` with a per-item
  `except Exception: rows.append(_row_from_list(item))`; finally `rows.sort(key=_sort_key)`.
  `_SocketClient.get_json()` stateless (new connection each call). `_one_container()` uses
  `_get_optional()` (swallows per-call failures) for both `json` and `stats`.
- `app/settings.py` — frozen `Settings` dataclass + `load_settings`; `_parse_int` helper exists.
  Conventions docstring: collectors must **not** import this module; only `app.main` and
  `tests/test_settings` depend on it.
- `app/main.py` — `call_containers()` invokes the injected collector with
  `socket_path=`, `api_version=`, `timeout=` only. (`main.py` is NOT in the allowed file list.)
- `tests/test_docker.py` — 94 tests total in suite. `FakeClient` records `self.calls`; no test asserts
  the sequential *order* of internal calls. `test_default_client_get_only_round_trip` asserts
  `[method ...] == ["GET","GET","GET"]` for a single container (all GET → order-independent under
  concurrency) and uses `any(...)` for path contents. No sequential-order assertion to weaken.
- `tests/test_settings.py` — only calls `load_settings(...)`; adds no field, so a new `Settings` field
  is safe. `tests/test_page.py` builds its own stub `Settings` only when `app.settings` is missing
  (it is present here), so it is unaffected.
- `.env.example` / `README.md` env table — `DOCKER_*` block located; insertion points identified.
- No existing references to `CONTAINER_FETCH_WORKERS` anywhere in the repo.

### 2. Test-environment note

The host shell had `PYTHONPATH` empty and system `python3` (3.12.3) without the pinned deps. I
installed the project's pinned dev requirements into the user site so the exact verification command
works:

```
python3 -m pip install --user --break-system-packages -r requirements-dev.txt
```

(pre-existing `~/.local` has unrelated tools; this only added fastapi/httpx/pytest 8.3.4/etc.)

### 3. Baseline test run (before any change)

```
cd /home/pank/projects/homedashboard
PYTHONPATH= python3 -m pytest -q -p no:cacheprovider
```

Result: **94 passed, 1 warning in 2.15s** (matches the stated baseline of 94 passed).

### 4. Decisions / design

- Add `CONTAINER_FETCH_WORKERS`, effective default **8**, coerced to **min 1**, stdlib only
  (`concurrent.futures.ThreadPoolExecutor`).
- Because `docker.py` must not import `app.settings` (convention + explicit source test) and `main.py`
  is outside the allowed file list, the collector resolves the worker count as:
  explicit `workers=` argument → env `CONTAINER_FETCH_WORKERS` → default 8. `settings.py` gains a typed
  `container_fetch_workers` field (same env, min 1) as the canonical config surface, and the env
  fallback keeps the setting live end-to-end without touching `main.py`.
- Concurrency must not change observable output: results are written back by original list index, so
  the pre-sort row order equals the sequential order; `rows.sort(key=_sort_key)` is preserved
  verbatim (stable sort → identical final order regardless of completion order).
- Every worker exception is captured and falls back to `_row_from_list(item)`, mirroring the current
  `except Exception`.

### 5. Changes made

**`app/collectors/docker.py`** (+75/−9 area)

- New stdlib imports: `from concurrent.futures import ThreadPoolExecutor`, `import os`.
- New module constants `DEFAULT_CONTAINER_FETCH_WORKERS = 8` and
  `_CONTAINER_FETCH_WORKERS_ENV = "CONTAINER_FETCH_WORKERS"`, plus helpers
  `_workers_from_env()` and `_resolve_workers(explicit=None)`:
  takes an int/str, else `_workers_from_env()`, else the default; any
  non-int / out-of-range value falls back to the default; clamps with `max(1, ...)`.
  (Result is *not* memoized, so tests that change the env var are honoured.)
- New `_fetch_rows(api, version, items, moment, workers)`: builds one row per list item by
  original index (`ordered = [None] * len(items)`). `workers <= 1` (or a single item) keeps the
  exact sequential loop; otherwise it submits `_one_container` per item to a `ThreadPoolExecutor`,
  captures **each** future's exception and swallows it → keeps the `_row_from_list(item)`
  fallback for that index. `except Exception` mirrors the old inline `except Exception`, and
  `future.result()` is called per-future so one failure cannot cancel the others. Returns rows in
  original list order (completion order irrelevant).
- `collect_containers()` signature unchanged, plus an optional additive `workers=None` param
  (existing `client=` / `socket_path=` callers unaffected). The `/containers/json` list call is
  still first and sequential; per-item work moved from the inline loop into `_fetch_rows`;
  `rows.sort(key=_sort_key)` preserved verbatim. Outer-call failure still returns
  `_unavailable(...)` (JSON-error/socket-error) or `_list_failure(...)`.

**`app/settings.py`** (+4): added `container_fetch_workers: int` to the frozen `Settings`
  dataclass and `container_fetch_workers=max(1, _parse_int(env.get("CONTAINER_FETCH_WORKERS"), 8))`
  in `load_settings`. `_parse_int` already maps None/empty/invalid → default 8, and the `max(1, ...)`
  clamp keeps a configured `0` or negative from producing an invalid pool size.

**`.env.example`** (+3): under the `DOCKER_*` block, with comment
  `# Maximum parallel per-container Docker API fetches (minimum 1).` and
  `CONTAINER_FETCH_WORKERS=8`.

**`README.md`** (+1): table row `| \`CONTAINER_FETCH_WORKERS\` | \`8\` | Max parallel per-container Docker detail fetches (min 1). |`

**`tests/test_docker.py`** (+204, 5 new tests; `import time`, `import threading`, `_inspect`/`_stats`
  helpers already existed):

1. `test_rows_identical_across_worker_counts` — 5 containers, union of sort ranks/healths;
   asserts `sequential["containers"] == concurrent["containers"]` (contents **and** order) for
   `CONTAINER_FETCH_WORKERS=1` vs `=8`, and asserts the strict expected name order `[a, c, a2, b, d]`.
2. `test_stats_failure_soft_fails_and_stays_available` — `/stats` raises for one container; its row
   keeps the `json`-derived fields (health/restart_count) with `cpu_percent`/
   `memory_used_bytes`/`memory_limit_bytes` `None`, the other container is fully populated, and the
   result is `available: True, reason: None`.
3. `test_worker_exception_falls_back_to_list_only_row` — monkeypatches
   `app.collectors.docker._one_container` to raise; the future's exception is swallowed and each
   container yields its list-only row with pool path active (`workers=4`), `available: True`.
4. `test_concurrent_fetches_respect_worker_bound` — `TrackingClient` with a lock records
   in-flight calls (0.02 s sleep each); with bound `3` asserts `peak <= 3` (bound respected) and
   `peak >= 2` (actually concurrent).
5. `test_worker_count_coerced_to_minimum_one` — env values `0`, `-4`, `not-a-number`, `` all still
   return `available: True` and the expected single row (no crash, min clamp).

No existing test asserted sequential internal call order: `test_default_client_get_only_round_trip`
asserts `[method ...] == ["GET", "GET", "GET"]` (order-independent under concurrency) and `any(...)`
for paths, so it was left unchanged and still passes.

Scope audit: `git status --short` shows only `.env.example`, `README.md`, `app/collectors/docker.py`,
`app/settings.py`, `tests/test_docker.py` at `M` plus the new report file at `??`. The
`.ai/agent-reports/ergo-20261017-homedashboard.md` modification was pre-existing before this task
(the checkout was checked out dirty) and was **not** touched by me. No changes to Dockerfile,
entrypoint.sh, compose, CI, `proxy.py`, agents/host collectors, or templates.

### 6. Verification after change

Exact required command:

```
cd /home/pank/projects/homedashboard
PYTHONPATH= python3 -m pytest -q -p no:cacheprovider
```

Result: **99 passed, 1 warning in 2.19s** (baseline was 94 passed; +5 new tests, 0 failures, 0 errors).
The only warning is the pre-existing `starlette/testclient.py` `anyio.abc.BlockingPortal`
`DeprecationWarning`.

Flakiness check on the timing-sensitive bound test — the 5 new docker tests run 10× consecutively:
`5 passed, 14 deselected` every run (0.16–0.17 s each), so the concurrency assertions are stable.

I did **not** measure latency: the orchestrator rebuilds/deploys the image and measures end-to-end
against the live daemon. No latency figure is claimed here.

