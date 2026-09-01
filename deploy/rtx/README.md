# RTX hosts (`rcg-asalah-1` / `rcg-asalah-2`) — vLLM + full stack

**Status: TRIAGE ONLY. Nothing here is wired into the app yet, on purpose.**

Target: replace Ollama-on-`aria-gb10-2` with **vLLM** on the two SFU RCG RTX boxes, and
run the full JD Bank stack there.

---

## Step 1 — run the triage (do this first)

```bash
scp deploy/rtx/triage.sh asalah@rcg-asalah-1.research.sfu.ca:/tmp/
ssh asalah@rcg-asalah-1.research.sfu.ca 'bash /tmp/triage.sh' | tee rtx-1.txt

scp deploy/rtx/triage.sh asalah@rcg-asalah-2.research.sfu.ca:/tmp/
ssh asalah@rcg-asalah-2.research.sfu.ca 'bash /tmp/triage.sh' | tee rtx-2.txt
```

Read-only: it installs nothing, writes nothing, and contacts no third party. Verified to
run to **exit 0** on a box with no GPU, no `nvidia-smi`, no `ss`, and no firewall tool —
every absent tool prints `(absent: …)` and the run continues, because a missing tool is a
finding, not a crash.

**Why triage before provisioning.** CLAUDE.md's standing lesson is *check the Bank, not
the counter*. A provisioning script written against an assumed distro and driver version
is that same failure in a new costume. The provisioning script gets written against
`rtx-1.txt` / `rtx-2.txt`, not against a guess.

---

## Step 2 — three decisions that block the wiring

None of these are code problems. Each one is a ruling that has to exist before an edit is
honest, and two of them are expensive to get wrong.

### 🔴 D1 — These boxes are on a PUBLIC IP. That is an ADR-003 re-decision, not a config append.

`rcg-asalah-1` → `206.12.17.82`, `rcg-asalah-2` → `206.12.17.83`. Both publicly routable.
`aria-gb10-2` is not.

The repo already refuses this, deliberately and in two places. `assert_inference_host_allowed`
(`core/src/jd_bank/security/egress.py`) admits a host only on an **exact allowlist match**
or a **loopback / RFC-1918 literal**; a routable public FQDN is rejected *before* the
`AsyncOpenAI` client is constructed, so no JD content can have left the process. The same
check runs again at settings load in production (`core/src/settings.py:668`).

So pointing `OLLAMA_BASE_URL` at these hosts fails closed until they are added to
`ALLOWED_INFERENCE_HOSTS`. **Do not just add them.** `.env.example` and `settings.py` both
carry the same instruction, written before this came up:

> Moving inference OFF a trusted segment is a FIPPA question (NN #5) — re-decide it, do
> not just append a host here.

What "re-decide" means concretely: an **ADR-003 amendment** recording that SFU RCG hosts
are institutionally controlled (they are SFU, not a vendor — NN #5's actual invariant is
*no third-party/cloud API*, which RCG does not violate), plus what keeps the endpoint from
being reachable by anyone but us. **vLLM ships no authentication.** A vLLM bound to
`0.0.0.0` on `206.12.17.82` is an open inference endpoint serving JD text to the internet.
The triage's *Listening sockets* and *Firewall posture* sections exist to measure that.

The safe shape, and my recommendation: **bind vLLM to `127.0.0.1` and reach it over an SSH
tunnel or a private interface** — never a public bind. That keeps the egress guard's
loopback/private branch satisfied *by construction* and needs no allowlist widening at all.

### 🔴 D2 — Changing the embedding model forces a full re-embed of the whole archive.

This is by design and the design is good, but the cost is real.

`embeddings.yaml` is content-hashed into `Embeddings.stamp` (`rules/loader.py:995`), and
that stamp is written onto every Neo4j node as `embed_stamp`. The store compares stamps
before it skips, so **any change to `model:` mismatches every existing node and forces a
full re-embed**. The loader's own exclusion list says so explicitly: *"anything touching
WHAT is sent to the model, or WHICH model sees it, does not belong here."*

That is **14,565 documents plus every role**, and `deploy/README.md` already prices the
Neo4j store at 640 MB precisely because rebuilding it "costs GPU hours".

It gets worse than a re-embed if the model's dimensionality moves. `dimensions: 768` must
equal both the model's real output **and** the Neo4j index in
`core/db/migrations/002_jd_vectors.cypher` (`jd_document_embeddings`, `jd_section_embeddings`)
and `003` (`jd_role_embeddings`). A different dimension is a **migration**, not a re-embed.

**Recommendation: serve `nomic-ai/nomic-embed-text-v1.5` on vLLM.** It is 768-dim, so the
Neo4j indexes stand and D2 stays a re-embed rather than a migration. Be clear-eyed that
the vectors will still differ from Ollama's quantised GGUF build of the same model — so
the re-embed is unavoidable either way; this choice only avoids *also* rebuilding the
indexes.

The model name is a **rulebook** value (`embeddings.model`, HR-124, still `open`), not a
setting. Changing it means editing `embeddings.yaml`, updating HR-124, running
`make register`, and committing the regenerated register **in the same commit** — CI's
drift check is not part of `make gates`, and skipping it is how the 2026-08-27 merge went
red.

### 🟡 D3 — One vLLM process serves one model. Two models means two servers.

Verified against vLLM's docs: serving multiple models from one OpenAI-compatible server
is not supported — you run one instance per model. JD Bank needs **two**:

| what | rulebook key | today (Ollama) | vLLM equivalent |
|---|---|---|---|
| embeddings | `embeddings.model` (HR-124) | `nomic-embed-text` | `nomic-ai/nomic-embed-text-v1.5` |
| chat / rewrite + audit | `rewrite.model` (HR-176), `quality.model` | `qwen2.5-coder:14b` | `Qwen/Qwen2.5-Coder-14B-Instruct` |

Two boxes, two roles is the obvious split — but the split should follow the triage's VRAM
numbers, not the hostnames. Note `ChatClient` uses **constrained decoding** (`response_format`
with a JSON schema); vLLM supports this via its guided-decoding backend, and it is worth a
live golden run before trusting it, since the Ollama path already hit one model-specific
failure there (`failed to load model vocabulary required for format`).

---

## What is already true, and needs no decision

Two pleasant surprises from reading the code:

- **The client swap is genuinely config-only.** `EmbedClient` and `ChatClient` both build
  a plain `AsyncOpenAI(base_url=settings.ollama_base_url, api_key="ollama")` and take the
  model name from the rulebook. vLLM's OpenAI-compatible surface accepts both, and ignores
  the api_key. ADR-003 promised "swapping to vLLM later is a config change, not a code
  change" — that promise holds. The env var is still *named* `OLLAMA_BASE_URL`, which will
  read as a lie once vLLM is behind it; renaming it is cosmetic and can ride along later.
- **`install.ps1` is portable.** It has no `C:\` paths, no `.exe` calls, no CIM/WMI — it
  should run under `pwsh` on Linux as-is. The only Windows assumptions are two error
  *strings* ("Install Docker Desktop", "Start Docker Desktop") at lines 134 and 137.

## Not yet written, and deliberately so

The provisioning script (driver → NVIDIA container toolkit → vLLM containers → health
check) and the compose wiring. Both get written against real triage output.

---

## Verification pass (2026-09-01) — the claims above, checked against the code

Every factual claim in D1–D3 was re-read against the source rather than trusted. **All of
them hold.** Three things the first pass did not say came out of it, and each one changes
how a decision should be ruled — so they are recorded here, not just in a chat log.

| claim | verdict |
|---|---|
| egress guard is exact-allowlist **or** loopback/RFC-1918 IP literal, before `AsyncOpenAI` exists | ✅ `security/egress.py` — `_is_internal_ip` + `assert_inference_host_allowed` |
| the same check runs again at settings load in production | ✅ `settings.py:647` `_unsafe_inference_host`, reached from `_unsafe_for_production` (`:539`), gated on `environment == "production"` (`:427`) |
| `embeddings.yaml` is content-hashed into `Embeddings.stamp` → `embed_stamp` | ✅ `rules/loader.py:995` (`stamp`) over `digest` (`:971`); "WHICH model sees it" is explicitly **in** the digest |
| `dimensions: 768` must match three Neo4j indexes | ✅ `002_jd_vectors.cypher` (`jd_document_embeddings`, `jd_section_embeddings`) + `003_jd_role_vectors.cypher` (`jd_role_embeddings`) — three `vector.dimensions: 768` |
| both clients are a plain `AsyncOpenAI(base_url=..., api_key="ollama")`, model from the rulebook | ✅ `embeddings/client.py:70`, `llm/client.py` — swap is genuinely config-only |
| `install.ps1` is portable bar two error strings | ✅ no `C:\`, no `.exe`, no CIM/WMI anywhere in the file; the two strings are at `:134` and `:137` |

### 🔴 New finding 1 — D1's recommendation needs **no allowlist change at all**

`allowed_inference_hosts` already ships with `localhost`, `127.0.0.1`,
`host.docker.internal` and `aria-gb10-2` (`settings.py:210`). So a loopback-bound vLLM is
admitted **by the default allowlist**, with `localhost` working as well as the IP literal
(it is an exact allowlist entry — the `_is_internal_ip` branch only ever sees IP literals,
so a bare hostname would otherwise be rejected).

That makes the recommended shape strictly stronger than the README argued: binding to
loopback means **no edit to `ALLOWED_INFERENCE_HOSTS`, and no widening of the guard**.
The ADR-003 amendment is still owed — it records *why* RCG is institutionally controlled —
but the security surface does not move at all.

### 🔴 New finding 2 — but loopback + Docker do not compose for free

The app runs in containers (ADR-006). A vLLM bound to `127.0.0.1` **on the host** is not
reachable at `127.0.0.1` **from a container** — that is the container's own loopback. The
options, both already admitted by the guard:

- `host.docker.internal` — on the allowlist already, but on Linux it needs
  `extra_hosts: ["host.docker.internal:host-gateway"]` in compose (it is not automatic as
  it is on Docker Desktop).
- the bridge gateway literal (`172.17.0.1`) — RFC-1918, so the guard's `_is_internal_ip`
  branch admits it directly, no allowlist entry.

Neither is a decision, but D1 is not implementable without picking one, and the triage's
*Docker* + *Listening sockets* sections are what says which is available.

### 🟡 New finding 3 — D2's real risk is the task prefix, and it fails silently

`nomic-embed-text-v1.5` expects task prefixes (`search_document: ` / `search_query: `) on
its inputs; Ollama's packaged `nomic-embed-text` handles that itself. **`embeddings.yaml`
has no prefix knob** — the serialized text goes to the model as-is.

Serve the raw HF weights on vLLM without prefixes and nothing breaks loudly: the vectors
are still 768-dim, they still MERGE onto the same nodes, `make embed` still reports
success. Only retrieval quality degrades — which is exactly CLAUDE.md's *green that does
not mean what it sounds like*. If D2 is ruled toward vLLM, the prefix belongs in
`embeddings.yaml` as a registered knob (it changes WHAT is sent to the model, so it is in
the digest by construction), and the cutover needs a retrieval check against known-good
pairs, not just a completed re-embed.

### 🟡 Refinement to D3 — constrained decoding is one caller, not the whole chat path

`constrain_to_schema` defaults to **False**; the rewrite path uses loose JSON mode. The
only production opt-in is the 4.2b quality audit (`quality/audit.py:106`), on a small
schema. So vLLM's guided decoding needs to work for exactly one call site — a much
smaller live-golden surface than "the chat client" implies.

---

## Blocked: the triage has not run

`rcg-asalah-1` and `rcg-asalah-2` are **reachable** — TCP connects and the SSH handshake
completes (both host keys are in `known_hosts`; `-2`'s was added on first contact). Auth is
the blocker: both answer `Permission denied (publickey,password)`. There is no private key
in `~/.ssh` and the Windows `ssh-agent` service is `Stopped / Disabled`.

**No provisioning script has been written, and that is the correct state** — writing one
against an assumed distro/driver/VRAM is the exact failure `triage.sh`'s header exists to
prevent. It gets written against `rtx-1.txt` / `rtx-2.txt`.
