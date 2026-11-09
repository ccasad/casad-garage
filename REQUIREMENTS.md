# CHANGE ME — Requirements

Last updated CHANGE ME

Written as if this repo is public: no personal names, health or financial details, addresses or real emails.

## Overview and goals

CHANGE ME: a paragraph on what the app does and for whom.

**Goals for version 1**

- CHANGE ME

**Success looks like:** CHANGE ME (one sentence).

## Feature to-do list

- [ ] CHANGE ME

## Users and access

Invite-only: an admin plus the people they invite. No public sign-up.

| Role | Who | Can do |
| --- | --- | --- |
| Admin | The person who runs the app | Invite and remove people, everything a member can do |
| Member | People the admin invites | CHANGE ME |

## Functional requirements

**CHANGE ME (area)**

- **FR-1** CHANGE ME

## Data scope

CHANGE ME: what data the app holds and where it comes from.

## Non-functional requirements

**Security and privacy**

- **NFR-1** All traffic over HTTPS (Vercel default).
- **NFR-2** Third-party tokens are encrypted at rest with a key held only in environment variables.
- **NFR-3** Sensitive records are encrypted at rest.
- **NFR-4** Every database query is scoped to the signed-in user.
- **NFR-5** Request only the third-party scopes needed, read-only.
- **NFR-6** No personal data in logs, URLs or error messages.
- **NFR-7** Sessions expire after 30 minutes idle.
- **NFR-8** An audit log records sign-ins and other sensitive actions.

**Performance**

- **NFR-9** Each request finishes within 60 seconds; long work is split across requests.
- **NFR-10** Pages load from stored data, without calling third parties, in under 2 seconds.

**Cost and operations**

- **NFR-11** Runs on free tiers (Vercel Hobby, Neon Free): $0 a month.
- **NFR-12** Secrets are never committed.
- **NFR-13** A user can download or delete all their data at any time.

## Out of scope and future ideas

- CHANGE ME

## Open questions and risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| CHANGE ME | | |
