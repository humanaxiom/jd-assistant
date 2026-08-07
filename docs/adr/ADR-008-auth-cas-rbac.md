# ADR-008 — Authentication (SFU CAS SSO) + RBAC + server-side sessions

**Status:** Accepted (foundation, wiring, admin UI and the JSON API all landed —
see Rollout; CSRF and the fail-closed startup invariant are tracked separately)
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
   (prev_hash/row_hash + a tail-tracker trigger, ported from HRIS, migration `0005`) so
   auth events and reviewer actions are tamper-**evident**: `verify_audit_chain`
   recomputes the chain and any altered/deleted row flips it to `ok=False`. Tamper-
   **prevention** via Postgres role GRANT/REVOKE is a later hardening step — it needs the
   app to connect as a restricted (non-owner) role.

## Rollout (slices)

- **Phase 1 (foundation) — DONE:** Settings; `cas_service`; migration `0004`
  (`users`/`user_roles`/`sessions`); `session_service` + `user_service`;
  `current_user` / `require_roles`; auth routes + login page + `require_ui_user`.
- **Phase 2 (wiring) — DONE for the UI, and *only* the UI (see phase 4):**
  `require_ui_user` on the Builder/dashboards + `require_ui_roles(reviewer, admin)` on
  the review queue; the review/compose **UI** body `reviewer_id`/`author_id` swapped for
  the authenticated user (`actor.cas_username`); the hash-chained audit (migration
  `0005` + `verify_audit_chain`); a user pill / sign-out in `_base.html`. *(Identity is
  recorded as the CAS username; a hard FK `review_actions.reviewer_id → users.id` was
  left off to avoid persisting the dev-mode synthetic actor — a later refinement, not a
  security gap.)*
- **Phase 3 — DONE:** the user-management admin UI (list / activate-disable / assign
  roles, with self-lockout guards) + first-admin bootstrap via `BOOTSTRAP_ADMINS`.
- **Phase 4 (the JSON API) — DONE (P0.1a, 2026-08-07).** Phase 2 read as though it had
  covered every surface. It had not: the **JSON** routers (`/jd-bank/review`,
  `/jd-bank/compose`) and the legacy harness routes (`/tasks`, `/gates/run`,
  `/memory/similar`) were mounted with **no gate at all**, and the JSON review routes
  still took `reviewer_id` from the request body — which `service.approve` writes into
  the hash-chained `audit_log` as the actor. With `cas_enabled=True` an unauthenticated
  `POST /jd-bank/review/{id}/approve` reached the review *service* and, on a gate-clean
  DRAFT, would have **published** it (NN #1) under a caller-chosen identity the chain
  then attested to intact (NN #6). Recording it as a phase rather than editing phase 2
  green: the gap was real and shipped, and a rollout log that quietly repairs itself is
  worth less than one that says what was missed.
  - review JSON → `require_roles(reviewer, admin)`; compose JSON → `current_user`;
    harness routes → `require_roles(admin)`; `/health` stays public. `require_roles`,
    **not** `require_ui_roles`: an API client must get 401/403, never a 303 to an HTML
    login page.
  - `reviewer_id` **removed** from the approve/reject/edit request models, along with
    `overrides[].reviewer` — a second body-supplied actor on the same audit path. The
    route stamps both from the session. The *service* keeps its `reviewer_id`
    parameter: it is transport-agnostic and correct; only the route may no longer let a
    caller choose it.
  - `tests/unit/test_authorization_matrix.py` is now the table of record: it walks the
    live routing table, so a route added without an access decision fails the build.
  - Still open, deliberately split out: **CSRF** for cookie-authenticated state changes
    (P0.1b) and the **fail-closed startup invariant** (P0.2) — `cas_enabled=False` still
    returns a transient admin before any cookie is read, so these gates only bind when
    CAS is on.

## Alternatives considered

- **Signed stateless cookies (JWT-style).** Simpler (no session table) but no per-session
  revocation and weaker audit — rejected for an HR-approval system.
- **OIDC/SAML instead of CAS.** SFU speaks CAS; adding an IdP shim is needless surface.
- **A permissions table + role→permission map.** More flexible, but net-new design not
  present in HRIS and not justified by three roles over a handful of surfaces.

## Consequences

- The app can require SFU sign-in and attribute every reviewer action to a real user.
- CI/local dev is unaffected: `cas_enabled=False` keeps everything runnable offline.
- Existing routes were **unchanged until phase 2** — the foundation was additive, so it
  landed without touching current behavior or tests. That additiveness is also how the
  JSON API stayed ungated for two further phases without a test noticing; phase 4 closes
  it and pins the whole surface in one table.
- If the app ever needs finer-grained authz than three roles, item 3 is the decision to
  revisit (add a permissions layer), not a reason to avoid RBAC now.
