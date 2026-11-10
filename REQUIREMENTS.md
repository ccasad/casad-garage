# Casad Garage — Requirements

Last updated 2026-11-09

Written as if this repo is public: no personal names, health or financial details, addresses or real emails.

## Overview and goals

Casad Garage is a shared garage for a household. It keeps everything about each car in one place: the car's facts (VIN, year, make, model, trim, color, plate, a photo), dated mileage readings, service history, upcoming due dates (registration, inspections, loan payoff, warranty ends), and work a shop recommended that hasn't been done yet. Car details fill in from the VIN using the free NHTSA lookup, and service records can be imported from a shop's PDF invoice instead of typed in. Everyone in the household sees the shared cars; any car can be marked private to the person who added it. The app is organised around one selected car at a time, chosen from a car selector at the top of every page.

**Goals for version 1**

- See every car at a glance and open any car for its full history.
- Log every service with date, mileage and cost.
- Know what's due soon without keeping a separate notes app.
- Import a shop invoice PDF, including the declined jobs, instead of typing it.

**Success looks like:** after a month, every service is logged and the app shows what's coming up for each car.

## Feature to-do list

- [x] Cars: add, edit, delete; car selector with remembered car; Overview tab; All cars view (FR-1, FR-3 to FR-6)
- [x] Color and car photo (FR-1, FR-7)
- [x] VIN lookup through NHTSA (FR-2)
- [x] Mileage readings (FR-10, FR-11)
- [x] Service records, typed in (FR-12 to FR-14)
- [x] Due dates and "Due soon" (FR-15 to FR-17)
- [x] Private cars ("Only me") (FR-8)
- [x] Starred cars and sorting (FR-9)
- [x] Invoice PDF upload, parsing and review (FR-18 to FR-23)
- [x] Recommended work from declined jobs (FR-24 to FR-26)
- [x] Warranties (FR-27)
- [x] Loan payoff (FR-28)
- [x] The app's own car icon (NFR-17)
- [x] Fix uploads to Vercel Blob, show upload errors, log Blob failures (FR-7, FR-18, NFR-18)
- [x] Check file storage button for the admin (FR-29)
- [x] Reach the private Blob store with OIDC; Check file storage reports the method (FR-7, FR-18, FR-29, NFR-14)
- [x] Put the star and Edit buttons on the photo row so the car name uses the full width (FR-4)
- [x] Title number on cars (FR-1)
- [x] Do-it-yourself services: Done by Shop / Myself (FR-12, FR-13)
- [x] Brand and part number on service items (FR-12, FR-13)
- [x] Accept pre-1981 VINs: form, Look up and invoice matching (FR-1, FR-2, FR-20)
- [x] Hide the phone tab bar while typing and leave room for the keyboard (NFR-19)
- [x] Fix invoice upload losing the PDF on iPhone: service worker handles only GET navigations (cache `offline-v2`), upload with fetch, friendly form errors (FR-18, NFR-20)
- [x] Read declined jobs that come after the payment history (FR-19)

## Users and access

Invite-only: an admin plus the people they invite. No public sign-up.

| Role | Who | Can do |
| --- | --- | --- |
| Admin | The person who runs the app | Invite and remove people; delete any car; everything a member can do |
| Member | Household members the admin invites | See and edit all shared cars; add cars; mark cars they added as "Only me"; delete cars they added |

## Screens

- **Car selector** at the top right of every page (FR-3).
- **Tabs for the selected car:** Overview, Service, Due, To do. **More** holds Documents, Mileage history and the template's standard settings (appearance, your data, people for the admin).
- **All cars** view, reached from the top of the car selector (FR-4).
- Laptop layout: the same tabs in the template's sidebar, with the car selector in the top bar.

## Functional requirements

**Cars**

