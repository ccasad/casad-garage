# Build log

## Done
- Cars: add, edit, delete; car selector with remembered car; Overview tab; All cars view (FR-1, FR-3 to FR-6) — Add, edit and delete cars with a car selector, Overview and All cars
- Color and car photo (FR-1, FR-7) — Add car color and a resized, privately stored car photo (FR-1, FR-7)
- VIN lookup through NHTSA (FR-2) — Fill car details from the VIN with the NHTSA lookup (FR-2)
- Mileage readings (FR-10, FR-11) — Add mileage readings and the car's current mileage (FR-10); FR-11's automatic reading came with service records
- Service records, typed in (FR-12 to FR-14) — Log, list, search, edit and delete service records (FR-11 to FR-14)
- Due dates and "Due soon" (FR-15 to FR-17) — Add due items, the Due tab and Due soon markers (FR-15 to FR-17)
- Private cars ("Only me") (FR-8) — Let the person who added a car mark it Only me, with audit and export scoping (FR-8)
- Starred cars and sorting (FR-9) — Add personal car stars and sort order (FR-9)
- Invoice PDF upload, parsing and review (FR-18 to FR-23) — Upload invoice PDFs, read them and review before saving, with duplicate warning (FR-18 to FR-23, FR-24 creation)
- Recommended work from declined jobs (FR-24 to FR-26) — Add the To do tab for recommended work (FR-24 to FR-26)
- Warranties (FR-27) — Work out warranty end dates and add warranty-ends due items (FR-27)
- Loan payoff (FR-28) — Add an encrypted car loan with its payoff date as a due item (FR-28)

## Next
- Nothing: every item in the version 1 to-do list is built and ticked.

## Decisions
- Navigation tabs act on the user's remembered selected car (stored per user in user_prefs), so tab URLs have no car id.
- Added crypto.blind_index (HMAC-SHA256 under a key derived from TOKEN_ENCRYPTION_KEY) for VIN matching (spec: keyed hash of the VIN).
- An admin can delete any car they can see; a member's 'Only me' car is not visible to the admin either (FR-8 over the role table).
- Migrations are generated with scripts/new_migration.py (empty SQLite, as the task describes).
- Without BLOB_READ_WRITE_TOKEN, files are stored in a local folder (.local-storage, gitignored). Vercel Blob is used with private access when the token is set; its REST calls follow the @vercel/blob SDK source and could not be exercised here.
- VIN look-up overwrites year, make, model, trim and engine with what NHTSA returns (when it returns a value) and leaves everything else as typed.
- A service record needs at least one item; its total defaults to the sum of the item costs when left blank. Saving a record with a mileage adds/updates a linked mileage reading (FR-11) that is removed with the record.
- Open due items of the same type are closed automatically when a service record with an oil change or state/emissions inspection item is first saved; the 'set the next due' offer appears on the record page right after saving (pre-filled: +12 months for inspections, +6 months and +5,000 mi for oil changes, editable).
- Today's date for 'due soon' is the server's UTC date.
- Data download: includes every car the user can see (their own, including 'Only me', plus shared ones) with its records; it never includes another person's 'Only me' car. Deleting an account also deletes the cars that person added, shared or not.
- Sort choices are Name, Year (newest first) and Recently serviced (never-serviced cars last); starred cars always come first.
- Invoice parser: shop name is the first line of the text; job totals are read from the status line or the line right after it; the posted date and odometer-in become the record's date and mileage; a job's shop note and Note paragraph go to the record notes (approved) or the recommended item's note (declined). It was only exercised on an invented fixture in the documented layout, built with reportlab (dev dependency); real PDFs may extract differently.
- Uploads: the server accepts PDFs up to 10 MB, but Vercel caps serverless request bodies at 4.5 MB, so larger invoices will be refused on Hobby (photos are resized to stay well under).
- An uploaded invoice that matches no visible car is visible only to its uploader until a car is chosen; the parsed data is kept (encrypted) only until the review is saved. Uploaded filenames are stored encrypted.
- If every job on an invoice was declined, saving the review adds only recommended-work items and the odometer reading (no empty service record).
- Recommended work: the To do tab total sums quoted prices of open items (items without a price are counted separately). Dismissed or done items can be reopened from the collapsed history.
- Warranty: each service item can carry months and/or miles; the app keeps one 'warranty ends' due item per such item (end date = service date + months, clamped to month end; end mileage = service mileage + warranty miles). These items follow the service record: they can be marked done but not edited or deleted on the Due tab.
- Loan: stored encrypted on the car (lender, final date, monthly amount); the final payment date is also kept as a plain 'loan payoff' due item (the app needs to sort and flag it), which follows the car's loan and can be marked done but not edited on the Due tab.
- Fixture and sample data in tests are invented (shop 'Example Auto Care', make 'Acme', VIN 1A4AA11AA1A111111); nothing from the private notes is in the repo.

