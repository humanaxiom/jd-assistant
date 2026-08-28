# Plan — the department taxonomy (a full sweep, built to be accurate)

**Status:** design only, no code. Written 2026-08-27.

> 🔴 **SUPERSEDED AS THE PRIMARY MECHANISM (2026-08-27).** Measurement showed IT at SFU is
> both central and embedded — a duty-text sweep found **121 IT roles sitting in faculties
> and business units**, none of them in a central IT department. **No org chart gathers a
> function.** See [`FUNCTIONAL-ROLE-TAXONOMY.md`](FUNCTIONAL-ROLE-TAXONOMY.md).
>
> **This document remains valid** for what it actually does: department as a *filter*
> ("IT roles in the Faculty of Science"), and the 739-string sweep below still stands. It is
> **no longer blocked on an authoritative org list**, because it is no longer how a function
> gets defined.


**Why:** the IT demo exposed department fragmentation, and the same fragmentation blocks
every other unit. This is the general capability, and **accuracy is the requirement, not
coverage.**

**⚠ This document corrects an estimate in
[`IT-SUBSET-DEMO-AND-FACETS.md`](IT-SUBSET-DEMO-AND-FACETS.md).** That plan called the
department map "an afternoon of curation, ~150–250 strings". **It is 739 strings and it is
not an afternoon.** The measurements below are why.

---

## 1. The sweep — what is actually there

Measured against the live Bank, 2026-08-27:

| | |
|---|---:|
| distinct department strings, **drafts** | **739** (across 1,799 drafts) |
| distinct department strings, **all parses** | **1,483** (across 8,830 documents) |
| drafts with no department at all | 690 of 2,489 (**27.7%**) |

**Coverage is a long tail with no convenient cut:**

| | drafts covered | % |
|---|---:|---:|
| top 25 strings | 546 | 30.4% |
| top 50 | 733 | 40.7% |
| top 100 | 963 | **53.5%** |
| top 200 | 1,204 | 66.9% |
| **appear exactly once** | **483 strings (65.4%)** | |

**Curating the top 100 buys barely half the corpus.** There is no 80/20 here.

## 2. 🔴 The finding that decides the design

**Mechanical normalisation collapses 7.4%.** Casefolding, unifying `&`/"and", stripping
`SFU`/`the` prefixes, dropping punctuation and collapsing whitespace takes **739 → 684**.

**The fragmentation is semantic, not typographic.** These are not spelling variants:

```
Information Technology Services   11
Information Technology            10
IT Services                       10
IT Client Services                 3
Academic Computing Services        3
Library Systems                    3
Service Desk                       1
```

No algorithm can tell you whether *IT Client Services* is a **child of** *Information
Technology Services* or a **peer** of it, or whether *Library Systems* belongs to IT at all
or to the Library. **That is an org-chart fact, not a string-similarity fact** — and every
fuzzy-matching approach will guess, confidently, and be wrong in ways nobody notices until
a stakeholder sees their unit merged into someone else's.

**Accuracy therefore requires an authoritative source and human sign-off. There is no
shortcut, and pretending otherwise is how this feature becomes untrustworthy.**

## 3. The tail is four different problems, needing four different fixes

Sampling the 483 singletons shows they are **mostly legitimate**, not garbage:

| kind | example | right treatment |
|---|---|---|
| **genuine small unit** | `Department of Gerontology`, `Office of the Ombudsperson` | its own canonical unit — do **not** merge |
| **sub-unit that rolls up** | `SFU Surrey Facilities Services`, `Service Desk`, `VPR Animal Care` | **hierarchy** — a child, *not* an alias |
| **mechanical variant** | `Marketing & Communication` vs `Marketing and Communications` | deterministic normalisation (~55 strings) |
| **parse error** | `(Office of the Registrar) Financial Assistant` — a job title in the department field | exclude + fix the parser (**~30 strings, ~4%**) |

**The critical distinction: `SFU Surrey Facilities Services` is not a misspelling of
`Facilities Services` — it is a child of it.** A flat alias map either destroys that
(rolling a campus into its parent, losing a real distinction) or refuses to merge (leaving
the fragmentation). **The model has to be a two-level hierarchy: unit → sub-unit.**

