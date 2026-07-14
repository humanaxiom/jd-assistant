"""Turn an exception into a ledger reason that is the SAME on every run.

Extracted from :mod:`src.jd_bank.baseline.runner` (Phase 3.2a) so the archive ingest
driver (:mod:`src.jd_bank.ingest.driver`) can share it rather than re-implementing the
same regexes in a second home — HANDOFF calls that shape (one fact, two homes) the
``max_listed`` landmine: nothing keeps two copies in step.

Two sources of per-run noise leak into extractor exception messages, and BOTH have to
go or a skip ledger is not an audit trail:

1. ``extract._extract_doc`` writes the bytes to a ``NamedTemporaryFile`` before handing
   them to antiword, so a failure message names it::

       antiword failed: /tmp/tmp0k444cks.doc is not a Word Document

2. ``extract._extract_docx`` hands python-docx a ``BytesIO``, and python-docx puts its
   **repr** in the message — which carries a heap address::

       docx parse failed: file '<_io.BytesIO object at 0x7917efaa0590>' is not a Word
       file, content type is 'application/vnd.ms-word.document.macroEnabled...'

Both are freshly random every run. Left in, two runs over the same archive would
produce byte-different ledgers, and identically-broken files would each report as
their own unique reason with a count of 1 instead of grouping. (2) was missed when (1)
was fixed, and it outlived a "verified byte-identical across two runs" claim on the
Phase 2.5 baseline — see HANDOFF's gotchas. Both are artefacts of **our own** plumbing
and say nothing about the JD, so scrubbing them discards no evidence; the rest of the
message survives verbatim.

Any future extractor backend should assume its exception messages carry the same kind
of per-run noise, and prove it by running twice — not by asserting it.
"""

from __future__ import annotations

import re
import tempfile

#: Any path under the system temp dir, as it appears inside an exception message.
_TMPFILE = re.compile(re.escape(tempfile.gettempdir()) + r"[/\\]\S+")

#: A CPython object repr — ``<_io.BytesIO object at 0x7f...>``. The address is the
#: process's heap layout, not a fact about the JD, and it is different every run.
_OBJ_ADDR = re.compile(r"<([\w.]+) object at 0x[0-9a-fA-F]+>")


def stable_reason(exc: Exception) -> str:
    """``exc`` as a ledger reason that is the SAME on every run.

    See the module docstring for what gets scrubbed and why.
    """
    reason = _TMPFILE.sub("<tmpfile>", f"{type(exc).__name__}: {exc}")
    return _OBJ_ADDR.sub(r"<\1>", reason)
