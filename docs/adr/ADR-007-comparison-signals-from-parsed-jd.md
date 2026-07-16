# ADR-007: Deriving Comparison Signals from a Parsed SFU JD

**Status:** Accepted
**Date:** 2026-07-15

## Context

Phase 2.4c landed three pure modules — `bank/similarity.py`, `bank/clustering.py`,
`bank/drift.py` — as tested maths **deliberately not wired to anything**. Their inputs
did not exist: a `SFUJobDescription` (`models/parsed_jd.py`) carries no skill set, no
structured education level, no years bar and no normalized title — only free-text
`qualifications`, a `relationships.supervisory` blob, and a raw `title`. hris fed those
functions from a Neo4j skill graph, a skill ontology (family weighting) and an idf table
built from résumé matching; JD Bank has none of the three.

Phase 3.4b's Tier-3 role-equivalence runner needs a single feature object per JD to
consume. **3.4a is the pure adapter that produces it** — `ParsedJD → JobSignals` — plus
the two drift-helper fixes the derivation depends on. No runner, no candidate generation,
no idf, no hard constraint, no Tier-3 threshold: those are 3.4b.

Everything here was designed against the **live archive** (14,565 JDs), and the numbers
below are measured, not assumed (CLAUDE.md: *every claim about the archive must be checked
against the archive*):

- Qualification-kind counts: `skill` 56,651 · `education` 12,885 · `ability` 10,157 ·
  `experience` 8,148 · `knowledge` 4,786. **41% of JDs have ZERO qualifications** — their
  skill set is correctly empty.
- The skill vocabulary is **5,584 free-text tokens dominated by noise**; the 20 most
  frequent (`ability, excellent, knowledge, skills, with, experience, work, degree, …`)
  swamp any signal.
- JDFN **embeds the degree and the years inside the `knowledge`-kind blob** (e.g.
  *"Bachelor's degree in Computing Science or related discipline, and five years of
  related experience; or an equivalent combination…"*). Reading education from
  `kind == "education"` alone finds a degree in **40 of ~10,000** JDFN JDs; reading over
  ALL qual text finds one in **8,414 of 8,560 (98%)**.
- The digit-only years regex matched **226** JDFN JDs; JDFN spells years out
  (`"five years"`), and the spelled-out forms make **4,585 of 4,888** derivable.

## Decision

`bank/signals.py` derives a frozen `JobSignals(skills, education_ordinal,
experience_years, supervisory_reports, title, normalized_title, family, function,
comma_supervisory, restricted, employee_group, department)` — the single surface Tier-3 /
drift / clustering consume — purely from a parsed JD and the rulebook. It imports no
`jd_bank` (the layering ratchet) and does no I/O.

1. **Skills are a keyword bag from the `{skill, knowledge, ability}` quals** — lowercase
   `[a-z0-9]+` tokens, minus a measured stopword list (the top-20 noise) and tokens
   shorter than `skill_min_token_len`. `experience`/`education` are excluded because they
   inject year-counts and degree words. **Not a canonical skill set**; idf-weighting is
   deferred to 3.4b. Empty for the ~41% of JDs with no quals — honest, not a bug.
2. **Education is read over `{education, knowledge}` qual text** (`education_source_kinds`)
   via the existing `education_level_from_text` primitive, so JDFN's `knowledge`-blob
   degree is found — but NOT over `skill`/`ability`, whose "high degree of accuracy"
   clerical phrasing the bare `degree` cue misreads as a bachelors (measured: all-6 kinds
   inject 1,161 such false positives; `[education, knowledge]` keeps 93.6% of the win with
   4).
3. **The experience bar recognises digits AND spelled-out years** (`experience_word_numbers`),
   read from `experience_source_kinds` **in order** — the `experience` quals first, then
   the `knowledge` blob as fallback (both DATA, HR-154).
4. **The title is normalized once** into a `CanonicalTitle` (stem + SFU family/function +
   comma-supervisory + reserved-phrase flag), reusing `normalize_title`, `classify_title`
   and `titles.yaml :: restricted` — no re-implementation.

Every new knob is DATA in the (hashed) `comparison.yaml` and registered `open` /
`our_invention` (HR-149…HR-153); the two drift helpers are amended (HR-102 gains the
word-number sibling; HR-153 names the education source kinds).

## Alternatives considered

- **Build a skill ontology** (canonical names + family weighting), as hris had.
  *Rejected/deferred*: the archive skill vocabulary is 5,584 free-text tokens; a real
  ontology is a project of its own needing a JD subject-matter expert. It can be added
  later behind the same `JobSignals.skills` field with zero re-plumbing.
- **Shingle-based skills** (character/word n-grams instead of tokens). *Rejected*: shingles
  are not nameable, and drift's `added`/`dropped` lists and cluster labels must be
  human-readable skill words.
- **No stopwords / no idf, raw tokens.** *Rejected*: the top-20 tokens are noise; every
  pair of JDs would "overlap" on `ability` and `experience`, and clustering would collapse.
- **Read education from `kind == "education"` only.** *Rejected*: measured to miss the
  JDFN degrees that live in the `knowledge` blob (3,307 corpus-wide vs 7,880).
- **Read education from ALL qual kinds.** *Rejected*: the bare `degree` cue turns CUPE
  clerical "high degree of accuracy" (`skill`/`ability`) into 1,161 false-positive
  bachelors — a systematic upward bias on typists. `[education, knowledge]` removes 99.7%
  of them for 6.4% of the win.
- **Keep the digit-only years regex.** *Rejected*: measured to miss 95% of derivable JDFN
  year bars, which are spelled out.

## Consequences

- **Honest degradation from hris's ontology-backed pipeline**, declared rather than
  smuggled: skills are a keyword bag, seniority is coarse (single ordinal + a max
  year-count heuristic), and 41% of JDs yield empty skills. The register entries state
  each consequence.
- **The `JobSignals` contract is the single consumer surface.** 3.4b's runner, and any
  future re-cluster, depends only on this object — so an ontology, an idf corpus, or a
  better seniority model can be added later with no change to the consumers.
- **`a`/`an` → 1 is deliberately NOT supported** for spelled-out years (an unmeasured
  call; mapping determiners to a count risks false positives). Flagged for review in
  HR-152.
- `comparison.yaml` is hashed, so these knobs churn `rules_version` — correct, because
  they change what the clusterer computes.
