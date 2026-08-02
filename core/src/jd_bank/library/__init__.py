"""The browsable JD Bank — read-only content library over the archive + roles.

A thin read layer that turns stored ``SFUJobDescription`` content (archive parses and
harmonized canonicals) into readable views for the UI, so HR can *read* JDs — not just
see filenames, counts, and dashboards. Everything here is read-only (NN #1).
"""

from __future__ import annotations

from src.jd_bank.library.models import (
    MemberJD,
    RoleListItem,
    RolePage,
    RoleRef,
    RoleView,
    SourceJDView,
    SourceListItem,
    SourcePage,
)
from src.jd_bank.library.service import (
    DEFAULT_PAGE_SIZE,
    get_role,
    get_source_jd,
    list_roles,
    list_source_jds,
)

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MemberJD",
    "RoleListItem",
    "RolePage",
    "RoleRef",
    "RoleView",
    "SourceJDView",
    "SourceListItem",
    "SourcePage",
    "get_role",
    "get_source_jd",
    "list_roles",
    "list_source_jds",
]
