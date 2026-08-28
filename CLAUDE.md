# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Kies — a self-hosted, single-user personal/business finance app and
growing "life OS" (accounts/transactions, investments, debts, goals, plus
non-finance domains: photos, calendar/todos, projects, life-area habit
tracking, contacts, reading list). German UI and comments throughout. No
multi-user/role system by design (single owner, no registration) — don't
propose one.

FastAPI + SQLAlchemy + SQLite backend (`backend/app/`), vanilla-JS frontend
with **no build step** (`frontend/`, classic `<script>` tags sharing one
global scope — not ES modules). macOS/iOS companion apps under `macos/`
(Swift, GRDB-backed offline sync, separate from this repo's day-to-day
workflow unless a change needs a native counterpart).

See `README.md` for the full feature list and `ROADMAP.md` (gitignored,
not in the repo — private working notes) for current priorities.

## Commands

```bash
# Local dev (mounts code into the container, uvicorn --reload)
docker compose up -d
# -> http://localhost:8000

# Backend: compile/lint a changed file before anything else
python3 -m py_compile backend/app/<file>.py
python3 -m pyflakes backend/app/<file>.py   # ignore ".crud_*.X imported but unused" — deliberate re-export pattern in crud.py, not a bug

# Frontend: syntax-check a changed JS file (no bundler/linter configured)
node --check frontend/js/<file>.js

# Tests (backend/tests/, pytest) - install once, not part of the production image
pip install -r backend/requirements-dev.txt
cd backend && python3 -m pytest tests/ -v
python3 -m pytest tests/test_auth.py::test_login_lockout_after_repeated_failures -v   # single test

# Pull live production data into a local dev copy (one-way, see README "Datenhaltung")
./scripts/pull-live.sh
```

There is no frontend build/lint toolchain — `node --check` is purely a
syntax check, nothing more is configured.

## Deploy model — read before assuming CI gates anything

`docker-publish.yml` builds and pushes the image to GHCR on every push to
`main`, unconditionally. Watchtower on the production TrueNAS host
auto-pulls within minutes. `tests.yml` (pytest) runs in parallel but is
**informational only** — it does not block the image push. This is a
deliberate choice, not an oversight: live-verification against the running
production container (`docker cp` a changed file in, exercise it, then
`docker restart` if backend Python changed) is expected to happen *before*
committing, not delegated to CI. See `.claude/skills/project-conventions/`
for the detailed workflow, including a path-layout gotcha in the
production container (frontend serves from `/frontend`, backend from
`/app/app` — they are NOT both under `/app`).

## Architecture

