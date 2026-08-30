# CURRENT — where the truth lives

**The authoritative index for humans and agents. Read this before stating any fact about
this project.**

🔴 **This file deliberately contains almost no facts.** Facts rot; pointers and commands
do not. Every row below names **where the answer lives** and **how to check it yourself**.
If you find a count, a version or a status written *here*, that is a bug — delete it and
leave the pointer.

> **The rule this file exists to enforce:** *do not repeat a fact you have not checked.*
> Five figures once agreed with each other across four documents and all five were wrong —
> they agreed **because** they came from one unchecked source. Agreement between documents
> is a correlated failure, not corroboration. **Only the system and the archive are second
> opinions.**

---

## What is true now

| Question | Authoritative source | Check it yourself |
|---|---|---|
| How many documents, roles, drafts, published? Where does the archive drop out? | 🥇 **`/jd-bank/ui/funnel`** — computed from the DB at request time | open it; `docker compose port api 8000` gives the real port |
| What has been measured about the archive, and the working behind it | [`docs/FINDINGS.md`](docs/FINDINGS.md) | each finding names its command |
| Which parser version is in force | the constant, not a doc | `grep '^PARSER_VERSION' core/src/jd_core/parser/segmenter.py` |
| How many decisions are open / ratified, and what HR still owes | the generated register's **own header** | `sed -n '5,7p' docs/decisions/HR-DECISION-REGISTER.md` |
| Is the tree clean? Is anything unmerged? | git and GitHub, never a document | `git status && git fetch && gh pr list` |
| Is the stack up? On which ports? | Docker, never a document | `docker ps` · `docker compose port api 8000` |
| Is the archive itself as claimed? | **the source files** — `C:\repos\hris\fixtures\SFU_JDs` (read-only) | `make field-audit` · `make singletons` |
| What we do next | [`docs/plan.md`](docs/plan.md) | — |
| What is half-finished right now | [`HANDOFF.md`](HANDOFF.md) | verify against `gh pr list` before trusting it |

⚠ **A document is never the authority for a number.** If a doc and the funnel disagree,
the funnel is right and the doc is a bug.

---

## Which document is which

| Document | Status | It is for |
|---|---|---|
| [`CURRENT.md`](CURRENT.md) | 🟢 **live** | this index — read first |
| [`HANDOFF.md`](HANDOFF.md) | 🟢 **live** | state and traps at the start of a session |
| [`docs/plan.md`](docs/plan.md) | 🟢 **live** | what we do next, in order |
| [`CLAUDE.md`](CLAUDE.md) | 🟢 **live** | invariants and the change workflow |
| [`docs/FINDINGS.md`](docs/FINDINGS.md) | 🟢 **live** | everything measured, with its working |
| [`docs/OPERATOR-GUIDE.md`](docs/OPERATOR-GUIDE.md) | 🟢 **live** | using and running the system (served in-app at 📖 Guide) |
| [`DEVELOPER_GUIDE_1.md`](DEVELOPER_GUIDE_1.md) | 🟢 **live** | onboarding, workflow, `PARSER_VERSION` contract |
| [`docs/decisions/`](docs/decisions/) | 🟢 **live** | the register (generated) + what HR must decide |
| [`docs/adr/`](docs/adr/) | 🟢 **live** | architecture decisions |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | 🟠 **superseded** | the 2026-08-13 review, as a record |
| [`docs/STATUS-2026-08-24.md`](docs/STATUS-2026-08-24.md) | 🟠 **diagnosis stands, prescription superseded** | why priorities were reset |
| [`CodeX/`](CodeX/) | 🟠 **superseded in its numbers** | the 2026-08-07 design critique |
| [`docs/baseline/`](docs/baseline/), [`docs/audit/`](docs/audit/) | 🔵 **dated records** | measurements at the version each names |
| [`docs/archive/`](docs/archive/) | 🔵 **history** | the build record |

**🔵 dated records are not stale — they are evidence.** Each is stamped with the version it
measured. Do not "refresh" one; take a new measurement and add it.

---

## Two rulings that override older wording anywhere you find it

1. **Owner ruling, 2026-08-29 — the measure is DRAFTS.** Nothing is blocked on policy, and
   publishing happens in the **final deployment**, not in pilot/dev/MVP. Any document
   asking *"does this change the number of PUBLISHED JDs?"* is out of date. Ask instead:
   **does this give a role a draft, or make an existing draft truer to its sources?**
2. **Directive #1 — tested, and deployable without the assistant.** `make gates` green,
   the failing test written first, the guard broken once to prove it can go red, and it
   ships through the scripts. See [`CLAUDE.md`](CLAUDE.md).

---

## For agents

- **Two different things are called "agents" here.** `core/src/agents/` is a live Python
  pipeline in the app (`run_pipeline` arq job). `harness-claude-code/.claude/agents/*.md`
  are Claude Code definitions that are **vendored, not installed** — no session dispatches
  them. Details in [`CLAUDE.md`](CLAUDE.md).
- **You are the reviewer.** Every "a subagent's claim of green is not evidence" rule binds
  when the claim is your own; the second opinion is a re-run, not another model.
- **Before you state a number, run the command in the table above.** Before you follow a
  rule you read in a document, check it here — the rule may be one of the superseded ones.
