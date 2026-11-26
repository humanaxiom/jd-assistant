"""The harmonize REWRITE pass (Phase 4.2a) — the LLM's first Phase-4 consumer.

:func:`rewrite_merged_role` takes the deterministic Phase-4.1
:class:`~src.jd_core.models.bank.MergedRole` draft (already a valid
``SFUJobDescription``) and has a self-hosted LLM reword it into cleaner,
template-faithful prose, then scores the result with the validator (the oracle).

**We differ from hris deliberately.** hris fed the LLM the raw member JDs and let it
free-associate; we feed the GROUNDED 4.1 merge draft and forbid new content. The rewrite
may REPHRASE the draft but may not INTRODUCE skills/duties/qualifications the draft did
not contain — a deterministic **anti-fabrication guard** (the heart of this task) scrubs
ungrounded qualifications and flags no-overlap duties after the model replies. The
prompt instruction is advisory; the guard + validator are what actually bound the output
(validator-as-oracle, non-negotiable #3).

The result is a frozen ``RewrittenDraft`` with no approval, canonical or published
field: it is a DRAFT (non-negotiable #1). Nothing here publishes
anything, and ``jd_core`` is never imported the other way round.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Final

from pydantic import BaseModel

from src.jd_bank.jd_text import flatten_jd as _flatten_jd
from src.jd_bank.jd_text import outline_jd
from src.jd_bank.llm.client import ChatClient
from src.jd_bank.llm.prompts import load_prompt
from src.jd_bank.rewrite.fidelity import (
    before_cut,
    carries_placeholder,
    content_tokens,
    cut_off_tail,
    field_cap,
    grounding_comparison,
    is_fragment,
    named_terms,
    sentences,
    source_view,
    stemmed_tokens,
)
from src.jd_core.bank.merge import duty_text
from src.jd_core.models.bank import (
    AntiFabricationRecord,
    MergedRole,
    RewrittenDraft,
)
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.models.quality import DEFAULT_TEMPLATE, WJQ_TEMPLATE, JDTemplate
from src.jd_core.quality.scoring import score_issues
from src.jd_core.quality.validators import evaluate_jd_rules, template_of
from src.jd_core.rules import Comparison, Rewrite, Rules, get_rules
from src.jd_core.textnorm import fold_text

#: The ONLY fields the rewrite may change. Everything else on the draft is restored from
#: the grounded 4.1 merge, which derived it from the source JDs.
#:
#: 🔴 **THIS IS AN ALLOW-LIST BECAUSE A DENY-LIST FAILED THREE TIMES.** The pass was
#: written as "the model returns a JD, we scrub what it ADDED" — the anti-fabrication
#: guard — and nothing at all policed what it REMOVED. Each time a field turned out to
#: matter, it was patched individually, and the next one was found the same way (by
#: probing the live Bank, never by a test):
#:
#: 1. ``employee_group`` — nulled on ~95% of CUPE drafts, silently moving each one to
#:    the JDFN bar, because that field is what ``template_of`` reads.
#: 2. ``classification`` / ``position_number`` — facts about the posting a language
#:    model has no way to know, added to the patch pre-emptively.
#: 3. ``additional_context`` — nulled likewise, which on a CUPE draft is **seven of the
#:    WJQ's fourteen sections**: the merge had just been fixed to carry them (HR-207)
#:    and the rewrite threw them away again on the very next run.
#:
#: The prompt's own schema literally shows ``"additional_context": null``, so the model
#: is doing what it was asked. The defect is the contract, not the model: **a rewrite
#: that may return any field can delete any field**, and "reword this draft" does not
#: license dropping content the sources stated. Inverting the default makes the next
#: such field safe by construction rather than after someone notices it missing.
#:
#: The boilerplate presence booleans are deliberately absent here too — they are set
#: explicitly further down, per template, and restoring them first makes that the only
#: place they are decided.
_REWRITABLE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "title",
        "position_summary",
        "duties",
        "decision_making",
        "problem_solving",
        "relationships",
        "qualifications",
    }
)

#: The sections the guard will not let the rewrite CREATE from nothing. Each is a whole
#: SFU-template section that a JDFN document has and a WJQ one structurally does not, so
#: on a CUPE draft an invented one is not embellishment — it is an answer to a question
#: the source document was never asked. Duties and qualifications are deliberately NOT
#: here: those are policed per item, by grounding, above.
_SECTIONS_NEVER_INVENTED: Final[tuple[str, ...]] = (
    "decision_making",
    "problem_solving",
    "relationships",
)

#: 🔴 REPLACED BY ``rewrite.rewritable_qualification_kinds`` (HR-208, 2026-08-19).
#:
#: This was a hardcoded ``frozenset({"knowledge", "skill", "ability"})`` naming the
#: kinds the grounding guard scrubs — its comment argued that education / experience /
#: security "are structural BARS derived by the 4.1 merge from member signals, not
#: free-text skills the model could invent, so they pass through". Every clause of that
#: is true except the conclusion: because they are derived rather than authored, a model
#: returning them has NO SOURCE for them, and passing them through is precisely what let
#: a clerical CUPE draft come back demanding a PhD in Astrophysics and an Enhanced
#: Reliability clearance, with an empty anti-fabrication record.
#:
#: The set is now rulebook DATA (CLAUDE.md §2) and does two jobs: the kinds in it are
#: the model's to author, policed by grounding; every other kind is DISCARDED and
#: restored from the merge draft. Left as a name so the reasoning above stays findable.


def _rewritable_kinds(rewrite: Rewrite) -> frozenset[str]:
    """The qualification kinds this rulebook lets the rewrite author (HR-208)."""
    return frozenset(rewrite.rewritable_qualification_kinds)


def _content_tokens(text: str, comparison: Comparison) -> frozenset[str]:
    """The content tokens of ``text`` — lowercase ``[a-z0-9]+`` runs, minus stopwords
    and short tokens (the SAME filter ``signals._skill_bag`` applies), so grounding
    lines up with how skills are compared everywhere else."""
    return content_tokens(text, comparison)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Token-Jaccard. Two empty sets are identical (1.0)."""
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _closest(
    tokens: frozenset[str], candidates: Sequence[frozenset[str]]
) -> tuple[int, float]:
    """``(index, score)`` of the candidate closest to ``tokens`` by token-Jaccard, or
    ``(-1, 0.0)`` when there are no candidates.

    One helper for both directions of the duty reconciliation — "which merge duty is
    this rewritten one?" and "does this merge duty still exist?" are the same question
    asked from either end, so they must not be two pieces of arithmetic that can drift.
    """
    best_index, best = -1, 0.0
    for index, candidate in enumerate(candidates):
        score = _jaccard(tokens, candidate)
        if score > best:
            best_index, best = index, score
    return best_index, best


def _skill_frequency_lines(freq: Sequence[tuple[str, int]]) -> str:
    """``skill_frequency`` provenance as the prompt's ``skill_frequency`` slot."""
    if not freq:
        return "(none extracted)"
    return "\n".join(f"- {name}: {count}" for name, count in freq)


def _draft_vocabulary(
    source: SFUJobDescription, merged: MergedRole, comparison: Comparison
) -> frozenset[str]:
    """The allowed vocabulary a rewritten qualification must be grounded in: the SOURCE
    VIEW's content tokens (:func:`~src.jd_bank.rewrite.fidelity.source_view` — the
    merge draft minus the questionnaire's instructions and SFU's boilerplate, HR-273…
    HR-276) PLUS its member-derived skill-frequency names. Generous by design — a
    rephrasing reuses the draft's words; a wholly new skill does not.

    🔴 Boilerplate is OUT since 2026-10-20: the merge carries the EE statement and the
    territorial acknowledgement as qualification lines, and on the pilot's 1d68c603 the
    model fused them into "Commitment to employment equity and respect for Indigenous
    territories and cultures" — which their own words then grounded."""
    vocab: set[str] = set(_content_tokens(_flatten_jd(source), comparison))
    for name, _count in merged.provenance.skill_frequency:
        vocab |= _content_tokens(name, comparison)
    return frozenset(vocab)


def _names_grounded(
    text: str, vocab: frozenset[str], rewrite: Rewrite, comparison: Comparison
) -> bool:
    """Whether every NAMED term of ``text`` (an acronym, a capitalized word mid-item —
    :func:`~src.jd_bank.rewrite.fidelity.named_terms`) is in ``vocab`` (HR-272). A
    token-overlap bar cannot see a new name riding on grounded words: "(e.g., ICOM Code
    of Ethics, CITES)" passed at 5 of 9 where the source says "International Council on
    Museums"."""
    names, numbers = (
        rewrite.named_terms_must_be_grounded,
        rewrite.numbers_must_be_grounded,
    )
    if not (names or numbers):
        return True
    terms = named_terms(text, comparison, numbers=numbers)
    if not names:
        terms = frozenset(t for t in terms if t.isdigit())
    return terms <= vocab


