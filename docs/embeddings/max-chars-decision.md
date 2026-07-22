# HR-126 `max_chars` — the design decision (prepared 2026-07-22)

> Status: **DECISION PREPARED, not yet executed.** The re-embed + validation step
> needs the Ollama host on `aria-gb10-2`, which is occupied by the full-archive
> canonical run until it completes (~2026-07-24). This document is the design call so
> that step is one command away when the GPU frees. HR-126 stays **`open`** in the
> register — this records *our* engineering decision, not an HR ratification.

## The problem, in one paragraph

`embeddings.max_chars` (currently `10000`) is a **character** cap standing in for a
**token** limit. The server (`nomic-embed-text` on `aria-gb10-2`) hard-rejects any
input over **8,192 tokens** with an HTTP 400 — it never silently truncates. Characters
per token is not constant: legacy boilerplate-heavy `.doc` text runs ~1.5 chars/token,
but the dense WJQ text the v2 parser now recovers runs closer to **~1.1 chars/token**.
So a single char cap cannot simultaneously (a) avoid truncating real content and
(b) stay under the token limit for the densest documents. It is a genuine design
decision, not a knob tweak.

## What changed — the original basis is falsified

`max_chars=10000` was chosen at Phase 3.2b (2026-07-13) on a measurement that is now
**stale**. It predates the WJQ template parser and the docx table/content-control
recovery, both of which pulled dense real text *back into* the serialization.

| Serialized doc length (all 14,522 v2 parsed JDs) | Phase 3.2b (pre-WJQ) | Re-measured v2 (2026-07-21) |
|---|---|---|
| median | 2,559 | **3,909** |
| p99 | 5,993 | **11,816** |
| p99.9 | 8,870 | **12,825** |
| max | 8,987 | **13,486** |
| exceed 10,000 (→ **truncated**) | **0** | **1,400 (~9.6%)** |

Of those 1,400 truncated docs, **~11 are so dense that even the 10,000-char-truncated
text still exceeds 8,192 tokens** → a live 400 → the runner skips them and they get
**no document vector at all** (`bad_requests: 11` in the last embed run —
`docs/embeddings/summary.json`).

**There is no single `max_chars` that avoids both truncation and the 400.** The
densest docs are genuinely longer than the model's window (13,486 chars ≈ ~11k tokens
at 1.2 chars/tok). Lower the cap → fewer 400s but *more* of the 1,400 truncated. Raise
it → less truncation but *more* 400s. This is the trade the decision has to name.

## What the doc vector is actually for

`max_chars` governs the **whole-document** vector only. That vector feeds Tier-3
role-equivalence dedup, search, and clustering — the **retrieval substrate**, *not* the
approval bar (the validator never reads a vector; HR-126 is excluded from
`rules_version` for exactly this reason). Two facts bound the blast radius of any doc
vector loss:

