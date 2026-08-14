# Runbook — backup and restore

**Phase 6 deliverable.** Every command here was executed against the live stack on
2026-08-13 and the numbers quoted are what it printed. Where a step says a thing is safe,
it is safe because it was tried, not because it reads that way.

---

## 0. What actually has to be backed up

**Postgres, and only Postgres.**

`docker compose` runs three stateful services. Their contents are not equally precious:

| Store | Holds | Backed up? |
|---|---|---|
| **Postgres** | Every JD, cluster, canonical version, review action, user, role, and the hash-chained `audit_log` | **YES — this is the ledger** |
| **Neo4j** | Vectors only: `JDDocument` 14,404 · `JDSection` 36,174 · `JDRole` 1,797 | **No — rebuild it** (see [reindex.md](reindex.md)) |
| **Redis** | The arq queue | No — transient by design |

Neo4j is a **derived index**, not a source of truth: `make embed` rebuilds the document
and section vectors from `parsed_jds`, and `make embed-roles` rebuilds the role vectors
from `canonical_jds`. Both live in Postgres. Backing the vectors up would mean keeping a
second copy of something you can regenerate exactly.

> **⚠ The one thing that would change this.** Neo4j *also* hosts the harness agent-memory
> graph (`Agent` / `Artifact` / `Task` / `Subtask`), which is **not** derivable from
> Postgres. Measured on this deployment: **all four labels have 0 nodes**, so nothing is
> at risk today. **If agent memory is ever populated, this section is wrong and Neo4j
> joins the backup set.** Check before trusting it:
>
> ```bash
> docker exec jd-bank-neo4j-1 cypher-shell -u neo4j -p "$NEO4J_PASSWORD" --format plain \
>   "MATCH (n) WHERE n:Agent OR n:Artifact OR n:Task OR n:Subtask RETURN count(n);"
> ```

---

## 1. Take a backup

Run against the live container. Read-only; safe at any time, no downtime.

```bash
docker exec jd-bank-postgres-1 pg_dump -U app -d harness -Fc -f /tmp/harness.dump
docker cp jd-bank-postgres-1:/tmp/harness.dump ./harness-$(date +%Y%m%d-%H%M).dump
docker exec jd-bank-postgres-1 rm -f /tmp/harness.dump
```

`-Fc` (custom format) is **not optional** — see §3, where the ordering it guarantees is
the reason a restore does not destroy the audit chain.

Measured size: **59,106,543 bytes (~56 MiB)** for 14,565 files / 1,804 canonical JDs.

### Record the fingerprint at backup time

Take this **now**, with the backup, and keep it beside the dump. It is what makes a
restore verifiable rather than merely uneventful:

```bash
docker exec -i jd-bank-postgres-1 psql -U app -d harness -t -c "
SELECT (SELECT count(*) FROM canonical_jds)  AS canonical_jds,
       (SELECT count(*) FROM user_roles)     AS user_roles,
       (SELECT count(*) FROM audit_log WHERE row_hash IS NOT NULL) AS chained_rows,
       (SELECT encode(digest(string_agg(encode(row_hash,'hex'),'|'
          ORDER BY created_at, id),'sha256'),'hex')
        FROM audit_log WHERE row_hash IS NOT NULL) AS audit_fingerprint;"
```

Live values on 2026-08-13:

```
canonical_jds | user_roles | chained_rows | audit_fingerprint
         1804 |         12 |         1810 | d8899dc82655ab22822eb286716e78200636438c0e7b69711857d26008b7bb6b
```

`audit_log` holds 4,411 rows of which **1,810 are chained**. The rest predate migration
`0005` and carry `NULL` hashes by design — they sit outside the chain, which starts fresh
at the first insert after that migration. **A restore that reports fewer than 1,810
chained rows has lost audit history.**

---

## 2. Restore — the blessed path

**Restore a full custom-format dump into an EMPTY database.** This is the only path that
was verified end to end, and it is the one to use.

```bash
# 1. A clean, empty database. NEVER restore over a live one.
docker exec jd-bank-postgres-1 psql -U app -d postgres -c "CREATE DATABASE harness_restored;"

# 2. Restore.
docker cp ./harness-YYYYMMDD-HHMM.dump jd-bank-postgres-1:/tmp/restore.dump
docker exec jd-bank-postgres-1 pg_restore -U app -d harness_restored --no-owner /tmp/restore.dump

# 3. VERIFY (§4) before pointing anything at it.
```

**Verified result:** the audit chain came back **byte-identical** — 1,810 chained rows and
the same `d8899dc8…` fingerprint, and `audit_chain_tail` matched at
`8d22471b5be0ea156ce163f5dff31fcecb74851ddd7c77fbc060aaef093304bd`.