def _is_grounded(
    text: str, vocab: frozenset[str], rewrite: Rewrite, comparison: Comparison
) -> bool:
    """Whether ``text`` is grounded in ``vocab`` under the policy (HR-182/183).

    ``token_overlap``: grounded iff at least ``skill_grounding_threshold`` of its
    content tokens are in ``vocab``. ``all_grounded``: grounded only if EVERY token is
    (the threshold is inert). A qualification with no content tokens (all stopwords) is
    grounded — there is nothing to fabricate. Either way its named terms must be in
    ``vocab`` too (HR-272).
    """
    if not _names_grounded(text, vocab, rewrite, comparison):
        return False
    return _qualification_covered(_content_tokens(text, comparison), vocab, rewrite)


def _qualification_covered(
    tokens: frozenset[str], vocab: frozenset[str], rewrite: Rewrite
) -> bool:
    """The qualification token rule (HR-182/183) on token sets, either direction."""
    if not tokens:
        return True
    grounded = tokens & vocab
    if rewrite.skill_grounding_policy == "all_grounded":
        return grounded == tokens
    return len(grounded) / len(tokens) >= rewrite.skill_grounding_threshold


def _covers(tokens: frozenset[str], vocab: frozenset[str], threshold: float) -> bool:
    """Whether ``vocab`` holds at least ``threshold`` of ``tokens``. A text with no
    content tokens has nothing to fabricate and nothing to lose."""
    return not tokens or len(tokens & vocab) / len(tokens) >= threshold


def _grounded_in_one(
    text: str,
    units: Sequence[frozenset[str]],
    vocab: frozenset[str],
    threshold: float,
    rewrite: Rewrite,
    comparison: Comparison,
) -> bool:
    """Whether ``text`` is supported by ONE of ``units`` (token sets) at ``threshold``,
    with its named terms in ``vocab``. One unit, never their union (review round 2:
    against a long duty's whole vocabulary, a clause stitched from words scattered over
    many clauses passed)."""
    if not _names_grounded(text, vocab, rewrite, comparison):
        return False
    tokens = _content_tokens(text, comparison)
    return not tokens or any(
        len(tokens & unit) / len(tokens) >= threshold for unit in units
    )


def _ceiling(field: str, model: type[BaseModel] = SFUJobDescription) -> int:
    """The model's own ``max_length`` for a list field — a restore may never build a
    value the contract would refuse to read back."""
    for meta in model.model_fields[field].metadata:
        limit = getattr(meta, "max_length", None)
        if isinstance(limit, int):
            return limit
    raise LookupError(f"{model.__name__}.{field} has no max_length")  # pragma: no cover


def _optional_ceiling(field: str, model: type[BaseModel]) -> int | None:
    """:func:`_ceiling`, for a field the contract leaves UNBOUNDED on purpose —
    ``SFURelationships.supervisory`` since HR-324 (its cap is rulebook data and ships
    as null). ``None`` means nothing to fit under."""
    try:
        return _ceiling(field, model)
    except LookupError:
        return None


def _has(value: object) -> bool:
    """Whether a section VALUE carries content. A ``SFURelationships`` with no
    supervisory text and no contacts is empty, though the object itself is truthy."""
    if isinstance(value, SFURelationships):
        return bool(value.supervisory or value.internal or value.external)
    return bool(value)


def _reconcile_list(
    section: str,
    source_items: Sequence[str],
    model_items: Sequence[str],
    rewrite: Rewrite,
    comparison: Comparison,
    log: _ItemLog,
) -> list[str]:
    """One list section, per item (HR-269/270): keep a model item only if ONE source
    item of the same section grounds it, then put back (if the section is restorable)
    every source sentence the kept items no longer cover."""
    threshold = rewrite.section_item_grounding_threshold
    units = [_content_tokens(item, comparison) for item in source_items]
    vocab = frozenset().union(*units)
    # A decision the merge marked REFERRED (HR-282/283) grounds a rewritten decision
    # only if that decision keeps the referral: the round-2 model wrote "Makes decisions
    # regarding the expenditure of University funds" from a decision its source REFERS.
    label = log.referred_label if section == "decision_making" else ""
    label_stems = log.stems(label) if label else frozenset()
    referred = [bool(label) and item.startswith(label) for item in source_items]
    kept: list[str] = []
    for item in model_items:
        usable = units
        # The WHOLE label, not one word of it (review of c873b13: "Approves …,
        # informing the supervisor" kept a referred decision as one it makes).
        if any(referred) and not label_stems <= log.stems(item):
            usable = [u for u, ref in zip(units, referred, strict=True) if not ref]
        if _grounded_in_one(item, usable, vocab, threshold, rewrite, comparison):
            kept.append(item)
        else:
            log.scrubbed.append((section, item))
    lost = log.restorable(
        log.losses(section, source_items, kept, rewrite, comparison, cap=section)
    )
    if not lost or section not in rewrite.restore_uncovered_items_in:
        return kept
    restored = [*kept, *lost]
    if len(restored) > _ceiling(section):
        restored = list(source_items)  # the source fits its own contract
    log.restored.extend((section, text) for text in lost)
    return restored


class _ItemLog:
    """What the per-item section guard dropped, found lost, and put back."""

    def __init__(self, rules: Rules) -> None:
        self._rules = rules
        self.referred_label = rules.harmonization.referred_decision_label
        self.scrubbed: list[tuple[str, str]] = []
        self.uncovered: list[tuple[str, str]] = []
        self.restored: list[tuple[str, str]] = []

    def stems(self, text: str) -> frozenset[str]:
        """``text``'s stemmed content tokens (HR-285), for the referral check."""
        return stemmed_tokens(
            text,
            grounding_comparison(self._rules),
            self._rules.rewrite.coverage_stem_suffixes,
        )

    def restorable(self, texts: Sequence[str]) -> list[str]:
        """``texts`` minus any carrying a template placeholder (the HR-047 gate —
        :func:`~src.jd_bank.rewrite.fidelity.carries_placeholder`) or that is a
        FRAGMENT (HR-287: "Makes decisions regarding", "(e.g. … curve tracers,"). Those
        stay in :attr:`uncovered` only, so the review page lists them as dropped."""
        return [
            t
            for t in texts
            if not carries_placeholder(t, self._rules)
            and not is_fragment(t, self._rules)
        ]

    def losses(
        self,
        section: str,
        source_items: Sequence[str],
        kept: Sequence[str],
        rewrite: Rewrite,
        comparison: Comparison,
        *,
        cap: str,
    ) -> list[str]:
        """The source ITEMS to put back (whole — never a partial clause), recording
        every source SENTENCE the kept items do not cover (HR-269, read from the
        source's end); an exact repeat is listed once.

        Lost-ness is judged per sentence, so nothing is silently gone; what comes back
        is the source item (round 2: restoring sentences one by one turned a contacts
        paragraph into bullets of single sentences, one of them a parser cut-off). An
        item exactly at the parser's character cap for its field (``cap`` names it) was
        CUT: its unterminated last sentence is a partial clause, recorded and never put
        back, and the item returns up to it (HR-287).

        A lost sentence deliberately does NOT join the covering vocabulary. The merge
        has already de-duplicated a section's items (HR-210…212), and on a contact list
        the shared words are the department's name: on the pilot's 0a75edf1, letting
        a restored "Biomedical Physiology and Kinesiology Faculty …" cover the rest
        hid the distinct BPK Researchers and Laboratory Engineers contacts."""
        threshold = rewrite.section_item_grounding_threshold
        vocab = frozenset().union(*(_content_tokens(k, comparison) for k in kept))
        limit = field_cap(cap, self._rules)
        lost: list[str] = []
        back: list[str] = []
        for item in source_items:
            whole, tail = cut_off_tail(item, limit, self._rules)
            missing = [
                s
                for s in whole
                if not _covers(_content_tokens(s, comparison), vocab, threshold)
            ]
            if missing:
                # Recorded at the granularity it is restored at, so "lost and not put
                # back" (the review page's list) never names text that IS in the draft.
                text = before_cut(item, tail)
                if text and text not in back:
                    back.append(text)
            if tail is not None and not _covers(
                _content_tokens(tail, comparison), vocab, threshold
            ):
                lost.append(tail)
        self.uncovered.extend((section, text) for text in dict.fromkeys([*back, *lost]))
        return back


