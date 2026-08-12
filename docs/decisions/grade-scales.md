# HR Decision — the per-group grade / classification scales

**For:** SFU Human Resources · **Status:** OPEN (awaiting HR) · **The 15-minute ask:**
`grade-scales-hr-ask.md` · **Background:**
`docs/audit/data-state-and-grade-2026-08-01.md` (the data-state review).

## Why this is a decision, not a setting we can pick

Pay is set from a position's **grade/classification**, and **each employee group has its
own scale** — there is no single scale across groups. The JD Bank can *carry* a grade per
role (the structured `classification{scheme, value, source}` field, Phase A shipped), but
it cannot **validate or rank** a grade until SFU tells us each group's scale. We will not
invent one.

This decision is deliberately **not** yet encoded as a build-enforced rulebook default
(`grades.yaml` + the HR decision register), because the register cross-checks every
default against the live value on every build — encoding a *guessed* scale would either
block the build or bake in a placeholder HR would have to unwind. The moment HR fills the
table below, we wire it in (one small PR: `grades.yaml` + register entries, `status: open`
→ `ratified`).

## What we measured (evidence)

| Group | In the JD document? | Observed grade values in the archive |
|---|---|---|
| **CUPE** | **Yes** — **2,322** parsed | numeric: **6, 7, 8, 10, 11** seen (a "Grade N" / "Gr. N" line) |
| **APSA** | **Yes** — **687** parsed | stated in the modern template's identification header |
| **APEX** | **Yes** — **34** parsed | same header field |
| **Polytechnic** | None found | — |

**3,049 of 14,522 (21%) state a grade we can read; 11,473 state none at all.**
Source: `extract_classification` over the archive at parser `v3`, re-counted 2026-08-11.

> ⚠️ **This table was wrong until parser v3 and has been corrected.** It previously said APSA
> "rarely" prints a grade, and that the real value lived in a separate HR system. Both were
> false. The modern
> SFU template keeps its whole identification block — grade included — in the **docx header**,
> which extraction used to skip; v3 reads it. And there is **no live system of record to hold a
> grade in**: the system this JD subsystem was ported from is itself still in development and
> contains no usable data. Nothing here should be planned around an import from it.

## What HR must provide (fill this in)

For **each** group, the ordered list of valid grade values (and any label):

| Group | Scale kind | The full ordered list of valid grades | Notes |
|---|---|---|---|
| CUPE | numeric | e.g. `1, 2, … 14` ? | confirm the min/max |
| APSA | ? | ? | Hay-graded → what does the grade look like? |
| APEX | ? | ? | |
| Polytechnic | ? | ? | |

Also decide:
- Is grade ever a **publish gate**, or purely advisory metadata? *(recommended: advisory)*
- **Where does grade come from for the 11,473 JDs that state none?** There is no live system to
  import from, so this is a method question. *(Recommended: HR supplies the valid values above,
  which turns grade entry into a checked dropdown on the authoring form and the reviewer's
  screen — both fields already exist — and the reviewer sets it at approval, where the authority
  already sits. Separately, HR spot-checks a sample of the 3,049 we already read; if the sample
  is right we accept them and 21% of the archive arrives graded for an afternoon of HR time and
  no engineering.)*
- If a system of record ever does hold grades, a bulk import would be a small addition — but it
  would move compensation data and needs a **FIPPA review first**. Reviewer-entered grades on an
  internal system raise no new privacy question.

## The config we will ship once ratified (template)

When the table above is filled, this becomes `src/jd_core/rules/grades.yaml` (unhashed —
it never changes how a JD is *scored*; a metadata/reference decision, like `quality.yaml`),
with one register entry per scheme (`status: open` until ratified):

```yaml
# grades.yaml — PROVISIONAL / UNRATIFIED. Per-employee-group grade scale.
# rules_version is NOT affected (unhashed): the grade is advisory metadata, never a gate.
schemes:
  cupe:
    label: "CUPE 3338 pay grade"
    kind: numeric
    parse_from_document: true      # the JD prints "Grade N" (~64% recoverable)
    values: [ ]                    # HR: the full ordered list (observed: 6,7,8,10,11)
  apsa:
    label: "APSA salary grade"
    kind: unknown                  # HR: confirm the scale
    parse_from_document: false     # assigned post-authoring; not in the JD
    values: [ ]
  apex:
    label: "APEX classification"
    kind: unknown
    parse_from_document: false
    values: [ ]
  poly:
    label: "Polytechnic classification"
    kind: unknown
    parse_from_document: false
    values: [ ]
```

Until then the grade is captured (parsed for CUPE; entered in the Builder/review for the
rest) and shown **with its provenance**, but never validated against a scale.
