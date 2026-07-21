# Egress audit — JD content over the network (Phase 4.6a)

**Invariant:** CLAUDE.md non-negotiable #5 — *self-hosted inference only; no third-party
or cloud LLM API, ever; no vendor egress of JD content.*

**Ratified boundary (do not re-litigate):** "local" = **not cloud / not third-party**. JD
text crossing the **private network** to an **internal host we control** (`aria-gb10-2`,
ADR-003) is **ALLOWED**. A public / third-party host (`api.openai.com`,
`api.anthropic.com`, any public FQDN or routable public IP) is a **violation**.

Before Phase 4.6a this boundary was enforced only by a human reading code. It is now a
**build failure**: the two JD-content network sinks call
`assert_inference_host_allowed(...)` (`core/src/jd_bank/security/egress.py`) on the
real-construction path, **before** any `AsyncOpenAI` client exists and before any content
could be sent. The guard checks the `base_url` host against a **host allowlist**
(`settings.allowed_inference_hosts`, env-overridable via `ALLOWED_INFERENCE_HOSTS`);
loopback / private (RFC-1918) IP literals are also allowed (a future dev-box Ollama is a
permitted internal case). It raises `DisallowedInferenceHostError` naming the offending
host and the allowlist.

## Every place JD / archive content can leave the process over the network

| Sink | File:line | Points at | Carries | Guarded? |
|---|---|---|---|---|
| Rewrite + quality-audit LLM | `core/src/jd_bank/llm/client.py:94` (`ChatClient.__init__` builds `AsyncOpenAI(base_url=settings.ollama_base_url, ...)`) | `settings.ollama_base_url` (default `http://aria-gb10-2:11434/v1`) | **SFU JD archive content** (JD text sent for rewrite / quality audit) | **YES** — `assert_inference_host_allowed(...)` at line 90, before the client is built |
| Embeddings | `core/src/jd_bank/embeddings/client.py:70` (`EmbedClient.__init__` builds `AsyncOpenAI(base_url=settings.ollama_base_url, ...)`) | `settings.ollama_base_url` (default `http://aria-gb10-2:11434/v1`) | **SFU JD archive content** (parsed JD section text sent to embed) | **YES** — `assert_inference_host_allowed(...)` at line 66, before the client is built |

These are the **only two** sinks that transmit SFU JD archive content. Both build their
client from the same `settings.ollama_base_url`; both now refuse to build against a host
not on the allowlist.

**Threat model / known limitation (deliberate):** the guard checks the `base_url` **host
string**, not the DNS-resolved IP. A **public** FQDN is rejected regardless of what it
resolves to (safe direction). The residual gap is an *allowlisted name* repointed via DNS
to a public IP — this is out of scope: Phase 4.6a targets **misconfiguration** (someone
sets `OLLAMA_BASE_URL` to a cloud endpoint), not a malicious insider who also controls
DNS. A scheme-less `base_url` is rejected (fail-closed); the shipped `ollama_base_url`
always carries `http://`.

## Other network users in this repo — confirmed NOT SFU JD archive content

The repo vendors the harness, which has its own Ollama users. Each was inspected; none
carries SFU JD archive content:

| User | File:line | Carries |
|---|---|---|
| Harness agent-memory embeddings | `core/src/memory/graph.py:29` (`GraphMemory` embeds artifacts into Neo4j `artifact_embeddings`) | **HARNESS lineage/artifact data** — task descriptions, code artifacts, "have we solved this before?" retrieval. Not JD archive content. |
| Coder / pipeline agent models | `core/src/agents/base.py:53`, `core/src/agents/coder.py:33` (agent LLM clients) | **HARNESS agent data** — code, plans, reviews for the Planner→Coder→Reviewer pipeline. Not JD archive content. |

**Finding:** no path was found by which SFU JD archive content reaches the harness
agent-memory or coder-agent clients. They operate on the harness's own lineage/code data.
They point at the same `ollama_base_url` (also internal by default) but were **left
unguarded in this phase by design** — Phase 4.6a scopes the build-enforced guard to the
**JD-content** sinks, which are the NN #5 subject. (If a future change ever routes JD
archive text through `GraphMemory` or an agent client, that path MUST call the guard too;
flag it in review.)

## Why the allowlist lives in `settings.py`, not the rulebook register

The allowlist is **OPS/SECURITY config**, not a JD-scoring rule: it changes **no JD's
score**. The HR decision register (`docs/decisions/HR-DECISION-REGISTER.md`) governs
**rulebook scoring defaults** that HR ratifies; a network egress allowlist is not one of
those. It therefore lives in `core/src/settings.py` (env-overridable), **not** in
`jd_core/rules/` and **not** in `decision_register.yaml`. This is a deliberate placement
decision, recorded here.

## What is pinned by tests

`core/tests/unit/test_egress_guard.py`:
- Guard both directions: `aria-gb10-2` passes; `api.openai.com`, `api.anthropic.com`, a
  Google FQDN, and an arbitrary public host raise `DisallowedInferenceHostError`.
- Loopback / docker-host / RFC-1918 private IP literals pass; a public IP literal
  (`8.8.8.8`) and a host-less URL are rejected; matching is case-insensitive.
- Default allowlist comes from settings and admits the shipped `ollama_base_url`.
- **Wired-in pins (load-bearing):** constructing the REAL `ChatClient()` / `EmbedClient()`
  with `ollama_base_url` overridden to a cloud host RAISES. Verified to go RED when the
  guard call is removed from the client, then restored.
- Default settings build a real content client without raising; an injected test-fake
  client is not re-guarded.
