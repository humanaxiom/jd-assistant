# Coded-language soft lexicon (Gender Decoder) — measured, and NOT built

**Date:** 2026-08-07 · **Status:** decided — do not build · **Rulebook impact:** none
(`rules_version` untouched; no file added)

`docs/ROADMAP.md` carried a quick win: expand the shipped inclusive-language meter with a
**Gender-Decoder-style soft lexicon** — the masculine/feminine-coded word stems from Gaucher,
Friesen & Kay (2011) — to "catch lean the exact-match list misses". It was measured against the
whole archive before being built. **It should not be built.** This doc records why, so the item
is not re-proposed from the roadmap later.

Method: all **14,522** current-parser (`jd_segmenter_v3`) JDs, scanned through the shipped chain
over exactly the text `_inclusive_language` scans (HR-058 boilerplate redaction + `textnorm`
fold). The lexicon was the published list from the Gender Decoder implementation, ported
verbatim — 52 masculine stems, 50 feminine — nothing invented or added.

## 1. The roadmap's premise was a misattributed number

`ROADMAP.md` justified the item with "*fires on only 10/14,522*". That figure is not this rule.

| rule | fires on |
|---|---|
| `SFU-LANG-CODED` (`coded_terms.yaml` — the coded-language list) | **11,160 / 14,522 = 76.8%** |
| `SFU-QUAL-BANNED-PHRASE` (HR-041/120 — the neighbouring backlog row) | **11** |

Confirmed across six commits of the committed `docs/baseline/summary.json`. The exact-match list
is not a near-silent guard rail with gaps to fill; it fires on three quarters of the archive.
The premise was wrong by three orders of magnitude, and **the roadmap has been corrected.**

## 2. The soft lexicon is a constant dressed as a finding

| | share of 14,522 |
|---|---|
| ≥1 **masculine**-coded hit | 99.52% |
| ≥1 **feminine**-coded hit | 99.82% |
| **both** sides | **99.50%** |
| neither | 0.16% |

Median JD: 18 masculine hits, 18 feminine. Net lean (masc − fem) is a broad, near-symmetric
distribution centred on −1 — the shape of noise, not of a classifier. Under the published bands
**95.7% of SFU JDs would receive a lean verdict** and 67% a "strongly" one.

**The verdict is an artefact of two free choices, not a property of the JD:**

- *Where the neutral band sits* (unratified): neutral goes **4.3% → 48.9%** as the band widens
  from 0 to 5.
- *One vocabulary stem.* Dropping masculine `decision` — the word inside SFU's own mandated
  `IMPACT OF DECISION MAKING` heading — flips the corpus from 30/37 masculine/feminine to
  **19/55**. Dropping feminine `respon` (`DUTIES AND RESPONSIBILITIES`) flips it to **57/16**.

A ratio rule fails identically: the middle half of the corpus sits within ±8 points of an even
split.

## 3. Between 38% and 77% of hits are not gendered lean at all

Measured by recording the surface word behind all 566,492 coded tokens:

| stem | side | what actually matched |
|---|---|---|
| `confident` | M | `confidential` + `confidentiality` = **99.8%**; literal "confident" = **6 tokens** |
| `commit` | F | `committee`/`committees` = **84.5%** |
| `decision` | M | the mandated heading `IMPACT OF DECISION MAKING` |
| `respon` | F | the mandated heading `DUTIES AND RESPONSIBILITIES` |
| `connect` | F | the template's own `Internal connections` / `External connections` labels |
| `athlet` | M | the **Athletics & Recreation** unit name |
| `agree` | F | **collective agreements** |
| `nag` | F | surnames (`nagap`, `nagra`, `nagasawa`) |

Two auditable bounds: **38.5%** of tokens are indisputably non-lean (stemming collisions,
verbatim template headings, WJQ form labels, unit names, proper nouns); **77.2%** once ordinary
job-function vocabulary is included. The published list also double-counts every "interpersonal"
(both `interpersona` and `interpersonal` are stems) — 13,825 phantom feminine tokens.

Curating the lexicon down to the 71 stems that survive the false-positive read does not rescue
it: the median JD becomes **2 vs 2**, 60% of the masculine side is `independently` and 61% of the
feminine side is `collaboratively` — words SFU's own template and KSA guidance ask authors to
write. The verdict would reduce to *"does this JD say 'independently' more often than
'collaboratively'?"*

## 4. What the shipped list is actually for

The two are complementary, in the direction that flatters the existing list. **45.9%** of the
shipped rule's findings are invisible to the soft lexicon: the generic pronouns (`his/her` alone
is 8,344 docs) and every gendered occupational noun (`chairman`, `foreman`, `manpower`,
`repairman`, `workman`). Five of the coded adjectives HR would care most about — `aggressive`,
`ambitious`, `competitive`, `compassionate`, `dominant` — are **already shipped**.

The soft lexicon's genuinely-new *and* genuinely-coded contribution is ~**0.4%** of coded tokens:
`driven`, `autonom`, `empath`, `emotiona`, `nurtur`, `polite`, `self-sufficien`, `assert`,
`loyal`.

## Decision

**Do not build the soft lexicon**, and do not aggregate coded-language findings into a
per-document lean verdict — on this corpus a verdict cannot be honest. This is the same failure
mode, and the same answer, as the near-duplicate guard's similarity threshold (Phase 5.9): rank
or flag individual, actionable terms; never publish a number the data cannot support.

**Spend the effort on the list already shipped instead.** HR-029 is the live defect and it is now
carries measured evidence: three terms SFU never published — `confidential` (29.8% of docs),
`individual` (25.6%), `agreement` (11.6%) — generate **83%** of today's findings, while 16 of the
37 terms never fire. That is an HR ruling, not an engineering change; per the standing rule we
change nothing until HR decides.

If any part of the roadmap item survives HR review, it is **not** a new lexicon file but ~9
individually-justified additions to `coded_terms.yaml`, each with its own register entry and its
own measured firing rate — and **no aggregation to a verdict, ever**.
