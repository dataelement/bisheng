from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _department(
    *,
    department_id: int,
    name: str,
    short_name: str | None,
    parent_id: int | None,
    path: str,
):
    return SimpleNamespace(
        id=department_id,
        dept_id=f"BS@{department_id}",
        name=name,
        short_name=short_name,
        parent_id=parent_id,
        path=path,
        sort_order=0,
    )


@pytest.mark.asyncio
async def test_create_department_options_keep_official_names_and_add_display_paths() -> None:
    departments = [
        _department(
            department_id=1,
            name="首钢集团",
            short_name="首钢",
            parent_id=None,
            path="/1/",
        ),
        _department(
            department_id=18,
            name="技术研发中心",
            short_name=" 研发 ",
            parent_id=1,
            path="/1/18/",
        ),
    ]
    service = KnowledgeSpaceService(
        request=SimpleNamespace(),
        login_user=SimpleNamespace(user_id=7, tenant_id=1, is_admin=lambda: True),
    )
    service._visible_departments_for_create = AsyncMock(return_value=departments)

    options = await service._department_options_for_create()
    option = next(item for item in options if item.id == 18)

    assert option.name == "技术研发中心"
    assert option.short_name == "研发"
    assert option.display_name == "研发"
    assert option.path_name == "首钢集团/技术研发中心"
    assert option.display_path_name == "首钢/研发"


@pytest.mark.asyncio
async def test_create_department_tree_exposes_display_fields_without_extra_queries() -> None:
    departments = [
        _department(
            department_id=1,
            name="首钢集团",
            short_name=None,
            parent_id=None,
            path="/1/",
        ),
        _department(
            department_id=18,
            name="技术研发中心",
            short_name="研发",
            parent_id=1,
            path="/1/18/",
        ),
    ]

    class _Result:
        def all(self):
            return []

    class _Session:
        async def exec(self, _statement):
            return _Result()

    @asynccontextmanager
    async def _session():
        yield _Session()

    service = KnowledgeSpaceService(
        request=SimpleNamespace(),
        login_user=SimpleNamespace(user_id=7, tenant_id=1, is_admin=lambda: True),
    )
    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
        new=_session,
    ):
        tree = await service._build_department_tree(departments)

    child = tree[0]["children"][0]
    assert child["name"] == "技术研发中心"
    assert child["short_name"] == "研发"
    assert child["display_name"] == "研发"
