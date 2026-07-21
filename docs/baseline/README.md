# The Archive Baseline

**The read of the data in `summary.json`. Does the archive ratify the approval bar, or kill it?**

| | |
|---|---|
| Archive | `C:\repos\hris\fixtures\SFU_JDs` (READ-ONLY), 14,565 files |
| Accounted for | **14,522 scored + 43 skipped = 14,565.** No silent drops. |
| Rules | `jd_rules_sfu_v4+c8ec90d74eb5` *(post-WJQ)* |
| Parser | `jd_segmenter_v2` *(WJQ template router)* |
| Segmentation | `jd_rules_sfu_v4+d4c4e253c13a` |
| Regenerate | `make baseline JD_ARCHIVE_PATH=<archive>` (~9 min) |

> **⚠️ Regenerated at `jd_segmenter_v2` (2026-07-15) after two extraction fixes.** Two defects that
> silently shrank what the parser could read were fixed: `_extract_docx` now reads TABLE and Word
> CONTENT-CONTROL text (PR #30, ~20.7M chars recovered), and a new WJQ/CUPE-3338 template parser (PR
> #32) reads the ~4,300 files (29.5%) the segmenter never understood. **Effect on this baseline:**
> **archive-wide broken parses (`parse_confidence < 0.10`) fell 4,984 → 105** (99.3% now parseable),
> median archive score rose 19 → 42.8, and a **`template` facet** was added — **jdfn 10,222 / wjq
> 4,300 / 43 skipped**. **The 874-JD current-practice cohort below is BYTE-IDENTICAL** (approval
> 78.6%, median 79.0, 81A/551B/240C/2D): WJQ is CUPE — a different template with no rulebook bar —
> so it is EXCLUDED from the cohort (`template != wjq`, HR-143) and scoring it under the JDFN gates
> is a category error deferred to HR. **So every cohort claim below still holds; only the
> archive-wide framing gained the WJQ/extraction context** (the old "~5% — a category error" number
> is now largely *explained*: a third of the archive was a template we could not read).

> **History.** Phase **2.5** built this baseline and ran it against rulebook `…+2cb6723a5241`. It
> exposed three defects **in our own rules**, which Phase **2.6** then fixed — so the numbers below
> are the *corrected* ones. Where a 2.5 figure is still quoted it is labelled **(pre-2.6)**.
> All runs are over the identical 14,565 files.

---

## Reproducing the cohort — read this before filtering anything

Most numbers here are about **"current practice"**: the JDs SFU writes *today*, where the mandated
territorial/EDI footer is normal and the footer gate is therefore not merely detecting a document's
age. That cohort is **874 JDs**, defined on validator post-state:

```
era ∈ {new, current}   AND   SFU-COMP-TERRITORIAL did NOT fire
```

⚠️ **Phase 2.6 added a fourth era (`current`, 2024+), which split the old `new` band.** The filter
that worked before 2.6 (`era == "new"` alone) now returns **79** JDs, not 874. If you get 79, this
is why.

---

## The verdict: **the archive RATIFIES the bar.**

This run was commissioned as the trial of an approval bar nobody at SFU has ratified — the score
floor of 60, the grade floor of C, the severity floor, the blocking set and the non-overridable
gates are `our_invention`, and **the brief said plainly that the run was allowed to kill them.**

It didn't. On the population that can actually put the bar on trial, the bar is sound — and it is
barely even binding:

| Current practice (n = 874) | pre-2.6 | **now** |
|---|---|---|
| **Approval rate** | 71.9% | **78.6%** |
| Median score | 77.3 | **79.0** |
| **Clear the score floor of 60** | 99.4% | **99.8%** |
| Grades | 5 A · 509 B · 355 C · 5 D · 0 F | **81 A · 551 B · 240 C · 2 D · 0 F** |
| Blocked | 246 | **187** |
| **Rejected by the score floor** | 5 | **2** |

**The score floor of 60 rejects two job descriptions out of 874.** It is not the thing standing
between SFU and an approvable JD bank.

### …and every headline number that says otherwise is an artefact

| Population | Approval | Why the number is what it is |
|---|---|---|
| All 14,522 scored | ~5% | A category error — and now largely *explained*: a third of it (4,300 WJQ/CUPE files) is a template with **no rulebook bar**, plus 1967-era JDs judged against the 2019 template. |
| Era `new` (2019–2023) | **1.0%** | **Still an artefact** — see the date detector below. |
| Era `current` (2024+) | **61.2%** | A *date* band, not a practice band. |
| **Current practice** (n=874) | **78.6%** | **The bar's actual trial.** |

**Do not quote the whole-archive number.** Do not quote the `new`-era number either. Both measure a
*rollout date*, not job-description quality.

---

## What Phase 2.6 fixed — three defects that were ours, not the archive's

The most valuable thing 2.5 produced was not a score. It was the discovery that **three of our own
rules were broken**, and that they were distorting the very numbers SFU HR was about to ratify.

### 1. A rule that could never *not* fire

`SFU-STRUCT-HOW-WHY` counted duties lacking "how and why" detail. But the parser **never populates
that field** — `segmenter.py` says so in its own docstring: `how_why` is *"left empty"*. So the rule
fired on **every duty of every JD**, by construction. It hit **100% of the 628 JDs we would
approve**. It had *zero* discriminating power: a constant subtracted from every score.

This is the same class of bug as the Phase 2.4 `render.py` disaster — **faithful to hris, wrong
here.** In hris an LLM populated `how_why`; our deterministic parser structurally cannot. The port
never checked the consumer.

Fixed by marking the rule **unevaluable** (data, not code — Phase 4 reinstates it with one YAML word
once the parser can extract the field). Archive-wide the finding went **8,593 → 0**. Scores **rose
on 9,217 files, were unchanged on 5,305, and fell on none.**

> Note the precise claim. *Every score that carried the finding rose; none fell.* **Not** "every
> score rose" — 36.5% of the archive never carried it and did not move.

### 2. The #2 gate in the system was a scoping bug

`SFU-QUAL-BANNED-PHRASE` is supposed to catch wish-list language (*"may include"*, *"an asset"*) in
the **Qualifications** section. It was scanning the **whole document** — so *"Responsibilities may
include arranging catering…"* in **duties** prose tripped a Qualifications gate.

It drove **all 104** `SFU-APPROVE-QUAL-MINIMUM` blocks. Every one of them was a wrong-section match.

Fixed (and made a rulebook knob, `banned_phrase_scope`, so HR can still choose). `QUAL-MINIMUM`
blocks went **104 → 0**; archive-wide the finding went **1,600 → 10**. **This is the entire +59
approvals** (628 → 687) — exactly the 59 JDs it was the *sole* blocker of. The other 45 it blocked
were also failing something else and remain blocked.

> **A consequence worth HR's attention:** correctly scoped, the banned-phrase list now fires on
> **10 files in 14,522**. Either it is a guard-rail nobody hits, or it is missing the phrases SFU's
> authors actually use. That is now the live question.

### 3. Our era model conflated two rollouts

See below — it had a **7×** effect.

---

## One gate is a date detector, and it explains almost everything

`SFU-APPROVE-EDI-FOOTER` blocks **94%** of the archive. That looked like a damning quality finding:
JDs missing SFU's own mandated territorial acknowledgement and employment-equity statement.

It is not a quality finding. **The acknowledgement is a rollout still in progress.** Measured
against the raw text of every archive JD, by year:

| Year | JDs | Carry the acknowledgement | Median score | Approval |
|---:|---:|---:|---:|---:|
| 2015 | 521 | 0.0% | 24.5 | 0.0% |
| 2017 | 779 | 0.0% | 23.9 | 0.0% |
| 2018 | 777 | 0.0% | 42.8 | 0.0% |
| 2019 | 1,913 | 0.2% | 63.4 | 0.2% |
| 2021 | 1,031 | 1.4% | 72.1 | 0.9% |
| 2022 | 609 | 1.0% | 74.5 | 0.8% |
| 2023 | 472 | **11.2%** | 76.1 | 6.4% |
| 2024 | 409 | **63.3%** | 76.1 | **45.7%** |
| 2025 | 450 | **84.9%** | 79.0 | **62.0%** |
| 2026 | 175 | **88.6%** | 79.0 | **64.0%** |

*(Median column is **post-2.6**. The **Approval** column is **pre-2.6** — the 2.6 fixes moved
approval, but only via the banned-phrase gate, and the shape of the curve is unchanged. The
acknowledgement column is a property of the documents and is unaffected by any rulebook.)*

Approval rate tracks acknowledgement adoption almost exactly, because a blocking gate keyed to the
footer **is** an adoption detector. The JDs are not getting dramatically better. They are getting
the paragraph.

**The validator is correct here, and this was checked.** Cross-examining `SFU-COMP-TERRITORIAL`
against a raw-text scan of all **6,259** JDs in the then-`new` era — which, **post-2.6, is the
`new` + `current` bands combined** (the fourth band split it): 5,375 fired with the text genuinely
absent, 873 correctly did not fire, **10 false positives (0.2%)**, 1 false negative. The rule works.
The archive really doesn't have the paragraph yet.

### This corrects an error this project made twice

The Phase 0 census (§8.2) claims the footer lives in `word/footer*.xml` and warns that a body-only
extractor will under-report it. **That is false for this corpus** — checked across 20 modern JDFN
docs: the text is in `word/document.xml`, and `footer*.xml` contained it **zero** times.

Then the orchestrator made the mirror-image mistake: having verified that 17 of 20 *recent* JDFN
docs carry the acknowledgement, it nearly concluded that an 81% miss-rate *must* be an extractor
bug. Those 20 were the **newest 400 files** — the one slice where adoption is ~85%. Generalised to
the era, the sample was worthless. The contradiction was only caught by cross-examining the
validator's own output against the raw text, file by file, across all 6,259.

**Both errors are the same error: a claim about the archive that was not checked against the
archive.** It is the rule this phase exists to honour, and it caught the phase's own author.

---

## The era model was wrong, and the baseline proved it

Era classification assumed **one** transition. **There are two, four years apart:**

1. the **JDFN template** rolled out in **2019** (332 files → 1,131 in 2020);
2. the **territorial/EDI footer** became standard practice in **2023–24** (11% → 63%).

Our `new` era captured (1) and was then judged by a blocking gate that only (2) satisfies. That is
why a 2019 JDFN document — authored correctly under the template of its day — is un-approvable.

**Phase 2.6 added a fourth band, `current` (2024+):**

| Era | Files | Approval | Median |
|---|---:|---:|---:|
| `old` (≤2009) | 3,339 | 0% | 33.3 |
| `transition` (2010–2018) | 4,964 | 0% | 24.5 |
| `new` (2019–2023) | 5,228 | **1.0%** | 68.3 |
| `current` (2024+) | 1,034 | **61.2%** | 78.0 |

A subtlety worth recording: the `JDFN` token used to override the date band **outright**. Since
every JD written today carries it, a naive fourth band would have collapsed instantly. The token now
**promotes** an old file up the ladder but never **demotes** a current one.

### The band is still not the same thing as the cohort — and we did not force it

`current` (1,034) and the current-practice cohort (874) **agree on 795**. They differ because
**239 JDs dated 2024+ still lack the footer**, and **79 that carry it predate 2024**. The band reads
61.2%; the cohort reads 78.6%. **That 17-point gap *is* the rollout's remaining 37%.**

**Quote the cohort for claims about the bar. Quote the band for claims about a date.** The truer
fix — defining "current" by the footer's *presence* rather than by a date — is a live open decision
(HR-109) and is HR's to make, not ours.

---

## Where the bar *actually* bites — and it is not the score floor

Of the 187 current-practice JDs that still cannot be approved:

| Blocking gate | Files | |
|---|---:|---|
| **`SFU-APPROVE-SUMMARY-LENGTH`** | **134** | summary outside 100–150 words |
| `SFU-APPROVE-QUAL-EQUIVALENT` | 42 | no "or an equivalent combination…" |
| `SFU-APPROVE-EDI-FOOTER` | 10 | partial footer |
| `SFU-APPROVE-SUMMARY-CONDITIONS` | 9 | |
| `SFU-APPROVE-MANDATORY-SECTIONS` | 7 | **non-overridable — no waiver** |
| `SFU-APPROVE-SEVERITY-FLOOR` | 7 | |
| **`SFU-APPROVE-SCORE-FLOOR`** | **2** | |
| **`SFU-APPROVE-GRADE-FLOOR`** | **2** | |
| `SFU-APPROVE-KSA-ORDER` | 1 | |
| ~~`SFU-APPROVE-QUAL-MINIMUM`~~ | **0** | *was 104 — the scoping bug, now fixed* |

The bar's teeth are in **a word count**. **HR believes it is being asked to ratify a quality bar. It
is being asked to ratify a 100–150 word range.** Say that out loud before anyone signs.

The one saving grace: 100–150 words is **SFU's own published number** (`sfu_rulebook` provenance),
not ours.

### HR-047 is a legacy problem, not a current one

The non-overridable placeholder gate — which makes a JD **permanently un-approvable, with no
waiver**, because it merely *discusses* action verbs — blocks **29.4% of the whole archive** and
**zero** current-practice JDs. It is a real menace on the legacy corpus and **not** a threat to what
SFU writes today. This was the finding everyone expected to be the villain. The data says it isn't.
Prioritise accordingly.

---

## The shape of the distribution — and a trap in it

The `new`-era histogram is bimodal and the score floor sits in the valley between the modes. It is
tempting to call that a ringing endorsement: a threshold in a natural gap. **Do not.**

The two modes are **not** "bad JDs" and "good JDs". They are **"lacks the acknowledgement"** and
**"has it"** — the same rollout as everywhere else in this report. The valley is the gap between a
JD that trips the mandated-section findings and one that doesn't. It is an artefact of the 2023–24
footer adoption, not evidence that SFU's job descriptions naturally cluster either side of 60.

**Within current practice the distribution is unimodal.** There is no valley for the floor to sit
in. The floor of 60 is defensible because it is **nearly inert** (99.8% clear it; it rejects 2) —
*not* because the data carved a natural threshold there. Those are very different arguments and only
the first one is true.

---

## The skip ledger (43 files) — itself a finding

| Reason | Files |
|---|---:|
| `.docx` python-docx cannot open (no `word/docProps/app.xml`) | 22 |
| **`.doc`-named files that are actually RTF** | **9** |
| No extraction backend (`.tif`, `.serv`, `.dot`) | 5 |
| Damaged `.doc` ("Big Block Depot is damaged") | 3 |
| 89 MB `.rtf` over the extractor's 50 MiB cap | 1 |
| Other antiword / docx failures | 3 |

**The 9 RTF-mislabelled `.doc` files are recoverable JDs we are silently dropping** — we *have* an
RTF backend; extension-trust is losing them. Same for the 89 MB `.rtf`. Backlog: content-sniffing is
a deliberate change to the extractor with its own blast radius, and 10 files of 14,522 move no
number in this report.

---

## What this run does NOT license anyone to say

- ❌ *"The SFU JD archive is 5% compliant."* Not a meaningful statement.
- ❌ *"The approval bar is too harsh."* The data says the opposite: on current-practice JDs it is
  nearly inert (99.8% clear the score floor; it rejects 2).
- ❌ *"The score floor sits in a natural valley in the data."* The valley is the footer rollout.
  Within current practice the distribution is unimodal.
- ❌ *"Old JDs are bad JDs."* They are JDs written to a different template. This run scores them
  against a rulebook that did not exist when they were authored — a fact about our method, not
  about them.
- ❌ *"Fixing HOW-WHY raised every score."* It raised **every score that carried the finding**
  (8,593). 5,305 files never carried it and did not move.
- ✅ *"On the JDs SFU writes today, 79% are approvable under our proposed bar, and the median scores
  79."* That is the finding, and it is stamped `jd_rules_sfu_v4+8c004c4dadd1`.

---

## Register consequences

Recorded in [`../decisions/HR-DECISION-REGISTER.md`](../decisions/HR-DECISION-REGISTER.md) with the
evidence attached. What SFU HR must now decide is in
[`../decisions/HR-REVIEW-PACKET.md`](../decisions/HR-REVIEW-PACKET.md); what we change once they rule
is in [`../decisions/POST-REVIEW-CHANGE-PLAN.md`](../decisions/POST-REVIEW-CHANGE-PLAN.md).

**Standing rule: if a default looks wrong, it is registered as `open` — never quietly patched.**
The three fixes in 2.6 were *defects* (a rule that could not fire, a mis-scoped scan, a modelling
error), not preference changes, and each landed with a register entry carrying its measured
before/after.

1. **The approval bar (score floor 60 / grade floor C / severity floor) — met real data and
   SURVIVED.** Recommend ratification. Status stays `open`; only SFU HR can ratify.
2. **The operative bar is a word count**, not the score floor (HR-004 / HR-019 / HR-020).
3. **The era model** (HR-109/110/111/122) — fourth band added; era-by-footer-presence remains open.
4. **The banned-phrase list is now nearly inert** (10 files) — is it a guard-rail nobody hits, or is
   it missing the phrases SFU authors actually use? (HR-041 / HR-120)
5. **`SFU-STRUCT-HOW-WHY` is retired as unevaluable** until the parser can extract the field
   (HR-119 / HR-121). Phase 4 reinstates it with one YAML word.
