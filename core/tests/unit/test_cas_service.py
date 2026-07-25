"""CAS v2 ticket validation (ADR-008). No live CAS: a fake httpx client returns canned
serviceValidate XML, so the parse/success/failure paths are exercised offline."""

from __future__ import annotations

import httpx
import pytest

from src.api.services.cas_service import CAS_NS, CasValidationError, validate_ticket

_SUCCESS = (
    '<cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">'
    "<cas:authenticationSuccess><cas:user>asalah</cas:user>"
    "</cas:authenticationSuccess></cas:serviceResponse>"
)
_FAILURE = (
    '<cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">'
    '<cas:authenticationFailure code="INVALID_TICKET">ticket not recognized'
    "</cas:authenticationFailure></cas:serviceResponse>"
)


class _FakeHTTP:
    """Minimal stand-in for httpx.AsyncClient: records the request and returns a canned
    response (or raises a network error), so validation is testable without CAS."""

    def __init__(
        self, *, text: str = "", status: int = 200, raise_exc: Exception | None = None
    ):
        self._text = text
        self._status = status
        self._raise = raise_exc
        self.last_url: str | None = None
        self.last_params: dict[str, str] | None = None

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        # Mirrors the httpx.AsyncClient.get(url, params=..., timeout=...) call shape.
        self.last_url = url
        self.last_params = kwargs.get("params")  # type: ignore[assignment]
        if self._raise is not None:
            raise self._raise
        return httpx.Response(status_code=self._status, text=self._text)


async def _validate(http: _FakeHTTP) -> str:
    return await validate_ticket(
        cas_server_url="https://cas.sfu.ca/cas",
        validate_route="/serviceValidate",
        service_url="http://localhost:25800/jd-bank/ui/cas/validate",
        ticket="ST-abc123",
        http=http,  # type: ignore[arg-type]
    )


async def test_success_returns_the_username() -> None:
    http = _FakeHTTP(text=_SUCCESS)
    assert await _validate(http) == "asalah"
    # It hits the configured validate URL with the service + ticket as query params.
    assert http.last_url == "https://cas.sfu.ca/cas/serviceValidate"
    assert http.last_params == {
        "service": "http://localhost:25800/jd-bank/ui/cas/validate",
        "ticket": "ST-abc123",
    }


async def test_authentication_failure_raises() -> None:
    with pytest.raises(CasValidationError, match="INVALID_TICKET"):
        await _validate(_FakeHTTP(text=_FAILURE))


async def test_non_200_raises() -> None:
    with pytest.raises(CasValidationError, match="returned 503"):
        await _validate(_FakeHTTP(text="upstream down", status=503))


async def test_malformed_xml_raises() -> None:
    with pytest.raises(CasValidationError, match="malformed"):
        await _validate(_FakeHTTP(text="<not-xml"))


async def test_network_error_raises() -> None:
    boom = httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED")
    with pytest.raises(CasValidationError, match="unreachable"):
        await _validate(_FakeHTTP(raise_exc=boom))


async def test_success_without_user_tag_raises() -> None:
    no_user = (
        '<cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">'
        "<cas:authenticationSuccess></cas:authenticationSuccess></cas:serviceResponse>"
    )
    with pytest.raises(CasValidationError, match="no <user>"):
        await _validate(_FakeHTTP(text=no_user))


def test_namespace_constant() -> None:
    # Guard the Yale CAS namespace the parser keys on (a typo here silently fails auth).
    assert CAS_NS == "{http://www.yale.edu/tp/cas}"
