# Phase 4.2b — LLM nuanced quality-audit pass (`jd_quality`)

## Goal
Give Phase 4 its **second LLM pass**: a NUANCED, evidence-cited quality audit of a JD
(`SFUJobDescription` — e.g. a 4.1 `MergedRole.draft` or a 4.2a `RewrittenDraft.draft`).
The LLM reports only the three **nuanced** dimensions a regex validator cannot judge —
`inclusive_language`, `clarity`, `seniority_mismatch` — and **every finding must cite a
VERBATIM quote from the JD**. A finding whose `evidence` is not found verbatim in the JD
text is **dropped** (the anti-fabrication guard, the heart of this task).

The audit is **advisory**. Structural/quantitative problems stay with the deterministic
validator (`jd_core`), which remains the scoring oracle (non-negotiable #3). **This pass
computes NO score and no grade** — it never competes with the validator. The output is a
frozen `QualityAudit` value object. Nothing persists (DB is 4.4), nothing publishes (#1).

Port reference (hris, READ-ONLY):
- prompt `packages/prompts/src/prompts/templates/jd_quality_v1.{system,user}.j2`
- the verbatim-evidence scrub `apps/worker/src/worker/jd_quality_task.py::_merge_llm_findings`.

**We differ from hris deliberately** (check the consumer, not just the source —
HANDOFF Gotcha "faithful to hris ≠ correct here"):
- hris audits `description_raw` (the original document) and ALSO runs an LLM
  `sfu_jd_extract` first. **We do neither**: our input is an already-parsed
  `SFUJobDescription`, and `sfu_jd_extract` is out of scope (our parser is regex — 4.2a).
- hris MERGES deterministic rule findings + LLM findings and SCORES them. **We do not** —
  the deterministic layer is the validator, already run elsewhere; this pass is the
  nuanced LLM layer ONLY, and emits advisory issues, not a score.

## Key facts you must honour
- **The schemas already exist** — do NOT re-create them. `core/src/jd_core/models/quality.py`
  already carries `JDQualityFinding` / `JDQualityFindings` (the LLM output schema, ported
  from hris) and `JDQualityIssue` (`source: "rule" | "llm"`, `evidence`, `rule_id`). The
  audit produces `JDQualityIssue` with `source="llm"`, `rule_id=None`.
- **Reuse 4.2a's `ChatClient` + prompt loader** (`jd_bank/llm/`). Do not add a second client
  or a second loader.
- **The validator is the oracle; this pass does not score.** Tests assert the audit's
  post-state (which findings survive the scrub, their categories/evidence), NEVER verbatim
  model text (non-negotiable #3).
- **`jd_core` must not import `jd_bank`.** The audit pass lives in `jd_bank`; it may import
  `jd_core` models/rules freely, never the reverse (import ratchet — keep it green).
- **Ollama is on `aria-gb10-2`; `make gates` and CI must NOT depend on a live endpoint.**
  Unit + integration tests mock the client; the live golden is opt-in / local-only, and
  its marker is deselected in pytest `addopts`, the `Makefile`, AND `.github/workflows/ci.yml`
  (mirror the embeddings + 4.2a-rewrite live-test guard EXACTLY).
- **No new heavy deps.** `openai` (`AsyncOpenAI`) is already used. Do NOT add `jinja2`.
- **Audit model/temperature is a rulebook decision → registered `open`.** It is a SEPARATE
  decision from the rewrite model (a rewrite-policy change must not silently move the audit
  model), so it gets its own file `quality.yaml`, not a reuse of `rewrite.yaml`'s knobs.

## Files in scope (new unless noted)

### The nuanced audit consumer
- `core/src/jd_bank/quality/__init__.py`
- `core/src/jd_bank/quality/audit.py` — `audit_quality(jd, *, client, rules=None) -> QualityAudit`:
  1. Flatten the JD into the `jd_text` prompt slot using the **shared** flattener (see
     refactor below) — the SAME text the scrub uses as its haystack, so a quote the model
     copied from the prompt can be found verbatim.
  2. `load_prompt(rules.quality.prompt_version, jd_text=...)` → `client.chat_json(...,
     JDQualityFindings, max_tokens=rules.quality.max_tokens, max_retries=rules.quality.max_retries)`.
  3. **Anti-fabrication guard (the heart):** for each returned finding, drop it if
     `evidence` is empty/None OR its `casefold()` is not a substring of the flattened JD's
     `casefold()`; record every dropped finding. Convert each SURVIVING finding to a
     `JDQualityIssue(source="llm", rule_id=None, ...)`. When
     `rules.quality.anti_fabrication_enabled` is `False`, keep ALL findings unscrubbed and
     record the guard as disabled (visible, never invisible — mirror 4.2a's
     `AntiFabricationRecord.enabled=False` pattern).
  4. Return a **frozen `QualityAudit`** — NO score/grade/approval/canonical field.
- `core/src/jd_bank/jd_text.py` (NEW shared module) — move `_flatten_jd` out of
  `jd_bank/rewrite/harmonize.py` to `flatten_jd` here and have BOTH consumers import it.
  This is deliberate: 4.2a's must-fix was that a section dropped from the flattener is
  invisible to the oracle (the Relationships omission). One flattener, one home, so the
  audit haystack cannot silently diverge from the rewrite's. Keep `harmonize.py` behaviour
  byte-identical (re-export or import; its tests must stay green).

### The output model
- `core/src/jd_core/models/bank.py` — add a frozen `QualityAudit` (`extra="forbid"`,
  `frozen=True`) alongside `RewrittenDraft`:
  - `issues: tuple[JDQualityIssue, ...]` — surviving nuanced findings, source="llm".
  - `dropped: tuple[JDQualityFinding, ...]` — findings the scrub removed (ungrounded
    evidence). The audit trail; frozen evidence, not a scratchpad.
  - `anti_fabrication_enabled: bool` — whether the scrub ran.
  - `model: str`, `prompt_version: str`, `rules_version: str` — provenance stamps.
  (No `job_id`, no `overall_score`, no `grade`, no `generated_at` — those are hris
  persistence/scoring fields; this is an in-memory advisory value object. Same trim
  discipline as the module docstring already documents for `CanonicalRole`.)

### Prompt templates
- `core/src/jd_bank/llm/templates/jd_quality_v1.system.j2` + `.user.j2` — port faithfully
  from hris. The user template's only variable is `{{ jd_text }}`. The loader already
  raises on a missing/unknown var — no loader change needed.

### Registered config (REGISTERED + UNHASHED — same class as `rewrite.yaml`)
- `core/src/jd_core/rules/quality.yaml` — NEW. A quality-AUDIT-policy change decides how a
  JD is *audited* (advisory), NOT how it is *scored/approved* (the HASHED files own that),
  so it is EXCLUDED from `rules_version`. Top-of-file banner mirroring `rewrite.yaml`'s.
  Knobs, all `status: open` / `provenance: our_invention`, PROVISIONAL (calibrate at 4.5 —
  claim no measured evidence):
  - `model` (default `gpt-oss:120b`), `temperature` (`0.0`), `max_tokens` (`1024`, hris's
    value for this pass), `max_retries` (`1`), `prompt_version` (`jd_quality_v1`),
    `anti_fabrication_enabled` (`true`).
- `core/src/jd_core/rules/loader.py` — add `QUALITY_FILE`, a typed `QualityAudit`-rules
  model (name it e.g. `QualityAuditRules` to avoid colliding with the `bank.QualityAudit`
  value object) on `Rules`, add `quality.yaml` to `_FILE_MODELS` and `_UNHASHED_FILES`.
  Wire coverage/cross-file exactly as `rewrite`/`harmonization` do.
- `core/src/jd_core/rules/decision_register.yaml` — HR-185.. entries for every `quality.yaml`
  knob, `status: open`, `provenance: our_invention`, honest `why_it_matters` (PROVISIONAL;
  no measured evidence). Run `make register` so the Markdown regenerates.

### ChatClient generalization (small, back-compatible)
- `core/src/jd_bank/llm/client.py` — the client currently binds `model`/`temperature` to
  `rules.rewrite.*` in `__init__`. Generalize so the audit pass can bind them to
  `rules.quality.*`: add optional `model: str | None = None`, `temperature: float | None =
  None` params; when provided they win, else fall back to `rules.rewrite.*` (so ALL existing
  rewrite tests + call sites stay byte-identical). Update the docstring: the model is a
  **rulebook** decision (the section the caller passes — rewrite OR quality), NEVER
  `settings.agent_model`. The audit consumer constructs
  `ChatClient(model=rules.quality.model, temperature=rules.quality.temperature)`.

### Make + compose (mirror `rewrite-golden` / the `rewrite` service exactly)
- `Makefile` — `make quality-golden` opt-in local-only target (live marker deselected in
  `addopts`, the Makefile default, and CI).
- `docker-compose.yml` — a `quality` compose service if the golden needs one (mirror
  `rewrite`).
- `.github/workflows/ci.yml` — ensure the live marker stays deselected with `--strict-markers`.

### Tests (under `core/tests/` — self-contained; `docs/` + repo-root fixtures NOT mounted)
See Acceptance.

## Acceptance (all via `make gates` in Docker; live golden separate)
1. **Validator-as-oracle / post-state, not text** — a content-keyed fake `ChatClient`
   returns FIXED `JDQualityFindings`; assert which issues survive, their categories,
   `source=="llm"`, and that the surviving evidence is a verbatim JD substring. Never
   assert model prose.
2. **Anti-fabrication guard, pinned by MUTATION** — fake LLM returns one finding whose
   `evidence` IS a verbatim JD substring and one whose evidence is NOT (fabricated) → the
   fabricated one is dropped and recorded in `dropped`, the grounded one survives in
   `issues`. **Disable the guard (`anti_fabrication_enabled: false`, and update the register
   so the drift alarm stays silent) → a BEHAVIOURAL assertion goes red** (the fabricated
   finding now survives). Also: a finding with empty/None evidence is dropped. (A green
   suite proves nothing about a guard you have not tried to break — HANDOFF Gotcha.)
3. **The scrub haystack is the SHARED flattener** — a finding quoting text that lives ONLY
   in a section the flattener must include (e.g. Relationships) survives; prove the audit
   and the rewrite use the SAME `flatten_jd` (the 4.2a Relationships must-fix must not
   regress). If `flatten_jd` drops a section, this test goes red.
4. **Audit model source** — `audit_quality` drives the client off `rules.quality.model`; a
   test where `rules.quality.model`, `rules.rewrite.model`, and `settings.agent_model` are
   three DISTINCT strings goes red if the code reads the wrong source.
5. **Non-negotiable #1 / #3** — `QualityAudit` is frozen, has NO score/grade/approval/
   canonical/published field; the audit never marks anything canonical and never computes a
   score.
6. **Unhashed config** — editing `quality.yaml` does NOT change `rules_version`; `make
   register-check` + the `_OFF_SURFACE` coverage guard both pass; every knob is registered.
7. **Prompt loader** — the ported templates render; `prompt.version == "jd_quality_v1"` is
   stamped onto `QualityAudit.prompt_version`; a missing var raises (existing loader
   behaviour — one assertion is enough).
8. **Client discipline reused, not duplicated** — the audit path goes through the same
   never-retry-400 / retry-transient / invalid-JSON-then-`LLMOutputInvalidError` client;
   one test that an over-length audit request raises `ChatBadRequestError` (not retried).
9. **Import ratchet** — `jd_core` still does not import `jd_bank`; `harmonize.py` tests
   stay green after the `flatten_jd` move; coverage ≥ 80 (repo ~95%); ruff/black/mypy
   --strict clean.

## Design decision to RECORD (do not implement here) — structural-bar inflation guard
The 4.2a reviewer follow-up asks whether to extend the anti-fabrication guard to the
structural bars (`education` / `experience` / `security` quals) — 4.2a scrubs only
`skill/knowledge/ability`, so an LLM inflating "Bachelor's → PhD" in a *rewrite* passes
through today (same class as the 4.1 experience-bar-inflation defect).

**Decision for this task: NOT in 4.2b.** Rationale: (a) 4.2b's audit is READ-ONLY and
cannot inflate a bar — the inflation risk lives in 4.2a's *rewrite*, not here; (b) catching
"Bachelor's → PhD" needs a level-COMPARISON (education ordinal / experience years), not the
token-grounding the guard does — a deliberate change with its own blast radius, not a
drive-by. Recommend implementing it as a scoped 4.2a-guard follow-up (register `open` when
added). This task only RECORDS the decision (task file + HANDOFF Next-up); it changes no
code for it.

## Out of scope (do NOT do here)
- `sfu_jd_extract` (our parser is regex), any DB persistence / arq / review queue (4.4),
  the diff/change-log (4.3), the composer, any score/grade computation by the LLM.
- The structural-bar inflation guard (recorded above as a follow-up).
- Calibrating the `quality.yaml` knobs — they ship PROVISIONAL `open`; a measurement pass
  is a later task (4.1/4.2a measure-after pattern).
- Any golden test that calls the live endpoint inside `make gates` / CI.
