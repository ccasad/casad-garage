# Build log

## Done
- Cars: add, edit, delete; car selector with remembered car; Overview tab; All cars view (FR-1, FR-3 to FR-6) — Add, edit and delete cars; car selector; Overview and All cars (FR-1, FR-3 to FR-6)
- Color and car photo (FR-1, FR-7) — Color and car photo (FR-1, FR-7)
- VIN lookup through NHTSA (FR-2) — VIN lookup through NHTSA (FR-2)
- Mileage readings (FR-10, FR-11) — Mileage readings (FR-10, FR-11 for the readings themselves; the automatic reading from service records arrives with service records)
- Service records, typed in (FR-12 to FR-14) — Service records, typed in (FR-11 to FR-14)
- Due dates and "Due soon" (FR-15 to FR-17) — Due dates and "Due soon" (FR-15 to FR-17)
- Private cars ("Only me") (FR-8) — Private cars ("Only me") (FR-8)
- Starred cars and sorting (FR-9) — Starred cars and sorting (FR-9)
- Invoice PDF upload, parsing and review (FR-18 to FR-23) — Invoice PDF upload, parsing and review (FR-18 to FR-23)
- Recommended work from declined jobs (FR-24 to FR-26) — Recommended work from declined jobs (FR-24 to FR-26)
- Warranties (FR-27) — Warranties (FR-27)
- Loan payoff (FR-28) — Loan payoff (FR-28)

## Next

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

## Needs a human
- Create a Vercel Blob store and connect it to the project (adds BLOB_READ_WRITE_TOKEN) so photo and invoice uploads work in production. The Blob client in app/storage.py was written from the SDK source without a live store, so try one photo upload after connecting.
