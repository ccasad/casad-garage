# Build log

## Done
- Cars: add, edit, delete; car selector with remembered car; Overview tab; All cars view (FR-1, FR-3 to FR-6) — Add, edit and delete cars; car selector; Overview and All cars (FR-1, FR-3 to FR-6)
- Color and car photo (FR-1, FR-7) — Color and car photo (FR-1, FR-7)

## Next
- VIN lookup through NHTSA (FR-2)
- Mileage readings (FR-10, FR-11)
- Service records, typed in (FR-12 to FR-14)
- Due dates and "Due soon" (FR-15 to FR-17)
- Private cars ("Only me") (FR-8)
- Starred cars and sorting (FR-9)
- Invoice PDF upload, parsing and review (FR-18 to FR-23)
- Recommended work from declined jobs (FR-24 to FR-26)
- Warranties (FR-27)
- Loan payoff (FR-28)

## Decisions
- Navigation tabs act on the user's remembered selected car (stored per user in user_prefs), so tab URLs have no car id.
- Added crypto.blind_index (HMAC-SHA256 under a key derived from TOKEN_ENCRYPTION_KEY) for VIN matching (spec: keyed hash of the VIN).
- An admin can delete any car they can see; a member's 'Only me' car is not visible to the admin either (FR-8 over the role table).
- Migrations are generated with scripts/new_migration.py (empty SQLite, as the task describes).
- Without BLOB_READ_WRITE_TOKEN, files are stored in a local folder (.local-storage, gitignored). Vercel Blob is used with private access when the token is set; its REST calls follow the @vercel/blob SDK source and could not be exercised here.

## Needs a human
- Create a Vercel Blob store and connect it to the project (adds BLOB_READ_WRITE_TOKEN) so photo and invoice uploads work in production. The Blob client in app/storage.py was written from the SDK source without a live store, so try one photo upload after connecting.
