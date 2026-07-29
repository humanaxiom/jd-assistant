# JD Bank — Operator & User Guide

A practical guide to running and using JD Bank: what the system is, who does what, every
feature, and exactly where **admin rights** (or server/operator access) are required.

> A **standalone visual version** of this guide (SFU-branded, print-friendly, single file)
> lives next to this one at [`operator-guide.html`](operator-guide.html) — open it in a
> browser or hand it to non-technical staff. Keep the two in sync when either changes.

> **Legend used throughout**
> - **[any]** — any signed-in user
> - **[author]** — a user holding the `author` role
> - **[reviewer]** — a user holding the `reviewer` role
> - **[admin]** 🔑 — a user holding the `admin` role (app-level)
> - **[operator]** 🖥️ — shell + Docker access on the server (deploy/ops), **not** an app
>   role. The app `admin` role and operator access are **different things** (see §3).

---

## 1. What JD Bank is

JD Bank turns SFU's sprawling job-description archive into a clean, governed source of
truth, and helps staff **author new, standards-compliant JDs**. Two halves:

- **The pipeline (back office).** Every JD in the archive is parsed, de-duplicated
  (exact / near-duplicate / role-equivalent), clustered by role, and harmonized into one
  **draft canonical JD** per role — scored against SFU's published standards by a
  deterministic validator. This runs on the server via `make` tasks (§7).
- **The app (front office).** A web UI at **http://localhost:25800** (dev) where people
  **compose** a JD with live compliance feedback, **review & approve** drafts, browse
  **dashboards**, and (admins) **manage users**.

**Four guardrails the whole system is built on** — operators must not work around these:

1. **Nothing auto-publishes.** A canonical JD is a *draft* until a human **reviewer**
   explicitly approves it. Overriding a blocking gate requires a written reason, recorded.
2. **Self-hosted inference only.** All LLM/embedding calls go to SFU-controlled Ollama
   (`aria-gb10-2`). No JD text ever goes to a cloud/vendor API — this is build-enforced.
3. **The validator is the oracle.** Scores/approvability come from the rulebook validator,
   never from the LLM's own claims about its output.
4. **Append-only, tamper-evident audit.** Every review/approve/edit and every login is
   recorded in a hash-chained `audit_log` (alteration or deletion is detectable, §7).

---

## 2. Personas & roles

The app has **three roles**, held in any combination (a person can be both reviewer and
admin). Roles are assigned in the **User management** screen (§6, admin-only).

| Persona | Role | Can do |
|---|---|---|
| Hiring manager / recruiter | **author** | Use the Builder: search/clone, author, get LLM assist, export `.docx`, submit a draft to the review queue. Browse dashboards. |
| HR reviewer | **reviewer** | Everything an author can, **plus** open the review queue and **approve / reject / edit / override** drafts (the human-approval gate). |
| System administrator | **admin** 🔑 | Everything above, **plus** manage users (assign roles, enable/disable accounts). |
| System operator / DevOps | **[operator]** 🖥️ | Run the data pipelines, migrations, deploys, and CAS configuration from the server shell. This is **infrastructure access**, not an app role. |

> New users are provisioned as **author** on their first sign-in. Reviewer and admin are
> granted deliberately by an admin. A person can be an app **admin** without server
> **operator** access, and vice-versa.

---

## 3. Access & sign-in

- **URL:** http://localhost:25800 (dev). Every UI page lives under `/jd-bank/ui/…`.
- **Sign-in:** SFU **CAS SSO**. Click **Sign in with SFU CAS** on the login page; you are
  redirected to `cas.sfu.ca` and back. Your identity is your SFU computing ID.
- **The nav bar** shows who you are and your primary controls: **🧱 Builder ·
  📋 Review queue · 📊 Dashboards · 👤 Users** *(admins only)* · *your name* ·
  **Sign out**. The **👤 Users** link only appears if you hold the `admin` role.
