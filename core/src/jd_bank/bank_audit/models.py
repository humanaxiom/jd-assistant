"""What a Bank audit reports — counts and ratios only, never JD text.

Frozen, like every other report object in this repo: an audit is an observation, and an
observation that can be edited after the fact is not evidence.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


def _pct(part: int, whole: int) -> float:
    """``part`` as a percentage of ``whole``, 1dp. Zero when there is no denominator —
    NEVER a division by zero and never ``None``, so a caller cannot accidentally render
    "no data" as "0% retained" or crash a report on an empty cohort."""
    if whole <= 0:
        return 0.0
    return round(100.0 * part / whole, 1)


class CarryThrough(BaseModel):
    """One section: how many clusters' SOURCES offered it vs how many DRAFTS kept it.

    **The ratio is the metric; the counts alone are unreadable.** "620 drafts carry
    point-factor content" is either perfect or a catastrophe depending on whether 620 or
    6,490 clusters had any to carry, and the producer's own summary reports neither.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    section: str
    #: Clusters with at least one SOURCE document carrying this section. The honest
    #: denominator: a cluster whose sources are all silent cannot lose anything, and
    #: counting it as a miss would make a perfect run look like a 70% one.
    offered: int = Field(ge=0)
    #: Drafts that carry it now.
    kept: int = Field(ge=0)
    #: The REGISTERED merge policy for this section on this form, where one exists
    #: (HR-169/HR-207/HR-210…HR-212). ``"drop"`` means the Bank is *supposed* to discard
    #: it, so 0% is the correct answer and not a defect — without this the audit's first
    #: run flagged JDFN ``additional_context`` at 0%, which is exactly what HR-169 asks
    #: for. A metric that cannot tell a policy from a bug trains people to ignore it.
    policy: str | None = None

    @property
    def retention_pct(self) -> float:
        """``kept`` as a percentage of ``offered``. **100.0 is the only good answer**
        where the section is meant to be carried — anything less is content the archive
        stated and the Bank dropped."""
        return _pct(self.kept, self.offered)

    @property
    def is_fabrication(self) -> bool:
        """More DRAFTS carry this section than clusters whose SOURCES offered it.

        🔴 THIS IS THE FABRICATION DETECTOR, and it was found by accident: the audit's
        first correct run reported JDFN ``problem_solving`` at **228.2% (1,084 / 475)**,
        which looks like an arithmetic bug and is not. A draft can only carry what its
        sources stated, so a ratio above 100% means the Bank is holding content **no
        source document ever wrote** — the S-5 defect (1,084 JDFN drafts carried a
        section invented from nothing, and scored ~18 points higher for it) stated as a
        single number instead of a five-page argument.

        It is deliberately a SEPARATE reading from :attr:`is_shortfall`. Losing content
        and inventing it are opposite failures with opposite fixes, and a metric that
        collapsed them into "not 100%" would have hidden the more serious one.
        """
        return self.kept > self.offered

    @property
    def is_shortfall(self) -> bool:
        """Whether this reading is a DEFECT, as opposed to a policy or a non-question.

        Three ways to be neither, and each was a false alarm on the first live run:
        nothing was offered (``0/0`` — no CUPE source states Problem Solving, so there
        is nothing to keep); the policy is ``drop`` (the Bank is doing what it was
        told);
        or everything offered was kept.
        """
        return (
            bool(self.offered) and self.policy != "drop" and self.retention_pct < 100.0
        )


class RewriteHealth(BaseModel):
    """What the LLM rewrite did to a form's duties — including the controlled comparison
    that separates "the model did this" from "the data was always like that".

    A rewrite FAILURE falls back to the deterministic merge, so those drafts are the
    same
    pipeline with the model removed. They are the control group, and the Bank produces
    them for free.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rewritten_duties: int = Field(ge=0)
    rewritten_with_frequency: int = Field(ge=0)
    merge_only_duties: int = Field(ge=0)
    merge_only_with_frequency: int = Field(ge=0)
    duties_total: int = Field(ge=0)
    duties_flagged: int = Field(ge=0)
    drafts: int = Field(ge=0)
    drafts_with_a_flagged_duty: int = Field(ge=0)

    @property
    def rewritten_frequency_pct(self) -> float:
        return _pct(self.rewritten_with_frequency, self.rewritten_duties)

    @property
    def merge_only_frequency_pct(self) -> float:
        """The CONTROL. If this is far above :attr:`rewritten_frequency_pct`, the
        rewrite is destroying a field the deterministic merge preserves — which is a
        defect in the rewrite, not a property of the archive."""
        return _pct(self.merge_only_with_frequency, self.merge_only_duties)

    @property
    def flagged_duty_pct(self) -> float:
        return _pct(self.duties_flagged, self.duties_total)

    @property
    def drafts_flagged_pct(self) -> float:
        """Share of drafts carrying at least one flagged duty. **Approaching 100% means
        the flag has stopped being a signal and become a constant** — the pathology this
        repo has now hit on three separate findings."""
        return _pct(self.drafts_with_a_flagged_duty, self.drafts)


class GateBlock(BaseModel):
    """One gate, and how many of a form's drafts it blocks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_id: str
    drafts: int = Field(ge=0)


class FormAudit(BaseModel):
    """One FORM's drafts. Never merged with the other's — a mean across two forms is a
    mean across two different measurements (CUPE Phase D)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    template: str
    drafts: int = Field(ge=0)
    mean_score: float = Field(ge=0, le=100)
    mean_duties: float = Field(ge=0)
    approvable: int = Field(ge=0)
    carry_through: tuple[CarryThrough, ...] = ()
    rewrite: RewriteHealth
    blocking_gates: tuple[GateBlock, ...] = ()


class BankAudit(BaseModel):
    """The whole report. **There is deliberately no overall score or overall retention
    field** — the same rule the producer result follows: if a blended number does not
    exist, nobody can quote one."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    documents_parsed: int = Field(ge=0)
    published: int = Field(ge=0)
    forms: tuple[FormAudit, ...] = ()
