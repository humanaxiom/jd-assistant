# The 31.9% `employee_group` residual is NOT a parser defect

**Date:** 2026-08-13 · **Status:** measured, decided, **no code shipped** ·
**Measured over:** all 14,522 v3-parsed JDs, plus a 300-file random sample of the residual.

## The claim as recorded, and what is wrong with it

`docs/ROADMAP.md` and `HANDOFF.md` have carried this for weeks:

> **31.9% of the archive (4,630 JDs) has no parsed `employee_group`** — *the parser's
> residual* — so "the Bank serves JDFN" is unfalsifiable for a third of the corpus. Close
> before the CUPE scope conversation; **no HR dependency**.

The size is right. **The diagnosis is wrong, and so is the "no HR dependency".** The
documents do not contain the fact. There is almost nothing for a parser to recover.

## What was measured

Live DB, `parser_version = jd_segmenter_v3`:

| | |
|---|---|
| Parsed rows | **14,522** |
| With `employee_group` | **9,892** (68.1%) |
| Without | **4,630** (31.9%) |

Then a **300-file random sample of the 4,630**, re-extracted with the shipped extractor:

| What the document contains | Count | Share |
|---|---:|---:|
| **No group token anywhere in the text** | **274** | **91.3%** |
| A token somewhere, but not as a labelled field | 26 | 8.7% |
| An `Employee Group:` label the parser missed | **1** | **0.3%** |
| Extraction failed | 0 | 0.0% |

**91.3% of the residual does not state its employee group at all.** The parser is not
missing it; it is not there.

## The 8.7% is a trap, not an opportunity

The obvious next idea — "the token appears somewhere, use it" — is actively harmful.
Sampled context lines, verbatim:

```
Supervises one full-time CUPE support staff person.
Note: Also directly or indirectly supervises CUPE staff and volunteers …
grievance procedure for CUPE, Local 3338 and APSA staff and written …
agreements (CUPE, Local 3338 and TSSU).
CUPE grievances to step 2.
```

These are **JDFN roles that supervise or negotiate with CUPE staff**. Classifying on a
loose token match would mislabel them CUPE — and would do so *selectively*, biting hardest
on supervisory and HR-facing roles, i.e. exactly the population most likely to mention
another group. That is the category error HR-143/HR-194 exist to prevent, manufactured by
us instead of avoided.

A minority of the 26 are genuine self-descriptions (`(APSA)`,
`Administrative and Professional Staff (APSA) Continuing Position`, `EXCLUDED`). A narrow
rule could catch those. It cannot be justified by the aggregate.

## The filename recovers 193, and that is the ceiling

4,536 of 14,565 filenames carry a `JDFN_<GROUP>` token, and the segmentation rulebook
already knows the pattern (`segmentation.employee_group_pattern`) — but it is used **only**
by `jd_bank/baseline/facets.py` for cohort faceting, never to populate a parsed JD.

Of the **4,630** rows with no group, **193 have a `JDFN_<GROUP>` filename** — **4.2% of the
residual, 1.3% of the archive.** The filename tokens also include typos the rulebook's
token list rightly does not accept (`JDFN_ASPA` ×26, `JDFN_ASAP` ×2, `JDFN_CUPS` ×1, plus
single-letter junk `JDFN_D`/`JDFN_B`/`JDFN_S`); "correcting" them would be inventing data.

**Maximum honest recovery: 193 + ~14 (the 0.3% mislabelled) ≈ 207 of 4,630 — about 4.5% of
the residual.** The gap stays at roughly 30% of the archive whatever we build.

## Why no code shipped, and this is the important part

The filename fallback is correct and cheap in isolation. Shipping it is **not**, right now:

**A parser behaviour change requires a `parser_version` bump**, because the idempotency key
is `(source_document_id, parser_version)` and nothing re-parses without it. But
`PARSER_VERSION` is a constant that the baseline, embeddings and dedup layers filter on —
so bumping it to `jd_segmenter_v4` **without immediately re-parsing all 14,565 files leaves
the running system querying for a version that has no rows**, i.e. an apparently empty
Bank. The re-parse is hours of compute and is an operator's decision, not a commit's.

So the version bump and the re-parse must ship **together**, deliberately, by someone who
can watch them. Recorded here rather than half-landed.

## What this changes

1. **The backlog framing is corrected.** This is not "the parser's residual" and it is not
   dependency-free. It is *the archive does not record this fact*, and closing it properly
   means the **HRIS** — the authoritative source for employee group — which is the same
   HRIS-export/FIPPA thread already blocked on HR.
2. **The CUPE scope conversation is not blocked on us.** The stated reason for closing this
   first was that "the Bank serves JDFN" is unfalsifiable for a third of the corpus. That
   remains true, and **no amount of parsing will fix it.** HR can be told the honest
   version now: *the Bank serves roughly a third of SFU's archive, deliberately excludes
   another third, and for the last third the documents themselves do not say.*
3. **A ready-to-ship change is scoped** (filename fallback, exact tokens only, no typo
   correction, one register entry) for whenever the next `parser_version` bump and archive
   re-parse are run together.

## The pattern, for the third time

This is the same failure mode as the Phase-5.9 similarity threshold and the coded-language
soft lexicon: **the obvious design was undeliverable, and only measuring first revealed
it.** In all three cases the item's own premise was the thing that did not survive contact
with the corpus. Measure the archive before building for it — this rule has now paid for
itself three times.
