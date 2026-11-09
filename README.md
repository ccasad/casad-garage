# Casad Garage

A shared garage for a household: every car in one place, with its facts, dated mileage, service history, upcoming due dates and the work a shop recommended but hasn't done yet. Car details fill in from the VIN (free NHTSA lookup), and a shop's PDF invoice can be imported instead of typed in. Invite-only; everyone sees the shared cars, and a car can be marked **Only me**.

Requirements are in `REQUIREMENTS.md` (FR-x / NFR-x); `BUILD_LOG.md` records what was built and the decisions made along the way.

## What it does

The app is organised around **one selected car**, chosen from the selector at the top right of every page (it remembers your last choice). The selector lists your cars (starred first, then your sort order), marks cars with items due soon, and links to **All cars** and **Add a car**.

| Page | Path | What's there |
| --- | --- | --- |
| Overview | `/` | Photo, facts, loan, current mileage (with a quick add), due-soon banners, "last done" per service type |
| Service | `/service` | The car's service records, newest first, with a type filter and text search; log a service, upload an invoice |
| Service record | `/service/{id}` | Items with type, brand, part number, cost and warranty; a DIY tag and who did it for Myself records; edit or delete; offers to set the next inspection / oil-change due item |
| Due | `/due` | Due items soonest first (overdue and due-soon highlighted), mark done, add or edit; completed items in a collapsed list |
| To do | `/todo` | Recommended work (from declined invoice jobs or added by hand) with the quoted total; mark done (optionally linking the service record) or dismiss |
| All cars | `/cars` | A card per visible car with photo, current mileage and its due-soon items; star cars and choose the sort |
| Add / edit a car | `/cars/new`, `/cars/{id}/edit` | Year, make, model, trim, engine, color, plate, title number, VIN with **Look up**, loan, notes, Shared / Only me |
| Invoice review | `/invoices/{id}/review` | Check, edit, remove or add lines of an uploaded invoice before anything is saved |
| More | `/more` | Documents, Mileage history, Your data, appearance, people (admin) |
| Mileage history | `/mileage` | Readings newest first; edit or delete |
| Documents | `/documents` | Uploaded invoices for the car; opened through the app |

### How the parts work

- **Access** (`app/cars.py`): every query goes through `visible_filter(user)` — shared cars plus the user's own "Only me" cars. Anything attached to a car is reached by joining to the car with that filter, so another person's private data is a 404, not a 403. Only the person who added a car can change its visibility; they or the admin delete it.
- **Mileage**: the newest reading by date is the current mileage. Saving a service record with a mileage adds a linked reading (updated or removed with the record).
- **Due soon** (`app/due.py`): an open item is *overdue* when its date has passed or the current mileage reached its due mileage, and *due soon* within 30 days or 500 miles. Loan payoff and warranty-ends items follow the car's loan and the service item's warranty; everything else is entered by hand. Saving a service with an oil change or an inspection closes the open due item of that type.
- **VIN lookup** (`app/nhtsa.py`): only when "Look up" is tapped; calls NHTSA vPIC `DecodeVinValues`. Pages never wait on a third party.
- **Invoice import** (`app/invoice.py`, `app/routes/invoices.py`): the PDF is stored privately, its text extracted with `pypdf` inside the upload request, and parsed for the one supported shop layout (see REQUIREMENTS.md). Only vehicle and job information is kept (encrypted, and only until the review is saved); the customer block and payment history are skipped. The car is matched by the VIN's keyed hash; with no match you pick a car or add one pre-filled from the invoice. A duplicate (same shop and repair order number) warns first. PDFs with no text, or a layout the parser doesn't know, stay attached to the car and open an empty service record. To support another shop, add a parser beside `parse_invoice`.
- **Files** (`app/storage.py`): photos (resized in the browser to 1600 px JPEG, `app/static/js/uploads.js`) and invoice PDFs go to Vercel Blob with private access under random paths; the database keeps only the reference. They are served only by `/cars/{id}/photo` and `/documents/{id}/file`, behind the same access check. Blob failures are logged with the operation, status and Vercel error code only. The admin's **Check file storage** (More) saves, reads back and deletes a test file and shows the result. Set `VERCEL_BLOB_API_URL` to override the API base. On Vercel the app authenticates with OIDC: `BLOB_STORE_ID` plus the `x-vercel-oidc-token` header of the current request (`OidcMiddleware`; `VERCEL_OIDC_TOKEN` also works). Then `BLOB_READ_WRITE_TOKEN` if set; otherwise files go to `.local-storage/`, never on Vercel (saving fails with a clear message instead). Check file storage also shows the method and whether the store ID and OIDC token were found. Vercel limits a request body to 4.5 MB, so a larger invoice can't be uploaded in production even though the app's own limit is 10 MB.
- **Encryption**: VIN, plate, title number, notes (car, service, due, recommended work), loan and uploaded filenames use `EncryptedText` / `EncryptedJSON`. `cars.vin_hash` is `crypto.blind_index(vin)`, an HMAC under a key derived from `TOKEN_ENCRYPTION_KEY`.
- **Audit log**: car added / deleted / visibility changed, invoice uploaded / imported (IDs only).

### Tables

`cars` (facts, visibility, encrypted VIN/plate/notes/loan, photo reference), `user_prefs` (selected car, sort), `car_stars`, `mileage_readings`, `service_records`, `service_items` (with warranty), `due_items` (manual, loan or warranty source), `documents` (invoice PDFs, parsed result until reviewed), `recommended_items`. All cascade from `cars`, which cascades from the user who added it. Your data (`app/exporter.py`) downloads every car the user can see with all of the above, never another person's "Only me" car; deleting an account also deletes the cars that person added and their stored files.

### Environment

As in the template, plus a private Vercel Blob store connected to the project (nothing to copy: Vercel adds `BLOB_STORE_ID` and the app uses OIDC). `BLOB_READ_WRITE_TOKEN` is optional, for local use.

### Tests

`tests/` covers each requirement. The invoice parser is tested on an invented fixture in the documented layout (`tests/invoice_fixture.py`, built with `reportlab`); no real invoice is in the repo. NHTSA and Blob are replaced by mock transports / an in-memory backend. New migrations were generated with `scripts/new_migration.py` (empty SQLite, no Postgres needed).

## From the app template

The rest of this README describes the template this app started from.

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
3. Icons are generated: edit the drawing in `scripts/make_icons.py` and run `uv run python scripts/make_icons.py` (one 1024 px master; the car stays inside the centre 80% so maskable icons work).
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