**Backend module layout** (`backend/app/`): `main.py` is intentionally thin
(~1600 lines) — almost every endpoint lives in `routers/*.py` (27 modules,
one FastAPI `APIRouter` per domain), included into `main.py`'s `app` with
`dependencies=[Depends(auth.require_auth)]` for protected ones or none for
the public auth/sync/webhook routers. `crud.py` was similarly split into
domain modules (`crud_investments.py`, `crud_todos.py`,
`crud_connections.py`, `crud_goals.py`, `crud_life_areas.py`,
`crud_misc.py`, `crud_trips_review.py`, `crud_routines.py`) — each
re-imported back into `crud.py`'s namespace (`from .crud_investments import
*`-style) so callers keep using `crud.foo()` regardless of which file `foo`
actually lives in. What's left directly in `crud.py` (~2300 lines) is the
irreducible core: accounts, categories, transactions, recurring-payment
detection, budgets, dashboard/net-worth aggregation, global search — things
either foundational (referenced by almost everything) or genuinely
cross-cutting with hard circular dependencies if split further.

`crud.py`/`crud_*.py` functions never fetch `Settings` themselves — callers
(routers, the scheduler) fetch via `auth.get_or_create_settings(db)` and
pass `settings` in as a parameter.

**Frontend module layout** (`frontend/js/`): physically split by the
former `app.js`'s section markers into ~40 files, but still classic
`<script>` tags — every file shares one global scope (functions/consts
declared in one file are callable from any other). New files must be added
to `frontend/index.html`'s script list AND to `SHELL_ASSETS` in
`frontend/sw.js`, with `sw.js`'s `CACHE_NAME` bumped so installed PWA
instances actually pick up the change (stale-cache bug otherwise).

**Scheduling**: `main.py` creates a single `APScheduler` `BackgroundScheduler`
at **module import time** (not inside a FastAPI startup event) — importing
`app.main` anywhere (including in tests) starts every registered cron job
against whatever `DATA_DIR` is currently configured. Tests set `DATA_DIR`
to a temp directory before importing (`backend/tests/conftest.py`) to avoid
touching production data; the jobs still technically start but have
nothing to act on against an empty test DB.

**Auth** (`auth.py`, `routers/auth_login.py`): password (Argon2id) + optional
TOTP (2FA) + optional passkeys (WebAuthn), session-cookie based with CSRF
double-submit-cookie protection (`auth.require_auth`, checked on every
mutating request to a protected router) and progressive brute-force
lockout (`FAILED_LOGIN_THRESHOLD`/`LOCKOUT_BASE_SECONDS`, must be wired
into *every* endpoint that verifies a password/TOTP/recovery code — this
exact omission has shipped as a real bug twice already, see
`.claude/agents/security-reviewer.md`). Native sync (`/api/sync/*`) and the
n8n webhook (`/api/webhook/*`) are deliberately **outside** this login
system — their own shared-secret headers, since native clients/n8n have no
browser session.

**Sync registry** (`sync_registry.py`/`sync.py`): the native macOS/iOS
clients pull/push through a generic entity registry
(`SYNC_REGISTRY: dict[str, SyncEntity]`) rather than per-entity endpoints —
adding a new syncable entity means registering it here with
create/update/delete functions and `depends_on` (for ordering), not writing
new routes. Conflict resolution is last-write-wins via `updated_at`, with
losing writes returned to the client as visible `conflicts[]` rather than
silently dropped. A generic tombstone table (`sync_tombstones.py`, hooked
via a SQLAlchemy session event) covers deletes for every model
automatically, without touching `crud.py` per-model.

**Suggestion queue** (`AssistantSuggestion`, `crud.create_suggestion_if_new`
/ `decide_pending_suggestion`): the shared "propose, then user
confirms/rejects/snoozes" mechanism, reused across unrelated features
(overdue-todo nudges, auto-detected category rules) rather than each
building its own pending-state table. Dedup is keyed on `(kind, ref_id)` —
a `ref_id` that's freshly generated on every detection pass (instead of a
stable existing row's id) breaks the "don't re-ask after rejection"
guarantee unless the underlying draft row is kept, not deleted, on
rejection.

**Notifications** (`notifications.py`): `notifications.notify(settings,
text, urgent=False)` is the single choke point for all Telegram sends —
quiet-hours logic lives there once. Don't add a per-caller quiet-hours
check; call `notify()`.

**Smart Home** (`smarthome.py` + `ha_client.py` + `routers/smarthome.py`,
`crud_smarthome.py`): the non-finance "life OS" bridge — Home Assistant REST
(`ha_client`, sync `requests`, same shape as `ollama_client`) plus the local
Ollama for free-form requests. `smarthome.process_command(db, settings, text,
confirm=False)` is the one pipeline entry point (fast path: alias/keyword →
direct HA service; else LLM intent JSON), never raises — errors come back as
`{"ok": False, "reply": <de>}`. Policy is an allowlist of `domain.service`
pairs (`DEFAULT_ALLOWED_SERVICES`) plus a hard `BLOCKED_SERVICES` denylist;
extra pairs opt-in via `settings.homeassistant_extra_services`. HA
URL/token/filters live on `Settings` (token Fernet-encrypted like every other
secret). `voice/` (`stt.py`/`tts.py`, chosen via `STT_BACKEND`/`TTS_BACKEND`
env — `stub`|`faster-whisper`|`piper`|`http`) does local speech in/out for
`POST /api/smarthome/voice/command`; heavy deps are opt-in via
`requirements-voice.txt`, default `stub` returns 501. `SmartHomeFloorplan` is
one JSON blob (rooms+devices geometry in metres) driven only by the 2D editor
+ 3D view in `js/smarthome-floorplan.js`. `smarthome_automations.py` lets the
LLM propose workflows and write the HA automation YAML for them
(`SmartHomeAutomationDraft`, status vorschlag→entwurf→angelegt); YAML is
validated against the same `service_allowed` allowlist + known entity_ids
before it can be pushed via the HA config API — never auto-armed; a weekly
scheduler job (`_scheduled_smarthome_automation_suggestions`) drops one
digest nudge into the `AssistantSuggestion` queue. `smarthome_ws.py` is a
background thread holding an HA-WebSocket state cache (`_get_states` prefers
it over REST); `GET /api/smarthome/events` re-broadcasts changes to the UI as
SSE. Hands-free voice: browser streams 16 kHz PCM over the WebSocket
`/api/smarthome/voice/stream` (its own `smarthome_ws_router`, no
`require_auth` dep — auth checked in-handler via `ws.session`);
`voice/wakeword.py` runs openWakeWord ("hey jarvis") server-side, then the
captured command goes through the normal pipeline. `openwakeword` ships in
`requirements-voice.txt`.
