# The one-of-a-kind job — HR-223

**How many SFU jobs exist exactly ONCE, and what the Bank does with them.**

Regenerate with:

```bash
make singletons                              # -> singleton-summary.json
make singletons SINGLETON_ARGS="--examples 60"   # print more titles verbatim
```

Read-only: Postgres only, no Neo4j, no Ollama, no archive bind, and it writes no Bank
row. Safe to run at any time.

## Why this exists

The Bank's contract is *many documents become one role*. It has no answer for *one
document is already the role*: `build_clusters` takes EDGES as its only input, so a
document with no near-duplicate is never **considered** — it is not rejected by any rule.
`comparison.singleton_role_policy` records that as `drop` — what we do today, registered
as a decision rather than left as an accident, because it caps what the Bank can **ever**
publish.

This report measures the population that policy governs, so the numbers in the register
can be **re-derived by a person** instead of trusted. The first set of them was measured
by hand on 2026-08-28 and was stale within a day: `PARSER_VERSION` went v6→v7, 805 titles
were recovered, and every bucket here is title-based.

## How to read it

**Four buckets, never one total.** Reported as a single number, "documents with no
near-duplicate" hides three different situations:

| bucket | what it means |
|---|---|
| `unique_title` | The title appears exactly once in the archive — a genuinely singular SFU job, and the population HR-223 is about. |
| `shares_title_with_role_document` | A document with the same title **did** reach a role. That is a dedup recall miss (plan.md D3), not a unique job — the role already exists. |
| `shares_title_with_other_orphan` | A group the dedup never linked. Minting one role per document would duplicate it. |
| `title_unjudgeable` | 🔴 **COULD NOT EVALUATE.** The parser recovered no usable title, so neither answer is available. Reported, never folded into one. |

**The control is not decoration.** The same split is reported over the documents that
*did* reach a role. If the could-not-evaluate rate were as high there, the report would
be measuring the parser rather than the archive — that is exactly how a token scan once
"proved" 92% of ungrouped documents name no employee group while its control scored 49%.

**`unique_title` is an UPPER BOUND.** Only the definitional case is excluded — a title
with no letter in it (`#01246`) cannot be a job title. Banner text, truncated titles and
an incumbent's name are still counted, because they *are* unique strings, and a
junk-title classifier invented on a sample is the failure mode the register exists to
prevent. That is why titles are printed verbatim: the sample is there to be read.

**Means come with medians.** A mean over a thousand documents is an aggregate, and an
aggregate is where this project keeps hiding things.

⚠ **Documents, not roles.** Every count on this page is a count of archive documents.
