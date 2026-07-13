# ADR-003: Offline Inference — Ollama on Metal, OpenAI-Compatible Client

**Status:** Accepted · **Amended 2026-07-13** (topology corrected — see the amendment at the end;
the *decision* is unchanged and is not re-opened)
**Date:** 2026-07-09

## Context

We build offline-first AI applications. Inference must not depend on cloud APIs, and GPU access is best from the host, not inside containers.

## Decision

- **Ollama runs on bare metal** (direct GPU/Metal access); everything else in Docker
- Containers reach it via `host.docker.internal:11434` (compose `extra_hosts: host-gateway` for Linux parity)
- All agent code uses the **OpenAI-compatible `/v1` endpoint** through `AsyncOpenAI(base_url=...)` — swapping to vLLM later is a config change, not a code change
- **CI never calls a model endpoint**: unit tests mock the client; integration tests mock only the embedding call and use real Postgres/Neo4j/Redis
- Models: `qwen2.5-coder:14b` (coding), `nomic-embed-text` (768-dim embeddings matching the Neo4j vector index)

## Consequences

- Fully offline runtime; zero cloud spend or data egress
- CI is deterministic and fast (no model variance in gates)
- Model quality gates (evals) must run on a self-hosted runner with GPU — out of scope of the default pipeline, tracked separately

## Alternatives Considered

- **Ollama in Docker**: GPU passthrough friction, worse Metal support on macOS; rejected
- **Native Ollama Python client**: locks us in; the OpenAI-compatible surface keeps vLLM migration trivial (already under evaluation); rejected

---

## Amendment — 2026-07-13 (JD Bank): the real topology, and what it does and does not unblock

The decision above stands. **One factual claim in it was wrong for this project**, and it had been
deferring work on the strength of an unchecked assumption — so it is corrected here rather than
carried.

### What was wrong

> ~~"Containers reach it via `host.docker.internal:11434`"~~

**Ollama does not run on the dev box.** It runs on metal on **`aria-gb10-2`**, a separate trusted
internal host. `docker-compose.yml` said `host.docker.internal` until this was checked.

`OLLAMA_BASE_URL` is now `${OLLAMA_BASE_URL:-http://aria-gb10-2:11434/v1}` — overridable, so the
hostname is configuration and not a fact welded into the repo.

### Verified, not assumed (from *inside* the `gates` container)

- `aria-gb10-2:11434` is reachable.
- **`nomic-embed-text` is present and returns 768-dim vectors** — matching the Neo4j vector index
  mandated by ADR-002. Checked, because "the model is the right dimensionality" is exactly the kind
  of claim this project has been burned by assuming.

### What that unblocks — and what it emphatically does NOT

This corrects a false constraint, but **only half of it was false.** Both halves matter:

| | Can it reach `aria-gb10-2`? |
|---|---|
| **Local `make gates`** (dev box, Docker) | ✅ **YES** — verified. |
| **CI** (`.github/workflows`, `runs-on: ubuntu-latest`) | ❌ **NO, and never will.** GitHub-hosted cloud runners cannot route to an internal host. |

So the statement in HANDOFF — *"the golden test needs host Ollama, which the self-contained `gates`
container cannot reach"* — was **false locally and true in CI**, for a different reason than it gave.

**Therefore the rule in this ADR is unchanged and is now enforced by network topology, not merely by
policy: `make gates` MUST NOT depend on a live model endpoint.** A test that calls Ollama passes on a
developer's machine and turns CI red. That is a worse failure than not having the test, because it is
intermittent and it trains people to ignore CI.

**The pattern for Phase 3.2 onward:**
- **Unit tests** mock the client (as this ADR already required).
- **Integration tests** mock the embedding call; real Postgres/Neo4j/Redis via testcontainers.
- **A live golden test against real Ollama is opt-in and local-only** — its own make target or a
  pytest marker that *skips* when the endpoint is unreachable. It must never be in the `make gates`
  path. Skipping-when-absent is not a loophole here; it is the only shape that is honest in both
  environments.

### Data boundary — this changes what "local-first" means

CLAUDE.md non-negotiable #5 used to read *"JD content never leaves this machine."* **That is now
false in the letter**: from Phase 3.2, JD text crosses a private network to `aria-gb10-2` to be
embedded.

The invariant that actually matters is intact and is restated in CLAUDE.md: **all inference runs on
infrastructure we control; no third-party or cloud LLM API; no vendor egress of JD content.**

⚠️ **The trust assumption is explicit: `aria-gb10-2` is a trusted internal host on a private
segment.** These are SFU HR records, so **FIPPA applies**. If the inference host ever moves off a
trusted segment — or if the link stops being private — this is a **compliance decision to be
re-taken, not a config value to be edited.** Transport is currently plain HTTP on the internal
network; TLS is a question the moment that stops being true.
