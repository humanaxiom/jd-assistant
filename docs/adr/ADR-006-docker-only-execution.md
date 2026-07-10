# ADR-006: Docker-Only Execution — No Host Runtimes

**Status:** Accepted
**Date:** 2026-07-10

## Context

The v2 harness's original developer flow installed a host Python (`python -m venv`, `pip
install -r requirements*.txt`), ran `make gates` **outside** containers on the host, and used
the `pre-commit` framework (host-managed hook venvs). Only Ollama was mandated on metal.

The project owner set a hard rule for JD Bank — and, as this project is intended to become
the **golden standard for all new projects**, for the harness going forward:

> **All code must run in Docker images. No local Python or other runtime/compiler on the host.**

Two forces make this the right call:
- **Reproducibility / golden standard.** "Works on my machine" dies when the only runtime is
  the pinned image. Every developer, the ReviewLoop, and CI execute byte-identical toolchains.
- **Offline-first integrity (ADR-003).** The stack is already Dockerized; a host Python is a
  second, drifting environment that can smuggle in cloud deps or version skew. Removing it
  closes that gap.

The one intentional exception is **Ollama**, which stays on host metal for GPU/Metal access
(inherited ADR-003) — it is inference infrastructure, not project code/tooling.

## Decision

**No host language runtimes or compilers.** Git, Docker + Compose, and host Ollama are the
only host prerequisites. All Python — app, tests, gates, migrations, linters, type-checker —
executes inside containers built from `core/Dockerfile` (which already installs
`requirements-dev.txt`). Source is bind-mounted (`./core:/app`), so edits on the host reflect
in the container with no rebuild.

- **Gates run in the container.** `make gates` / `gates-fast` delegate to
  `docker compose exec api …` (ruff, black, mypy, pytest). `make` is a host task-runner only —
  it invokes Docker; it does not run project code.
- **Testing is a non-negotiable, fully-Dockerized gate — including integration.** The full
  suite (ruff · black · mypy · unit+coverage · **integration**) runs in a dedicated one-shot
  `gates` compose service (`profile: tools`) via `docker compose run --rm gates`. Integration
  tests use testcontainers, so the `gates` service mounts the Docker socket **in the compose
  file** (`/var/run/docker.sock`), which works on Linux and Docker Desktop alike, and sets
  `TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal` (sibling containers reachable via the host
  gateway) and `TESTCONTAINERS_RYUK_DISABLED=true` (the reaper is unreliable in Docker-in-Docker).
  CI runs the identical command. There is no host-Python fallback for tests — ever.
- **Pre-commit** is a thin `.git/hooks/pre-commit` script that calls `make gates-fast` (Docker)
  — not the host `pre-commit` framework. The branch-name check is pure bash (no runtime).
- **Editor auto-fix hook** (`.claude/settings.json` PostToolUse) runs ruff via
  `docker compose exec` with a graceful fallthrough when the stack is down.

## Consequences

- **Prerequisites shrink** to Git + Docker + host Ollama. No venv, no `pip install`, no host
  `pre-commit`. Onboarding is `docker compose up -d` + `make migrate`.
- **`make gates` is self-contained** — it runs in the one-shot `gates` service and does not
  require `make up` first (testcontainers spins its own Postgres/Neo4j; unit/static need
  nothing). `gates-fast` is the quick edit-loop subset (static + unit, no integration).
- **The `gates` service owns the testcontainers config** (socket mount, host override, ryuk
  disabled) so it is uniform across every developer and CI — not a per-machine setup step.
  Requirement: the developer's Docker daemon is reachable (true by definition when Docker runs).
- **Deliberate drift from upstream harness.** `Makefile`, `.claude/settings.json`, and (later)
  `.pre-commit`/CI now carry project Docker-only overrides vs `C:\repos\agent-harnesses-v2`.
  Per ADR-004 these are recorded, deliberate deltas — and are **candidates to upstream** into
  the harness so the golden standard is Docker-only by default.
- **CI** must run the same in-container gates (no host Python step) so local == CI.

## Alternatives Considered

- **Keep host Python for gates, Docker for the app** (the original harness flow): simplest, but
  reintroduces the drifting second environment and "works on my machine"; rejected by the rule.
- **Devcontainer only:** good for editors, but doesn't force CI/ReviewLoop parity; the
  container-exec gate path covers all three. Complementary, not a replacement.
