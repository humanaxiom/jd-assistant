# Runbook — reindex the vector store

**Phase 6 deliverable.** Every command here was executed against the live stack on
2026-08-13 and the numbers quoted are what it printed.

---

## 0. What a reindex is, and when you need one

Neo4j holds **derived** data — vectors computed from rows in Postgres. Rebuilding it is
always safe in the sense that nothing is lost: the inputs are the ledger.

| Index | Nodes (live) | Rebuilt by | Reads from |
|---|---|---|---|
| `jd_document_embeddings` | `JDDocument` **14,404** | `make embed` | `parsed_jds` |
| `jd_section_embeddings` | `JDSection` **36,174** | `make embed` | `parsed_jds` |
| `jd_role_embeddings` | `JDRole` **1,797** | `make embed-roles` | `canonical_jds` |

Reindex when:

1. **After a restore** — the restored Postgres has no vectors to go with it.
2. **After an embedding-configuration change** — `embed_stamp` moves and every stored
   vector becomes incomparable to new queries (see §3).
3. **After a bulk re-ingest or re-parse** — new `parsed_jds` rows have no vectors.
4. **After `make canonical-drafts` or a batch of approvals** — new roles, so
   `make embed-roles`.

**Requires a reachable Ollama** on `aria-gb10-2` (`OLLAMA_BASE_URL`, ADR-003). Postgres and
Neo4j must be up. Unlike `make ingest`, this reads the database, not the archive.

---

## 1. Rebuild

```bash
make embed          # documents + sections, from parsed_jds
make embed-roles    # harmonized roles, from canonical_jds
```

Both write a summary you should read rather than trusting the exit code:

- `docs/embeddings/summary.json`
- `docs/embeddings/roles-summary.json`

> **⚠ Both summaries are COMMITTED FILES, and a partial run overwrites them.** Verified the
> hard way while writing this runbook: `make embed EMBED_ARGS="--limit 50"` rewrote
> `summary.json` from `documents_seen: 14522` to `documents_seen: 50`. **After any
> `--limit` run, `git checkout -- docs/embeddings/summary.json`** — otherwise the repo's
> record of the last full pass silently becomes a record of your 50-document spot check.

---

## 2. Re-running is free — the resume behaviour, measured

Both runners are **skip-first**: a node is re-embedded only when its identity key
`(text_sha256, model, embed_stamp)` differs from what is stored. An unchanged corpus
re-run makes **zero** inference calls.

Measured on the live index:

```
$ make embed EMBED_ARGS="--limit 50"
documents: 50 seen, 0 embedded, 49 unchanged, 1 empty (skipped, never a zero vector)
sections: 0 embedded, 78 unchanged, 72 skipped (< min_section_chars)
nodes pruned (no longer planned): 0
embed calls: 0  reused-by-memo: 0  bad_requests: 0  backed_off: 0
model=nomic-embed-text dimensions=768 embed_stamp=jd_rules_sfu_v4+b760ce00210a
```

**`embed calls: 0`.** So an interrupted reindex is resumed by simply running it again, and
running it "just in case" costs nothing but the scan. There is no separate resume flag and
none is needed.

An **empty** document is skipped, never written as a zero vector — a zero vector is
equidistant from everything and would surface as a spurious neighbour.

---

## 3. ⚠ `embed_stamp` — the difference between a free re-run and re-embedding the archive

Every vector node carries `embed_stamp`, a digest of the **vector-affecting** contents of
`embeddings.yaml`. It is the third component of the skip-first key, and it is read back at
query time: `_comparable` in `composer/search.py` drops any hit whose stamp is not the one
now in force, because a cosine between vectors from two different configurations is not
worse, it is **meaningless**.

Live value, on every one of the 14,404 documents and 1,797 roles:

```
jd_rules_sfu_v4+b760ce00210a
```

**Change a vector-affecting key — `model`, `max_chars`, `include_title_in_document` — and
the stamp moves, every stored vector becomes stale, and the next run re-embeds the whole
corpus.** Budget for that: it is ~14.4k documents plus ~36k sections against the GPU, not a
maintenance window you take by surprise.

**Not every key moves it.** `_NON_VECTOR_EMBEDDING_FIELDS` excludes the ones that provably
cannot change a vector (the interactive wait budgets added in #97). That exclusion is
*declared*, and a guard test requires every knob to be either in the stamp or explicitly
excluded — so a stamp change is always an argued decision, never an omission. **A stamp
that cries wolf trains people to ignore it.**

### Check parity before blaming the index

If search returns fewer results than expected, compare the stamps before re-embedding
anything:

```bash
# what the rulebook now demands
docker exec jd-bank-api-1 python -c \
  "from src.jd_core.rules import get_rules; print(get_rules().embeddings.stamp)"

# what is actually stored
docker exec jd-bank-neo4j-1 cypher-shell -u neo4j -p "$NEO4J_PASSWORD" --format plain \
  "MATCH (d:JDDocument) RETURN coalesce(d.embed_stamp,'<null>') AS stamp, count(*) ORDER BY 2 DESC;"
```

A mismatch means a partial or stale index; the shortfall is also logged with counts by
`_comparable` at query time, with the instruction that fixes it.

---

## 4. Verify the rebuild

```bash
docker exec jd-bank-neo4j-1 cypher-shell -u neo4j -p "$NEO4J_PASSWORD" --format plain \
  "MATCH (d:JDDocument) RETURN count(d);
   MATCH (s:JDSection) RETURN count(s);
   MATCH (r:JDRole)    RETURN count(r);"
```

Expected against the live archive: **14,404 / 36,174 / 1,797**.

**The gaps are expected and they reconcile exactly** — check the arithmetic rather than
worrying at the numbers. From the committed summaries of the last full pass:

| | seen | embedded | empty (skipped) |
|---|---|---|---|
| documents | 14,522 | **14,404** | **118** |
| roles | 1,802 | 1,797 | 5 |

`14,404 + 118 = 14,522` and `1,797 + 5 = 1,802`. An empty record is skipped, never written
as a zero vector. **A shortfall that reconciles is not a failed reindex; one that does not
is.**

(`roles_seen` 1,802 against today's 1,804 canonical JDs is also expected: the summary
records the last full pass, and two canonicals have been created since.)

Then confirm the app agrees: Builder search (`/jd-bank/ui/compose/search`) should return
hits, and the near-duplicate authoring guard should fire on a known-duplicate title.

---

## 5. Order matters after a full restore

```
make migrate        # schema + the three Neo4j cypher migrations (001 core, 002 doc vectors, 003 role vectors)
make embed          # needs parsed_jds
make embed-roles    # needs canonical_jds
```

`make migrate` first: the vector **indexes** are created by cypher migrations `002` and
`003`, and embedding into a database with no index writes nodes that nothing can query.

`embed-roles` is deliberately **not** wired into `approve` — publishing must not depend on
the GPU, and network I/O inside the review transaction would hold the
`SELECT … FOR UPDATE` lock. Run it after, like `make embed`.

---

## 6. What is NOT covered here

- **Timing of a full cold rebuild.** Not measured — every run available to measure was a
  skip-first no-op, and quoting a guess is worse than admitting the gap. Measure it the
  first time a real full rebuild is done, and put the number here.
- **Rebuilding the harness agent-memory graph** (`Agent` / `Artifact` / `Task` / `Subtask`).
  It is not derived from Postgres and cannot be rebuilt this way. All four labels are
  currently empty; see [backup-and-restore.md](backup-and-restore.md) §0.
