"""Which origin CAS sends the authenticated browser back to (P0.3 part 1).

**What broke.** The app was reached from outside the dev box for the first time
(`sfuai.ca:7000` → `25800`) and sign-in stopped working: CAS authenticated the user,
issued a ticket, and returned the browser to `http://localhost:25800/...`, because
the return origin was a **single static setting**. Repointing it fixed the forward and
broke localhost — one value cannot serve both.

**Why the mechanism already in the code was not the answer.**
``cas_service_from_request`` took the origin from ``X-Forwarded-Host``, which is
client-supplied: an attacker sets it, the authenticated user is bounced to them
**carrying their CAS ticket**, and ``x-forwarded-proto`` defaults to ``http`` so the
derived origin can be plaintext under a secure cookie. P0.2 refused that flag in
production, so the two options as they stood were *rigid* and *exploitable*.

**The third option, which is what this file pins.** Derive the origin from the request —
then require it to be on an **allowlist** the deployment states. Derivation is not the
control; validation is. An unlisted origin falls back to the static setting and
**never** to the header — the single property that makes reading a header safe at all.
"""

from __future__ import annotations

import pytest
from fastapi import Request

from src.api.service_origin import request_origin, resolve_service_origin
from src.settings import Settings

LOCALHOST = "http://localhost:25800"
FORWARD = "http://sfuai.ca:7000"
ATTACKER = "http://attacker.example"


def make_request(
    *, host: str = "localhost:25800", scheme: str = "http", **headers: str
) -> Request:
    """A request as the app would receive it: a ``Host`` header (every HTTP/1.1 request
    has one) plus whatever proxy headers the test is about."""
    raw = [(b"host", host.encode())]
    raw += [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/jd-bank/ui/cas/login",
            "scheme": scheme,
            "headers": raw,
            "query_string": b"",
        }
    )


def settings_allowing(*origins: str, **overrides: object) -> Settings:
    """Settings with the allowlist under test — and **the static fallback pinned**.

    Pinning it is not tidiness. The first run of this file failed on the dev box and
    would have passed in CI: the repo-root ``.env`` sets ``CAS_SERVICE_BASE_URL`` to the
    demo forward, the ``gates`` service passes it through, and a bare ``Settings()``
    inherited it — so "falls back to the static origin" silently asserted against
    whatever the developer's forward happened to be. A test whose expected value comes
    from the machine it runs on is a test that will be green somewhere and red somewhere
    else, for reasons unrelated to the code. (The pin at the container boundary is in
    ``docker-compose.yml``; this one is belt to that braces.)
    """
    overrides.setdefault("cas_service_base_url", LOCALHOST)
    return Settings(allowed_service_origins=list(origins), **overrides)  # type: ignore[arg-type]


# ── The defect, fixed ────────────────────────────────────────────────────────────


def test_both_origins_work_at_once_with_no_config_change_between_them() -> None:
    """The whole point. One deployment, two ways in, no ``.env`` edit to switch."""
    settings = settings_allowing(LOCALHOST, FORWARD)

    assert (
        resolve_service_origin(make_request(host="localhost:25800"), settings)
        == LOCALHOST
    )
    assert (
        resolve_service_origin(make_request(host="sfuai.ca:7000"), settings) == FORWARD
    )


def test_a_plain_port_forward_is_recognised_from_the_host_header_alone() -> None:
    """This is the case that actually happened, and the reason ``X-Forwarded-Host`` was
    never going to be enough: an ``ssh -L`` / TCP forward adds **no proxy headers at
    all**. The browser's own ``Host`` is the only evidence of the origin it used."""
    settings = settings_allowing(FORWARD)

    resolved = resolve_service_origin(make_request(host="sfuai.ca:7000"), settings)

    assert resolved == FORWARD


def test_a_real_proxy_is_believed_when_it_is_on_the_list() -> None:
    settings = settings_allowing("https://jdbank.sfu.ca")

    resolved = resolve_service_origin(
        make_request(
            host="api-internal:8000",
            x_forwarded_host="jdbank.sfu.ca",
            x_forwarded_proto="https",
        ),
        settings,
    )

    assert resolved == "https://jdbank.sfu.ca"


# ── The control: derivation is not trust ─────────────────────────────────────────


def test_an_injected_forwarded_host_does_not_reach_the_return_url() -> None:
    """The DoD's named test. An attacker who can set a header must not be able to choose
    where an authenticated user — and their CAS ticket — is sent."""
    settings = settings_allowing(LOCALHOST)

    resolved = resolve_service_origin(
        make_request(host="localhost:25800", x_forwarded_host="attacker.example"),
        settings,
    )

    assert resolved == LOCALHOST
    assert "attacker" not in resolved


def test_an_injected_host_header_does_not_reach_the_return_url_either() -> None:
    """``Host`` is client-supplied too. It is safe to *read* only because it is checked;
    an unlisted value is worth exactly as little as an unlisted ``X-Forwarded-Host``."""
    settings = settings_allowing(LOCALHOST)

    resolved = resolve_service_origin(make_request(host="attacker.example"), settings)

    assert resolved == LOCALHOST


