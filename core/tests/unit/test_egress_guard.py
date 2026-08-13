"""The egress guard (Phase 4.6a) — the build-enforced form of CLAUDE.md NN #5.

NN #5: **no third-party or cloud LLM API, ever — no vendor egress of JD content.**
Inference on an INTERNAL host we control (``aria-gb10-2``, ADR-003) is ALLOWED; a
public/cloud host is not. Until now nothing sent JD content to the cloud, but that
safety rested on a human reading code. These tests make it a build failure instead.

Two layers are pinned:

1. :func:`assert_inference_host_allowed` — the guard itself: an internal host passes,
   a cloud host raises, loopback/private hosts pass (a future dev-box Ollama is a
   permitted internal case).
2. The guard is actually WIRED into ``ChatClient`` and ``EmbedClient`` — constructing
   the REAL client (settings' ``ollama_base_url`` pointed at a cloud host) RAISES before
   any ``AsyncOpenAI`` client is built. This is the load-bearing pin: delete the guard
   call from a client and it goes red.
"""

from __future__ import annotations

import pytest

from src.jd_bank.embeddings.client import EmbedClient
from src.jd_bank.llm.client import ChatClient
from src.jd_bank.security.egress import (
    DisallowedInferenceHostError,
    assert_inference_host_allowed,
)
from src.settings import get_settings

_ALLOWLIST = ["aria-gb10-2", "localhost", "127.0.0.1", "host.docker.internal"]


# --- the guard, both directions -------------------------------------------------


def test_internal_host_passes() -> None:
    """The ratified default: JD content crossing the private net to ``aria-gb10-2``
    (a host we control) is ALLOWED (NN #5 / ADR-003)."""
    assert_inference_host_allowed(
        "http://aria-gb10-2:11434/v1", allowed_hosts=_ALLOWLIST
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.openai.com/v1",
        "https://api.anthropic.com",
        "https://generativelanguage.googleapis.com/v1",
        "http://evil.example.com:11434/v1",
    ],
)
def test_cloud_host_is_rejected(base_url: str) -> None:
    """A public/third-party host is a vendor-egress violation — rejected, and the
    error names the offending host so the failure is legible."""
    with pytest.raises(DisallowedInferenceHostError) as exc:
        assert_inference_host_allowed(base_url, allowed_hosts=_ALLOWLIST)
    from urllib.parse import urlsplit

    assert (urlsplit(base_url).hostname or "") in str(exc.value)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:11434/v1",
        "http://127.0.0.1:11434/v1",
        "http://host.docker.internal:11434/v1",
    ],
)
def test_loopback_and_docker_host_pass(base_url: str) -> None:
    """A dev-box Ollama on loopback / the docker host is an explicitly-permitted
    internal case."""
    assert_inference_host_allowed(base_url, allowed_hosts=_ALLOWLIST)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://10.0.1.7:11434/v1",  # RFC-1918
        "http://192.168.1.50:11434/v1",  # RFC-1918
        "http://172.16.3.9:11434/v1",  # RFC-1918
    ],
)
def test_private_ip_literals_pass_even_when_not_listed(base_url: str) -> None:
    """A private (RFC-1918) / loopback IP is on an internal segment by construction —
    allowed without needing to enumerate every address in the allowlist."""
    assert_inference_host_allowed(base_url, allowed_hosts=["aria-gb10-2"])


def test_a_public_ip_literal_is_rejected() -> None:
    """A routable public IP is NOT internal — it must be rejected even though it is an
    IP literal (only PRIVATE/loopback IPs get the blanket allowance)."""
    with pytest.raises(DisallowedInferenceHostError):
        assert_inference_host_allowed("http://8.8.8.8:11434/v1", allowed_hosts=["x"])


def test_a_base_url_with_no_host_is_rejected() -> None:
    """A malformed base_url from which no host can be parsed must fail closed, never
    silently pass."""
    with pytest.raises(DisallowedInferenceHostError):
        assert_inference_host_allowed("not-a-url", allowed_hosts=_ALLOWLIST)


