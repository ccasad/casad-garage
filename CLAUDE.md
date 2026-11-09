# CLAUDE.md

Context for Claude Code sessions in this repo.

## What this is

CHANGE ME: two or three sentences on what the app does and for whom.

**Read REQUIREMENTS.md before starting any task.** Requirement IDs (FR-x, NFR-x) are the source of truth; reference them in commits. README.md explains how the built parts work.

## Stack and commands

- Python 3.13 + FastAPI, deployed to Vercel (Hobby) as one serverless function (`app.main:app`)
- Neon Postgres via SQLAlchemy 2 + psycopg 3; schema changes are Alembic migrations
- Jinja2 + HTMX, Tailwind v4 (standalone CLI via pytailwindcss), PWA shell
- Passkeys (WebAuthn) for app sign-in, invite-only
- uv for dependencies; local development runs in Docker (the owner's Intel Mac can't install some deps natively)

Use the Makefile: `make up`, `make test`, `make lint`, `make format`, `make css`, `make migration m="..."`, `make migrate`, `make requirements`. Add packages with `uv add --no-sync <pkg>`, then `make requirements`.

## Status

Built (from app-template): passkey sign-in and invites, server-side sessions, audit log, activity (last active, sign-ins) for the admin, Your data (download and delete), Dark/Light/System theme, PWA shell, phone tabs and laptop sidebar, encrypted column types.

Not built yet: everything in REQUIREMENTS.md.

Next, in order:
1. CHANGE ME

## Rules

- Build as if the repo is public, even while it's private: no personal details (names, health or financial specifics, addresses, real emails) in any committed file or commit message. Use the GitHub no-reply email for commits. Never add a LICENSE file.
- GitHub workflows trigger only on `push` / `workflow_dispatch`, and every job checks `github.actor == 'ccasad' && github.triggering_actor == 'ccasad'`.
- Never commit secrets or real personal data. Keep secrets in `.env` (gitignored) and Vercel env vars; keep `.env.example` current. Tests use made-up data.
- No personal data in logs, URLs, error messages, or the service worker cache.
- Encrypt sensitive content at rest with the `app/crypto.py` helpers (`EncryptedText`, `EncryptedJSON`).
- Every query is scoped to the signed-in user.
- Every state-changing route has `dependencies=[Depends(same_origin)]`.
- Each request finishes within 60 seconds; long work continues across requests.
- Migrations: generate, review, and note in the PR that production must be migrated before deploy.
- Rebuild `app/static/css/app.css` with `make css` after adding Tailwind classes; it's committed.
- Keep pages usable at 360 px wide; check phone and laptop layouts and both themes.
- Write audit events for new sensitive actions, and add tests with each feature.
- When a to-do feature is finished, tick it in REQUIREMENTS.md and update README.md and the Status above.
