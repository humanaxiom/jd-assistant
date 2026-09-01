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

---

# TRIAGE RESULT (2026-09-01) — 🔴 STOP. The build cannot proceed on these boxes.

`triage.sh` ran to **exit 0** on both hosts. Raw output is committed beside this file:
[`rtx-1.txt`](rtx-1.txt), [`rtx-2.txt`](rtx-2.txt). Read those, not this summary, if the two
ever disagree.

**The two boxes are byte-for-byte the same spec, and neither is an RTX host.** This is
precisely the outcome triage exists to find, and it invalidates the premise of the plan
above rather than any detail in it. **No provisioning script has been written.** Writing
one now would mean scripting a CUDA install against hardware that is not there.

## What they actually are

| | `rcg-asalah-1` (206.12.17.82) | `rcg-asalah-2` (206.12.17.83) |
|---|---|---|
| OS | Ubuntu 26.04.1 LTS, kernel 7.0.0-30 | identical |
| CPU | AMD EPYC 9135, 64 cores | identical |
| RAM | **750 GiB** | identical |
| **GPU** | 🔴 **NONE** | 🔴 **NONE** |
| Docker | 🔴 absent | 🔴 absent |
| sudo | 🔴 none (`uid=1001`, groups=`asalah` only) | 🔴 none |
| Root disk | 100 G LVM on a 444 G partition | identical |
| Unused NVMe | 2 × 1.7 TB, unpartitioned | identical |
| Outbound | docker.com / huggingface.co / pypi.org all HTTP 200 | identical |
| Listening on `0.0.0.0` | **only sshd:22** | **only sshd:22** |

## 🔴 Blocker 1 — there is no GPU, of any vendor, in either box

Not "no driver". **No device.** Checked four independent ways, both hosts:

- `nvidia-smi` absent, `nvcc` absent, `nvidia-ctk` absent
- `lspci` lists **157 devices** and the only display adapter is a **Matrox G200eW3** —
  that is the BMC's onboard VGA on a server board, not a compute GPU
- `/dev/nvidia*` does not exist
- `modinfo nvidia` → **`Module nvidia not found`** — the driver is not merely unloaded, it
  is not even available to this kernel

There is no AMD Instinct or other accelerator either; the only AMD entries are Turin host
bridges and root-complex event collectors. So "install the driver" is not the fix. Either
the cards were never installed, these are not the machines that were meant, or the RCG
allocation is CPU-only.

## 🔴 Blocker 2 — no Docker, and no way to install it

`docker` is absent and `asalah` is `uid=1001` with `groups=1001(asalah)` — no `docker`
group, no `sudo` group, and `sudo -n true` fails with *interactive authentication is
required* on both hosts. **Nothing can be installed by us.** ADR-006 makes the entire
stack Docker-only with no host-Python fallback, so this blocks running the app here just
as firmly as Blocker 1 blocks vLLM. Storage is emphatically *not* the constraint (344 G
free in the VG plus 3.4 TB of untouched NVMe per box) — root privilege is.

## 🔴 Blocker 3 — neither box can reach `aria-gb10-2`

`http://aria-gb10-2:11434/v1/models` → **HTTP 000** from both. The staged migration the
triage was checking for — stand vLLM up here while the existing Ollama keeps serving, cut
over once vectors agree — **is not available**. Any cutover from these boxes is a hard one.

## 🟡 A new security fact that outranks D1's framing

The boxes are on public IPs **and have no host firewall at all**: `ufw` absent,
`firewall-cmd` absent, and the `iptables` binary itself is absent. Nothing stands between a
listening socket and the internet.

The current posture is clean — the only `0.0.0.0` listener on either box is sshd, and
everything else (systemd-resolved, chrony, and on `-1` a VS Code remote server plus one
Python `MainThread`) is bound to loopback. But it is clean *by accident of nothing running
yet*, not by enforcement.

So D1's recommendation is no longer merely the safer shape — **on this hardware a
`0.0.0.0` vLLM bind would be an unauthenticated inference endpoint on the public internet
with no packet filter in front of it.** Loopback + tunnel is the only defensible option,
and per the verification pass above it needs **no allowlist change at all**.

## Where that leaves D1 / D2 / D3

- **D1** — still owed, and now sharper. The FIPPA/ADR-003 question is unchanged, but the
  *technical* half is settled by the evidence: bind loopback, no exceptions, no allowlist
  edit. The firewall absence is worth naming in the ADR amendment.
- **D2** — unchanged and still correct, but **not actionable**. Nothing about the re-embed
  cost or the `nomic-v1.5` task-prefix gap moves until there is something to serve the
  model on.
- **D3** — **moot for now.** One-process-per-model is a GPU-scheduling decision and there
  is no GPU to schedule.

## 🔴 D0 — the decision that now comes first

**Is this the right hardware, or the right plan?** Three ways out, and this is the owner's
call, not an engineering one:

1. **Get the GPUs.** If the RTX cards were meant to be in these chassis, this is an RCG
   ticket. Everything in this README then applies as written, and the triage should be
   re-run to capture the real VRAM before the provisioning script is written.
2. **Get root, and run CPU-only.** Worth taking seriously and *only partly viable*: 64
   cores and 750 GiB RAM will embed acceptably — `nomic-embed-text` is a ~137 M-parameter
   model and the re-embed is a batch job that can take its time. But `Qwen2.5-Coder-14B`
   for the 4.2a rewrite / 4.2b audit on CPU is single-digit tokens/sec, which is not a
   usable interactive path. A **split** (embeddings here, chat stays on `aria-gb10-2`) is
   coherent — except Blocker 3 says these boxes cannot reach `aria-gb10-2` today.
3. **Stay on `aria-gb10-2`.** Nothing is broken there. This whole branch becomes a
   documented dead end, which is a perfectly good outcome for two days of triage.

