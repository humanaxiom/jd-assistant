# Plan — functional role taxonomy (what people DO, not where they sit)

**Status:** design only, no code. Written 2026-08-27.
**Supersedes** the org-chart premise in
[`DEPARTMENT-TAXONOMY.md`](DEPARTMENT-TAXONOMY.md), which remains valid as a *facet* but is
the wrong instrument for finding a function.

> 🔴 **SUPERSEDED IN PART, 2026-08-27 — read
> [`IT-FUNCTIONAL-SWEEP-MEASUREMENT.md`](IT-FUNCTIONAL-SWEEP-MEASUREMENT.md) alongside this.**
> The method below is right and is what was executed. Its **numbers are not**: every
> "128 / 121 / ~166 roles" figure on this page came from the biased term list this document
> itself condemns in §2, and none of them reproduces. The corrected sweep measured that
> **no threshold is both precise and complete** (98% recall costs 1,141 candidates; at ~166
> candidates recall is 48.9%), which turns §3.2's "rank, never auto-assign" from a
> precaution into a requirement. **Treat every role count on this page as an estimate that
> was tested and failed.**


---

## 1. The org-chart approach was wrong, and here is the proof

**IT at SFU is both central and embedded.** A department mapping can never gather it,
because most IT people do not sit in an IT department. Measured against the live Bank:

A duty-text sweep for IT work finds **128 roles**. Only **7** are in the ITP filename
family. The other **121 sit in faculties and business units**:

| role | department |
|---|---|
| Computer and Network Support Technician | Faculty of Science |
| Computer Systems Analyst | Mechatronics |
| System Administrator | Continuing Studies |
| Library Systems Technician | Library Systems |
| Computer Support Technician | Learning & Teaching Technology |
| IT Technician | Beedie School of Business |
| Computer Systems Administrator | Computing Science |
| Technical Support Specialist | Linguistics |
| Technical Support Technician | Earth Sciences |
| Computer Systems Technician | Mechatronic Systems Engineering |

**Not one of these is in a central IT department.** A department facet reporting
*"IT Services: 10 roles"* would be wrong by more than an order of magnitude, and it would
be wrong in the direction that makes the CIO's own staff invisible.

## 2. 🔴 And the first term list I wrote was biased — that is the harder lesson

The same sweep **missed 38 of the 45 ITP roles**, which are unambiguously IT:
*Network Engineer*, *Identity Management Architect*, *Application Developer*,
"LAN/WAN networks", "data centre solutions".

**Why:** my term list — `troubleshoot`, `workstation`, `helpdesk`, `printer`, `peripheral`,
`backup` — encoded one mental model of IT: **desktop support**. Architects and engineers do
not write duties in that vocabulary, so the sweep silently excluded the senior half of the
function.

> **A hand-written term list is a hypothesis about a job family, and it will be shaped by
> whoever writes it.** This one was wrong in a way that was invisible until checked against
> a known-good cohort. **Every functional definition must be validated against a
> known-good set before it is trusted, and the validation must be able to fail.**

## 3. The design that follows from those two facts

### 3.1 Multiple independent weak signals, unioned for recall

No single signal is sufficient — that is the measured finding, not a precaution:

| signal | strength | measured |
|---|---|---|
| **duty text** | the function itself | 99.1% of drafts have duties; found 121 embedded IT roles |
| **classification family** (filename) | authoritative where present | ITP = **469** docs → 45 roles; the ONLY signal that finds the analyst half (measured) |
| **title** | fast, unreliable alone | "Technical Support Specialist" is IT; "Research Technician" may or may not be |
| **department** | weak for function, useful as a *filter* | most IT roles are not in an IT department |

**Union them for candidates. Never intersect** — intersection would have produced **7 IT
roles** instead of ~166.

Estimated true IT cohort: **128 functional + 45 ITP − 7 overlap ≈ 166 roles**, versus the
45 the filename family alone gives and the ~40 a department facet would.

### 3.2 Rank candidates; never auto-assign

Each candidate carries **why it matched** — which terms, which family, which title token.
A reviewer confirms or rejects. The output is a curated membership list, stored as data.