1. **Section vectors are separate and un-truncated in practice.** `position_summary`,
   `duties`, and `qualifications` each get their own embedding (HR-130). Every one of
   the ~11 over-window docs has each *section* comfortably under 8,192 tokens — the
   length comes from *summing* sections, not from any one being huge. So the
   load-bearing role signal (what the JD's duties and quals say) is embedded **in full**
   for these docs even when the document vector is partial or absent.
2. **Truncation is whole-unit and provenance-honest.** `SerializedText.truncated` and
   the pre-truncation `text_chars` are already stamped on every node, so a partial
   vector is *marked* partial, never silently passed off as complete.

## The four options, evaluated

| # | Option | Info loss | Complexity | Idempotent? | New dep? |
|---|---|---|---|---|---|
| a | Progressive re-truncation on a 400 | small (only the ~11) | low | ~ (see below) | no |
| b | Chunk long docs + mean-pool the vectors | none | **high** | yes | no |
| c | Doc vector best-effort; lean on section vectors | the 1,400 stay partial/absent | **none** (already the behavior) | yes | no |
| d | Lower `max_chars` to a token-safe floor (~8,000) | **largest** (truncates all 1,400 harder) | low | yes | no |

- **(b) chunk + mean-pool** is the only zero-loss option, but it is disproportionate
  for a retrieval substrate: mean-pooling dilutes the signal, and it makes a chunked
  doc's vector **not directly comparable** to the ~90% of docs embedded whole — an
  asymmetry that silently biases every cosine score the long tail participates in. It
  also moves `embeddings.stamp` (full re-embed) and adds real code + test surface.
  Rejected for MVP; revisit only if the long tail proves to matter for dedup recall.
- **(d) lower the cap** trades the 400 (11 docs) for *worse* truncation on 1,400 docs.
  Wrong direction — it degrades the many to rescue the few.
- **(c) pure best-effort** is the *current* behavior: the runner already isolates the
  400 and moves on. Its only defect is that it's an *accident*, not a decision, and it
  leaves the ~11 with **zero** document vector.

## Decision: (a) progressive backoff + (c) section-vector reliance

**Keep `max_chars=10000`** (the 1,389 truncated-but-not-400 docs keep their fuller
vector) **and add a progressive-backoff safety net so no JD ever ends with a zero
document vector**, while **consciously accepting** that for the over-window tail the
document vector is best-effort and the *section* vectors carry the role signal.

Concretely:

1. **`embeddings.yaml` gains one knob** — `max_chars_fallback: [8000, 6000, 4000]`
   (registered as a new `open` entry, **HR-193**, per the standing rule: any
   non-trivial default is YAML-configurable + registered in the same PR). An empty
   list restores today's exact behavior (skip on 400), so the knob's alternative is
   real, not decorative.
2. **The runner's existing one-text-at-a-time 400 branch** ([runner.py:262-270](../../core/src/jd_bank/embeddings/runner.py#L262-L270))
   gains the ladder: on a single-text 400, re-cut that text on its **whole-unit
   (`\n`) boundaries** down to each successive fallback cap and embed the first rung
   that succeeds. Re-cutting on `\n` preserves the whole-unit-boundary invariant for
   free, because `_join_truncated` already joins units with `\n` — no need to carry the
   source `SFUJobDescription` into the memo. Only the ~11 densest docs ever enter this
   path; the common case is untouched.
3. **Idempotency preserved, and one honest imprecision.** The backed-off vector is
   memoised under the text's **original** (`max_chars`) `text_sha256`, and the node is
   written with that sha and `truncated=True`. So on a re-run at the same stamp the
   serializer reproduces the `max_chars` text, its sha matches the node, and the doc
   is **skipped** — the unchanged-corpus idempotency guarantee
   (`documents_embedded == embed_calls == 0`) is fully intact. `bad_requests` now
   counts only texts that 400 *even at the smallest fallback rung* (expected: 0), and a
   new `EmbedRunResult.texts_backed_off` counts the rescued ones so the summary
   artifact makes the behavior visible rather than hiding it.

### The one imprecision we accept, named explicitly

Keying on the `max_chars` sha is what keeps skip-first sound (that text is the
deterministic *identity* of the doc: same `max_chars` text + same ladder + same server
→ same backed-off vector). The price is that for the ~11 backed-off nodes the stored
`text_sha256` is the sha of the text we *intended* to embed, not of the shorter bytes
we *actually* embedded — `truncated=True` flags the node as partial, but a strict
"does `sha(embedded_text) == text_sha256`?" audit would not hold for these few nodes.
The only other cost is that on a **full** re-embed (a stamp change re-embeds
everything anyway) each of the ~11 pays one extra failed round-trip before its ladder
succeeds. Both are bounded and deliberate; persisting the backoff outcome to make the
sha exact is not worth a schema change for ~11 nodes. Recorded here so the next reader
does not mistake either for a bug.

## What runs when `aria-gb10-2` frees (the one command)

The change is fully unit-testable **offline** — the embed client is injectable, so a
fake that 400s on over-N-char text drives the ladder under `make gates` with no Ollama.
Only the final corpus re-embed + count check needs the host:

```
# 1. offline: unit + mutation tests (no Ollama) — part of the staged PR
make gates

# 2. host free: re-embed the whole archive on the new code
make embed            # opt-in, local-only live path (ADR-003)

# 3. verify the decision held, against the archive (never from memory)
#    expect: bad_requests -> 0, documents_backed_off ~ 11,
#    documents_embedded unchanged for the other ~14k, docs/embeddings/summary.json updated
```

**Every number in step 3 must be re-measured against the archive, not asserted** —
this is the rule that has already caught a census, two coders, a reviewer and the
orchestrator (CLAUDE.md `docs/baseline/README.md`).

## Register impact

- **HR-126** — stays `open`; `why_it_matters` / `impact_if_changed` updated to record
  that (a)+(c) is the chosen direction and *why* (b)/(d) were rejected. Still no HR
  ratification — SFU HR rules on this alongside the rest of the embeddings decisions.
- **HR-193** (new, `open`, `our_invention`) — `embeddings.max_chars_fallback`, the
  backoff ladder. Unhashed (same file as HR-124…130 — cannot move a JD's score).
