"""Minimal, versioned prompt loader (Phase 4.2a).

The two harmonize templates are pure ``{{ var }}`` substitution, so this renders them
with a tiny in-repo substituter rather than pulling in ``jinja2`` (no new heavy dep —
task constraint). Templates are versioned DATA under ``templates/`` and loaded via
``importlib.resources`` so they are visible inside the ``gates`` container (which mounts
only ``./core``).

**A missing OR unknown template variable RAISES** (:class:`PromptError`) — a prompt is
never shipped with an unresolved ``{{ x }}`` left in it, and a caller that misspells a
variable is told rather than silently ignored.
"""

from __future__ import annotations

import importlib.resources
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from openai.types.chat import ChatCompletionMessageParam

_PACKAGE: Final[str] = __package__ or "src.jd_bank.llm"

#: A ``{{ name }}`` placeholder (optional surrounding whitespace). ``\w+`` only — the
#: templates use plain identifiers, never dotted/filter expressions (jinja territory).
_PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class PromptError(RuntimeError):
    """A prompt template is missing, or a template variable is missing / unknown."""


@dataclass(frozen=True)
class RenderedPrompt:
    """A rendered system+user prompt and the template version it came from.

    ``version`` is the template NAME (e.g. ``jd_harmonize_v1``); the ``_vN`` suffix IS
    the version, and it is stamped onto ``RewrittenDraft.prompt_version`` so a draft
    traces to the exact wording that produced it.
    """

    version: str
    messages: tuple[ChatCompletionMessageParam, ...]


def _read_template(filename: str) -> str:
    resource = importlib.resources.files(_PACKAGE).joinpath("templates", filename)
    try:
        return resource.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptError(f"cannot read prompt template {filename!r}: {exc}") from exc


def _render(template: str, values: Mapping[str, str], used: set[str]) -> str:
    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise PromptError(
                f"prompt template references {{{{ {name} }}}} but no value for "
                f"{name!r} was given — refusing to ship an unresolved placeholder"
            )
        used.add(name)
        return values[name]

    return _PLACEHOLDER.sub(substitute, template)


def load_prompt(name: str, **variables: object) -> RenderedPrompt:
    """Load + render the ``<name>.system.j2`` / ``<name>.user.j2`` template pair.

    Every ``{{ x }}`` in either template must have a value in ``variables`` (else
    :class:`PromptError`), and every value in ``variables`` must be USED by a template
    (an unknown/misspelled variable is a caller bug, not a silent no-op).
    """
    values = {key: str(value) for key, value in variables.items()}
    used: set[str] = set()
    system = _render(_read_template(f"{name}.system.j2"), values, used)
    user = _render(_read_template(f"{name}.user.j2"), values, used)

    unknown = sorted(set(values) - used)
    if unknown:
        raise PromptError(
            f"prompt {name!r} was passed variable(s) {unknown} that no template uses — "
            f"a misspelled or stray variable is a caller error, not a silent no-op"
        )

    messages: tuple[ChatCompletionMessageParam, ...] = (
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    )
    return RenderedPrompt(version=name, messages=messages)
