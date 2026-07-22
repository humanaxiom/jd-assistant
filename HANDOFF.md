# JD Bank — Session Handoff

Read this first every session. Single source of truth for current state + how we work.

**NEWEST (2026-07-21, latest): FULL-ARCHIVE enrichment run IN FLIGHT + 4.6 follow-ups MERGED
([PR #59](https://github.com/humanaxiom/jd-assistant/pull/59), CI green, rebase-merged).**

**① The full-archive canonical enrichment is RUNNING** — the complete bank, LLM pipeline, on the
new constrained-decode/`reasoning_effort` code. Detached crash-safe container **`jd-canonical-fullrun`**
(`docker compose run -d ... canonical python -m src.jd_bank.canonical --commit-every 25`), full LLM
pipeline (rewrite `gpt-oss:120b` + audit) over **ALL 2458 recomputed clusters**. **Watch:**
`docker logs -f jd-canonical-fullrun` (stderr progress every 25 clusters). **Resume if it dies:** re-run
the same command — idempotent, refreshes/skips what already landed. Summary → `docs/canonical/summary.json`
on completion. As of this handoff: **150/2458, 0 failures, ~63 s/cluster steady-state, ETA ~44h (~2 days).**
Verified before launch: Ollama reachable on `aria-gb10-2`, `gpt-oss:120b` loaded, egress allow-list intact,
`review_actions=0` (nothing human-touched to clobber). **MUST run WITH the LLM** — a `--no-llm` full run
would refresh the existing enriched drafts back to deterministic prose (no no-clobber protection at
`review_actions=0`).

> **⚠ POST-RUN CLEANUP (record this):** the full-corpus clustering yields **different `cluster_id`s**
> than the earlier `--limit 5000` seed (membership differs → different `cluster_id_for` uuid5), so the run
> **PERSISTS NEW drafts alongside** the seed's 389 rather than refreshing them (only ~17% coincidental
> refresh: 26/150 at checkpoint 6). `canonical_jds` will grow to ~2000+. The **superseded seed drafts**
> (all `DRAFT`, `review_actions=0` → safe to delete) should be **pruned after the run** so the review
> queue doesn't show near-duplicate drafts of the same role. Do NOT prune mid-run.

**② [PR #59](https://github.com/humanaxiom/jd-assistant/pull/59) — three 4.6 follow-ups + a CI fix, MERGED**
(gates **1784 · 93.94%**; `rules_version` untouched — no rule/decision-param change):
- **4.6d dead Flask `frontend` REMOVED** — compose service + env/port, the `core/frontend/` scaffold
  package (superseded by the FastAPI `/jd-bank/ui`), the now-unused `flask` dep, and README/DEVELOPER_GUIDE
  refs. **Surfaced a latent bug:** `jinja2` (used directly by the FastAPI dashboards/review UI) was only
  installed **transitively via flask** — the clean CI build broke (`ModuleNotFoundError: jinja2`) while
  local `make gates` masked it (`docker compose run` reuses a stale image, doesn't rebuild on a
  requirements change). Fixed by declaring `jinja2>=3.1.0` explicitly; verified against a from-scratch
  `docker compose build gates`. **Lesson: `make gates` does NOT rebuild — `docker compose build gates`
  first when deps change, or CI will catch what you didn't.**
- **Two secondary cluster-KPI test pins tightened** — `largest_cluster` (`"133"`, which doubled as a
  `size_distribution` key) and `flagged_clusters` (`"11"`, a substring of 10911/150911/47111/1191) were
  collision-prone; replaced with collision-free `9092`/`4707`, `largest_cluster` decoupled from the size
  buckets so each pin uniquely guards its KPI.
- **jdbank-scrub open flag CLOSED** — repo-wide search found no reference treating `C:\repos\jdbank` as
  authoritative; every mention is an intentional "it's stale" note or the unrelated `jdBank.ts` hris TS
  filename. Nothing to scrub.

**STILL DEFERRED — and now BIGGER than it looked:** the **`max_chars`/dense-WJQ embedding** follow-up.
Re-measured over the v2 corpus this session (read-only, no Ollama), **HR-126 was falsified**: it is not
"11 docs" — **1,400 docs (~9.6%) are TRUNCATED** at `max_chars=10000` (the WJQ re-parse recovered dense
text; median 2,559→3,909, MAX 8,987→13,486), and the 11 `bad_requests` are just the densest subset where
even the truncated text still 400s past the 8,192-token limit. **There is no single `max_chars` that both
avoids truncation and avoids the 400** — it is now an OPEN DESIGN DECISION (progressive-backoff-on-400 /
chunk+pool / rely on section vectors / lower to a token-safe floor). HR-126 in the register carries the
corrected numbers + the four options ([PR #62](https://github.com/humanaxiom/jd-assistant/pull/62)). Needs
a design call AND the Ollama host (busy with the run) to re-embed + validate — do it AFTER `aria-gb10-2`
frees. Also still open: the 4.5 HR pilot; review-queue structured edit view.

**NEXT SESSION:** (1) check `docker logs jd-canonical-fullrun` — if done, read `docs/canonical/summary.json`,
**prune the superseded seed drafts** (full-run cluster_ids ≠ the 389 seed's → they coexist), re-baseline/
update docs; if dead, re-run the same command to resume. (2) then the `max_chars` DESIGN decision (read the
corrected HR-126 first). This session merged **PRs #59 (4.6 + jinja2), #61 (this handoff), #62 (HR-126)**.

---

**PRIOR (2026-07-21, later): review queue LLM-ENRICHED + producer/LLM hardening MERGED ([PR #58](https://github.com/humanaxiom/jd-assistant/pull/58), CI green).**
The 379-draft queue now carries REAL prose: a crash-safe ~10h `gpt-oss:120b` run refreshed all **379 in
place** (384 drafts have real rewrite prose, 291 audited; **0 cluster failures**). Two hardening features
landed on `main` to make that — and the future full-archive run — safe and observable:
- **Producer crash-safety + observability** — `run_canonical_producer` gained `commit_every`/`progress_every`
  (`--commit-every`, default 25): commits BETWEEN clusters (after the SAVEPOINT releases, never a partial),
  stderr progress line. Proven over the 10h run (zero lost work).
- **LLM robustness** — constrained decoding (`json_schema`) **scoped to the AUDIT** (`JDQualityFindings`;
  fixes a ~24% enum-mismatch failure); the **REWRITE stays loose** because `SFUJobDescription`'s large
  grammar 500s Ollama (`failed to load model vocabulary` — the deferred live gate caught this before it
  shipped a zero-prose regression). New per-pass `reasoning_effort` knob: **HR-191** rewrite=`null`,
  **HR-192** quality=`low`.
- **Register 190→192** (both new = `reasoning_effort`; all `open`, 0 ratified; surface 251→253);
  **`rules_version` unchanged** (unhashed). Gates **1784 · 93.94%**. Both live goldens execute+pass.

**NEXT: the 4.5 pilot** on the now real-prose queue (`:25800`), then optionally the full-archive enrichment
on this improved code (audit-complete + faster + rewrite-safe). Docs (HANDOFF/plan/register) brought current.

---

**Phase 4.6 (Visibility & local-only assurance) — COMPLETE, SHIPPED, PUSHED, CI GREEN.** User-reprioritized *ahead* of the 4.5 pilot (the backend was substantial but invisible beyond
"tests pass", and the proprietary archive had to be provably local). All merged to `main` and **pushed**;
CI is green (7m41s full Docker suite — first green run since the billing block); PRs #56/#57 reconciled
(auto-closed as MERGED). **1,773 tests · 93.94% · register in step · `rules_version` unchanged** (this
phase adds no scoring rule). One-pager: **`docs/status/2026-07-21-shipped.md`**. What shipped:

- **Three read-only dashboards** inside the FastAPI `api` service (server-rendered Jinja, under
  `make gates`, no new dep): `/jd-bank/ui/dashboard/{baseline,dedup,clusters}` render committed report
  artifacts (`docs/baseline/summary.json`, `docs/dedup/*.json`, `docs/cluster/cluster-summary.json`),
  reusing the existing `extra="forbid"` report models (verified in-container each REAL artifact
  validates). **Every headline figure is READ from the artifact and mutation-pinned** — hardcoding a
  number turns tests red (the answer to "no visibility besides test-pass claims"). Graceful empty-states
  (200, never 500), incl. per-tier degrade on dedup. The baseline aggregator now emits the **874-JD
  current-practice cohort** as a segment (`SegmentDimension += "cohort"`) so THE headline
  (874 · 78.6% · median 79.05 · A81/B551/C240/D2) lives in the committed artifact; whole-archive rate
  demoted with its "category error — never quote" warning.
- **Egress guard — NN #5 is now a BUILD FAILURE** (`core/src/jd_bank/security/egress.py`).
  `assert_inference_host_allowed(base_url)` raises for any host not on `settings.allowed_inference_hosts`
  (default `aria-gb10-2` + loopback/private; env `ALLOWED_INFERENCE_HOSTS`); BOTH content clients
  (`jd_bank/llm/client.py`, `embeddings/client.py`) call it before building `AsyncOpenAI`. Opus
  security-reviewed: fail-closed mutation-verified, every bypass trick rejected (`aria-gb10-2@api.openai.com`,
  `127.0.0.1.evil.com`, encoded IPs, case, trailing-dot, public IPv6). Evidence: `docs/security/egress-audit.md`.
  **Boundary RATIFIED: "local" = not cloud; internal `aria-gb10-2` OK** (NN #5/ADR-003); dev-box-only declined.
- **Review queue SEEDED (data, not a code merge):** `make canonical-drafts CANONICAL_ARGS="--no-llm
  --limit 5000"` persisted **379 DRAFT canonical_jds** (378 multi-member clusters + 1 singleton; 751
  clusters recomputed from the 133,842 role-equiv edges over the first 5,000 parsed_jds), each with an
  audit-log row. Live UI populated: `/jd-bank/ui/queue` → detail → approve/reject/edit/override. **These
  are DETERMINISTIC 4.1 merge drafts (`--no-llm`, zero egress)** — the 4.2 LLM rewrite/audit
  (`gpt-oss:120b`, guard-permitted) can REFRESH them in place. **`--limit` bounds INPUT parsed_jds rows,
  NOT output drafts** (a 3-row smoke test formed 0 clusters). Seed is DB data; `docs/canonical/summary.json`
  is a partial-run working artifact (not committed).

**NEXT: 4.5 pilot** (5–10 clusters with a real HR reviewer through the now-populated UI). **Open
follow-ups:** ~~LLM-enrich a batch~~ **DONE** — the full 379 seed is LLM-enriched (PR #58 producer
hardening made the 10h run crash-safe); a **full-archive** enrichment (the complete bank) is still open and
should run on the new constrained-decode/`reasoning_effort` code; tighten
2 secondary cluster-KPI pins (`largest_cluster`, `flagged_clusters`) to collision-free sentinels;
review-queue **edit** view is still a raw-JSON `<textarea>` (structured editor deferred); remove the dead
Flask `frontend` compose service (4.6d, not yet done). App runs at `:25800` (`docker compose up -d api`).

**Docs refreshed 2026-07-21 (this session):** `HR-DECISION-MATRIX.md` committed (plain-language HR
decision matrix, verified against `summary.json`) + cross-linked from `HR-REVIEW-PACKET.md` (was
orphaned). Repo-wide staleness swept: decision-register count corrected (now **192** after HR-191/192;
was 119/123/166 in various docs), the 874-cohort grade spread corrected to **81 A / 551 B** (was 82 A / 550 B)
in the packet, baseline README, change-plan, and the register source (regenerated; `register-check` green),
Phase 4.6 marked COMPLETE in `plan.md`, and the egress-guard "not cloud / internal host" wording aligned.

Last updated: 2026-07-20 (**4.4a follow-up DONE — the producer's injected LLM client is now SPLIT into
`rewrite_client`/`audit_client` so the `QualityAudit.model` stamp can't lie once `quality.yaml` retunes
(NN #6); MERGED LOCALLY (PR #57, git-only — GitHub CI still billing-blocked, see 4.4a-followup below).
Gates 1734, 93.89%. 4.5 HR pilot still next. The Phase-4.4 review queue is COMPLETE: producer → service
→ routes → UI.**
`core/src/api/routes/ui.py` is a MINIMAL server-rendered UI INSIDE the FastAPI app (`/jd-bank/ui`) —
chosen over the untested Flask `frontend/` so the human-approval surface stays under `make gates`
(mypy --strict + coverage + TestClient). `GET /queue` · `GET /review/{id}` (404 page on unknown) ·
`POST /review/{id}/{approve,reject,edit}` → 303 to the queue on success, RE-RENDER the detail page with
the error + NO commit on a service error (pinned both directions). Jinja2 templates (`_base`/`review_
queue`/`review_detail`/`review_not_found`) mirror the dashboard theme. TRANSPORT ONLY — the 4.4b service
keeps every invariant; override construction builds one `GateOverride` per FILLED overridable-gate reason
field (blanks skipped, never synthesized — service re-checks). **NO new runtime dependency:**
`request.form()` asserts `python-multipart` (absent) on the installed Starlette even for urlencoded
bodies, so POST bodies parse via stdlib `urllib.parse.parse_qsl` on the raw body. Autoescape on, no
`|safe` on archive text; the 4.3 diff renders from `change_log["harmonization_diff"]`. Reviewer (Opus)
APPROVED after one must-fix (a rendered-draft assertion that was TAUTOLOGICAL with the title — a wrong
`change_log` key would have passed silently, the recurring silent-empty trap; now asserts a draft-unique
string). Gates **1731, 93.67%** (`ui.py` 99%). No knob; `rules_version` untouched. **⚠ MERGED LOCALLY,
NOT via GitHub:** GitHub Actions was billing-blocked at merge time ("recent account payments have failed
/ spending limit") so CI could not run — `main` was fast-forwarded locally (`make gates` is CI-identical
per ADR-006). **PR #56 is open + unmerged on GitHub; re-run its CI and reconcile once billing is fixed.**
Follow-ups (out of scope): the edit view uses a raw JSON `<textarea>` (structured per-field editor
deferred); the pre-existing `jd_core→jd_bank` edge (`parser/store.py`) still open. Prior line — 4.4c
review ROUTES MERGED (PR #55).
`core/src/api/routes/jd_bank.py` is THIN HTTP over the 4.4b service — a `/jd-bank` router on the
harness app. Five endpoints: `GET review/queue?limit=` · `GET review/{id}` (404 on unknown) ·
`POST review/{id}/{approve,reject,edit}` (`reviewer_id` in the BODY, pilot model, no SSO). Routes add
ZERO invariants — the service keeps NN #1 publish gate / validator-as-oracle / override-needs-reason /
append-only audit; a handler unpacks → calls ONE service fn → COMMITS on success → serializes. The ONLY
route logic is the typed-error→status map: `CanonicalNotFound`/None-packet→404; `IllegalTransition`+
`NotApprovable`→409; `GateOverrideError`+`MissingReason`+malformed-edit `ValidationError`→422.
Commit-on-success / no-commit-on-error pinned BOTH directions; TestClient units monkeypatch the service.
Reviewer (Opus) APPROVED, no must-fix, re-ran gates. Gates **1716, 93.61%**. No schema/knob change.
**Two follow-ups (out of scope, recorded):** a pre-existing `jd_core→jd_bank` edge (`parser/store.py`
imports `jd_bank.db.models`) — its own chore; optional `get_session`→`api/deps.py` to drop the router's
bottom-of-file circular-import shim (`# noqa: E402`). Prior line — 4.4b review SERVICE MERGED (PR #54).
`jd_bank/review/service.py` is the human-approval spine (NN #1): list queue / assemble packet /
approve·reject·edit·override over the 4.4a DRAFT canonicals, writing status transition +
`review_actions` + append-only `audit_log`. **approve PUBLISHES only when the gate decision permits**
— it RE-VALIDATES current `content` (validator-as-oracle, NN #3; never trusts the stored `change_log`
roll-up), runs `evaluate_gates`→`apply_overrides`, else raises `NotApprovableError` (the ONLY publish
path). Override needs a written reason (reuses `apply_overrides`). `get_review_packet` surfaces a
FRESHLY recomputed `GateDecision` (stored roll-up display-only — pinned). edit → new `version+1` DRAFT
(prior ARCHIVED, EDIT action on v2); folded in the 4.4a follow-up (producer no-clobber now
`order_by(version desc)`). `FOR UPDATE` lock serializes approves. No schema change, no new knob.
Reviewer (Opus) APPROVED after one must-fix (unpinned packet recompute) + focused confirm. Gates
**1701, 93.54%**. Follow-up: a concurrent double-approve test (lock is real; backlog for the pilot).
Prior line — 4.4a canonical-draft
PRODUCER MERGED (PR #53); 4.4b next.** 4.4a is the first slice of the review queue:
`jd_bank/canonical/runner.py::run_canonical_producer` drives the full Phase-4 pipeline per JDFN
cluster (4.1→4.2a→4.2b→4.3→validator) and PERSISTS a DRAFT `canonical_jds` row — the work-list 4.4b/4.4d
consume. NOTHING publishes (NN #1; draft's `GateDecision.approved=False` while gates block). IDEMPOTENT
(clusters upserted on the stable `cluster_id_for` uuid5; canonical refreshed in place). **NO-CLOBBER**
(a canonical with `status!=DRAFT` OR any `review_actions` row is left byte-identical + counted
`skipped_reviewer_touched` — never overwrites/cascade-deletes a human artifact; mutation-pinned both
halves). APPEND-ONLY `audit_log` per persist/refresh/skip. Best-effort LLM INJECTED + mockable
(`client=None`→deterministic merge draft; per-cluster failure isolates via SAVEPOINT, pinned by
fault-injection). Roll-up + 4.3 diff + provenance live in `canonical_jds.change_log`;
`validation_report_id`=NULL (validation_reports is parsed_jd-keyed). No new knob. Reviewer (Opus)
APPROVED after one must-fix (untested SAVEPOINT branch) + focused confirm. Gates **1678, 93.41%**.
**Two follow-ups (see 4.4 Next-up):** split `rewrite_client`/`audit_client` before the two LLM YAMLs
diverge; multi-version no-clobber lookup for 4.4b. 4.4 slicing (user-chosen): producer→service→routes→
server-rendered UI. 4.3 is the harmonization CHANGE-LOG / per-source diff:
`jd_core/bank/change_log.py::build_harmonization_diff`
4.3 is the harmonization CHANGE-LOG / per-source diff: `jd_core/bank/change_log.py::build_harmonization_diff`
— pure/deterministic/order-invariant, no LLM/DB, gives the 4.4 reviewer a per-source diff (which
sections each member fed; duties kept vs folded/dropped) + a "removed content and why" change log.
Drop-vs-dedup is authoritative from the merge's ACTUAL cap-dropped groups (`merge.dropped_duty_occurrences`),
NOT a Jaccard proxy — the reviewer proved the proxy mislabels a duty that folds into a SURVIVING group
but drifts from its re-picked representative; fixed + mutation-pinned both directions. `merge.py`
exposes shared `canonical_member_order`/`dropped_duty_occurrences`/`unmerged_content` (one home);
`merge_cluster` byte-identical. Frozen `HarmonizationDiff`, no approval/score field (NN #1); NO new
knobs, `rules_version` untouched. Reviewer (Opus) APPROVED after one must-fix round + a focused
mutation-verified confirm. Gates **1655 passing, 93.84%**. Follow-up: a `jd_bank/` runner to produce
change-logs over real clusters (mirrors 4.1's measure-after runner). 4.2b is Phase 4's SECOND LLM pass:
`jd_bank/quality/audit.py::audit_quality` — the NUANCED audit (`inclusive_language`/`clarity`/
`seniority_mismatch`) with a **verbatim-evidence anti-fab scrub** (a finding whose `evidence` is not
found verbatim in the JD is dropped). **Advisory — computes NO score/grade** (validator stays the
oracle, NN #3); frozen `QualityAudit`, no approval field (NN #1). Reuses 4.2a's `ChatClient`
(generalized with optional model/temp overrides) + prompt loader; `flatten_jd` now SHARED in
`jd_bank/jd_text.py`. New **UNHASHED** `quality.yaml` (HR-185..190, all `open`, provisional). Reviewer
(Opus) APPROVED after breaking all four load-bearing mutation pins. Gates **1641 passing, 93.76%**.
Two follow-ups recorded (structural-bar inflation guard for the 4.2a rewrite; provenance-stamp/
category-filter note for 4.4 wiring). 4.2a is Phase 4's FIRST LLM pass: `jd_bank/rewrite/harmonize.py`
rewords the deterministic 4.1 merge draft into cleaner prose via self-hosted Ollama
(`gpt-oss:120b` on `aria-gb10-2`) under an **anti-fabrication guard** — output is an explicit DRAFT
scored by the validator, nothing auto-publishes. Reusable LLM scaffolding landed: `jd_bank/llm/`
`ChatClient` (JSON mode, deterministic temp 0.0, never-retry-400, model from `rules.rewrite.model`)
+ prompt loader (ported `jd_harmonize_v1`). New **UNHASHED** `rewrite.yaml` (HR-176..184, all `open`,
provisional — calibrate at 4.5 pilot). Reviewer (Opus) APPROVED after one must-fix: `_flatten_jd`
dropped the Relationships section from the validator's text so a coded term the LLM wrote there was
invisible to the oracle — fixed + mutation-pinned. Gates **1615 passing, 93.72%**.
4.1 follow-ups #1 (calibrate) + #3 (runner) DONE: the read-only `jd_bank/harmonize/`
runner measured the merge over **1,801 JDFN clusters**; the 9 `harmonization.yaml` knobs are now
registered with measured evidence — **one default moved (`max_duties` 10 → 12**, aligned to the
model's 12-duty cap; `duties_over_max` flag 20.8% → 4.8%), the other 8 kept as measured-well-placed.
Phase 3 complete (3.1–3.5). Archive **99.3% parseable**; **2,458 role clusters** over 14,522 signed
JDs; **133,842 ROLE_EQUIVALENT edges** (clustered at gate 0.75); **9 flagged** for HR review; 75.1%
coverage. Test suite **1577 passing, 93.60%**; HR decision register **175** (HR-167..175 all `open`,
unhashed `harmonization.yaml`; measured evidence written into each `why_it_matters`).)

**Catching up? Read [`docs/status/2026-07-21-shipped.md`](docs/status/2026-07-21-shipped.md) first** —
the current one-pager (Phase 4.6: the read-only dashboards + build-enforced egress guard + seeded review
queue — the backend made visible end to end). The prior
[`2026-07-19-shipped.md`](docs/status/2026-07-19-shipped.md) covers Phase 4.1–4.4 (the harmonization
pipeline + the human-approval review queue). Before that,
[`2026-07-15-shipped.md`](docs/status/2026-07-15-shipped.md) covers 3.2 / 3.3 + the extraction defects;
[`2026-07-13-shipped.md`](docs/status/2026-07-13-shipped.md) covers 2.5 / 2.6 / 3.1.

**PR stack all MERGED:** [#19](https://github.com/humanaxiom/jd-assistant/pull/19) (2.5 baseline)
→ [#22](https://github.com/humanaxiom/jd-assistant/pull/22) (2.6 defects, re-opened after #20 auto-closed)
→ [#21](https://github.com/humanaxiom/jd-assistant/pull/21) (3.1 dedup) → [#23](https://github.com/humanaxiom/jd-assistant/pull/23) (3.2a ingest) → [#24](https://github.com/humanaxiom/jd-assistant/pull/24) (3.2b embeddings)
→ [#26](https://github.com/humanaxiom/jd-assistant/pull/26) (nonstandard ports) → [#27](https://github.com/humanaxiom/jd-assistant/pull/27) (3.3 Tier-2 near-dup) → [#28](https://github.com/humanaxiom/jd-assistant/pull/28) (coverage-rate fix + docs)
→ [#30](https://github.com/humanaxiom/jd-assistant/pull/30) (extraction: docx tables/controls) → [#31](https://github.com/humanaxiom/jd-assistant/pull/31) (baseline refresh)
→ [#32](https://github.com/humanaxiom/jd-assistant/pull/32) (WJQ parser) → [#33](https://github.com/humanaxiom/jd-assistant/pull/33) (baseline at v2)
→ [#34](https://github.com/humanaxiom/jd-assistant/pull/34) (LSH retune) → [#35](https://github.com/humanaxiom/jd-assistant/pull/35) (pipeline refresh).

Repo: **`C:\repos\JD-Assistant`** → GitHub **github.com/humanaxiom/jd-assistant**.

---

## THE HEADLINE. Read this before you believe anything about the archive.

**The archive RATIFIES the approval bar. It does not kill it.** The 2.5 brief (written before the
run) predicted the opposite and told you to expect the bar to die. It didn't. Correcting that
expectation is the single most important thing on this page.

Full deliverable: **`docs/baseline/README.md`** + `summary.json` + `errors.jsonl`.
Regenerate: `make baseline JD_ARCHIVE_PATH=C:/repos/hris/fixtures/SFU_JDs` (~9 min, single-process).

Ran all **14,565** files → 14,522 scored, 43 skipped, every file accounted for.
**Numbers below are post-2.6** (rulebook `jd_rules_sfu_v4+8c004c4dadd1`).

| Population | Approval | |
|---|---|---|
| All scored | ~5% | **A category error. Never quote it.** |
| Era `new` (2019–2023) | 1.0% | **Also an artefact** — the footer gate is a date detector. |
| Era `current` (2024+) | 61.2% | A *date* band, not a practice band. |
| **Current practice** (n=874) | **78.6%** | The bar's real trial. |

On current practice: median **79.0**, **99.8% clear the score floor of 60**, grades 81 A / 551 B /
240 C / 2 D / **zero F**. **The score floor rejects 2 JDs out of 874.**

> ⚠️ **The cohort filter changed in 2.6.** It is now `era ∈ {new, current}` ∧ no
> `SFU-COMP-TERRITORIAL`. The pre-2.6 filter (`era == "new"` alone) now returns **79** JDs, not 874.
> If you get 79, this is why. Stated at the top of `docs/baseline/README.md`.

### 2.6 — three defects that were OURS, not the archive's

The most valuable thing 2.5 produced was not a score. It was finding that **three of our own rules
were broken and were distorting the numbers HR was about to ratify.** Fixed before HR saw anything.

1. **`SFU-STRUCT-HOW-WHY` could never *not* fire** (HR-121). It counted duties lacking `how_why` —
   but `segmenter.py` **never populates that field** ("left empty"). It fired on **100% of the JDs we
   would approve.** Zero discriminating power; a constant subtracted from every score. **Same class
   as the 2.4 `render.py` disaster: faithful to hris, wrong here** — in hris an LLM filled the field;
   our regex parser structurally cannot. Now marked **unevaluable** (data, not code — Phase 4
   reinstates it with one YAML word). Finding **8,593 → 0**. Scores rose on 9,217, unchanged on
   5,305, **fell on 0**. *(Say "every score that carried the finding rose" — NOT "every score rose".)*
2. **`SFU-QUAL-BANNED-PHRASE` scanned the whole document** (HR-120), though its rule text says
   *Qualifications only*. It drove **all 104** `QUAL-MINIMUM` blocks — every one a wrong-section
   match. Now a knob (`banned_phrase_scope`). Blocks **104 → 0**; **+59 approvals** (exactly the JDs
   it was the *sole* blocker of). **This is the entire 71.9% → 78.6% gain.**
3. **The era model conflated two rollouts** (HR-122) — 4th band `current` (2024+) added.

Net: approval **71.9% → 78.6%**, median **77.3 → 79.0**, blocked **246 → 187**, score-floor
rejections **5 → 2**.

### Why every other number lied: one gate is a DATE DETECTOR

`SFU-APPROVE-EDI-FOOTER` blocks 86% of the `new` era — not because those JDs are bad, but because
the **territorial acknowledgement is a rollout still in progress**: 0% (2018) → 0.2% (2019) → 1.4%
(2021) → 11% (2023) → 63% (2024) → 85% (2025) → **88.6% (2026)**. Approval rate tracks adoption
almost exactly, because a blocking gate keyed to the footer *is* an adoption detector.

**The validator is correct and this was checked**: cross-examined `SFU-COMP-TERRITORIAL` against a
raw-text scan of all 6,259 new-era JDs → **10 false positives (0.2%)**. The archive genuinely
doesn't have the paragraph yet.

### The era model was WRONG, and the baseline proved it (HR-109/110/111 → fixed in 2.6, HR-122)

It assumed **one** transition. There are **two, four years apart**: the JDFN *template* rolled out
in 2019; the *acknowledgement/EDI footer* became standard in **2023–24**. `new` captured the first
and was then judged by a gate only the second satisfies — so a 2019 JDFN doc, authored correctly
under the template of its day, was un-approvable. **A 7× gap, all date and no quality.**

Fixed: 4th band `current` (2024+). Bands: `old` 3,339 · `transition` 4,964 · `new` 5,228 ·
`current` 1,034. **A trap we nearly hit:** the `JDFN` token used to override the date band
*outright* — and every JD written today carries it, so a naive 4th band would have collapsed
instantly. The token now **promotes** an old file but never **demotes** a current one.

**Still open (HR's call):** the band is **not** the cohort. `current` (1,034) and current-practice
(874) agree on **795** — 239 JDs dated 2024+ still lack the footer; 79 that carry it predate 2024.
**Quote the cohort for claims about the bar, the band for claims about a date.** Defining "current"
by footer *presence* rather than date is the truer signal and remains HR's decision.

### What the bar ACTUALLY gates (HR-004/019/020/041/042)

Of the **187** current-practice JDs still blocked: `SUMMARY-LENGTH` **134**, `QUAL-EQUIVALENT` 42,
`EDI-FOOTER` 10 … `SCORE-FLOOR` **2**, `GRADE-FLOOR` **2**. (`QUAL-MINIMUM` was 104 → now **0**.)
**HR believes it is ratifying a quality bar. It is ratifying a 100–150 word range.** Say that before
anyone signs. (The one saving grace: that range is SFU's *own published number*, not ours.)

- **⚠️ New open question 2.6 created:** correctly scoped, the banned-phrase list now fires on **10
  files in 14,522**. Either it is a guard-rail nobody trips, or **it is missing the phrases SFU's
  authors actually write.** Needs an experienced JD reviewer, not an engineer. (HR-041)
- **`SFU-APPROVE-QUAL-MINIMUM`'s `overridable: true` rationale has evaporated.** It was justified by
  *"the phrase match spans the whole document"* — which is no longer true. Deliberately left
  overridable (hardening a gate off the back of a bug fix, unratified, is what the register exists
  to prevent), but HR should now decide it **on purpose**. (HR-042)
- **HR-047 blocks ZERO current-practice JDs** (29.4% of the whole archive, 23.4% of
  latest-per-position). A legacy-corpus menace, **not** a threat to what SFU writes today. This is
  the finding everyone expected to be the villain; the data says it isn't. Prioritise accordingly.
- **`evaluable` is a loaded gun — keep it registered.** 2.6 added `RuleSpec.evaluable` to retire
  `HOW-WHY`. It is a switch that can silently disable an inconvenient rule. The reviewer **exploited
  the first version of the guard**: promote a rule to `high` in `titles.yaml` (so it blocks via the
  **severity floor**, not a named gate), then set `evaluable: false` → finding vanishes, approval
  flips, rulebook loads clean. The guard now checks a rule's **maximum reachable severity** (which is
  *not* just `default_severity` — `coded_terms` tiers and `titles.restricted[].severity` override it).
  What stops abuse is that `evaluable` is **registered, on the decision surface, and mutation-pinned**.
  Keep it that way.

### The trap in the distribution — do not fall in it

The `new`-era histogram is bimodal and the floor of 60 sits in the valley. **This is not evidence
the floor is well-placed.** The two modes are "has the acknowledgement" / "doesn't" — the same
rollout again. Within current practice the distribution is **unimodal, centred 70–79**. The floor
is defensible because it is *nearly inert*, not because the data carved a threshold there.

---

## Current state — Phase 4 STARTED (4.1 merge engine MERGED); 4.2 next

**Phase 4.1 — the deterministic harmonization merge engine — is MERGED (PR #46).** A pure,
LLM-free `jd_core/bank/merge.py` (`merge_cluster(members) -> MergedRole`): section selection,
duty union/dedup/reorder, KSA rebuild, composing the existing `provenance`/`signals`/`similarity`
primitives. **The output is an explicit DRAFT — nothing auto-canonical** (non-negotiable #1);
`MergedRole`/`MergeProvenance` are frozen with no approval field. **9 knobs** in the new
**registered-but-UNHASHED** `harmonization.yaml` (HR-167..175, all `open`, `our_invention`) — a
merge-policy change decides how JDs are *merged*, not how a JD is *scored*, so it is excluded from
the `rules_version` digest (same pattern as dedup/embeddings/segmentation). Every knob
mutation-pinned; order-invariance pinned byte-identical; validator-as-oracle honest (the draft
trips the boilerplate gates, never "approved"). Reviewer-approved (Opus) after one round + a
focused confirm — the one real defect (experience-bar inflation: a `frozenset` dropped
`experience_source_kinds`' ordered fallback, so a `knowledge`-blob number could inflate the bar and
get relabeled `kind="experience"`) is fixed and pinned by a regression that goes red under the old
behaviour. **Two follow-ups this created (see Next up):** calibrate the 9 defaults against the real
clusters (a measurement pass, the 3.5 pattern), and the deferred **%-rebalance** of duty allocations.

**Phase 3 is done.** All of 3.1–3.5 are merged and have run over the real archive. The dedup engine (Tier-1 exact, Tier-2 near-dup, Tier-3 role-equivalence) is complete; the clustering runner generated a full cluster report; all core subsystems landed. **Archive is 99.3% parseable and 99.4% covered end-to-end** (parse → embed → dedup). The validation engine, HR decision register, all EXTRACT-eligible `jd_core` modules, the full archive in Postgres, the embedding service (14,395 doc + 36,174 section vectors in Neo4j), Tier-2 near-dup (15,072 edges), Tier-3 role-equivalence (133,842 edges), and role-clustering (2,458 clusters) are all landed.

| Phase | State | PR | Commit |
|---|---|---|---|
| 2.1 rules-as-data (8 versioned YAML + typed loader) | MERGED | [#6](https://github.com/humanaxiom/jd-assistant/pull/6) | `43f29db` |
| 2.2 section validators (29 rules, rulebook-as-code) | MERGED | [#7](https://github.com/humanaxiom/jd-assistant/pull/7) | `9eaa39d` |
| 2.3 gate runner ("never approve if…", 14 gates) | MERGED | [#8](https://github.com/humanaxiom/jd-assistant/pull/8) | `5b8d954` |
| HR decision register (58 decisions, build-enforced) | MERGED | [#9](https://github.com/humanaxiom/jd-assistant/pull/9) | `c519bed` |
| 2.4a bank value objects + provenance + render | MERGED | [#11](https://github.com/humanaxiom/jd-assistant/pull/11) | `43435a7` |
| 2.4b title classifier + Hay signals (tables as data) | MERGED | [#12](https://github.com/humanaxiom/jd-assistant/pull/12) | `b71868a` |
| 2.4c similarity + clustering + drift (pure functions) | MERGED | [#13](https://github.com/humanaxiom/jd-assistant/pull/13) | `58fc7d2` |
| 2.5-prep: HR-058 boilerplate exemption + content-derived `rules_version` | MERGED | [#16](https://github.com/humanaxiom/jd-assistant/pull/16) | `98c0add` |
| scanner hardening: invisible-char + line-wrap folding (HR-108) | MERGED | [#17](https://github.com/humanaxiom/jd-assistant/pull/17) | — |
| **2.5 THE ARCHIVE BASELINE** — trial of the approval bar | MERGED | [#19](https://github.com/humanaxiom/jd-assistant/pull/19) | `7e75835` |
| **2.6 three rulebook defects** — HOW-WHY unevaluable · banned-phrase scope · 4th era band | MERGED | [#22](https://github.com/humanaxiom/jd-assistant/pull/22) | — |
| **3.1 Tier-1 exact dedup** — one file per row; dedup a finding, not a silent collapse | MERGED | [#21](https://github.com/humanaxiom/jd-assistant/pull/21) | — |
| **3.2a archive→Postgres ingest driver** — all 14,565 files in the ledger | MERGED | [#23](https://github.com/humanaxiom/jd-assistant/pull/23) | — |
| **3.2b embedding service** — doc + section vectors on `aria-gb10-2` (Ollama + Neo4j) | MERGED | [#24](https://github.com/humanaxiom/jd-assistant/pull/24) | — |
| **3.3 Tier-2 near-dup** — MinHash/LSH → exact Jaccard; 14,312 edges; the reconcile | MERGED | [#27](https://github.com/humanaxiom/jd-assistant/pull/27) | — |

Test suite: **1518 passing**, coverage **94.02%**, all in Docker via `make gates`. Decision
register grew from 58 to **166 decisions** (3.2b added HR-124..HR-130 for embeddings; 3.3 added HR-131..HR-140 for `dedup.yaml` and amended HR-093; this session added HR-141..HR-148 for WJQ parsing; 3.4a added HR-149..HR-154 for JobSignals; 3.4b added HR-155..HR-160 for Tier-3 role-equivalence; 3.5 added HR-161..HR-166 for clustering).

All 16 EXTRACT-mapped hris modules are now ported or explicitly deferred: `export.py` → 5.4,
the 3 prompt templates (`sfu_jd_extract`/`jd_harmonize`/`jd_quality`) → 4.2, `jd_import_service`
→ 5 (see `docs/audit/hris-reuse-map.md` and Next up, below). 2.4c's `similarity`, `clustering`
and `drift` landed as pure, tested functions **deliberately not wired to anything yet** — the
`ParsedJD → signals` adapter is Phase 3 work (see Next up).

---

## This session: extraction defects FIXED + pipeline refreshed

**Two extraction defects that were silently shrinking the visible archive are BOTH FIXED and the pipeline has been refreshed end-to-end.** The wins are documented with data; HR numbers remain unaffected (the defects were outside the 874-JD current-practice cohort).

### Defect 1: docx table/content-control extraction (PR #30, #31)

`_extract_docx` read only `document.paragraphs`, silently losing all text in TABLES and Word CONTENT CONTROLS (`<w:sdt>`). Fixed with a document-order body walk that recurses into `<w:tbl>` cells and `<w:sdtContent>`. **Measured recovery: files losing everything 24 → 0; files losing >40% of their text 2,596 → 1; ~20.7M characters recovered.** Byte-identical on plain-paragraph docs (bounded blast radius, pinned). Reviewer-approved (Opus), every safety claim mutation-verified.

Baseline regenerated (PR #31): **HR cohort byte-identical** (874, 78.6%, median 79.0) — but the docx fix alone **rescued 3,278 files** from broken parse (parse_confidence <0.10: 4,984 → 1,706).

### Defect 2: WJQ template parser (PR #32, #33)

SFU's **Weighted Job Questionnaire (WJQ) Custom** form — **~4,300 files (29.5% of the archive)** — is a *different document template* the segmenter knew nothing about. A new **marker-routed** segmenter (`parser/wjq.py`) reads WJQ's 14-section template into `SFUJobDescription`; headings/labels/frequency-markers/instruction-cruft live as data in a new **hashed** `rules/wjq.yaml`. Two user decisions: **(1)** duty frequency markers `(D)/(W)/(M)/(S)` → a new additive `SFUDuty.frequency` (marker stripped); **(2)** **WJQ is parse-only and EXCLUDED from the approval-bar cohort** — the 874-JD current-practice cohort gains a `template != wjq` clause (HR-143). WJQ is CUPE; the bar was built only for JDFN/APSA and the rulebook defines no WJQ bar, so scoring WJQ under the JDFN gates is a category error.

`PARSER_VERSION jd_segmenter_v1 → v2`; `ParseResult.template ∈ {jdfn,wjq,unknown}`. Register **HR-141..HR-148** (which took the register to 148; it is **160** after 3.4). Reviewer-approved (Opus) after two rounds and **two real defects**, both proven on the archive and both the class gates-green hides: (a) an uncapped summary fallback that **raised on 568 real files**; (b) loose union markers that **misrouted 69 genuine JDFN JDs** into WJQ — fixed with two-tier detection, misroutes 69→3.

Baseline regenerated at v2 (PR #33): **HR cohort BYTE-IDENTICAL** (874, 78.6% approval / 687, median 79.0, grades 81A/551B/240C/2D) — the `template != wjq` exclusion did its job. Template facet: **jdfn 10,222 / wjq 4,300 / 43 skipped**.

### The combined coverage win

**Archive-wide broken parses (parse_confidence < 0.10): 4,984 → 1,706 (docx) → 105 (WJQ). The archive is now 99.3% parseable.** Of the 4,300 WJQ files, only 43 remain broken.

### The pipeline refresh (PR #34, #35)

`PARSER_VERSION v2` forced a full re-parse. Re-ran ingest → embed → near-dup with measured results:
- **Re-parse:** 14,522 fresh v2 `parsed_jds` rows.
- **Re-embed:** documents with a vector **9,517 → 14,395**; section vectors **22,922 → 36,174**; empty-serialization documents **5,005 → 118**. **11 documents hit `bad_requests`** — denser WJQ text still exceeds the model's 8192-token limit after truncation to `max_chars=10000`. Runner isolates+skips them (no crash), sections still embed — a 0.08% doc-vector gap + a `max_chars` follow-up.
- **near-dup LSH retune (PR #34):** the recovered text (WJQ boilerplate, nearly identical across ~4,300 files) blew candidate count past `max_candidate_pairs` at the old `bands=32/rows=4`. Retuned to **`bands=16/rows=8`** (midpoint 0.707): **candidates 98,193+ → 23,705, edges 15,082 → 15,080** (unchanged — the boilerplate was candidate waste that never became an edge at jaccard_min=0.85). HR-136/137 updated.
- **Re-near-dup:** **15,072 edges** (was 14,312 pre-fix), 99.6% coverage; reconcile updated 13,917 / wrote 1,155 / pruned 395. Cross-position still dominant (68%).
- **Archive now ~99.4% covered end-to-end (parse → embed → dedup).**

**The full archive is in Postgres.** Every measured count independently reproduces:

| PostgreSQL | Value | Validates against |
|---|---|---|
| `source_documents` (one row per file) | **14,565** | 3.1's ledger property |
| `parsed_jds` scored | **14,522** | 2.5 baseline "14,522 scored" |
| `parsed_jds` failed or unsupported | **43** | 2.5 baseline "43 skipped" |
| Distinct `sha256` | 12,593 | — |
| Duplicate files (1,972 redundant) | **1,972** | 3.1's measured count, exactly |

**Phase 3.2a — the ingest driver.** Two blocking defects had to be fixed first:
1. **`parse_and_store` was not idempotent** — unconditional INSERT, no unique constraint. Two runs
   doubled `parsed_jds`, each row a fresh UUID, orphaning every vector. Fixed: migration **`0003`**
   adds `uq_parsed_source_parser` on `(source_document_id, parser_version)` (parse is a pure
   function). `parse_and_store` now mirrors `ingest_document`'s select→SAVEPOINT-insert→re-select
   shape, and the upgrade **refuses** rather than deleting rows.
2. **Incumbent names would have crossed the network** to `aria-gb10-2`. `ingest_document` computed
   the clean text, persisted the report, and **discarded the text**. The obvious driver would parse
   RAW text carrying incumbent names, violating FIPPA. Fixed: it now returns `IngestOutcome(document, text)`
   and the driver parses the clean text on **every** path, including the resumed one. Also:
   `_stable_reason` extracted to a shared home; `stream_sha256` hashes in 1 MiB chunks so oversized
   files still get a row (3.1's ledger property holds; hashing bytes we refuse to parse was never
   the hazard the cap guards).

**New in the repo:** `make ingest JD_ARCHIVE_PATH=... [INGEST_ARGS=...]`, an `ingest` compose service,
`jd_bank/ingest/driver.py`.

**Phase 3.2b — the embedding service.** Document- **and** section-level embeddings on `aria-gb10-2`
(Ollama client, Neo4j upsert). New rule file `embeddings.yaml`; register entries **HR-124..HR-130**
(all `open`, all `our_invention` — SFU publishes no embedding policy). Every default **measured**
against the live endpoint + all 14,522 parsed JDs:
- Server hard-rejects `400: input length exceeds context length` (no silent truncation).
- Limit is **8192 tokens**; real JD text runs ~1.5 chars/token (legacy boilerplate-heavy `.doc`), so
  practical ceiling is ~12,000 chars.
- Serialized JD lengths over all 14,522: median 2,559 · p99 5,993 · p99.9 8,870 · **max 8,987** ·
  **zero exceed 10,000**. → **`max_chars: 10000`** truncates **nothing** in this archive.
- **`min_section_chars: 40`** excludes 1 summary + 6 duty-blocks in 14,522 — guard-rail, not a filter.
- **`include_title_in_document: false`** — `similarity.py` promises title-agnostic scoring; a title
  in the document vector silently voids that. Mutation-pinned.
- Embeddings **deterministic** (same text → identical vector) + **content-keyed** on `(text_sha256,
  model, embed_stamp)` → idempotent + unchanged corpus writes nothing, calls Ollama zero times.
- Runner **reconciles/prunes** stale vectors (a MERGE-only design would leave dead vectors live in
  the queryable index). The keep-list is derived *before* embedding, so a 400 or transient failure
  never triggers a delete.
- **ADR-003 live-test guard:** `make gates` CAN reach `aria-gb10-2`; **CI never will.** Live tests
  are deselected in pytest `addopts`, `Makefile`, **AND** `.github/workflows/ci.yml` (with
  `--strict-markers`). **`make embed`** runs them opt-in and local-only. New: `docs/embeddings/summary.json`
  (counts + stamps, **never vectors**).

**Gates: 3.2b 1256 passing / 95.55% · 3.3 1368 / 94.90% · after the WJQ parser + extraction fixes 1424 / 95.17%.**

---

## THE BIG NEW FINDING — record this prominently

**Our parser cannot read 29% of the archive.** SFU's **Weighted Job Questionnaire (WJQ) Custom**
form — a *different document template* from the JDFN one the segmenter knows, with headings like
`PART 1: JOB DESCRIPTION` — is **4,226 files (29.1% of the archive)**, and **89% of them (3,771)
parse to ZERO content sections.**

- **34.5% of all parsed JDs (5,005 of 14,522) serialize to zero characters** — nothing to embed.
  WJQ is **75%** of that.
- By era: `old` 34.3% empty · `transition` **52.7%** · `new` 21.5% · `current` **13.8%**. **NOT
  a legacy-only problem** — a 2024 CUPE `.docx` with 9,291 chars of real duties and summary comes
  back with `parse_confidence: 0.02`, zero sections, and a title misread.
- `docs/rulebook/sfu-reference.md` **already documents WJQ Custom** as SFU's point-factor instrument.
  The project knew the *instrument*; the **parser was never taught its document template.**

**Two things keep this from being a crisis, both checked against the archive:**

1. **The HR numbers are CLEAN.** The 874-JD current-practice cohort reproduces exactly from the
   committed baseline artifact, and **ZERO of those JDs have a broken parse** (median `parse_confidence`
   **0.74**). All 4,984 unparsed JDs grade **F, median score 19.0** — they sit entirely inside the
   archive-wide "~5% approval" figure HANDOFF already brands *a category error, never quote it*. **No
   re-baseline needed; the HR packet is unaffected.** In fact this **explains** that number for the
   first time: the archive-wide approval rate is low in large part because a third of the corpus is
   a template we never taught the parser to read.

2. **No rework for 3.2.** The embedding design is content-keyed and idempotent, so when a WJQ parser
   lands, those JDs re-parse to different text → `text_sha256` moves → they **re-embed automatically**.

**The consequence lands on Phase 3, not HR: embeddings and clustering see only ~65% of the archive
until WJQ is parsed.** **File WJQ parser support as a task that BLOCKS 3.5 (clustering)** — a
cluster report produced before it would silently cover 65% of the corpus, which is exactly the trap
2.6 taught (metrics computed on a corpus quietly missing a third of itself). It does **not** block
3.3/3.4.

---

## What 2.5-prep established about the archive — read before you trust any archive claim

Both pre-baseline fixes are merged. **The most valuable output was not the code — it was the
measurements**, because two of the three things we *believed* about the archive turned out to be
false, and only running against the real corpus revealed it.

**Measured on the real archive** (`C:\repos\hris\fixtures\SFU_JDs`, through this repo's own
`ingest/extract.py`; several independent random samples, all agreeing):

| Belief | Reality |
|---|---|
| "Zero-width chars are a routine `.docx` artefact" | **FALSE.** 600–799 `.docx` sampled: **zero** Cf chars, zero soft hyphens, zero ligatures. `<w:softHyphen/>` exists as an XML *element* in 7 files — python-docx drops it before the scanner sees it. The ZWSP fix is correct hardening but moves **~nothing** on this archive. |
| "HR-058 is the archive's highest-frequency false positive" | **Not the biggest one.** The real one was **line-wrapping**: antiword hard-wraps legacy `.doc`, so `"equivalent\n   combination"` read as *missing the equivalency path*. `SFU-QUAL-EQUIVALENT` drops **~50%** (74→35, 97→47, 72→34 across samples — ~10% of legacy JDs). |
| "The territorial-ack + equity footers have HR-058's bug too" | **FALSE.** With the exemption forced off, both produce zero coded terms, zero markers, zero restricted titles. Only `about_sfu` hits. |

**The lesson, and it is now a rule: every claim about the archive must be checked against the
archive.** Two coders and the orchestrator all reasoned confidently from "zero-width chars are
common in .docx". They are not, in this corpus. The reviewer was the only one who looked, and it
overturned the premise of an entire PR — a PR whose false narrative was about to be written into
2.5's provenance.

Also established: the JDs contain **real leftover template instructions** (e.g. *"For each item
start with an action verb and briefly describe WHAT is done…"*, still sitting in a live JD), which
the line-wrap had been hiding from the placeholder gate. Expect 2.5 to surface more of these.

---

## The decision register — read this before touching a rule

`docs/decisions/HR-DECISION-REGISTER.md` (generated by `make register` from
`core/src/jd_core/rules/decision_register.yaml`; `make register-check` fails the build on drift,
also wired into CI). **192 decisions, all `open` — SFU HR has ratified nothing yet, but the packet
is now written and the numbers in it are corrected: `docs/decisions/HR-REVIEW-PACKET.md`.**

Provenance (at 192 entries): **101 our-invention · 72 hris-calibration · 19 SFU-rulebook**. The entire approval
bar — score floor 60.0, grade floor C, the severity floor, the 14-rule blocking set, the 2
non-overridable gates — is **our invention, not an SFU number**. It must be ratified against the
Phase 2.5 archive baseline (see Next up, below).

**Standing rule for all future work:** any non-trivial metric or rule change must be
YAML-configurable — never a code change — and must land with a register entry in the *same* PR.
**If a default looks wrong, register it as `open`. Do not quietly patch it.**

Enforcement (the build fails if): a register config path doesn't resolve against live rules; a
`current_default` drifts from the live value; a param on the 253-item decision surface is
neither registered nor explicitly exempted with a stated reason; or the surface enumerator
itself is shrunk to dodge that check.

### Known false positives / landmines (registered `open`, behaviour deliberately unchanged)

| ID | Issue |
|---|---|
| HR-058 | **FIXED** (PR #16). SFU's mandated "do not edit" About SFU paragraph contains `compassionate`, a **medium** coded term — a compliant JD scored 91.5/A → 81.5/B, and omitting the paragraph tripped `SFU-COMP-ABOUT` instead. The coded-term scan now redacts SFU's mandated passages first. The exemption is granted to SFU's **TEXT** (verbatim, modulo folding), never to a **location** — so coded language cannot be smuggled through by wrapping it in boilerplate-shaped prose (verified against 11 adversarial JDs). |
| HR-108 | Whitespace-run collapsing treats a paragraph break as one space — which would weld two unrelated paragraphs and **invent** findings, including a non-overridable `SFU-STRUCT-PLACEHOLDER` gate trip (a permanently un-approvable JD, no waiver). Default is therefore **paragraph-aware** (`collapse_across_paragraph_break: false`). Measured: the safer default costs **zero** of the −50% `SFU-QUAL-EQUIVALENT` win — both settings give byte-identical findings on the real archive, with the boundary genuinely engaged (100% of `.doc`, 47% of `.docx`). Free insurance. |
| HR-119/121 | ~~`SFU-STRUCT-HOW-WHY` fires on 100% of approvable JDs~~ **FIXED (2.6)** — it was **unevaluable**: the parser never populates `how_why`, so it could never *not* fire. Retired as data; Phase 4 reinstates it with one YAML word once the parser extracts the field. |
| HR-041/120 | ~~`SFU-QUAL-BANNED-PHRASE` scans the whole document~~ **FIXED (2.6)** — blocks 104 → 0, **+59 approvals**. **New open question:** correctly scoped it now fires on **10 files in 14,522** — guard-rail nobody trips, or missing the phrases SFU authors actually write? |
| HR-047 | `action verb` / `how and why` / `what by` are placeholder markers feeding the **non-overridable** no-placeholders gate → a JD that merely discusses action verbs is permanently un-approvable, no waiver. **2.5 measured it: 29.4% of the archive, 23.4% of latest-per-position, but ZERO current-practice JDs — a legacy menace, not a threat to what SFU writes today.** |
| HR-046 | Working-condition markers include `housing`, `parking`, `relocation` → a Parking Services JD naming its own domain is blocked. |
| HR-025 | A single `(50%)` duty allocation escapes SFU's Part-11.6 duty-total gate. |
| HR-048 | The incumbent regex (`\bmy\b\|\bmyself\b\|\bi am\b`) is the whole of Part 2B and it blocks, yet "he is responsible for…" passes. |
| HR-055 | The action-verb glossary is a CLOSED list missing `supports`, `delivers`, `liaises`, `writes` → well-written duties penalised for word choice. |
| HR-029 | 9 of the 31 coded terms are hris additions SFU never published (relabelled `hris_calibration`). |
| HR-059 | The title **seniority ladder** (vp/chief/director/manager/lead/associate/assistant) was shipped by hris as "SFU's official ladder (Toolkit p18-19)" — it is **not in the rulebook** (`chief` appears zero times; the only "VP" is a *restricted* title, Part 3.5). Now data (`titles.yaml :: families`), registered `open`. HR-029 in the title dimension. The *functional* table (analyst/officer/…) IS rulebook-sourced (Part 3.3) and is not in question. |

---

## How we work (KEEP DOING THIS — subagent flow)

Delegate implementation to subagents so the orchestrator's context stays lean. Per task:

1. **Tester+Coder subagent**: strict TDD (failing tests first → implement → `make gates` green in
   Docker), leaves changes uncommitted, reports a tight summary.
2. **Reviewer subagent** (merge-blocking): independently re-runs `make gates`, adversarial audit
   of scope/port-fidelity/quality, returns APPROVED / CHANGES REQUIRED. Route any must-fix back to
   the coder subagent via SendMessage (keeps its context) before PR.
3. **Orchestrator (you)**: on APPROVED, commit → push branch → open PR → watch CI → merge (rebase).

### Model tiering — see `docs/subagent-model-strategy.md`

**Spend on judgment, not on typing. Reviewers are ALWAYS the strongest tier (Opus) — never
downgrade the checker.** Coders may drop to Sonnet/Haiku when the task is well-specified with a
strong mechanical oracle (wiring, transcription, renames, docs). Never downgrade: faithful ports,
rulebook/policy semantics, security-touching diffs, or anything changing a decision parameter.
Tier B/C subagents must STOP and escalate on any judgment call rather than guess.

Why the Reviewer stays expensive: across all four Phase 2 tasks it returned CHANGES REQUIRED
**every time**, and every finding was real — an unpinned 116-verb glossary, a validator that
**crashed** on real archive input, a non-overridable gate that could not fire, and a decision
surface silently missing 4 of 10 rule files. Coders were competent but consistently over-claimed.

---

## Non-negotiables (enforced)

- **Docker-only (ADR-006):** NO host Python/venv/pip. All code/tests/gates/migrations run in
  containers. `make gates` runs the FULL suite (ruff·black·mypy--strict·unit·integration·
  coverage≥80) in the one-shot `gates` compose service — self-contained, CI-identical. Only
  Ollama runs on host metal.
- **Storage (ADR-002):** Neo4j = vectors (768-dim cosine, `nomic-embed-text`) + graph;
  Postgres = all relational/transactional SQL; Redis+arq = queue. **NO pgvector.**
- **Rulebook as tests / as data:** every SFU gate = a failing-fixture + passing-fixture test;
  gates/verb-lists/lexicons live in versioned YAML under `jd_core/rules/`, never hardcoded.
  Validator is the oracle (assert post-state, never verbatim LLM text).
- **Human approval:** canonical JDs are drafts until an HR reviewer approves; nothing
  auto-publishes. Gate overrides require a written reason in the audit log.
- **Local-first / job-not-person:** Ollama only; incumbent names normalized out of canonical JDs
  as a RULEBOOK quality step — NOT a resume-grade privacy gate (these are JDs, not resumes).
- **Claude-only:** the Codex/Copilot harness layers were removed. Don't reintroduce them, pgvector,
  or `make use-*`.

---

## Gotchas learned (save yourself the pain)

- **A test whose docstring NAMES a mechanism must be run against that mechanism being broken —
  otherwise it is a decoy.** 3.3 shipped one: `shingles.py` passed `join_paragraphs=True` and its
  docstring claimed *that* was what made a `.doc` and its `.docx` twin shingle identically. It is
  **inert** — `textnorm.PARAGRAPH` is U+2029 and the tokenizer (`[a-z0-9]+`) discards it, so the token
  stream is identical either way. Making the shingler consult HR-108 — *exactly the regression the
  module exists to prevent* — left **all 20 tests green**, including the one whose docstring said it
  would go red. The property was true; the stated mechanism was false; the pin was worthless. This is
  the **third** appearance of "a correct fix pinned by nothing" (3.2a SAVEPOINT, 3.2b skip-predicate +
  sha→vector binding, 3.3 this). **A green suite proves nothing about a guard you have not tried to
  break — and if a test's docstring explains WHY it holds, break that why and watch it go red.**
- **The reconcile prune deleted DATA on a class the design forgot (3.3).** A transient read failure
  *pruned a document's real near-dup edges*, because the prune scope was derived from rows **fetched**
  rather than documents **read**. The rule: an **unreadable** document is an *unknown, not a "no"* — it
  must never prune. A **below-min-shingles** document is a deterministic function of config+text — it
  **must** (raising `min_shingles` has to delete). Any prune/reconcile you write (Tier-3, re-cluster)
  inherits this: derive the keep-list from what you *successfully processed*, and pin BOTH directions
  (unreadable → no prune; below-threshold → prune).
- **The reviewer paid for itself again: 10 real defects across 3 rounds on 3.2b, 6 on 3.2a, 4 on 3.3.**
  The two most dangerous on each were the **same class — a correct fix pinned by NOTHING**: (3.2a)
  the SAVEPOINT protecting a caller's uncommitted work — the exact bug 3.1 spent a migration fixing
  — had a race test whose racer *committed first*, so the pre-check short-circuited and the guarded
  branch was never reached. (3.2b) dropping `text_sha256` from the skip predicate (the whole
  content-identity guarantee) left all 1242 tests green; reversing the runner's sha→vector binding
  — **every vector on the wrong JD** — left all 12 integration tests green. **All now go red.** The
  standing lesson holds: **a green suite proves nothing about a guard you have not tried to break.**
- **A test fake can make a bug unwritable.** 3.2b's fake embed client keyed vectors on **batch
  index**, so two different texts at the same position got the *same* vector — which made the entire
  class of "this node got the vector of its own text" assertion silently impossible to write. **Fakes
  in this suite must be content-keyed.**
- **An `OSError`-unreadable file still gets no `source_documents` row** (zero such files in the 2.5
  ledger; every one of the 43 is extract-stage or the size cap). Unlike the oversized case, its bytes
  cannot be read *at all*, so `(storage_ref, sha256)` is genuinely unsatisfiable and a sentinel hash
  would collide in Tier-1 with every other unreadable file. Backlog line, not a hole to paper over.
- **`docs/embeddings/`** is bound by the `embed` compose service; keep the `.gitkeep` or Docker
  creates it root-owned.
- **The archive-claim rule caught the orchestrator itself in 2.5 — twice, in mirror image.** (a)
  The Phase 0 census (§8.2) says the territorial footer lives in `word/footer*.xml` and warns a
  body-only extractor will miss it. **That is FALSE for this corpus** — checked across 20 modern
  JDFN docs: it is in `word/document.xml`, and `footer*.xml` had it **zero** times. (b) Having
  verified that 17 of 20 *recent* JDFN docs carry the acknowledgement, the orchestrator nearly
  declared the 81% miss-rate a bug — but those 20 were the **newest 400 files**, the one slice
  where adoption is ~85%. The sample was worthless generalised to the era. It was only caught by
  cross-examining the validator against the raw text of **all 6,259** new-era JDs. **A sample
  drawn from the newest files is not a sample of the corpus. Check the claim against the whole
  archive, not against the slice that is easy to look at.**
- **OLLAMA IS ON `aria-gb10-2`, NOT ON THIS MACHINE — and the local/CI split is the whole story.**
  (ADR-003 amended 2026-07-13.) `docker-compose.yml` said `host.docker.internal` until someone
  checked; it is now `${OLLAMA_BASE_URL:-http://aria-gb10-2:11434/v1}`.
  **Verified from inside the `gates` container:** reachable, `nomic-embed-text` present, **768-dim**
  (matches the ADR-002 Neo4j index — checked, not assumed).

  | | Reaches `aria-gb10-2`? |
  |---|---|
  | **Local `make gates`** | ✅ **YES** |
  | **CI** (`runs-on: ubuntu-latest`, GitHub-hosted) | ❌ **NO, and never will** — a cloud runner cannot route to an internal host |

  So the old claim *"the `gates` container cannot reach host Ollama"* was **false locally and true in
  CI**, for a different reason than it gave — and it had been **deferring work** (the 4.2 prompts).
  **The rule it protected still stands, now enforced by topology rather than policy: `make gates`
  MUST NOT depend on a live model endpoint.** A test that calls Ollama passes on your machine and
  turns CI red — worse than not having the test, because it is intermittent and trains people to
  ignore CI. **Live golden tests are opt-in and local-only** (own make target, or a marker that
  *skips* when the endpoint is unreachable). Unit tests mock the client; integration tests mock the
  embedding call.

  ⚠️ **Data boundary changed.** Non-negotiable #5 no longer says "JD content never leaves this
  machine" — from 3.2, JD text crosses a private network to be embedded. The real invariant (**no
  third-party/cloud LLM API, no vendor egress**) is intact, and `aria-gb10-2` is a **trusted internal
  host**. These are SFU HR records, so **FIPPA applies**: if the inference host ever leaves a trusted
  segment, that is a **compliance decision to re-take, not a config value to edit.**
- **Any `repr()` in an exception message will break baseline reproducibility.** The runner is
  single-process *precisely* to guarantee two runs over the same archive produce byte-identical
  artifacts — that is what the audit trail is made of. Two things have already broken it: antiword's
  random **temp-file path**, and python-docx's **`<_io.BytesIO object at 0x7917...>`** — a heap
  address, straight into the skip ledger, from one real macro-enabled `.docx`. The second was missed
  when the first was fixed *and outlived a "verified byte-identical across two real runs" claim*.
  `_stable_reason` (`baseline/runner.py`) now scrubs both. **If you add an extractor backend, assume
  its exception messages carry per-run noise, and prove reproducibility by running the baseline
  twice — do not assert it.**
- **`segmentation.yaml` is registered but NOT hashed.** It is an ordinary rule file in
  `_FILE_MODELS`, excluded from the `rules_version` digest by `_UNHASHED_FILES = {REGISTER_FILE,
  SEGMENTATION_FILE}` — the exact mechanism `decision_register.yaml` already used. So editing it
  does **not** churn `rules_version` (which is right: it decides which *files* a baseline covers,
  never how a JD is *scored*). Reuse this pattern for any future "registered, but does not change
  what the rules decide about a JD" config. **Do not** give it a bespoke second-config-root
  subsystem — that was tried in 2.5, it forced a `jd_core → jd_bank` layering inversion, and the
  reviewer correctly demanded it be replaced by the one-line exclusion.
- **`jd_core` must not import `jd_bank`** — the rulebook is the pure core. Enforced by a ratchet
  (`test_no_new_core_to_bank_import_appears`, which `lstrip()`s so a lazy in-function import can't
  slip it) plus `test_the_rulebook_never_imports_jd_bank`. One pre-existing edge is pinned:
  `jd_core/parser/store.py` imports `jd_bank.db.models` (a persistence adapter; a genuine leaf, no
  cycle possible). **Backlog: move it.** If you add a re-export to `jd_bank/baseline/__init__.py`
  you will re-create a cycle that kills `get_rules()` — the ratchet is what stands between you and
  that.
- **`rules_version` is now content-derived, and that couples rule edits to `make register`.**
  Since 2.5-prep, `Rules.version` is `jd_rules_sfu_v4+<12-hex digest of the rule content>` — and
  `rules/render.py` renders it into the register Markdown header. So **any change to any rule
  YAML (except `decision_register.yaml`) now fails `make register-check` until you re-run
  `make register`**, even when no register prose changed. That is the intended forcing function
  (the committed register names the exact rulebook it describes), but it is new and it looks like
  a spurious CI failure the first time it bites. `decision_register.yaml` is deliberately excluded
  from the digest, so editing register prose does *not* churn the version.
- **The `gates` container mounts only `./core` at `/app`.** Tests must be self-contained under
  `core/tests/`; `docs/` and repo-root fixtures are NOT visible in it.
- **testcontainers work in the `gates` service** (Docker socket mounted + host-override env vars).
  Integration tests can run the real Alembic migration against a fresh PG.
- **`.gitattributes`** forces LF (so container shell scripts survive Windows) and marks binary
  fixtures — don't let CRLF/text filters corrupt binaries.
- `hris` (`C:\repos\hris`) is READ-ONLY reference for ports. `agent-harnesses-v2` is the live
  upstream harness this repo vendors (ADR-004). `C:\repos\jdbank` is STALE — ignore it.
- **Docker artifacts are now `jd-bank-*`** (compose project renamed from `agent-harness`, PR #14).
  `core/src/agents/` and `harness-claude-code/` keep harness naming — that IS the vendored harness,
  and the "built on agent-harnesses-v2" doc lines are true provenance, not stale names. The Neo4j
  password is still `harnesspass`: a **credential**, not a project name — renaming it is a
  behavioural change, not cosmetics.
- **"Faithful to hris" ≠ "correct here" — the most expensive lesson of Phase 2.4.** A *verified
  line-by-line faithful* port of `render.py` still shipped a data-corrupting bug: it emitted
  `PROBLEM SOLVING & LEVEL OF SUPERVISION`, which this repo's parser (`fullmatch`, ` AND ` only)
  cannot read — so re-parsing a rendered JD silently swallowed the entire Problem Solving section
  and the validators then misfired on a JD that was complete. It was harmless in hris because hris
  re-parsed **with an LLM**; here the reader is a regex. Gates were green throughout. **Every port
  lands in a repo whose consumers differ from hris's — check the consumer, not just the source.**
- **One rulebook fact, one home.** The `max_listed` duplicate-knob landmine turned out to be
  systemic: the same shape appeared three more times in 2.4 (Hay modifiers, the two education
  ladders, education cues). All are now closed with **load-time cross-file validators** — rename a
  term in one file and the rulebook *fails to load* instead of silently zeroing a score. Reuse that
  pattern (`loader.py`: `_hay_modifiers_exist_on_the_rulebooks_own_scales`) whenever a vocabulary
  is referenced from two files, and close the outstanding `max_listed` item the same way.
- **A green `make register-check` does NOT mean "everything is registered."** It only diffs the
  register *Markdown*. Surface coverage is enforced by **`make gates`** (the `_OFF_SURFACE` guard
  test in `tests/unit/test_decision_register.py`). Run both.
- **Prove a decision is pinned by MUTATION, not by reading the test.** The bar: change the shipped
  YAML value *and update the register in step so the drift alarm is silent* — a **behavioural** test
  must still go red. Tests that pin only the branch let HR move the number with nothing failing.

---

## Next up

### ⏭ Phase 4 — Harmonization & review. **4.1 merge engine MERGED + calibrated; 4.2 next.**

Task files now live under `docs/tasks/` (`phase-4.1-merge-engine.md` and
`phase-4.1-followup-merge-runner.md` are the templates — goal / files-in-scope / design contract /
acceptance / out-of-scope).

- **4.1 merge engine — DONE (PR #46).** See Current state. Pure `bank/merge.py`, drafts only.
- **4.1 calibration + runner — DONE (this session).** The `jd_bank/harmonize/` measurement runner and
  the knob calibration (follow-ups #1/#3). One default moved (`max_duties` 10 → 12), 8 kept with
  measured evidence in the register. `docs/harmonize/summary.json` is the measurement of record.
- **4.2a harmonize rewrite pass — DONE (PR #49).** LLM scaffolding (`jd_bank/llm/` `ChatClient` +
  prompt loader, ported `jd_harmonize_v1`) + the consumer `jd_bank/rewrite/harmonize.py::rewrite_merged_role`:
  feeds the GROUNDED 4.1 draft (not raw members), anti-fabrication guard scrubs ungrounded
  skill/knowledge/ability quals + flags invented duties, scores via the validator → frozen
  `RewrittenDraft` (no approval field, NN #1). `rewrite.yaml` REGISTERED + UNHASHED (wording ≠
  scoring; not in `rules_version`), HR-176..184 all `open`/`our_invention`, PROVISIONAL. Live golden
  opt-in/local-only (`make rewrite-golden`). Task file: `docs/tasks/phase-4.2a-harmonize-rewrite.md`.
- **4.2b quality audit pass — DONE (PR #51).** `jd_bank/quality/audit.py::audit_quality(jd)` — the
  nuanced LLM pass (`inclusive_language`/`clarity`/`seniority_mismatch`) with the **verbatim-evidence
  anti-fab scrub** (a finding whose `evidence` is not a casefold substring of the JD is DROPPED,
  ported from hris `_merge_llm_findings`). **Advisory: computes NO score/grade** — the deterministic
  validator stays the oracle (NN #3); frozen `QualityAudit` has no approval/canonical field (NN #1).
  Reuses 4.2a's `ChatClient` (now generalized with optional `model`/`temperature` overrides,
  back-compat) + prompt loader. `_flatten_jd` extracted to a SHARED `jd_bank/jd_text.py::flatten_jd`
  (the 4.2a Relationships must-fix made structural — audit haystack == rewrite serialization, one
  home). New `quality.yaml` REGISTERED + UNHASHED (7th unhashed file), HR-185..190 all
  `open`/`our_invention`, PROVISIONAL (calibrate at 4.5). `make quality-golden` opt-in/local-only.
  Reviewer (Opus) APPROVED — independently re-ran gates and broke all four load-bearing pins
  (guard-off ships the fabricated finding; flattener dropping a section reds the Relationships pin;
  wrong model source reds; un-hashing reds). Task file: `docs/tasks/phase-4.2b-quality-audit.md`.
  Gates **1641 passing, 93.76%**. Two follow-ups it created (see below).
- **4.3 change-log/diff — DONE (PR #52).** Pure `jd_core/bank/change_log.py::build_harmonization_diff(merged, members, *, rewrite=None)`
  → frozen `HarmonizationDiff` (`rendered_draft` via `render.py` display-only, `per_source`
  `SourceContribution`, `removed` `RemovedContent`, `flagged_duties`). Reuses the merge's exact
  ordering + group fate (shared public `merge.canonical_member_order`/`dropped_duty_occurrences`/
  `unmerged_content`; `merge_cluster` byte-identical). Optional 4.2a rewrite folding (scrubbed skills →
  `removed`; flagged duties → `flagged_duties`, not removed). NO new knobs; `rules_version` untouched.
  Task file: `docs/tasks/phase-4.3-change-log-diff.md`. **Follow-up:** a `jd_bank/` runner that loads
  real clusters and writes a change-log artifact over the archive (out of scope in 4.3 — the pure
  generator landed first, exactly as the 4.1 merge engine did before its measurement runner). **⚠ the
  `removed` list is NOT exhaustive over the KSA rebuild's incidental non-core-skill drops** — those are
  deliberately outside `RemovedReason`, visible instead via `MergeProvenance.skill_frequency` (noted in
  the `change_log.py` docstring); the runner/4.4 UI should surface skill_frequency alongside `removed`.
- **4.4 review queue — decomposed (user-chosen slicing): producer → service → routes → server-rendered UI.**
  - **4.4a canonical-draft PRODUCER — DONE (PR #53).** See header. Clusters → persisted DRAFT `canonical_jds`.
    Task file: `docs/tasks/phase-4.4a-canonical-draft-producer.md`.
  - **4.4b review SERVICE + audit — DONE (PR #54).** `jd_bank/review/service.py` — list_review_queue /
    get_review_packet / approve / reject / edit over the DRAFT canonicals; the human-approval spine (see
    header). Task file: `docs/tasks/phase-4.4b-review-service.md`. **Follow-up:** a concurrent double-approve
    test (the `FOR UPDATE` lock is real + the sequential stale-status guard is pinned, so the invariant holds;
    a true concurrency test is a pilot backlog line).
  - **4.4c FastAPI routes — DONE (PR #55).** See header. Thin `/jd-bank` router over the 4.4b service
    (`core/src/api/routes/jd_bank.py`), TestClient-tested, error→status map + commit discipline pinned.
    Task file: `docs/tasks/phase-4.4c-review-routes.md`. Two follow-ups (both out of scope, in header):
    pre-existing `jd_core→jd_bank` edge in `parser/store.py`; optional `get_session`→`api/deps.py`.
  - **4.4d server-rendered UI — DONE (PR #56, MERGED LOCALLY — GitHub CI billing-blocked, PR still open).**
    See header. Minimal `/jd-bank/ui` inside FastAPI (user-chosen: server-rendered, gated). Task file:
    `docs/tasks/phase-4.4d-review-ui.md`. **Reconcile PR #56 on GitHub once Actions billing is restored**
    (re-run CI; the branch `feat/4.4d-review-ui` is already ff-merged into local `main`). Follow-ups: the
    edit view's raw-JSON `<textarea>` → a structured per-field editor; surface
    `MergeProvenance.skill_frequency` alongside the 4.3 `removed` list (not exhaustive over incidental
    KSA-rebuild skill drops — 4.3 note) — neither built in 4.4d (minimal).
  - **4.5 — NEXT.** Pilot 5–10 clusters with a real HR reviewer over the now-complete review queue
    (producer → service → routes → UI); feedback → fixtures/rules. Every pilot bug becomes a regression
    fixture (NN #7). This is where the 4.2/4.3/4.4 provisional `open` defaults get calibrated against a
    human's judgment.
- **4.4a follow-up — DONE (PR #57, MERGED LOCALLY — GitHub CI still billing-blocked, PR open).** Split the
  injected LLM `client` into `rewrite_client` (bound to `rules.rewrite.model`, the `ChatClient` default) +
  `audit_client` (bound EXPLICITLY to `rules.quality.model`/`temperature`). `run_canonical_producer` /
  `_process_cluster` / `_run_llm_passes` take both; `llm_enabled = rewrite_client is not None`; the advisory
  audit runs only when an `audit_client` is provided; `rewrite_client=None` is the deterministic `--no-llm`
  path. New `__main__._build_clients(rules, *, no_llm)` constructs the pair (both-or-neither) and `_run`
  closes both. **Why it mattered:** `audit_quality` always stamps `QualityAudit.model = rules.quality.model`
  from the RULES, not the client — so with one rewrite-bound client the audit stamp becomes a lie the moment
  `quality.yaml` is retuned (NN #6). Today the two YAMLs are byte-identical so nothing lied yet; the split
  makes the audit follow `quality.yaml`. **Pure wiring — no rules/YAML/register/schema change** (registered
  nothing, as specified). Two pins, both proven RED by the Opus reviewer under their regression: routing
  (distinct fakes each see only their own schema — re-merging reds it) + binding (`_build_clients` forces
  the two models apart so identical defaults can't mask a regression). Gates **1734, 93.89%**. **Reconcile
  PR #57 on GitHub once Actions billing is restored** (branch `chore/4.4a-split-llm-clients` is ff-merged
  into local `main`; the "Gate: branch-name" failure is the billing block — the runner never starts — not a
  real gate failure, same as #56).

**Follow-ups 4.2b created:**
- **Structural-bar inflation guard (DEFERRED, its own task).** Decided in 4.2b, NOT implemented: the
  4.2a *rewrite* guard scrubs only `skill/knowledge/ability`, so an LLM inflating "Bachelor's → PhD"
  in a rewrite still passes (same class as the 4.1 experience-bar-inflation defect). 4.2b's audit is
  READ-ONLY and cannot inflate a bar, so the risk lives in 4.2a. Catching it needs a level-COMPARISON
  (education ordinal / experience years), not the token-grounding the guard does — a deliberate change
  with its own blast radius. Register `open` when added.
- **Provenance stamp can outrun the injected client (4.4 wiring note).** `audit_quality` stamps
  `QualityAudit.model = rules.quality.model`, but the `ChatClient` is injected and could be bound to a
  different model (faithful to 4.2a's `rewrite_merged_role` pattern — nothing asserts stamp == actual
  client model). When 4.4 wires the caller, bind `ChatClient(model=rules.quality.model, ...)` so the
  stamp cannot lie. Optional defense-in-depth: pin the scrub's accepted categories to the 3 nuanced
  ones (`JDQualityFinding.category` currently accepts all 9 `JDIssueCategory` values; only the system
  prompt, not code, constrains output — a model returning a structural category with grounded evidence
  passes through as an advisory `source="llm"` issue). Within contract today (audit is advisory), but
  worth closing.

**Follow-ups 4.1 created (do before/with the harmonization pilot):**
1. ✅ **DONE (this session) — calibrated the 9 `harmonization.yaml` defaults against the real
   clusters.** Built the runner (#3 below), ran the merge over **1,801 JDFN clusters**, measured the
   distributions each knob cuts on, and registered the measured evidence into HR-167..175 (so none
   hardens by inertia — the HR-093/HR-121 lesson). **Only ONE default moved: `max_duties` 10 → 12**
   (HR-172), aligned to the model's own `duties` cap (`parsed_jd.py:104`, `max_length=12`): at 10 the
   `duties_over_max` flag fired on 374/20.8% of clusters, 288 of which held 11–12 duties the model
   could keep; at 12 it fires only on the 86/4.8% where the cap forces a *real* drop. Mutation-pinned
   (reverting to 10 goes red on a behavioural assertion, not the drift alarm). The other 8 knobs are
   **well-supported as-is** and kept: `duty_dedup_jaccard_min` 0.7 sits at the pairwise-Jaccard
   **valley floor** (global min 0.70–0.75; outcome threshold-insensitive); `core_skill_min_fraction`
   0.5 sits in the sparse valley of a bimodal skill distribution; the title/summary/context/presence
   policies all match the measured shape. Artifacts: **`docs/harmonize/summary.json`** (the measured
   distributions) + `clusters.csv` (per-cluster scalars, counts-only). See Current state.
2. **%-rebalance of duty allocations — DEFERRED from 4.1, its own task.** Allocations are free-text
   `(NN%)` inside duty statements (validator regex, Part-11.6 duty-total gate), **not** a structured
   `SFUDuty` field. Merged drafts currently carry duty statements *verbatim*, so a merge of two
   members can produce allocations that don't sum to 100. Rebalancing needs allocation extraction +
   the Part-11.6 gate interaction — a deliberate change, not a drive-by.
3. ✅ **DONE (this session) — the `jd_bank/harmonize/` runner that loads real clusters and drives the
   merge.** Read-only (rollback, no `Cluster` row), deterministic (byte-identical over two runs),
   single-process. Recomputes clusters in-process via `run_clustering` (NOT the lossy filename-keyed
   3.5 CSV), reloads each member `SFUJobDescription` (`signals_load.load_member_jds`), JDFN-only.
   `make harmonize-measure` + a `harmonize` compose service. This is where #1's measurement ran.
4. **The un-merged sections** (`decision_making` / `problem_solving` / `relationships` /
   `position_number`) are left at model defaults by 4.1 and surfaced by the `sections_not_merged`
   provenance flag. Merging them each needs its own registered per-section policy — fold into 4.2/4.3
   or a dedicated task; the flag keeps the gap honest for the 4.4 reviewer meanwhile. **Measured: the
   flag fires on 1,762/1,801 (97.8%) of JDFN clusters** — nearly universal, so the un-merged sections
   are the norm, not an edge case. Prioritise a per-section merge policy accordingly.
5. **WJQ harmonization stays BLOCKED** on WJQ boilerplate redaction + `.doc` title extraction (the
   Phase-4-priority follow-ups from Phase 3) — the merge engine is exercised on JDFN clusters only.

**New follow-ups this calibration created:**
6. **Persist `ParseResult.template`.** `jd_core/parser/store.py` drops it, so the harmonize runner
   filters WJQ by the `employee_group == "cupe"` proxy — which conservatively **over-excludes ~189
   genuine JDFN docs that merely name CUPE** (safe direction for the JDFN bar, and *counted*, never
   silent — but imprecise). Persisting `template` makes WJQ filtering exact here and unblocks the WJQ
   work (#5). A schema/parse-key change, its own task.
7. **The 3.5 cluster artifacts leak JD prose the same way `clusters.csv` almost did** — `docs/cluster/
   cluster-report.csv` + `cluster-members.csv` commit `cluster_label` = the modal member `title`,
   which the parser frequently fills with a whole summary/boilerplate paragraph (~46% of rows). Same
   root cause the 4.1-followup reviewer caught and we fixed in `harmonize/clusters.csv` (dropped the
   `label` column; pinned by `test_clusters_csv_has_no_jd_title_or_text_derived_column`). **Scrub the
   3.5 artifacts on a chore branch** (drop/replace the prose label), NOT mid-feature. Artifact-hygiene,
   not a privacy breach (JD prose, not incumbent PII), but these are HR records and the rule is
   counts/labels/filenames only.
8. **`seniority_bar_policy` max-vs-modal is an HR policy call, not an engineering one.** Measured: bars
   rarely diverge (education spread 0 in 817/844; experience 0 in 756/843), but `max` differs from
   `modal` on ~77 clusters. Kept `max` (do not understate a stated requirement), registered HR-175 —
   but whether a harmonized role should take the **highest** or the **most-common** stated bar is a
   ruling for the 4.5 pilot, not a default to flip unilaterally.

### ⏭ HR ratification. **Read `docs/decisions/HR-REVIEW-PACKET.md` + `POST-REVIEW-CHANGE-PLAN.md`.**

**Phase 2.6 is done: the three defects that were distorting HR's numbers are fixed and the archive
is re-baselined.** So the packet HR reads now carries *corrected* figures — we fixed first, then
asked. **Keep doing it in that order.**

What remains is genuinely HR's (6 decisions): the 100–150 word range that is the *real* gatekeeper;
the un-appealable no-placeholders gate (recommend making it waivable); the footer gate that blocks
94% of the archive (recommend the composer auto-inserts the boilerplate instead of penalising
authors); the score/grade/severity floors (recommend ratify — they reject 2 of 874); whether the
banned-phrase list is missing the phrases SFU authors actually use; and whether "current" should mean
a date or the footer's presence.

Recording a ruling: flip `status: open` → `ratified` and set `decided_by` / `decided_on` /
`decision_note`. **The loader enforces all three** — a ratified entry without them fails to load. Use
it; do not invent a side file.

> ⛔ **Do not** hand HR a number, collect ratifications, and *then* fix a bug that moves it. The
> register would record "HR ratified 60.0" against a distribution that no longer exists.

⚠️ **If the footer gate is auto-inserted (recommended):** CLAUDE.md's standing open flag —
*"territorial acknowledgement wording: verify against SFU's current official text"* — **becomes
blocking**, because we would then be *generating* the wording, not merely checking for it. Get the
official text from HR in the same review.

- **Phase 3 — dedup & clustering. ✅ ALL COMPLETE (3.1–3.5 merged and run).** Cluster report generated with 2,458 clusters; 9 flagged for HR review. Phase 4 (harmonization & review) is next.**
  - **3.1 landed a schema change worth knowing:** `source_documents` is now **one row per FILE**
    (the UNIQUE on `sha256` is gone), and dedup is a **finding** — `DedupEdge` rows — not a silent
    write-time collapse. It was a **provenance bug**: `ingest_document()` returned the existing row
    on a duplicate SHA, so ~1,972 duplicate files would have been ingested with their filenames
    **discarded entirely**, while `DedupTier`/`DedupEdge` sat dead (an edge needs two source ids;
    the duplicate never got one). All three tiers now write into the same edge table.
  - **The 3.1 finding that matters for 3.5:** **798 of the 1,037 duplicate groups (77%) span more
    than one `position_id`** — 2,463 files. Those are **not re-saves**; they are *distinct positions
    sharing a byte-identical JD*. Only 141 groups are genuine re-saves. **Tier-1 hands clustering a
    role cluster with similarity pinned at 1.0, for free, before a single embedding is computed.**
  - **3.3 (Tier-2 near-dup) is DONE and RAN: 14,312 near-dup edges** over the archive (MinHash/LSH on
    word-5-gram shingles → **exact Jaccard** confirm, `jaccard_min: 0.85`). **67.5% of edges span
    different positions** — cross-position cloning again, consistent with 3.1's 77%. The reconcile is
    proven idempotent on the real corpus (2nd pass: 0 written / 0 updated / 0 pruned). Two measurements
    settled the design, both now in `dedup.yaml` + register HR-131..HR-140:
    - 🔴 **`clone_threshold: 0.92` IS MEANINGLESS ON THIS CORPUS, and now it is MEASURED, not
      predicted.** Nearest-neighbour document cosine: median **0.988**, **98% of JDs have a neighbour
      ≥ 0.92** — a cosine bar confirms *everything*. Word-5-gram Jaccard on the same corpus discriminates
      hugely: NN median **0.126**, random-pair median **0.0022** (p99.9 = 0.30). So **Jaccard drives and
      `cosine_confirm_min` ships `null` (OFF)** — the path is implemented and tested, but a filter that
      can never reject is HR-121's dead gate inverted. **HR-093 is amended with this measurement; it must
      be re-derived before Tier-3 uses it.** Never quote a document-cosine similarity as evidence two SFU
      JDs are the same role without stating the baseline neighbour cosine.
    - 🔴 **The obvious oracle is WORSE than no oracle.** "Same `position_id` ⇒ duplicate" fails: same-
      position pairs median Jaccard **0.30**; cross-position LSH candidates median **0.58** — *the
      negatives are more similar than the positives*. Tuning `jaccard_min` on it pushes the threshold the
      wrong way. `fixtures/labels/pairs.csv` (12 near-dup positives / 44 files / `best_guess_label` column
      / authored against a census this repo later caught being wrong) **cannot be a precision/recall CI
      gate** — one error swings recall 8 points. 3.3 ships a **pinned behavioural fixture** (exact
      candidates/Jaccards/edges — move a knob → red) + an **adjudication sample**
      (`docs/dedup/near-dup-adjudication-sample.csv`, 192 stratified pairs, empty `human_label`) so a real
      label set can finally be built. *The old one is bad precisely because nobody ever generated
      candidates to adjudicate.*
    - **Two structural decisions carried forward:** Tier-2 edges are **NOT additive** (a Jaccard edge is
      only true relative to a threshold + shingle config), so the runner **reconciles: insert / update /
      prune** — a MERGE-only design would leave the DB full of edges from a config that no longer exists.
      And the EXACT/NEAR ladder is closed **structurally** (candidates generated over one signature per
      distinct `sha256`), pinned by a 6-member star-group test — the naive "skip pairs with an EXACT edge"
      check is wrong under Tier-1's `star` topology (only 5 of a 6-group's 15 pairs carry an edge, so it
      would write the other 10).
  - ✅ **Both extraction defects DONE.** WJQ Custom template parser (#32, #33) and `_extract_docx`
    tables/controls fix (#30, #31) are merged. Archive-wide broken parses: 4,984 → 1,706 → 105 (99.3%).
    **3.5 clustering is now UNBLOCKED.** Plus: **WJQ boilerplate redaction** (14-section scaffolding
    near-identical across ~4,300 files) inflates their mutual similarity and is a **Phase-3.5 quality
    follow-up** — not a blocker, but WJQ files will over-cluster on shared template unless the scaffolding
    is redacted like JDFN's About-SFU/territorial/EDI passages.
  - ✅ **3.4a — ParsedJD → JobSignals adapter + title normalizer** (PR #38, MERGED). Wired 2.4c's pure-but-uncalled `similarity`/`clustering`/`drift`. New `jd_core/bank/signals.py`: `build_job_signals(jd) -> JobSignals` (skills = an **idf-less keyword bag** from `{skill,knowledge,ability}` quals minus stopwords — honestly degraded vs an ontology, empty for ~41% of JDs with no quals) + `canonical_title`. Frozen `JobSignals`/`CanonicalTitle` in `models/bank.py`. Two measured drift fixes: **word-number years** (1,116 → 5,573 derivable) and **education from `[education, knowledge]` quals** (JDFN's degree in `knowledge` blob → 1,161 false-positive "bachelors" reduced to 4 FPs). Register **HR-149..HR-154**; ADR-007. Reviewer-approved (Opus); the one defect (all-6-kinds education FP) caught by measuring against the archive.
  - ✅ **3.4b — Tier-3 role-equivalence runner** (PR #39, MERGED). Writes `DedupEdge(tier=ROLE_EQUIVALENT)` blending doc-vector cosine + idf skill overlap + seniority via 2.4c's `score_job_similarity`. **Two user decisions:** skills = the idf keyword bag (`families={}`, ontology deferred; idf computed in-runner, floored at 0); the over-merge guard = **title-family-band CONFLICT veto** (bands >`max_band_gap`(1) apart never role-equivalent; `employee_group` soft veto both-known-and-differ; `grade` unused). **`role_equiv_threshold = 0.5`** — measured: 99.2% pos / 3.0% neg. **Honest limitations, all registered:** 70% of titles `family=="unmapped"` so band veto is partial (~30%); positives are Tier-2 weak labels (no honest P/R gate — ships pinned fixture + stratified adjudication sample); blended score bimodal (41% empty-skills pairs floor ~0.52). Register **HR-155..HR-160**; `make dedup-role` + compose service. Reviewer-approved (Opus) after one round; **two defects were real crashes on real data that synthetic fixtures hid** — near-identical 768-dim embeddings compute cosine >1.0 (16% of real pairs) → ValidationError; ubiquitous skill's negative idf. Both clamped + pinned with real-magnitude fixtures. **Perf follow-up (HR-159 note):** candidate gen O(bucket²) in 8,215-doc `unmapped` bucket (~1hr whole-archive; completes) — Neo4j vector-index top-k is the follow-up.
  - ✅ **3.4b Tier-3 archive run** (PR #41) — **COMPLETE**. `make dedup-role` over full archive: **133,842 ROLE_EQUIVALENT edges** at the **0.75 threshold** (260,357 candidates → 4,248 vetoed → 256,109 admissible → 133,842 qualifying). Measured clustering knee: the measured bimodal score distribution (41% empty-skills pairs floor ~0.52; 59% floor ~0.68) collapses into a single **8,884-JD blob** at 0.5; breaks at gate 0.75. Per-tier edge admission strategy finalized: EXACT/NEAR always-in, ROLE gated at `cluster_role_equiv_min=0.75` (the measured knee). Writes `docs/dedup/role-equiv-summary.json` + `role-equiv-adjudication-sample.csv`.
  - ✅ **3.5 clustering runner** (PR #42, MERGED) — **report-only, not persistent** (re-cluster reconcile would cascade-delete approved canonicals; report suffices). **Per-tier edge admission, NOT scalar threshold** (🔴 **key landmine**: edge scores incomparable across tiers [EXACT=1.0, NEAR∈[0.85,1.0], ROLE bimodal ∈[0.5,1.0]]; naive 0.80 threshold silently discards every ROLE edge in [0.5,0.80)). **Synthesize EXACT connectivity in-runner from sha256** (Tier-2 structurally excludes byte-identical pairs). **Two-stage over-merge guard:** edge admissibility (reuse 3.4b band/group veto) pre-union-find + post-union-find band-spread/group-mix/oversize **cohesion cap that FLAGS (not auto-splits)** for HR eyeball pass. Register **HR-161..HR-166** (cluster_tiers, cluster_role_equiv_min, cluster_max_band_spread, cluster_group_homogeneous, cluster_max_size, cluster_representative_policy) all measured post-run. Reviewer-approved (Opus): the three safety properties (no-Cluster-write/no-commit, the blob guard, EXACT synthesis) verified by mutation against the real 150,879-edge DB. Tests **1518 / 94.02%**.
  - ✅ **The cluster report** (PR #43, Phase-3 EXIT deliverable) — **2,458 role clusters** over 14,522 signed JDs — largest 132, **9 flagged** for HR review, 75.1% coverage, 3,620 singletons. 47,113 edges admitted (103,723 dropped by the 0.75 ROLE gate, 43 by the veto, 1,965 EXACT synthesized). Committed to `docs/cluster/`: `cluster-summary.json`, `cluster-report.csv` (row per cluster, ordered needs-eyes-first, empty `human_verdict` column), `cluster-members.csv` (counts/labels/filenames only, never JD text).
  - 🔴 **Key finding — the report reveals honest clustering quality limits:** the two largest flagged clusters ("Untitled Position" n=132 and n=108, both CUPE) are **WJQ `.doc` template artifacts**. WJQ `.doc` title extraction falls back to "Untitled Position" (~94% of WJQ `.doc`), so those files share a title AND the 14-section template scaffolding → they over-cluster on template, not role. The cohesion cap FLAGS them (oversize), not merges — so the report is honest about it. **A trustworthy WJQ cluster report needs two follow-ups: (1) WJQ boilerplate redaction** (redact the 14-section scaffolding before embedding/Tier-3, then re-embed + re-Tier-3 + re-cluster) and **(2) better WJQ `.doc` title extraction** (antiword loses the title label). The report is trustworthy for the JDFN population today.
- ~~**Rulebook work the baseline made urgent**~~ **ALL THREE DONE IN 2.6** (banned-phrase scoping,
  `HOW-WHY` unevaluable, 4th era band). Scores are now trustworthy. What is left is HR's, not ours.
- **Extension-trust is silently losing recoverable JDs** (from the 2.5 skip ledger,
  `docs/baseline/errors.jsonl`, 43 files): **9 `.doc`-named files are actually RTF** — and we have
  an RTF backend — plus an 89 MB `.rtf` over the extractor's 50 MiB cap, and 22 `.docx`
  python-docx cannot open. Fix = content-sniff the magic bytes instead of trusting the extension.
  Deliberately NOT done in 2.5: it is a real change to the extractor with its own blast radius,
  and 10 files of 14,565 move no number in the baseline.
- **Move `jd_core/parser/store.py`'s import of `jd_bank.db.models`** — the one pinned
  `jd_core → jd_bank` edge (see Gotchas). Harmless today (a leaf, no cycle), but it is the
  exception that the import ratchet has to carry.
- **Deferred EXTRACT modules** (plan already assigns them): `export.py` → 5.4 (needs `reportlab`, a
  new dep, plus SFU styling hris never implemented, plus the open territorial-ack flag); prompts
  (`sfu_jd_extract` / `jd_harmonize` / `jd_quality`) → 4.2 (no LLM client or prompt loader exists;
  ~~the golden test needs host Ollama, which the self-contained `gates` container cannot reach~~ —
  **that reason was FALSE, see the Ollama gotcha below; the real reason is that CI cannot reach the
  inference host, so a live golden test must be opt-in and local-only**);
  `jd_import_service` → 5 (composer upload; would force PyMuPDF back after 1.3 dropped the PDF path).

---


## Backlog (real, recorded — fold into cleanup PRs as they come up)

- **`max_chars` is too high for WJQ text.** 11 documents exceed the 8192-token model limit after
  truncation to 10,000 chars (`max_chars` was measured on JDFN-only serialized text, which maxes at 8,987;
  WJQ Hay-factor prose is denser). They get sections but no document vector (runner isolates+skips, no
  crash). Fix: lower `max_chars`, or truncate by tokens not chars. Register HR-124-adjacent.
- **WJQ template boilerplate is not redacted for near-dup/clustering — NOW CONFIRMED by the cluster report.** `redact_boilerplate` only knows
  JDFN's About-SFU/territorial/EDI passages. WJQ's 14-section scaffolding (near-identical across ~4,300
  files) inflates their mutual similarity — the cluster report exposed this: the two largest flagged clusters ("Untitled Position" n=132 and n=108) are WJQ `.doc` artifacts that over-cluster on shared template+seniority, not role. Redaction (before embedding/Tier-3, then re-embed + re-Tier-3 + re-cluster) is now a **Phase-4 priority** — block WJQ harmonization until this lands, so the canonical report reflects true role equivalence.
- **Better WJQ `.doc` title extraction — now needed before WJQ harmonization.** Antiword loses the document title label (WJQ form: "WEIGHTED JOB QUESTIONNAIRE — [TITLE]"; antiword reads only body text). Current fallback: "Untitled Position" (~94% of WJQ `.doc` files) → 132/108-JD clusters flagged in Phase 3.5 report. Extract before parsing (patch the extractor, or pre-scan the `.doc` XML).
- **Tier-3 candidate-gen perf (3.4b follow-up).** O(bucket²) scan in the 8,215-doc `unmapped` title bucket completes in ~1hr whole-archive, but it is not scaling. Replace with Neo4j vector-index top-k (compute seniority delta over candidates only, not all pairs in the bucket). No blast radius (candidate gen is deterministic from config+vectors).
- **Wire `run_tier1` to persist EXACT edges.** Tier-1 currently **has no DB caller** — SHA-256 exact dedup runs but never writes to `dedup_edges`. Clustering must add EXACT connectivity or identical dups split. Cheap wiring task, no new logic.
- **The parse idempotency key is blind to the extractor.** `parse_and_store` keys on `(source_document_id,
  parser_version)`; an extractor-only change (like #30) changes the text but not the key, so it does NOT
  force a re-parse — the docx fix's re-parse only happened because the WJQ change bumped `PARSER_VERSION`.
  Fold an extractor version into the key, or content-key the parse.
- **The baseline stamp doesn't capture the extractor.** #31 regenerated the baseline with a byte-identical
  `parser_version`/`rules_version` but different numbers (extraction changed). Fold an extractor version
  into the baseline stamp.
- **`sections_skipped_short` is a misnomer and the committed artifact says something false** (found by
  the first real embed run, `docs/embeddings/summary.json`). It reports **20,644** — but only **7**
  sections in the whole archive are actually *short* (1 summary + 6 duty-blocks, below
  `min_section_chars: 40`). The other ~20,637 are **ABSENT**, not short: the counter is
  `3 × 14,522 candidate slots − 22,922 embedded`, so it silently folds "this JD has no qualifications
  section at all" into "this section was too short to embed". Anyone reading the artifact would
  conclude the guard-rail is doing 3,000× more work than it is. Split it into `sections_absent` vs
  `sections_skipped_short` — the guard-rail's real footprint (7) is one of the numbers that justifies
  its default, and it is currently invisible.
- **The embed run's first pre-fetch logs six Neo4j `property key does not exist` warnings** against an
  empty index (`text_sha256`, `model`, `embed_stamp`). Harmless — it is the skip-first query running
  before any node exists — but it is noise at the top of every fresh run's log and will train people
  to ignore warnings. Quiet it (or state in the runner why it is expected on a cold index).
- **CI enforces a branch-name gate: `^(agent|feat|fix|chore)/<slug>$`.** A bare topic branch like
  `phase-4.1-merge-engine` **fails** the `Gate: branch-name` job, and every other gate `skipping`s
  behind it (so it reads like a total CI stall, not a naming nit). GitHub cannot re-point a PR's head
  branch, so the fix is: `git branch -m feat/<slug>`, push, close the old PR + delete its branch,
  reopen. **Name the branch `feat/…` from the start** (4.1 hit this — cost a PR reopen, #45 → #46).
- **Stacked PR merge gotcha — record this in lore.** Merging #19 with `--delete-branch` deleted its
  base branch, which **auto-closed PR #20** (2.6). GitHub will not reopen a PR whose head was rebased
  after closing, so 2.6 was re-opened as a **fresh PR #22** linked back to #20 for review history.
  **In a stacked PR chain, do NOT `--delete-branch` on merge until the whole stack has landed.**
- **`_extract_docx` joins paragraphs with a single `\n`**, so HR-108's paragraph boundary only
  engages on **47% of `.docx`** (373/799 — those with a literal blank line, or a whitespace-only
  paragraph, which survives `if p.text` as `"\n \n"`). The other ~53% still join adjacent paragraphs
  for matching, so a term could match across a `.docx` paragraph break. `.doc` is covered in full
  (498/498), and that is where the wrapping problem actually lives, so this is not urgent. Fix =
  `"\n\n".join(...)` — but it **rewrites the stored raw text the segmenter reads**, so it is its own
  deliberate change, not a drive-by.
- ~~**`SFU-QUAL-BANNED-PHRASE` scans the whole document**~~ **DONE (2.6, HR-120)** — scoped to
  Qualifications via the `banned_phrase_scope` knob. Blocks 104 → 0; **+59 approvals**. It had been
  filed as a backlog tidy-up; the baseline showed it was the **#2 operative gate in the approval
  bar**, so it landed as a register entry with measured before/after, not a cleanup PR. **That
  promotion — tidy-up → bar change — is the lesson: measure before you classify a bug as minor.**
- **No "current version of this path" concept** (new, 3.1). `source_documents` is now one row per
  **file**, keyed `(storage_ref, sha256)` — so if the bytes at a path ever change, the path gets a
  **second** row and nothing marks which is current. `dedup/tier1.py :: _document_refs` selects all
  rows, so that path would be **double-counted** in `total_documents`. Harmless today: the archive
  is READ-ONLY, so no path's bytes change. The pair-key is still right (keying on `storage_ref`
  alone would force an in-place UPDATE, silently re-pointing the `parsed_jds` already hanging off
  that row at bytes that never produced them — a provenance lie). **Fix when ingestion becomes
  incremental, not before.**
- ~~**`comparison.cluster_algo` can lie**~~ **DONE (3.1)** — now a closed `Literal` **and**
  `build_clusters` genuinely dispatches on it, so the stamp selects the algorithm rather than merely
  naming it. Verified by mutation: `louvain` in YAML → the rulebook refuses to load; forced past the
  loader → `build_clusters` refuses to run. The landmine is disarmed before Phase 3 writes a cluster
  row, exactly as this backlog line demanded.
- **Boundary tests for the comparison cutoffs.** `clone_threshold` (0.92), `material_years_delta`
  (2) and individual `title_stopwords` are pinned *by value* but are behaviourally invisible — the
  ported hris tests probe far from the cutoff (clone at 0.95; a delta of 3 against a bar of 2). The
  "move the number → something goes red" standard holds via the by-value pins, but a boundary test
  (`clone_verdict(0.92)` is a clone, `clone_verdict(0.9199)` is not) would make *behaviour* the
  oracle rather than the assertion.
- **HR-082** should name the divergence it papers over: the rulebook (l.238) *does* enumerate
  education levels — "Diploma, Bachelor's, Master's, PhD" — a 4-item list that differs from our
  5-rung ladder (we add `high_school`; we say `associate` where SFU says `Diploma`). HR-083 already
  owns the diploma/associate mismatch; HR-082 should mention SFU's list is shorter and differently
  named, since an HR reviewer ratifying the ladder will want to know.

- **`bank/render.py` → `parse_jd` round trip is lossy** (documented in the module docstring and
  pinned by `test_render_to_parse_is_documented_lossy_exactly_where_it_says_it_is`). Every section
  the renderer *writes* now survives re-parse, but: (a) identification is a subtitle line, not the
  `Department:` / `Grade:` labelled fields the segmenter reads → `department`, `grade`,
  `position_number` are lost (`employee_group` survives, token-scanned); (b) About-SFU + the
  territorial-ack/employment-equity footer are presence *booleans* on the model, so there is no
  text to render → a rendered canonical trips `SFU-COMP-ABOUT` and the footer gates; (c) the
  segmenter does not strip the `Supervisory: ` and `[skill] advanced ` labels, so they come back
  *inside* the value and a re-render **compounds** them. **Do not build a render→parse→render loop
  (composer "start from canonical") until this is closed.** Fix = template-faithful identification
  + footer emission, a label-strip in `segmenter._structure_relationships` / `_structure_quals`,
  and a round-trip fixture.
- **Landmine for the 2.4b `hay_signals` port:** hris `pipeline/bank/hay_signals.py:229` constructs
  `HaySignals(..., grade_mapped=False)`. The ported `HaySignals` is `extra="forbid"` and that field
  is **deliberately gone** (SFU publishes no Hay point charts; a graded signal is unrepresentable
  by construction). The port MUST drop the kwarg. It must **not** "fix" the `ValidationError` by
  re-adding the field — that silently undoes the Hay source-gate.
- Remove 4 **dead config values** nothing reads: `rule_catalog.SFU-LANG-CODED.default_severity`
  and the three `SFU-AUTH-TITLE-*.default_severity` (validators always override them).
- `max_listed` exists **twice** as independent knobs holding the same value 5
  (`thresholds.max_listed`, `gates.max_listed`) — nothing keeps them in step. (2.4b hit the
  same shape between `hay_signals.advanced_skill_modifiers` and
  `qualifications.skill_modifiers` and **closed it with a `Rules`-level cross-file validator**
  — use that as the pattern when closing `max_listed`.)
- **Decision-surface enumerator, residual hole (narrow).** `_OFF_SURFACE` (in
  `tests/unit/test_decision_register.py`) now forces every field of every rule file to be
  either on the surface or exempted with a reason, and `_FLAT_SURFACE_FILES` puts flat files on
  it automatically. But `test_the_decision_surface_walks_every_rule_file` only requires **≥1
  path per file** — so a *new* partially-hand-enumerated rule file listed in neither
  `_FLAT_SURFACE_FILES` nor `_OFF_SURFACE` could still hide a field. All current files are
  covered; shape any new rule file **flat** so it qualifies for `_FLAT_SURFACE_FILES`.
- **`make register-check` ≠ surface coverage.** `register-check` only diffs the committed
  register Markdown against `decision_register.yaml`. The surface/coverage guarantees are
  enforced by **`make gates`** (the `_OFF_SURFACE` guard test + `check_register` via
  `get_rules`). Run both; never read a green `register-check` as "everything is registered".
- ~~**`rules_version` tracks nothing.**~~ **DONE (PR #16)** — now derived from rule content
  (`jd_rules_sfu_v4+<digest>`), so a stamped `ValidationReport` identifies the rules that produced
  it. ~~**HR-058**~~ **DONE (PR #16)** too. Both were prerequisites for the 2.5 baseline.
- **2.4a citation error (fold into a chore branch).** `models/bank.py` (the `TitleFamily`
  warning) and HR-059 both say the rulebook's lone "VP" is a Part **3.5** restricted title. It
  is actually Part **3.6**, in the working-titles "should not use" list. The *conclusion* (SFU
  publishes no title ladder) is unaffected — only the citation is wrong.
- `docs/rulebook/rulebook/` is a tracked **duplicate** of `docs/rulebook/` — scrub on a chore branch.
- Root `.claude/` is NOT set up (harness subagent defs + no-commit-to-main / ruff hooks). An
  auto-generated `.claude/settings.json` (a permission allowlist Claude Code wrote itself) sits
  untracked — it is NOT the harness config; keep it out of commits. Standing up the real root
  `.claude/` is its own deliberate PR.
- `.gitattributes`: consider `linguist-generated` for the rendered register Markdown.
- Carried from Phase 1: tighten the legacy-`.doc` E2E confidence upper bound; guard bare
  single-word heading patterns in `parser/headings.py`; docx zip-ratio (decompression-bomb) guard
  in `ingest/extract.py`; wire the arq `run_ingest` worker task.

---

## Authoritative references

- **`docs/status/2026-07-15-shipped.md` — the current one-pager.** 3.2 embeddings, 3.3 near-dup, and
  both extraction defects, for the team and as the basis of what we tell HR. **Start here if catching
  up.** (`2026-07-13-shipped.md` covers the earlier 2.5/2.6/3.1.)
- `docs/plan.md` — full build plan, architecture, phase breakdown (current).
- **`docs/baseline/README.md` — THE ARCHIVE BASELINE (2.5).** The measured read of all 14,565 JDs.
  Read before making any claim about the archive. Regenerate with `make baseline`.
- **`docs/decisions/HR-REVIEW-PACKET.md` — what SFU HR must decide** (9 decisions, written for a
  non-engineer, each with measured impact + our recommendation).
- **`docs/decisions/POST-REVIEW-CHANGE-PLAN.md` — what we change once they rule** (per decision:
  config key, blast radius, what test must go red, sequencing).
- `docs/subagent-model-strategy.md` — model tiering rules for subagent dispatch.
- `docs/decisions/HR-DECISION-REGISTER.md` — generated register; `make register` / `make register-check`.
- `docs/adr/` — ADR-002 (PG/Neo4j), 003 (Ollama), 004 (repo placement), 005 (extract-vs-rewrite,
  Accepted), 006 (Docker-only).
- `docs/audit/hris-reuse-map.md` (16 EXTRACT / 8 REWRITE / 4 DISCARD) + `archive-census.md`.
- `docs/rulebook/sfu-jd-standards.txt` — the rulebook (Part 2 = new template, Part 8 = old).
- `DEVELOPER_GUIDE_1.md` — onboarding + Docker-only workflow. `CLAUDE.md` — project invariants.
- Persistent memories auto-load each session (storage-architecture, docker-only-execution,
  harness-upstream-subagents, jd-incumbent-names-not-pii, subagent-workflow, hr-decision-register).
