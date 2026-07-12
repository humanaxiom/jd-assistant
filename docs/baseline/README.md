# Phase 2.5 — The Archive Baseline

**The read of the data in `summary.json`. Does the archive ratify the approval bar, or kill it?**

| | |
|---|---|
| Archive | `C:\repos\hris\fixtures\SFU_JDs` (READ-ONLY), 14,565 files |
| Accounted for | **14,522 scored + 43 skipped = 14,565.** No silent drops. |
| Rules | `jd_rules_sfu_v4+2cb6723a5241` |
| Parser | `jd_segmenter_v1` |
| Segmentation | `jd_rules_sfu_v4+13820636b5ee` |
| Regenerate | `make baseline JD_ARCHIVE_PATH=<archive>` |

---

## The verdict: **the archive RATIFIES the bar.**

This run was commissioned as the trial of an approval bar that nobody at SFU has ratified — the
score floor of 60, the grade floor of C, the severity floor, the 14-rule blocking set and the 2
non-overridable gates are `our_invention`, 19 of 118 register decisions. The brief said plainly:
**the run is allowed to kill them.**

It didn't. On the population that can actually put the bar on trial, the bar is sound — and it is
barely even binding:

**Cohort:** "current practice" = the **874** `new`-era JDs on which `SFU-COMP-TERRITORIAL` did not
fire — i.e. those carrying SFU's mandated acknowledgement, so the footer gate is not merely
detecting their date. It is defined on **validator post-state**, so it is reproducible from
`docs/baseline/` with one filter rather than by re-scanning the archive. (A raw-text scan gives
883; the ~9-file gap is exactly the rule's measured 0.2% false-positive rate, and every figure
below moves by <1pp either way.)

| JDs authored under **current practice** (n = 874) | |
|---|---|
| **Approval rate** | **71.9%** |
| Median score | **77.3** |
| **Clear the score floor of 60** | **99.4%** |
| Grades | 5 A · 509 B · 355 C · 5 D · **0 F** |
| Blocked by the score floor | **5 files** |
| Blocked by the grade floor | **5 files** |

The score floor of 60 rejects five job descriptions out of 874. It is not the thing standing
between SFU and an approvable JD bank.

### …and every headline number that says otherwise is an artefact

| Population | Approval | Why the number is what it is |
|---|---|---|
| All 14,522 scored | **4.3%** | A category error. Judges 1967 JDs against the 2019 template. |
| Era = `new` (JDFN / 2019+) | **10.0%** | Still wrong — see below. |
| Latest version per position, era `new` | **13.5%** | Still wrong — see below. |
| **Carries the mandated acknowledgement** | **71.9%** | The bar's actual trial. |

**Do not quote the 4.3%.** Do not quote the 13.5% either. Both measure a *rollout date*, not
job-description quality.

---

## What actually happened: one gate is a date detector

`SFU-APPROVE-EDI-FOOTER` blocks **86.2%** of the entire `new` era. That looked, at first, like a
damning quality finding: current-template JDs missing SFU's own mandated territorial
acknowledgement and employment-equity footer.

It is not a quality finding. **The acknowledgement is a rollout still in progress.** Measured
against the raw text of every archive JD, by year:

| Year | JDs | Carry the acknowledgement | Median score | Approval |
|---:|---:|---:|---:|---:|
| 2015 | 521 | 0.0% | 24.5 | 0.0% |
| 2016 | 592 | 0.0% | 24.5 | 0.0% |
| 2017 | 779 | 0.0% | 23.9 | 0.0% |
| 2018 | 777 | 0.0% | 42.4 | 0.0% |
| 2019 | 1,913 | 0.2% | 62.8 | 0.2% |
| 2020 | 1,150 | 1.0% | 67.3 | 0.3% |
| 2021 | 1,031 | 1.4% | 69.1 | 0.9% |
| 2022 | 609 | 1.0% | 70.3 | 0.8% |
| 2023 | 472 | **11.2%** | 72.1 | 6.4% |
| 2024 | 409 | **63.3%** | 74.5 | **45.7%** |
| 2025 | 450 | **84.9%** | 76.1 | **62.0%** |
| 2026 | 175 | **88.6%** | 76.1 | **64.0%** |

Approval rate tracks acknowledgement adoption almost exactly, because a blocking gate keyed to
the footer *is* an adoption detector. The JDs are not getting dramatically better; they are
getting the paragraph.

