"""Central configuration — single source of truth, loaded from env.

**This module also refuses to load an unsafe production posture (P0.2).** See
:class:`ConfigurationRefusedError` and
:meth:`Settings._refuse_an_unsafe_configuration`: in ``environment="production"`` a
``Settings`` that would leave the service open simply does not construct, so the
process dies at import instead of serving. The check lives here, at settings load,
rather than in the FastAPI lifespan, because the API is not the only reader: **eight
pipeline compose services** (``ingest``, ``embed``, ``embed-roles``, ``near-dup``,
``dedup-role``, ``cluster``, ``harmonize``, ``canonical``) plus the arq ``worker``
construct this class and open the same Postgres, Neo4j and Ollama, and not one of them
runs the API's lifespan. (``baseline`` and ``dedup`` are deliberately NOT in that list —
they are filesystem-only and never construct ``Settings``. The two live-golden services,
``rewrite`` and ``quality``, do.) Pinned by ``tests/unit/test_production_posture.py``,
and — because a check nobody can turn on is not a check —
``tests/unit/test_compose_env_delivery.py`` pins that every setting a refusal can name
is actually deliverable through ``docker-compose.yml``.
"""

from __future__ import annotations

import ipaddress
import socket
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import unquote, urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode

#: The committed, in-git values the production check refuses. They are **not secrets** —
#: anyone can read them in this file and in ``docker-compose.yml`` — which is precisely
#: why a production deployment still carrying them has no credentials at all. Named once
#: so the field defaults below and the check cannot drift apart.
_COMMITTED_DATABASE_URL = "postgresql+asyncpg://app:app@postgres:5432/harness"
_COMMITTED_NEO4J_PASSWORD = "harnesspass"
_COMMITTED_CAS_SERVICE_BASE_URL = "http://localhost:25800"

#: The deployment modes this service knows. A typo (``prod``, ``PRODUCTION``,
#: ``staging``) is REFUSED rather than aliased: if ``ENVIRONMENT=prod`` silently meant
#: *development*, an operator who believed the guard was on would be running the unsafe
#: posture with no warning — the exact failure P0.2 exists to remove. A future mode gets
#: added deliberately, not by whoever first types it.
Environment = Literal["development", "production"]
_ENVIRONMENTS: tuple[str, ...] = ("development", "production")


class ConfigurationRefusedError(RuntimeError):
    """Configuration this service refuses to load. Raised out of a validator.

    **Deliberately NOT a ``ValueError`` (nor an ``AssertionError``), and that is a
    security property, not a style choice.** Pydantic catches those two inside a
    validator and re-raises them as a ``ValidationError`` whose rendered
    ``input_value`` is, for a model-level validator, **the entire model** — so the very
    refusal written to prove that credentials never reach a log line would print
    ``neo4j_password='…'`` and the full database DSN into ``docker logs`` and from
    there into a ticket. Any other exception type escapes a validator unwrapped,
    carrying only the message composed here — which names settings and never values.
    """


class UnknownEnvironmentError(ConfigurationRefusedError):
    """``ENVIRONMENT`` is not one of :data:`_ENVIRONMENTS`."""


class UnsafeConfigurationError(ConfigurationRefusedError):
    """One or more settings are unsafe for the declared :data:`Environment`.

    Reports **every** unmet condition in one message: an operator fixing a deployment
    one restart per mistake is an operator who sets the mode back to development.
    """


def _dsn_password(dsn: str) -> str | None:
    """The password component of a DSN, percent-decoded. ``None`` if there is not one.

    **Raises ``ValueError`` on a DSN it cannot parse — it does not swallow it.** An
    unparseable DSN means "whether this carries the committed credential is unknown",
    and the caller turns not-knowing into a refusal — see
    :meth:`Settings._unsafe_database_url`.
    Returning ``None`` here would have made an unparseable DSN *pass* the check.

    ``urlsplit`` does not percent-decode, so ``%61pp`` would otherwise slip past a
    comparison against ``app``.

    **Do NOT casefold this, and the asymmetry with the line above is deliberate.**
    ``%61pp`` is the committed password *spelled differently* — Postgres receives the
    identical bytes — so decoding it closes a real evasion. ``APP`` is a genuinely
    different password, because Postgres passwords are case-sensitive; refusing it
    would be a false positive that bricks a legitimate deployment over a credential
    that is not the committed one. Percent-encoding is an encoding; case is content.
    """
    password = urlsplit(dsn).password
    return None if password is None else unquote(password)


