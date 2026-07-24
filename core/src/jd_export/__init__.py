"""SFU-template document export (Phase 5.7).

Renders a :class:`~src.jd_core.models.parsed_jd.SFUJobDescription` to an official
SFU-format ``.docx`` — Times New Roman 10, bold section headers, standard bullets,
``(NN%)`` allocations carried in the duty text, empty sections dropped, and the
mandated territorial-acknowledgement + Employment-Equity footer injected from the
rulebook (never inlined).

    from src.jd_export import render_sfu_docx
    docx_bytes = render_sfu_docx(jd)
"""

from src.jd_export.render import render_sfu_docx

__all__ = ["render_sfu_docx"]