def _reconcile_relationships(
    source: SFURelationships,
    model: SFURelationships,
    rewrite: Rewrite,
    comparison: Comparison,
    log: _ItemLog,
) -> SFURelationships:
    """Relationships per item against the merge's OWN relationships (HR-269/270).

    🔴 MEASURED (pilot, 0a75edf1): the model replaced a WJQ draft's Biomedical
    Physiology and Kinesiology contacts — and every duration / frequency cell with them
    — by "Engineering Science" contacts the section never names, and nothing objected:
    only an EMPTY or INVENTED section was ever checked. The supervisory text, each
    internal and each external contact is one unit; a model item must be grounded in one
    of them, and every source sentence must stay covered by what is kept."""
    section, threshold = "relationships", rewrite.section_item_grounding_threshold
    sup_units = (
        sentences(source.supervisory, rewrite.sentence_abbreviations)
        if source.supervisory
        else []
    )
    # A contact is grounded in ONE unit: a supervisory sentence, or a window of up to
    # `relationships_row_window` consecutive items of one contact list (HR-288). The WJQ
    # table reaches the merge one cell per item ("Graduate Students", "< 1 hour",
    # "Frequent"), and prompt v4 asks the model to keep a contact's duration and
    # frequency WITH it — which no single cell grounds (round 2: 7 such contacts were
    # scrubbed). Names are still checked (HR-272), against the whole section.
    window = rewrite.relationships_row_window
    rows = [
        " ".join(items[i : i + size])
        for items in (source.internal, source.external)
        for size in range(1, window + 1)
        for i in range(len(items) - size + 1)
    ]
    units = [_content_tokens(text, comparison) for text in (*sup_units, *rows)]
    vocab = frozenset().union(*units)

    def keep(item: str) -> bool:
        if _grounded_in_one(item, units, vocab, threshold, rewrite, comparison):
            return True
        log.scrubbed.append((section, item))
        return False

    supervisory = (
        model.supervisory if model.supervisory and keep(model.supervisory) else None
    )
    internal = [c for c in model.internal if keep(c)]
    external = [c for c in model.external if keep(c)]
    kept = [*([supervisory] if supervisory else []), *internal, *external]
    restoring = section in rewrite.restore_uncovered_items_in
    lost_sup = log.losses(
        section,
        [source.supervisory] if source.supervisory else [],
        kept,
        rewrite,
        comparison,
        cap="supervisory",
    )
    lost_int = log.losses(
        section, source.internal, kept, rewrite, comparison, cap="internal"
    )
    lost_ext = log.losses(
        section, source.external, kept, rewrite, comparison, cap="external"
    )
    if not restoring or not (lost_sup or lost_int or lost_ext):
        return model.model_copy(
            update={
                "supervisory": supervisory,
                "internal": internal,
                "external": external,
            }
        )
    lost_sup, lost_int, lost_ext = (
        log.restorable(lost_sup),
        log.restorable(lost_int),
        log.restorable(lost_ext),
    )
    if lost_sup:
        joined = " ".join(part for part in (supervisory, *lost_sup) if part)
        # Over the ceiling, the SOURCE's text (minus any parser cut-off) replaces the
        # model's: it covers itself, and it fits, being shorter than the source field.
        sup_ceiling = _optional_ceiling("supervisory", SFURelationships)
        supervisory = (
            joined
            if sup_ceiling is None or len(joined) <= sup_ceiling
            else " ".join(lost_sup)
        )
    internal = [*internal, *lost_int]
    if len(internal) > _ceiling("internal", SFURelationships):
        internal = list(source.internal)
    external = [*external, *lost_ext]
    if len(external) > _ceiling("external", SFURelationships):
        external = list(source.external)
    log.restored.extend((section, text) for text in (*lost_sup, *lost_int, *lost_ext))
    return model.model_copy(
        update={"supervisory": supervisory, "internal": internal, "external": external}
    )


#: Where a model statement or clause is cut into the pieces HR-284 compares: ";" and
#: sentence ends — the model merges several source sentences into one clause. Not at
#: commas: measured, a comma cut "Manage revenue streams from cash donations, grant
#: funding and sale of image use rights…" into two pieces neither of which held enough
#: of the source sentence it rewords.
_MODEL_PIECES: Final[re.Pattern[str]] = re.compile(r";\s+|(?<=[.!?])\s+")
_COMMA: Final[re.Pattern[str]] = re.compile(r",\s+")
#: A capitalized word, for telling a Title Case heading from a sentence with names.
_CAPITALIZED: Final[re.Pattern[str]] = re.compile(r"\b[A-Z][A-Za-z0-9]*")
_WORDS: Final[re.Pattern[str]] = re.compile(r"\b[A-Za-z][A-Za-z0-9]*")


class _DutyCoverage:
    """Whether a source duty SENTENCE is already in the rewritten duties (HR-267 read
    source -> rewrite, HR-272 names, HR-284 rewording, HR-285 stemming) — the test that
    decides what fold-back puts back.

    Round 2 measured both ways it was wrong:

    * **Too loose** (cb73e45c, item 3): "careers as they relate to academic programs"
      was "covered" by a duty's words PLUS text fold-back had just put in ("academic
      offerings"), and "opportunities in Cooperative Education" by two generic words
      without its name — both gone from the draft and in no record. So the model's
      text covers on its own (restored text no longer pools into it: it covers only
      its own near-duplicate sentence), and the covering duty must state the
      sentence's named terms.
    * **Too strict** (museum, item 4): "Monitors possible copyright infringement." came
      back word for word under the model's "…, monitor copyright issues, …". So words
      are compared stemmed, and a model piece that clearly rewrote the sentence (most
      of ITS words are the sentence's, and it keeps ``reworded_unit_min_share`` of the
      sentence) covers it.

    Coverage only: grounding (rewrite -> source) is unchanged and unstemmed.
    """

    def __init__(self, duties: Sequence[SFUDuty], rules: Rules) -> None:
        rewrite = rules.rewrite
        self._rewrite = rewrite
        self._comparison = grounding_comparison(rules)
        self._threshold = rewrite.how_why_grounding_threshold
        self._share = rewrite.reworded_unit_min_share
        #: The whole-duty test reads the model's words UNSTEMMED: measured on the
        #: round-2 replay, stemming a whole merged duty let its generic words ("need",
        #: "priority", "request") "cover" lost sentences — "allocating centrally
        #: managed classrooms…" by "Determine records needs, priorities…". Stemming is
        #: for the PIECE test below, where one model clause has to match one sentence.
        self._duties = [content_tokens(duty_text(d), self._comparison) for d in duties]
        #: Each model clause cut at ";" and sentence ends — and each comma PART of
        #: those too: a model clause lists several rewordings ("Assess suitability of
        #: …, monitor copyright issues, identify risks of stolen property …"), and one
        #: of them may be all that is left of a source sentence. Both bars of HR-284
        #: still apply to every piece, whole or part.
        self._pieces = [
            stems
            for d in duties
            for text in (d.statement, *d.how_why)
            for piece in _MODEL_PIECES.split(text)
            for part in dict.fromkeys((piece, *_COMMA.split(piece)))
            if (stems := self._stems(part))
        ]
        #: (stemmed tokens, raw tokens) of each restored sentence.
        self._restored: list[tuple[frozenset[str], frozenset[str]]] = []

    def _stems(self, text: str) -> frozenset[str]:
        return stemmed_tokens(
            text, self._comparison, self._rewrite.coverage_stem_suffixes
        )

    def _names(self, text: str) -> frozenset[str]:
        rw = self._rewrite
        if not (rw.named_terms_must_be_grounded or rw.numbers_must_be_grounded):
            return frozenset()
        terms = named_terms(text, self._comparison, numbers=rw.numbers_must_be_grounded)
        words = _WORDS.findall(text)
        heading = (
            bool(words)
            and words[0][0].isupper()
            and len(_CAPITALIZED.findall(text)) * 3 >= len(words) * 2
        )
        if not rw.named_terms_must_be_grounded or heading:
            # A Title Case heading ("Compliance with International, National, &
            # Provincial Heritage Legislation") capitalizes every word, so a capital
            # names nothing there: only its acronyms and numbers are its names.
            terms = frozenset(
                t
                for t in terms
                if t.isdigit()
                or (
                    rw.named_terms_must_be_grounded
                    and any(
                        sum(c.isupper() for c in w) >= 2 and w.lower() == t
                        for w in words
                    )
                )
            )
        return terms

    def __call__(self, sentence: str, *, headline: str = "") -> bool:
        """Covered? For a how/why clause pass its source duty's ``headline``: what the
        clause adds beyond its headline is what can be lost, so the headline's words do
        not count towards covering it — "ordering welcome event food" under "…welcome
        events" is not covered by a duty that says "Plans the welcome events"."""
        raw = content_tokens(sentence, self._comparison)
        tokens = self._stems(sentence)
        if headline:
            # Only when the clause keeps at least two words of its own: one leftover
            # word ("student", of "the execution of all student grades") would be
            # covered by any duty that mentions it.
            if len(own_raw := raw - content_tokens(headline, self._comparison)) >= 2:
                raw = own_raw
            if len(own := tokens - self._stems(headline)) >= 2:
                tokens = own
        if not tokens:
            return True
        thr = self._threshold
        names = self._names(sentence)
        if any(_covers(raw, v, thr) and names <= v for v in self._duties):
            return True
        # ⚠ A reworded piece is NOT held to the sentence's names (review of c873b13,
        # measured): requiring them listed 98 more sentences on the round-2 replay, most
        # a member's own unit name the harmonized role rightly generalises ("AAE's
        # website", "the School's website", "SFU Food's website" -> "website"), and
        # folding them put the rewording in twice. The cost — a reworded sentence can
        # lose an audience list ("…to the Dean, Associate Deans, Chairs") silently — is
        # recorded as an open question on HR-284.
        if any(
            len(p & tokens) / len(p) >= thr
            and len(p & tokens) / len(tokens) >= self._share
            for p in self._pieces
        ):
            return True
        # Names too (review of c873b13): a two-word sentence "opportunities in
        # Cooperative Education" read as covered by a restored sentence sharing only
        # "opportunities".
        return any(
            _covers(tokens, r, thr) and names <= raw_r for r, raw_r in self._restored
        )

    def restored(self, sentence: str) -> None:
        """``sentence`` is in the draft now as restored text: ONE restored sentence
        covers a later source sentence it holds the HR-267 fraction of (a second
        member's duty saying the same thing) — never the restored text pooled with the
        model's, which is how "careers as they relate to academic programs" read as
        covered by "programs" (model) plus "academic" (the folded "academic
        offerings")."""
        if tokens := self._stems(sentence):
            self._restored.append((tokens, content_tokens(sentence, self._comparison)))


