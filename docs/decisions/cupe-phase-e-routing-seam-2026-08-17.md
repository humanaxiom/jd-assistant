# Phase E — the routing seam, measured before it was debated

**Date:** 2026-08-17 · **Status:** spike result, no code change · **Decides:** the shape
of CUPE authoring support, not whether to ship it (that is HR-194).

`docs/plan.md` §Phase E asks a question and tells us how to answer it:

> A separate WJQ builder over the same services (search, assemble, validate, review,
> export) is likely *less* code and makes "which form am I authoring?" a **routing**
> decision made once, rather than a per-field one made everywhere. **Decide it by trying
> the routing seam first, not by debating it.**

So this is the measurement, taken over the shipped Builder before writing anything.

## What the Builder is actually made of

`src/jd_bank/composer/` is **2,204 lines** across 11 modules, plus `compose_ui.py`
(1,055) and `compose.py` (196) in the API layer. Counting references to JDFN-shaped
fields (`decision_making`, `problem_solving`, `supervisory`, `about_sfu`, the KSA kinds):

| module | lines | form-specific? |
|---|---|---|
| `duplicates.py` | 451 | **no** — 0 references |
| `persist.py` | 152 | **no** — 0 |
| `assist.py` | 135 | **no** — 0 |
| `drafts.py` | 110 | **no** — 0 |
| `questions.py` | 94 | **no** — 0 (a *loader*; the form lives in its YAML) |
| `models.py` | 85 | **no** — 0 |
| `search.py` | 697 | **one function** — `_answers_from_jd` (the clone mapping) |
| `validate.py` | 152 | **one function** — `_section_present` |
| `assemble.py` | 160 | **yes** — answers → `SFUJobDescription` |
| `answers.py` | 91 | **yes** — the answer contract itself |

**About 84% of the composer is already form-blind.** Every behavioural module — search,
the near-duplicate authoring guard, draft storage, submit-into-review, the LLM assist —
never asks which form it is holding.

The UI layer is the same story in a smaller space: `compose_ui.py`'s form coupling is
**three declarative maps** (`_SECTION_LABELS`, and the `_*_TARGETS` sets that say how
each answer field is rendered and read back). Those are *statements about a form*, not
logic.

## The result, and it is not quite what the plan expected

**The divergence between the two forms is entirely "what does this form consist of" —
declarations — and not "how does authoring work" — behaviour.**

That changes the answer. The plan framed it as *one builder with conditionals* versus
*two separate builders*. Measured, both are wrong:

- **Conditionals** would scatter one fact (the form) across the four functions and three
  maps that hold a declaration each, and every future change would have to find all
  seven.
- **Two separate builders** would duplicate the *wiring* of 1,500 form-blind lines to
  vary a data table. The shared half is not merely "reusable" — it is already written and
  it already does not care.

What the seam actually wants is a **form spec, selected once**: one object per template
carrying its answers model, its assembler, its question set, its clone mapping, its
section-presence map and its UI field declarations. "Which form am I authoring?" is then
answered exactly once, at the route that starts a draft, and nothing downstream asks
again — the same shape `applies_to` (Phase B) and `thresholds_for` (Phase C) already give
the rules and the numbers.

## Why the seam holds, structurally

Everything downstream of assembly speaks `SFUJobDescription`. A WJQ assembler that
returns one — `employee_group="cupe"`, the point-factor blocks in `additional_context`
where the WJQ **parser** already puts them — needs **no** change to search, dedup,
validation, review, or export. Validation in particular is already correct for free:
`evaluate_jd_rules` reads `template_of` off the draft and applies the WJQ rules (Phase B)
and numbers (Phase C).

⚠ **One thing this does NOT settle, recorded so it is not discovered late.** The WJQ's 14
sections do not map onto `SFUSection`, which is the JDFN template's section list and is
what `Question.section`, the rule catalog's `section`, and the gate jump-links all key
on. Ten WJQ sections have no JDFN counterpart (`level_of_independence`,
`training_exercised`, `direction_exercised`, `impact_of_errors`, `effort`,
`working_conditions`, `continuing_education`, `minor_functions`, `approval_review`, and
the point-factor blocks). Extending `SFUSection` touches the rulebook and the completeness
pin that 8.3c built (`_SECTION_ANCHORS` is asserted equal to `get_args(SFUSection)`) — so
it is a rulebook change with a register entry, not a UI detail, and it should be decided
before the WJQ question set is written rather than after.

## What this does not decide

**Whether the Bank should author CUPE at all is HR-194 and remains open.** This spike is
about shape. The standard Phase B established still applies: if it is built, it is built
the way APSA's was — measured, every value registered `open`, nothing auto-publishing, HR
free to change any of it.