⚠ Parse errors being only ~4% is good news and a trap: it means **the data is mostly real,
so a wrong mapping is a wrong statement about a real unit**, not noise cleanup.

## 4. Design

### 4.1 The authoritative source comes first

**Do not invent canonical units from JD text.** SFU has a real org structure — the HR
system, the SFU web directory, the Faculty/VP portfolio list. **Obtain it and map to it.**

This is the single decision that makes the feature accurate. Without it we are inventing a
taxonomy from the very strings whose inconsistency is the problem, and we will not be able
to answer "why is my unit under that heading?" when a dean asks. **If no authoritative list
can be obtained, say so and scope the feature to the units we can defend** — a correct
partial taxonomy beats a complete invented one.

### 4.2 A reviewed map, as rulebook data

`department_taxonomy.yaml`, registered like every other non-trivial default:

```yaml
units:
  information_technology_services:
    label: Information Technology Services
    parent: vp_finance_administration        # from the authoritative source
    sub_units:
      it_client_services: { label: IT Client Services }
      service_desk:       { label: Service Desk }
    matches:                                  # exact strings, never patterns
      - Information Technology Services
      - Information Technology
      - IT Services
```

**Exact strings, never regexes.** A pattern silently captures the next unit that happens to
contain the word — which is precisely how *School of Computing Science* would land in IT.
Every mapping is a listed, reviewable line.

### 4.3 Human review, on grouped candidates

The tooling's job is to **present candidates, never to merge.** Grouping the 739 strings by
lead significant token yields **~206 groups (102 multi-string, 104 singleton)** — so a
reviewer makes **roughly 200–240 decisions, not 739.** That is a day or two with someone who
knows SFU, not an afternoon, and not a month.

Output: a worksheet of `raw string → proposed unit → [confirm / reassign / own unit /
exclude]`, ordered by draft count so the highest-impact decisions come first and the work is
useful even if it stops early.

### 4.4 Honest rendering

- Every facet shows coverage: *"department known for 72.3% of roles"*.
- A permanent **`(not stated)`** bucket for the 690 drafts with no department — visible, never
  silently dropped.
- An **`(unmapped)`** bucket for strings not yet curated, with its count. **The map is
  allowed to be incomplete; it is not allowed to be silently incomplete.**

## 5. Sequence

| # | step | who | size |
|---|---|---|---|
| 1 | **Obtain SFU's authoritative org list** | needs SFU | the blocker — start now |
| 2 | Deterministic normalisation (7.4%) + exclude the ~30 parse errors | eng | small |
| 3 | Generate the grouped review worksheet (~206 groups, ordered by impact) | eng | small |
| 4 | **Human curation against the authoritative list** | SFU + eng | 1–2 days |
| 5 | `department_taxonomy.yaml` + registered entry + facet rendering | eng | medium |
| 6 | Per-unit statistics (the dashboard) | eng | medium |

**Step 1 is the long pole and it is not engineering.** Steps 2–3 can proceed in parallel and
make step 4 cheap — but doing 4 without 1 produces a taxonomy we invented, which fails the
accuracy bar this document exists to meet.

## 6. What this does not block

**The IT demo does not need any of this.** The ITP cohort comes from source filenames
(368 documents → 45 roles → 32 approvable) and is unaffected by department fragmentation.
Ship the demo on the curated collection; the taxonomy is the follow-on that generalises it
to every other unit.

## 7. Risks

- 🔴 **Inventing the taxonomy** because the authoritative list is slow to obtain. It will be
  wrong in ways only the affected unit notices, and it will be quoted back to us.
- ⚠ **Fuzzy matching creeping in** as "just to get started". `Faculty of Science` and
  `Faculty of Health Sciences` are different faculties, three characters apart.
- ⚠ **Treating sub-units as aliases**, collapsing real campus/function distinctions.
- ⚠ **The 27.7% with no department** being read as "small" — it is 690 roles, larger than
  any single unit in the corpus.
