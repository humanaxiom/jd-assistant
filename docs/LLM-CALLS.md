# LLM calls — every call site, end to end

Engineer-facing inventory of every place the app talks to a model, traced from the
entry point (HTTP route / `make` target / arq job) to the single network call. The
HR-facing counterpart is [`AI-USAGE.md`](AI-USAGE.md); this file is the code map.

Verified against the code 2026-10-15 by grepping `core/src` for
`chat.completions.create`, `embeddings.create`, `ChatClient(`, `EmbedClient(`,
`chat_json(` and `embed_batch(`. **There are exactly four physical network call sites**;
everything else funnels into them. Re-run that grep before trusting this list.

All calls go to Ollama's OpenAI-compatible `/v1` on `aria-gb10-2`
(`settings.ollama_base_url`). No cloud API anywhere (NN #5).

---

## The four network call sites

| # | Call | File | Model from | Egress-guarded |
|---|---|---|---|---|
| **A** | `ChatClient._create` → `chat.completions.create` | [jd_bank/llm/client.py:204](../core/src/jd_bank/llm/client.py#L204) | rulebook (`rules.rewrite.*` or caller override) | ✅ |
| **B** | `EmbedClient.embed_batch` → `embeddings.create` | [jd_bank/embeddings/client.py:100](../core/src/jd_bank/embeddings/client.py#L100) | rulebook `rules.embeddings.model` | ✅ |
| **C** | `BaseAgent._complete` / `CoderAgent.iterate` → `chat.completions.create` | [agents/base.py:65](../core/src/agents/base.py#L65), [agents/coder.py:55](../core/src/agents/coder.py#L55) | `settings.agent_model` | ❌ — see finding below |
| **D** | `GraphMemory._embed` → `embeddings.create` | [memory/graph.py:134](../core/src/memory/graph.py#L134) | `settings.embed_model` | ✅ |

A and B are **JD Bank** (JD content). C and D are the **inherited harness agent
pipeline** (`core/src/agents/` — application code, unrelated to Claude Code subagents).

---

## JD Bank — chat (call site A)

| # | Use | Function | Entry point(s) | Model / mode | Prompt |
|---|---|---|---|---|---|
| 1 | **Harmonization rewrite** (4.2a) — reword the deterministic merge draft | `rewrite_merged_role` [rewrite/harmonize.py](../core/src/jd_bank/rewrite/harmonize.py) | `make canonical-drafts` → `canonical/__main__._build_clients` → `runner._run_llm_passes`; also `make rewrite-golden` | `rules.rewrite.model` (`gpt-oss:120b`), **loose JSON mode**, `reasoning_effort: null`, **`max_tokens` 4096** (HR-178) | `jd_harmonize_v4` |
| 2 | **Quality audit** (4.2b) — advisory findings on the chosen draft | `audit_quality` [quality/audit.py:101](../core/src/jd_bank/quality/audit.py#L101) | same producer run, its **own** client (`rules.quality.*`); also the audit golden | `rules.quality.model` (`gpt-oss:120b`), **schema-constrained**, `reasoning_effort: low`, **`max_tokens` 2048** (HR-187) | `jd_quality_v1` |
| 3 | **Summary assist** (5.5) — suggest a Position Summary | `suggest_summary` [composer/assist.py:120](../core/src/jd_bank/composer/assist.py#L120) | `POST /jd-bank/compose/assist/summary`; `POST /jd-bank/ui/compose/assist` (with a timeout budget) | `rules.rewrite.model`, loose JSON | `jd_compose_summary_v1` |

All three use `chat_json`: up to 3 transient retries with backoff, a 400 never retried,
then a bounded repair-nudge loop until the reply validates into the pydantic model.
Rewrite and audit are **best-effort** — a failure falls back to the merge draft / omits
the audit, never aborts the run. Every output is re-checked by the deterministic
validator (NN #3).

**Token budgets (measured 2026-10-20, rewrite pilot on the v9 Bank).** Ollama caps the
reasoning stream and the content **separately** at `max_tokens`. At the old rewrite
budget of 2048, 4 of 22 first calls stopped on `length` with an empty reply, saved only by
the single repair retry; at 4096 all six re-run clusters finished first-call, the
largest reply at 2,025 content tokens. The audit at 1024: 2 of 22 calls hit `length` and
their retries used 1,003 / 965 of the 1,024. The budgets are now 4096 (HR-178) and 2048
(HR-187), both still `open`. `suggest_summary` reuses the rewrite's budget (finding 3).

**The rewrite's input is not the raw merge draft** (2026-10-20): it is
`rewrite/fidelity.source_view` — the draft minus the old questionnaire's instructions
(HR-275/276) and SFU boilerplate sentences (HR-273/274). See
[`plans/PARSER-V9-LISTS-AND-CAPS.md`](plans/PARSER-V9-LISTS-AND-CAPS.md) §15.

## JD Bank — embeddings (call site B, `nomic-embed-text`, 768-dim)

| # | Use | Function | Entry point | Reads / writes |
|---|---|---|---|---|
| 4 | **Archive document + section embeddings** | `embeddings/runner.py` [:273](../core/src/jd_bank/embeddings/runner.py#L273) batch, [:284](../core/src/jd_bank/embeddings/runner.py#L284) per-text fallback, [:302](../core/src/jd_bank/embeddings/runner.py#L302) `max_chars` ladder | `make embed` | **writes** `(:JDDocument)` → `jd_document_embeddings` |
| 5 | **Harmonized role embeddings** | `run_role_embedding` [embeddings/roles.py:197](../core/src/jd_bank/embeddings/roles.py#L197) (+ fallbacks :211, :115) | `make embed-roles` | **writes** `(:JDRole)` → `jd_role_embeddings` |
| 6 | **Builder search** — embed the query once | `search_similar_jds` [composer/search.py:532](../core/src/jd_bank/composer/search.py#L532) | `GET /jd-bank/compose/search`; `GET /jd-bank/ui/compose/search` | **reads** both indexes (after the two Postgres `ILIKE` title passes) |
| 7 | **Near-duplicate authoring guard** — embed the draft once | `find_related_roles` [composer/duplicates.py:319](../core/src/jd_bank/composer/duplicates.py#L319) | `POST /jd-bank/ui/compose/new` (optional client; any failure → empty panel) | **reads** `jd_role_embeddings`; the draft vector is never stored |

**Not a call:** dedup Tier-2/3 and clustering only **read** stored `(:JDDocument)`
vectors (`dedup/near/runner.py::_fetch_vectors`) — they never construct an embed client.

## Harness agent pipeline (call sites C + D)

| # | Use | Function | Entry point | Model |
|---|---|---|---|---|
| 8 | Planner / Tester / Reviewer / Security / Docs agents | `BaseAgent._complete` | `POST /tasks` → arq `run_pipeline` → `AgentOrchestrator` | `settings.agent_model` (`qwen2.5-coder:14b`) |
| 9 | Coder fix loop | `CoderAgent.iterate` | same pipeline, per gate-failure iteration | `settings.agent_model`, temp 0.1 |
| 10 | Agent-memory embed (write) | `GraphMemory.record_artifact` | `BaseAgent` after each agent output; arq `embed_artifact` | `settings.embed_model` → `artifact_embeddings` |
| 11 | Agent-memory embed (query) | `GraphMemory.similar_artifacts` | Planner/Tester/Coder context retrieval; `GET /memory/similar` | `settings.embed_model` |

---

## End-to-end flow

```mermaid
flowchart LR
  %% ── Entry points ──
  subgraph ENTRY["Entry points"]
    MK_EMB["make embed"]
    MK_ROLES["make embed-roles"]
    MK_CANON["make canonical-drafts<br/>(+ rewrite / audit goldens)"]
    R_SEARCH["GET /compose/search<br/>GET /ui/compose/search"]
    R_NEW["POST /ui/compose/new"]
    R_ASSIST["POST /compose/assist/summary<br/>POST /ui/compose/assist"]
    R_TASK["POST /tasks"]
    R_MEM["GET /memory/similar"]
  end

  %% ── Batch: archive + roles ──
  subgraph BATCH["Batch producers (CLI containers)"]
    EMB_RUN["embeddings/runner.py<br/>serialize_document + max_chars ladder"]
    ROLE_RUN["embeddings/roles.py<br/>run_role_embedding"]
    PROD["canonical/runner.py<br/>deterministic merge draft"]
    REWRITE["rewrite_merged_role<br/>jd_harmonize_v4 · loose JSON · max_tokens 4096"]
    AUDIT["audit_quality<br/>jd_quality_v1 · schema-constrained · effort low · max_tokens 2048"]
    VAL1["Validator (oracle)<br/>score · grade · gates"]
  end

  %% ── Builder (API) ──
  subgraph BUILDER["JD Builder (api)"]
    SEARCH["search_similar_jds<br/>title ILIKE passes first"]
    DUP["find_related_roles<br/>advisory, never raises"]
    ASSIST["suggest_summary<br/>jd_compose_summary_v1"]
    VAL2["assess_draft (oracle)"]
  end

  %% ── Harness ──
  subgraph HARNESS["Harness agent pipeline (worker)"]
    ARQ["arq run_pipeline"]
    ORCH["AgentOrchestrator<br/>Planner→Tester→Coder loop→Reviewer→Security→Docs"]
    GMEM["GraphMemory<br/>record_artifact / similar_artifacts"]
  end

  %% ── The four network call sites ──
  subgraph CALLS["Network call sites → Ollama /v1 on aria-gb10-2"]
    A{{"A · ChatClient._create<br/>chat.completions<br/>gpt-oss:120b (rulebook)"}}
    B{{"B · EmbedClient.embed_batch<br/>embeddings<br/>nomic-embed-text (rulebook)"}}
    C{{"C · BaseAgent._complete / CoderAgent<br/>chat.completions<br/>qwen2.5-coder:14b (settings)"}}
    D{{"D · GraphMemory._embed<br/>embeddings<br/>nomic-embed-text (settings)"}}
  end

  %% ── Stores ──
  PG[("Postgres<br/>parsed_jds · canonical_jds · audit_log")]
  DOCIDX[("Neo4j jd_document_embeddings<br/>(:JDDocument)")]
  ROLEIDX[("Neo4j jd_role_embeddings<br/>(:JDRole)")]
  ARTIDX[("Neo4j artifact_embeddings")]
  HUMAN(["HR reviewer approves"])

  %% batch embed
  MK_EMB --> EMB_RUN
  PG -- parsed JDs --> EMB_RUN
  EMB_RUN --> B
  EMB_RUN -- write --> DOCIDX
  MK_ROLES --> ROLE_RUN
  PG -- current roles --> ROLE_RUN
  ROLE_RUN --> B
  ROLE_RUN -- write --> ROLEIDX
  DOCIDX -. Tier-3 / clustering READ only .-> PG

  %% canonical producer
  MK_CANON --> PROD
  PG -- clusters --> PROD
  PROD --> REWRITE --> A
  REWRITE -- "fail → keep merge draft" --> VAL1
  REWRITE --> VAL1 --> AUDIT --> A
  AUDIT -- "advisory · fail → omit" --> PG
  PG -- DRAFT --> HUMAN

  %% builder
  R_SEARCH --> SEARCH --> B
  SEARCH -- query --> DOCIDX
  SEARCH -- query --> ROLEIDX
  R_NEW --> DUP --> B
  DUP -- query --> ROLEIDX
  R_ASSIST --> ASSIST --> A
  ASSIST --> VAL2

  %% harness
  R_TASK --> ARQ --> ORCH --> C
  ORCH --> GMEM
  R_MEM --> GMEM
  GMEM --> D
  GMEM -- read/write --> ARTIDX

  classDef call fill:#2f81f7,color:#fff,stroke:#1c4fa0;
  classDef oracle fill:#8957e5,color:#fff,stroke:#5a32a3;
  classDef human fill:#3fb950,color:#fff,stroke:#217a33;
  classDef unguarded fill:#d73a49,color:#fff,stroke:#8b1a26;
  class A,B,D call;
  class C unguarded;
  class VAL1,VAL2 oracle;
  class HUMAN human;
```

**Blue** = egress-guarded network call · **Red** = network call without the egress guard
· **Purple** = deterministic validator · **Green** = human gate.

---

## Findings from this sweep

1. 🔴 **Call site C is not egress-guarded.** `BaseAgent.__init__`
   ([agents/base.py:53](../core/src/agents/base.py#L53)) and `CoderAgent.__init__`
   ([agents/coder.py:33](../core/src/agents/coder.py#L33)) build `AsyncOpenAI` from
   `settings.ollama_base_url` without `assert_inference_host_allowed`. The comment in
   [memory/graph.py:30-39](../core/src/memory/graph.py#L30-L39) states the rule that
   should cover them — *"one setting, one rule, checked everywhere it is read"* — and
   these two reads were missed. Fix is a `core/` change → branch + PR, with a failing
   test first.
2. The harness pipeline reads models from `settings`, not the rulebook. That is
   deliberate (the JD Bank clients' docstrings insist on keeping the two apart), but it
   means `qwen2.5-coder:14b` is not in the HR register — correct, since it never touches
   a JD decision.
3. `suggest_summary` reuses `rules.rewrite.model` / `max_tokens` / `max_retries` — no
   separate rulebook knob. A change to the rewrite model moves the Builder assist too.