_LEAD_WORD: Final[re.Pattern[str]] = re.compile(r"[A-Za-z]+")


def _lead_word(text: str) -> str:
    match = _LEAD_WORD.search(text)
    return match.group(0).lower() if match else ""


def _source_kind(
    text: str,
    sources: Sequence[SFUQualification],
    rules: Rules,
    template: JDTemplate = DEFAULT_TEMPLATE,
) -> str | None:
    """The kind of the SOURCE qualification ``text`` rewords (HR-294), or ``None`` when
    it may not be taken: the source line holding the largest share of its words (ties
    to the first), if that share reaches ``qualification_kind_min_overlap`` (HR-302) and
    ``text`` does not NAME a different kind by its lead word (HR-303).

    🔴 MEASURED (the v9 full pass): the merge's CUPE lines are `skill` and `ability`
    only — the WJQ parser never writes `knowledge` — yet 568 of the 612 rewritten CUPE
    drafts failing K→S→A carry a `knowledge` line, and "Ability to use word-processing…"
    came back `skill` in one place and `ability` two lines later.

    🔴 REVIEW of 6000ba6 (measured on JDFN): with no floor, "PMP certification" took
    `knowledge` from a line sharing a quarter of its words; "Ability to build
    consensus…" took `skill` from "Excellent interpersonal skills with the ability to…".
    A line whose lead word names a kind keeps it — unless the source line opens with the
    same word, which is what a CUPE form section looks like ("Ability to …" printed
    under Occupational Skills)."""
    rewrite = rules.rewrite
    comparison = grounding_comparison(rules)
    tokens = _content_tokens(text, comparison)
    if not tokens:
        return None
    best, chosen = 0.0, None
    for src in sources:
        share = len(tokens & _content_tokens(src.text, comparison)) / len(tokens)
        if share > best:
            best, chosen = share, src
    if chosen is None or best < rewrite.qualification_kind_min_overlap:
        return None
    lead = _lead_word(text)
    # Per form (round-2 review): on the WJQ the kind is the form SECTION and a line's
    # lead word only a reading of it — 65 CUPE lines kept `ability` and would print
    # under Occupational Requirements instead of Occupational Skills.
    lead_words = rewrite.qualification_kind_lead_words.get(template, {})
    named = next((k for k, words in lead_words.items() if lead in words), None)
    if named is not None and named != chosen.kind and _lead_word(chosen.text) != lead:
        return None
    return chosen.kind


def _form_order(
    competencies: Sequence[SFUQualification],
    bars: Sequence[SFUQualification],
    source: Sequence[SFUQualification],
    rules: Rules,
) -> list[SFUQualification]:
    """Qualifications in the FORM's order (HR-293): the bars (education, experience, …)
    where the merge has them — those it lists before its first competency first, the
    rest after — and the competencies stably sorted by the rulebook's K→S→A rank
    (``qualifications.ksa_rank``, HR-052).

    🔴 MEASURED (the v9 full pass): every CUPE merge draft passes SFU-GATE-KSA-ORDER and
    612 of 636 rewritten ones fail it. The reassembly kept the MODEL's order, appended
    restored lines, then the bars — so a blocking gate failed on an order nobody chose.
    """
    rank = rules.qualifications.ksa_rank
    last = max(rank.values(), default=0) + 1
    authorable = {q.kind for q in competencies} | set(rank)
    first = next((i for i, q in enumerate(source) if q.kind in authorable), len(source))
    lead_texts = {q.text for q in source[:first]}
    lead = [q for q in bars if q.text in lead_texts]
    trail = [q for q in bars if q.text not in lead_texts]
    ordered = sorted(competencies, key=lambda q: rank.get(q.kind, last))
    return [*lead, *ordered, *trail]


_SPACES_RUN: Final[re.Pattern[str]] = re.compile(r"[ \t]+")