**The validator is correct here and was checked.** Cross-examining `SFU-COMP-TERRITORIAL` against
a raw-text scan of all 6,259 new-era JDs: 5,375 fired with the text genuinely absent, 873
correctly did not fire, **10 false positives (0.2%)**, 1 false negative. The rule works. The
archive really doesn't have the paragraph yet.

### This corrects an error made twice in this project

The Phase 0 census (§8.2) claims the footer lives in `word/footer*.xml` and warns that a
body-only extractor will under-report it. **That is false for this corpus** — checked across 20
modern JDFN docs: the text is in `word/document.xml`, and `footer*.xml` contained it **zero**
times.

And then the orchestrator made the mirror-image mistake: having verified that 17 of 20 *recent*
JDFN docs carry the acknowledgement, it nearly wrote "the extractor reads it fine, so an 81%
miss rate must be a bug." Those 20 were the **newest** 400 JDFN files — the one slice where
adoption is ~85%. Generalised to the era, the sample was worthless. The contradiction was only
caught by cross-examining the validator's own output against the raw text, file by file, across
all 6,259.

**Both errors are the same error: a claim about the archive that was not checked against the
archive.** It is the rule this phase exists to honour, and it caught the phase's own author.

---

## The era model is wrong, and the baseline proves it

`segmentation.yaml` classifies era as OLD (≤2009) / TRANSITION (≤2018) / NEW (2019+, or any file
carrying the `JDFN` token) — registered as **HR-109 / HR-110 / HR-111**.

That model assumes one transition. **There are two, and they are four years apart:**

1. the **JDFN template** rollout — 2019 (332 files → 1,131 in 2020);
2. the **territorial acknowledgement / EDI footer** becoming standard practice — **2023–2024**
   (11% → 63%).

Our `new` era captures (1) and is then judged by a blocking gate that only (2) satisfies. That is
why a 2019 JDFN document — authored correctly under the template of its day — is un-approvable.
Hence `new`-era approval of 10.0% against current-practice 71.9%: **the same bar, two different
populations, a 7× difference.**

This is a decision-parameter finding and it goes to the register as `open`, with the evidence
above — **not** as a quiet edit. Proposal for HR: either a fourth band (`current`, 2024+) or an
era defined by the footer's presence rather than a date. Both are HR's call, not ours.

---

## Where the bar *does* bite — and it is not the score floor

Of the 246 current-practice JDs that still cannot be approved:

| Blocking gate | Files | |
|---|---:|---|
| `SFU-APPROVE-SUMMARY-LENGTH` | **134** | position summary outside the word-count range |
| `SFU-APPROVE-QUAL-MINIMUM` | **104** | **all 104 driven by a rule we know is broken — see below** |
| `SFU-APPROVE-QUAL-EQUIVALENT` | 42 | |
| `SFU-APPROVE-EDI-FOOTER` | 20 | partial footer |
| `SFU-APPROVE-MANDATORY-SECTIONS` | 7 | **non-overridable — no waiver** |
| `SFU-APPROVE-SCORE-FLOOR` | **5** | |
| `SFU-APPROVE-GRADE-FLOOR` | **5** | |

The bar's teeth are in **summary length and qualifications formatting**, not in the score.
**HR believes it is being asked to ratify a quality bar. It is being asked to ratify a word-count
range.** Say that out loud before anyone signs.

### The #2 gate in the system is a rule we already knew was mis-scoped

All **104** `SFU-APPROVE-QUAL-MINIMUM` blocks are driven by `SFU-QUAL-BANNED-PHRASE` — the rule
carrying the **known scoping bug** already on the backlog: its own rule text says it bans phrases
from *Qualifications*, but it scans the whole document, so `"Responsibilities may include
arranging catering…"` in **duties** prose trips a Qualifications gate.

That bug was logged as a tidy-up. It is not a tidy-up. **It is the second-largest component of the
approval bar**, and fixing its scope is therefore a change to the bar itself — it must go through
the register, not a cleanup PR.

### The one rule that should worry us

`SFU-STRUCT-HOW-WHY` fires on **77.7%** of the new era, **99.4%** of current practice, and —
the number that settles it — **100% of the 628 JDs we would actually approve.**

A finding present on *every single JD you are willing to approve* is not distinguishing anything.
It is a constant subtracted from every score. It is not a blocking gate, so it costs only points,
but at that frequency it is the largest single depressant on the whole distribution and the top
candidate for the next false-positive investigation. Registered as **HR-119** and promoted out of
`trivial` on the strength of this run. Nothing was changed in this PR.