- Icon colour comes from the slug (`casad-garage`): hue 176 → #30a69e. The favicon and header logo use the SVG, drawn from the same shapes as the PNGs. All manifest icons are "any maskable" since the art is full-bleed with a safe zone.

- Blob client (FR-7, FR-18): kept hand-written HTTP rather than adding the Python `vercel` SDK (no network here to check it installs cleanly, and it adds a dependency to a one-function deploy). Requests were aligned to the `@vercel/blob` client as recalled from its source: `PUT {api}/?pathname=` (trailing slash), `POST {api}/delete`, `GET` of the blob URL with the bearer token, `x-api-version` 13, `x-vercel-blob-access: private`, `x-add-random-suffix`, `x-content-type`; `VERCEL_BLOB_API_URL` overrides the base. The SDK source could not be fetched here, so the exact version is unconfirmed; use Check file storage (More, as admin) to verify.
- Blob failures log only the operation, HTTP status and Vercel's error code (NFR-18); the Check file storage page (FR-29) shows the same status and code.
- An invoice upload failure redirects with a fixed notice code (never text from the URL), so the reason shown comes from the app.

- OIDC Blob (003): the Python `vercel` SDK couldn't be installed or inspected here (no network), so the hand-written client was extended: bearer = the request's OIDC token (`x-vercel-oidc-token` header via `OidcMiddleware`, else `VERCEL_OIDC_TOKEN`) plus an `x-vercel-blob-store-id` header; all other requests unchanged. The store-ID header name is unconfirmed against the SDK source; run More > Check file storage after deploy, whose status and error code say if it's wrong. Order: OIDC, read-write token, local folder (never on Vercel).

- 005 (title, DIY, brand): the existing `service_items.part` column now holds the brand (label changed, no rename) and `part_number` is new. `done_by` defaults to shop (server default) so old records are Shop. Editing a DIY record keeps its original person; switching a record to Shop clears it; invoice imports force Shop. The data download names the item field `brand` (was `part`) and adds `part_number`, `done_by`, `title_number`.

## Needs a human
- Connect a Vercel Blob store with private access to the project (adds BLOB_STORE_ID; OIDC is used, no token to copy) so photo and invoice uploads work in production. The Blob client in app/storage.py was written from the SDK source without a live store, so after connecting, run More > Check file storage as admin. If it fails, its status and error code say why.
- Try the invoice import with one real invoice. The parser was only tested on an invented fixture in the documented layout; if the real PDF's text comes out differently the upload still works (the file is kept and an empty record opens), but the parser in app/invoice.py may need adjusting.

## Changes
- 001-car-icon: the app has its own white-car icon on a slug-derived colour, generated by `scripts/make_icons.py` (NFR-17)
- 002-fix-uploads: Blob requests match the official client, upload errors show the server's reason, Blob failures are logged, admin Check file storage (FR-7, FR-18, FR-29, NFR-18)
- 003-blob-oidc: the Blob backend authenticates with OIDC (store ID + request OIDC token), Check file storage reports the method (FR-7, FR-18, FR-29, NFR-14)
- 004-overview-buttons: star and Edit buttons moved onto the photo row; the car name uses the full width and wraps (FR-4)
- 005-title-diy-parts: car title number, Done by Shop / Myself with a DIY tag, and separate brand and part number on service items (FR-1, FR-12, FR-13)
