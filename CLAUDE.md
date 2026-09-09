# CLAUDE.md

## Project

Kies is a self-hosted, single-owner finance app growing into a personal Life OS. The UI and most comments are German. Do not propose registration, roles, or a multi-user system unless explicitly requested.

- Backend: FastAPI, SQLAlchemy, SQLite in `backend/app/`
- Frontend: vanilla JavaScript in `frontend/`, classic scripts and one shared global scope; no build step
- Native clients: Swift apps under `macos/`, with GRDB offline sync
- Current branch may contain unfinished user changes. Inspect `git status` and the diff first; never discard them.

Read the relevant implementation before assuming documentation or old notes are current.

## Efficient workflow

1. Use `rg` to locate the symbol or test.
2. Read only the relevant function or at most about 200 lines.
3. Change the smallest coherent area.
4. Run the focused check first; broaden only after it passes.
5. Summarize changed files, validation, and remaining limitations briefly.

Keep command output below 150 lines. Put verbose output in `/tmp` and inspect only the error summary. Do not read whole transcripts, databases, large logs, or generated files. Avoid repeated repository-wide searches and repeated auto-compaction. If context becomes bloated, start a fresh session from the current diff.

## Checks

```bash
python3 -m py_compile backend/app/<file>.py
python3 -m pyflakes backend/app/<file>.py
node --check frontend/js/<file>.js
cd backend && python3 -m pytest <focused-test> -q -x
```

Install development dependencies from `backend/requirements-dev.txt` only when needed. There is no frontend build or lint pipeline.

## Critical conventions

- `main.py` includes domain routers from `backend/app/routers/`. Put new endpoints in the matching router.
- Domain CRUD modules are re-exported through `crud.py`; apparent unused imports there can be deliberate.
- CRUD functions receive settings from callers; they do not fetch settings themselves.
- New frontend JS files must be added to `frontend/index.html` and `frontend/sw.js`; bump the service worker `CACHE_NAME`.
- Importing `app.main` starts APScheduler jobs. Tests must set a temporary `DATA_DIR` before importing it.
- Protected browser routes use session auth and CSRF. Native sync and webhooks use their own shared-secret headers.
- Native entities are added through `SYNC_REGISTRY`, with dependencies and last-write-wins conflict reporting.
- Send notifications through `notifications.notify()` so quiet hours apply centrally.
- Smart Home actions must keep the service allowlist, hard denylist, and confirmation rules intact.
- Never expose secrets, production data, tokens, or personal document contents in output.

## Deployment

A push to `main` publishes the image and TrueNAS Watchtower can deploy it automatically. CI tests are informational and do not block publishing. Before committing or pushing, run the relevant checks. Do not deploy, restart production, or copy files into the live container unless the user requested it.

Production paths differ: backend is `/app/app`, frontend is `/frontend`.

## Compact instructions

Preserve only the objective, modified files, failing test names, decisions, and next command. Drop raw file contents, long command output, old conversation, and repeated explanations.
