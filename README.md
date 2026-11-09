# app-template

The starting point for new apps: a working, deployable app with everything that isn't specific to one idea. New apps are created from this template and add their own features on top.

The stack, patterns and conventions are documented in the `tools-used` docs; this README covers how this code works.

## What's included

- **Sign-in with passkeys**, invite-only. The admin invites each person with a one-time link (`/admin/people`); the link's token is in the URL fragment, so it never reaches server logs, and only its hash is stored. A new device is set up by inviting the same email again.
- **Server-side sessions**: the cookie holds a random token, the database holds its hash. 30 minutes idle, 12 hours in all. Every state-changing route checks the `Origin` header.
- **Audit log** (`audit_events`) for sign-ins, invites, removals, exports and deletions. Never put personal data in `detail`.
- **Activity** for the admin: when each person was last active (`users.last_active_at`, set at sign-in and when the session is touched) and their sign-ins in the last 30 days, on the People page. `python -m app.cli stats` prints the same as counts only (no names), for the app factory. No page views, clicks or IP addresses are recorded; the Your data page says so.
- **Your data** (`/account`): download everything as JSON, or delete the account (type DELETE). When you add tables that belong to a user, add them to `export_data()` in `app/routes/account.py` and give them `ForeignKey("users.id", ondelete="CASCADE")`.
- **Encryption at rest**: `EncryptedText` and `EncryptedJSON` column types in `app/models.py`, keyed by `TOKEN_ENCRYPTION_KEY`.
- **Appearance**: Dark (default), Light or System, saved on the account and in a cookie.
- **PWA shell**: manifest, icons, a service worker that caches only the offline page, an offline banner. Every page is `Cache-Control: no-store`.
- **Layout**: bottom tabs on phones, a sidebar on laptops, both from `NAV_ITEMS` in `app/web.py` (up to five; keep More last). Usable at 360 px.
- **Tests** (in-memory SQLite) and a test that the migrations build the same schema as the models.
- **CI**: lint, tests and a gitleaks secret scan on every push, only for pushes by `ccasad`.

## Making a new app from it

1. Create the repo from this template with issues and the wiki off.
2. Set the app's name: `APP_NAME` (env var), `name` / `short_name` / `description` in `app/static/manifest.webmanifest`, and `name` in `pyproject.toml`.
3. Replace the placeholder icons in `app/static/icons/` (keep the file names and sizes; the maskable icon keeps its artwork inside the centre 80%).
4. Fill in `REQUIREMENTS.md` and the `CHANGE ME` lines in `CLAUDE.md`.
5. Replace `app/templates/pages/home.html` and add pages to `NAV_ITEMS`.

## Local development (Docker)

```bash
cp .env.example .env     # set DATABASE_URL to a Neon dev branch, and TOKEN_ENCRYPTION_KEY
make migrate             # create the tables
make invite-admin        # prints a one-time link to set up your passkey
make up                  # http://localhost:8000
```

| Command | What it does |
| --- | --- |
| `make up` / `make down` | Start or stop the dev server |
| `make test` | Run the tests (in-memory SQLite, never your Neon database) |
| `make lint` / `make format` | Ruff checks / auto-fix and format |
| `make css` / `make css-watch` | Rebuild `app/static/css/app.css` after changing templates (it's committed) |
| `make migration m="add x"` | Generate a migration from model changes (review it before applying) |
| `make migrate` | Apply migrations to `DATABASE_URL` |
| `make requirements` | Regenerate `requirements.txt` after changing dependencies |

## Deploying (Vercel + Neon)

Vercel deploys `main`; there's no build step. Set these in Vercel (Production): `APP_BASE_URL`, `APP_NAME`, `DATABASE_URL` (Neon pooled URL), `TOKEN_ENCRYPTION_KEY`, `ADMIN_EMAIL`, `WEBAUTHN_RP_ID` (the domain, no scheme). Apply migrations to production **before** deploying code that needs them; they never run on deploy. Then create the first admin invite with `python -m app.cli invite --admin` against the production database.

## Secrets

Never in this repo. Where each one lives:

| Variable | Where it lives | Can it be regenerated? |
| --- | --- | --- |
| `TOKEN_ENCRYPTION_KEY` | Vercel env var + 1Password ("<app> keys", App Keys vault) | **No.** A new key can't read existing data. |
| `DATABASE_URL` | Vercel env var; Neon console → Connect | Yes (reset the password in Neon) |
| `APP_BASE_URL`, `APP_NAME`, `ADMIN_EMAIL`, `WEBAUTHN_RP_ID` | Vercel env vars | Not secrets |
