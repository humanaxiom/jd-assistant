"""P0.2 — the production startup invariant: the unsafe posture must fail closed.

``settings.py`` has claimed, in a comment, since ADR-008 that *"a startup check refuses
``cas_enabled`` + a dev-fake user together"*. **No such check was ever written.** Worse,
the *shipped default* is ``cas_enabled=False``, and with it
:func:`src.api.deps.resolve_user` short-circuits **before reading any cookie** and hands
back a transient user holding ``cas_dev_default_role`` — ``admin``. P0.1a gated the JSON
API; those gates only bind when CAS is on. This file pins the other half: a deployment
that *says* it is production may not boot in the unsafe posture.

**Where the check lives, and why here rather than in the FastAPI lifespan.** Every test
below asserts that constructing :class:`~src.settings.Settings` itself refuses. The API
is not the only thing that reads these settings: ``ingest``, ``embed``, ``embed-roles``,
``near-dup``, ``dedup-role``, ``cluster``, ``harmonize``, ``canonical`` and the arq
worker are all separate compose services that never run the API's lifespan, and they
open the same Postgres, the same Neo4j and the same Ollama endpoint. A lifespan-only
check would leave every one of them unguarded. Refusing at settings load is the one
place that covers all of them, and it is also what makes the failure a **non-zero exit**
(see :func:`test_a_production_boot_with_an_unsafe_posture_exits_non_zero`).

**READ THIS BEFORE IMPLEMENTING: the exception type is deliberately NOT pinned, and the
obvious implementation leaks a password.** The natural pydantic form — raising
``ValueError`` (or ``AssertionError``) from a ``model_validator`` — is *wrong here*.
Pydantic catches those and wraps them in a ``ValidationError`` whose rendered
``input_value`` is **the whole model**, so the error text an operator pastes into a
ticket contains ``neo4j_password='harnesspass'`` and the full database DSN. Pinning
``ValidationError`` would have pinned that leak into the contract. Raise a **dedicated
exception type** instead — pydantic lets a non-``ValueError`` escape a validator
unwrapped — and these tests will accept it, because they assert behaviour rather than a
class. :func:`test_the_refusal_never_prints_a_secret_value` is what keeps the choice
honest; if it goes red, this paragraph is why.

**Refuse to boot — NOT "degrade to read-only" (decided; do not re-litigate under deploy
pressure).** The tempting softer failure mode is to start anyway and serve reads. It
does not work here, because **what is broken is the identity layer, not the write
path**: with ``cas_enabled=False`` every cookieless caller is already a transient
*admin*, so a read-only service still hands anyone on the network the entire
unpublished draft corpus, the archive JD content, the user-administration listing and
the LLM-driven compose surface. That protects NN #1 (nothing publishes) and does nothing
for NN #6 or FIPPA. It also adds a second production code path that nothing tests and
that becomes the permanent state of any deployment which cannot be bothered to fix its
config — and it is meaningless for the eight non-API compose services, which have no
"read-only" to fall back to. This is an HR pilot, not a life-safety system: a boot that
fails is a ten-minute config fix; a pilot that runs half-open is a conversation with the
Privacy Office.

**Deliberately out of scope, so their absence is not an oversight:**

* ``session_cookie_samesite='strict'`` — **P0.1b**, with CSRF as a whole. ``strict``
  suppresses the cookie on a cross-site navigation and the CAS return leg *is* one
  (``cas.sfu.ca`` -> us). Depending on when the session cookie is issued relative to
  that hop, mandating ``strict`` here could break login in exactly the posture this file
  makes compulsory, and a fail-closed check that bricks production is worse than the
  gap. It needs the redirect flow tested end to end first.
* **No app/session secret is validated, because none exists.** Sessions are opaque
  server-side tokens (``secrets.token_urlsafe(32)`` in a Postgres row), not signed
  cookies — there is no signing key in ``Settings``. The one secret-shaped committed
  string, ``FLASK_SECRET_KEY=change-me`` in ``.env.example``, has been orphaned since
  Flask was removed in ``3e32103``: **delete it, do not validate it.**
* **No entropy rule.** The condition is literally "not the committed default"; a weak
  password passes. Retrofitting an entropy floor later breaks a running deployment, so
  if one is ever wanted it is a separate, announced decision.
* **No bypass flag** (pinned by :func:`test_there_is_no_bypass_flag_for_production`).
  ``ALLOW_UNSAFE_PRODUCTION`` gets set once, during the deploy that is failing, and is
  never unset. ``environment`` defaulting to ``development`` *is* the opt-out.
* ``bootstrap_admins`` non-empty — availability, not safety (an operator may seed the DB
  instead).

**Not register-bearing.** This is deployment safety, not a rulebook metric or an HR
policy: no ``decision_register.yaml`` entry, and ``rules_version`` does not move.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from src.settings import Settings

# ── The committed defaults, verbatim. These are in git; they are not secrets, and a
# production deployment that still carries them has no secrets at all. ───────────────
COMMITTED_DATABASE_URL = "postgresql+asyncpg://app:app@postgres:5432/harness"
COMMITTED_NEO4J_PASSWORD = "harnesspass"
#: The shipped ``cas_service_base_url`` — the origin CAS redirects the browser back to.
COMMITTED_SERVICE_BASE_URL = "http://localhost:25800"

#: A production posture with every condition MET. Each violation test overrides exactly
#: one key, so a failure names the culprit. Values are passed to ``Settings(...)``
#: directly rather than through env vars: init arguments outrank both the environment
#: and ``.env`` in pydantic-settings, so these tests describe the same posture whether
#: they run in the `gates` container (which exports the committed defaults) or not.
SAFE_PRODUCTION: dict[str, Any] = {
    "environment": "production",
    "cas_enabled": True,
    "cas_dev_fake_user": "",
    "cas_verify_tls": True,
    "cas_service_base_url": "https://jdbank.sfu.ca",
    "session_cookie_secure": True,
    "database_url": "postgresql+asyncpg://jdbank:UYm-not-the-committed-one@pg:5432/jd",
    "neo4j_password": "nor-is-this-one-Xq7",
    "ollama_base_url": "http://aria-gb10-2:11434/v1",
    "allowed_inference_hosts": ["aria-gb10-2"],
}

#: id -> (override that breaks exactly one condition, the setting the message must name)
VIOLATIONS: dict[str, tuple[dict[str, Any], str]] = {
    "cas_disabled": ({"cas_enabled": False}, "cas_enabled"),
    "dev_fake_user_set": ({"cas_dev_fake_user": "asalah"}, "cas_dev_fake_user"),
    # An authentication BYPASS, not hardening: with TLS verification off, the
    # /serviceValidate round-trip that decides who the caller is can be answered by
    # anyone who can get in the path. It ships True, but `settings.py` documents it as
    # flip-it-if-the-cert-chain-complains — which is exactly how it becomes false and
    # stays false. Ranked with `cas_enabled`, above the credential conditions.
    "cas_tls_verification_off": ({"cas_verify_tls": False}, "cas_verify_tls"),
    # The origin CAS redirects the browser back to after login. Left at the shipped
    # localhost default, production login cannot work at all — and an http service URL
    # combined with `session_cookie_secure=True` means the cookie is never sent. Better
    # discovered at boot than by the first user who tries to sign in.
    "committed_service_base_url": (
        {"cas_service_base_url": COMMITTED_SERVICE_BASE_URL},
        "cas_service_base_url",
    ),
    "cookie_not_secure": ({"session_cookie_secure": False}, "session_cookie_secure"),
    "committed_db_password": (
        {"database_url": COMMITTED_DATABASE_URL},
        "database_url",
    ),
    "committed_neo4j_password": (
        {"neo4j_password": COMMITTED_NEO4J_PASSWORD},
        "neo4j_password",
    ),
    "inference_host_not_allowlisted": (
        {"ollama_base_url": "https://api.openai.com/v1"},
        "ollama_base_url",
    ),
}


def refusal_message(**overrides: Any) -> str:
    """Build a production ``Settings`` that violates ``overrides`` and return the
    refusal message. Fails the test if it boots instead.

    ``Exception`` on purpose — see the module docstring. The implementation must NOT
    raise ``ValueError`` from a ``model_validator``: pydantic wraps it in a
    ``ValidationError`` that prints the whole model, secrets included.
    """
    with pytest.raises(Exception) as excinfo:  # noqa: B017 - see the module docstring
        Settings(**{**SAFE_PRODUCTION, **overrides})
    message = str(excinfo.value)
    assert message.strip(), (
        "the refusal raised an empty message — an operator has to be able to read what "
        "is wrong and fix it"
    )
    return message


# ── A. The startup invariant ─────────────────────────────────────────────────────────


def test_a_fully_safe_production_posture_boots() -> None:
    """The control must not be a brick: with every condition met, production boots and
    reports itself as production. This also fails while ``environment`` does not exist,
    which is what stops the refusal tests below from passing vacuously."""
    settings = Settings(**SAFE_PRODUCTION)

    assert settings.environment == "production"
    assert settings.cas_enabled is True


@pytest.mark.parametrize(
    ("override", "named"),
    [pytest.param(o, n, id=k) for k, (o, n) in VIOLATIONS.items()],
)
def test_production_refuses_to_boot_when_one_condition_is_unmet(
    override: dict[str, Any], named: str
) -> None:
    """One case per condition, so a red run names which one regressed. The message must
    name the **setting**, not just complain: an operator reading a container's last log
    line needs to know what to change."""
    message = refusal_message(**override).lower()

    assert named in message, (
        f"the refusal did not name {named!r} — it said: {message!r}. Name the setting "
        "an operator has to change; 'unsafe configuration' is not actionable."
    )


def test_the_refusal_names_every_unmet_condition_at_once() -> None:
    """The one most likely to be built lazily as fail-on-first.

    An operator fixing a deployment one restart per mistake is an operator who will
    give up and set the mode back to development. Every unmet condition, one pass.
    """
    every_violation: dict[str, Any] = {}
    for override, _ in VIOLATIONS.values():
        every_violation.update(override)

    message = refusal_message(**every_violation).lower()

    missing = sorted(named for _, named in VIOLATIONS.values() if named not in message)
    assert not missing, (
        f"the refusal named only some of the unmet conditions; it never mentioned "
        f"{missing}. Collect every failure and report them together — do not raise on "
        f"the first one. Message was: {message!r}"
    )


def test_the_refusal_never_prints_a_secret_value() -> None:
    """The message is going to end up in a container log, a CI transcript and a
    screenshot in a ticket. It may name the *setting*; it may never print the *value*.

    (This is also the reason the tests do not pin the exception type — pydantic's own
    ``ValidationError`` renders ``input_value``, i.e. the entire ``Settings`` model,
    including these two fields. See the module docstring.)
    """
    message = refusal_message(
        database_url=COMMITTED_DATABASE_URL,
        neo4j_password=COMMITTED_NEO4J_PASSWORD,
    )

    leaked = [
        secret
        for secret in (COMMITTED_NEO4J_PASSWORD, "app:app@", COMMITTED_DATABASE_URL)
        if secret in message
    ]
    assert not leaked, (
        f"the refusal printed {leaked} — a credential in a log line. Name the setting "
        f"('neo4j_password is the committed default'), never the value. Message was: "
        f"{message!r}"
    )


def test_the_startup_check_the_settings_comment_promised() -> None:
    """The exact combination ``settings.py`` has claimed to refuse since ADR-008.

    Named after the comment it makes true — ``settings.py``: *"Empty in prod (a startup
    check refuses cas_enabled + a dev-fake user together)."* The comment shipped; the
    check did not.

    ``cas_dev_fake_user`` mints a session for a named user **without contacting CAS** —
    in production that is unauthenticated impersonation of whoever is named.
    """
    message = refusal_message(cas_enabled=True, cas_dev_fake_user="asalah").lower()

    assert "cas_dev_fake_user" in message


def test_a_whitespace_only_dev_fake_user_is_still_a_dev_fake_user() -> None:
    """``" "`` is not empty. A truthiness check on the raw string would let it through,
    and ``resolve_user`` would then treat it as a configured fake user."""
    message = refusal_message(cas_dev_fake_user="   ").lower()

    assert "cas_dev_fake_user" in message


def test_disabled_cas_tls_verification_is_refused() -> None:
    """``cas_verify_tls=False`` turns the ticket-validation round-trip into something
    anyone in the network path can answer — an authentication **bypass**, not a
    hardening nit. The setting exists for a container whose CA bundle is stale; that is
    a dev accommodation, and it may not survive into production.
    """
    message = refusal_message(cas_verify_tls=False).lower()

    assert "cas_verify_tls" in message


@pytest.mark.parametrize(
    "service_base_url",
    [
        COMMITTED_SERVICE_BASE_URL,
        "http://jdbank.sfu.ca",  # right host, no TLS
        "https://localhost:25800",  # TLS, but still the dev origin
        "http://127.0.0.1:25800",
    ],
    ids=["committed_default", "plain_http", "https_localhost", "loopback_literal"],
)
def test_a_dev_or_plaintext_cas_service_origin_is_refused(
    service_base_url: str,
) -> None:
    """Both halves matter, so both are pinned.

    *Plaintext* — this is the origin CAS sends the freshly authenticated browser back
    to; over http the ticket travels in clear and the session cookie (``secure=True`` in
    production) is never sent, so login silently cannot complete. *Localhost* — a
    production deployment still pointing at the dev origin will bounce every user to
    their own machine after login.
    """
    message = refusal_message(cas_service_base_url=service_base_url).lower()

    assert "cas_service_base_url" in message


def test_a_real_https_service_origin_is_accepted() -> None:
    """The other direction — the check must not be a blanket "no URLs I recognise"."""
    settings = Settings(
        **{**SAFE_PRODUCTION, "cas_service_base_url": "https://jdbank.its.sfu.ca"}
    )

    assert settings.environment == "production"


def test_a_private_inference_host_is_accepted_without_being_listed() -> None:
    """The production check must use the SAME notion of "allowed inference host" as the
    egress guard (``src.jd_bank.security.egress``), which admits any loopback/RFC-1918
    literal because a dev-box or internal Ollama is a permitted internal case (NN #5).

    Two different definitions of the same boundary is how one of them ends up wrong.
    """
    settings = Settings(**{**SAFE_PRODUCTION, "ollama_base_url": "http://10.4.2.9/v1"})

    assert settings.environment == "production"


def test_a_host_added_to_the_allowlist_is_accepted() -> None:
    """The allowlist is authoritative — the check reads it, it does not hardcode
    ``aria-gb10-2``. Moving the inference host is a config change, not a code change."""
    settings = Settings(
        **{
            **SAFE_PRODUCTION,
            "ollama_base_url": "http://aria-gb10-9:11434/v1",
            "allowed_inference_hosts": ["aria-gb10-9"],
        }
    )

    assert settings.environment == "production"


# ── The deployment mode itself ───────────────────────────────────────────────────────


def test_the_default_mode_is_development() -> None:
    """Inferring production from other flags would be circular, so the mode is
    explicit — and it defaults to the safe-to-be-wrong side. Nobody gets production
    behaviour by accident, and nobody has to opt out of it to develop."""
    assert Settings().environment == "development"


def test_the_shipped_default_settings_still_load() -> None:
    """Development is unchanged and painless (and ``make gates`` keeps working: the
    `gates` compose service deliberately pins ``CAS_ENABLED=false``, so a check that
    fired there would be a self-inflicted wound)."""
    settings = Settings()

    assert settings.cas_enabled is False
    assert settings.environment == "development"


@pytest.mark.parametrize("value", ["prod", "PRODUCTION", "staging", "", "true"])
def test_an_unrecognised_deployment_mode_is_refused(value: str) -> None:
    """Fail closed on a typo — including ``prod``, which is deliberately **not** an
    alias.

    If ``ENVIRONMENT=prod`` silently meant *development*, an operator who believed they
    had enabled the guard would be running the unsafe posture with no warning at all —
    the exact failure this task exists to remove. Aliasing it to *production* would also
    be fail-closed; refusing is the reviewed call, because one alias invites the next
    and the fix is five seconds long. A future mode (``staging``) gets added
    deliberately, not by whoever first types it.
    """
    with pytest.raises(Exception) as excinfo:  # noqa: B017 - see the module docstring
        Settings(environment=value)

    message = str(excinfo.value).lower()
    assert "environment" in message
    for valid in ("development", "production"):
        assert valid in message, (
            f"the refusal did not offer {valid!r} as a valid mode — it said "
            f"{message!r}. Refusing a typo is only a five-second fix if the message "
            "says what to type instead."
        )


# ── The real entry point: it must EXIT, not warn ─────────────────────────────────────


def test_a_production_boot_with_an_unsafe_posture_exits_non_zero() -> None:
    """Loud, and fatal. A refusal that is logged and stepped over is not a control.

    This runs the actual import path a container entrypoint takes (``get_settings()``)
    in a subprocess with a production environment and the committed defaults, and pins
    that the process **dies** with a message on stderr that names the settings and not
    the secrets. Sub-second: it imports one module.
    """
    core_dir = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "ENVIRONMENT": "production",
        "CAS_ENABLED": "false",
        "CAS_DEV_FAKE_USER": "",
        "SESSION_COOKIE_SECURE": "false",
        "DATABASE_URL": COMMITTED_DATABASE_URL,
        "NEO4J_PASSWORD": COMMITTED_NEO4J_PASSWORD,
        "PYTHONPATH": str(core_dir),
    }

    proc = subprocess.run(
        [sys.executable, "-c", "from src.settings import get_settings; get_settings()"],
        cwd=core_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert proc.returncode != 0, (
        "a production boot in the unsafe posture exited 0 — the process must die, not "
        f"warn. stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    stderr = proc.stderr.lower()
    for named in ("cas_enabled", "session_cookie_secure", "neo4j_password"):
        assert named in stderr, (
            f"the fatal error did not name {named!r} on stderr; an operator reading "
            f"`docker logs` gets nothing to act on. stderr={proc.stderr!r}"
        )
    assert (
        COMMITTED_NEO4J_PASSWORD not in proc.stderr
    ), "the fatal error printed the password into the container log"
    assert "app:app@" not in proc.stderr, (
        "the fatal error printed the database DSN, credentials included, into the "
        "container log"
    )


# ── Development is unchanged ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "override",
    [pytest.param(o, id=k) for k, (o, _) in VIOLATIONS.items()],
)
def test_development_still_boots_in_every_unsafe_combination(
    override: dict[str, Any],
) -> None:
    """Not one of these is a problem in development — that is the whole point of the
    mode being explicit. CAS off with a transient admin *is* the dev experience."""
    settings = Settings(**{**SAFE_PRODUCTION, **override, "environment": "development"})

    assert settings.environment == "development"


def test_development_boots_with_every_condition_violated_at_once() -> None:
    """Including the combination the phantom comment named. In development it is
    supported; the mode, not the flags, is what decides."""
    every_violation: dict[str, Any] = {"environment": "development"}
    for override, _ in VIOLATIONS.values():
        every_violation.update(override)

    settings = Settings(**{**SAFE_PRODUCTION, **every_violation})

    assert settings.environment == "development"


def test_there_is_no_bypass_flag_for_production() -> None:
    """Deliberate: the *mode* is the opt-out, and there is no second override that
    makes an unsafe production boot anyway.

    A ``ALLOW_UNSAFE_PRODUCTION`` escape hatch is set once, during the deploy that is
    failing, by someone under time pressure — and then it is set forever. If a
    deployment cannot meet the conditions it is not production yet.
    """
    bypass_shaped = [
        name
        for name in Settings.model_fields
        if any(
            token in name
            for token in ("allow_unsafe", "skip_startup", "ignore_unsafe", "force_boot")
        )
    ]

    assert not bypass_shaped, (
        f"{bypass_shaped} looks like a production bypass. The reviewed design has "
        "exactly one switch (`environment`); adding a second is a policy change and "
        "needs to be argued, not merged."
    )


# ── B. cas_anonymous_user must be non-blank ──────────────────────────────────────────
#
# Found by the P0.1a security review, and reachable only with `cas_enabled=False` — so
# this one is validated in EVERY mode, not just production. Gating it on production
# would miss it entirely, because the dev posture is the only place it can happen.
#
# With a blank value the two approve paths disagree: approve-WITH-overrides 422s (the
# domain `reviewer` field carries `min_length=1`) while approve-WITHOUT-overrides
# succeeds and writes an EMPTY actor into the append-only, hash-chained audit_log. A
# published JD attributed to nobody is an NN #6 provenance hole.


@pytest.mark.parametrize("blank", ["", " ", "\t", "   \n "])
def test_a_blank_anonymous_user_is_refused_at_load(blank: str) -> None:
    with pytest.raises(Exception) as excinfo:  # noqa: B017 - see the module docstring
        Settings(cas_anonymous_user=blank)

    assert "cas_anonymous_user" in str(excinfo.value).lower()


def test_a_blank_anonymous_user_is_refused_in_production_too() -> None:
    """Production ignores the synthetic actor (CAS is on), but a setting that is invalid
    in one mode is not valid in the other — and a prod->dev rollback must not be the
    thing that discovers it."""
    message = refusal_message(cas_anonymous_user="").lower()

    assert "cas_anonymous_user" in message


def test_the_shipped_anonymous_user_is_unchanged() -> None:
    """The fix is a validator, not a rename: `dev-anonymous` is the actor string already
    written into dev audit rows."""
    assert Settings().cas_anonymous_user == "dev-anonymous"


# ── C. Findings of the P0.2 reviews (2026-08-09) ─────────────────────────────────────
#
# Added after the security + correctness reviews of the first implementation. Each one
# pins a hole that was found in the CODE, not in the contract above: the sections
# before this line are unchanged.


def test_a_malformed_inference_url_does_not_leak_the_model_through_pydantic() -> None:
    """The exact leak the module docstring forbids, reached by a different door.

    ``assert_inference_host_allowed`` calls ``urlsplit`` unguarded, so ``http://[::1``
    raises a bare ``ValueError`` out of the validator — and a ``ValueError`` is the one
    exception type pydantic *wraps*, producing a ``ValidationError`` whose
    ``errors()[0]["input"]`` is the whole model: ``neo4j_password`` and the DSN. ``str``
    of it happens to truncate the repr at ~50 characters, which is an implementation
    detail and not a contract — Sentry, ``rich`` and ``pytest --showlocals`` all print
    the structured value. So the type itself is pinned here, not just the text.
    """
    with pytest.raises(Exception) as excinfo:  # noqa: B017 - see the module docstring
        Settings(**{**SAFE_PRODUCTION, "ollama_base_url": "http://[::1"})

    assert not isinstance(excinfo.value, PydanticValidationError), (
        "a malformed ollama_base_url produced a pydantic ValidationError, which "
        "renders the entire Settings model (password and DSN included) as `input`. "
        "Catch the ValueError in the validator and use the dedicated exception type."
    )
    assert "ollama_base_url" in str(excinfo.value).lower()
    for secret in (COMMITTED_NEO4J_PASSWORD, "app:app@"):
        assert secret not in repr(excinfo.value)


def test_a_malformed_database_url_is_refused_rather_than_assumed_safe() -> None:
    """ "I could not parse the password" is not "the password is fine".

    The credential check must fail closed on a DSN it cannot read, the way the CAS
    origin check already does — otherwise a typo'd DSN is the way past it.
    """
    message = refusal_message(database_url="postgresql+asyncpg://u:p@[::1/jd")

    assert "database_url" in message.lower()
    for secret in (COMMITTED_NEO4J_PASSWORD, "app:app@"):
        assert secret not in message


def test_a_malformed_cas_service_origin_is_refused_rather_than_assumed_safe() -> None:
    """The same fail-closed reading for the origin: a URL whose scheme and host cannot
    be read is not an https production origin, so it is refused rather than skipped."""
    message = refusal_message(cas_service_base_url="https://[::1").lower()

    assert "cas_service_base_url" in message


def test_a_percent_encoded_committed_password_is_still_the_committed_password() -> None:
    """``urlsplit`` does not percent-decode, so ``%61pp`` is ``app`` to Postgres and a
    different string to a naive comparison."""
    message = refusal_message(
        database_url="postgresql+asyncpg://app:%61pp@postgres:5432/harness"
    )

    assert "database_url" in message.lower()


@pytest.mark.parametrize(
    "origin",
    [
        "https://localhost.",  # trailing-dot FQDN — a resolver strips it
        "https://127.1",  # inet_aton short form
        "https://2130706433",  # the same address as an integer
        "https://0x7f000001",  # …and as hex
    ],
    ids=["trailing_dot", "inet_aton_short", "integer_ipv4", "hex_ipv4"],
)
def test_the_other_spellings_of_loopback_are_refused(origin: str) -> None:
    """``127.0.0.1`` is not the only way to write the dev origin, and every OS resolver
    accepts these. A check that only knows the canonical spelling is a check with a
    documented bypass."""
    message = refusal_message(cas_service_base_url=origin).lower()

    assert "cas_service_base_url" in message


def test_a_private_intranet_origin_is_accepted() -> None:
    """The deliberate divergence from the egress guard, pinned so nobody "fixes" it.

    RFC-1918 is refused for an *inference* host only when it is not on the allowlist;
    for the CAS service origin it is legitimate — an intranet-only SFU deployment
    reached at ``https://10.x`` is a real deployment. Only LOOPBACK is refused, because
    loopback means "whatever machine the browser is on".
    """
    settings = Settings(
        **{**SAFE_PRODUCTION, "cas_service_base_url": "https://10.4.2.9"}
    )

    assert settings.environment == "production"


def test_deriving_the_cas_service_origin_from_a_request_header_is_refused() -> None:
    """The ninth condition, found by the security review.

    With ``cas_service_from_request``, ``routes/auth.py`` builds the CAS service origin
    from ``X-Forwarded-Host`` and never reads the validated ``cas_service_base_url`` —
    so a *caller* picks the origin CAS is told to redirect to, and ``x-forwarded-proto``
    falls back to ``http``, making the derived origin plaintext even with a secure
    cookie. Refused outright in production rather than allowlisted: an allowlist is a
    second, untested definition of the same origin, and the deployment that needs this
    is a multi-host one we do not have.
    """
    message = refusal_message(cas_service_from_request=True).lower()

    assert "cas_service_from_request" in message


def test_deriving_the_origin_from_a_request_header_is_fine_in_development() -> None:
    settings = Settings(
        **{
            **SAFE_PRODUCTION,
            "environment": "development",
            "cas_service_from_request": True,
        }
    )

    assert settings.cas_service_from_request is True


def test_settings_cannot_be_mutated_after_the_invariant_was_checked() -> None:
    """The invariant is verified once, at construction, on an ``lru_cache``d instance
    shared by the whole process. If a field could be reassigned afterwards, a single
    line anywhere could void it with nothing re-validating. No code does that today;
    this is what keeps the guarantee true tomorrow."""
    settings = Settings()

    with pytest.raises(Exception) as excinfo:  # noqa: B017 - pydantic's frozen error
        settings.cas_enabled = True  # type: ignore[misc]

    assert "frozen" in str(excinfo.value).lower()
