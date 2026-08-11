"""FastAPI application — task API, gate status, memory queries.

**Authorization lives here**, at the mount points: every router below is included with
the dependency that decides who may reach it, and the legacy harness routes further
down carry theirs per route. ``tests/unit/test_authorization_matrix.py`` holds the table
of record and fails if a route is served without an entry — a new route must not ship
without an access decision.

**CSRF lives here too, but one level up** (P0.1b-i): :func:`src.api.csrf.enforce_csrf`
is an *application-wide* dependency, not a per-router one, because the rule it enforces
is a property of the request (*"a state change authenticated by a session cookie must
carry that session's token"*) and not of a route. Mounted at the app, it covers a route
added tomorrow with nobody having to remember it exists — there is no allow-list here to
drift out of step with the routing table. Scoping it to the browser surface would have
been a real hole and not a hypothetical one: ``POST /gates/run`` takes ``branch`` as a
**query parameter with no body**, so an ordinary cross-site form with an admin's cookie
enqueued an arq job.

:class:`~src.api.security_headers.SecurityHeadersMiddleware` is mounted for the same
feature's sake — a framed review page carries its own valid token, so clickjacking
borrows the CSRF control rather than bypassing it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.csrf import enforce_csrf
from src.api.db.models import Role
from src.api.deps import current_user, require_roles
from src.api.readiness import router as readiness_router
from src.api.security_headers import SecurityHeadersMiddleware
from src.memory.graph import GraphMemory
from src.models.db import Task, TaskStatus
from src.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    app.state.engine = create_async_engine(s.database_url)
    app.state.sessionmaker = async_sessionmaker(
        app.state.engine, expire_on_commit=False
    )
    app.state.arq = await create_pool(RedisSettings.from_dsn(s.redis_url))
    app.state.memory = GraphMemory()
    yield
    await app.state.memory.close()
    await app.state.arq.close()
    await app.state.engine.dispose()


# `dependencies=` on the app applies to EVERY route this app serves, including the ones
# included below with their own gates — an app-level dependency is solved BEFORE the
# route's own, so the CSRF check runs ahead of the handler and ahead of any effect. A
# `GET`, and a request carrying no session cookie, both pass straight through; see
# src/api/csrf.py.
app = FastAPI(
    title="JD Bank API",
    version="2.0.0",
    lifespan=lifespan,
    dependencies=[Depends(enforce_csrf)],
)
# Clickjacking defeats token CSRF outright (a framed page carries its own valid token),
# so the headers that prevent framing ship with the CSRF feature. Raw ASGI, not
# BaseHTTPMiddleware — nothing upstream of these handlers may re-wrap the request body.
app.add_middleware(SecurityHeadersMiddleware)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with app.state.sessionmaker() as session:
        yield session


# ── Schemas ────────────────────────────────────────────────────────────────


class TaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    spec: str = Field(min_length=10)


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    status: TaskStatus
    branch: str | None

    model_config = {"from_attributes": True}


# ── Routes ─────────────────────────────────────────────────────────────────
#
# These are the INHERITED HARNESS API (agent tasks, the `run_pipeline` arq job, agent
# memory) — no JD Bank surface calls them. They write, enqueue work and read the agent
# memory graph, none of which belongs to an anonymous caller in an HR service, so they
# are **admin-only**. They are gated rather than deleted: `POST /tasks` is the entry
# point to the vendored subagents pipeline (CLAUDE.md §Subagents), and removing a
# subsystem's entry point is a bigger decision than a security fix should make on its
# own. Whether the harness API belongs in this service at all is a separate question.
#
# `/health` and `/ready` alone stay public: they are the probes, and must answer
# before — and whether or not — anyone can sign in.

#: The gate for every legacy harness route. One name so a new one cannot be added at a
#: different (or no) access level by accident.
_HARNESS_ADMIN = [Depends(require_roles(Role.ADMIN))]


@app.get("/health")
async def health() -> dict[str, str]:
    """LIVENESS — static, and it must stay that way.

    An orchestrator restarts the container when this fails, so a dependency check here
    would turn a Neo4j blip into a simultaneous restart of every healthy pod. Dependency
    health is `/ready` (src/api/readiness.py); `tests/unit/test_api.py` pins that this
    handler touches no `app.state` at all.
    """
    return {"status": "ok"}


# READINESS — public like `/health` (the poller has no cookie) but, unlike it, actually
# asks Postgres/Neo4j/Redis whether they are answering. Ungated on purpose; its body is
# a fixed vocabulary and never a DSN, host or driver error. See src/api/readiness.py.
app.include_router(readiness_router)


@app.post(
    "/tasks", response_model=TaskOut, status_code=201, dependencies=_HARNESS_ADMIN
)
async def create_task(
    payload: TaskCreate, session: AsyncSession = Depends(get_session)
) -> Task:
    """Create a task, generate its agent branch, and enqueue the pipeline."""
    task = Task(title=payload.title, spec=payload.spec, status=TaskStatus.PENDING)
    slug = "-".join(payload.title.lower().split()[:4])
    session.add(task)
    await session.flush()
    task.branch = f"agent/{str(task.id)[:8]}-{slug}"
    await session.commit()

    await app.state.arq.enqueue_job(
        "run_pipeline",
        task_id=str(task.id),
        task_spec=payload.spec,
        branch=task.branch,
    )
    return task


@app.get("/tasks/{task_id}", response_model=TaskOut, dependencies=_HARNESS_ADMIN)
async def get_task(
    task_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> Task:
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    return task


@app.get("/tasks/{task_id}/lineage", dependencies=_HARNESS_ADMIN)
async def task_lineage(task_id: uuid.UUID) -> list[dict[str, Any]]:
    """Neo4j lineage: subtasks, agents, artifacts for a task."""
    result = await app.state.memory.task_lineage(str(task_id))
    return cast("list[dict[str, Any]]", result)


@app.get("/memory/similar", dependencies=_HARNESS_ADMIN)
async def similar(q: str, k: int = 5) -> list[dict[str, Any]]:
    """Vector search over prior artifacts."""
    result = await app.state.memory.similar_artifacts(q, k=k)
    return cast("list[dict[str, Any]]", result)


@app.post("/gates/run", dependencies=_HARNESS_ADMIN)
async def run_gates(branch: str) -> dict[str, str]:
    job = await app.state.arq.enqueue_job("run_gates_job", branch=branch)
    return {"job_id": job.job_id}


# Imported here (not with the top-of-file imports) because the router imports
# `get_session` back from this module — importing it at the top would be circular.
from src.api.routes.admin import router as jd_bank_admin_router  # noqa: E402
from src.api.routes.auth import (  # noqa: E402
    RedirectToLogin,
    require_ui_roles,
    require_ui_user,
)
from src.api.routes.auth import router as jd_bank_auth_router  # noqa: E402
from src.api.routes.compose import router as jd_bank_compose_router  # noqa: E402
from src.api.routes.compose_ui import router as jd_bank_compose_ui_router  # noqa: E402
from src.api.routes.dashboard import router as jd_bank_dashboard_router  # noqa: E402
from src.api.routes.guide import router as jd_bank_guide_router  # noqa: E402
from src.api.routes.jd_bank import router as jd_bank_router  # noqa: E402
from src.api.routes.library import router as jd_bank_library_router  # noqa: E402
from src.api.routes.ui import router as jd_bank_ui_router  # noqa: E402

# Auth routes (login/logout/CAS) are ungated — the login page and the CAS legs must be
# reachable by a visitor who has no session yet, and logout must work for an expired
# one (it revokes only the caller's own cookie-identified session).
app.include_router(jd_bank_auth_router)
# The JSON review API is the same NN #1 approval surface as the review UI, so it takes
# the same roles — but `require_roles`, not `require_ui_roles`: an API client must get
# 401/403, never a 303 to an HTML login page. Reads are gated too; a review packet is
# unpublished draft JD content. (P0.1a: this router shipped with NO gate at all, and
# took its `reviewer_id` from the request body — see routes/jd_bank.py.)
app.include_router(
    jd_bank_router,
    dependencies=[Depends(require_roles(Role.REVIEWER, Role.ADMIN))],
)
# The review queue is the NN #1 human-approval surface — reviewer or admin only.
app.include_router(
    jd_bank_ui_router,
    dependencies=[Depends(require_ui_roles(Role.REVIEWER, Role.ADMIN))],
)
# The content library (browse/read roles + source JDs) is read-only — any signed-in
# user (redirect if not). It never publishes; approval stays on the reviewer queue.
app.include_router(jd_bank_library_router, dependencies=[Depends(require_ui_user)])
# Dashboards, the guide + the Builder require any authenticated user (redirect if not).
app.include_router(jd_bank_dashboard_router, dependencies=[Depends(require_ui_user)])
app.include_router(jd_bank_guide_router, dependencies=[Depends(require_ui_user)])
# The JSON compose API mirrors the Builder UI's access — any signed-in user — but with
# the JSON gate (`current_user` -> 401), not the redirecting UI one. Nothing publishes
# here; it does disclose archive JD content and drive the self-hosted LLM.
app.include_router(jd_bank_compose_router, dependencies=[Depends(current_user)])
app.include_router(jd_bank_compose_ui_router, dependencies=[Depends(require_ui_user)])
# User management — admin only.
app.include_router(
    jd_bank_admin_router, dependencies=[Depends(require_ui_roles(Role.ADMIN))]
)


@app.exception_handler(RedirectToLogin)
async def _redirect_to_login(request: Any, exc: RedirectToLogin) -> Any:
    """Turn an unauthenticated UI request (``require_ui_user``) into a 303 redirect to
    the login page, carrying where the visitor was heading so login can bounce back."""
    from urllib.parse import urlencode

    from fastapi.responses import RedirectResponse

    target = f"/jd-bank/ui/login?{urlencode({'next': exc.next_path})}"
    return RedirectResponse(url=target, status_code=303)
