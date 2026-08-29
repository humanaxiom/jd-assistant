# Subagent model strategy

How we pick a model tier for each subagent, and why it does not cost us quality.

Status: ⚠ **DORMANT for Claude Code sessions, as of 2026-08-29.** It described "every
subagent dispatched in this repo", and today no session dispatches any: the definitions in
`harness-claude-code/.claude/agents/` are vendored, not installed at the repo root, so
Claude Code never loads them — and the standing session rule is not to dispatch an agent
unless the user asks. See CLAUDE.md § *Two different things are called "agents" here*.

**Keep it, for two reasons.** The evidence below is a real record of what a merge-blocking
reviewer caught, and the principle survives the mechanism: **downgrade the writer, never
the checker.** When one model does the writing AND the checking, the checker half is a
separate, adversarial *pass* — re-run the gates, break the guard, read the diff — not a
separate model. That is the form the CLAUDE.md verification rules now take.

It applies as written the moment the definitions are installed, or to the `run_pipeline`
pipeline in `core/src/agents/`, which IS live.

---

## The principle

**Spend on judgment, not on typing.**

Model cost should track how much *judgment* a task needs, not how much *text* it produces.
A 700-line faithful port of business logic and a 700-line docs refresh are the same size and
nothing like the same risk.

The quality floor is not the coder's model tier. It is:

1. **`make gates` green** — ruff · black · mypy --strict · unit · integration · coverage ≥ 80.
   Non-negotiable at every tier (ADR-006).
2. **The merge-blocking Reviewer**, which re-runs the gates independently and audits the diff
   adversarially.

Those two hold regardless of which model wrote the code. So a cheaper coder does not lower the
floor — it just needs a stronger oracle underneath it. That is the whole strategy: **downgrade
the writer, never the checker.**

---

## Why the checker is never downgraded

Evidence from Phase 2 (four tasks, four Tester+Coder → Reviewer cycles). The Reviewer returned
CHANGES REQUIRED **every time**, and every finding was real:

| Task | What the coder shipped and believed was done | What the Reviewer caught |
|---|---|---|
| 2.1 rules-as-data | "gates green, 51 tests" | The 116-verb glossary was pinned only by `len() == 116` + spot-checks. A corrupted verb passed. |
| 2.2 validators | "gates green, faithful port" | `SFU-GATE-DUTY-PCT` built an unbounded evidence string against a 500-char cap → **the validator crashed** on real archive input. |
| 2.3 gate runner | "an unreasoned override is unrepresentable" | `model_construct` bypassed it. Also: the **non-overridable** placeholder gate could not fire on `[insert department]` or on any 5+ underscore run — a false safety guarantee. |
| Decision register | "94 params, full coverage" | The surface walked 6 of 10 rule files. Eleven judgment calls invisible, three feeding **blocking** gates. |

Coders were competent and consistently **over-claimed**. Reviewers were the reason nothing bad
shipped. Reviewers therefore stay on the strongest tier, always. This is not negotiable, and it
is what buys the freedom to run cheaper coders elsewhere.

---

## Tiers

### Tier A — strongest model (Opus)
Judgment-heavy, ambiguous, or unforgiving. **Always** used for:

- **Every merge-blocking Reviewer**, without exception, at any task size.
- **Faithful ports** where fidelity to a source is the requirement (`hris` → `jd_core`).
- **Rulebook / policy semantics** — validators, gates, severities, scoring, anything touching
  `gates.yaml`, `rule_catalog.yaml`, or `decision_register.yaml`.
- **Security-touching diffs** — subprocess, file I/O, untrusted input, auth, network.
- Anything where the spec is genuinely underdetermined and the subagent must *decide*.

### Tier B — mid model (Sonnet)
Well-specified implementation with a **strong mechanical oracle** — the tests, types, or an
exact spec can tell right from wrong without taste:

- Wiring and scaffolding against an existing, settled pattern.
- Refactors fully covered by existing tests.
- Fixture/data transcription where the exact expected values are supplied in the brief.
- Renderers, serializers, CLI plumbing.
- Docs generated from a supplied outline.

### Tier C — cheapest model (Haiku)
Mechanical and verifiable by reading the diff:

- Renames, path scrubs, import reordering, formatting.
- Moving files; deleting dead code that a test already proves dead.
- HANDOFF / changelog / backlog updates from supplied facts.

---

## Guardrails (these are what make it safe)

1. **The Reviewer is always Tier A.** If the checker is cheap, the whole scheme collapses.
2. **`make gates` green is required at every tier.** No exceptions, no host fallback.
3. **Escalate on judgment.** A Tier B/C subagent that hits an ambiguity — needs a new dependency,
   wants to change a default, finds the spec underdetermined, or thinks a rule value is wrong —
   must **STOP and report**, never guess. Say this explicitly in the brief.
4. **Never downgrade a task whose acceptance criterion is "faithful to the source."** Fidelity
   bugs are silent; gates do not catch them, only a careful reader does.
5. **No cheap tier without a mechanical acceptance test.** If you cannot say in advance what
   would prove the work correct, the task is not Tier B/C — it is Tier A.
6. **Never downgrade anything that changes a decision parameter.** Those belong in the decision
   register and get Tier A eyes (see `docs/decisions/HR-DECISION-REGISTER.md`).

## Dispatching

The `Agent` tool takes a `model` parameter (`opus` | `sonnet` | `haiku`). Set it explicitly per
dispatch; do not rely on inheritance. State the tier and the reason in the brief so the subagent
knows when to escalate rather than improvise.

If in doubt: **Tier A.** A wrong port costs far more than the model did.
