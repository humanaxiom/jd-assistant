"""Render the HR decision register to Markdown, for humans.

``decision_register.yaml`` is the source of truth (CLAUDE.md §2: rulebook as
data). This module is a *view* of it — never the other way round::

    make register        # writes docs/decisions/HR-DECISION-REGISTER.md
    make register-check  # fails if the committed Markdown drifted (CI runs this)

Because the register is machine-checked against the live rules
(:func:`~src.jd_core.rules.loader.check_register`), rendering it can only ever
print values that are actually in force — the document HR reads and the config
the validator runs on cannot disagree.

Ordering is by ``id`` throughout and grouping is fixed, so the output is
byte-stable: the only thing that can change it is a change to the register.

Run as a module (this is what the Makefile does, inside the ``gates`` container —
``docs/`` is not mounted there, so the Markdown is written on the host from
stdout)::

    python -m src.jd_core.rules.render > docs/decisions/HR-DECISION-REGISTER.md
"""

from __future__ import annotations

import difflib
import sys
from collections.abc import Mapping, Sequence
from typing import Any, Final, cast

from src.jd_core.rules.loader import (
    DecisionProvenance,
    DecisionStatus,
    HRDecision,
    Rules,
    assert_register_in_step,
    decision_surface,
    get_rules,
)

#: Where the rendered view is committed (relative to the repo root, not ``core/``).
REGISTER_MARKDOWN: Final[str] = "docs/decisions/HR-DECISION-REGISTER.md"

#: Provenance, in the order HR should read it: what nobody ratified comes first.
_PROVENANCE_ORDER: Final[tuple[DecisionProvenance, ...]] = (
    "our_invention",
    "prior_calibration",
    "sfu_rulebook",
)

#: Section headings and blurbs use the SAME words as the table labels below. Two
#: vocabularies for one idea is how a reader stops trusting a document.
_PROVENANCE_HEADING: Final[dict[DecisionProvenance, str]] = {
    "our_invention": "We chose it — nobody has ratified these",
    "prior_calibration": "An earlier version of this tool chose it — also unratified",
    "sfu_rulebook": "SFU's published standard — but read the caveats",
}

_PROVENANCE_BLURB: Final[dict[DecisionProvenance, str]] = {
    "our_invention": (
        "We picked these because the system needed *a* value. There is no SFU "
        "precedent behind any of them. **Start here.**"
    ),
    "prior_calibration": (
        "Numbers an earlier version of this software already used, which we kept. "
        "SFU has never published a scoring model, so these are **not** SFU rules and "
        "**not** industry standards — they are engineering guesses that happen to be "
        "older than the rest. They need your ruling exactly as much as the group "
        "above."
    ),
    "sfu_rulebook": (
        "The value is SFU's own, from the JD Toolkit or the official template — but "
        "*what we do about a breach* (whether it merely costs points or actually "
        "blocks approval, and how widely we search for it) is still ours. Each entry "
        "says which part is which."
    ),
}

#: The label shown in the SUMMARY TABLE. It must be self-explaining: an HR reader
#: asked "prior calibration — what is this??", and they were right to. A term of
#: art in a column, with its definition in a section heading hundreds of lines
#: below, is not a label — it is a lookup the reader will not perform.
_PROVENANCE_LABEL: Final[dict[DecisionProvenance, str]] = {
    "our_invention": "we chose it",
    "prior_calibration": "an earlier version of this tool",
    "sfu_rulebook": "SFU's published standard",
}

#: Printed immediately above the summary table, so the fourth column can be read
#: without leaving it.
_PROVENANCE_LEGEND: Final[tuple[str, ...]] = (
    "**Reading the last column.** Where each value came from is the whole point of "
    "this register — so it is written out plainly here, and no term of art is used "
    "anywhere in it:",
    "",
    "| Where it came from | What that means for you |",
    "|---|---|",
    "| **SFU's published standard** | The number is SFU's own, taken from the JD "
    "Toolkit or the official template. *What we do about a breach* — whether it "
    "merely costs points or actually blocks approval — is still ours, and each entry "
    "says which part is which. |",
    "| **an earlier version of this tool** | A number an earlier version of this "
    "software already used, which we kept. SFU has never published a scoring model, "
    "so this is **not** an SFU rule and it is **not** an industry standard — it is an "
    "engineering guess that happens to be older than the others. Treat it exactly as "
    'you would *"we chose it"*. |',
    "| **we chose it** | We picked a value because the system needed one. There is no "
    "SFU precedent behind it, and nobody outside this project has approved it. |",
    "",
    "Two of the three mean *nobody at SFU has agreed to this yet.* That is the "
    "honest position, and it is why this document exists.",
)

