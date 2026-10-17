# Review: concurrent container fetches (2026-10-17)

Verdict: no blocking defect. The uncommitted collector change preserves list-call failure semantics, per-container soft-fail for `Exception`, index order before the stable sort, and pool shutdown. Latency was not measured here and is not claimed.

## Pytest (this review, not the worker report)

```
cd /home/pank/projects/homedashboard
PYTHONPATH= python3 -m pytest -q -p no:cacheprovider
```

Observed: **99 passed, 1 warning in 2.29s**. The warning is the pre-existing `starlette/testclient.py` `anyio.abc.BlockingPortal` `DeprecationWarning`. No failures.

## Findings

No blocking findings. Residual notes below are not required code changes.

### Note — published order test does not prove tie stability (low, test gap only)

`tests/test_docker.py:542-592` compares `CONTAINER_FETCH_WORKERS=1` vs `8` on five containers whose `_sort_key` tuples are all distinct (`app/collectors/docker.py:341-350` returns `(rank, name)`). A completion-order scramble of those rows still sorts to `a, c, a2, b, d`. Confirmed by reversing the pre-sort list and re-running that fixture: sorted output still matched.

The implementation itself is not completion-order dependent. `app/collectors/docker.py:229-240` writes `future.result()` into `ordered[index]` and only then returns that list. `rows.sort(key=_sort_key)` at `app/collectors/docker.py:76` is stable, so equal keys keep list order (non-dicts already dropped at line 74, same as the old `continue`).

Experiment (not in the suite): two `running` containers both named `dup`, first inspect slept 0.2s so it finished last, plus an `exited` sibling. `workers=8` restart order was `[11, 22, 0]`, identical to `workers=1`. That is the case the suite does not lock.

Not a code defect. Optional follow-up: assert that tie order in a test. Do not treat the current equality assertion as proof.

### Note — `BaseException` from a worker still escapes (matches the required `except Exception`)

`app/collectors/docker.py:237-240` (and the sequential branch at 224-228) catch `Exception` only. A worker `BaseException` subclass is re-raised by `future.result()` and is not caught by `collect_containers`'s outer `except Exception` (`app/collectors/docker.py:83-84`). Probe: custom `BaseException` escaped. `RuntimeError` did not: both rows were list-only, `available` stayed `True`.

The change brief required parity with the old `except Exception`, not `BaseException`. `json`/`stats` failures on the default client are `OSError`, `JSONDecodeError`, or `_DockerHTTPError`, all `Exception`, and `_get_optional` (`app/collectors/docker.py:247-250`) already turns those into a list-only or partial row before they become future failures. Pool `with` still ran `__exit__`: thread count returned to the pre-call value after the `BaseException` escaped. Do not "fix" this by bare `except BaseException` around `future.result()` — that would also swallow a main-thread `KeyboardInterrupt` raised while waiting.

### Note — `submit()` failure becomes a whole-collector unavailable, and does not leak the pool

If `executor.submit` raises, the exception leaves `_fetch_rows`, the `with` at `app/collectors/docker.py:230` still shuts the pool down (`wait=True`), and `collect_containers` returns `_unavailable(..., "collector error")` (`app/collectors/docker.py:83-84`). Probe: `RuntimeError("submit failed")` did not escape; active thread count was unchanged. This is not a per-container soft-fail, and it does not need to be: no worker ran. Worker `Exception`s on the result path stay per-row (`app/collectors/docker.py:237-240`).

### Note — injected client is called concurrently; default client is safe

`_SocketClient.get_json` opens a new `_UnixHTTPConnection` per call and closes it before return (`app/collectors/docker.py:115-128`). No shared socket, no shared buffer. Safe for the pool.

`_fetch_rows` passes that same `api` object into every worker (`app/collectors/docker.py:231-234`). An injected client that mutates unsynchronized instance state can race. The change brief also required a fake client that records in-flight calls and exceeds 1, so concurrent `client.get_json` is what that test measures (`tests/test_docker.py:688-722`). `FakeClient.calls.append` is the only shared mutation in the existing double; the suite passed, and row contents do not depend on `calls`. Production does not use `client=`. No lock was added around I/O, which is required for the latency fix. Do not wrap default-client `get_json` in a lock — that would serialize the stats calls this change exists to overlap.

