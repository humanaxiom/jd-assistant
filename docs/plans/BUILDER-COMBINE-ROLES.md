# Track H — Combine harmonized roles into a new JD

**Design only. Nothing here is built.** Written 2026-10-15 against the live code and the
live Bank. Every "already exists" below was read in the tree. The one number this
design depends on was measured; the query is given so it can be re-run.

Origin: a director's scenario. *"We have one or more harmonized JDs that we'd like to
combine for the new clone."*

---

## What it is

> A manager is creating a role that does the work of two (or three) roles SFU already
> has. For example, a new *Advising & Records Coordinator* who does what the *Academic
> Advisor* and *Records Assistant* roles do today. The Builder can clone **one** role.
> It cannot start from **several**.

The author picks 2–4 harmonized roles, chooses which one leads, chooses which duties to
keep, and lands on the normal Builder, pre-filled, scored, and ready to edit. From there
nothing changes: the draft goes to the same human-approval review queue (NN #1).

---

## 🔴 The design decision: it is the harmonizer's engine with a different *intent*

The director's question was whether the logic should be similar to the harmonization
code. **Yes for the machinery, no for the policy.** The two jobs are opposites:

| | **Harmonize** (`merge_cluster`) | **Combine** (this track) |
|---|---|---|
| Inputs | N variants of **one** role | 2–4 **different** roles |
| Goal | the **consensus** of the variants | a **new** role covering all of them |
| Something only one input says | **noise**, so it is dropped (core-skill ≥ 50%, HR-173) | the reason that role was picked, so it is **kept** |
| Order of inputs | must not matter (documented, tested order-invariance) | **does** matter: one role leads |
| Title / summary | picked automatically (modal / most central) | written by the author. Nothing can be modal across 2 different roles |
| Cap overflow (> 12 duties) | drop the lowest-coverage groups, then flag | **the author chooses** |

Run `merge_cluster` unchanged over two different roles and every one of its policies
gives a confident wrong answer. This can be read off the code:

- **Title:** with two different titles each appears once, so the tie-break picks the
  **shortest**. The combined role is named by string length.
- **Summary:** "most central" over two texts is symmetric (Jaccard(a,b) = Jaccard(b,a)),
  so it is always a tie, and again the **shortest** wins.
- **Duties:** across different roles almost every duty has coverage 1, and ties sort
  by **statement text**. The 12-duty cap would keep the **alphabetically first** duties.
- **Qualifications:** with 3 roles, a skill held by one of them is below 50% and is
  **dropped**. That is exactly the skill that role was brought in for.

🔴 **So: reuse the helpers, not the entry point.** A new pure function
`combine_roles(roles, *, lead, rules)` in `jd_core/bank/combine.py` shares the merge's
tokenizer, duty grouping, qualification grouping and dedup threshold (one home for each,
per the module's own warning about second copies drifting). It does **not** add a flag
to `merge_cluster`, whose order-invariance is a documented guarantee and the basis of
the change-log's member indices.

### Measured: the cap is the normal case, not an edge case

Live Bank, 2026-10-15, current version of each role:

| | roles | median duties | p90 duties | roles with ≥ 6 duties |
|---|---|---|---|---|
| harmonized | 2,499 | 5 | 12 | 626 |

```sql
WITH cur AS (SELECT DISTINCT ON (cluster_id) cluster_id, content, change_log
             FROM canonical_jds ORDER BY cluster_id, version DESC)
SELECT coalesce(change_log->>'origin','harmonized'), count(*),
       percentile_cont(0.5) WITHIN GROUP (ORDER BY jsonb_array_length(content->'duties')),
       percentile_cont(0.9) WITHIN GROUP (ORDER BY jsonb_array_length(content->'duties')),
       sum((jsonb_array_length(content->'duties') >= 6)::int)
FROM cur GROUP BY 1;
```

Two median roles give about 10 duties before dedup. Any pair from the top quarter
exceeds 12, and three roles usually will. **Picking duties is therefore the main step
of the UX, not an exceptional path.** The Builder's own form also caps duties at 12
(`ComposerAnswers.duties`, `max_length=12`).

⚠ **Not yet measured, and it decides a default (H0 below):** how much the 0.7 duty-dedup
threshold folds across *different* roles. It was set for variants of one role. Between
near-twins (*Advisor I* / *Advisor II*) it may fold most duties. Between unrelated roles
it may fold none. Both are fine. What matters is that the screen reports which one
happened.

---

## Policy for each section (all YAML, all registered `open`)

Standing rule: every non-trivial default is configurable and registered in the same PR.
A new `combine:` block in `rules/harmonization.yaml` holds these. Each one is
`our_invention`, `status: open`, and gets an HR-number when it is registered (numbers are
assigned then, not here).

| Section | Proposed default | Why |
|---|---|---|
| Max roles | **4** | Beyond 4, the duty picker is the whole page. |
| Form | **all the same form, or refuse** | A JDFN + WJQ mix has no single answer contract (Phase E). It is refused with an explanation, not resolved. |
| Title | **lead role's title, flagged "rename this"** | Nothing can be modal across different roles. The flag means the author has to make a choice. |
| Summary | **lead role's summary, flagged**, plus the existing ✨ *Suggest a summary* (`suggest_summary`) | The one section that genuinely needs new prose. The LLM assist already exists and is already validator-checked. |
| Duties | **union, folded at `duty_dedup_jaccard_min`** (reuses HR-171); ordered **folded-across-roles first, then lead role, then the others in the order picked**; pre-tick the first 12 | Deterministic, explainable, and it keeps every role's core work visible. |
| Duty % allocation | **cleared** | Two roles' percentages add up to about 200%. Carrying them over would fail the allocation gate on every combine. |
| Qualifications (skills) | **union, deduped** | The opposite of HR-173, on purpose (see the table above). |
| Education / experience bar | **highest of the roles** (same as HR-175 `max`) | The new role must be able to do all of the work. |
| Security | **union** (HR-174) | |
| Decision making / problem solving | **union** (same as HR-210 / HR-211) | |
| Relationships | **union of contacts** | Different from HR-212 (`longest`): a combined role really does have both roles' contacts. |
| Employee group | **if they agree, carry it; if they differ, leave blank and flag** | |
| Grade | **always blank**, with a note | Grade is a classification decision. Averaging two roles' grades into a value would be the "assumption presented as a measurement" defect. Grade data is also known to be unreliable (see `docs/audit/data-state-and-grade-2026-08-01.md`). |
| Department | **lead role's** | The author normally changes it. |
| Boilerplate | **on** | Same as today's clone (`_render_clone`). |

---

## Workflow and process

```
 find roles ─► basket ─► Combine page ─► Builder (pre-filled) ─► Submit ─► Review queue
 (search,      (2–4)     lead role +      title/summary flagged,   same      "Combined from
  role page)             duty picker      compliance panel live    path      A, B, C" + report
```

1. **Find.** The author finds roles where they already do today: the Builder's search
   (*Start from an existing JD*) or a role page in 🏦 JD Bank.
2. **Collect.** Each role result gets **➕ Add to combine** next to the existing
   *Start from harmonized role →*. A tray at the top shows *"Combining 2 roles: Academic
   Advisor ✕, Records Assistant ✕ — [Combine →]"*. Only **roles** can be added, not raw
   archive documents (director's ruling 2), and only roles on the same form.
3. **Combine page** (new, read-only). One page with three parts:
   - **The roles**: one column per role showing title, status (*draft* / *published*,
     labelled as role search already labels them), employee group, duty count, and a
     *Read →* link. A radio button picks the **lead role** (default: the first one added).
     Any warnings sit here: group mismatch, form mismatch (blocking), *"the roles you
     picked have 19 duties between them; the form holds 12"*.
   - **The duties**: one checklist. *"In more than one of these roles"* comes first,
     each line folded into one with a chip naming its roles. Then one group per role.
     12 are pre-ticked. A live counter shows *"12 of 12"*. Unticked duties are listed in
     the combine report, so nothing is lost silently.
   - **[Open in the Builder →]**
4. **Builder.** The usual page, pre-filled, with a banner: *"Combined from Academic
   Advisor (lead), Records Assistant. The title and summary are from the lead role:
   rewrite them to describe the new role. [✨ Suggest a summary]"*. The compliance
   panel and the inclusive-language meter work as they do now.
   The near-duplicate guard ("SFU already has these roles") **excludes all source roles**
   but still warns about any *other* existing role the result looks like. That warning
   is the most useful one here: the "new" combined role may already exist.
5. **Submit → review.** The same path as today (`submit_composed_draft`). The reviewer
   sees **"Combined from A, B, C"** with links, plus the combine report: which role each
   section came from, which duties were folded, which were left out.

**What combining does not do:** it does not touch, retire, or supersede the source
roles. They stay as they are. Retiring a role that the new one replaces is a separate HR
decision, made in the review queue, and is not a side effect of authoring.

### UX notes that follow from this project's own lessons

- **Show no similarity percentage between the picked roles.** Measured: role
  similarity has no threshold, and unrelated roles can outscore true twins. Show which
  duties fold, which is a fact, not a score.
- **Each section of the combine page reports three things:** what was carried, what
  was folded, and what was left out. A combine that silently produces a short draft is
  the confident-wrong-answer defect again.
- **No JavaScript.** The Builder has none today. The basket is a query string
  (`/compose/combine?roles=a,b,c&lead=a`): bookmarkable, read-only, and needs no
  session state or CSRF.
- **Discoverable (Directive #1.3).** The entry point sits next to the existing clone
  buttons on both the search page and the role page, and the 📖 Operator Guide gets a
  section.

---

## What already exists, and what is new

| Reused, unchanged | where |
|---|---|
| load a role's current canonical as a JD | `composer.search.load_role_clone_answers` (its query) |
| tokenizer, duty grouping, qualification grouping, dedup threshold | `jd_core.bank.merge` (`_resolve_duty_groups`, `_group_quals`, …) |
| JD → Builder answers, routed by form | `forms.form_for(jd).clone_from_jd` |
| land on a scored, pre-filled Builder | `compose_ui._render_clone` |
| compliance panel, gates, summary assist | `assess_draft`, `suggest_summary` |
| near-duplicate guard | `composer.duplicates.find_related_roles` |
| draft persistence + audit row | `composer.persist.submit_composed_draft` |

| New | notes |
|---|---|
| `combine_roles()`: pure, deterministic, ordered by lead role | `jd_core/bank/combine.py`. No I/O. Imports no `jd_bank` (layering ratchet). Returns the draft plus a per-section provenance record. |
| `combine:` YAML block + register entries | same PR, `make register`, commit the regenerated register |
| `GET /compose/combine` page + basket controls | `compose_ui.py`, a new `compose_combine.html` template, two template edits |
| lineage: `combined_from_cluster_ids` | additive, optional field on `AnswerContract` (old `answers_json` still validates). Written to cluster metadata, `change_log` and the audit row, as `cloned_from_cluster_id` is today, and **only when present** (the existing "absent key is the statement" rule). |
| guard excludes a **set** | `find_related_roles(exclude_cluster_id=…)` takes one id today |
| combine report on review detail | reads the provenance from `change_log` |
| smoke coverage | see H4. Required by Directive #0 / #1.5. |

---

## Slices

| | Slice | Gate |
|---|---|---|
| **H0** | **Measure first.** Run `combine_roles` (or a spike of it) over real role pairs: nearest-neighbour pairs from `jd_role_embeddings`, and random same-group pairs. Report the union duty count, how much folds at 0.7, the over-cap rate, and the group/grade disagreement rate. Write it up in `docs/FINDINGS.md`. **The defaults in the table above get confirmed or changed here, before any UI.** | numbers in hand |
| **H1** | `combine_roles` + the YAML block + register entries + tests (failing test first; one per policy; a lead-role-ordering test; a refuse-mixed-forms test) | `make gates-fast` + `make register-check` |
| **H2** | Combine page + basket on search and role pages + Builder banner | `make gates` |
| **H3** | Lineage through submit, set-exclusion in the guard, combine report on review detail | `make gates` (touches persistence) |
| **H4** | Extend `make smoke`: combine two **live** roles over HTTP → 200, Builder pre-filled, ≤ 12 duties, both sources named. Operator Guide section. | **`make smoke` green**, which is the ship gate |

Each slice is a branch and a PR (`core/` always is). Nothing merges with `make smoke` red
(Directive #0).

**Placement in `docs/plan.md`** (needs its own PR): alongside Track G, since both are new
ways into the Builder. By the owner's measure it **gives roles drafts**, specifically new
roles. It does not make an existing draft truer, so it should not jump MVP-1.

---

## Director's rulings (2026-10-15)

Relayed by the project owner. These are scope rulings, not rulebook values, so they live
here and in the detailed design, not in the HR register.

| # | Question | Ruling |
|---|---|---|
| 1 | Should a combined role replace (retire / supersede) its sources? | **No.** Combining only authors a new draft. The source roles are never touched. |
| 2 | Roles only, or raw archive documents too? | **Roles only.** |
| 3 | Can CUPE (WJQ) and APSA/Poly (JDFN) roles be combined? | **No.** A mixed selection is refused. Same-form combines (JDFN + JDFN, WJQ + WJQ) are in scope. |
| 4 | Should an LLM write a blended version? | **No LLM in the combine step.** The combine is deterministic. LLM help is available only on the **final draft**, through the Builder's existing author-triggered assist. |

Still open, as a registered default rather than a question: **the maximum of 4 roles**.

➡ **Detailed design, flows and slice plans for H0–H4:**
[`BUILDER-COMBINE-ROLES-DESIGN.md`](BUILDER-COMBINE-ROLES-DESIGN.md).