- **FR-1** A user adds a car with year, make and model (required) and optional nickname, VIN, trim, engine, color, plate, VIN (a modern 17-character VIN, letters and digits without I, O or Q; or a pre-1981 VIN of 5 to 16 letters and digits, any letters; spaces and dashes are removed and it is stored upper-case; otherwise the form says "Enter a 17-character VIN, or the car's original VIN if it's from before 1981 (5 to 16 letters and numbers)."; stored encrypted whatever its length), title number (up to 40 characters, stored encrypted like the plate, shown on the Overview tab after Plate and included in the data download) and notes. The car appears in the car selector and becomes the selected car.
- **FR-2** On the add/edit form, the user enters a VIN and taps **Look up**; the app calls the NHTSA vPIC decode service and fills year, make, model, trim and engine. Every filled field stays editable. If the lookup fails or returns nothing, the app says so and the user types the details. Look up only works for 17-character VINs: for a shorter VIN the button is disabled, the form shows "Pre-1981 VIN: enter the year, make and model yourself." under the field (replacing the generic error), and the server endpoint returns that message without calling NHTSA.
- **FR-3** A car selector sits at the top right of every page. It lists the cars the user can see (in their star and sort order, FR-9), with a dot on any car that has items due soon, an "All cars" entry at the top, and "+ Add a car" at the bottom. Choosing a car makes it the selected car, and the tabs show that car. The app remembers the last selected car per user and opens on it; only when there is none (first visit, or that car was deleted or made private) does the page say "Pick a car above".
- **FR-4** The tabs act on the selected car: Overview (photo, then one row with the photo button on the left and the star button and Edit link on the right, then the full-width car name, facts, current mileage, "last done" per service type), Service (history, with + to log a service or upload an invoice), Due (its due items), To do (its recommended work). "All cars" shows every visible car as a card (photo, name, trim, color, current mileage, and its due-soon items); tapping a card selects that car.
- **FR-5** A user edits any field of a car they can see.
- **FR-6** The person who added a car, or the admin, deletes it after confirming; its records, documents and photo are deleted with it. Other members don't see a delete option.
- **FR-7** A user adds or replaces one photo per car from the phone's camera or library. The photo is resized in the browser before upload (longest side 1600 px, JPEG) and shown on the Overview tab and on the car's card in All cars. Cars without a photo show a placeholder. When an upload fails, the page shows the server's reason (for example "The photo is too large."), not a generic message.
- **FR-8** Each car is **Shared** (default) or **Only me**. Only the person who added a car can change this. An "Only me" car, and everything attached to it, is never shown to anyone else, including in their data download.
- **FR-9** Each user can star cars. In that user's car selector and All cars view, starred cars come first; the rest follow their chosen sort (name, year, or most recently serviced), which the app remembers per user. Stars and sort are personal: one person's choices don't change anyone else's list.

**Mileage**

- **FR-10** A user adds a mileage reading (date, miles) to a car. The newest reading by date is the car's current mileage; Mileage history (under More) lists past readings, newest first, and a reading can be edited or deleted.
- **FR-11** Saving a service record or an imported invoice adds its odometer reading automatically.

**Service records**

- **FR-12** A user adds a service record: date, mileage, who did it (**Done by: Shop / Myself**, default Shop), shop and repair order number (Shop only), one or more items (description, type, optional brand up to 120 characters, optional part number up to 60 characters, cost), total cost and notes. **Myself** hides the shop and repair-order fields and records the signed-in user as the person who did it (`done_by` `shop`/`self`, `done_by_user_id` set null if that user is deleted). Imported invoices and existing records are Shop. The existing `part` column holds the brand. Types: oil change, tires, alignment, brakes, engine air filter, cabin air filter, battery, fluids, state inspection, emissions inspection, other.
- **FR-13** The Service tab lists the car's records newest first, with a filter by type and a text search (also matching brand and part number). Records done by Myself show a small DIY tag and "by <display name>" (or "by a former member") instead of the shop; the record page shows the same. Tapping a record shows its items and lets the user edit or delete it.
- **FR-14** The Overview tab shows the last date and mileage for each service type that has been done (e.g. "Cabin filter: Feb 2026, 52,100 mi").

**Due dates**

- **FR-15** A user adds a due item to a car: type (registration, state inspection, emissions inspection, oil change, loan payoff, warranty ends, other), a due date and/or a due mileage, and notes.
- **FR-16** When a user saves a service item of type state inspection, emissions inspection or oil change, the app offers to set the next due date or mileage for it, and closes any open due item of the same type on that car.
- **FR-17** An item is **due soon** when it is overdue, due within 30 days, or within 500 miles of the car's current mileage. The Due tab lists the selected car's items soonest first with due-soon and overdue ones highlighted; All cars shows each car's due-soon items. A user marks an item done or edits it.

**Invoice import**

