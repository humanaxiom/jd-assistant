"""P0.4 — the production deployment file, and the two lies it exists to stop telling.

P0.2 built a guard that refuses to boot an unsafe production posture. P0.3 established
that this deployment is **internet-facing**. So the deployment that most needs the guard
is the one running without it — and the way it was running would have hidden the guard
even once switched on.

**Lie one: "Up".** ``api`` runs ``uvicorn … --reload``. Measured against this repo's own
image with ``ENVIRONMENT=production`` and five conditions unmet:

============================  ==================================================
``uvicorn … --reload``        prints ``Application startup failed. Exiting.`` and
                              **stays alive** — still running when killed at 45s.
                              The container reads ``Up`` and serves nothing.
``uvicorn …``                 exits **3**, promptly.
============================  ==================================================

The fix is already the image's default: ``core/Dockerfile``'s ``CMD`` carries no
``--reload``. Production does not add a command; it **stops overriding** one. That is
what :func:`test_the_production_api_does_not_override_the_images_command` pins, together
with the Dockerfile end of it — because the guarantee only holds while both are true.

**Lie two: "this is what is deployed".** Fifteen services bind-mount ``./core:/app``, so
the *working tree* is what runs. That is also why this is a **standalone file and not
an overlay**: compose MERGES volume lists, so an overlay declaring ``volumes: []`` still
renders the base mount (measured with ``docker compose config``). The obvious shape
cannot deliver the one property that separates a deployment from a checkout.

── The cost of a standalone file, and how it is paid ────────────────────────────────

Duplication drifts. So the requirements here are **derived from ``docker-compose.yml``**
rather than listed: every service the dev file runs by default, and every environment
key its ``&app_env`` anchor carries, must appear in the production file too. A key added
to the dev anchor tomorrow fails this suite until production carries it — the same shape
as ``test_compose_env_delivery.py`` deriving its required set from a real refusal.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.unit.test_compose_env_delivery import _compose as _dev_compose
from tests.unit.test_compose_env_delivery import _env as _dev_env

#: The production file, in each place this suite can run (see the dev file's note: the
#: `gates` container binds only ./core, so both compose files are mounted at the root).
_CANDIDATE_PATHS = (
    Path("/docker-compose.prod.yml"),
    Path(__file__).resolve().parents[3] / "docker-compose.prod.yml",
)

#: Where the api image's default command lives — the other half of the reloader fix.
_DOCKERFILE_PATHS = (
    Path("/app/Dockerfile"),
    Path(__file__).resolve().parents[2] / "Dockerfile",
)

#: Environment keys the dev anchor carries that production deliberately does NOT, each
#: with the reason. Asserted exactly, so dropping a key is a decision rather than an
#: oversight.
DEV_ONLY_ENV_KEYS: dict[str, str] = {
    # Both are ways to be someone without authenticating. `_unsafe_for_production`
    # already refuses a set CAS_DEV_FAKE_USER, and this file pins it empty rather than
    # interpolating it — there is no value of it that is correct here.
    # (CAS_DEV_FAKE_USER is pinned, not absent, so it appears in the file; nothing is
    # dropped today. This table exists so that the first drop has to argue for itself.)
}


def _prod_compose() -> dict[str, Any]:
    """The parsed production compose file. Raises — never skips — if it is missing.

    A skip is how this whole class of check goes quiet: the file that is not there is
    exactly the file whose absence nobody notices.
    """
    for path in _CANDIDATE_PATHS:
        if path.is_file():
            loaded: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
            return loaded
    raise FileNotFoundError(
        "docker-compose.prod.yml was not found at any of "
        f"{[str(p) for p in _CANDIDATE_PATHS]}. "
        "Inside the `gates` container it is bind-mounted read-only at "
        "/docker-compose.prod.yml; if that mount was removed from the `gates` service, "
        "put it back rather than skipping this test."
    )


def _prod_services() -> dict[str, dict[str, Any]]:
    services: dict[str, dict[str, Any]] = _prod_compose()["services"]
    return services


def _prod_env(service: str) -> dict[str, Any]:
    env: dict[str, Any] = _prod_services()[service].get("environment") or {}
    return env


def _dockerfile() -> str:
    for path in _DOCKERFILE_PATHS:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"Dockerfile not found at {[str(p) for p in _DOCKERFILE_PATHS]}"
    )


def _default_dev_services() -> set[str]:
    """The services the dev file runs with a plain ``up`` — i.e. the deployment. The
    profile-gated ones (`gates`, and every pipeline job) are one-shot tasks, not the
    running system, and the production file deliberately does not repeat them."""
    return {
        name
        for name, service in _dev_compose()["services"].items()
        if not service.get("profiles")
    }


def _settings_bearing(services: dict[str, dict[str, Any]]) -> set[str]:
    """Services that construct :class:`~src.settings.Settings`.

    Keyed on ``ENVIRONMENT`` rather than on "has an ``environment`` block", because
    Postgres and Neo4j have one too — theirs configures the *database image*, not this
    application, and counting them made the first version of this check meaningless.
    """
    return {
        name
        for name, service in services.items()
        if "ENVIRONMENT" in (service.get("environment") or {})
    }


# ── The deployment covers what the dev file runs ─────────────────────────────────


def test_production_runs_every_service_the_dev_file_runs() -> None:
    """Derived, not listed. A new long-running service added to the dev file is part of
    the deployment the moment it exists, and this fails until production carries it."""
    missing = _default_dev_services() - set(_prod_services())

    assert not missing, (
        f"docker-compose.yml runs {sorted(missing)} but docker-compose.prod.yml does "
        "not, so a production deployment silently omits them. Add them here, or move "
        "them behind a `profiles:` key in the dev file if they are not part of the "
        "running system."
    )


def test_production_carries_every_environment_key_the_dev_anchor_does() -> None:
    """The drift this file exists to catch. Two compose files means two lists of
    settings, and the one nobody deploys with is the one that rots.

    A key may be deliberately dropped — but only by naming it in
    :data:`DEV_ONLY_ENV_KEYS` with a reason, which makes the drop reviewable.
    """
    dev_keys = set(_dev_env("api"))
    prod_keys = set(_prod_env("api"))

    missing = dev_keys - prod_keys - set(DEV_ONLY_ENV_KEYS)
    assert not missing, (
        f"docker-compose.prod.yml is missing {sorted(missing)}, which the dev "
        "`&app_env` anchor delivers. A setting absent here falls back to its code "
        "default in production — which for several of these is the value committed to "
        "this repo. Add it, or name it in DEV_ONLY_ENV_KEYS with the reason."
    )


# ── Lie one: the reloader ────────────────────────────────────────────────────────


def test_the_production_api_does_not_override_the_images_command() -> None:
    """Measured: under ``--reload`` a settings refusal leaves the container ``Up`` and
    serving nothing (it printed "Application startup failed. Exiting." and was still
    running at 45s); without it the process exits 3. So production must not supply a
    command at all — the image's own is already correct."""
    assert "command" not in _prod_services()["api"], (
        "the production api overrides the image's command. The image's CMD has no "
        "`--reload`, which is exactly what makes a failed start visible; overriding it "
        "is how that guarantee is lost."
    )