def test_host_match_is_case_insensitive() -> None:
    assert_inference_host_allowed(
        "http://ARIA-GB10-2:11434/v1", allowed_hosts=["aria-gb10-2"]
    )


def test_the_default_allowlist_comes_from_settings() -> None:
    """With ``allowed_hosts`` omitted the guard reads
    ``settings.allowed_inference_hosts`` — and the shipped default admits the real
    ``ollama_base_url`` host."""
    settings = get_settings()
    # default ollama_base_url host is on the default allowlist -> no raise
    assert_inference_host_allowed(settings.ollama_base_url)


# --- the guard is WIRED into the real content clients ---------------------------


def test_real_chat_client_rejects_a_cloud_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE load-bearing pin. Point settings' ``ollama_base_url`` at a cloud host and
    building the REAL ``ChatClient`` (the path that constructs its own ``AsyncOpenAI``
    from settings) must RAISE — before any client is built, before any JD content could
    be sent. Delete the guard call from ``ChatClient.__init__`` and this goes red."""
    cloud = get_settings().model_copy(
        update={"ollama_base_url": "https://api.openai.com/v1"}
    )
    monkeypatch.setattr("src.jd_bank.llm.client.get_settings", lambda: cloud)

    with pytest.raises(DisallowedInferenceHostError):
        ChatClient()


def test_real_embed_client_rejects_a_cloud_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same load-bearing pin for the embeddings sink."""
    cloud = get_settings().model_copy(
        update={"ollama_base_url": "https://api.anthropic.com/v1"}
    )
    monkeypatch.setattr("src.jd_bank.embeddings.client.get_settings", lambda: cloud)

    with pytest.raises(DisallowedInferenceHostError):
        EmbedClient()


def test_real_chat_client_builds_under_default_settings() -> None:
    """Default config is SAFE: the shipped ``ollama_base_url`` host is on the default
    allowlist, so a real JD-content client builds without raising (no network call is
    made at construction)."""
    ChatClient()


def test_real_embed_client_builds_under_default_settings() -> None:
    EmbedClient()


def test_an_injected_client_is_not_re_guarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The test-fake path (``client=...``) does not build from settings, so it is not
    re-checked — even with a cloud ``ollama_base_url`` in settings, an injected client
    constructs fine. The guard gates the REAL construction path, which is the only one
    that could leak."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    cloud = get_settings().model_copy(
        update={"ollama_base_url": "https://api.openai.com/v1"}
    )
    monkeypatch.setattr("src.jd_bank.llm.client.get_settings", lambda: cloud)
    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())),
        close=AsyncMock(),
    )

    ChatClient(client=fake)  # must not raise


def test_graph_memory_rejects_a_cloud_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """The **third** construction path, wired in P0.1b-ii after the 2026-08-07 review
    found it unguarded.

    ``GraphMemory.__init__`` builds an ``AsyncOpenAI`` from the same
    ``ollama_base_url`` the two clients above read, and did so without asking. It embeds
    **agent artifacts** rather than JD text, which is why it was missed and is *not* why
    it would be safe: an artifact is a diff, a spec, or a reviewer's note about the JD
    pipeline, and "this egress carries slightly less sensitive content" is not a
    boundary anyone can maintain. One setting, one rule, checked everywhere it is read.

    The Neo4j driver is injected so this test never opens a socket — the guard must fire
    on construction regardless, and before the embedding client exists.
    """
    from unittest.mock import MagicMock

    from src.memory.graph import GraphMemory

    cloud = get_settings().model_copy(
        update={"ollama_base_url": "https://api.openai.com/v1"}
    )
    monkeypatch.setattr("src.memory.graph.get_settings", lambda: cloud)

    with pytest.raises(DisallowedInferenceHostError):
        GraphMemory(driver=MagicMock())


def test_graph_memory_builds_under_default_settings() -> None:
    """The other direction: the internal host is allowed, so the guard has not simply
    broken agent memory."""
    from unittest.mock import MagicMock

    from src.memory.graph import GraphMemory

    GraphMemory(driver=MagicMock())