#: Status sections, in the order they are rendered: what is still open first.
_STATUS_ORDER: Final[tuple[DecisionStatus, ...]] = ("open", "ratified", "deferred")

_STATUS_HEADING: Final[dict[DecisionStatus, str]] = {
    "open": "Open — we defaulted these; SFU HR has not decided them",
    "ratified": "Ratified by SFU HR",
    "deferred": "Deferred — consciously postponed",
}


def _code(value: str) -> str:
    return f"`{value}`"


#: Beyond this many members, a collection is summarised (not listed) in the
#: summary TABLE — a 116-verb glossary in a table cell is unreadable. The full
#: value is always shown in the entry's detail block below it.
_TABLE_MEMBER_LIMIT: Final[int] = 4


def _format_value(value: Any, *, compact: bool = False) -> str:
    """A ``current_default`` as Markdown.

    ``compact`` is for the summary table, where a long collection is shown as a
    count and the reader is sent to the detail block.
    """
    if value is None:
        return _code("null")
    if isinstance(value, bool):
        return _code("true" if value else "false")
    if isinstance(value, Mapping):
        entries = cast(Mapping[str, Any], value)
        if not entries:
            return "*(empty)*"
        if compact and len(entries) > _TABLE_MEMBER_LIMIT:
            return f"*{len(entries)} entries — see below*"
        return "; ".join(f"{_code(key)} → {entries[key]}" for key in entries)
    if isinstance(value, list):
        items: list[str] = [str(item) for item in value]
        if not items:
            return "*(empty)*"
        if compact and len(items) > _TABLE_MEMBER_LIMIT:
            return f"*{len(items)} entries — see below*"
        return ", ".join(_code(item) for item in items)
    return _code(str(value))


def _decision_block(decision: HRDecision) -> list[str]:
    lines = [
        f"#### {decision.id} — {decision.question.strip()}",
        "",
        f"- **We ship:** {_format_value(decision.current_default)}",
        f"- **Configured in:** `{decision.config.file}` → `{decision.config.path}`",
    ]
    provenance = _PROVENANCE_LABEL[decision.provenance]
    if decision.source_part:
        provenance = f"{provenance} ({decision.source_part})"
    lines.append(f"- **Where the default came from:** {provenance}")
    lines.append(f"- **Why it matters:** {decision.why_it_matters.strip()}")
    lines.append(f"- **If it changes:** {decision.impact_if_changed.strip()}")
    if decision.status == "ratified":
        lines.append(
            f"- **Decided by:** {decision.decided_by} on {decision.decided_on} — "
            f"{decision.decision_note}"
        )
    elif decision.status == "deferred":
        who = decision.decided_by or "—"
        when = decision.decided_on or "—"
        note = decision.decision_note or "no note recorded"
        lines.append(f"- **Deferred by:** {who} on {when} — {note}")
    lines.append("")
    return lines


def _is_pattern_valued(decision: HRDecision) -> bool:
    """Is this decision's value a regular expression?

    Detected from the config path rather than by sniffing the string, so a value
    that merely *looks* regex-ish is never mangled and a real pattern is never
    missed. Every pattern in the rulebook lives either at a ``*_pattern`` key or
    in ``patterns.yaml``.
    """
    return decision.config.path.endswith("_pattern") or (
        decision.config.file == "patterns.yaml"
    )


def _summary_table(decisions: tuple[HRDecision, ...]) -> list[str]:
    lines = [
        "| ID | Decision | Default | Where the default came from |",
        "|---|---|---|---|",
    ]
    for d in decisions:
        question = " ".join(d.question.split())
        # A regex in a table cell tells this document's stated audience nothing —
        # it is not a decision they can weigh. The full pattern is in the detail
        # block below, next to the `why_it_matters` that explains what it does.
        value = (
            "*a text pattern — see below*"
            if _is_pattern_valued(d)
            else _format_value(d.current_default, compact=True)
        )
        lines.append(
            f"| [{d.id}](#{d.id.lower()}) | {question} | "
            f"{value} | {_PROVENANCE_LABEL[d.provenance]} |"
        )
    lines.append("")
    return lines