def test_no_production_service_runs_a_reloader() -> None:
    """The general form, over every service — because the next one added is the one
    that copies the dev file's line."""
    offenders = {
        name: service["command"]
        for name, service in _prod_services().items()
        if "--reload" in str(service.get("command", ""))
    }

    assert not offenders, (
        f"{sorted(offenders)} run a reloader in production. A reloader keeps the "
        "parent "
        "process alive when the app fails to start, so the container reports Up while "
        "serving nothing."
    )


def test_the_image_default_command_is_still_reload_free() -> None:
    """The other half. "Production does not override the command" is only a fix while
    the thing it declines to override is correct."""
    dockerfile = _dockerfile()

    cmd = [line for line in dockerfile.splitlines() if line.strip().startswith("CMD")]
    assert cmd, "the Dockerfile declares no CMD, so production has nothing to inherit"
    assert "--reload" not in " ".join(cmd), (
        "the image's default command grew a `--reload`. The production compose file "
        "deliberately does not override the command, so this IS the production command."
    )


# ── Lie two: the working tree ────────────────────────────────────────────────────


def test_no_production_service_mounts_the_source_tree() -> None:
    """The image is what runs. A bind of ``./core`` means the deployment is whatever is
    checked out on the box — including a half-finished edit."""
    offenders: dict[str, list[str]] = {}
    for name, service in _prod_services().items():
        volumes = service.get("volumes") or []
        binds = [str(v) for v in volumes if str(v).startswith("./")]
        source = [b for b in binds if b.split(":")[0] in ("./core", "./core/")]
        if source:
            offenders[name] = source

    assert not offenders, (
        f"{offenders} bind the source tree into the container, so the working tree is "
        "what runs rather than the built image."
    )


def test_the_only_bind_mount_is_the_read_only_artifacts_directory() -> None:
    """``./docs`` is bound because the read-only dashboards render committed pipeline
    artifacts from it. Read-only, and it is the one exception — stated here so a second
    one has to be argued for."""
    for name, service in _prod_services().items():
        for volume in service.get("volumes") or []:
            spec = str(volume)
            if not spec.startswith("./"):
                continue  # a named volume (pgdata / neo4jdata)
            assert spec == "./docs:/docs:ro", (
                f"{name} binds {spec!r}. The only host path production mounts is "
                "./docs, read-only."
            )


