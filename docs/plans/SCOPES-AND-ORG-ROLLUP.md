# Plan — scopes and the org rollup (so the second unit is not a rewrite)

**Status:** design. Written 2026-08-27 after the IT collection shipped.
**Requirement (from review):** the IT view is **instance #1 of a general unit view**, not a
one-off. The next unit is **VPFA** (Finance and Administration), **into which ITS rolls
up**. Build A4/A5 so adding VPFA does not mean rewriting the dashboards, queries and API.

Every number below is a query against the live Bank, run while writing this.

---

## 1. 🔴 The thing that would have caused the rewrite

**The IT collection is resolved by CLASSIFICATION, and VPFA does not have one.**

`functional_families.yaml` resolves membership from the **ITP token in a source filename**
— SFU's own job-family code. That works because IT *has* a classification family. It does
not generalize even one step:

| | |
|---|---|
| **ITP** | a classification. One code, 469 filenames, unambiguous. |
| **VPFA** | an org unit. Spans APSA, CUPE, APEX and more. **No code exists in any filename.** |

So "just point the existing resolver at VPFA" is not a small change — it is not possible.
A unit needs a **different resolver**, and the seam for it has to exist before A4/A5 are
written against `family`, or every dashboard, query and template learns the wrong shape.

**That is the rewrite this document is here to avoid, and it is why the fix goes in now
even though the VPFA data work does not.**

## 2. And the naive unit filter is 27× wrong — measured

