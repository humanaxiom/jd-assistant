"""Phase 5.5 — LLM authoring assist (suggest an improved Position Summary).

Validator-as-oracle (NN #3): the tests assert the VALIDATOR's verdict on the draft the
suggestion would produce — its word count, its section state — never the model's exact
words (the fake supplies those). The LLM client is a fake, so no network is hit and the
assist's own wiring (prompt → reply → re-validate → grounding) is what is under test.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes import compose
from src.jd_bank.composer import suggest_summary
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)


class _FakeChat:
    """Stands in for the whole ``ChatClient`` — returns a FIXED summary as the reply
    model, and records that it was closed. The client's own discipline (retry, egress
    guard, JSON repair) is proved in the 4.2 client tests, not re-proved here."""

    def __init__(self, summary: str) -> None:
        self._summary = summary
        self.closed = False

    async def chat_json(
        self,
        messages: object,
        model_cls: type[Any],
        *,
        max_tokens: int,
        max_retries: int,
    ) -> Any:
        return model_cls(summary=self._summary)

    async def close(self) -> None:
        self.closed = True


def _draft() -> SFUJobDescription:
    """A fully-authored draft whose only weakness is a too-short summary."""
    return SFUJobDescription(
        title="Software Developer",
        employee_group="apsa",
        about_sfu_present=True,
        position_summary="Too short.",
        duties=[
            SFUDuty(action_verb=v, statement=f"{v} the widget program")
            for v in ("Manages", "Coordinates", "Provides")
        ],
        decision_making=["Approves expenditures up to $5k"],
        problem_solving=["Resolves scheduling conflicts independently"],
        relationships=SFURelationships(supervisory="Supervises 2 staff"),
        qualifications=[
            SFUQualification(
                text="Bachelor's degree or an equivalent combination of experience",
                kind="education",
            ),
            SFUQualification(text="Ability to work cooperatively", kind="ability"),
        ],
        territorial_acknowledgement_present=True,
        employment_equity_present=True,
    )


def _section(assessment: Any, name: str) -> Any:
    return next(s for s in assessment.sections if s.section == name)


async def test_suggestion_is_the_validators_verdict_on_the_new_summary() -> None:
    # A 120-word summary (in the SFU 100-150 range) built from the draft's own words.
    summary = " ".join(["widget", "program"] * 60)  # 120 words, all grounded
    suggestion = await suggest_summary(_draft(), client=_FakeChat(summary))

    assert suggestion.word_count == 120
    assert suggestion.assessment.summary_word_count == 120
    # The validator now sees a compliant summary section (post-state, not the words).
    assert _section(suggestion.assessment, "position_summary").state == "ok"
    assert suggestion.prompt_version == "jd_compose_summary_v1"


async def test_grounding_flags_a_fabricated_summary() -> None:
    grounded = await suggest_summary(
        _draft(), client=_FakeChat(" ".join(["widget", "program"] * 60))
    )
    fabricated = await suggest_summary(
        _draft(), client=_FakeChat(" ".join(["zebra", "helicopter"] * 60))
    )
    assert grounded.grounded_fraction == 1.0
    assert fabricated.grounded_fraction == 0.0


async def test_suggest_does_not_mutate_the_input_draft() -> None:
    draft = _draft()
    await suggest_summary(draft, client=_FakeChat("a better summary here"))
    assert draft.position_summary == "Too short."


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def test_assist_route_returns_a_suggestion_and_closes_the_client() -> None:
    fake = _FakeChat(" ".join(["widget", "program"] * 60))
    app.dependency_overrides[compose.get_chat_client] = lambda: fake
    client = TestClient(app)  # no lifespan; the route needs no DB

    resp = client.post(
        "/jd-bank/compose/assist/summary",
        json={"title": "Software Developer", "position_summary": "Too short."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["word_count"] == 120
    assert body["assessment"]["summary_word_count"] == 120
    assert fake.closed is True
