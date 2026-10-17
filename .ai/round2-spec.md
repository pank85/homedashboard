# homedashboard round 2 — spec (authoritative)

Round 1 shipped: containers / agents / host panels, `/api/*`, the Herdr Web reverse proxy,
Dockerfile + compose, GitLab CI that **builds and now deploys** to the homeserver, and
concurrent container fetches. Round 2 is this document. Code is the source of truth for patterns.

Live instance: container `homedashboard` on the homeserver, published on **8090**, served publicly at
**https://dashboard.pkatopodis.me** (Cloudflare → NPM → 172.16.0.50:8090). Repo root
`/home/pank/projects/homedashboard`, branch `main`.

## Hard constraints (carried from round 1, not renegotiable)

- C1 **Generic.** No hardcoded hostnames, IPs, usernames or absolute host paths outside env defaults.
  Every new setting goes in `.env.example` + the README table.
- C2 **Degrade, never crash.** Every source is optional; a missing one shows `unavailable: <reason>`.
  The page must render with nothing mounted.
- C3 **Read-only by default.** Existing endpoints stay read-only. The new state-changing actions (R6)
  are behind an explicit token and must be disabled when it is unset.
- C4 No secrets in the repo or the image.
- C5 Stdlib first. New runtime dependencies require justification; SQLite is `sqlite3` (stdlib).
- C6 One published port.

## R1 — Human-readable values everywhere (all panels)

Add one pure formatting module (e.g. `app/formatting.py`) and use it in the JSON payload **and** the
templates, so the API and the page never disagree:

- bytes → `B / KiB / MiB / GiB / TiB` (binary, 1 decimal above KiB) with the raw byte value kept in the
  JSON alongside the formatted string (machine consumers keep working).
- uptime / elapsed → `3d 4h`, `5h 12m`, `42s`.
- percentages → 1 decimal.
- timestamps → ISO in the JSON, and a short relative form (`12s ago`) in the UI.

The reported complaint is literally "human readable values gb not kilobits", so every size currently shown
in KiB/MiB must be presented in GB-scale units where that is the natural unit, and the JSON must carry a
`*_human` string next to each raw number.

## R2 — Prettier container cards + filtering

- One card per container in a responsive CSS grid (1 column on a phone, auto-fill on a desktop). Each card:
  name (the compose service name readable, container id short), image (tag only, with the registry host
  elided), a **state badge** (running / exited / restarting / created / paused), a **health badge**
  (healthy / unhealthy / none), uptime, restart count, and CPU + memory as a labelled bar with the
  human-readable value.
- **Filter controls**, client-side, no round trip: a text box matching name or image, a state filter
  (All / Running / Stopped), and a "hide healthy" toggle. Filters must survive the periodic refresh
  (re-apply after each poll) and show a count ("12 of 38 shown").
- Sorting: unhealthy/restarting first, then running by name (existing contract — keep it).
- Degenerate cases: 0 containers, 1 container, a container with no healthcheck, an exited container with
  no stats — all render without a gap or an "undefined".
- Accessibility: the badges must not rely on colour alone (include the word).

## R3 — AI agents panel: Hermes, Pi, OpenCode, Claude, and herdr state

The panel must show, for each detected agent: the agent kind/name, its herdr workspace label, its tab
label, its herdr status (`working` / `idle` / `blocked` / `done` / `unknown`), its cwd, and how long it has
been in that state where herdr reports it. Group by workspace.

Add a **herdr block** above the agent list reporting whether a herdr server is reachable, the herdr
version, the session name in use, and the workspace/tab/agent counts. When the mounted herdr config is
absent the block says exactly that (C2) instead of showing an empty list.

Sources, in order: (1) the herdr CLI against the mounted host config (see R5), (2) the `/proc` process
scan (already implemented), with the panel naming which sources contributed.

**Scout must answer before the Architect plans:** the exact `herdr` CLI surface for this installed
version (0.9.5) — `herdr agent start --help`, `herdr agent --help`, `herdr tab --help`,
`herdr workspace --help`, `herdr server agent-manifests` — and which `--kind` values are actually
supported (we believe `hermes`, `pi`, `opencode`, `claude`). Do not guess a flag that the binary does not
have; report the literal help text.

## R4 — Chat sessions the user can start, that survive

A "New session" control: pick an agent kind (the allowlisted kinds from R3), pick or type a working
directory (validated, R6), optionally a label, then **Start**. The dashboard creates a real herdr
workspace + tab + agent on the host and records the result in the local DB (R7). The new session appears
in the panel immediately and in a **Sessions** list, so it is not lost when the browser is closed or the
page is refreshed — that is the point of the feature ("για να μη το χάνουμε").

The Sessions list shows: label, agent kind, herdr workspace id, status, cwd, created/updated time,
and a click-through to Herdr Web (the existing `/herdr/` proxy) focused on that session. Provide a
**Copy / link** action giving the exact `herdr --session <name> attach` command a human can paste in a
terminal, and a way to mark a session finished/archived in our DB (this must NOT stop or delete anything
in herdr — see C3; say so in the UI).

## R5 — Reaching the host herdr from the container (verified feasibility)

Verified manually on 2026-10-17: mounting `/home/pank/.config/herdr` into the container at herdr's own
default config path makes `herdr --session hermes workspace list` and `herdr --session hermes agent list`
return the host's **real** workspaces and agents, including over a read-only mount. Design against that:

