# ADR-008 — Authentication (SFU CAS SSO) + RBAC + server-side sessions

**Status:** Accepted (foundation landed; wiring + admin UI in progress)
**Date:** 2026-07-25
**Supersedes the pilot posture:** the free-text `reviewer_id` / `author_id` on each
request ("pilot model, no SSO", HANDOFF.md) is replaced by an authenticated user.

## Context

JD Bank had **no authentication**: the review queue and Builder took a `reviewer_id` /
`author_id` string in the request body. That was fine for a single-operator pilot but is
not acceptable once real HR reviewers approve JDs (NN #1 human approval must attribute to
a real person) or once the app is exposed beyond one machine.

SFU authenticates via **CAS** (`https://cas.sfu.ca/cas`). The HRIS project
(`C:\repos\hris`) already ships CAS SSO + RBAC + a user-admin, all in **FastAPI Python**
(its ADR-0005) — the same server-side stack as this repo — so the *shapes* port directly.
Two adaptations were required: HRIS uses raw asyncpg + hand SQL where we use **SQLAlchemy
ORM + Alembic**, and HRIS's front-gate is Next.js middleware where our UI is
**server-rendered Jinja** (so the gate is a FastAPI dependency, not a JS middleware).

## Decision

1. **CAS v2 SSO.** `cas_service.validate_ticket` performs the `serviceValidate` XML
   round-trip; the route layer runs the redirect dance
   (`/cas/login` → CAS → `/cas/validate` → session). The ticket is a bearer credential
   and is never logged.

2. **Server-side sessions, not signed cookies.** A session is an opaque
   `secrets.token_urlsafe(32)` id in a `sessions` row; the cookie carries only that id.
   Chosen over signed/stateless cookies for **per-session revocation** (logout, and
   revoke-on-disable) and auditability. Sliding-window TTL.

3. **Role-based access, three roles: `author` / `reviewer` / `admin`.** Held
   many-to-many (`user_roles`) so a user can be both reviewer and admin. **No permissions
   table / no role→permission map** — authorization is per-route via
   `require_roles(*roles)` (403 unless the user holds one). This mirrors HRIS; a
   fine-grained permission model is explicitly out of scope (it does not exist in HRIS to
   port and is not needed yet).
   - `author` — use the Builder, submit drafts.
   - `reviewer` — approve/reject/edit/override in the review queue (the NN #1 surface).
   - `admin` — manage users.

4. **Identity is CAS.** `users` has **no password hash**; a user is keyed by
   `cas_username` and provisioned on first login (`provision_or_get`, race-safe) with a
   configurable default role (`default_new_user_role`, ships `author` — the
   least-privileged useful role; nothing publishes without a reviewer, NN #1).

5. **Dev/CI escape hatch.** `cas_enabled=False` (the default) makes every request a
   synthetic anonymous user with a configurable role — so the app runs, and `make gates`
   passes, **without ever reaching `cas.sfu.ca`** (ADR-003's "nothing on the gates path
   hits a live endpoint" rule extends to CAS). `cas_dev_fake_user` exercises the full
   cookie/session machinery locally without the SFU round-trip.

6. **UI gate is a redirect, not a 401.** `require_ui_user` bounces an unauthenticated
   browser to `/login` (via a `RedirectToLogin` handler); JSON API routes get a 401 from
   `current_user`. Transparent in dev mode.

7. **Auth config is ops/security, not a rulebook decision.** It changes no JD's score, so
   it lives in `Settings` (like the egress guard), **not** in `jd_core/rules/` or the HR
   decision register.

8. **Tamper-evident audit.** The existing append-only `audit_log` gains a hash chain
   (prev_hash/row_hash + a tail-tracker trigger, ported from HRIS) so auth events and
   reviewer actions are tamper-**evident**. *(Landing in phase 2, when actions are wired
   through it; tamper-**prevention** via Postgres role GRANT/REVOKE is a later hardening
   step — it needs the app to connect as a restricted role.)*

## Rollout (slices)

- **Phase 1 (foundation) — DONE:** Settings; `cas_service`; migration `0004`
  (`users`/`user_roles`/`sessions`); `session_service` + `user_service`;
  `current_user` / `require_roles`; auth routes + login page + `require_ui_user`.
- **Phase 2 (wiring) — next:** apply `require_ui_user` to the UI routers; swap
  `reviewer_id`/`author_id` for the resolved `CurrentUser` (FK `review_actions.reviewer_id`
  / `audit_log.actor` → `users`); gate the review queue to `reviewer`/`admin`; the
  hash-chained audit + a user pill / sign-out in `_base.html`.
- **Phase 3 (later):** the user-management admin UI (list / activate-disable / assign
  roles, with self-lockout guards) + a first-admin bootstrap (seed or script).

## Alternatives considered

- **Signed stateless cookies (JWT-style).** Simpler (no session table) but no per-session
  revocation and weaker audit — rejected for an HR-approval system.
- **OIDC/SAML instead of CAS.** SFU speaks CAS; adding an IdP shim is needless surface.
- **A permissions table + role→permission map.** More flexible, but net-new design not
  present in HRIS and not justified by three roles over a handful of surfaces.

## Consequences

- The app can require SFU sign-in and attribute every reviewer action to a real user.
- CI/local dev is unaffected: `cas_enabled=False` keeps everything runnable offline.
- Existing routes are **unchanged until phase 2** — the foundation is additive, so it
  lands without touching current behavior or tests.
- If the app ever needs finer-grained authz than three roles, item 3 is the decision to
  revisit (add a permissions layer), not a reason to avoid RBAC now.