The obvious implementation (filter `department` by the unit's name) fails harder for VPFA
than it did for IT. Draft-level counts:

| department string | roles |
|---|---:|
| Office of the Vice-President, Finance and Administration | **2** |
| Finance | 19 |
| Financial Services | 8 |
| Procurement Services | 7 |
| Financial Aid & Awards / Financial Aid and Awards | 8 |
| Budget Office | 4 |
| Student Accounts | 3 |
| Financial Reporting | 2 |
| Research Accounting | 2 |
| Financial Services - Purchasing, AVP Financial Planning Office, Payroll, Treasury … | tail |

**A filter on the unit's own name returns 2 roles. The portfolio is ~55+.** For IT the
same error was 10-vs-40; here it is worse, because a vice-presidency is *never* the string
written on a JD — the JD names the office the person actually sits in.

**A unit is a rollup, or it is wrong.**

## 3. ITS is the same shape — and it shows the second trap

| department string | roles |
|---|---:|
| Information Technology Services | 11 |
| IT Services | 10 |
| Information Technology | 10 |
| IT Client Services | 3 |
| Academic Computing Services | 3 |
| ESPM Enterprise Systems · Enterprise Systems | 4 |
| IT Services, Application Services · IT Services, Strategic Services | 4 |
| IT Client Services – AV Services | 2 |
| Research Computing | 2 |

≈ **49 roles across 11+ strings** for one unit.

⚠ **And the trap:** `School of Computing Science` (**13 roles**) and `Computing Science`
(2) are **academic units that teach computing**. They are not ITS, they do not roll up to
VPFA, and any substring match on "computing" or "IT" sweeps them in. **The alias map is
curated, never inferred.**

## 4. The design

### 4.1 A `Scope` is the unit of computation — everything takes one

Today a collection page takes a `FunctionalFamily`. Generalise that to a **Scope**: a named
set of roles, resolved by one or more **resolvers**, unioned, then adjusted by human
overrides.

```yaml
scopes:
  information_technology:          # instance #1 — what ships today
    label: Information Technology
    resolvers:
      - kind: classification
        families: [ITP]
    include: []                    # reviewed additions
    exclude: []                    # reviewed removals — beats everything

  vpfa:                            # instance #2 — NOT built yet
    label: Finance and Administration
    resolvers:
      - kind: org_unit
        unit: vpfa                 # resolves to vpfa AND ALL DESCENDANTS
    include: []
    exclude: []
```

**Resolver kinds, and what each is allowed to decide:**

| kind | decides membership? | status |
|---|---|---|
| `classification` | ✅ yes — SFU's own code | **built** |
| `org_unit` | ✅ yes — via the curated alias map + rollup | **designed, not built** |
| `explicit` (`include`/`exclude`) | ✅ yes — a human ruling, applied last | **built** |
| `duty_terms` | 🔴 **NEVER** — ranks a review queue only | **built**, and fenced |

⚠ **Resolvers are UNIONED, never intersected.** Measured: intersecting duty terms with the
ITP family would have deleted the analyst half of IT. That rule is not specific to IT and
carries over to every scope.

### 4.2 Org units are a tree, and a unit scope rolls up

```yaml
org_units:
  vpfa:
    label: Finance and Administration
    parent: null
    aliases: ["Office of the Vice-President, Finance and Administration",
              "Vice President Finance & Administration", "AVP Finance Administration"]
  its:
    label: Information Technology Services
    parent: vpfa
    aliases: ["Information Technology Services", "IT Services", "Information Technology",
              "IT Client Services", "IT Services, Application Services", ...]
  financial_services:
    parent: vpfa
    aliases: ["Financial Services", "Financial Reporting", "Research Accounting", ...]
```

Resolving scope `vpfa` = roles whose department string is an alias of `vpfa` **or of any
descendant** — so ITS roles appear under VPFA automatically, which is the requirement.

**`aliases` is the 739-string map** from
[`DEPARTMENT-TAXONOMY.md`](DEPARTMENT-TAXONOMY.md), finally given the shape it needs. That
plan measured the sweep and demoted department from *defining a function* to *being a
filter*; this adds the one thing it lacked — **a parent**, so a filter can roll up.

### 4.3 🔴 Every scope must publish its own coverage

A unit rollup reads `department`, and **department is missing on 692 of 2,493 drafts
(27.8%)**. Those roles can never appear under any unit, at any point, however good the
alias map gets.

> **A VPFA page that says "55 roles" without saying "and 28% of the Bank has no department
> recorded, so this is a floor" is the archive-claim error in UI form.** The collection
> page already publishes a recall note for exactly this reason; a unit scope needs the
> same, and its number is different from the family's.

## 5. What A4/A5 must do NOW (and it is small)

This is the whole "avoid the rewrite" ask, and it is a seam, not a feature:

1. **Every funnel/facet/aggregation query takes a `scope`, not a `family`** — and `None`
   means the whole Bank. One parameter, threaded from the route down.
2. **The scope resolves to a set of cluster ids** — which `resolve_members()` already
   returns. The existing signature is *already* the right seam; it only needs the
   argument generalised from `FunctionalFamily` to `Scope`.
3. **No query hardcodes ITP, IT, or a family key.** The IT collection becomes
   `?scope=it`, one row of config.
4. **Every facet reports coverage and a `(not stated)` bucket** — already required by
   [`IT-SUBSET-DEMO-AND-FACETS.md`](IT-SUBSET-DEMO-AND-FACETS.md) §Layer 2, and now doubly
   so because a unit facet's blind spot is 27.8%.

**Deliberately NOT now:** the `org_unit` resolver, the tree, and the alias curation. Those
need SFU's org structure from a person, and the review says plan them rather than build
them. The seam costs little today; retrofitting it after two dashboards and an API have
hardcoded `family` costs a rewrite.

## 6. What is still blocked on a human

- **The alias map** — 739 strings, curated per unit. Not inferable: §3 shows
  `School of Computing Science` looking exactly like ITS to any matcher.
- **The tree** — we have one edge from review (**ITS → VPFA**) and nothing else. SFU
  publishes no machine-readable org chart in this archive.

⚠ **Do not seed either by inference.** A wrong rollup is worse than an absent one: it
produces a confident number for a vice-president's own portfolio, which is precisely the
audience that will know it is wrong.

## 7. Risks

- ⚠ **Scope creep into org-chart modelling.** This needs a parent pointer and an alias
  list. It is not an HR org system, does not model reporting lines, positions or budgets,
  and must not grow into one.
- ⚠ **Two axes, easily confused.** *Function* (what people do — ITP) and *unit* (where they
  sit — ITS/VPFA) are independent, and the measured finding is that **they do not
  coincide**: most IT roles sit outside any IT department. A scope must say which axis it
  is, and the UI must not blur them.
- ⚠ **A unit page invites "why is my team missing?"** The honest answer is §4.3's coverage
  number, shown before it is asked.
