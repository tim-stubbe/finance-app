---
name: project-conventions
description: Established working conventions for the Kies finance-app repo (deploy/test workflow, git conventions, architecture rules). Background knowledge for Claude only - not a user-invoked command.
user-invocable: false
---

# Kies – Project Conventions

Background knowledge distilled from many nights of work on this repo. Apply
automatically; no need to re-derive these from scratch each session.

## Deploy & live-test workflow (no CI gate by design)

There is **no CI deploy gate** — this is a deliberate choice by the user.
`docker-publish.yml` builds and pushes the Docker image on every push to
`main`, unconditionally. `tests.yml` (pytest) runs alongside it but is
purely informational and never blocks a deploy. Watchtower on the TrueNAS
server auto-pulls the new image within ~5 minutes of a push.

Because of this, **live-verification happens BEFORE the push, not via CI**:

1. Static checks first: `python3 -m py_compile` + `pyflakes` for changed
   backend files; `node --check` + an HTMLParser tag-balance script for
   changed frontend files.
2. Stage changed files locally into a scratch dir mirroring the container
   layout, then `docker cp` them into the **running** production container
   (`ix-stubbe-finance-app-stubbe-finance-app-1` on host `truenas`, SSH
   alias in `~/.ssh/config`, passwordless `sudo`).
3. **Path matters — this has bitten us before**: the container has TWO
   separate roots.
   - Backend (`backend/app/*.py`) → `WORKDIR /app`, `COPY backend/app ./app`
     → lands at `CONTAINER:/app/app/...`. `docker cp` destination:
     `CONTAINER:/app/`.
   - Frontend (`frontend/*`) → `FRONTEND_DIR=/frontend`,
     `COPY frontend /frontend` → lands at `CONTAINER:/frontend/...`.
     `docker cp` destination: `CONTAINER:/` (container **root**), NOT
     `/app/`. Copying frontend files to `/app/` silently creates a stray,
     unserved `/app/frontend` directory — looks successful, isn't served.
     A hookify rule (`.claude/hookify.kies-frontend-docker-cp-path.local.md`)
     warns on this specific mistake.
4. Verify what actually got served: `curl -sk https://localhost:8000/<path>`
   against the running container (via SSH), not just "the copy succeeded".
5. Test backend logic live via `docker exec ... python3 -c "from app import
   main; ..."` one-liners, or install pytest/httpx ephemerally
   (`pip install --no-cache-dir pytest httpx` inside the container),
   `docker cp` the `backend/tests/` dir in, run `python3 -m pytest tests/`,
   then **uninstall pytest/httpx afterward** — they must never persist in
   the production image.
6. Static files (HTML/CSS/JS) are served fresh from disk on every request —
   no restart needed. Backend Python logic loaded into the already-running
   uvicorn process needs `docker restart <container>` to take effect.
7. Only after live verification: `git add`, `git commit`, then **immediately
   `git push origin main`** without waiting for confirmation — this is a
   standing preference, not something to ask about each time.
8. Don't actively wait/poll for a deploy or background job with `sleep` —
   either keep working on something else, or react to the background-task
   completion notification when it arrives.

## Architecture rules

- **Never build a system that already exists.** Before adding a feature,
  check `frontend/js/*.js`, `backend/app/routers/*.py`, `backend/app/
  crud*.py`, and `ROADMAP.md` for something equivalent already there —
  extend it instead of duplicating (this repo has caught several near-
  duplicate builds this way; ⌘K search, bulk-categorize, duplicate
  detection, and the Fehler-Log all already existed when later asked-for
  features assumed they didn't).
- `crud.py` (and its `crud_*.py` siblings) **never fetches `Settings`
  itself** — callers (routers/scheduler) fetch via
  `auth.get_or_create_settings(db)` and pass `settings` in as a parameter.
- `notifications.notify(settings, text, urgent=False)` is the single choke
  point for all Telegram sends (quiet-hours logic lives there once, not
  duplicated per caller).
- `AssistantSuggestion` (`kind`, `ref_id` unique together) is the shared
  pending/accepted/rejected/snoozed queue — reuse it for any new
  "propose, then confirm" feature rather than building a parallel one.
  `create_suggestion_if_new()` dedups only via `(kind, ref_id)` — a
  suggestion kind whose `ref_id` is freshly generated each detection run
  (rather than a stable existing row's id) breaks the "don't re-ask after
  rejection" guarantee unless the underlying draft row is kept (not
  deleted) on rejection as a permanent marker. This exact bug shipped once
  for `category_rule` suggestions and was fixed by not deleting the draft.
- `IgnoredRecurringPayment` is the user-facing escape hatch for a false-
  positive recurring-payment detection (e.g. several similar-sized
  purchases through a BNPL/installment merchant getting mistaken for a
  subscription). Point users at it — or apply it directly via
  `crud.create_ignored_recurring_payment` — rather than trying to make the
  heuristic itself smarter for one merchant.
- Frontend is intentionally classic `<script>` tags sharing one global
  scope (no ES modules, no build step) — new JS files follow the same
  pattern, added to `frontend/index.html`'s script list AND to
  `SHELL_ASSETS` in `frontend/sw.js`, with `CACHE_NAME` bumped so installed
  PWA instances pick up the change.
- Any negative-cache pattern (an external lookup that failed and shouldn't
  be retried every call) needs an explicit TTL, not permanent caching of
  the failure — a `resolved_at`/`fetched_at` timestamp column without an
  actual TTL check in the read path is a bug waiting to be found (shipped
  once for `IsinTickerCache`, fixed with `ISIN_NEGATIVE_CACHE_TTL`).
- Anomaly/heuristic detectors that operate on `Transaction.amount` sign
  alone (not `Category.type`) can misfire on income-type categories that
  happen to contain negative-signed entries (corrections, untagged
  transfers) — always check the category's actual type when the detector's
  name implies a direction (e.g. "spending outlier" should never fire on
  an `einnahme` category).

## Rigor before declaring something done

`py_compile`/`pyflakes`/`node --check`/HTML-balance-check are necessary but
not sufficient — several real bugs in this repo were only caught by a
deliberate self-review pass or an explicit `pr-review-toolkit` agent run
*after* the code already compiled and passed its own tests, by reading the
diff again with fresh eyes against the docstrings' own stated claims (e.g.
a docstring claiming a missed cron slot would be "caught up" when the
actual comparison logic couldn't do that; a docstring claiming a TTL exists
when the read path never checked it). When asked to review recently-shipped
work, prefer spawning `pr-review-toolkit:code-reviewer` (or the general
`code-review` skill) over assuming the existing tests/compile-cleanliness
already prove correctness.