**Whichever way D0 goes, root access on both boxes is a prerequisite** — no option above
survives `uid=1001` with no sudo.

---

## ⚠ CORRECTION (same day) — the cards are RTX 6000 Ada. They are not LINKING.

The owner confirms both boxes are **RTX 6000 Ada** machines, "running Linux but nothing
set up yet". The section above concluded "no GPU, of any vendor" — that was the right
reading of the evidence available but **the wrong framing**, and it is corrected here
rather than edited away.

What is true is narrower and more useful: **the OS sees no PCIe link on any GPU slot.**
The cause is *below* the operating system, so no amount of driver or software work on
these hosts will change it.

### Re-probed by numeric vendor ID, not by name

The first pass grepped `lspci` output for the string `nvidia`, which a stale `pci.ids`
database would defeat. It does not: `pci.ids` is dated **2026-02-12**, and the definitive
check is numeric anyway —

- `lspci -nn -d 10de:` → **no output**, both hosts (10de is NVIDIA's vendor ID; immune to
  any name database)
- `lspci -nn -d ::0300 / ::0302 / ::0380` (VGA / 3D / display class) → only the BMC's
  Matrox G200eW3
- `modinfo nvidia` → `Module nvidia not found`; no `/dev/nvidia*`; no `nouveau`/`vfio`

### Not a VM — bare metal, and the right chassis

Ruled out the obvious reconciliation (a VM without passthrough):
`systemd-detect-virt` → **`none`**, and there is no `hypervisor` CPU flag. DMI reports
**Dell PowerEdge R7725** (board `0KRFPX`, rack chassis) on both — a machine that does take
these cards. So the hardware story is consistent; the cards simply are not on the bus.

### The decisive measurement — no link training

Firmware advertises 13 PCIe slots. For every GPU-candidate slot:

| slot | root port | `cur_bus_speed` | downstream devices |
|---|---|---|---|
| 2 | `0001:c4:01` | **Unknown** | **0** |
| 4 | `0001:88:01` | **Unknown** | **0** |
| 6 | `0000:80:03` | **Unknown** | **0** |
| 7 | `0000:88:01` | **Unknown** | **0** |
| 10 | `0000:00:01` | **Unknown** | **0** |

`cur_bus_speed=Unknown` means **no link is trained** — nothing is electrically negotiating
on those slots — and each root port shows AMD's *Turin PCIe Dummy Host Bridge*, its marker
for an unpopulated root complex. 157 PCI endpoints enumerate in total; none is NVIDIA.

### What this evidence can and cannot distinguish

It **cannot** tell these three apart, because all three produce exactly this signature:

1. the cards are not physically installed yet;
2. they are installed but have no link — unseated, GPU riser cage not cabled, or no
   auxiliary power;
3. the slots are disabled or powered down in BIOS.

Reading `dmesg` would narrow it (BAR-assignment and link-training failures are logged),
but `kernel.dmesg_restrict=1` and `asalah` is in neither `adm` nor `systemd-journal`.

### Next steps, in order

1. 🔴 **Check iDRAC hardware inventory** (out-of-band, *System → Inventory → PCIe*). This
   is definitive and settles case 1 vs cases 2–3 in one look, independent of BIOS settings
   and of the OS. It needs no Linux access at all.
2. If the cards **are** listed as installed: check BIOS for **Above 4G Decoding** (a 48 GB
   card needs large-BAR MMIO space and will fail to enumerate without it), plus slot
   enable/disable and PCIe bifurcation on the riser.
3. If they are **not** listed: physical install / re-seat / aux-power and riser cabling —
   an RCG or Dell-support task.
4. 🔴 **Independently: `asalah` needs root (or at minimum `adm` + `docker`) on both boxes.**
   Blocker 2 stands regardless of how the GPU question resolves — nothing in this plan is
   installable at `uid=1001` with no sudo.

**Re-run `triage.sh` once the cards link.** The provisioning script still gets written
against real `nvidia-smi` VRAM numbers, not against an assumption — which remains the
whole point.

### FAQ: "there's no NVIDIA because the OS is plain — don't we just need CUDA?"

No. Reasonable question, and the answer is worth writing down because it is the natural
first guess.

**`lspci` enumerates the PCI bus, not drivers.** Measured on `rcg-asalah-1`: of **157** PCI
devices, **112 have no kernel driver bound at all** — and `lspci` lists every one. Driver
software is irrelevant to whether a device is enumerated.

Four layers, and we fail at the first:

| layer | what happens | when | CUDA involved? |
|---|---|---|---|
| 1. **PCIe link training** | card and slot negotiate electrically | power-on, in firmware — before the OS exists | **no** |
| 2. **PCI enumeration** | kernel walks the bus; `lspci` reports it | boot | **no** |
| 3. Driver binding | `nvidia.ko`, `/dev/nvidia*`, `nvidia-smi` | after install | yes |
| 4. CUDA runtime + container toolkit | containers can use the GPU | after install | yes |

`cur_bus_speed=Unknown` on every GPU slot is a **layer-1** failure: no link was trained, so
layer 2 has nothing to enumerate. CUDA lives at layers 3–4 and cannot make a device appear
on a bus it never joined.

On a correctly-linked box with a bare OS and zero NVIDIA software, `lspci` still prints
`NVIDIA Corporation AD102GL [RTX 6000 Ada Generation]` — merely with nothing under *Kernel
driver in use*. The control case here is the onboard Matrox, which enumerates fine and has
`mgag200` bound automatically, so driver loading works on these hosts in general.

**The driver and container toolkit ARE required** — they are step one of the provisioning
script. They are simply downstream of this problem: installing them today would fail at
`nvidia-smi` with *no devices found*, because there is no device to find.
