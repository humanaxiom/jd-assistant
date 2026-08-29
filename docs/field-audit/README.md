# P3b — the identification fields against the RAW ARCHIVE

**`title` and `employee_group` were the only two fields ever compared against the source
files, and each produced defects on first contact** — two and one respectively.
`department`, `grade`, `classification` and `position_number` had never been checked at
all. This is that check, for the fields read from a LABEL.

```bash
make field-audit JD_ARCHIVE_PATH=<SFU JDs>
make field-audit JD_ARCHIVE_PATH=<SFU JDs> FIELD_AUDIT_ARGS="--sample 1200 --evidence 20"
```

Read-only: it opens the archive and reads Postgres, and writes no Bank row.

## How to read it

Five columns per field per bargaining unit, and **never one archive-wide percentage** —
`title` was never a general problem (47.6% of CUPE against 0.0% everywhere else) and the
aggregate hid that completely.

| column | means |
|---|---|
| `parser` | the parser stored a value (sentinel-checked, not `<> ''`) |
| `readable` | the document states a value under a name a registered mechanism CAN read |
| 🔴 `UNREAD` | the document states a value under a name **neither** mechanism can read |
| `blank` | the label is present and EMPTY — a blank form field, not a defect |
| `nolabel` | ⚠ **could not evaluate** — no field name containing a key word appears |

`readable − parser` is **the gap**: the archive states it, the Bank does not.
`--evidence N` prints that gap file by file, because an aggregate is not a finding until
the files behind it have been opened.

## 🔴 Identification labels have TWO provenances

Exactly the shape of the `employee_group` defect (FINDINGS §7):

- the **WJQ form** reads `wjq.id_labels` — rulebook data, whole-cell exact match;
- the **modern template** reads **hardcoded regexes** in `parser/headings.py`
  (`DEPARTMENT_LABEL_RX` and friends), which are not rulebook data at all.

`Department:` is unreadable by the first and read fine by the second. A probe that tested
only the registered list reported "no label found" for **129 of 129 APSA documents while
the parser held a department for 52 of them** — a probe contradicting the parser in the
parser's favour. So discovery (broad key word) and readability (could either mechanism
read it?) are separate steps here.

## ⚠ What this probe CANNOT see — published, not assumed

- **`classification` is not evaluated at all.** It is pulled by hardcoded regex
  (`_CUPE_GRADE_RX` and friends), not from a label, so a label probe says nothing about
  it. Reported as unevaluated rather than as clean.
- **`grade` is UNDER-counted for CUPE** — `parser` 465 against `readable` 98 — because
  `_CUPE_GRADE_RX` also finds grades in prose (`Secretary, Grade 6`). A negative gap here
  is the probe's blind spot, not a defect.
- **Discovery is by key word**, so a field named without one is invisible. The key words
  and the exclusions are printed in the output: an exclusion is a claim, and a claim you
  cannot see is one you cannot check.
- 🔴 **The probe reads the WHOLE document; the parser reads only the identification
  block.** So the gap is an **upper bound** on what any scope-matched fix recovers. See
  FINDINGS §9 — the value is often on the cover page, outside the parser's scope by
  design.
- Residual value noise: a handful of rows capture an adjacent label as a value
  (`'Position Number(s)' -> 'Current Position'`). Read the evidence rows, do not total
  them.

## Three of its own defects, each caught by re-measuring

Recorded because each would have become a fabricated finding, and the same shapes recur:

1. **Probe scope ≠ parser scope** — the two-provenances defect above.
2. 🔴 **Substring instead of word boundary** — the rule this project had already written
   down. `grade` matched **upgrade**, so duty prose was reported as a stated grade.
3. 🔴 **The fix for (2) caused a worse bug.** `\b` asserts a word/non-word *transition*,
   so `\bposition #\b` cannot match `Position #:`. APSA `position_number` fell from 4,836
   readable to 310 while the parser still held 4,753 — **a probe disagreeing with the
   parser by 4,443 is reporting its own defect.** Lookarounds now say what was meant:
   not butted against a letter or digit.