#: ``"app"`` — read off the committed DSN rather than restated, so changing one changes
#: both. Checking the *password component* (not only the whole string) means a
#: deployment that repoints the committed credential at another host is still caught.
_COMMITTED_DB_PASSWORD = _dsn_password(_COMMITTED_DATABASE_URL)
if not _COMMITTED_DB_PASSWORD:  # pragma: no cover - a typo in the constant above
    raise ConfigurationRefusedError(
        "_COMMITTED_DATABASE_URL carries no password component, so the production "
        "check for the committed database credential could never fire. Fix the "
        "constant rather than deleting the check."
    )


def _is_loopback_host(host: str) -> bool:
    """True for ``localhost`` / ``*.localhost`` / any loopback IP literal.

    **Only loopback — deliberately narrower than the egress guard's notion of
    "internal".** The guard also admits every RFC-1918 address, which is right for an
    *inference* host and wrong here: ``cas_service_base_url`` is the origin a real
    user's browser is redirected back to, and for an intranet-only SFU deployment a
    private ``10.x`` origin is a perfectly legitimate one. Refusing it (as the guard's
    broader rule would, inverted) would brick a valid deployment. What is never
    legitimate is *loopback*, which resolves to whatever machine the browser is on.

    Loopback has more spellings than ``127.0.0.1``: a trailing-dot FQDN
    (``localhost.``), and the legacy ``inet_aton`` short / integer / hex forms
    (``127.1``, ``2130706433``, ``0x7f000001``) that every OS resolver still accepts.
    All are closed here. ``127.0.0.1.nip.io`` and friends are NOT — a DNS name that
    happens to resolve to loopback cannot be recognised without resolving it, which a
    settings load must not do; a self-inflicted foot-gun, not an attacker's way in.
    """
    lowered = host.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(lowered).is_loopback
    except ValueError:
        pass
    try:  # 127.1 / 2130706433 / 0x7f000001 — what a resolver would actually accept
        packed = socket.inet_aton(lowered)
    except OSError:
        return False
    return ipaddress.IPv4Address(packed).is_loopback


