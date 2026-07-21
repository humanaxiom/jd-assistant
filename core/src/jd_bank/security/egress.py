"""Egress guard (Phase 4.6a) — the build-enforced form of CLAUDE.md NN #5.

NN #5 in prose: *no third-party or cloud LLM API, ever — no vendor egress of JD
content.* Inference on an **internal host we control** (``aria-gb10-2``, ADR-003) is
ALLOWED; JD text crossing the private network to it is the ratified boundary, not a
violation. A public / third-party host (``api.openai.com``, ``api.anthropic.com``, any
public FQDN) is a violation.

Until now that boundary was enforced only by a human reading code: the two JD-content
network sinks (:class:`~src.jd_bank.llm.client.ChatClient`,
:class:`~src.jd_bank.embeddings.client.EmbedClient`) both build their ``AsyncOpenAI``
from ``settings.ollama_base_url``, which *defaults* to the internal host. This module
makes it a **build failure** instead: both clients call
:func:`assert_inference_host_allowed` on the real-construction path, BEFORE the
``AsyncOpenAI`` client exists and before any content could be sent.

The boundary is a HOST ALLOWLIST (``settings.allowed_inference_hosts``,
env-overridable): an exact hostname match passes, and — because a future dev-box Ollama
is an explicitly permitted *internal* case — any loopback / private (RFC-1918) IP
literal passes too. A public FQDN or a routable public IP that is not on the allowlist
is rejected. Stdlib only; no new runtime dependency.

This is OPS/SECURITY config, not a JD-scoring rule — it changes no JD's score — so the
allowlist lives in ``settings.py``, NOT in ``jd_core/rules/`` and NOT in the HR
decision register (which governs rulebook scoring defaults). See
``docs/security/egress-audit.md``.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlsplit


class DisallowedInferenceHostError(RuntimeError):
    """An inference ``base_url`` points at a host that is NOT on the allowlist.

    Raised BEFORE any ``AsyncOpenAI`` client is constructed, so no JD content can have
    left the process. The message names the offending host and the allowlist so the
    build failure is legible (NN #5 / ADR-003).
    """


def _is_internal_ip(host: str) -> bool:
    """True if ``host`` is a loopback / private (RFC-1918) / link-local IP literal.

    These are on an internal segment by construction, so they are allowed without
    enumerating every address in the allowlist (a dev-box Ollama is a permitted
    internal case). A routable PUBLIC IP literal returns False and is rejected.
    """
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def assert_inference_host_allowed(
    base_url: str, *, allowed_hosts: Iterable[str] | None = None
) -> None:
    """Raise :class:`DisallowedInferenceHostError` unless the ``base_url`` host is OK.

    A host is allowed when it exactly matches (case-insensitively) an entry in
    ``allowed_hosts`` OR is a loopback / private IP literal. ``allowed_hosts`` defaults
    to ``settings.allowed_inference_hosts``. Fails closed: a ``base_url`` from which no
    host can be parsed is rejected.
    """
    if allowed_hosts is None:
        # Imported lazily so this module has no import-time settings dependency.
        from src.settings import get_settings

        allowed_hosts = get_settings().allowed_inference_hosts

    allowlist = {h.strip().lower() for h in allowed_hosts if h.strip()}
    host = urlsplit(base_url).hostname

    if not host:
        raise DisallowedInferenceHostError(
            f"cannot determine the inference host from base_url {base_url!r} - "
            f"refusing to send content to an unidentifiable endpoint (allowlist: "
            f"{sorted(allowlist)})"
        )

    if host.lower() in allowlist or _is_internal_ip(host):
        return

    raise DisallowedInferenceHostError(
        f"inference host {host!r} (from base_url {base_url!r}) is not an internal host "
        f"we control: it is not on the allowlist {sorted(allowlist)} and is not a "
        f"loopback/private address. CLAUDE.md NN #5 forbids sending JD content to a "
        f"third-party/cloud endpoint. Point OLLAMA_BASE_URL at an internal host, or "
        f"add this host to ALLOWED_INFERENCE_HOSTS if it is genuinely one we control."
    )
