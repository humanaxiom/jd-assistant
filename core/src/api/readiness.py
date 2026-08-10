"""``GET /ready`` — dependency readiness, split off from liveness (P0.2).

``/health`` is a **liveness** probe: an orchestrator polls it on a short interval and
*restarts the container* when it fails. Checking Postgres/Neo4j/Redis inside it would
therefore invert what it is for — a Neo4j blip would kill every healthy API pod at
once, escalating a degraded dependency into a full outage. So ``/health`` stays static
(pinned in ``tests/unit/test_api.py``) and dependency health lives here.

**Public, and detail-free.** Public because the caller is an orchestrator or a load
balancer with no session cookie; a probe that could only ever answer 401 is not a health
signal. Safe because the body is a fixed vocabulary — a dependency name and one of two
words — never a DSN, a host, a port, a username or a driver's exception text::

    200  {"status": "ok",       "checks": {"postgres": "ok",   "neo4j": "ok", ...}}
    503  {"status": "degraded", "checks": {"postgres": "down", "neo4j": "ok", ...}}

The failure is *classified* into that vocabulary and the exception is **logged**, where
an operator with access to the container can read it; it is never served.

**Every probe is bounded** (:data:`PROBE_TIMEOUT_SECONDS`), and the probes run
concurrently, so the whole endpoint is bounded too. "Down" and "hanging" are different
failures and only one of them is easy: a refused connection raises at once, while a host
that has silently vanished leaves the driver waiting on a socket. An unbounded probe
turns the readiness endpoint into a casualty of the outage it exists to report — the
same defect class as the Phase 5.9 embed timeout.

The probe set is a FastAPI dependency (:func:`get_probes`) so it can be overridden in a
test without Postgres, Neo4j and Redis — the convention the dashboards already use for
``get_baseline_summary_path``. A probe is ``async () -> None``: it returns on success
and raises on failure.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

logger = logging.getLogger(__name__)

router: APIRouter = APIRouter()

#: The per-probe budget, in seconds. A named constant rather than a magic number inside
#: a ``wait_for`` call: it is an ops parameter someone will want to find and reason
#: about. Long enough for a healthy round-trip on a loaded box, short enough that the
#: probes cannot outlast an orchestrator's own probe timeout.
PROBE_TIMEOUT_SECONDS = 2.0

#: ``async () -> None`` — returns if the dependency answered, raises if it did not.
Probe = Callable[[], Awaitable[None]]


def get_probes(request: Request) -> dict[str, Probe]:
    """The real probe set: one per dependency the API cannot serve a request without.

    Each probe reads ``app.state`` **when it is called**, not now — the lifespan is what
    puts the engine, the arq pool and the graph driver there, and building the set must
    not require them to exist yet (a missing one is simply a "down").
    """
    app = request.app

    async def postgres() -> None:
        async with app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def neo4j() -> None:
        await app.state.memory.verify_connectivity()

    async def redis() -> None:
        await app.state.arq.ping()

    return {"postgres": postgres, "neo4j": neo4j, "redis": redis}


async def _probe_succeeded(name: str, probe: Probe) -> bool:
    """Run one probe inside its budget. A timeout is a "down", not a stall.

    Broad ``except`` on purpose: every failure mode of a driver — refused connection,
    auth rejection, DNS, a timeout — is the same fact to a caller of this endpoint, and
    the exception text (which routinely carries the DSN and the username) must not be
    allowed to escape into the classification. It goes to the log instead.
    """
    try:
        await asyncio.wait_for(probe(), timeout=PROBE_TIMEOUT_SECONDS)
    except Exception as exc:
        # The TYPE, not only the text: `asyncio.TimeoutError` stringifies to the empty
        # string, so logging `exc` alone renders "…failed:" and nothing — in the one
        # case (hung, not refused) where an operator most needs to know which it was.
        logger.warning(
            "readiness probe %r failed: %s: %s", name, type(exc).__name__, exc
        )
        return False
    return True


@router.get("/ready")
async def ready(
    probes: Annotated[dict[str, Probe], Depends(get_probes)],
) -> JSONResponse:
    """Report every dependency's state — all of them, not only the first failure."""
    names = list(probes)
    results = await asyncio.gather(
        *(_probe_succeeded(name, probes[name]) for name in names)
    )
    checks = {
        name: ("ok" if ok else "down") for name, ok in zip(names, results, strict=True)
    }
    healthy = all(results)
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )
