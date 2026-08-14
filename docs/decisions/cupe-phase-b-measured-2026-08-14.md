# CUPE Phase B, measured over the whole archive — and the correction it forces

**Date:** 2026-08-14 · **Method:** `make baseline` over all 14,565 archive files, the
sanctioned archive path (`docs/baseline/README.md`), not a database sample.

> **⚠️ WHY THIS DOCUMENT EXISTS.** Phase B was written up — in `HANDOFF.md`, `docs/plan.md`
> and PR #110 — as *"Still ~0% approvable, and that is expected; the thresholds are
> JDFN-calibrated. That is Phase C."* **That is false.** It came from a 600-row spike over
> `parsed_jds` reporting **0.2%**. Measured over the whole archive, CUPE/WJQ is approvable
> at **59.0%**. The spike was wrong by roughly 300×, and the phase that was planned on top
> of it was planned on a number nobody had checked against the archive.
>
> This is the standing rule biting for the fourth time in one day: **every claim about the
> archive must be checked against the archive.** A 600-document `ORDER BY id` slice is not
> the corpus.

## 1. The before/after, same populations, whole archive

| baseline | `rules_version` | parser | generated |
|---|---|---|---|
| **before** | `jd_rules_sfu_v4+90af5e27dc83` | `jd_segmenter_v3` | 2026-08-02 (committed `docs/baseline/`) |
| **after** | `jd_rules_sfu_v4+a4c5e2d0f0f3` | `jd_segmenter_v4` | 2026-08-14 (this run) |

Population `all` — the file counts are identical either side, so this is a clean pairing:

| cohort | n | approvable before | approvable after | mean before | mean after |
|---|---|---|---|---|---|
| **WJQ (CUPE)** | 4,300 | **0.0%** | **59.0%** | 51.8 | **63.2** |
| **JDFN** | 10,222 | 6.7% | **6.7%** | 57.7 | 57.9 |

Population `latest_per_position` (one row per position, the fairest cut):

| cohort | n | approvable after | mean after |
|---|---|---|---|
| **WJQ** | 1,956 | **60.7%** | 64.6 |
| **JDFN** | 4,339 | 12.0% | 61.8 |

**JDFN holding at exactly 6.7% is the control**, and it is the half that matters most:
Phase B's central claim — that the filter does not silence rules everywhere — survives at
full-archive scale, not just in a sample.

### ⚠ The one confound, stated rather than hidden

The two baselines differ in **both** the rulebook (Phase B) **and** the parser (Phase A,
v3 → v4). JDFN being flat (6.7% → 6.7%, mean 57.7 → 57.9) is good evidence the parser
change is scoring-neutral — **but Phase A's truncation fix landed specifically on CUPE**,
so JDFN is not a clean control for the WJQ row. Some part of 51.8 → 63.2 may be Phase A.
The 0.0% → 59.0% approvability jump is far too large to attribute there, but it has **not**
been isolated, and this document does not claim it has.

## 2. WJQ is not unjudged — but it is judged by a smaller ruleset

25 of the 32 catalogue rules judge WJQ; 7 are JDFN-only. Mean findings per document:
**WJQ 7.20 · JDFN 8.87.**

| rule | WJQ | JDFN |
|---|---|---|
| `SFU-LANG-CODED` | 94.6% | 69.4% |
| `SFU-QUAL-DEGREE-DISCIPLINE` | 82.8% | 45.6% |
| `SFU-STRUCT-DUTIES-TOO-MANY` | 82.3% | 35.3% |
| `SFU-STRUCT-ACTION-VERB` | 82.0% | 74.9% |
| `SFU-QUAL-SKILL-MODIFIER` | **76.1%** | 5.1% |
| `SFU-STRUCT-SUMMARY-TOO-SHORT` | 40.0% | 41.6% |
| `SFU-AUTH-ABILITIES-OBSERVABLE` | **32.2%** | 0.4% |
| `SFU-COMP-RELATIONSHIPS` | 30.1% | 2.9% |
| `SFU-STRUCT-SUMMARY-TOO-LONG` | 27.1% | 21.4% |
| `SFU-STRUCT-PLACEHOLDER` | 24.0% | 37.3% |
| `SFU-COMP-QUALS` | 23.5% | 48.4% |
| `SFU-COMP-DUTIES` | 16.6% | 3.3% |
| `SFU-STRUCT-DUTIES-TOO-FEW` | 0.6% | 40.6% |
| **the 7 withheld** | **0.0%** | 72.0% – 90.1% |

## 3. 🔴 The inversion, and where it comes from

**WJQ now clears a bar that 93% of JDFN documents cannot.** The mechanism is *what blocks*,
not *what scores*. The two non-overridable gates:

| gate | WJQ | JDFN |
|---|---|---|
| `SFU-APPROVE-MANDATORY-SECTIONS` | 1,119 (26%) | 5,113 (50%) |
| `SFU-APPROVE-NO-PLACEHOLDERS` | 1,031 (24%) | 3,811 (37%) |

JDFN documents fail the JDFN bar **mostly on boilerplate presence** — `-TERRITORIAL` 90.1%,
`-REL-HEADER` 82.9%, `-PROBLEM` 74.6%, `-ABOUT` 73.8%, `-EDI` 72.0% — and Phase B exempted
WJQ from exactly those. Grades tell the same story: **no WJQ document earns an A** (B 857 ·
C 2,320 · D 702 · F 421) while JDFN has 100.

### Consequence 1 — HR-201 decides approvability, not score

`-TERRITORIAL` and `-EDI` feed the EDI-footer blocking gate. The entry's
`impact_if_changed` said *"restoring roughly a third of the score gap Phase B closed."*
Measured, it is bigger than that: **HR's boilerplate ruling plausibly decides whether 4,440
CUPE JDs are approvable at all** (59% vs ~0%). Corrected in the register.

### Consequence 2 — Phase C's premise is gone, and the real question is the inverse

Phase C was *"recalibrate the thresholds, because CUPE cannot clear the bar."* CUPE clears
it **nine times more often than APSA**. The live question is not whether the bar is too
high for CUPE — it is **whether a 25-rule bar is still a bar**, and that is a question about
what the WJQ form *should* be held to, not about moving a number.

## 4. What Phase C actually has to work with

The threshold items are real but secondary to §3, and two of them are **form facts** rather
than calibration:

- **`SFU-STRUCT-DUTIES-TOO-MANY` fires on 82.3% of WJQ** against `duties_max: 5`. But CUPE
  duty counts are **bimodal, not averaging 9.7**: **77.4% of CUPE JDs have exactly 12
  duties** and 16.2% have **0**. Twelve is the WJQ's duty-slot count — a property of the
  form, the same category as `applies_to`, not a writing convention. *(The 16.2% parsing to
  zero duties is a parser question, and must not be turned into a quality bar before it is
  understood.)* Advisory today (`gates.yaml` omission (d)).
- **The summary band is skewed the opposite way to the plan's framing.** The plan cites
  "CUPE averages 168 words vs a 100–150 band", implying the ceiling should rise. Measured:
  **39.9% of CUPE summaries fall below 100 words** and only **15.1%** exceed 300 (max 671);
  the 168 mean is that thin tail pulling. Raising the ceiling addresses 15% and leaves the
  40% that are too short untouched — and `SUMMARY-TOO-SHORT` is already ungated
  (`gates.yaml` tension #1), so the cohort's commonest summary defect blocks nothing today.
- **Genuine WJQ-specific gaps worth registering:** `SFU-QUAL-SKILL-MODIFIER` (76.1% vs
  5.1%) and `SFU-AUTH-ABILITIES-OBSERVABLE` (32.2% vs 0.4%) — the WJQ's qualification
  conventions differ sharply from the JDFN's.
- **A number to distrust before using it:** JDFN parses a **median of 1** qualification
  (mean 1.0) against WJQ's 21. That is the JDFN qualifications block landing as one blob,
  not JDFN roles having one qualification — so any qualification-count threshold calibrated
  on JDFN would be calibrated on a parser artifact.

## 5. How to reproduce

```
JD_ARCHIVE_PATH=C:/repos/hris/fixtures/SFU_JDs \
JD_BASELINE_OUT=./out/baseline-phasec \
docker compose run --rm -T baseline python -m src.jd_bank.baseline --commit-to ""
```

⚠ **`--commit-to ""` does not skip the committed write, it redirects it to the container's
CWD** — the run drops `summary.json` / `errors.jsonl` into `core/`. Delete them afterwards.
Omitting the flag entirely **overwrites the committed `docs/baseline/summary.json`**, which
is the same hazard already recorded for `make embed --limit`. The committed baseline was
verified unchanged by this run.