### Note — `Settings.container_fetch_workers` is not passed into the collector

`app/settings.py:109-111` parses `CONTAINER_FETCH_WORKERS` with `max(1, _parse_int(..., 8))`. Nothing reads `settings.container_fetch_workers`. `app/main.py:175-179` still passes only socket, API version, and timeout. That file was outside the allowed edit set, and `tests/test_docker.py:381-388` forbids `docker.py` from importing `app.settings`.

The live path is `os.environ` inside `_workers_from_env` (`app/collectors/docker.py:204-211`), then `max(1, ...)` in `_resolve_workers` (`app/collectors/docker.py:193-201`). `docker-compose.yml` loads `.env` via `env_file`, so a deployed `CONTAINER_FETCH_WORKERS` is in the process environment and the collector sees it. Garbage tolerance matches settings: probed `load_settings` for `None`, `""`, `"  "`, `"0"`, `"-4"`, `"not-a-number"`, `"8.5"` → `8, 8, 8, 1, 1, 8, 8`. Collector env coercion is covered by `tests/test_docker.py:726-742` for `0`, `-4`, `not-a-number`, `""`.

Documented in `.env.example:25-26` and `README.md:118` next to the other `DOCKER_*` rows, default 8, minimum 1. Not a functional miss given the file allowlist. Wiring it through `call_containers` would be a separate, out-of-scope edit.

### Note — do not stage the unrelated dirty report

`git status` also shows `.ai/agent-reports/ergo-20261017-homedashboard.md` modified. Its mtime is 16:09; the perf edits are 22:12. The diff is CI registry notes, not this change. The worker report says it was already dirty. Do not include it in the perf commit. The five allowed source files plus the worker report are the perf set. This review file is the only file this review wrote.

## Checks that held

1. **Order.** Index write-back plus stable `_sort_key`. Tie experiment above matched `workers=1` even when the first container finished last. `refreshed_at` stayed the caller-supplied `now` (`2024-06-01T00:00:00+00:00`), not completion time (`app/collectors/docker.py:77-81`).
2. **Soft-fail.** Stats/`Exception` → list-only or partial row, `available: True`. Non-dict list entries are skipped (`app/collectors/docker.py:74`); a probe with `str`/`None`/`int` plus one real dict kept only dict rows.
3. **Outer list failure.** Unchanged branches at `app/collectors/docker.py:66-73`. Probes: `OSError` → `docker socket not reachable: ...`; `JSONDecodeError` and a non-list body → `malformed JSON from docker API`; `available` false and `containers` empty in all three.
4. **Pool lifecycle.** Pool exists only inside `with ThreadPoolExecutor` (`app/collectors/docker.py:230`). Empty list and `workers <= 1` return before that (`app/collectors/docker.py:221-228`). After a normal call, a `submit` failure, and a `BaseException` escape, `threading.active_count()` was back to the pre-call value.
5. **Bound is real.** `tests/test_docker.py:720-722` asserts `peak <= 3` and `peak >= 2`, with inflight updated under one lock around a 0.02s sleep (`tests/test_docker.py:688-711`). Forcing `ThreadPoolExecutor.__init__` to `max_workers=64` made that test raise `AssertionError`. Ignoring the bound fails the test. A fully sequential implementation fails `peak >= 2`.
6. **No weakened test.** `git diff` for `tests/test_docker.py` only adds `import time` and five new tests. `test_default_client_get_only_round_trip` still requires three GETs. Single-container default-client tests never enter the pool (`len(items) == 1` at `app/collectors/docker.py:222`).
7. **Scope of the perf edit.** Source hunks are only `app/collectors/docker.py`, `app/settings.py`, `tests/test_docker.py`, `.env.example`, `README.md`.

No latency number is accepted or claimed. That measurement waits on a rebuilt image.

VERDICT: APPROVED
