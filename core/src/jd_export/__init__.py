"""SFU-template document export (Phase 5.7; per-form since Track J1).

``render_sfu_docx`` is the ONE entry point: it renders a
:class:`~src.jd_core.models.parsed_jd.SFUJobDescription` on the form it belongs to,
chosen by :func:`~src.jd_core.quality.validators.template_of`, so callers never branch.

* APSA/APEX/Poly (JDFN) — :func:`render_jdfn_docx`: HR's 2024 template layout (header
  identification table, About SFU, sections in template order), Times New Roman 10,
  typed bullets the Bank's parser can read back, how/why sub-bullets, ``(NN%)``
  allocations carried in the duty text, empty sections dropped, and the mandated
  territorial-acknowledgement + Employment-Equity footer injected from the rulebook
  (never inlined). Wording in ``apsa_form.yaml`` (Track J4).
* CUPE (WJQ) — :func:`render_cupe_docx`: HR's "WJQ Custom — Part 1" form, its wording
  from ``cupe_form.yaml``, sign-off lines blank, and NO APSA footer.

    from src.jd_export import render_sfu_docx
    docx_bytes = render_sfu_docx(jd)
"""

from src.jd_export.cupe import render_cupe_docx
from src.jd_export.render import render_jdfn_docx, render_sfu_docx

__all__ = ["render_cupe_docx", "render_jdfn_docx", "render_sfu_docx"]