⚠ **No similarity threshold.** Role-vector similarity was measured on this corpus and
**unrelated roles outscore true twins** — the standing rule is *rank, never threshold, and
never show a percentage*. Embeddings may **order** a review queue; they may not **decide**
membership.

### 3.3 Functional families as rulebook data

`functional_families.yaml`, registered like every other non-trivial default:

```yaml
information_technology:
  label: Information Technology
  evidence:
    # ⚠ MATCHED ON WORD BOUNDARIES, never as substrings: `lan` as a substring
    # matched 1,568 of 2,493 roles (plan, planning, Langara). See the measurement §7.
    duty_terms: [network, server, hardware, software, troubleshooting, operating system,
                 architecture, identity management, application development, data centre]
    classification_families: [ITP]
    title_terms: [systems analyst, network, computer, technical support, developer]
  members:   [...]      # the REVIEWED list — the authority
  excluded:  [...]      # with a reason; a rejection is evidence too
```

**`members` is the authority, not `evidence`.** Evidence generates candidates; the reviewed
list is what the UI reads. That way a mis-sort is fixed by editing a line, not by tuning a
term list and re-running everything downstream.

### 3.4 Every family reports its own recall risk

A family page states its recall honestly, e.g. *"45 roles confirmed from the ITP classification family; N added by review from a ranked duty-text queue; the duty sweep alone reaches 98% recall only by returning 46% of the archive, and it nearly misses every IT **analyst** role."*

**This is not decoration.** It is the only defence against the §2 failure recurring
silently in the next family somebody defines.

## 4. Building the other families

The IT sweep is the template, and the method transfers:

1. **Seed from a known-good cohort** where one exists (a classification family, a
   department that really is coherent, a hand-picked list).
2. **Sweep duty text** for candidates.
3. 🔴 **Measure recall against the seed.** If the sweep misses seed members — as mine
   missed 38 of 45 — **the term list is wrong, not the seed.** Widen and repeat.
   ⚠ **And measure it in more than one direction.** The IT list has now failed four times:
   missing the engineers, then the analysts, then the leadership, and finally anyone whose
   JD does not use the vocabulary at all. Recall against one seed proves one direction.
4. **Review candidates**, capturing rejections with reasons.
5. **Publish with the recall statement.**

Plausible next families: Finance/Accounting · HR · Facilities/Trades · Research
Support/Lab · Student Services/Advising · Communications/Marketing · Library.

⚠ **Do not build ten families at once.** Do IT end-to-end, learn what step 3 teaches, then
generalise. A taxonomy is easy to define and expensive to correct once people cite it.

## 5. What this changes about the earlier plans

| plan | status |
|---|---|
| [`IT-SUBSET-DEMO-AND-FACETS.md`](IT-SUBSET-DEMO-AND-FACETS.md) | **still valid; the story changes shape.** The demo leads with the **45 authoritative ITP roles** and adds embedded IT as a **reviewed** list, because no computed total is defensible (measurement §1). The CIO story is *"your IT function is larger than your IT department, and here is the ranked list"* — not a number. |
| [`DEPARTMENT-TAXONOMY.md`](DEPARTMENT-TAXONOMY.md) | **demoted, not cancelled.** Department stays a useful *filter* ("IT roles in the Faculty of Science") and the 739-string sweep still stands. It is no longer the way to define a function, and it is **no longer blocked on an authoritative org list** for this purpose. |

**The org-list ask is no longer the long pole.** That is the practical win from this change
of approach: the functional sweep runs on data we already have.

## 6. Risks

- 🔴 **A biased term list, silently under-recalling.** Already happened once (§2). Mitigation
  is step 3, and it must be able to fail.
- ⚠ **False positives from generic verbs.** "Research Technician" in FASS scored 8 — plausible
  but needs a human. **Candidates are candidates.**
- ⚠ **Families that overlap.** A Library Systems Technician is IT *and* Library. Membership
  should be many-to-many; forcing one home will start an argument that is not ours to settle.
- ⚠ **Duty text quality.** Duties are 99.1% present but the CUPE cohort's duty *frequencies*
  are known-unreliable, and some statements read as fragments. Adequate for term matching;
  do not build anything finer on it without measuring first.
