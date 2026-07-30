# Phase 4.4d — the review UI (minimal, server-rendered inside FastAPI)

> **PARTIALLY SUPERSEDED (2026-07-29).** This spec's "Edit content input: a raw-JSON `<textarea>`…
> a structured per-field editor is out of scope" (and the matching Out-of-scope note) was the MVP
> and shipped as such — it is now **replaced by a full per-field `SFUJobDescription` editor**
> (`src/api/routes/ui.py::_content_from_form` + `review_detail.html`). The detail page also now
> links a **draft-vs-last-approved version diff** (`/jd-bank/ui/review/{id}/diff`). Everything else
> in this spec (queue → detail → approve/reject/override, commit discipline, no-new-dependency) is
> still accurate. Kept as the historical task record.

## Goal
The LAST slice of the Phase-4.4 review queue: a **minimal, server-rendered** HTML UI a human HR
reviewer drives to work the queue — **queue list → cluster detail (draft + 4.3 diff + validation
report + approve / edit / reject / override) → back to the queue.** It renders **inside the FastAPI
app** (`core/src/api`, so it is under `make gates`: mypy --strict + coverage + TestClient tests),
NOT the untested Flask `frontend/`. **No JS build step; no new runtime dependency** (see constraints).

**The UI owns NO invariants.** Every action goes through the 4.4b service
(`jd_bank/review/service.py`) exactly as the 4.4c JSON routes do — the UI just renders the packet
and turns a form submit into one service call. NN #1 (nothing publishes unless the gate decision
permits), validator-as-oracle, override-needs-a-reason, append-only audit all stay in the service.
A UI handler cannot approve a blocked draft any more than the JSON route can — the service raises.

## Files in scope (new unless noted)
- `core/src/api/routes/ui.py` — an `APIRouter(prefix="/jd-bank/ui")` of `HTMLResponse` endpoints.
- `core/src/api/templates/` (new dir) — Jinja2 templates: `review_queue.html`, `review_detail.html`
  (a shared `_base.html` is fine). Mirror `core/frontend/templates/dashboard.html`'s dark-theme
  inline CSS so it reads as the same product; keep it minimal.
- `core/src/api/main.py` (edit) — `app.include_router(ui_router)` alongside the existing
  `jd_bank_router` include (same bottom-of-file block; same circular-import shim already there).
- `core/tests/unit/test_review_ui.py` — TestClient tests (service monkeypatched, `get_session`
  overridden), mirroring `test_review_routes.py`.

## Endpoints (all under `/jd-bank/ui`, all `HTMLResponse`)
| Method + path | Does | Renders / result |
|---|---|---|
| `GET /queue` | `service.list_review_queue(session, limit=?)` | `review_queue.html` — a row per DRAFT: title, cluster/version, status, stored score/grade, blocking-gate count, link to detail. Empty-queue state. |
| `GET /review/{canonical_id}` | `service.get_review_packet(session, id)` | `review_detail.html`; **404 page if None**. Shows: the FRESH `decision` (approved? + each blocking `GateReason`: gate_id, source_part, reason, `overridable`), score/grade, issues, the rendered draft, the 4.3 diff + `removed` from `change_log`, and the four action forms. |
| `POST /review/{canonical_id}/approve` | build overrides from the form → `service.approve(...)` | success → **303** redirect to `/jd-bank/ui/queue`; on `NotApprovableError`/`GateOverrideError` → re-render the detail page (200) with the error shown, **no commit**. |
| `POST /review/{canonical_id}/reject` | `service.reject(..., reason=)` | success → 303 to queue; `MissingReasonError` → re-render detail with error, no commit. |
| `POST /review/{canonical_id}/edit` | parse content → `service.edit(..., new_content=, reason=)` | success → 303 to the NEW version's detail (or queue); `ValidationError`/`MissingReasonError` → re-render with error, no commit. |

