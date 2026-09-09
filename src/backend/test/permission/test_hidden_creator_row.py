"""Where the authorization panel withholds the protected creator row.

COFCO customisation. A channel never shows one — ownership is implicit and the
row cannot be edited, so it is only noise. A department knowledge space never
shows one for a stronger reason: `Knowledge.user_id` records the super admin who operated
the creation, for auditing only; the space's responsible figure is its single
space admin, surfaced through the manager grant. The panel listed the creator as
a protected owner nobody could remove, putting the operating super admin back in
front of every department space.

The rule existed and was lost: `ceafce0e76` skipped the synthesis in the old
`/permissions` endpoint, and F048 replaced that whole endpoint with the unified
grant API, taking the customisation with it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.permission.application.resource_api import F048ResourcePermissionApi

_SPACE_ID = "156"
_DEPARTMENT_BINDING = SimpleNamespace(space_id=156, department_id=7)


def _row(source_id: int, source_type: str):
    return SimpleNamespace(
        source_id=source_id,
        source_type=source_type,
        subject_type="user",
        subject_id="1",
        protected=source_type == "CREATOR",
        editable=source_type != "CREATOR",
    )


_ROWS = [_row(1, "DIRECT"), _row(2, "CREATOR")]


def _binding(found):
    return patch(
        "bisheng.knowledge.domain.models.department_knowledge_space.DepartmentKnowledgeSpaceDao.aget_by_space_id",
        AsyncMock(return_value=_DEPARTMENT_BINDING if found else None),
    )


async def test_a_department_space_withholds_the_creator_row():
    with _binding(True):
        rows = await F048ResourcePermissionApi._without_hidden_creator_row(
            resource_type="knowledge_space",
            resource_id=_SPACE_ID,
            rows=_ROWS,
        )

    assert [row.source_type for row in rows] == ["DIRECT"]


async def test_an_ordinary_space_keeps_its_creator():
    with _binding(False):
        rows = await F048ResourcePermissionApi._without_hidden_creator_row(
            resource_type="knowledge_space",
            resource_id=_SPACE_ID,
            rows=_ROWS,
        )

    assert [row.source_type for row in rows] == ["DIRECT", "CREATOR"]


async def test_a_channel_always_withholds_the_creator_row():
    """Ownership is implicit and the row cannot be edited — it is only noise."""
    lookup = AsyncMock(return_value=_DEPARTMENT_BINDING)
    with patch(
        "bisheng.knowledge.domain.models.department_knowledge_space.DepartmentKnowledgeSpaceDao.aget_by_space_id",
        lookup,
    ):
        rows = await F048ResourcePermissionApi._without_hidden_creator_row(
            resource_type="channel",
            resource_id="70b0130ff3344001b368891803520eee",
            rows=_ROWS,
        )

    assert [row.source_type for row in rows] == ["DIRECT"]
    # A channel has no department binding to consult.
    lookup.assert_not_awaited()


@pytest.mark.parametrize(
    ("resource_type", "resource_id"),
    [
        ("workflow", "41ceff840cd741fb92fdb9d9cf41f967"),
        ("knowledge_space", "not-a-number"),
    ],
)
async def test_other_resources_are_untouched_and_never_queried(resource_type, resource_id):
    """Only a numeric knowledge space can carry a department binding."""
    lookup = AsyncMock(return_value=_DEPARTMENT_BINDING)
    with patch(
        "bisheng.knowledge.domain.models.department_knowledge_space.DepartmentKnowledgeSpaceDao.aget_by_space_id",
        lookup,
    ):
        rows = await F048ResourcePermissionApi._without_hidden_creator_row(
            resource_type=resource_type,
            resource_id=resource_id,
            rows=_ROWS,
        )

    assert rows is _ROWS
    lookup.assert_not_awaited()