def render_register(rules: Rules) -> str:
    """The HR decision register as Markdown. Deterministic for a given rulebook."""
    assert_register_in_step(rules)
    register = rules.decision_register
    decisions = tuple(sorted(register.decisions, key=lambda d: d.id))
    counts = {status: len(register.by_status(status)) for status in _STATUS_ORDER}

    out: list[str] = [
        "# SFU HR Decision Register",
        "",
        "> **Generated file — do not edit by hand.** Rendered from"
        " `core/src/jd_core/rules/decision_register.yaml` by `make register`."
        " `make register-check` (and CI) fails the build if this file drifts from it.",
        "",
        f"Rulebook version `{rules.version}` · **{len(decisions)} decisions** "
        f"({counts['open']} open · {counts['ratified']} ratified · "
        f"{counts['deferred']} deferred) · {len(register.trivial)} parameters "
        f"explicitly exempted as trivial · "
        f"{len(decision_surface(rules))} parameters on the decision surface, all "
        "accounted for.",
        "",
        "## What this is",
        "",
        "Every policy call JD Bank currently makes **by default**, because SFU HR has"
        " not made it. For each one: the question, the value we ship, exactly where"
        " that value is configured, and — the column that matters most — whether the"
        " default came from SFU's published rulebook, from an earlier internal"
        " implementation we carried forward, or from nobody but us.",
        "",
        "**Nothing here is a code change.** Every value below is a line in a versioned"
        " YAML file. Changing one is a data edit; `src/jd_core/quality/` is not"
        " touched.",
        "",
        "**This document cannot rot.** The register is data, and the build checks it"
        " against the live rules three ways: every `Configured in` path must resolve;"
        " every `We ship` value must equal the real one; and every parameter on the"
        " decision surface must be either listed here or explicitly exempted as"
        " trivial. Tune a threshold without updating the register and `make gates`"
        " fails.",
        "",
    ]

    out += [*_PROVENANCE_LEGEND, ""]

    for status in _STATUS_ORDER:
        in_status = register.by_status(status)
        if not in_status:
            continue
        out += [f"## {_STATUS_HEADING[status]}", ""]
        out += _summary_table(in_status)
        for provenance in _PROVENANCE_ORDER:
            group = tuple(d for d in in_status if d.provenance == provenance)
            if not group:
                continue
            out += [
                f"### {_PROVENANCE_HEADING[provenance]}",
                "",
                _PROVENANCE_BLURB[provenance],
                "",
            ]
            for decision in group:
                out += _decision_block(decision)

    out += [
        "## Trivial — on the decision surface, deliberately not a decision",
        "",
        "The build requires every parameter on the decision surface to be either a"
        " decision above or an exemption here **with a reason**. Nothing can be"
        " silently skipped. `Covered by` means the parameter *is* a decision — just"
        " one that is pinned by the entry named, so changing it still breaks the"
        " build.",
        "",
        "| Configured in | Why it is not a decision | Covered by |",
        "|---|---|---|",
    ]
    for exemption in sorted(register.trivial, key=lambda t: t.config.path):
        reason = " ".join(exemption.reason.split())
        covered = exemption.covered_by or "—"
        out.append(f"| `{exemption.config.path}` | {reason} | {covered} |")
    out.append("")

    return "\n".join(out) + "\n"


def check_markdown(committed: str, rules: Rules) -> tuple[str, ...]:
    """A unified diff of ``committed`` against a fresh render. Empty == in step."""
    fresh = render_register(rules)
    if committed == fresh:
        return ()
    return tuple(
        difflib.unified_diff(
            committed.splitlines(),
            fresh.splitlines(),
            fromfile=f"{REGISTER_MARKDOWN} (committed)",
            tofile="rendered from decision_register.yaml",
            lineterm="",
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Render the register — or, with ``--check``, diff it against stdin.

    Both modes run **entirely inside the container** (ADR-006): the ``gates``
    service mounts only ``./core``, so ``docs/`` is invisible to it. ``make
    register`` redirects stdout to the file; ``make register-check`` pipes the
    committed file in on stdin, and the comparison happens here — no host ``diff``,
    ``mkdir`` or ``rm``, which do not exist on the Windows shell ``make`` uses.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    rules = get_rules()

    if args == ["--check"]:
        diff = check_markdown(sys.stdin.read(), rules)
        if not diff:
            sys.stdout.write(f"{REGISTER_MARKDOWN} is in step with the register.\n")
            return 0
        sys.stderr.write("\n".join(diff) + "\n")
        sys.stderr.write(
            f"\n{REGISTER_MARKDOWN} is STALE. Run `make register` and commit it.\n"
        )
        return 1

    if args:
        sys.stderr.write("usage: python -m src.jd_core.rules.render [--check]\n")
        return 2

    sys.stdout.write(render_register(rules))
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