def test_an_unlisted_origin_falls_back_to_the_static_setting_not_the_header() -> None:
    settings = settings_allowing(LOCALHOST, cas_service_base_url=FORWARD)

    resolved = resolve_service_origin(make_request(host="elsewhere.example"), settings)

    assert resolved == FORWARD


def test_the_port_is_part_of_the_origin() -> None:
    """``sfuai.ca:7000`` and ``sfuai.ca:7001`` are different origins to a browser and to
    CAS, so a substring or host-only match would let an unintended port through."""
    settings = settings_allowing(FORWARD)

    assert resolve_service_origin(make_request(host="sfuai.ca:7001"), settings) != (
        "http://sfuai.ca:7001"
    )


def test_a_lookalike_hostname_is_not_a_match() -> None:
    settings = settings_allowing("https://jdbank.sfu.ca")

    for lookalike in (
        "jdbank.sfu.ca.attacker.example",
        "evil-jdbank.sfu.ca",
        "jdbank.sfu.ca:8443",
    ):
        resolved = resolve_service_origin(
            make_request(host=lookalike, scheme="https"), settings
        )
        assert resolved != f"https://{lookalike}", lookalike


def test_the_scheme_is_part_of_the_origin() -> None:
    """An https deployment must not accept the http spelling of itself: that is how a
    ticket ends up crossing the network in the clear."""
    settings = settings_allowing("https://jdbank.sfu.ca")

    resolved = resolve_service_origin(
        make_request(host="jdbank.sfu.ca", x_forwarded_proto="http"), settings
    )

    assert resolved != "http://jdbank.sfu.ca"


# ── Shape and normalisation ──────────────────────────────────────────────────────


def test_matching_ignores_case_and_a_trailing_slash() -> None:
    """A browser may send any case in ``Host``; an operator will write a trailing slash.
    Neither is a different origin, and treating them as one produces a silent fallback
    that looks exactly like a typo nobody made."""
    settings = settings_allowing("http://SFUAI.ca:7000/")

    assert resolve_service_origin(make_request(host="sfuai.CA:7000"), settings) == (
        FORWARD
    )


def test_only_the_first_value_of_a_forwarded_header_chain_is_read() -> None:
    """``X-Forwarded-Host`` accumulates through hops; entry one is the client's."""
    settings = settings_allowing(FORWARD)

    resolved = resolve_service_origin(
        make_request(host="internal:8000", x_forwarded_host="sfuai.ca:7000, inner:80"),
        settings,
    )

    assert resolved == FORWARD


@pytest.mark.parametrize(
    "host", ["", " ", "not a host", "sfuai.ca:notaport", "sfuai.ca:70000"]
)
def test_a_malformed_host_falls_back_rather_than_raising(host: str) -> None:
    """A crafted ``Host`` must not 500 the login route — it is the first thing an
    unauthenticated stranger can reach."""
    settings = settings_allowing(LOCALHOST, cas_service_base_url=LOCALHOST)

    assert resolve_service_origin(make_request(host=host), settings) == LOCALHOST


def test_request_origin_reports_what_it_derived_before_any_checking() -> None:
    """The derivation step on its own, so the allowlist test above cannot pass merely
    because derivation returned nothing."""
    assert request_origin(make_request(host="sfuai.ca:7000")) == FORWARD
    assert (
        request_origin(make_request(host="x", x_forwarded_host="attacker.example"))
        == ATTACKER
    )


# ── Defaults and degenerate configurations ───────────────────────────────────────


def test_an_empty_allowlist_pins_the_static_origin() -> None:
    """Turning the mechanism off must leave the previous behaviour exactly in place."""
    settings = settings_allowing(cas_service_base_url=FORWARD)

    assert resolve_service_origin(make_request(host="sfuai.ca:7000"), settings) == (
        FORWARD
    )
    assert resolve_service_origin(make_request(host="localhost:25800"), settings) == (
        FORWARD
    )


def test_the_shipped_default_lets_a_dev_box_sign_in() -> None:
    """The default allowlist is the committed dev origin, so `docker compose up` on a
    fresh checkout signs in without anyone configuring anything — and production refuses
    to load while that default is still in place (``test_production_posture.py``).

    Asserted against the field's declared default rather than a bare ``Settings()``, so
    it cannot be answered by an environment variable on the machine running it.
    """
    default = Settings.model_fields["allowed_service_origins"].default

    assert default == [LOCALHOST]
    assert (
        resolve_service_origin(
            make_request(host="localhost:25800"), settings_allowing(*default)
        )
        == LOCALHOST
    )


def test_the_static_fallback_is_returned_without_its_trailing_slash() -> None:
    """The service URL is concatenated with a path; a double slash is a different URL to
    CAS, and CAS compares the service string byte-for-byte across the two legs."""
    settings = settings_allowing(cas_service_base_url="http://localhost:25800/")

    assert resolve_service_origin(make_request(), settings) == LOCALHOST
