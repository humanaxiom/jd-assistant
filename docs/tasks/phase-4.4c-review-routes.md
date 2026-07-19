# Phase 4.4c — the review ROUTES (thin FastAPI over the 4.4b service)

## Goal
Expose the Phase-4.4b review service (`jd_bank/review/service.py`) over HTTP as a JD-Bank
router hung off the existing harness app (`core/src/api/main.py`). **Thin transport ONLY.**
The service already owns every invariant (NN #1 publish gate, validator-as-oracle, override-
needs-reason, append-only audit, legal-transitions). The routes add **NONE of their own** —
no second publish path, no gate logic in a handler, no re-validation. A handler unpacks the
request → calls exactly one service function → commits → serializes the result, and maps the
service's typed errors to HTTP status codes. Nothing more.

## Files in scope (new unless noted)
- `core/src/api/routes/__init__.py` (new package)
- `core/src/api/routes/jd_bank.py` — an `APIRouter` (prefix `/jd-bank`) with the five endpoints.
- `core/src/api/main.py` (edit) — `app.include_router(...)`. No other change.
- `core/tests/unit/test_review_routes.py` — TestClient tests (mirror `test_api.py`'s pattern:
  drive `TestClient(app)` WITHOUT the lifespan, override `get_session` with a fake/mock session,
  monkeypatch the `service` functions so the route logic is tested in isolation from the DB).

## Endpoints (all under `/jd-bank`)
| Method + path | Service call | Success |
|---|---|---|
| `GET /review/queue?limit=` | `list_review_queue(session, limit=limit)` | 200, list of queue items |
| `GET /review/{canonical_id}` | `get_review_packet(session, canonical_id)` | 200 packet; **404 if None** |
| `POST /review/{canonical_id}/approve` | `approve(session, id, reviewer_id=, overrides=)` | 200, canonical summary |
| `POST /review/{canonical_id}/reject` | `reject(session, id, reviewer_id=, reason=)` | 200, canonical summary |
| `POST /review/{canonical_id}/edit` | `edit(session, id, reviewer_id=, new_content=, reason=)` | 200, canonical summary |

- **Reviewer identity = caller-supplied string in the request body** (`reviewer_id`), the pilot
  model — no SFU SSO. The `review_actions.reviewer_id` column already models it.
- **The route commits.** The service `flush`es but does not `commit` (caller owns the
  transaction, like the producer/ingest driver). On the success path the handler
  `await session.commit()` after the service returns; on any service error it must NOT commit
  (roll back and raise the mapped HTTP error). Mirror `create_task`'s commit shape in `main.py`.
- **Request bodies** (pydantic models, `extra="forbid"`):
  - approve: `{ reviewer_id: str, overrides: list[GateOverride] = [] }` — reuse the existing
    `jd_core.models.quality.GateOverride` as the list element (it already makes a reasonless/
    unnamed override unconstructable; a bad element yields 422 from FastAPI's own validation).
  - reject: `{ reviewer_id: str, reason: str }`
  - edit: `{ reviewer_id: str, new_content: dict, reason: str }`

## Error → status mapping (the ONLY logic the routes own)
Catch the service's typed errors and translate. Do not leak a 500.
| Service raises | HTTP | Why |
|---|---|---|
| `CanonicalNotFoundError` | **404** | no such canonical |
| `IllegalTransitionError` | **409** | not a live DRAFT — no double-publish / re-open |
| `NotApprovableError` | **409** | gates still block; the draft's state conflicts with publish |
| `GateOverrideError` | **422** | the override request is invalid (unreasoned / non-overridable / not-blocking / doubled) |
| `MissingReasonError` | **422** | a reject/edit with a blank reason |
| pydantic `ValidationError` (malformed `new_content` on edit) | **422** | the edited content is not a valid `SFUJobDescription` |
| `get_review_packet` returns `None` | **404** | unknown id |

`GET /review/queue` and the missing-id `GET` cannot 500 on a normal miss. Keep the mapping in
ONE place (a small helper or explicit `try/except` per handler — your call; be consistent).

## Response shapes
- Queue: return the `ReviewQueueItem` value objects (FastAPI serializes the frozen pydantic
  models directly — UUID/enum/datetime handled). A `response_model` is optional but nice.
- Packet: return the `ReviewPacket` value object (carries `content`, `change_log`, the FRESH
  `decision`, score/grade/issues).
- approve/reject/edit: a small `CanonicalOut` — `{ canonical_id, cluster_id, version, status }`
  read off the returned `CanonicalJD`. Do NOT dump the whole ORM row.

## Acceptance (all via `make gates` in Docker)
1. **Every endpoint is TestClient-tested** with the service monkeypatched: happy path returns
   the mapped status + shape; queue passes `limit` through; approve passes `reviewer_id` +
   parsed `overrides` through to the service exactly once.
2. **Error mapping pinned per row of the table above** — each typed error → its status, asserted.
   The malformed-edit body (`new_content` that fails `SFUJobDescription` validation) → 422.
3. **The route commits on success and does NOT commit on a service error** — assert
   `session.commit` awaited once on a happy approve/reject/edit, and NOT awaited (or rolled back)
   when the service raised. This is the one behaviour a handler could get wrong.
4. **No second publish path / no invariant logic in a handler** — the handler calls the service
   and nothing else decides publish/gates. (A reviewer will check this by reading; keep it true.)
5. `jd_core` does not import `jd_bank`; `api` may import both. ruff/black/mypy --strict clean;
   coverage ≥ 80. `make register-check` green (no new knob, `rules_version` untouched).

## Out of scope
- The server-rendered UI (4.4d), auth / real reviewer identity (SSO), pagination beyond `limit`,
  re-opening a published/archived canonical, any new rule/knob or schema change. A real
  integration (live Postgres) test is optional — the unit TestClient tests are the contract here;
  the service's own integration tests already cover the DB transitions.
