# Phase 4.2a — LLM harmonize rewrite pass (scaffolding + first consumer)

## Goal
Give Phase 4 its **first LLM pass**: take the deterministic 4.1 merge draft
(`MergedRole.draft`, already a valid `SFUJobDescription`) and have a self-hosted LLM
**rewrite it into cleaner, template-faithful prose** — WITHOUT inventing skills, duties,
or qualifications the merge draft did not contain. The output is an explicit **DRAFT**,
scored by the existing validator (the oracle). Nothing auto-publishes (non-negotiable #1).

This task delivers the reusable LLM scaffolding (chat client + prompt loader + registered
config) *and* its first real consumer (the harmonize rewrite). The `jd_quality` nuanced
audit pass is a separate follow-up task (4.2b) — OUT OF SCOPE here.

Port reference (hris, READ-ONLY): `apps/worker/src/worker/jd_bank_task.py::harmonize_cluster`
and `packages/prompts/src/prompts/templates/jd_harmonize_v1.{system,user}.j2`. **We differ
from hris deliberately: hris fed the LLM raw member JDs and let it free-associate; we feed
the grounded 4.1 merge draft and forbid new content.** Check the consumer, not just the
source ("faithful to hris ≠ correct here" — HANDOFF Gotchas).

## Key facts you must honour
- **`MergedRole.draft` is an `SFUJobDescription`** (`core/src/jd_core/models/bank.py:173`);
  `MergedRole.provenance.skill_frequency` is `((skill, members_requiring), ...)`.
- **The validator is the oracle.** Score/grade the rewritten draft through the SAME engine
  the baseline uses (`evaluate` / gate runner in `jd_core`). Tests assert validator
  post-state, NEVER verbatim model text (non-negotiable #3).
- **Ollama is on `aria-gb10-2`, OpenAI-compatible `/v1`** — `settings.ollama_base_url`.
  Mirror the embed client `core/src/jd_bank/embeddings/client.py` exactly for retry / never-
  retry-400 / determinism discipline. **`make gates` and CI must NOT depend on a live
  endpoint** — unit + integration tests mock the client; the live golden is opt-in/local-only.
- **Chat model is a rulebook decision → registered `open`.** Available on the host today:
  `gpt-oss:120b`, `gpt-oss:20b`, `qwen3.5:latest`, `gemma4:26b`, `llama4:latest`. Default
  `gpt-oss:120b` (strongest general instruct → best JSON-schema adherence), `status: open`,
  `provenance: our_invention`. SFU publishes no rewrite policy; hris used an LLM prompt only.
- **`jd_core` must not import `jd_bank`.** The rewrite pass lives in `jd_bank`; it may import
  `jd_core` models/rules/validator freely, never the reverse.
- **No new heavy deps.** `openai` (`AsyncOpenAI`) is already used by the embed client. Do NOT
  add `jinja2` — the two templates are pure `{{ var }}` substitution; render with a minimal
  in-repo substituter.

## Files in scope (new unless noted)
- `core/src/jd_bank/llm/__init__.py`
- `core/src/jd_bank/llm/client.py` — `ChatClient` (mirror `EmbedClient`):
  `AsyncOpenAI` chat.completions, `response_format={"type": "json_object"}`,
  `temperature` from rules (default 0.0 → deterministic), retry transient (3, exp backoff),
  **never retry a 400** (`ChatBadRequestError`). Method
  `chat_json(messages, model_cls: type[BaseModel], *, max_tokens, max_retries) -> BaseModel`:
  validate the JSON into `model_cls`; on invalid JSON / ValidationError retry up to
  `max_retries` (with a terse repair nudge), then raise `LLMOutputInvalidError`. Model id
  comes from `get_rules().rewrite.model`, NEVER `settings.agent_model` (mirror the embed
  client's model-source discipline + its mutation-proof test: drive a rules model that is a
  DISTINCT string from `settings.agent_model` so the two sources can actually be told apart).
- `core/src/jd_bank/llm/prompts.py` — `load_prompt(name, **vars) -> RenderedPrompt`
  (`.messages` = system+user, `.version`). Templates as versioned data under
  `core/src/jd_bank/llm/templates/` (port `jd_harmonize_v1.system.j2` + `.user.j2`,
  keep wording faithful). Unknown/missing template var must RAISE, never silently leave
  `{{ x }}` in the prompt.
- `core/src/jd_bank/rewrite/__init__.py`
- `core/src/jd_bank/rewrite/harmonize.py` — `rewrite_merged_role(merged, *, client, rules?)
  -> RewrittenDraft`:
  1. Serialize `merged.draft` to the prompt's `member_jds` slot (we feed the GROUNDED draft,
     not raw members) + `skill_frequency` from provenance.
  2. `chat_json(...) -> SFUJobDescription`.
  3. **Anti-fabrication guard** (the heart of this task): the rewrite may rephrase but may not
     INTRODUCE. Build the allowed vocabulary from the merge draft (+ its member-derived
     skill_frequency names). Any output qualification whose skill/knowledge/ability content is
     NOT grounded in that vocabulary is **scrubbed** (dropped) and recorded; a duty with no
     token overlap to any draft duty is **flagged** (recorded, not silently kept). Exact
     grounding policy is a registered knob (`anti_fabrication.*`). Mirror hris's evidence-
     verify scrub in spirit.
  4. Mark boilerplate present (`about_sfu_present` / `territorial_acknowledgement_present` /
     `employment_equity_present` = True) so the grade reflects role content, exactly as
     `jd_bank_task.harmonize_cluster` does — and say WHY in a comment.
  5. Score via the validator → issues, score, grade.
  6. Return a **frozen `RewrittenDraft`** with NO approval/canonical field (non-negotiable #1):
     the rewritten `SFUJobDescription` (a DRAFT), `score`, `grade`, `issues`,
     `anti_fabrication` scrub record (dropped skills + flagged duties), `model`,
     `prompt_version`, `rules_version`. Add `RewrittenDraft` to `jd_core/models/bank.py`
     (frozen, `extra="forbid"`) alongside `MergedRole`.
- `core/src/jd_core/rules/rewrite.yaml` — REGISTERED + **UNHASHED** (a rewrite-policy change
  decides how a draft is *worded*, not how a JD is *scored* — same class as
  `harmonization.yaml`). Knobs (all `open`, `our_invention`): `model`, `temperature`,
  `max_tokens`, `max_retries`, `prompt_version`, `anti_fabrication.enabled`,
  `anti_fabrication.skill_grounding` policy + threshold, `anti_fabrication.duty_flag`
  threshold. Add a top-of-file banner mirroring `harmonization.yaml`'s.
- `core/src/jd_core/rules/loader.py` — add `REWRITE_FILE`, a typed `RewriteRules` model on
  `Rules`, and add `rewrite.yaml` to `_UNHASHED_FILES` (so it does NOT churn `rules_version`)
  and to `_FILE_MODELS`. Wire cross-file/coverage as the existing unhashed files do.
- `core/src/jd_core/rules/decision_register.yaml` — HR-176.. entries for every `rewrite.yaml`
  knob, `status: open`, `provenance: our_invention`, honest `why_it_matters` (these are
  PROVISIONAL starting values, to be calibrated at the 4.5 pilot — do NOT claim measured
  evidence we don't have). Run `make register` so the Markdown regenerates.
- `Makefile` + `docker-compose.yml` — `make rewrite-golden` opt-in local-only target + a
  `rewrite` compose service (mirror `embed` / `harmonize`). A `live`-style pytest marker that
  is **deselected in pytest addopts, the Makefile, AND `.github/workflows/ci.yml`** (mirror
  the embeddings live-test guard exactly).
- Tests under `core/tests/` (self-contained — `docs/` + repo-root fixtures are NOT mounted in
  the `gates` container).

## Acceptance (all via `make gates` in Docker; live golden separate)
1. **Validator-as-oracle snapshot** — a content-keyed fake chat client returns a FIXED
   rewritten JD; assert the validator post-state (score, grade, issue ids), never the text.
2. **Anti-fabrication guard, pinned by mutation** — fake LLM injects a skill NOT in the merge
   draft → guard scrubs it, records it, and the returned draft does not contain it. **Disable
   the guard (flip the knob, update the register so the drift alarm stays silent) → a
   BEHAVIOURAL assertion goes red.** Also a duty with no overlap → flagged. (A green suite
   proves nothing about a guard you have not tried to break — HANDOFF Gotchas.)
3. **Client discipline** — never-retry-400 (`ChatBadRequestError`); retry-transient-then-raise;
   `temperature` from rules is actually passed to the API; invalid JSON retried up to
   `max_retries` then `LLMOutputInvalidError`; response reassembled from the intended choice,
   not assumed positionally.
4. **Model source** — `chat_json` uses `rules.rewrite.model`; a test where `rules.rewrite.model`
   and `settings.agent_model` are DISTINCT strings goes red if the code reads the setting.
5. **Non-negotiable #1** — `RewrittenDraft` is frozen and has no approval/canonical/published
   field; the draft is an ordinary `SFUJobDescription`, never marked canonical.
6. **Unhashed config** — editing `rewrite.yaml` does NOT change `rules_version`; `make
   register-check` + the `_OFF_SURFACE` coverage guard both pass; every knob is registered.
7. **Prompt loader** — a missing template variable raises; `RenderedPrompt.version` is stable
   and stamped onto `RewrittenDraft.prompt_version`.
8. **Import ratchet** — `jd_core` still does not import `jd_bank`; gates green.
9. Coverage ≥ 80 (repo runs ~95%); ruff/black/mypy --strict clean.

## Out of scope (do NOT do here)
- The `jd_quality` nuanced audit pass (→ 4.2b) and `sfu_jd_extract` (our parser is regex;
  revisit only if a future task needs it).
- %-rebalance of duty allocations (4.1 follow-up #2), un-merged sections (#4), WJQ (#5),
  the diff/change-log (4.3), the review queue / persistence / arq (4.4), any DB writes.
- Calibrating the knobs against real clusters — they ship as PROVISIONAL `open` defaults;
  a measurement pass is a later task (mirrors 4.1's measure-after pattern).
- Any golden test that calls the live endpoint inside `make gates`/CI.