- New setting `HERDR_SESSION` (default `hermes`). **Never** operate on session `default` — it is the
  user's personal session. Refuse (and say so) if asked for `default`.
- New setting `HERDR_CONFIG_DIR` already exists for our app's own purposes; make the docs state that the
  host config directory must be mounted at herdr's default path inside the container for these features.
- The compose files must show the mount, commented or defaulted so a stranger without herdr still works.
- Every herdr CLI call is bounded by a timeout and its failure degrades (C2). Report the literal command
  and its stderr in the panel's `reason` when it fails — that is what made round 1's bugs findable.

## R6 — Action endpoints, token-gated (security is not optional here)

The dashboard is **publicly reachable**. A web endpoint that can spawn agents on the host is a real risk,
so:

- New setting `CHAT_API_TOKEN`. **Unset means every state-changing endpoint returns 403 and the UI renders
  the "New session" control disabled with the reason.** This is the default and it must fail closed.
- With a token set, every mutating call (`POST /api/sessions`, `POST /api/sessions/<id>/archive`, any
  other write) requires it, accepted either as `Authorization: Bearer <token>` or a same-origin form
  field. Never place the token in the HTML or in client-side JS in a way that is served to other users —
  the UI may accept it once from the operator and keep it in `localStorage` (document that choice).
- **Strict input validation, allowlists only:** agent kind from the R3-supported set; the working
  directory must resolve under `CHAT_CWD_ALLOWLIST` (comma-separated absolute prefixes, default the
  user's projects root supplied by the deployment, NOT hardcoded in code) and must exist; the label is
  restricted to a safe character class and a length cap. Reject anything else with 400 and a reason.
- **Never build a shell string.** Execute `herdr` with an argv list, never `shell=True`, never
  `os.system`, never string interpolation into a shell. This is the single most important requirement in
  R2 — a review finding here blocks approval.
- No endpoint may start/stop/delete containers (round-1 C3 still holds).

## R7 — Persistence (SQLite, no new infrastructure)

- `sqlite3` from the standard library (C5). New setting `DB_PATH` (default `/data/dashboard.db`), the
  parent directory created on startup if missing. Deployment mounts it as a bind mount at
  `/home/pank/docker-data/homedashboard` (the homeserver convention: no named volumes).
- Tables (names are the Architect's choice, but the content is required):
  - our chat sessions: label, agent kind, herdr session name, herdr workspace/tab/pane ids, cwd, status
    (`starting`/`running`/`idle`/`blocked`/`done`/`archived`/`failed`), created_at, updated_at, and the
    last error text when creation failed;
  - observed herdr state: a snapshot row per (workspace, tab/agent) per refresh — enough to answer
    "what was running and when" without unbounded growth. Keep a bounded retention (a setting, default
    e.g. 7 days or N snapshots) and prune on write — an unbounded snapshot table is a defect.
- Writes must be safe under the app's concurrent access (the page polls; the collector may run in a
  thread): one connection policy, `check_same_thread` handled, a lock or a connection-per-thread, and a
  WAL journal. State the policy in the plan and test it.
- The DB must never be required: `DB_PATH` unset or unwritable → sessions panel says persistence is
  unavailable, the read-only panels keep working (C2).
- Schema changes apply on startup with a tiny idempotent migration step (this project has no Alembic and
  must not gain one).

## R8 — Deployment updates

- The homeserver compose gains: the herdr config mount, `HERDR_SESSION`, `DB_PATH` + the bind mount for
  `/home/pank/docker-data/homedashboard`, `CHAT_API_TOKEN` (from `.env`, never committed), and
  `CHAT_CWD_ALLOWLIST`.
- `.env.example` and the README document every new key, the herdr mount requirement, the token's
  fail-closed default, and the exact `herdr ... attach` command a human can paste.

## Testing

`pytest` (stdlib + the pinned deps). Required coverage, at minimum:
- formatting helpers at boundaries (1023/1024 bytes, 0, None, huge values, 1 decimal rounding);
- the container filter/sort semantics as pure functions (not only in the template);
- the herdr output parser against saved realistic payloads, including an error payload and an empty one;
- **the action endpoints with the token unset → 403**, with a wrong token → 401/403, with the correct
  token → the happy path against a fake herdr runner;
- input validation: path outside the allowlist, non-existent path, an unknown agent kind, a label with
  shell metacharacters, a path that resolves via `..` out of the allowlist — each must be rejected;
- the SQLite layer: create session, list, archive, snapshot pruning actually prunes, and the
  "DB unavailable" path;
- one test per panel asserting the page renders when every source is unavailable (round-1 contract).

## Out of scope (state in the plan's "will not change" list)

Stopping/deleting containers or herdr sessions; authentication of the whole dashboard (only the mutating
endpoints are gated); history charts; multi-host; streaming terminals inside the page (that stays in
Herdr Web via the existing `/herdr/` proxy); user accounts; mobile app.

## Definition of done

- `pytest` green.
- The page renders with the new cards, filters, human-readable values, the agents/herdr block and the
  Sessions list — verified against the live daemon, not only with fixtures.
- With `CHAT_API_TOKEN` unset, every mutating endpoint returns 403 (tested with curl).
- With a token set, creating a session via the UI/API creates a **real** herdr workspace that survives a
  page reload and is listed in the Sessions list.
- GitLab pipeline green through build **and** deploy; the running container is the new image.
- Pushed to both GitHub and GitLab.