### Why it survives — the mechanism, because it is load-bearing

`audit_log` is hash-chained by a **`BEFORE INSERT` trigger** (migration `0005`), which
overwrites `NEW.prev_hash` and `NEW.row_hash` on *every* insert, unconditionally. Restoring
rows into a table whose trigger is live would therefore **re-chain them** — computing new
hashes over restored data and silently replacing the tamper-evidence.

A full `pg_restore` is safe because it loads **table data before it creates triggers**. The
trigger does not exist yet while the rows land. That ordering is a property of the custom
format dump, which is why §1 insists on `-Fc`.

---

## 3. 🔴 The trap — and it reports success

**Do NOT restore with `--data-only` into an already-migrated database.** Measured, on the
real dump:

```bash
pg_restore -U app -d harness_dataonly --schema-only --no-owner /tmp/harness.dump
pg_restore -U app -d harness_dataonly --data-only  --no-owner /tmp/harness.dump
```

| | live | after `--data-only` |
|---|---|---|
| `canonical_jds` | 1,804 | **0** |
| `user_roles` | 12 | **0** |
| chained `audit_log` rows | 1,810 | **0** |
| `users` | 6 | 6 |
| **`pg_restore` exit code** | — | **0** |

The restore printed `warning: errors ignored on restore: 7` and **exited 0**. The resulting
database starts, accepts logins, has every user — and contains **not one job description**.
An operator who checked the exit code and logged in would conclude the restore worked.

> **This is the same trap as reading a pipeline's exit status instead of its output** — the
> lesson HANDOFF already records for `make gates | tail`. A zero exit is not evidence.
> **Read the output, then verify the data.**

The cause is that `--data-only` leaves constraint and chain triggers live, so foreign keys
fire mid-load and rows are rejected in dependency order.

**If you genuinely must go data-only** (restoring into a schema you have migrated
yourself), `--disable-triggers` is required. Verified correct — 1,804 canonical JDs, 12
roles, 1,810 chained rows, identical `d8899dc8…` fingerprint:

```bash
pg_restore -U app -d harness_dt --data-only --disable-triggers --no-owner /tmp/harness.dump
```

`--disable-triggers` needs superuser. The compose `app` role is one (`rolsuper = t`), so
this works as shipped — **and that is itself worth noting when the production posture
tightens the app role**, because this path will stop working then.

---

## 4. Verify the restore — do not skip this

Run the §1 fingerprint query against the restored database and compare **all four values**
to what you recorded at backup time.

```bash
docker exec -i jd-bank-postgres-1 psql -U app -d harness_restored -t -c "
SELECT (SELECT count(*) FROM canonical_jds)  AS canonical_jds,
       (SELECT count(*) FROM user_roles)     AS user_roles,
       (SELECT count(*) FROM audit_log WHERE row_hash IS NOT NULL) AS chained_rows,
       (SELECT encode(digest(string_agg(encode(row_hash,'hex'),'|'
          ORDER BY created_at, id),'sha256'),'hex')
        FROM audit_log WHERE row_hash IS NOT NULL) AS audit_fingerprint;"
```

- **All four match** → the restore is faithful, audit history included.
- **`audit_fingerprint` differs but counts match** → the chain was **re-hashed** during
  restore. The data may be intact but its tamper-evidence no longer attests to the
  original. Treat as a failed restore.
- **Counts are 0 or low** → you hit §3. Start again with the blessed path.

`user_roles = 0` deserves its own line: with no roles, **nobody can review or approve
anything**, and `default_new_user_role` is `author`. The app will look healthy and be
unable to publish.

The application's own verifier (`src.api.services.audit.verify_audit_chain`) recomputes
every chained row and checks the links form one unbroken chain. It is the stronger check;
the SQL above is the one you can run without the app.

---

## 5. After a restore — rebuild the vectors

The restored Postgres has no Neo4j to go with it. Until the vectors are rebuilt, Builder
search and the near-duplicate authoring guard return **nothing** — quietly, because
`embed_stamp` parity filtering treats absent vectors as "not comparable" rather than as an
error (see [reindex.md](reindex.md), and `_comparable` in `composer/search.py`).

Follow **[reindex.md](reindex.md)**.

---

## 6. What is NOT covered here

- **Point-in-time recovery / WAL archiving.** This is a nightly-dump runbook. PITR is a
  deployment decision nobody in this repo has made.
- **Backup scheduling, retention and off-host storage.** A dump on the same disk as the
  database is not a backup. Where these go is an ops decision, and it is open.
- **Encryption of the dump at rest.** It contains every JD and every user identity.
- **The archive files themselves** (`C:\repos\hris\fixtures\SFU_JDs`) — read-only source
  data, backed up wherever the archive lives, not by this repo.
