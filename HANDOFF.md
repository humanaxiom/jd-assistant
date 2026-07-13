# JD Bank — Session Handoff

Read this first every session. Single source of truth for current state + how we work.
Last updated: 2026-07-13 (**Phase 2 COMPLETE — 2.5 (baseline) + 2.6 (three defect fixes).** The
approval bar met the real corpus and **survived**. HR review is unblocked. Phase 3 next.)

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

On current practice: median **79.0**, **99.8% clear the score floor of 60**, grades 82 A / 550 B /
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

## Current state — Phases 1 and 2 COMPLETE and merged; Phase 3 is next

Phases 1 and 2 are fully merged to `main`. The validation engine (rules-as-data → section
validators → gate runner), the HR decision register, and all remaining EXTRACT-eligible
`jd_core` modules (2.4a/b/c) are landed.

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
| **2.5 THE ARCHIVE BASELINE** — trial of the approval bar | PR [#19](https://github.com/humanaxiom/jd-assistant/pull/19) | `7e75835` |
| **2.6 three rulebook defects** — HOW-WHY unevaluable · banned-phrase scope · 4th era band | PR (stacked on #19) | — |

Test suite: **1143 passing**, coverage **97.40%**, all in Docker via `make gates`. Decision
register grew from 58 to **123 decisions** (2.4 added `hay_signals.yaml` + `comparison.yaml`;
2.5-prep added `boilerplate.yaml`; scanner hardening added `textnorm.yaml`; 2.5 added
`segmentation.yaml`; 2.6 added HR-120/121/122).

All 16 EXTRACT-mapped hris modules are now ported or explicitly deferred: `export.py` → 5.4,
the 3 prompt templates (`sfu_jd_extract`/`jd_harmonize`/`jd_quality`) → 4.2, `jd_import_service`
→ 5 (see `docs/audit/hris-reuse-map.md` and Next up, below). 2.4c's `similarity`, `clustering`
and `drift` landed as pure, tested functions **deliberately not wired to anything yet** — the
`ParsedJD → signals` adapter is Phase 3 work (see Next up).

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
also wired into CI). **123 decisions, all `open` — SFU HR has ratified nothing yet, but the packet
is now written and the numbers in it are corrected: `docs/decisions/HR-REVIEW-PACKET.md`.**

Provenance (as of the 108-entry snapshot): **19 our-invention · 71 hris-calibration · 18 SFU-rulebook**. The entire approval
bar — score floor 60.0, grade floor C, the severity floor, the 14-rule blocking set, the 2
non-overridable gates — is **our invention, not an SFU number**. It must be ratified against the
Phase 2.5 archive baseline (see Next up, below).

**Standing rule for all future work:** any non-trivial metric or rule change must be
YAML-configurable — never a code change — and must land with a register entry in the *same* PR.
**If a default looks wrong, register it as `open`. Do not quietly patch it.**

Enforcement (the build fails if): a register config path doesn't resolve against live rules; a
`current_default` drifts from the live value; a param on the 157-item decision surface is
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

- **Phase 3 — dedup & clustering. 3.1 (Tier-1 exact dedup) is DONE; 3.2 (embeddings) is next.**
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
  - **Still to wire up: 2.4c's trio.** `similarity`, `clustering` and `drift` are pure, tested,
    *uncalled* functions: `skill_overlap` needs a skill ontology + idf corpus, `seniority_closeness`
    needs an education enum + years bar, and a `ParsedJD` has none of them. Phase 3 must design the
    `ParsedJD → signals` adapter (where do skills come from? proposal: `qualifications` where
    `kind ∈ {knowledge, skill, ability}`) against the real corpus. That is a **new decision** — it
    wants an ADR and register entries. Note `families={}` degrades `skill_overlap` to plain
    idf-weighted Jaccard vs hris's ontology-aware scoring; record that when it lands.
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
  the golden test needs host Ollama, which the self-contained `gates` container cannot reach);
  `jd_import_service` → 5 (composer upload; would force PyMuPDF back after 1.3 dropped the PDF path).

---


## Backlog (real, recorded — fold into cleanup PRs as they come up)

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
