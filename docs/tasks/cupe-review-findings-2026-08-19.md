# CUPE review — six adversarial reviewers, 2026-08-19

**Why this exists.** Phases B–E (PRs #109–#122) shipped in one weekend, orchestrator-only,
with **no second reviewer**. Six Opus reviewers were then run over
`git diff 3660812..origin/main`, each with a distinct lens, each told to verify against the
code rather than the commit messages. They found ~30 issues; two are P0.

**Read this before touching CUPE code.** Everything below is CONFIRMED by a reviewer
running the real code in the `gates` container unless marked SUSPECTED.

---

## 🔴 P0-1 — A CUPE author cannot submit or export. The Builder is write-only.

`core/src/api/templates/compose_new.html` — the hidden `form` field is inside the **check**
form only (line ~259). Export (~228) and Submit (~240) are **separate `<form>` elements**
carrying only `csrf_token` + `answers_json`. Hidden inputs do not cross form boundaries, so
both handlers get `form=None`, fall back to JDFN, and run
`ComposerAnswers.model_validate_json(<WJQ payload>)` under `extra="forbid"` — error page.

Reproduced end to end:

```
check   -> 200 | WJQ answers captured correctly
export  -> 200 text/html      (an error page, not a .docx)
submit  -> 200, no redirect   (nothing persisted)
         author text preserved on the page: False
```

The author fills the whole questionnaire, clicks Submit, and gets a pydantic error with
**every field they typed wiped**. The entire Phase E journey terminates there.

**Why four new WJQ UI tests missed it:** every one synthesises its own POST body, supplying
the `form` field the page forgets to emit. They test the handler, not the page.

**Fix:** add the hidden field to both forms — then generalise the template-source scanner
that `_csrf.html` already ships for exactly this class (a required hidden input missing from
one `<form>` of several). The durable guard is a test that drives the round trip **from the
rendered HTML**; anything that hand-builds the body reproduces the blind spot.

## 🔴 P0-2 — An inverted test certifies live data loss

`core/tests/unit/test_composer_forms.py::test_unrecognised_context_text_is_kept_rather_than_dropped`
asserts `all(getattr(cloned, t) is None for t in WJQ_CONTEXT_TARGETS)` — that the text
**was** dropped, under a name and docstring promising the opposite. **It would go red if the
bug were fixed**, so it actively blocks the repair.

The bug it certifies: `wjq_assemble._split_context_blocks` starts `current = None` and only
keeps lines `if current is not None`. Anything before the first exact canonical heading is
discarded, and a context with **no** recognised heading is discarded entirely. The
production docstring claims twice that such text "lands in the first section — visible to
the author, editable, and not silently lost". There is no first section.

Reachable today: `template_of` routes on `employee_group == "cupe"` alone and over-calls WJQ
on a JDFN document that merely mentions CUPE; that document's `additional_context` is
ordinary prose with no WJQ heading, so cloning it discards the whole field silently.

---

## Severe — content loss and integrity

### S-1 The author picks their own approval bar (JDFN form)

`compose_ui._answers_from_form` passes the posted `employee_group` straight into
`ComposerAnswers` with no check against `segmentation.jdfn_employee_groups`. Since Phase B
that field selects the ruleset AND the numeric profile. Same content:

| `employee_group` | outcome |
|---|---|
| `apsa` | 59.38 · D · blocked (EDI footer, duty allocation, score, grade) |
| `cupe` | 89.05 · B · **approved, zero blocking gates** |

`SFU-APPROVE-EDI-FOOTER` is an *overridable* gate that normally demands a written reason in
the audit log (NN #1). One dropdown value removes it with no override and no audit row.
`wjq_assemble.py` fixes `employee_group` for exactly this reason — the protection was
applied to one form only.

### S-2 The rewrite can delete most of a role, and the change-log hides it

`_REWRITABLE_FIELDS` grants the model replace-rights over whole containers. Measured: a
12-duty CUPE draft, model returns 3 → **grade B, 89.05, zero duty findings**, empty
`AntiFabricationRecord`. Worse, `build_harmonization_diff` computes against `merged.draft`,
so the reviewer packet reports `duties_kept: 12, removed: []` and `rendered_draft` shows
twelve duties while `canonical_jds.content` has three. The artifact whose purpose is
"nothing vanishes silently" is what conceals it.

### S-3 The model can invent education / experience / security bars

`_GROUNDED_KINDS = {knowledge, skill, ability}` only. Measured: the grounded qualification
discarded and `PhD in Astrophysics required` / `Ten years of nuclear reactor experience` /
`Enhanced Reliability security clearance` inserted on a clerical CUPE draft, with an empty
anti-fabrication record. **On an HR system an invented hiring bar is the highest-consequence
fabrication possible** — it is what screens candidates.

### S-4 `SFUDuty.frequency` is destroyed on every CUPE draft

The merge carries it; the prompt's duty schema has no `frequency` key, so the model cannot
return it, and duties are replaced wholesale. Verified: `['daily'] -> [None]`. Structural,
100%, not probabilistic. The `_REWRITABLE_FIELDS` completeness pin walks
`SFUJobDescription.model_fields` only and cannot see nested models.

### S-5 ⚠ "JDFN IS THE UNTOUCHED CONTROL" WAS CLAIMED REPEATEDLY AND IS FALSE

`_SECTIONS_NEVER_INVENTED` fires on **both** forms, because `merge_cluster` deliberately
never populates `decision_making` / `problem_solving` / `relationships` for anyone — so the
antecedent is true on every cluster of every template. Verified on an `apsa` draft:
`scrubbed_sections = ('decision_making', 'problem_solving')`. Every JDFN rewritten draft now
carries findings it did not before Phase D. Argued, measured and tested for CUPE only; the
JDFN score impact was never put in a diff. **Re-measure before quoting any JDFN number.**

Related: the guard guarantees `relationships is None` on every CUPE draft, and
`SFU-COMP-RELATIONSHIPS` is `[jdfn, wjq]` — so that rule now fires on 100% of the CUPE
cohort, the "a finding present on every approvable JD is a constant, not a signal"
pathology the rulebook names elsewhere.

### S-6 Silent truncation the author is never told about

- `additional_context` is cut at 20,000 (the model bound) while the seven WJQ answer fields
  allow 28,000 — tail-first, so `continuing_education` goes first. HR-200's measured defect
  reproduced on the authoring side, using the **contract** bound rather than the registered
  `segmentation.additional_context_max_chars` (16,000).
- The UI offers 12 major **and** 12 minor duty rows; the assembler keeps 12 total. An author
  entering any minor function loses all of them, silently, while `answers_json` still shows
  them.
- A body line exactly equal to a canonical heading (`EFFORT`, pasted from the paper form)
  relocates the author's text into another section on the next clone.

---

## Producer / data integrity

- **`--resume` permanently abandons rewrite-failed clusters.** `pipeline.llm_enabled` means
  "a client was injected", not "the rewrite landed", so a cluster whose rewrite raised holds
  a deterministic draft stamped `llm_enabled: True` and is skipped by every future resume,
  counted as "owes no further work". **The clusters that most need retrying are the ones
  resume can never retry.** Fix: key on `rewrite_ran` / `not rewrite_failed`.
- **Counters do not partition.** Three shapes fall through every counter:
  `templates_harmonized=("wjq",)` with an all-JDFN cluster; a mixed cluster under
  `("wjq","jdfn")`; a cluster whose members all fail to load. `wjq_members_authored` counts
  members of clusters that were skipped or failed. The documented identity in `models.py`
  ("persisted + refreshed + skipped + failed == clusters_seen") predates two new skip
  counters and is now false.
- **The `clusters` snapshot is write-once**, so re-ordering `templates_harmonized` re-authors
  the canonical while the cluster row keeps claiming the old form and the old sources — the
  Library would show APSA documents as the sources of a CUPE draft.
- **A resume skip writes no audit row**, contradicting the module's own stated invariant
  ("one audit row per persist/refresh and per skip").
- **`--resume --allow-downgrade --no-llm` is a silent no-op** — resume fires first, so the
  deliberate re-baseline never happens and the run exits 0.
- **A member dropped by `load_member_jds` is invisible per cluster** — `members_excluded`
  counts template drops only, so HR can read a "harmonized" role that is a copy of one
  document with nothing saying a source was dropped.

## Rulebook / policy

- **`SFU-GATE-SENIOR-TITLE` is unfalsifiable on the WJQ** — it needs
  `relationships.supervisory`, which `parser/wjq.py` never populates by design. 71 of 4,300
  CUPE documents carry the finding and it feeds an overridable gate no CUPE author can clear.
  It is the rule the JDFN-only set forgot.
- **`thresholds.wjq.duties_max: 12` is structurally dead** — the model caps at 12 and both
  parsers truncate there, so `n > 12` is unreachable. HR is being asked to ratify a number
  indistinguishable from `evaluable: false` on that form.
- **`applies_to` is not on the decision surface** — `decision_surface()` emits nothing for
  it, so the build-breaking drift check cannot see a template-scope change on 31 of 32
  rules. (Mitigated by `test_rule_applies_to_template.py`, which pins the set exactly — but
  the guarantee lives in a unit test, not in the register HR reads.)
- **`template_of`'s "safe direction" claim is backwards.** Over-calling WJQ withholds the
  EDI-footer rules, which HR-201 measures as the difference between 0.0% and 59.0%
  approvable — so a mislabel flips approval False→True. And it is reachable: a JDFN document
  with no Identification heading has the whole document scanned for a bare `cupe`.
- **Register population splice** — HR-202/204/205 say "measured over all **4,440** CUPE
  documents at v4"; the v4 whole-archive run put the cohort at **4,300**. 4,440 is the v3
  count. The percentages are likely right; the population line names a cohort neither
  measurement used.
- **`assist.py` reads the unresolved JDFN summary band** while authoring a CUPE draft — the
  last unresolved `rules.thresholds` read. Harmless today (both profiles are 100/150),
  wrong the day HR moves HR-204/205.
- SUSPECTED: the profile swap in `merge_cluster` rebinds `active` wholesale, so its
  `content_hash` reports a version matching no rulebook on disk. Nothing stamps a version
  inside merge today; one added provenance field would write a lie.

## Security — mostly clean

No new routes, no XSS, CSRF intact by app-wide dependency, audit payloads counts-only, no
new egress. Two findings: the response amplifier (**fixed**, `56f3ebc`) and a pre-existing
`UnicodeDecodeError` → 500 on a non-UTF-8 body (documented, unchanged).

## Test quality — 1 vacuous, 10 weak, the rest solid

Beyond P0-2, the mutations that survive:

- **The summary band is unwired and untestable as written.** Forcing
  `active.thresholds.summary_*` (the JDFN profile) into the rewrite prompt keeps **30 tests
  green**; the same mutation on `duties_max` turns one red. `summary_min/max_words` are
  100/150 in *both* profiles, so every summary-band assertion in the CUPE work is
  unfalsifiable. Only `duties_max` genuinely differs.
- **The review queue's form badge**: forcing every row to "CUPE (WJQ)" keeps 55 tests green —
  `assert "JDFN" in body` is satisfied by the static warning paragraph added in the same
  commit. The detail-page test got this right with a `not_expected` per case; the queue test
  did not.
- `test_every_question_in_every_set_has_a_render_kind` is a truthiness check — restoring the
  original `return "list"` defect passes it.
- No completeness pin exists for `WJQAnswers` (the JDFN twin has one), so shortening five of
  the seven point-factor fields to `max_length=999` silently turns them into single-line
  inputs — the exact defect `render_kind` was written to prevent.
- `test_the_result_carries_no_field_that_scores_both_forms_at_once` blocks five hand-listed
  names; `overall_mean` sails through.
- `test_the_draft_is_stamped_with_model_prompt_and_rules_version` now reads the same source
  the code reads — a tautology where it used to be a literal.

**The highest-value missing test:** drive the WJQ round trip *from the rendered HTML* —
scrape `answers_json` out of the page and post it back to `/export` and `/submit` exactly as
the browser's forms do, with no synthesised `form` field. That is P0-1, and it generalises:
**for a multi-form surface, test the page, not the handler.**

---

## Already fixed

| | |
|---|---|
| publish race (NN #1) | `56f3ebc` — re-check `FOR UPDATE` immediately before the write, **not** a lock across the LLM calls (which would block reviewers for a minute) |
| response amplifier (20–40×) | `56f3ebc` |
| live goldens silently skipping | `98f284a` — all three probes; 9 live tests now genuinely run |

## Suggested order

1. **P0-1** — three lines of HTML, the generalised template scanner, and a rendered-HTML
   round-trip test.
2. **P0-2** — fix `_split_context_blocks`, then invert the test to match its own name.
3. **S-1** — validate `employee_group` server-side against the rulebook.
4. **S-2 / S-3 / S-4 together** — they are one defect: the allow-list works at top level and
   grants replace-rights over containers. A rewrite-vs-merge delta recorded into
   `AntiFabricationRecord` addresses all three and gives `build_harmonization_diff`
   something true to report.
5. **S-5** — re-measure JDFN before quoting any JDFN number anywhere.
6. The producer and rulebook lists as Phase G.
