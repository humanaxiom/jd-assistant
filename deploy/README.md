# Deploying JD Bank to a fresh box, offline

## 🔴 DIRECTIVE #1 — why this directory exists

**Set by the project owner, 2026-08-28:**

> **Every step must leave the code TESTED and every feature DEPLOYABLE THROUGH THE
> SCRIPTS, by a person, with no assistant in the loop.**

Done is not "it works on the dev box". Done is **tested** (`make gates` green, failing
test first), **deployable** (through the two scripts below), **discoverable** (reachable
in the UI — a feature nothing links to has not been delivered), and **green on
`make deploy-check`**, which CI enforces as *"Gate: deployable offline"*.

The question to ask at the end of every task: **could the owner deploy and see this,
tomorrow, without me?**

Full statement in [`../CLAUDE.md`](../CLAUDE.md).

---

**Goal:** after any change, this repo can be put on a box that has Docker and **no
internet**, and come up as a working JD Bank with the archive already in it.

Verified end to end on 2026-08-28 by rehearsing a full install beside the live stack
(separate volumes, separate ports): every row count matched the bundle, both Neo4j vector
labels matched, and the funnel rendered 14,565 → 14,522 → 2,493 from the restored
database.

---

## The two commands

| where | command | needs internet |
|---|---|---|
| **connected box** | `make bundle`, or `.\build.ps1 -Bundle` | yes — it builds images and pulls base images |
| **target box** | `.\deploy\install.ps1 -BundleDir <bundle>` | **no** |

That is the whole workflow. `install.ps1` passes `--no-build --pull never` to every
compose call, so a missing image **fails loudly** instead of quietly reaching for Docker
Hub — an install that silently pulls has proved nothing about the offline box.

---

## What is in a bundle (~1.4 GB)

| file | size | why a fresh box cannot do without it |
|---|---:|---|
| `images.tar` | 652 MB | No Docker Hub for postgres/neo4j/redis, and no PyPI to `pip install` the api image's dependencies. |
| `postgres.dump` | 98 MB | The whole relational Bank — documents, parses, roles, edges, audit. |
| `neo4j.dump` | 640 MB | The vector store. Neo4j is a *derived* index and `make embed` could rebuild it, but that costs GPU hours on `aria-gb10-2`. Shipping it makes the box useful the moment it boots. |
| `MANIFEST.txt` | — | Image ids, row counts and SHA-256 of each artifact, so the target can prove it installed what was cut. |

**Not in the bundle, on purpose:**

- **The repo.** `api` and `worker` bind-mount `./core`, so the *source* is what actually
  runs. Copy the repo to the target alongside the bundle.
- **Ollama.** It runs on metal on `aria-gb10-2` (ADR-003, non-negotiable #5) and is
  reached over the internal network. Nothing here bundles a model.

---

## 🔴 When you must re-cut the bundle — and when you must not

Because the app runs from the bind-mounted `./core`, **a code change does not need a new
bundle.** Copy the repo and restart.

Re-cut only when the *image* changes:

| change | re-cut? |
|---|---|
| Python code, templates, rules YAML | **no** — copy the repo |
| `core/requirements*.txt`, `core/Dockerfile` | **yes** — `make bundle` |
| you want the target to carry newer data | **yes**, or just re-cut the data: `-SkipImages` |

`bundle.ps1` takes `-SkipImages` / `-SkipData` so you can re-cut only the half that moved.

---

## Keeping it deployable: `make deploy-check`

`make bundle` takes minutes and a gigabyte, so nobody runs it per change. `make
deploy-check` is the cheap standing check — it verifies the properties that silently make
a bundle *wrong*:

- **Image names do not depend on the compose project name.** This is the one that already
  bit. Compose names a built image `<project>-<service>` by default; the bundle ships
  images *by name*, so a target installing under a different project name would look for
  an image the tarball does not contain. Caught on 2026-08-28 by rehearsing an install
  under `-ProjectName jd-bank-verify`, fixed with explicit `image:` keys on `api` and
  `worker`. The check asks compose for its image list under two project names and
  requires them to be identical.
- The deploy kit is present.
- `core/.dockerignore` exists — and does **not** exclude `tests/` or `alembic/`, which
  must reach the image because `make gates` runs the suite inside it (ADR-006) and
  migrations run from the api container.

Run it after touching `docker-compose.yml`, the `Dockerfile`, or anything in `deploy/`.

---

## The restore trap this deliberately avoids

`pg_restore --data-only` into an already-migrated database **silently destroys the Bank
and exits 0** — measured on a real dump, recorded in `docs/archive/`.

So the bundle carries a **full** `-Fc` dump, and `install.ps1`:

1. counts the tables in the target database;
2. **refuses to run** if there are any, unless you pass `-Force`;
3. restores into an empty database, which brings schema, data and `alembic_version`
   together — so the box lands at head without running a migration.

It never runs `--data-only`, and it never runs `alembic upgrade` before a restore.

---

## Verification is part of the install

The install is not finished when the containers are up; it is finished when the **data**
is provably there. A stack that boots against an empty database looks identical to a
restored one until you ask. So `install.ps1` ends by comparing live row counts against
`MANIFEST.txt` and counting the Neo4j vector nodes, and **exits non-zero** if anything
disagrees.

---

## Rehearsing an install without risking the live stack

Install under a different project name and different ports. Different name → different
volumes and containers, so nothing existing is touched:

```powershell
$env:JD_API_PORT='25900'; $env:JD_PG_PORT='25532'
$env:JD_NEO4J_HTTP_PORT='25574'; $env:JD_NEO4J_BOLT_PORT='25587'; $env:JD_REDIS_PORT='25479'
.\deploy\install.ps1 -BundleDir .\dist\jd-bank-bundle -ProjectName jd-bank-verify -NoCas
```

Tear it down with `docker compose --project-name jd-bank-verify down -v`.

This is how the workflow was validated, and it is the honest way to test a change to the
deploy path — the alternative is finding out on the box that matters.

---

## What the target box still needs from the network

Nothing, to serve the Bank: the app, the library, the review queue, the funnel and the
dashboards all read Postgres and Neo4j.

The **internal** network (not the internet) is needed only for inference —
`make embed`, `make embed-roles`, and the LLM jobs, which talk to Ollama on
`aria-gb10-2`. If that host is unreachable those jobs fail fast and say so; nothing else
degrades.
