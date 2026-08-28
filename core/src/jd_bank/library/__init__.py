"""The browsable JD Bank — read-only content library over the archive + roles.

A thin read layer that turns stored ``SFUJobDescription`` content (archive parses and
harmonized canonicals) into readable views for the UI, so HR can *read* JDs — not just
see filenames, counts, and dashboards. Everything here is read-only (NN #1).
"""

from __future__ import annotations

from src.jd_bank.library.families import (
    MAX_CANDIDATES,
    collection_stats,
    family_for,
    rank_candidates,
    resolve_members,
    score_text,
)
from src.jd_bank.library.models import (
    CollectionStats,
    FamilyCandidate,
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
    "MAX_CANDIDATES",
    "CollectionStats",
    "FamilyCandidate",
    "MemberJD",
    "RoleListItem",
    "RolePage",
    "RoleRef",
    "RoleView",
    "SourceJDView",
    "SourceListItem",
    "SourcePage",
    "collection_stats",
    "family_for",
    "get_role",
    "get_source_jd",
    "list_roles",
    "list_source_jds",
    "rank_candidates",
    "resolve_members",
    "score_text",
]