class Settings(BaseSettings):
    # ── Deployment posture (P0.2) ────────────────────────────────────────────
    # Explicit, and defaulting to the safe-to-be-wrong side: nobody gets production
    # behaviour by accident, and nobody has to opt out of it to develop. In
    # `production` this model REFUSES TO CONSTRUCT unless the whole safe posture holds
    # (`_refuse_an_unsafe_configuration`). There is deliberately NO bypass flag — the
    # mode itself is the opt-out; an `ALLOW_UNSAFE_PRODUCTION` gets set once, during
    # the deploy that is failing, and is never unset.
    environment: Environment = "development"

    # Inference: Ollama on metal, OpenAI-compatible /v1 (ADR-003, amended 2026-07-13).
    # It runs on a TRUSTED INTERNAL HOST — `aria-gb10-2` — not on the dev box, and not
    # `host.docker.internal` (which is what this said until someone checked). Overridden
    # by OLLAMA_BASE_URL in compose. `nomic-embed-text` is 768-dim, matching the ADR-002
    # Neo4j vector index — verified from inside the `gates` container, not assumed.
    #
    # NOTE: local `make gates` reaches this host; CI (`ubuntu-latest`) CANNOT, and never
    # will. Nothing on the `make gates` path may call a live endpoint. See ADR-003.
    ollama_base_url: str = "http://aria-gb10-2:11434/v1"
    # Phase 4.6a — the build-enforced form of CLAUDE.md NN #5 (no vendor egress of JD
    # content). OPS/SECURITY config, NOT a JD-scoring rule: it changes no JD's score, so
    # it lives here and NOT in `jd_core/rules/` or the HR decision register. The two
    # JD-content network sinks (`jd_bank.llm.client.ChatClient`,
    # `jd_bank.embeddings.client.EmbedClient`) refuse to build against a host not on
    # this list — see `jd_bank.security.egress` and docs/security/egress-audit.md. The
    # default admits the internal Ollama host (`aria-gb10-2`) plus loopback / the docker
    # host (a future dev-box Ollama is a permitted INTERNAL case); private/RFC-1918 IP
    # literals are allowed by the guard directly. Override with the comma-separated env
    # var ALLOWED_INFERENCE_HOSTS. If the inference host ever moves OFF a trusted
    # segment this is a FIPPA question (NN #5) — re-decide it, don't just append here.
    allowed_inference_hosts: Annotated[list[str], NoDecode] = [
        "aria-gb10-2",
        "localhost",
        "127.0.0.1",
        "host.docker.internal",
    ]
    agent_model: str = "qwen2.5-coder:14b"

    @field_validator("allowed_inference_hosts", "bootstrap_admins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept a comma-separated string (the natural env form) as a list."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    # The HARNESS agent-memory embedding model (`memory.graph.GraphMemory`'s
    # `artifact_embeddings` index — lineage-graph retrieval). NOT what JD Bank
    # embeds a parsed JD with — that is `get_rules().embeddings.model` (HR-124),
    # a rulebook decision. The two coincide today (both `nomic-embed-text`) but
    # must be free to diverge: `src.jd_bank.embeddings` must never read this field.
    embed_model: str = "nomic-embed-text"
    # Phase 3.2b: OPERATIONAL, not a rulebook decision — MEASURED that a batched
    # embedding call returns identical vectors to one-at-a-time (ADR-003 / HR-124),
    # so this only trades throughput for memory and never changes what gets stored.
    embed_batch_size: int = 64

    # Phase 3.3: OPERATIONAL, not a rulebook decision — how many rows one
    # insert/update/delete statement (or one Neo4j vector fetch) carries in the
    # Tier-2 near-dup reconcile (`jd_bank.dedup.near.runner`). It cannot change WHICH
    # edges get written, only how many round-trips writing them costs; `dedup.yaml`
    # is where a decision that changes the RESULT would live.
    neardup_batch_size: int = 500

    # Postgres (transactions). The default is the committed dev credential — production
    # refuses to start while it is still in place (see `_unsafe_for_production`).
    database_url: str = _COMMITTED_DATABASE_URL

    # Neo4j (graph + vector memory)
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = _COMMITTED_NEO4J_PASSWORD

    # Redis / arq
    redis_url: str = "redis://redis:6379/0"

    # Review loop
    max_review_iterations: int = 5
    coverage_threshold: int = 80

    # ── Auth / CAS SSO + sessions (RBAC foundation, ADR-008) ─────────────────
    # OPS/SECURITY config, not a JD-scoring rule — changes no JD's score, so it lives
    # here, NOT in jd_core/rules/ or the HR decision register (same call as the egress
    # guard above). Ported in shape from the HRIS auth service (its ADR-0005).
    #
    # Production MUST set CAS_ENABLED=true. When false, every request is the synthetic
    # `cas_anonymous_user` with the `cas_dev_default_role` — so the app is usable in
    # dev/CI WITHOUT reaching SFU CAS (the `make gates` path never hits cas.sfu.ca).
    cas_enabled: bool = False
    cas_server_url: str = "https://cas.sfu.ca/cas"
    cas_validate_route: str = "/serviceValidate"
    # The base URL CAS redirects back to (the "service"); prod sets its real origin —
    # and production refuses to start on this dev default, on plain http, or on a
    # localhost/loopback origin (the ticket would travel in clear, the `secure` cookie
    # would never be sent, and every user would be bounced to their own machine).
    cas_service_base_url: str = _COMMITTED_CAS_SERVICE_BASE_URL
    # Derive the service base from the X-Forwarded-Host header when set (multi-host /
    # reverse-proxy deploys); default off — prod pins `cas_service_base_url`.
    cas_service_from_request: bool = False
    # SFU's CAS cert chain has historically failed strict TLS from inside containers
    # without a fresh ca-certificates bundle. Flip false ONLY with a documented reason.
    cas_verify_tls: bool = True
    # CAS enabled but no SFU connection: skip the cas.sfu.ca round-trip and mint a
    # session for this user — exercises the full cookie/session machinery in dev. In
    # production it is unauthenticated impersonation of whoever is named, so
    # `_unsafe_for_production` REFUSES to load a production Settings while it is set
    # (whitespace counts as set). This comment used to promise that check without it
    # existing anywhere; P0.2 built it.
    cas_dev_fake_user: str = ""

    # Server-side sessions: an opaque token in a Postgres row (revocable per-session +
    # auditable), not a signed cookie. Cookie carries only the token id.
    session_cookie_name: str = "jdbank_session"
    session_ttl_hours: int = 8
    session_idle_refresh_hours: int = 1  # slide the TTL when <1h from expiry
    session_cookie_secure: bool = False  # True in prod (HTTPS only)
    # `lax` is the ruling (P0.1b-i), not a placeholder: EVERY mutation in this app is a
    # POST, and `Lax` withholds the cookie from a cross-site POST. `strict` is PERMITTED
    # for an operator who has verified the CAS return leg against their users' browsers,
    # but it is deliberately not mandated — the cookie is set on the response to
    # /cas/validate, which IS the cross-site-arriving request, and whether a freshly-set
    # Strict cookie rides the immediately following same-origin redirect is
    # browser-dependent. A check that bricks production login is worse than the gap.
    # `none` is REFUSED in production (`_unsafe_for_production`); an unrecognised value
    # is refused in EVERY mode (`_always_unsafe`) — see `_normalised_samesite`.
    session_cookie_samesite: str = "lax"

    # The synthetic actor used when cas_enabled=False, and the role it holds. Lets a
    # dev/CI run exercise every role-gated surface without a login. Prod ignores both —
    # but a BLANK `cas_anonymous_user` is refused in EVERY mode (not just production),
    # because the only place it can bite is the dev posture: approve-with-overrides
    # would 422 on the domain `reviewer` field while approve-without-overrides succeeded
    # and wrote an empty actor into the append-only audit chain (NN #6).
    cas_anonymous_user: str = "dev-anonymous"
    cas_dev_default_role: str = "admin"

    # Role granted to a brand-new user on their first CAS login. `author` is the
    # least-privileged useful role (author drafts; nothing publishes without a reviewer,
    # NN #1); reviewer/admin must be granted by an admin. Tighten to a role that can do
    # nothing until granted by making this an unknown-until-granted flow (phase 3).
    default_new_user_role: str = "author"

    # First-admin bootstrap: CAS usernames granted `admin` on every login (comma-sep env
    # BOOTSTRAP_ADMINS). Solves "who promotes the first user" without a DB seed — set it
    # to the deploying admin's SFU id, they log in, then manage everyone else in the UI.
    bootstrap_admins: Annotated[list[str], NoDecode] = []

    # Read-only dashboards (Phase 4.6c): where the committed archive-baseline artifact
    # is mounted INSIDE the api container. `docs/` lives at the repo root (NOT under
    # `core/`, which binds to /app), so the compose api service binds `./docs:/docs:ro`
    # and this points at the baseline summary within it. Overridable (env
    # BASELINE_SUMMARY_PATH) and, in tests, via the `get_baseline_summary_path`
    # dependency — so a unit test can aim the loader at a fixture without a real mount.
    baseline_summary_path: str = "/docs/baseline/summary.json"

    # The rendered operator guide (make guide -> docs/operator-guide.html), served by
    # the in-app "📖 Guide" link. Mounted at /docs by the compose api service's
    # ./docs:/docs:ro bind. Env OPERATOR_GUIDE_PATH; tests aim it at a fixture.
    operator_guide_path: str = "/docs/operator-guide.html"

    # The dedup (Tier 1/2/3) + cluster read-only dashboards (Phase 4.6c slices 2+3) read
    # the SAME committed artifacts `make dedup` / `make near-dup` / `make dedup-role` /
    # `make cluster` write, mounted at `/docs/...` by the compose api service's
    # `./docs:/docs:ro` bind. Each mirrors `baseline_summary_path`: env-overridable
    # (DEDUP_SUMMARY_PATH etc.) and, in tests, aimed at a fixture via the matching
    # `get_*_summary_path` FastAPI dependency — so no real mount is needed to unit-test.
    dedup_summary_path: str = "/docs/dedup/summary.json"
    near_dup_summary_path: str = "/docs/dedup/near-dup-summary.json"
    role_equiv_summary_path: str = "/docs/dedup/role-equiv-summary.json"
    cluster_summary_path: str = "/docs/cluster/cluster-summary.json"

    # `frozen`: the production invariant is checked once, at construction. Without this
    # a single `get_settings().cas_enabled = False` at runtime would void it on the
    # shared, lru_cached instance and nothing would re-validate. No code does that
    # today; this is what keeps it that way.
    #
    # `env_file` is resolved INSIDE the container, where /app is ./core — so it is
    # `core/.env`, which does not exist and is NOT how the repo-root `.env` reaches a
    # service. `docker-compose.yml`'s `&app_env` anchor is: every key there is
    # `${VAR:-default}`, and compose interpolates the repo-root `.env` into it. Do not
    # "fix" a missing setting by trusting this line (see
    # tests/unit/test_compose_env_delivery.py).
    model_config = {"env_file": ".env", "extra": "ignore", "frozen": True}

    # ── The production startup invariant (P0.2) ──────────────────────────────────
    #
    # Every refusal below raises a `ConfigurationRefusedError`, never a `ValueError`
    # — see that class for why the obvious form leaks a password — and every message
    # names SETTINGS, never VALUES. The message is going to end up in a container log,
    # a CI transcript and a screenshot in a ticket.

    @field_validator("environment", mode="before")
    @classmethod
    def _known_environment(cls, value: object) -> object:
        """Refuse a typo'd mode, and say what to type instead."""
        if isinstance(value, str) and value not in _ENVIRONMENTS:
            raise UnknownEnvironmentError(
                f"environment={value!r} is not a deployment mode this service knows. "
                f"Valid values, exactly: {', '.join(_ENVIRONMENTS)}. "
                "'prod' is deliberately NOT an alias for 'production' and 'staging' "
                "does not exist yet - a mode that silently fell back to development "
                "would leave an operator who thought the production guard was on "
                "running with it off."
            )
        return value

    @model_validator(mode="after")
    def _refuse_an_unsafe_configuration(self) -> Settings:
        """Fail closed at load: an unsafe posture must not become a running service.

        Not "degrade to read-only" — what is broken in the unsafe posture is the
        *identity* layer, so a read-only service still hands anyone on the network the
        unpublished draft corpus, the archive content and the user listing. And the
        eight non-API pipeline services have no "read-only" to fall back to.
        """
        problems = self._always_unsafe()
        if self.environment == "production":
            problems += self._unsafe_for_production()
        if not problems:
            return self

        bullets = "\n".join(f"  - {problem}" for problem in problems)
        raise UnsafeConfigurationError(
            f"refusing to load settings: {len(problems)} unsafe setting(s) for "
            f"environment={self.environment!r}.\n"
            f"{bullets}\n"
            "Fix each setting named above in the environment (or .env) of EVERY "
            "service - the api, the arq worker and each pipeline job load this same "
            "configuration. Only setting NAMES are printed above; no value is echoed, "
            "so this message is safe to paste into a ticket."
        )

    def _normalised_samesite(self) -> str:
        """The ``SameSite`` value **as Starlette will honour it**.

        ``set_cookie`` does ``assert samesite.lower() in ['strict', 'lax', 'none']``, so
        ``None`` and ``NONE`` are the *same setting* as ``none``, not different ones. A
        case-sensitive comparison against ``"none"`` would therefore be a check with a
        one-keystroke bypass. Nothing else is normalised — Starlette does not strip, so
        ``" none "`` is not a spelling of ``none``, it is an unrecognised value, and it
        is refused as one.
        """
        return self.session_cookie_samesite.lower()

    def _always_unsafe(self) -> list[str]:
        """Conditions refused in every mode, production or not."""
        problems: list[str] = []
        if self._normalised_samesite() not in ("strict", "lax", "none"):
            problems.append(
                "session_cookie_samesite is not one of strict / lax / none, and this "
                "one does not fail at load - it fails at LOGIN. Starlette's set_cookie "
                "asserts the value, and the only place the session cookie is set is "
                "the CAS return leg, so the service would start cleanly, serve the "
                "login page, and 500 the instant anyone signed in; under -O the "
                "assert is compiled out and the browser silently discards the "
                "attribute. Set SESSION_COOKIE_SAMESITE to lax (the default) or strict"
            )
        if not self.cas_anonymous_user.strip():
            problems.append(
                "cas_anonymous_user is blank or whitespace. It is the actor a "
                "CAS-off deployment attributes every action to, so a review approval "
                "would be written into the append-only audit chain with an empty "
                "actor while the same approval WITH gate overrides was rejected by "
                "the domain model - set CAS_ANONYMOUS_USER to a non-empty name"
            )
        return problems

    def _unsafe_for_production(self) -> list[str]:
        """Every production condition that is unmet — collected, never fail-on-first."""
        problems: list[str] = []
        if not self.cas_enabled:
            problems.append(
                "cas_enabled is false, so identity resolution short-circuits before "
                "any cookie is read and EVERY anonymous request becomes a synthetic "
                "user holding cas_dev_default_role - set CAS_ENABLED=true"
            )
        # NOT `.strip()`: whitespace counts as SET. `resolve_user` tests the raw string,
        # so `"   "` really is a configured fake user, and stripping here would be the
        # one reading that let it through.
        if self.cas_dev_fake_user:
            problems.append(
                "cas_dev_fake_user is set (whitespace counts as set). It mints a "
                "session for that username WITHOUT contacting CAS, which in "
                "production is unauthenticated impersonation - set "
                "CAS_DEV_FAKE_USER to the empty string"
            )
        if not self.cas_verify_tls:
            problems.append(
                "cas_verify_tls is false. The /serviceValidate round-trip that "
                "decides who the caller is can then be answered by anyone in the "
                "network path: an authentication BYPASS, not a hardening nit - set "
                "CAS_VERIFY_TLS=true and fix the container's CA bundle instead"
            )
        if not self.session_cookie_secure:
            problems.append(
                "session_cookie_secure is false, so the session cookie would be sent "
                "over plain http - set SESSION_COOKIE_SECURE=true"
            )
        if self._normalised_samesite() == "none":
            problems.append(
                "session_cookie_samesite is 'none' (in any spelling), which attaches "
                "the session cookie to EVERY cross-site request - precisely the "
                "request a CSRF attack makes. The one value that turns a defence into "
                "an opt-out, and this app has no cross-site embed, no third-party "
                "iframe and no separate front-end origin that could need it - set "
                "SESSION_COOKIE_SAMESITE=lax (the default) or strict"
            )
        if self.cas_service_from_request:
            problems.append(
                "cas_service_from_request is true, so the CAS service origin is taken "
                "from the client-supplied X-Forwarded-Host header and the validated "
                "cas_service_base_url is never read - a caller chooses the origin, and "
                "x-forwarded-proto defaults to http, so the derived origin can be "
                "plaintext even with a secure cookie. Set "
                "CAS_SERVICE_FROM_REQUEST=false and pin the origin"
            )
        problems += self._unsafe_service_origin()
        problems += self._unsafe_database_url()
        if self.neo4j_password == _COMMITTED_NEO4J_PASSWORD:
            problems.append(
                "neo4j_password is the value committed to this repo (it is in git, so "
                "it is not a secret) - set NEO4J_PASSWORD to a real one"
            )
        problems += self._unsafe_inference_host()
        return problems

    def _unsafe_database_url(self) -> list[str]:
        """Refuse the committed database credential — and refuse not being able to tell.

        Fail closed on an unparseable DSN, exactly as :meth:`_unsafe_service_origin`
        does: "I could not read the password" is not "the password is fine".
        """
        if self.database_url == _COMMITTED_DATABASE_URL:
            return [self._committed_database_credential()]
        try:
            password = _dsn_password(self.database_url)
        except ValueError:
            return [
                "database_url is not a URL this service can parse, so whether it still "
                "carries the credential committed to this repo cannot be decided - and "
                "an undecidable credential check fails closed. Fix the DATABASE_URL "
                "syntax (percent-encode any reserved character in the password)"
            ]
        if password == _COMMITTED_DB_PASSWORD:
            return [self._committed_database_credential()]
        return []

    @staticmethod
    def _committed_database_credential() -> str:
        return (
            "database_url still carries the credential committed to this repo. It is "
            "in git, so it is not a secret and this deployment has no database "
            "password at all - point DATABASE_URL at a database with a real one"
        )

    def _unsafe_service_origin(self) -> list[str]:
        """The origin CAS redirects the authenticated browser back to: https, real."""
        try:
            parts = urlsplit(self.cas_service_base_url)
            scheme, host = parts.scheme, parts.hostname
        except ValueError:  # malformed URL — fail closed, same as an http one
            scheme, host = "", None
        if scheme == "https" and host and not _is_loopback_host(host):
            return []
        return [
            "cas_service_base_url is not a production origin: it must be an https URL "
            "at the service's real hostname, not plain http and not "
            "localhost/loopback. Over http the CAS ticket travels in clear and the "
            "session cookie (secure in production) is never sent, so login cannot "
            "complete; pointed at localhost, every user is bounced to their own "
            "machine after login - set CAS_SERVICE_BASE_URL"
        ]

    def _unsafe_inference_host(self) -> list[str]:
        """NN #5, decided by the SAME code the egress guard enforces at build time.

        Imported here rather than at module scope to keep this module's import graph
        free of ``jd_bank`` (the guard itself imports settings lazily for the mirror
        reason). Two divergent definitions of the boundary is how one ends up wrong.

        ``ValueError`` is caught alongside the guard's own error **and that is the
        whole point of this module's exception design**: the guard calls ``urlsplit``
        unguarded, so ``http://[::1`` raises a bare ``ValueError`` out of here —
        which pydantic would catch and re-raise as a ``ValidationError`` whose
        ``errors()[0]["input"]`` is the entire model, ``neo4j_password`` and DSN
        included. A malformed inference URL must fail closed as a refusal, not leak
        the model through the one exception type that gets wrapped.
        """
        from src.jd_bank.security.egress import (
            DisallowedInferenceHostError,
            assert_inference_host_allowed,
        )

        try:
            assert_inference_host_allowed(
                self.ollama_base_url, allowed_hosts=self.allowed_inference_hosts
            )
        except ValueError:
            return [
                "ollama_base_url is not a URL this service can parse, so the host it "
                "would send JD content to cannot be identified - refusing an "
                "unidentifiable inference endpoint (CLAUDE.md NN #5). Fix the "
                "OLLAMA_BASE_URL syntax"
            ]
        except DisallowedInferenceHostError:
            return [
                "ollama_base_url points at an inference host that is neither on "
                "allowed_inference_hosts nor a loopback/private address. CLAUDE.md "
                "NN #5 forbids sending JD content to a third-party or cloud endpoint "
                "- point OLLAMA_BASE_URL at an internal host we control, or add that "
                "host to ALLOWED_INFERENCE_HOSTS if it genuinely is one"
            ]
        return []


@lru_cache
def get_settings() -> Settings:
    return Settings()