- **Dev / CI mode** **[operator]** 🖥️: when `CAS_ENABLED=false` (the default off-SFU),
  every request runs as a synthetic **admin** user with no login — so the app is usable
  and testable without reaching CAS. Turn this **off in production** (`CAS_ENABLED=true`).
- **First-admin bootstrap** **[operator]** 🖥️: set `BOOTSTRAP_ADMINS=<your-cas-id>` (comma-
  separated) before first login; those users are granted **admin** automatically on every
  login. This is how the very first administrator is created — after that, admins manage
  everyone else in the UI.

---

## 4. Authoring a JD — the Builder  ·  [author] (any signed-in user)

**Where:** 🧱 Builder → `/jd-bank/ui/compose/new`. **Who:** any signed-in user (authors by
default). **Admin required:** no.

| Task | How | Notes |
|---|---|---|
| Start from an existing JD | **🔎 Search to clone** → pick a match → *Start from this* | Semantic search over the archive (JDFN scope; CUPE/WJQ excluded). The form pre-fills; edit from there. |
| Author from scratch | Fill the guided questions, then **Check compliance** | Live panel shows the score, grade, blocking gates, "Still to write" and "Fix these" — each finding links straight to the section that needs it. |
| Improve the summary with AI | **✨ Improve summary (assist)** | A self-hosted LLM suggests a better Position Summary; you review and edit it (nothing auto-applies). |
| Download the official document | **Export .docx ↓** | Renders the SFU `.docx`. Rendering only — nothing is validated or published. |
| Send for approval | **Submit for review →** | Persists a **draft** into the review queue, attributed to **you** (the signed-in user). It publishes nothing (guardrail #1). |

> **Scope:** the Builder authors **JDFN** roles (APSA / APEX / Polytechnic) only. CUPE
> roles use a different instrument (WJQ) with no ratified quality bar yet, so they are
> deliberately not authorable — see the HR decision register (HR-143 / HR-194).

---

## 5. Reviewing & approving — the Review queue  ·  [reviewer] or [admin]

**Where:** 📋 Review queue → `/jd-bank/ui/queue`. **Who:** **reviewer or admin only** — an
author who is not a reviewer is redirected/forbidden here. **Admin required:** no (reviewer
suffices).

| Task | How | Notes |
|---|---|---|
| See what's awaiting review | Open the **Review queue** | Lists draft canonical JDs. |
| Inspect a draft | Click a row → the review detail page | Shows the rendered draft, the harmonization change-log (what each source fed, what was dropped and why), and the live gate decision. |
| **Approve** | **Approve** (fill an override reason for any overridable blocking gate) | Publishes **only if** the validator's gates permit it, re-checked at approve time. A blocked draft cannot be approved without a valid override + written reason. |
| **Reject** | **Reject** + a reason | |
| **Edit** | **Edit** the JSON + a reason | Creates a new draft version; the prior is archived. |

> The reviewer on every action is the **authenticated user** — there is no "type your id"
> field. Every action is written to the tamper-evident audit log (guardrail #4).

---

## 6. User management — assign roles, enable/disable  ·  [admin] 🔑 ONLY

**Where:** 👤 Users → `/jd-bank/ui/admin/users`. **Who:** **admin only.** **Admin required:
YES.** 🔑

| Task | How | Notes |
|---|---|---|
| See everyone | Open **Users** | Table of every user who has signed in (provisioned on first login), their roles, status, and last login. |
| Grant / change roles | Tick **author / reviewer / admin** → **Save roles** | e.g. make a hiring manager a **reviewer** so they can approve. |
| Disable an account | **Disable** | Blocks login **and revokes their live sessions** immediately (signs them out everywhere). |
| Re-enable | **Enable** | |

> **Self-lockout guards:** you cannot remove your **own** admin role, nor disable your
> **own** account — so a single-admin deployment can't brick itself.

---

## 7. Operator tasks — pipelines, deploy, config  ·  [operator] 🖥️

These run on the **server shell** (Docker), not in the UI. They need **operator access**,
not the app admin role. Everything runs in containers (Docker-only, ADR-006); the one
exception is Ollama, which runs on `aria-gb10-2`.

### Bring-up & schema
| Task | Command | Notes |
|---|---|---|
| Start the stack | `make up` | Postgres, Neo4j, Redis, api, worker. Ollama must be reachable. |
| Apply DB migrations | `make migrate` | **Run before ingest.** Includes the auth tables (users/roles/sessions) and the audit hash-chain. |
| Open a shell in the app | `make shell` | |

### The archive pipeline (run in order)
| Task | Command | Notes |
|---|---|---|
| Ingest + parse the archive | `make ingest JD_ARCHIVE_PATH=<SFU JDs>` | Loads all files into Postgres. Incumbent names are scrubbed at ingest. |
| Embed | `make embed` | Section + document vectors into Neo4j. Uses self-hosted Ollama (local-only). |
| Near-duplicate dedup | `make near-dup` | Tier-2. |
| Role-equivalence dedup | `make dedup-role` | Tier-3 (needs ingest + embed). |
| Cluster roles | `make cluster` | Phase-3.5 clustering report. |
| Produce draft canonicals | `make canonical-drafts` | Phase-4.4a: one DRAFT per JDFN cluster into the review queue. Add the LLM rewrite/audit pass when Ollama is free; `--no-llm` for a deterministic run. |
| Archive baseline (measurement) | `make baseline JD_ARCHIVE_PATH=<SFU JDs>` | Scores the whole archive; writes `docs/baseline/`. |

### Governance & health
| Task | Command / where | Notes |
|---|---|---|
| Run the full test/gate suite | `make gates` | Static + unit + integration + coverage. What CI runs. |
| Regenerate the HR decision register | `make register` (check: `make register-check`) | Any non-trivial rule/metric must be YAML-configurable and registered. |
| Verify the audit chain | `verify_audit_chain()` in `src.api.services.audit` | Recomputes the hash chain; detects any altered/deleted `audit_log` row. |

### Auth configuration (env)
| Setting | Purpose |
|---|---|
| `CAS_ENABLED` | `true` in production (require SFU sign-in); `false` for dev/CI. |
| `CAS_SERVICE_BASE_URL` | The public origin CAS redirects back to. |
| `BOOTSTRAP_ADMINS` | Comma-separated CAS ids granted `admin` on login (first-admin bootstrap). |
| `SESSION_COOKIE_SECURE` / `_SAMESITE` | `true` / `strict` in production (HTTPS). |

> **Seeding users** (demo/data) is an operator task done directly against the DB; real
> users appear automatically on first CAS login. Roles are then managed in the UI (§6).

---

## 8. "Who can do this?" — quick reference

| Task | any | author | reviewer | admin 🔑 | operator 🖥️ |
|---|:--:|:--:|:--:|:--:|:--:|
| Sign in / out | ✅ | ✅ | ✅ | ✅ | — |
| Browse dashboards | ✅ | ✅ | ✅ | ✅ | — |
| Author / clone / assist / export a JD (Builder) | ✅¹ | ✅ | ✅ | ✅ | — |
| Submit a draft for review | ✅¹ | ✅ | ✅ | ✅ | — |
| Approve / reject / edit / override in the queue | — | — | ✅ | ✅ | — |
| Manage users (roles, enable/disable) | — | — | — | ✅ | — |
| Run pipelines / migrations / deploy / CAS config | — | — | — | —² | ✅ |

> ¹ The Builder & dashboards require only that you are **signed in**; new users hold
> `author` by default. ² App admins do **not** get server/pipeline access from the admin
> role — that is separate **operator** access.

---

*Related docs:* `HANDOFF.md` (current state), `docs/adr/ADR-008-auth-cas-rbac.md` (auth/RBAC
design), `docs/baseline/README.md` (the archive baseline), `docs/decisions/HR-REVIEW-PACKET.md`
(what SFU HR must decide), `CLAUDE.md` (invariants).
