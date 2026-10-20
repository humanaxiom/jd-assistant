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

Tear it down with `.\teardown.ps1 -ProjectName jd-bank-verify -Volumes` (add
`-AllowForeignProject` if its containers are already gone — see the guard below).

This is how the workflow was validated, and it is the honest way to test a change to the
deploy path — the alternative is finding out on the box that matters.

---

## Running a second Bank beside the live one

For a Bank built from a different branch (e.g. a new parser version) that must leave the
live Bank, its database and its images alone. **One rule: a second Bank is a second
checkout with its own `.env`.**

```powershell
git worktree add C:\repos\JD-Assistant-v9 parser-v9          # any branch
copy deploy\parallel-bank.env.example C:\repos\JD-Assistant-v9\.env
cd C:\repos\JD-Assistant-v9
.\build.ps1                     # jd-bank-api:v9 / jd-bank-worker:v9 — :latest untouched
.\launch.ps1 -NoCas             # project jd-bank-v9, http://localhost:26800
make smoke                      # runs against jd-bank-v9's Postgres, not the live one
.\teardown.ps1 -Volumes         # discards jd-bank-v9 ONLY
```

The `.env` (git-ignored, one per checkout) carries the whole identity:

| key | example | what it isolates |
|---|---|---|
| `COMPOSE_PROJECT_NAME` | `jd-bank-v9` | containers, volumes (`jd-bank-v9_pgdata` …), network |
| `JD_IMAGE_TAG` | `v9` | `jd-bank-api:v9` / `jd-bank-worker:v9`; tool images are `<project>-<service>` already |
| `JD_API_PORT` … `JD_REDIS_PORT` | 26800 / 26432 / 26474 / 26687 / 26379 | host ports (live is 25xxx) |
| `CAS_SERVICE_BASE_URL`, `ALLOWED_SERVICE_ORIGINS` | `http://localhost:26800` | CAS returns to *this* Bank; ships `CAS_ENABLED=false` |

`docker compose` reads `.env` itself, so every `make` target acts on this checkout's
Bank. The scripts (build / launch / teardown / bundle / install) and `make up` / `down` /
`migrate` / `gates` / `gates-fast` / `smoke` resolve the same values the same way
(**shell environment → `.env` → live defaults**) and **print which project, tag and ports
they are about to act on before acting**; the guarded ones also cross-check the answer
with `docker compose config` (`make bank-target` prints it on its own). With no `.env`
nothing changes: `docker compose config` on the live checkout is identical to before.

⚠ **The producer targets are NOT guarded and do not print** — `make ingest`, `embed`,
`embed-roles`, `dedup`, `near-dup`, `dedup-role`, `cluster`, `harmonize-measure`,
`canonical-drafts`, `bank-audit`, `singletons`, `field-audit`, `baseline`. In a second
checkout **with no `.env`** they run *that checkout's code* against the **LIVE** Bank
(project `jd-bank`). Create the `.env` before the first command; `make bank-target`
says which Bank a bare `make` would hit.

`make gates` / `make smoke` need nothing extra: `gates` reaches `postgres:5432` by service
name on the project's own network, so in the second checkout it hits the second Bank.

### The guard — what the scripts refuse

`build.ps1`, `launch.ps1`, `teardown.ps1`, `deploy\bundle.ps1`, `deploy\install.ps1` and
`make up` / `down` / `migrate` refuse (with the reason) when:

1. **the project's containers were created from another checkout** — compose stamps each
   container with the directory it came from, so `teardown.ps1 -ProjectName jd-bank
   -Volumes` typed in the v9 checkout is refused while the live stack exists;
2. **a linked git worktree aims at the live project name** `jd-bank` (no `.env` of its
   own) — this covers the case where the live stack is down and only its volumes remain.
   Chosen over "path is `C:\repos\JD-Assistant` on `main`" because paths differ per box
   and the live checkout is often on a feature branch;
3. **a destructive action** (`teardown -Volumes`, `install -Force`) targets a project that
   is not this checkout's and no container proves this checkout created it;
4. **a second project is still on tag `latest`**, or the tag is in use by another
   project's containers — its build would replace images another Bank runs on.

`-AllowForeignProject` overrides, and is meant to be typed by a person who has read the
reason. Code: `deploy\BankTarget.ps1`; tests: `deploy\tests\bank-target.tests.ps1` (run by
`make deploy-check`).

**Not covered:** a second *full clone* (not a worktree) with no `.env`, while the live
stack is down — nothing on the box then says which checkout the volumes belong to. Give
every second checkout its `.env` before its first command.

---

## What the target box still needs from the network

Nothing, to serve the Bank: the app, the library, the review queue, the funnel and the
dashboards all read Postgres and Neo4j.

The **internal** network (not the internet) is needed only for inference —
`make embed`, `make embed-roles`, and the LLM jobs, which talk to Ollama on
`aria-gb10-2`. If that host is unreachable those jobs fail fast and say so; nothing else
degrades.

…**with one exception that is not about serving the Bank but about getting into it:
signing in.** 🔴 **Every origin users reach the box on must be listed in
`ALLOWED_SERVICE_ORIGINS` — scheme, host AND port, each spelling its own entry** — or CAS
returns them to the fallback and they land on a connection timeout holding a valid ticket.
It is the one setting a correct install can still get wrong, and in production the app
**refuses to start** unless every entry is https at a real hostname.

**Hand [`../docs/NETWORK-SETUP.md`](../docs/NETWORK-SETUP.md) to whoever owns the network
for the target box**: ports and bindings, required egress, DNS/TLS, reverse-proxy headers,
NAT caveats, a verification sequence and a symptom→cause table.
