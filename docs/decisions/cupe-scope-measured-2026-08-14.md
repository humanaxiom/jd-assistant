# CUPE scope (HR-194) — measured, 2026-08-14

**Status: evidence for an OPEN decision. Nothing changed.** `jdfn_employee_groups` is still
`[apsa, apex, poly]`; no default was patched, no rule was added, `rules_version` is unmoved.
Per the standing rule, a default that looks wrong is registered as `open` and argued — not
quietly fixed.

**What this document is for.** HR-194 asks whether CUPE should remain out of the JD Bank
until a CUPE quality bar exists. Until now the answer rested on a *reasoned* claim — "scoring
CUPE on the JDFN gates would be a category error". This measures it. The claim survives, and
the numbers turn out to be more decisive than the argument was.

Measured over all **14,522** current-parser (`jd_segmenter_v3`) JDs, with cohort samples of
**600 CUPE and 600 JDFN** scored through the *shipped* validator path
(`evaluate_jd_rules` → `score_issues` → `evaluate_gates`).

---

## 1. The archive splits three ways, and CUPE is the second-largest piece

| `employee_group` | JDs | share |
|---|---|---|
| `apsa` | 4,946 | 34.1% |
| **(not parsed)** | 4,630 | 31.9% |
| **`cupe`** | **4,440** | **30.6%** |
| `apex` | 420 | 2.9% |
| `poly` | 50 | 0.3% |
| `excluded` | 36 | 0.2% |

**JDFN served = 5,416 (37.3%).** The unparsed third is a separate, already-settled question:
measured in [`employee-group-residual-2026-08-13.md`](employee-group-residual-2026-08-13.md),
those documents **do not state the fact** — it is not a parser defect and not closeable by
parsing.

## 2. ⚠ CUPE is NOT poorly served because it parses badly. It parses *richer*.

This is the finding that most changes the shape of the conversation. `parser/wjq.py` — the
WJQ 14-section segmenter — already works, and has since Phase 3.4:

| cohort | n | summary | duties | **avg duties** | quals | **avg quals** |
|---|---|---|---|---|---|---|
| jdfn | 5,416 | 99.3% | 97.8% | **3.8** | 94.0% | **1.0** |
| **cupe** | **4,440** | 96.1% | 83.8% | **9.7** | 74.1% | **19.5** |

A CUPE JD carries **2.5× the duties and ~20× the qualifications** of a JDFN one. **The
blocker was never ingestion. It is the absence of a bar to judge them by.**

## 3. Scored on the JDFN bar, CUPE cannot pass — 0 of 600

| | JDFN (n=600) | CUPE (n=600) |
|---|---|---|
| mean score | 72.4 | **51.7** |
| **approvable** | 68 (11.3%) | **0 (0.0%)** |
| grades | A 20 · B 246 · C 286 · D 42 · F 6 | **no A, no B** · C 133 · D 333 · F 134 |

Not one CUPE JD in 600 clears the approval bar, and none reaches even a B.

## 4. 🔴 And the reason is template difference, not quality

**Four rules fire on 100% of CUPE JDs:**

`SFU-COMP-TERRITORIAL` · `SFU-GATE-REL-HEADER` · `SFU-COMP-EDI` · `SFU-COMP-PROBLEM`

**This repo already has a name for that.** `rule_catalog.yaml` carries an `evaluable` flag
whose whole rationale is that *a rule that cannot NOT fire is a constant subtracted from
every score, not a quality signal* — the finding it emits is **unfalsifiable**. By that
standard, these four are not measuring CUPE quality; they are detecting that a CUPE document
is not a JDFN document.

The widest per-document gaps:

| rule | cupe % | jdfn % | gap |
|---|---|---|---|
| `SFU-COMP-DECISION` | 96.0 | 3.2 | **+92.8** |
| `SFU-QUAL-EQUIVALENT` | 89.0 | 15.3 | +73.7 |
| `SFU-QUAL-SKILL-MODIFIER` | 72.7 | 7.7 | +65.0 |
| `SFU-LANG-CODED` | 90.8 | 27.8 | +63.0 |
| `SFU-STRUCT-DUTIES-TOO-MANY` | 78.8 | 23.8 | +55.0 |
| `SFU-COMP-EDI` | 100.0 | 50.3 | +49.7 |
| `SFU-COMP-ABOUT` | 99.8 | 56.0 | +43.8 |
| `SFU-COMP-PROBLEM` | 100.0 | 57.3 | +42.7 |

**The mechanism, section by section** — the WJQ form simply does not contain two of the SFU
template's sections:

| section | cupe | jdfn |
|---|---|---|
| position summary | 96.1% | 99.3% |
| duties | 83.8% | 97.8% |
| **impact of decision making** | **3.1%** | 97.0% |
| **problem solving** | **0.0%** | 44.9% |
| relationships | 70.9% | 97.4% |
| qualifications | 74.1% | 94.0% |
| grade | 9.6% | 15.8% |

`SFU-COMP-PROBLEM` fires on **100%** of CUPE JDs because **0.0%** of them have a Problem
Solving section — the WJQ instrument never asks for one. Penalising a document for lacking a
section its own official template does not have is the category error, stated as a number.

`SFU-STRUCT-DUTIES-TOO-MANY` is the same defect from the other direction: `duties_max` is
**5**, calibrated on a JDFN cohort averaging 3.8 duties, while WJQ separates *major* from
*minor* functions and averages **9.7**. The rule fires on 78.8% of CUPE JDs for doing exactly
what its own form instructs.

---

## 5. What this settles, and what it does not

**Settled — the current default is right, and now on evidence rather than on argument.**
Serving CUPE through the JDFN bar today would mis-score ~4,440 JDs and refuse every one of
them. Keeping `jdfn_employee_groups = [apsa, apex, poly]` is correct.

**Not settled — and this is HR's, not ours:** whether a CUPE bar should be built at all. That
is HR-194.

**The order does not change, and §2 makes the cost clearer:** a CUPE bar (a WJQ ruleset with
an oracle) must exist **before** a `cupe` token is added to `jdfn_employee_groups`. Adding the
token first would surface CUPE in the Builder with nothing behind it. **What §2 changes is the
estimate of the remaining work:** parsing is done and the content is rich, so a CUPE bar is a
*rules* project — which of the WJQ sections carry a quality expectation, and what it is — not
a pipeline project.

**What a CUPE bar would have to score**, from §4's coverage table: position summary, duties
(with a duty count calibrated to the WJQ instrument, not `duties_max: 5`), relationships and
qualifications. It could not reuse the decision-making or problem-solving rules at all, since
the form does not collect them.

**One sentence for HR:** *the Bank serves roughly a third of SFU's archive, deliberately
excludes another third for which it has no ratified quality standard — and that exclusion is
now measured, not assumed: every one of 600 sampled CUPE JDs fails the JDFN bar, mostly on
four rules that fire on 100% of them because the CUPE form does not contain the sections they
check.*

---

## 6. How to reproduce

Cohort split and section coverage are SQL over `parsed_jds` at `parser_version =
'jd_segmenter_v3'`. The scoring comparison runs the shipped validator path in the `api`
container over 600 JDs per cohort ordered by `id` (a stable, arbitrary slice — **not** the
newest files, which are not a sample of the corpus). No LLM is involved: every rule quoted
here is deterministic.
