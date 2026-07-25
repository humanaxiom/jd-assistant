"""CAS v2 ticket validation (SFU CAS SSO) — ADR-008.

Ported in shape from the HRIS auth service (its ADR-0005): the validation half of a
CAS v2 flow, as async httpx + a strict XML parse. The two-call shape (redirect to CAS
-> CAS redirects back with a ticket -> we validate the ticket -> on success, create our
session) lives in :mod:`src.api.routes.auth`.

CAS protocol: https://apereo.github.io/cas/development/protocol/CAS-Protocol-Specification.html

Adapted from HRIS: stdlib :mod:`logging` (this repo has no structlog), and the ticket is
NEVER logged — it is a short-lived bearer credential.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import httpx

log = logging.getLogger(__name__)

#: The Yale CAS XML namespace every CAS v2 ``serviceValidate`` response is wrapped in.
CAS_NS = "{http://www.yale.edu/tp/cas}"


class CasValidationError(RuntimeError):
    """The CAS server rejected the ticket or returned a malformed response."""


async def validate_ticket(
    *,
    cas_server_url: str,
    validate_route: str,
    service_url: str,
    ticket: str,
    http: httpx.AsyncClient,
    timeout_s: float = 30.0,
) -> str:
    """Validate a CAS ticket and return the authenticated username.

    Raises :class:`CasValidationError` on any failure (network, HTTP, malformed XML,
    schema, or IdP-said-no) so the route layer can map it to 401/502. Injected
    ``http`` client makes this fully unit-testable without a live CAS server.

    Diagnostic logging is generous on purpose (operators need the exact validate URL +
    a slice of the body to fix a whitelist/cert/expiry problem) — but the ticket is
    never logged.
    """
    url = f"{cas_server_url.rstrip('/')}{validate_route}"
    params = {"service": service_url, "ticket": ticket}
    # NB: ticket NOT logged (bearer credential); its length is enough to confirm CAS
    # actually sent one.
    log.info(
        "cas.validate.start url=%s service=%s ticket_len=%d",
        url,
        service_url,
        len(ticket),
    )

    try:
        response = await http.get(url, params=params, timeout=timeout_s)
    except httpx.HTTPError as exc:
        # SFU CAS often fails strict TLS from inside containers without a recent
        # ca-certificates bundle. On SSL: CERTIFICATE_VERIFY_FAILED, set
        # CAS_VERIFY_TLS=false (and document why) — see Settings.cas_verify_tls.
        log.error("cas.validate.network url=%s error=%s", url, exc)
        raise CasValidationError(f"cas server unreachable: {exc}") from exc

    if response.status_code != 200:
        log.error(
            "cas.validate.http status=%d url=%s body=%r",
            response.status_code,
            url,
            response.text[:500],
        )
        raise CasValidationError(f"cas server returned {response.status_code}")

    try:
        # Trusted endpoint (our configured CAS server), not arbitrary user input.
        root = ET.fromstring(response.text)  # noqa: S314
    except ET.ParseError as exc:
        log.error("cas.validate.parse error=%s body=%r", exc, response.text[:500])
        raise CasValidationError(f"cas response malformed: {exc}") from exc

    success = root.find(f".//{CAS_NS}authenticationSuccess")
    if success is None:
        failure = root.find(f".//{CAS_NS}authenticationFailure")
        code = failure.get("code") if failure is not None else "unknown"
        detail = (failure.text or "").strip() if failure is not None else ""
        log.warning("cas.validate.rejected code=%s detail=%s", code, detail)
        raise CasValidationError(f"cas authentication failed: {code}")

    username = success.findtext(f"{CAS_NS}user")
    if not username:
        log.error("cas.validate.no_user_tag body=%r", response.text[:500])
        raise CasValidationError("cas success but no <user> element")

    return username.strip()