- **Reviewer identity = a `reviewer_id` form field** (pilot model, no SSO), exactly as the JSON routes.
- **Commit discipline (same as 4.4c):** commit ONLY after the service returns successfully; on any
  service error, do NOT commit — re-render the page (or a redirect for GET-unknown → 404). Pin BOTH
  directions in tests.
- **Override construction:** on the detail page, each **blocking + overridable** gate gets an optional
  reason textarea. The approve handler builds a `GateOverride(gate_id=<that gate>, reviewer=reviewer_id,
  reason=<text>)` for each textarea the reviewer filled, and passes them to `service.approve`. Leave a
  blank textarea out. **Do NOT pre-fill, synthesize, or default a reason** — a blank reason is not an
  override (the service/`GateOverride` will reject a blank one anyway; do not work around that). A
  non-overridable gate gets NO override input.
- **Edit content input:** a `<textarea>` holding the draft `content` as JSON (pre-filled from the
  packet). The handler `json.loads` it and passes the dict to `service.edit`, which re-validates
  (`SFUJobDescription`) — malformed JSON or invalid content → re-render with the error, no commit.
  (Minimal is fine; a structured per-field editor is out of scope.)

## Hard constraints
- **NO new runtime dependency.** Do **not** use FastAPI's `Form(...)` params (they require
  `python-multipart`, which is NOT installed). Parse the POST body with `await request.form()` —
  Starlette parses `application/x-www-form-urlencoded` (the default HTML form enctype) with no extra
  dependency. Templates use plain forms; no file uploads, no custom enctype. `jinja2` is already
  present (via Flask) so `fastapi.templating.Jinja2Templates` is fine. If you believe a dependency is
  genuinely unavoidable, **STOP and escalate** — do not add one silently.
- **No JS build step.** Server-rendered HTML + plain form POSTs. A few lines of inline vanilla JS are
  tolerable only if truly needed; prefer none.
- **The UI adds no invariant.** No gate/publish/validation logic in a handler or a template; the
  service is the only authority. No second publish path.
- **Escape all JD text in templates.** Jinja2 autoescape must be ON (it is by default for `.html`);
  never render draft content with `| safe`. This is untrusted archive text.

## Acceptance (all via `make gates` in Docker)
1. **Queue renders** the DRAFT items in service order (monkeypatched service returns a couple of
   items → assert titles/links/counts present; assert `limit` passthrough if exposed). Empty queue →
   a friendly empty state, not a crash.
2. **Detail renders** the fresh decision, score/grade, blocking gates (with `overridable` reflected:
   an overridable blocker shows an override reason field; a non-overridable one does NOT), the draft,
   and the 4.3 diff/removed. Unknown id → 404.
3. **Approve happy path** → service called once with the right `reviewer_id` + parsed overrides, then
   `session.commit` awaited once, then a 303 to the queue. **Approve of a still-blocked draft**
   (service raises `NotApprovableError`) → NO commit, page re-rendered with the blocking reason shown.
4. **Override from the form** → a filled reason on an overridable gate produces exactly one
   `GateOverride` with that gate_id + reason passed to `service.approve`; a blank textarea produces
   none. (The service enforces the rest — do not re-test the service here, test the wiring.)
5. **Reject / edit** happy paths → correct service call + commit + 303; **blank reason → the service's
   `MissingReasonError`** surfaces as a re-rendered error with no commit; **malformed edit JSON /
   invalid content → `ValidationError`** re-rendered with no commit.
6. **Commit discipline pinned both directions** (commit on success; never on a service error) — the
   one behaviour a handler could get wrong, as in 4.4c.
7. ruff/black/mypy --strict clean; coverage ≥ 80; `make register-check` green (no knob, `rules_version`
   untouched). `jd_core` does not import `jd_bank`.

## Out of scope
- Auth / real reviewer identity (SSO), pagination beyond a `limit`, a structured field-by-field editor,
  live-styling/JS frameworks, re-opening a published/archived canonical, the 4.5 pilot itself, any
  rule/knob or schema change. If the draft-content JSON textarea feels too raw for the pilot, note it
  as a follow-up — do not build a form builder here.
