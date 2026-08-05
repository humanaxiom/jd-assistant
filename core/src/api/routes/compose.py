"""JD Builder — compose routes (Phases 5.1 + 5.5 + 5.7 + 5.4).

Endpoints under ``/jd-bank/compose``:

* ``POST /validate`` (5.1) — score an in-progress draft and return its
  :class:`~src.jd_bank.composer.DraftAssessment` (the live compliance panel).
* ``POST /assist/summary`` (5.5) — ask the self-hosted LLM to improve the Position
  Summary and return a :class:`~src.jd_bank.composer.SummarySuggestion` (decision
  support; the author accepts or discards it).
* ``POST /export`` (5.7) — render a draft to the official SFU ``.docx`` for download.
* ``GET /search`` (5.4) — semantic search for an existing JD to start from.
* ``GET /clone/{source_document_id}`` (5.4) — the guided-authoring answers to
  pre-fill the Builder from a chosen existing JD.

**Nothing publishes here (NN #1);** authoring is read-only until a draft is submitted
to the review queue (5.6). ``/validate`` and ``/export`` are pure and DB-free. The LLM /
embedding / Neo4j clients are built via injectable factories (so tests substitute fakes
and no network is hit) — the content clients are egress-guarded at construction (NN #5)
and closed after the call.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from neo4j import AsyncDriver, AsyncGraphDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.main import get_session
from src.jd_bank.composer import (
    ComposerAnswers,
    DraftAssessment,
    SearchHit,
    SummarySuggestion,
    assess_draft,
    load_clone_answers,
    search_similar_jds,
    suggest_summary,
)
from src.jd_bank.embeddings.client import EmbedClient
from src.jd_bank.llm.client import ChatClient
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_export import render_sfu_docx
from src.settings import get_settings

logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/jd-bank/compose")

#: The OOXML ``.docx`` media type.
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _filename(title: str) -> str:
    """A safe download filename from the JD title (lowercase, hyphenated)."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{slug or 'job-description'}.docx"


def get_chat_client() -> ChatClient:
    """The LLM client for the assist route, as a FastAPI dependency so a test can
    override it with :attr:`app.dependency_overrides` (no network). The real client is
    egress-guarded at construction (NN #5) and bound to ``rules.rewrite.model``."""
    return ChatClient()


def get_embed_client() -> EmbedClient:
    """The embedding client for search — injectable (tests substitute a fake).
    Egress-guarded at construction (NN #5); bound to ``rules.embeddings.model``."""
    return EmbedClient()


def get_neo4j_driver() -> AsyncDriver:
    """The Neo4j driver for the vector-index search — injectable (tests substitute a
    fake). A driver is cheap to create per request and closed after."""
    settings = get_settings()
    return AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )


def get_optional_embed_client() -> EmbedClient | None:
    """:func:`get_embed_client`, but a construction failure is ``None`` instead of a
    dead endpoint — for routes where the client powers an ADVISORY extra.

    Both factories above raise at CONSTRUCTION on a misconfiguration:
    :class:`~src.jd_bank.embeddings.client.EmbedClient` runs the egress guard (NN #5)
    in ``__init__``, and the Neo4j driver rejects a bad URI scheme. FastAPI solves
    dependencies BEFORE the route body runs, so on the routes that merely *decorate* a
    response with an embedding-powered panel that raise takes the whole page down —
    the JD Builder losing its compliance panel because an environment variable points
    at the wrong host.

    So: caught, **logged with a stack trace**, and returned as ``None`` — the
    "no clients" call :func:`~src.jd_bank.composer.duplicates.find_related_roles`
    already supports. The page renders, the advisory panel is ABSENT (never a falsely
    reassuring "no matches"), and the misconfiguration is on the server's record
    instead of being normalised into silence. Routes whose whole purpose IS the
    embedding — ``/search``, ``/assist`` — keep the strict factories and keep failing
    loudly, because there a degraded answer would be a lie about the archive.
    """
    try:
        return get_embed_client()
    except Exception:
        logger.exception(
            "embedding client unavailable — the advisory near-duplicate panel will be "
            "omitted from this response; check OLLAMA_BASE_URL / the egress allow-list"
        )
        return None


def get_optional_neo4j_driver() -> AsyncDriver | None:
    """:func:`get_neo4j_driver`, degrading to ``None`` — see
    :func:`get_optional_embed_client` for why the advisory routes cannot let a
    construction failure escape into dependency solving."""
    try:
        return get_neo4j_driver()
    except Exception:
        logger.exception(
            "Neo4j driver unavailable — the advisory near-duplicate panel will be "
            "omitted from this response; check NEO4J_URI"
        )
        return None


@router.post("/validate", response_model=DraftAssessment)
async def validate_draft(jd: SFUJobDescription) -> DraftAssessment:
    """Score an in-progress draft against the SFU rulebook and return the live
    compliance assessment (findings split into guidance vs fix-these)."""
    return assess_draft(jd)


@router.post("/assist/summary", response_model=SummarySuggestion)
async def assist_summary(
    jd: SFUJobDescription,
    client: ChatClient = Depends(get_chat_client),
) -> SummarySuggestion:
    """Suggest an improved Position Summary (LLM, self-hosted), re-validated. The
    author decides whether to accept it; nothing auto-applies or publishes (NN #1)."""
    try:
        return await suggest_summary(jd, client=client)
    finally:
        await client.close()


@router.post("/export")
async def export_docx(jd: SFUJobDescription) -> Response:
    """Render a draft to the official SFU ``.docx`` and return it as a download.
    Pure rendering — nothing is validated or published (NN #1)."""
    content = render_sfu_docx(jd)
    return Response(
        content=content,
        media_type=_DOCX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{_filename(jd.title)}"'
        },
    )


@router.get("/search", response_model=list[SearchHit])
async def search(
    q: str,
    limit: int = 10,
    embed_client: EmbedClient = Depends(get_embed_client),
    neo4j_driver: AsyncDriver = Depends(get_neo4j_driver),
    session: AsyncSession = Depends(get_session),
) -> list[SearchHit]:
    """Semantic search for existing JDFN JDs like ``q``, to start a draft from."""
    try:
        return await search_similar_jds(
            q,
            embed_client=embed_client,
            neo4j_driver=neo4j_driver,
            session=session,
            limit=limit,
        )
    finally:
        await embed_client.close()
        await neo4j_driver.close()


@router.get("/clone/{source_document_id}", response_model=ComposerAnswers)
async def clone(
    source_document_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ComposerAnswers:
    """The guided-authoring answers to pre-fill the Builder from an existing JD. 404 if
    the document has no parsed JD to clone."""
    answers = await load_clone_answers(session, source_document_id)
    if answers is None:
        raise HTTPException(status_code=404, detail="no parsed JD to clone")
    return answers