### HR-047 is a legacy problem, not a current one

**HR-047 — the non-overridable placeholder landmine — blocks ZERO current-practice JDs.** It
blocks 29.4% of the whole archive and 23.4% of latest-per-position, so it is a real menace on the
legacy corpus (a permanently un-approvable JD, no waiver, because the JD merely *discusses*
action verbs). But it is not a threat to the JDs SFU writes today. Prioritise it accordingly —
this was the finding I most expected to be the villain, and the data says it isn't.

---

## The shape of the distribution — and a trap in it

The `new`-era distribution is **bimodal**, and the score floor of 60 does sit in the valley
between the modes. It is tempting to call that a ringing endorsement: a threshold in a natural
gap. **Do not.**

Latest-version-per-position, `new` era (n = 3,537):

```
 10-20  ████████               488
 20-30  █████                  339
 30-40                          56     <-- the valley
 40-50  ██                     122
 50-60  █                       60     <-- the floor of 60 sits here
 60-70  ███████████████        931
 70-80  ████████████████████  1208
 80-90  █████                  328
90-100                           5
```

The two modes are **not** "bad JDs" and "good JDs". They are **"lacks the acknowledgement"** and
**"has it"** — the same rollout as everywhere else in this report. The valley is the gap between
a JD that trips the mandated-section findings and one that doesn't; it is an artefact of the
2023–24 footer adoption, not evidence that SFU's job descriptions naturally cluster either side
of 60.

**Within current practice the distribution is unimodal, centred 70–79.** There is no valley for
the floor to sit in. So the floor of 60 is defensible because it is *nearly inert* (99.4% clear
it, 5 rejections) — not because the data carved a natural threshold there. Those are very
different arguments and only the first one is true.

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
RTF backend; extension-trust is losing them. Same for the 89 MB `.rtf`. Backlog, not fixed here:
content-sniffing is a deliberate change to the extractor with its own blast radius, and 10 files
of 14,565 do not move any number in this report.

---

## What this run does NOT license anyone to say

- ❌ "The SFU JD archive is 4% compliant." It is not a meaningful statement.
- ❌ "The approval bar is too harsh." The data says the opposite: on current-practice JDs it is
  nearly inert (99.4% clear the score floor; it rejects 5).
- ❌ "The score floor sits in a natural valley in the data." The valley is the footer rollout.
  Within current practice the distribution is unimodal. The floor is defensible because it is
  *inert*, not because it is *well-placed*.
- ❌ "Old JDs are bad JDs." They are JDs written to a different template. This run scores them
  against a rulebook that did not exist when they were authored, which is a fact about our
  method, not about them.
- ✅ "On the JDs SFU writes today, 72% are approvable under our proposed bar, and the median
  scores 77." That is the finding, and it is stamped `jd_rules_sfu_v4+2cb6723a5241`.

---

## Register consequences (all `open` — SFU HR has ratified nothing)

Recorded in `docs/decisions/HR-DECISION-REGISTER.md` with the evidence attached. **No shipped
default was changed by this run** — that is the standing rule: if a default looks wrong, it is
registered as `open`, never quietly patched.

1. **HR-001 / 002 / 003 — the approval bar met real data and SURVIVED.** Recommend ratification;
   status stays `open` because only SFU HR can ratify. Carries the bimodality caveat.
2. **HR-004 / HR-005 — the operative bar is not the score floor.** The full blocked-gate table is
   on the entry. HR is ratifying a word-count range.
3. **HR-019 / HR-020** — `SUMMARY-LENGTH` is the **#1 operative bar in the system** (134 of 246).
   The one saving grace: it is the part of the bar SFU *actually published*.
4. **HR-041 / HR-042** — the **#2 operative bar is the mis-scoped `SFU-QUAL-BANNED-PHRASE`**
   (104 of 246, all of them). Fixing its scope is a change to the bar, not a cleanup.
5. **HR-047** — real, but a legacy-corpus problem only. Zero current-practice blocks.
6. **HR-109 / 110 / 111 — the baseline DISPROVED our era model.** Two transitions, four years
   apart. A 4th `current` band, or an era defined by the footer's presence, is HR's call.
7. **HR-119 (new)** — `SFU-STRUCT-HOW-WHY`, promoted out of `trivial`. Fires on 100% of the JDs
   we would approve.
