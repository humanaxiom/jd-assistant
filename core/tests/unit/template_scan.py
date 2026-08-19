"""Scan template SOURCE (or rendered HTML) for the posting forms it contains.

Extracted from ``test_csrf_protection.py``, which grew this scanner for one class of
defect: **a required hidden input present on some ``<form>`` elements of a page and
missing from others.** Hidden inputs do not cross form boundaries, so "the page carries
the field" is not the property that matters — *every posting form on it* carrying the
field is.

That class recurred. P0-1 of ``docs/tasks/cupe-review-findings-2026-08-19.md``: the
Builder's ``form`` field (which SFU instrument the author is filling) was emitted inside
the check form only, so Submit and Export both fell back to JDFN and answered a CUPE
author with a pydantic error page that wiped everything they had typed. The CSRF scan
would have caught it had it been asking about any field but ``csrf_token``.
"""

from __future__ import annotations

import re

_FORM_OPEN = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
#: ``method=post`` however it is written — quoted either way, or bare. The first version
#: of this matched only the double-quoted spelling, so switching a form to single quotes
#: would have dropped it out of the scan silently.
_METHOD_POST = re.compile(r"""method\s*=\s*['"]?post['"]?""", re.IGNORECASE)


class UnclosedFormError(RuntimeError):
    """A ``<form>`` in a template with no ``</form>``.

    Raised, not tolerated. The first version of this scanner sliced an unclosed form to
    end-of-file, which meant *anything* later in the file satisfied the assertion — and
    that is not hypothetical: ``_csrf.html``'s own doc-comment contained a form tag, so
    this suite reported a green on the very file that defines the macro, for entirely
    the wrong reason. Both ends are closed now: the comment no longer spells out a form
    tag, and an unclosed one is an error rather than a free pass.
    """


def post_forms(html: str) -> list[str]:
    """Each posting form's source, opening tag to ``</form>``."""
    forms: list[str] = []
    for match in _FORM_OPEN.finditer(html):
        if not _METHOD_POST.search(match.group(0)):
            continue
        end = html.lower().find("</form>", match.end())
        if end == -1:
            raise UnclosedFormError(
                f"a posting form has no </form>: {match.group(0)!r}. Close it — an "
                "unclosed form makes this scan pass on the rest of the file."
            )
        forms.append(html[match.start() : end])
    return forms


def action_of(form_source: str) -> str:
    """The form's ``action``, or ``""`` for a form that posts back to the same URL."""
    match = re.search(r"""action\s*=\s*['"]([^'"]*)['"]""", form_source, re.IGNORECASE)
    return match.group(1) if match else ""