- **FR-18** From the Service tab, a user uploads a PDF invoice (up to 10 MB). The original is stored and listed under Documents for that car, where it can be opened. Uploads to the private Blob store match the official `@vercel/blob` client's requests exactly, and a failed invoice upload shows the reason. Picking a PDF sends it from page script with `fetch()` and `FormData` (fields `invoice` and `car_id`), like the photo upload: "Uploading…" shows in a status line next to the button, the button is disabled while it runs, and on success the page follows the `next` URL. For script requests (`Accept: application/json`) `POST /invoices` answers JSON `{"next": "/invoices/<id>/review"}` (or the manual-entry page), and on failure a 4xx JSON `{"detail": "<reason>"}` such as "That PDF is larger than 10 MB."; a plain form post still gets the 303 redirect, so the form works with JavaScript off. On Vercel the Blob backend authenticates with OIDC: `BLOB_STORE_ID` plus the Vercel OIDC token of the current request (the `x-vercel-oidc-token` header, or `VERCEL_OIDC_TOKEN` when set). Order: OIDC first; then `BLOB_READ_WRITE_TOKEN` if set (local development, or a store connected the older way); otherwise the local folder, and only when not running on Vercel (`VERCEL` unset). On Vercel with no usable credentials, saving fails with "File storage isn't connected: no BLOB_STORE_ID / OIDC token". Reading private blobs (photo, Documents) uses the same authentication.
- **FR-19** The app reads the PDF's text and, for the supported shop invoice layout (below), extracts: repair order number, date, shop name, VIN, odometer, each job with its title, status (approved or declined), notes and price, and the grand total.
- **FR-20** The app matches the invoice to a car by VIN (the invoice's `VIN:` line accepts 5 to 17 letters and digits; matching uses the same normalised value and keyed hash as the car form); if no visible car matches, it asks which car, or offers to add a new one pre-filled from the invoice's vehicle line.
- **FR-21** Before anything is saved, a review screen shows the service record (approved jobs) and the declined jobs; the user edits, removes or adds lines, then saves.
- **FR-22** If the PDF has no readable text or the layout isn't recognised, the app says so, keeps the file attached to the car, and opens an empty service record to fill in by hand.
- **FR-23** Importing an invoice whose shop and repair order number already exist warns before saving a duplicate.

Supported layout (one shop's invoice system; a text PDF, two or more pages):

- Header: `Invoice for RO #<number>`, `Posted Date: MM/DD/YY at ...`, `Vehicle: <year> <make> <model> <trim>`, a `VIN: <17 chars>` line, and `Odometer In: <n> / Out: <n>`. The shop's name, address and phone are the first lines.
- Jobs: numbered lines `<n> - <TITLE>`, sometimes followed by `**<shop note>**` on the same line and a `Note: ...` paragraph. Each job ends with a status line `✓ Approved on <date>` or `✓ Authorized on <date>` and its total on the right.
- A `Declined Jobs:` section lists more numbered jobs in the same form, each with `✘ Declined on <date>` and a total (sometimes `Subtotal $x + est. Tax $y   $total`; use the final amount).
- `Grand Total: $<amount>` near the end of page 1.
- Page 1 ends with the `Payment History` table and the page footer; page 2 starts with `Declined Jobs:`. Every line from `Payment History` until a `Declined Jobs` line (or the end) is skipped, so declined jobs that come after the payment history are still read.
- The customer block (name, address, phone, email) and the `Payment History` table are ignored and never stored.

**Recommended work**

- **FR-24** Declined jobs from an imported invoice become recommended work items on the car: description, the shop's note, quoted price, and the date and mileage recommended. A user can also add one by hand.
- **FR-25** The To do tab lists the selected car's open items with their total quoted cost, for planning the next shop visit.
- **FR-26** A user marks a recommended item done (optionally linking the service record that did it) or dismisses it; closed items stay in a collapsed history.

**Warranties and loan**

- **FR-27** A service item can carry a warranty in months and/or miles (e.g. a battery with 36 months). The app works out the end date and adds a "warranty ends" due item.
- **FR-28** A car can have a loan: lender, final payment date and an optional monthly amount. The final payment date shows as a due item.
- **FR-29** On the admin's page under More, a **Check file storage** button saves a tiny test file to the store, reads it back, compares it, deletes it, and shows "File storage works" or the failing step with the status code and error code. It also shows which backend is active and method ("Vercel Blob via OIDC", "Vercel Blob via read-write token" or "Local folder") and whether `BLOB_STORE_ID` and an OIDC token were found, never their values. Admin only; each check is recorded in the audit log.

## Data scope

All data is typed in by users, decoded from the VIN by the free NHTSA vPIC service (no key, read-only), or extracted from PDF invoices users upload.

- **Cars:** nickname, VIN, year, make, model, trim, engine, color, plate, notes, visibility, who added it, photo.
- **Per user:** starred cars, sort choice, last selected car.
- **Mileage readings:** date and miles.
- **Service records and items:** date, mileage, shop, repair order number, items, types, parts, costs, warranty.
- **Due items, recommended work items, loan.**
- **Files:** car photos and invoice PDFs, in Vercel Blob; the database keeps only references.

**Sensitive, encrypted at rest:** VIN, plate, loan details and notes. Invoice PDFs contain the owner's name, address, phone and payment details, so they are stored privately and served only through the app to users who can see the car. When parsing, the app keeps only vehicle and job information and discards customer contact and payment details. Matching by VIN works on a keyed hash of the VIN, so the plain VIN never has to be stored unencrypted.

## Non-functional requirements

**Security and privacy**

- **NFR-1** All traffic over HTTPS (Vercel default).
- **NFR-2** Third-party tokens are encrypted at rest with a key held only in environment variables.
- **NFR-3** Sensitive records are encrypted at rest.
- **NFR-4** Every database query is scoped to what the signed-in user may see: shared cars plus their own "Only me" cars.
- **NFR-5** Request only the third-party scopes needed, read-only.
- **NFR-6** No personal data in logs, URLs or error messages.
- **NFR-7** Sessions expire after 30 minutes idle.
- **NFR-8** An audit log records sign-ins and other sensitive actions (including car deletes and visibility changes).
- **NFR-14** Uploaded files are never reachable by a public URL; downloads go through the app's access check. The store is private and the app reaches it with OIDC (no stored secret needed).
- **NFR-15** Tests use only invented fixtures (fake VIN, names and shop details); no real invoice is ever committed.

**Performance**

- **NFR-9** Each request finishes within 60 seconds; long work is split across requests.
- **NFR-10** Pages load from stored data, without calling third parties, in under 2 seconds.
- **NFR-16** Parsing an invoice PDF finishes within the upload request (text extraction only, no image processing on the server).
- **NFR-18** When a Blob request fails, the server logs the operation (put/get/delete), the HTTP status and Vercel's error `code` from the response body, with no file contents, tokens, paths or personal data.
- **NFR-19** On the phone layout, while a text input, select or textarea has focus the bottom tab bar is hidden (a `keyboard-open` class on `<body>`, set on `focusin` and removed on `focusout` after a short delay so moving between fields doesn't flicker), and it returns when no field has focus. This works on every form with no per-page code; the laptop sidebar is unchanged. Pages keep enough bottom padding (including `env(safe-area-inset-bottom)`) that the last field and the Save button can scroll into view above the keyboard.
- **NFR-20** Validation errors (422) on HTML form posts render a friendly page ("Something was missing from the form. Please try again.") with a link back, instead of raw JSON. Clients that accept JSON still get JSON.
- **NFR-17** The app has its own icon: a simple white car seen from the side, flat and bold, on a solid background (hue = (sum of the slug's character codes × 47) mod 360, saturation 55%, lightness 42%). It replaces every icon the template shipped: each file under `icons` in the manifest, the `apple-touch-icon` and the favicon, keeping file names, sizes and formats. Icons are full-bleed squares with the car inside the central 80% (safe for maskable icons; manifest icons are `"any maskable"`). They are generated by `scripts/make_icons.py` (Pillow, dev dependency) from one 1024 px master, and the car stays recognisable at 32 px and 180 px.

**Cost and operations**

- **NFR-11** Runs on free tiers (Vercel Hobby, Neon Free, Vercel Blob free allowance): $0 a month.
- **NFR-12** Secrets are never committed.
- **NFR-13** A user can download or delete all their data at any time.

## Out of scope and future ideas

- AI extraction of any document layout; reading photos or scans of paper invoices (OCR).
- Invoice layouts from other shops (add one parser per shop later).
- Push notifications or email reminders (v1 uses "Due soon" and the selector dots).
- Factory maintenance schedules.
- Fuel economy tracking, cost charts, cars being considered for purchase.
- More than one photo per car; attaching other document types.
- Working offline.
- Decoding pre-1981 VINs (maker-specific formats).

## Open questions and risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| The shop changes its invoice layout | Imports stop extracting | Fall back to manual entry (FR-22); parser covered by tests on an invented fixture in the documented layout |
| NHTSA returns no trim, or is down | Fields stay empty | All fields editable; lookup is optional |
| Vercel Blob must be enabled for the project | Photo and invoice uploads fail until it is | Manual step: create a Blob store and connect it to the project; the builder stubs storage until then |
| Private Blob access | A public Blob URL could expose an invoice | Use private Blob access or unguessable paths served only through the app (NFR-14) |
