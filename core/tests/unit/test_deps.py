"""RBAC gate (ADR-008): require_roles passes a user holding any allowed role and 403s
otherwise. Pure logic — a hand-built User, no DB, no FastAPI DI (the dependency's inner
function is called directly with the resolved user)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.db.models import Role, User, UserRole
from src.api.deps import require_roles


def _user(*roles: Role) -> User:
    return User(
        cas_username="u",
        display_name="U",
        roles=[UserRole(role=r) for r in roles],
    )


async def test_user_with_an_allowed_role_passes() -> None:
    user = _user(Role.REVIEWER)
    gate = require_roles(Role.REVIEWER, Role.ADMIN)
    assert await gate(user=user) is user  # type: ignore[call-arg]


async def test_user_without_an_allowed_role_is_forbidden() -> None:
    user = _user(Role.AUTHOR)
    gate = require_roles(Role.REVIEWER, Role.ADMIN)
    with pytest.raises(HTTPException) as exc:
        await gate(user=user)  # type: ignore[call-arg]
    assert exc.value.status_code == 403
    assert "reviewer" in str(exc.value.detail)


async def test_admin_plus_reviewer_user_passes_a_reviewer_gate() -> None:
    user = _user(Role.ADMIN, Role.REVIEWER)
    assert await require_roles(Role.REVIEWER)(user=user) is user  # type: ignore[call-arg]


async def test_a_roleless_user_is_forbidden_everywhere() -> None:
    user = _user()
    with pytest.raises(HTTPException) as exc:
        await require_roles(Role.AUTHOR)(user=user)  # type: ignore[call-arg]
    assert exc.value.status_code == 403