# ── Credentials: no defaults, and no committed values ────────────────────────────


#: Settings whose value is a credential or an origin users are sent to. Compose must
#: refuse to render without them (`${VAR:?…}`) rather than fall back to the dev value.
MUST_BE_REQUIRED = (
    "DATABASE_URL",
    "NEO4J_PASSWORD",
    "CAS_SERVICE_BASE_URL",
    "ALLOWED_SERVICE_ORIGINS",
)


@pytest.mark.parametrize("key", MUST_BE_REQUIRED)
def test_a_credential_has_no_default_in_production(key: str) -> None:
    """``${VAR:-default}`` is right in the dev file and wrong here: it is precisely what
    let a deployment run on credentials that are published in git. ``${VAR:?message}``
    aborts the compose command instead."""
    value = str(_prod_env("api")[key])

    # `[A-Z0-9_]+`, not `[A-Z_]+`: NEO4J_PASSWORD has a digit in it, and the narrower
    # class silently failed to match the one credential most worth catching.
    assert re.match(r"^\$\{[A-Z0-9_]+:\?", value), (
        f"{key} is {value!r} in the production file. It must be `${{{key}:?<message "
        "saying what to set and why>}}` so compose refuses to render without it — a "
        "default here is a credential nobody chose."
    )


def test_no_committed_credential_appears_anywhere_in_the_production_file() -> None:
    """Belt to the braces above: the committed values are in git, so grepping for them
    is a check that survives any refactor of how the file is written."""
    raw = ""
    for path in _CANDIDATE_PATHS:
        if path.is_file():
            raw = path.read_text(encoding="utf-8")
            break

    for committed in ("harnesspass", "app:app@postgres"):
        assert committed not in raw, (
            f"the production compose file contains the committed credential "
            f"{committed!r}, which is in git and therefore is not a secret."
        )


# ── The posture is pinned, not merely available ──────────────────────────────────


@pytest.mark.parametrize(
    ("key", "expected"),
    [("ENVIRONMENT", "production"), ("CAS_ENABLED", "true"), ("CAS_DEV_FAKE_USER", "")],
)
def test_the_posture_is_pinned_and_cannot_be_turned_off_by_an_env_var(
    key: str, expected: str
) -> None:
    """These three are what "production" means; interpolating them would let the
    deployment opt out of the mode it just opted into. Everything else stays
    interpolated, because an operator must be able to supply real values."""
    value = _prod_env("api")[key]

    assert str(value) == expected, (
        f"{key} is {value!r} in production; it must be pinned to {expected!r}. "
        "A `${…}` here means the one deployment that needs the guard can disable it."
    )


def test_every_long_running_service_restarts_and_the_api_is_health_checked() -> None:
    """The dev file has **no restart policy at all**, and no healthcheck on the api — so
    a crashed app stays crashed, and a started-but-broken one still reads ``Up``."""
    for name, service in _prod_services().items():
        assert service.get("restart"), f"{name} has no restart policy"

    api = _prod_services()["api"]
    assert api.get("healthcheck"), (
        "the api has no healthcheck, so `Up` means 'the process exists' rather than "
        "'the service answers' — the same class of lie as the reloader."
    )


def test_the_data_stores_stay_on_loopback_in_production() -> None:
    """P0.3 bound these in the dev file; production must not quietly undo it. Here the
    credentials are real, so this is the second line of defence rather than the only
    one — which is a reason to keep it, not to drop it."""
    for name in ("postgres", "neo4j", "redis"):
        for spec in _prod_services()[name].get("ports") or []:
            assert str(spec).startswith(
                "127.0.0.1:"
            ), f"{name} publishes {spec!r} on all interfaces in production."


def test_the_api_binds_to_loopback_by_default() -> None:
    """TLS terminates in front of the app, so the app itself should not be the thing on
    the network. The bind address is overridable (`JD_API_BIND`) because a terminator on
    another host needs that — but the default is the safe one."""
    spec = str(_prod_services()["api"]["ports"][0])

    assert spec.startswith("${JD_API_BIND:-127.0.0.1}:"), (
        f"the api publishes {spec!r}; the default bind address must be loopback, with "
        "the override named so that exposing the app directly is a deliberate act."
    )


def test_the_settings_bearing_services_match_the_dev_files() -> None:  # noqa: D401
    """Every service that constructs ``Settings`` in production carries the full
    environment — a service that inherits nothing gets code defaults, and several of
    those are the committed values."""
    prod = _settings_bearing(_prod_services())

    assert prod == {"api", "worker"}, (
        f"the settings-bearing production services are {sorted(prod)}. If that "
        "changed, "
        "check the new one carries the *app_env anchor rather than a subset."
    )