def _summary_conditions(
    summary: str | None, source_summary: str | None, rules: Rules
) -> tuple[str | None, list[str]]:
    """The rewritten Position Summary minus every sentence naming a WORKING CONDITION
    (``markers.working_conditions``, the SFU-AUTH-SUMMARY-CONDITIONS markers, HR-046)
    that the source summary does not name itself (HR-295 — the HR-269 rule for this
    section). Returns ``(summary, dropped)``; a summary left empty comes back as the
    source's own.

    🔴 MEASURED (the v9 full pass): 35 CUPE drafts newly fail the blocking summary gate
    after the rewrite, ~30 of them because the model moved the WJQ's working-conditions
    block into the summary ("…flexible hours, including evenings and weekends",
    "on-call or shift schedules"). The markers are matched exactly as the gate matches
    them (folded, case-insensitive substring) and are not changed here."""
    if not summary:
        return summary, []

    def folded(text: str) -> str:
        return fold_text(
            text,
            join_paragraphs=rules.textnorm.collapse_across_paragraph_break,
            casefold=True,
        ).folded

    src = folded(source_summary or "")
    foreign = [m for m in rules.markers.working_conditions if m.casefold() not in src]
    parts = sentences(summary, rules.rewrite.sentence_abbreviations)
    dropped = [p for p in parts if any(m.casefold() in folded(p) for m in foreign)]
    if not dropped:
        return summary, []
    if len(dropped) == len(parts):
        return source_summary, dropped
    # Cut the dropped sentences out IN PLACE (review of 6000ba6): re-joining the kept
    # ones with " " lost the summary's paragraph breaks.
    out = summary
    for sentence in dropped:
        out = out.replace(sentence, "", 1)
    lines = [_SPACES_RUN.sub(" ", line).strip() for line in out.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text, dropped


def form_duty_limit(draft: SFUJobDescription, rules: Rules) -> int:
    """How many duties ``draft``'s FORM holds (HR-290): the form's own ``duties_max``
    and, on the CUPE form, the major-function limit the Builder holds an author to and
    the WJQ parser reads back (``cupe_form.function_limits``, HR-246) — the smaller."""
    template = template_of(draft)
    limit = rules.thresholds_for(template).duties_max
    if template == WJQ_TEMPLATE:
        limit = min(limit, rules.cupe_form.function_limits["major_functions"])
    return limit


def _duty_sentence(duty: SFUDuty) -> str:
    """A duty's headline as one sentence: its action verb in front of its statement,
    unless the statement already starts with it."""
    verb, statement = duty.action_verb.strip(), duty.statement.strip()
    if verb and not statement.lower().startswith(verb.lower()):
        return f"{verb} {statement}"
    return statement


class _Fit(BaseModel):
    """What :func:`_fit_the_form` did."""

    duties: list[SFUDuty]
    merged: list[tuple[str, str]] = []
    over: list[str] = []
    #: ``(absorbed statement, kept frequency, absorbed frequency)`` when they differ.
    conflicts: list[tuple[str, str, str]] = []


def _fit_the_form(
    duties: Sequence[SFUDuty],
    limit: int,
    clause_cap: int,
    comparison: Comparison,
    *,
    min_similarity: float = 0.0,
) -> _Fit:
    """Bring the MODEL's duties within the form (HR-290): at most ``limit`` duties and
    ``clause_cap`` how/why clauses each. Returns ``(duties, merged, over)``.

    🔴 MEASURED (the v9 full pass): the prompt states the form's number and one CUPE
    rewrite still came back with 13 major functions, which the Builder then refused to
    clone ("the form takes at most 12", HR-246). Nothing held the reply to the form.

    MERGE, NEVER DROP: while there are too many, the two MOST SIMILAR duties (token
    Jaccard of their whole text; ties to the earliest pair) become one — the later one's
    headline and clauses are appended as clauses of the earlier. Its frequency is kept
    when the two agree or one is blank; when they differ the earlier one's stands and
    the conflict is recorded. ``merged`` pairs each absorbed headline with the statement
    it went under; a clause the cap cannot hold is returned in ``over``.

    Review of 6000ba6: similarity is the ONLY ordering (it used to prefer any pair that
    fitted the clause cap over a more similar one), and below ``min_similarity``
    (HR-304) nothing is merged: the model's LAST duty is listed whole in ``over``
    instead. Either way fold-back still puts back any source sentence the result no
    longer covers."""
    fit = _Fit(duties=list(duties))
    out = fit.duties
    for i, duty in enumerate(out):
        if len(duty.how_why) > clause_cap:
            fit.over.extend(duty.how_why[clause_cap:])
            out[i] = duty.model_copy(update={"how_why": duty.how_why[:clause_cap]})
    while len(out) > limit:
        tokens = [_content_tokens(duty_text(d), comparison) for d in out]
        score, i, j = min(
            (-_jaccard(tokens[i], tokens[j]), i, j)
            for i in range(len(out))
            for j in range(i + 1, len(out))
        )
        if -score < min_similarity:
            last = out.pop()
            fit.over.extend([_duty_sentence(last), *last.how_why])
            continue
        keep, absorbed = out[i], out.pop(j)
        clauses = [_duty_sentence(absorbed), *absorbed.how_why]
        room = max(clause_cap - len(keep.how_why), 0)
        fit.over.extend(clauses[room:])
        if (
            keep.frequency
            and absorbed.frequency
            and keep.frequency != absorbed.frequency
        ):
            fit.conflicts.append(
                (absorbed.statement, keep.frequency, absorbed.frequency)
            )
        out[i] = keep.model_copy(
            update={
                "how_why": [*keep.how_why, *clauses[:room]],
                "frequency": keep.frequency or absorbed.frequency,
            }
        )
        fit.merged.append((absorbed.statement, keep.statement))
    return fit


def _frequency_by_coverage(
    duty: SFUDuty, source_duties: Sequence[SFUDuty], rules: Rules
) -> str | None:
    """The frequency a FLAGGED rewritten duty carries (HR-292): that of the source
    duties it covers by itself — at least ``flagged_duty_frequency_min_coverage`` of
    each one's sentences, by the fold-back's own coverage test — when they all state
    the same one. ``None`` otherwise, or when the knob is 0.

    🔴 MEASURED (the v9 full pass, each CUPE draft against its OWN merge): 4,339
    frequencies where the merges carried 4,596, all of the loss on flagged duties — a
    flagged duty had no source duty to carry one from. "Assign and supervise temporary
    staff, checking their work and providing guidance and training" is flagged against
    "Assigns and checks the work of temporary staff" (the model's extra words sink the
    Jaccard) and covers every sentence of it."""
    share = rules.rewrite.flagged_duty_frequency_min_coverage
    if share <= 0:
        return None
    covered = _DutyCoverage([duty], rules)
    abbreviations = rules.rewrite.sentence_abbreviations
    found: set[str | None] = set()
    for src in source_duties:
        parts = [
            s
            for text in (src.statement, *src.how_why)
            for s in sentences(text, abbreviations)
        ]
        if parts and sum(1 for s in parts if covered(s)) / len(parts) >= share:
            found.add(src.frequency)
    if len(found) == 1:
        return next(iter(found))
    return None


def _fold_back(
    duties: list[SFUDuty],
    source_duties: Sequence[SFUDuty],
    rules: Rules,
    *,
    duties_max: int,
) -> tuple[list[SFUDuty], list[str], list[str], list[tuple[str, str]]]:
    """Put back the source duty content no rewritten duty covers (HR-271), under the
    rewritten duty it belongs to (HR-279/280).

    🔴 MEASURED (pilot, 1d68c603): a twelve-duty merge, a five-duty JDFN cap (HR policy,
    `thresholds.duties_max`, untouched), and a model that met the cap by DROPPING whole
    areas — "Community Liaison & Committee Representation", "Research & Museum Career
    Skills Training" — recorded in ``removed_duties`` and gone. Merging related duties
    to reach the cap is the rewrite's job; losing an area is not.

    Each SENTENCE of every source duty (statement and clauses) must be covered — the
    HR-267 fraction of its tokens — by ONE rewritten duty as it now stands. An uncovered
    sentence is appended verbatim as a how/why clause of the rewritten duty that holds
    the most of its source duty (``fold_back``), or only listed (``record_only``).
    Covered-ness is re-read after each fold, so a near-duplicate source duty (the merge
    keeps several: S1/S2, S3/S4 on that cluster) does not fold the same point twice.

    🔴 WHERE a sentence goes is read from what the MODEL wrote, never from what was
    folded in (review of 934425f). Placement used to read each duty's text as it grew,
    so the first duty to take a fold held more words for the next source duty, and the
    next: on the pilot's 1d68c603 one duty took 30 of 37 folds, and "Conservation of
    Museum Collections & Asset Management" went under "Engage community partners…" (8%
    of its words there) while another rewritten duty held 24%. 89 of the 314 folds over
    the 28 recorded pilot replies were placed under a duty that was not the best match.

    A source duty whose best match holds less than ``fold_back_relevance_min`` of its
    words (HR-279) is not filed under an unrelated duty: its lost sentences come back as
    ITS OWN duty, verbatim and under its own heading, when the form has room
    (``duties_max``, HR policy), and are listed in ``dropped`` otherwise — shown to the
    reviewer, never silent. ``fold_back_max_per_duty`` (HR-280) passes a fold on to the
    next-best duty above that floor once a duty has taken that many.

    Returns ``(duties, folded, dropped, origins)``; ``origins`` pairs each folded
    sentence with the statement of the source duty it came from, so the review page can
    say where it was restored from."""
    rewrite, comparison = rules.rewrite, grounding_comparison(rules)
    floor, per_duty = rewrite.fold_back_relevance_min, rewrite.fold_back_max_per_duty
    cap = min(_ceiling("how_why", SFUDuty), rules.segmentation.duty_how_why_max_count)
    covered = _DutyCoverage(duties, rules)
    out = list(duties)
    #: What each duty said before anything was folded in — placement reads only this.
    base = [_content_tokens(duty_text(d), comparison) for d in out]
    extra: list[list[str]] = [[] for _ in out]
    folded: list[str] = []
    dropped: list[str] = []
    origins: list[tuple[str, str]] = []

    def has_room(j: int) -> bool:
        if len(out[j].how_why) + len(extra[j]) >= cap:
            return False
        return per_duty == 0 or len(extra[j]) < per_duty

    for src in source_duties:
        src_tokens = _content_tokens(duty_text(src), comparison)
        share = [
            len(src_tokens & tokens) / len(src_tokens) if src_tokens else 0.0
            for tokens in base
        ]
        # Best match first; ties to the first duty, so the fold is deterministic.
        ranked = [
            j
            for j in sorted(range(len(out)), key=lambda j: (-share[j], j))
            if share[j] >= floor
        ]
        unplaced: list[str] = []
        #: This source duty's pieces that may not come back on their own (HR-287):
        #: listed — unless the statement returns as the HEADING of its own duty below.
        listed: list[str] = []
        for text, limit, headline in (
            (src.statement, field_cap("statement", rules), ""),
            *(
                (clause, field_cap("how_why", rules), src.statement)
                for clause in src.how_why
            ),
        ):
            whole, tail = cut_off_tail(text, limit, rules)
            for sentence in (*whole, *([tail] if tail is not None else [])):
                if covered(sentence, headline=headline):
                    continue
                if (
                    rewrite.duty_coverage_policy == "record_only"
                    or not out
                    or carries_placeholder(sentence, rules)  # HR-047: never restore
                ):
                    dropped.append(sentence)
                    continue
                if sentence == tail or is_fragment(sentence, rules):
                    # A parser cut-off, or a lead-in / continuation line: never a
                    # how/why clause of its own (round 2: "Collaborates with V.",
                    # "(e.g. … curve tracers,"). Listed for the reviewer.
                    if sentence not in listed:
                        listed.append(sentence)
                    continue
                target = next((j for j in ranked if has_room(j)), None)
                if target is None:
                    if sentence not in unplaced:
                        unplaced.append(sentence)
                    continue
                extra[target].append(sentence)
                covered.restored(sentence)
                folded.append(sentence)
                origins.append((sentence, src.statement))
        if not unplaced:
            dropped.extend(listed)
            continue
        if len(out) >= duties_max:
            dropped.extend((*listed, *unplaced))
            continue
        # Its own duty, under its own source heading, verbatim.
        # The source statement heads it — unless it carries a placeholder, or a sentence
        # of it is ALREADY in the draft as restored text (folded under another duty a
        # moment ago, under an HR-280 limit or the how/why cap): heading with it would
        # put the same source words in the draft twice (review of 528f694).
        restored_so_far = set(folded)
        # A statement the parser cut heads its duty only up to its last full sentence.
        statement, statement_tail = cut_off_tail(
            src.statement, field_cap("statement", rules), rules
        )
        head_text = before_cut(src.statement, statement_tail)
        if (
            not head_text
            or carries_placeholder(head_text, rules)
            or any(sentence in restored_so_far for sentence in statement)
        ):
            heading, clauses = unplaced[0], unplaced[1:]
        else:
            own = set(statement)
            heading, clauses = head_text, [s for s in unplaced if s not in own]
        overflow = clauses[cap:]
        dropped.extend(overflow)
        restored = src.model_copy(
            update={
                "statement": heading,
                "how_why": clauses[:cap],
                # The source verb belongs to the source STATEMENT: put in front of a
                # how/why clause it would read as a sentence no source wrote.
                "action_verb": src.action_verb if heading == head_text else "",
            }
        )
        out.append(restored)
        base.append(_content_tokens(duty_text(restored), comparison))
        extra.append([])
        # The heading is the source's text too (even where another duty covers it), so
        # it is recorded as restored — the reviewer must not read it as the model's.
        # A lead-in headline ("… by") is in the draft now, as a heading over its
        # clauses, so it is no longer listed.
        heading_pieces = statement if heading == head_text else [heading]
        for sentence in dict.fromkeys((*heading_pieces, *unplaced)):
            if sentence not in overflow:
                covered.restored(sentence)
                folded.append(sentence)
                origins.append((sentence, src.statement))
        dropped.extend(s for s in listed if s not in folded)
    result = [
        duty.model_copy(update={"how_why": [*duty.how_why, *more]}) if more else duty
        for duty, more in zip(out, extra, strict=True)
    ]
    # Listed once each: near-identical source duties from two members can name the
    # same fragment ("Responsible for other duties as assigned by …, such as").
    return result, folded, list(dict.fromkeys(dropped)), origins


def _apply_anti_fabrication(
    llm_jd: SFUJobDescription, merged: MergedRole, rules: Rules
) -> tuple[SFUJobDescription, AntiFabricationRecord]:
    """Scrub what the model invented and restore what it lost (HR-181…HR-184,
    HR-208/213/214/267, and the 2026-10-20 fidelity rules HR-269…HR-276).

    Everything is judged against the SOURCE VIEW of the merge draft
    (:func:`~src.jd_bank.rewrite.fidelity.source_view`): the draft minus the old
    questionnaire's instructions and SFU's boilerplate, which the model is not shown,
    cannot ground anything, and no restore puts back.

    Returns the scrubbed JD + the audit record. When the guard is disabled
    (``rewrite.anti_fabrication_enabled = false``) the model's output is returned
    UNSCRUBBED and the record is empty-but-``enabled=False`` — so a disabled guard is
    visible, never invisible.
    """
    rewrite = rules.rewrite
    if not rewrite.anti_fabrication_enabled:
        return llm_jd, AntiFabricationRecord(enabled=False)

    comparison = grounding_comparison(rules)
    source, stripped, stripped_parts = source_view(merged.draft, rules)
    vocab = _draft_vocabulary(source, merged, comparison)

    authorable = _rewritable_kinds(rewrite)

    # Qualifications, in two populations (HR-208). The kinds the rewrite MAY author are
    # kept subject to grounding, as before. Every other kind is a structural hiring BAR
    # the 4.1 merge derived from the members: the model's version is discarded whatever
    # it says — a plausible invented bar passes a token-overlap test — and the merge's
    # own comes back verbatim.
    bars = [q for q in source.qualifications if q.kind not in authorable]
    bar_texts = {q.text for q in bars}
    kept: list[SFUQualification] = []
    scrubbed: list[str] = []
    restored_bars: list[str] = []
    relabelled: list[tuple[str, str, str]] = []
    source_competencies = [q for q in source.qualifications if q.kind in authorable]
    qual_form = template_of(merged.draft)
    relabel = qual_form in rewrite.qualification_kind_from_source
    for qual in llm_jd.qualifications:
        if (
            relabel
            and qual.kind in authorable
            and (kind := _source_kind(qual.text, source_competencies, rules, qual_form))
            and kind != qual.kind
        ):
            # HR-294: on this form the kind is the SOURCE's — the form section the
            # line it rewords was printed in (HR-302/303 bound it).
            relabelled.append((qual.text, qual.kind, kind))
            qual = qual.model_copy(update={"kind": kind})
        if qual.kind not in authorable:
            # Recorded only when the model's bar DIFFERS from the merge's. A model that
            # echoed the bar back unchanged had nothing overwritten, and a record that
            # fired on every draft would be read exactly the way an empty one is.
            if qual.text not in bar_texts:
                restored_bars.append(qual.text)
        elif not _is_grounded(qual.text, vocab, rewrite, comparison):
            scrubbed.append(qual.text)
        else:
            kept.append(qual)

    # …and what the model DROPPED (2026-10-20). MEASURED: a WJQ draft went 40 -> 15
    # qualifications. Most of that was honest de-duplication, but "circuit fabrication/
    # assembly", "web publishing software" and "instruct others on safe work
    # environments" were simply gone, and nothing recorded it. A source competency no
    # kept one covers (the HR-183 rule read from the source's end, against ONE kept
    # qualification) is recorded, and put back when `qualifications` is restorable.
    log = _ItemLog(rules)
    restoring_quals = "qualifications" in rewrite.restore_uncovered_items_in
    kept_tokens = [_content_tokens(q.text, comparison) for q in kept]
    lost_quals: list[SFUQualification] = []
    for qual in (q for q in source.qualifications if q.kind in authorable):
        tokens = _content_tokens(qual.text, comparison)
        if not any(_qualification_covered(tokens, k, rewrite) for k in kept_tokens):
            lost_quals.append(qual)
            if restoring_quals:
                kept_tokens.append(tokens)
    log.uncovered.extend(("qualifications", q.text) for q in lost_quals)
    # Whole qualifications only (HR-287): a line the parser cut at its 400-character
    # cap comes back up to its last full sentence, and a continuation line ("(e.g. lab
    # power supplies, …, curve tracers," — round 2, 0a75edf1) is listed, not restored.
    back: list[SFUQualification] = []
    for qual in lost_quals:
        whole, tail = cut_off_tail(qual.text, field_cap("qualifications", rules), rules)
        text = before_cut(qual.text, tail)
        if text and whole and log.restorable([text]):
            back.append(
                qual if text == qual.text else qual.model_copy(update={"text": text})
            )
            if text != qual.text:
                log.uncovered.append(("qualifications", text))
    if restoring_quals and back:
        kept = [*kept, *back]
        if len(kept) + len(bars) > _ceiling("qualifications"):
            kept = [q for q in source.qualifications if q.kind in authorable]
        log.restored.extend(("qualifications", q.text) for q in back)
    if rewrite.qualification_order == "form":
        kept = _form_order(kept, bars, source.qualifications, rules)
    else:
        kept.extend(bars)

    # Duties, reconciled against the source view in BOTH directions.
    source_duties = source.duties
    draft_duty_tokens = [
        _content_tokens(duty_text(duty), comparison) for duty in source_duties
    ]
    llm_duty_tokens = [
        _content_tokens(duty_text(duty), comparison) for duty in llm_jd.duties
    ]
    # Review M2 / HR-267: each CLAUSE must be grounded in ONE source unit — a duty's
    # headline plus one of its clauses (or the headline alone) — never in a union.
    # Since 2026-10-20 the unit may come from ANY source duty: the model merges
    # duties to reach the form's cap, and grounding a merged duty's clauses against the
    # one source it was matched to scrubbed 8 faithful clauses on the pilot's 1d68c603
    # and all 15 on 22994d3a. The strictness per unit is unchanged.
    clause_units = [
        unit
        for duty, headline in (
            (d, _content_tokens(d.statement, comparison)) for d in source_duties
        )
        for unit in (
            [headline | _content_tokens(c, comparison) for c in duty.how_why]
            or [headline]
        )
    ]
    duty_vocab = frozenset().union(*draft_duty_tokens)

    # → What did the model ADD? A duty itself is flagged, never dropped — a duty may
    # reword (HR-184). `frequency` is carried back from the merge duty a rewritten one
    # matches: the prompt's duty schema has no key for it, so a wholesale replacement
    # destroyed it on EVERY CUPE draft (S-4).
    flagged: list[str] = []
    duties: list[SFUDuty] = []
    scrubbed_how_why: list[str] = []
    for duty, tokens in zip(llm_jd.duties, llm_duty_tokens, strict=True):
        best_index, best = _closest(tokens, draft_duty_tokens)
        kept_clauses: list[str] = []
        for clause in duty.how_why:
            if _grounded_in_one(
                clause,
                clause_units,
                duty_vocab,
                rewrite.how_why_grounding_threshold,
                rewrite,
                comparison,
            ):
                kept_clauses.append(clause)
            else:
                scrubbed_how_why.append(clause)
        restored: dict[str, Any] = {}
        if kept_clauses != duty.how_why:
            restored["how_why"] = kept_clauses
        if best < rewrite.duty_flag_threshold:
            # A flagged duty used to keep NO clauses (it had no source duty to ground
            # them in). Each clause is now grounded against every source unit, so the
            # faithful ones of a flagged duty stay — and an ungrounded one still never
            # does.
            flagged.append(duty.statement)
            if duty.frequency is None and (
                frequency := _frequency_by_coverage(
                    duty.model_copy(update={"how_why": kept_clauses}),
                    source_duties,
                    rules,
                )
            ):
                restored["frequency"] = frequency
        else:
            # Review round 1: HR-272/278 read the STATEMENT too — "…program under
            # FIPPA" matched its source duty at a high Jaccard and nothing objected.
            # Flagged, never dropped (HR-184: a duty may reword); against the whole
            # source view, since a statement may name what the summary names.
            if not _names_grounded(duty.statement, vocab, rewrite, comparison):
                flagged.append(duty.statement)
            if duty.frequency is None:
                restored["frequency"] = source_duties[best_index].frequency
        duties.append(duty.model_copy(update=restored) if restored else duty)

    # 🔴 EMPTY-TO-EMPTY, FOR DUTIES (HR-213). A grounded draft with NO duties cannot
    # acquire any from a rewording pass. MEASURED ON THE LIVE BANK 2026-08-22: 153
    # drafts carried 1,219 duties that NO source document states — the WJQ parser
    # recovers no duties from 16.2% of CUPE documents, the merge correctly produces
    # nothing from nothing, and the rewrite then wrote eight to twelve plausible duties
    # out of thin air. The duty guard above only FLAGS what the model adds, which is
    # right when the draft HAS duties to drift from and vacuous when it has none. A
    # draft that honestly reports no duties fails `SFU-COMP-DUTIES` — the validator
    # doing its job, and the right place for the parser gap to become visible.
    if rewrite.duties_never_invented and not source_duties and duties:
        invented_duties = [duty.statement for duty in duties]
        duties = []
        flagged = []
        scrubbed_how_why = []  # the whole duty is recorded as invented instead
    else:
        invented_duties = []

    # ← What did the model TAKE AWAY? (S-2) A merge duty with no counterpart this close
    # in the rewrite — RECORDED as what the model did: a rewrite that folds two
    # near-identical duties into one is doing its job.
    removed_duties = [
        duty.statement
        for duty, tokens in zip(source_duties, draft_duty_tokens, strict=True)
        if _closest(tokens, llm_duty_tokens)[1] < rewrite.duty_flag_threshold
    ]
    # Within the FORM before anything is folded back (HR-290): the model's reply is
    # merged down to the form's duty limit and clause cap, so fold-back judges coverage
    # against the duties the draft will actually carry — and never itself adds a duty
    # past the limit.
    duty_limit = form_duty_limit(merged.draft, rules)
    clause_cap = min(
        _ceiling("how_why", SFUDuty), rules.segmentation.duty_how_why_max_count
    )
    merged_duties: list[tuple[str, str]] = []
    over_limit: list[str] = []
    conflicts: list[tuple[str, str, str]] = []
    if rewrite.duties_over_form_limit == "merge":
        fit = _fit_the_form(
            duties,
            duty_limit,
            clause_cap,
            comparison,
            min_similarity=rewrite.duty_merge_min_similarity,
        )
        duties, merged_duties, over_limit = fit.duties, fit.merged, fit.over
        conflicts = fit.conflicts
        # A flagged duty merged into another is a clause now: the flag names the duty
        # it went under (review of 6000ba6), once.
        into = dict(merged_duties)

        def went_under(statement: str) -> str:
            # follow a chain of merges; each absorbed statement left the list, so
            # the chain is finite
            while statement in into:
                statement = into[statement]
            return statement

        flagged = list(dict.fromkeys(went_under(s) for s in flagged))
    # …and what it LOST (HR-271): every source duty sentence no rewritten duty covers is
    # folded back or listed. This replaces the per-duty "restore the source's clauses"
    # rules of v9 review rounds 1–2, which asked the same question of the ONE matched
    # source duty and so misfired as soon as the model merged duties.
    duties, folded, dropped, origins = _fold_back(
        duties, source_duties, rules, duties_max=duty_limit
    )
    if not duties and source_duties and rewrite.duty_coverage_policy == "fold_back":
        # Nothing to fold into: the model returned no duties at all for a draft that
        # has them. The source's own duties come back whole.
        duties, folded, dropped, origins = list(source_duties), [], [], []
        restored_duties = True
    else:
        restored_duties = False

    # SECTIONS. Three questions, in order:
    # 1. A SECTION the grounded draft does not have cannot be written by the rewrite
    #    (CUPE Phase D): 0.0% of CUPE JDs have a Problem Solving section and 3.1% an
    #    Impact of Decision Making one, because the WJQ form does not ask.
    # 2. A section both have is reconciled PER ITEM against the merge's SAME section
    #    (HR-269/270, 2026-10-20). Until then a section the draft HAD was "left entirely
    #    to the rewrite", and the pilot measured what that let through: "Approves
    #    acquisition, deaccession and loan decisions" (Decision Making, no source states
    #    it), Decision Making 13 -> 5, a WJQ contact list replaced wholesale.
    # 3. A section the merge grounded may not come back EMPTY (HR-214). MEASURED
    #    2026-08-23: the merge grounded `relationships` for 43 of 50 processed clusters
    #    and 11 drafts came back without it (25.6%), against a 90.4% control.
    section_values: dict[str, Any] = {}
    invented_sections: list[str] = []
    for section in _SECTIONS_NEVER_INVENTED:
        if not _has(getattr(source, section)) and _has(getattr(llm_jd, section)):
            section_values[section] = None if section == "relationships" else []
            invented_sections.append(section)
    for section in ("decision_making", "problem_solving"):
        if getattr(source, section) and getattr(llm_jd, section):
            section_values[section] = _reconcile_list(
                section,
                getattr(source, section),
                getattr(llm_jd, section),
                rewrite,
                comparison,
                log,
            )
    if (
        source.relationships is not None
        and llm_jd.relationships is not None
        and _has(source.relationships)
        and _has(llm_jd.relationships)
    ):
        section_values["relationships"] = _reconcile_relationships(
            source.relationships, llm_jd.relationships, rewrite, comparison, log
        )
    restored_sections: list[str] = ["duties"] if restored_duties else []
    if rewrite.sections_never_emptied:
        for section in _SECTIONS_NEVER_INVENTED:
            grounded = getattr(source, section)
            now = section_values.get(section, getattr(llm_jd, section))
            if _has(grounded) and not _has(now) and section not in invented_sections:
                section_values[section] = grounded
                restored_sections.append(section)

    if rewrite.summary_conditions_must_be_grounded:
        summary, foreign = _summary_conditions(
            llm_jd.position_summary, source.position_summary, rules
        )
        if foreign:
            section_values["position_summary"] = summary
            log.scrubbed.extend(("position_summary", s) for s in foreign)

    scrubbed_jd = llm_jd.model_copy(
        update={"qualifications": kept, "duties": duties, **section_values}
    )
    return scrubbed_jd, AntiFabricationRecord(
        enabled=True,
        scrubbed_skills=tuple(scrubbed),
        flagged_duties=tuple(flagged),
        scrubbed_sections=tuple(sorted(invented_sections)),
        removed_duties=tuple(removed_duties),
        invented_duties=tuple(invented_duties),
        restored_bars=tuple(restored_bars),
        restored_sections=tuple(sorted(restored_sections)),
        scrubbed_how_why=tuple(scrubbed_how_why),
        folded_duty_content=tuple(folded),
        folded_duty_origins=tuple(origins),
        dropped_duty_content=tuple(dropped),
        merged_duties=tuple(merged_duties),
        over_form_limit=tuple(over_limit),
        relabelled_qualifications=tuple(relabelled),
        merged_duty_frequency_conflicts=tuple(conflicts),
        scrubbed_items=tuple(log.scrubbed),
        uncovered_items=tuple(log.uncovered),
        restored_items=tuple(log.restored),
        stripped_source_text=stripped,
        stripped_source_parts=stripped_parts,
    )


async def rewrite_merged_role(
    merged: MergedRole, *, client: ChatClient, rules: Rules | None = None
) -> RewrittenDraft:
    """Reword a 4.1 merge draft with the LLM, scrub fabrication, and score it.

    Pure of persistence: no DB, no publish. Returns a frozen ``RewrittenDraft`` — a
    DRAFT (non-negotiable #1), the validator's score/grade/issues, the anti-fab record,
    and the model / prompt / rules provenance.
    """
    active = rules if rules is not None else get_rules()
    rewrite = active.rewrite

    # The prompt states the DRAFT'S OWN FORM's numbers (CUPE Phase D). They used to be
    # inlined in the template as SFU's JDFN guidance — "3–5 major duties", "100–150
    # words" — which was a rulebook fact hardcoded in a prompt, and harmless only for
    # as long as JDFN was the one form the producer ever drafted.
    #
    # 🔴 On a CUPE draft that inlined "3–5" is DESTRUCTIVE, not merely wrong. The WJQ
    # form has twelve duty slots and 77.4% of CUPE JDs fill all twelve, so a rewrite
    # asked for three-to-five duties deletes most of the role — and the anti-fabrication
    # guard cannot catch it, because the guard exists to stop the model ADDING content.
    # Nothing downstream would have flagged the loss: the WJQ profile's `duties_min` is
    # 3, so a five-duty CUPE draft passes its own bar while missing seven duties the
    # source documents actually stated.
    thresholds = active.thresholds_for(template_of(merged.draft))

    # The model reads the SOURCE VIEW (2026-10-20): the merge draft minus the old
    # questionnaire's own instructions and SFU boilerplate (HR-273…HR-276). It is shown
    # nothing the guard would refuse to let it ground, or refuse to restore.
    source, _stripped, _parts = source_view(merged.draft, active)

    # …and the FLOOR is this merge's own, not the form's (HR-209). Phase D fixed the
    # destructive case; this fixes the quiet one. Measured over the five largest
    # all-CUPE clusters on 2026-08-19: 60 merge duties came back as 36, only 10
    # keeping a `frequency`. The form's `duties_min` of 3 licensed the model to
    # compress twelve grounded duties into seven, and nothing downstream objected —
    # the WJQ profile's own floor is 3 (HR-203), so the compressed draft passes its
    # own bar, and the anti-fabrication guard exists to stop the model ADDING.
    #
    # A rewrite is a rewording pass. Handed twelve duties its job is to reword twelve,
    # not to decide how many duties a role has. Capped by `duties_max` so a floor can
    # never ask for more than the form holds, and NOT raised to `duties_min` for a
    # sparse merge: a cluster that grounded two duties has two, and asking for three
    # asks the model to invent one. The validator reports that under-run honestly.
    duties_min = (
        min(len(source.duties), thresholds.duties_max)
        if rewrite.duty_floor_policy == "grounded"
        else thresholds.duties_min
    )

    # We feed the GROUNDED 4.1 draft into the `member_jds` slot, not the raw members.
    prompt = load_prompt(
        rewrite.prompt_version,
        member_count=merged.provenance.member_count,
        skill_frequency=_skill_frequency_lines(merged.provenance.skill_frequency),
        member_jds=outline_jd(source),
        duties_min=duties_min,
        duties_max=thresholds.duties_max,
        summary_min_words=thresholds.summary_min_words,
        summary_max_words=thresholds.summary_max_words,
    )
    # Loose JSON mode + repair retry (the default; NOT constrained decoding). Handing
    # Ollama's structured-output builder the large nested SFUJobDescription grammar 500s
    # it live (`failed to load model vocabulary required for format`), which would drop
    # every rewrite to the deterministic fallback. Loose mode is the ~99% pre-4.6 path;
    # only the audit's small schema opts into `constrain_to_schema` — see
    # ChatClient.chat_json.
    llm_jd = await client.chat_json(
        prompt.messages,
        SFUJobDescription,
        max_tokens=rewrite.max_tokens,
        max_retries=rewrite.max_retries,
    )

    scrubbed_jd, record = _apply_anti_fabrication(llm_jd, merged, active)

    # 🔴 THE MODEL MAY REWORD A DRAFT. IT MAY NOT DELETE FROM IT.
    #
    # Everything outside `_REWRITABLE_FIELDS` comes back from the GROUNDED merge draft,
    # which derived it from the source JDs. This is the anti-fabrication guard's posture
    # applied in the other direction: that guard stops the model ADDING, and until now
    # nothing stopped it REMOVING — which it did, silently, to three different fields in
    # one weekend (see `_REWRITABLE_FIELDS` for the list and how each was found).
    #
    # An ALLOW-LIST rather than another patch, because the deny-list version was wrong
    # three times running: the failure mode is "a field nobody thought about", so only
    # inverting the default makes the next one safe before someone notices it missing.
    scrubbed_jd = merged.draft.model_copy(
        update={field: getattr(scrubbed_jd, field) for field in _REWRITABLE_FIELDS}
    )

    # Boilerplate sections (About SFU, territorial acknowledgement, employment equity)
    # are template-provided, not authored by the rewrite — mark them present so the
    # grade reflects role CONTENT, as hris `jd_bank_task.harmonize_cluster` does. (This
    # differs on purpose from the 4.1 merge draft, which keeps them honest-OR because it
    # is not asserting authored compliance; the rewrite is graded on the wording made.)
    #
    # ⚠ "TEMPLATE-PROVIDED" IS A CLAIM ABOUT A TEMPLATE, so it is only true of the
    # template that provides them (CUPE Phase D). The WJQ form contains no About SFU
    # block, no territorial acknowledgement and no EDI statement — that is the measured
    # fact behind HR-201 — so asserting all three on a CUPE draft would state something
    # about the document that is not so, in the three fields a reviewer is likeliest to
    # take at face value. On a WJQ draft the merge's honest OR stands.
    #
    # It costs no score either way: `applies_to` (Phase B) already withholds the three
    # rules that read these fields from the WJQ, so the assertion was never buying the
    # CUPE cohort anything — it was only making the draft say something untrue.
    if template_of(scrubbed_jd) == DEFAULT_TEMPLATE:
        final_jd = scrubbed_jd.model_copy(
            update={
                "about_sfu_present": True,
                "territorial_acknowledgement_present": True,
                "employment_equity_present": True,
            }
        )
    else:
        final_jd = scrubbed_jd

    issues = evaluate_jd_rules(final_jd, _flatten_jd(final_jd), rules=active)
    score, grade = score_issues(issues, scoring=active.scoring)

    return RewrittenDraft(
        draft=final_jd,
        score=score,
        grade=grade,
        issues=tuple(issues),
        anti_fabrication=record,
        model=rewrite.model,
        prompt_version=prompt.version,
        rules_version=active.version,
    )
