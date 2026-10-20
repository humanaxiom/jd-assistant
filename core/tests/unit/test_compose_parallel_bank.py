"""P-stack — a second, fully isolated JD Bank can run beside the live one.

Owner, 2026-10-20: *"Let us create a new bank for v9. Leave the existing database
alone. A complete new set of images for this build."* A second Bank runs from its own
checkout with a git-ignored ``.env`` naming its own ``COMPOSE_PROJECT_NAME``,
``JD_IMAGE_TAG`` and ``JD_*_PORT`` block. Compose reads that ``.env`` natively, so the
isolation is a property of ``docker-compose.yml`` and of the committed example — both of
which are data, asserted here without Docker.

What broke before this file existed: ``api``/``worker`` were pinned to
``jd-bank-api:latest`` / ``jd-bank-worker:latest``. A second checkout building under ANY
project name overwrote the live images, and the next ``up`` of the live stack would
have run the other checkout's dependencies. The scripts' guard (refusing to act on a
project another checkout owns) is tested in ``deploy/tests/bank-target.tests.ps1``,
which ``make deploy-check`` runs — it is PowerShell and cannot run in this container.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_COMPOSE_PATHS = (
    Path("/docker-compose.yml"),
    Path(__file__).resolve().parents[3] / "docker-compose.yml",
)
#: Bind-mounted read-only into `gates` beside the compose file (see the `gates` service).
_EXAMPLE_PATHS = (
    Path("/parallel-bank.env.example"),
    Path(__file__).resolve().parents[3] / "deploy" / "parallel-bank.env.example",
)

#: The LIVE Bank's identity. A second Bank must differ from it in every one of these.
LIVE_PROJECT = "jd-bank"
LIVE_TAG = "latest"

#: The services that RUN from our image in a normal `up` — the ones whose image a
#: second checkout's build would otherwise overwrite.
LONG_RUNNING_BUILT = ("api", "worker")

PORT_KEYS = (
    "JD_API_PORT",
    "JD_PG_PORT",
    "JD_NEO4J_HTTP_PORT",
    "JD_NEO4J_BOLT_PORT",
    "JD_REDIS_PORT",
)


def _first_existing(paths: tuple[Path, ...], what: str) -> Path:
    for path in paths:
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"{what} was not found at any of {[str(p) for p in paths]}. Inside the `gates` "
        "container it is bind-mounted read-only; if that mount was removed, put it back "
        "rather than skipping this test."
    )


def _compose_text() -> str:
    return _first_existing(_COMPOSE_PATHS, "docker-compose.yml").read_text(encoding="utf-8")


def _compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(_compose_text())
    return loaded


def _example() -> dict[str, str]:
    """The committed example `.env`, parsed the way compose parses a simple `.env`."""
    text = _first_existing(_EXAMPLE_PATHS, "deploy/parallel-bank.env.example").read_text(
        encoding="utf-8"
    )
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        assert sep, f"not a KEY=VALUE line in the example: {raw!r}"
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _compose_port_defaults() -> dict[str, str]:
    """`${JD_X_PORT:-NNNN}` -> {JD_X_PORT: NNNN}, read from the compose file itself."""
    return dict(re.findall(r"\$\{(JD_[A-Z0-9_]+_PORT):-(\d+)\}", _compose_text()))


@pytest.mark.parametrize("service", LONG_RUNNING_BUILT)
def test_the_app_image_tag_is_parameterised(service: str) -> None:
    """The tag, and only the tag, follows `JD_IMAGE_TAG`; the default is the live tag.

    The NAME stays pinned (`jd-bank-<service>`) — `deploy-check` requires image names
    not to depend on the compose PROJECT, so a bundle installs under any project.
    """
    image = _compose()["services"][service]["image"]

    assert image == f"jd-bank-{service}:${{JD_IMAGE_TAG:-{LIVE_TAG}}}", (
        f"{service} must be `jd-bank-{service}:${{JD_IMAGE_TAG:-latest}}`; got {image!r}. "
        "A literal tag means a second Bank's build overwrites the live images."
    )


def test_the_default_project_is_still_the_live_one() -> None:
    """No `.env` -> the live project. The second Bank opts IN; the live one never moves."""
    assert _compose()["name"] == LIVE_PROJECT


def test_every_built_long_running_service_names_its_image() -> None:
    """A long-running service built from our Dockerfile without an `image:` would be
    named `<project>-<service>` — portable to nothing (deploy-check) and invisible to the
    tag. Tool services (profile `tools`) are exempt: compose's default already isolates
    them per project, and the bundle does not ship them."""
    services = _compose()["services"]
    offenders = [
        name
        for name, svc in services.items()
        if "build" in svc
        and "tools" not in (svc.get("profiles") or [])
        and "${JD_IMAGE_TAG" not in str(svc.get("image", ""))
    ]
    assert not offenders, f"built services with no tagged image: {offenders}"


def test_gates_reaches_the_data_stores_by_service_name_not_a_host_port() -> None:
    """`make smoke` in a second checkout must hit THAT checkout's Postgres. Addressing by
    compose service name resolves on the project's own network; a `localhost:<port>` or
    host-gateway DSN would reach whichever Bank owns that port — the live one."""
    env = _compose()["services"]["gates"]["environment"]
    assert "@postgres:5432/" in env["DATABASE_URL"]
    assert env["NEO4J_URI"] == "bolt://neo4j:7687"
    assert env["REDIS_URL"].startswith("redis://redis:6379")


def test_the_example_names_a_different_project_and_tag() -> None:
    example = _example()

    assert example["COMPOSE_PROJECT_NAME"] not in ("", LIVE_PROJECT)
    assert example["JD_IMAGE_TAG"] not in ("", LIVE_TAG)


def test_the_example_claims_every_port_and_none_collides_with_the_live_stack() -> None:
    example = _example()
    defaults = _compose_port_defaults()

    assert set(PORT_KEYS) <= set(defaults), f"compose no longer publishes {PORT_KEYS}"
    missing = [k for k in PORT_KEYS if k not in example]
    assert not missing, f"the example leaves {missing} on the LIVE stack's default port"
    collisions = {k: example[k] for k in PORT_KEYS if example[k] == defaults[k]}
    assert not collisions, f"the example reuses the live stack's ports: {collisions}"
    assert len({example[k] for k in PORT_KEYS}) == len(PORT_KEYS), "duplicate ports"


def test_the_example_sends_cas_back_to_its_own_port_and_ships_cas_off() -> None:
    """The live `.env` is never edited for the second Bank, so the second Bank's own
    `.env` must carry a CAS return origin on ITS port — otherwise a login on the second
    Bank is returned to the live one."""
    example = _example()
    own = f"http://localhost:{example['JD_API_PORT']}"

    assert example["CAS_ENABLED"] == "false"
    assert example["CAS_SERVICE_BASE_URL"] == own
    assert example["ALLOWED_SERVICE_ORIGINS"] == own
