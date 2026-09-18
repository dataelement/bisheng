from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from bisheng.knowledge.domain.models.knowledge_recycle_item import KnowledgeRecycleItem
from bisheng.knowledge.domain.services.knowledge_recycle_service import KnowledgeRecycleService


@pytest.mark.parametrize(
    ("name_keyword", "space_level", "page", "expected_names", "expected_total"),
    [
        ("  信息  ", "team", 2, ["信息报告乙.pdf"], 2),
        ("信息", "personal", 1, ["信息报告丙.pdf"], 1),
        ("%_", None, 1, ["进度100%_确认.pdf"], 1),
        ("不存在", None, 1, [], 0),
        ("   ", "team", 1, ["信息报告甲.pdf"], 4),
    ],
)
async def test_name_search_filters_before_pagination(
    name_keyword, space_level, page, expected_names, expected_total
):
    engine = create_engine("sqlite://")
    KnowledgeRecycleItem.__table__.create(engine)
    now = datetime(2026, 9, 17)
    rows = [
        ("信息报告甲.pdf", "team", True),
        ("信息报告乙.pdf", "team_ks", True),
        ("信息报告丙.pdf", "personal", True),
        ("其他.pdf", "team", True),
        ("进度100%_确认.pdf", "team", True),
        ("信息子文件.pdf", "team", False),
    ]
    with Session(engine) as session:
        for index, (name, level, listed) in enumerate(rows, 1):
            session.add(KnowledgeRecycleItem(
                id=index, tenant_id=1, file_id=index, knowledge_id=1,
                display_name=name, space_level=level, is_list_entry=listed,
                original_knowledge_id=1, original_path="/信息目录/" + name,
                file_encoding="信息编码", deleted_by=1,
                deleted_at=now - timedelta(minutes=index), expire_at=now + timedelta(days=7),
                recycle_batch_id=str(index), recycle_root_id=index,
            ))
        session.commit()

        @asynccontextmanager
        async def fake_session():
            yield SimpleNamespace(
                scalar=AsyncMock(side_effect=session.scalar),
                execute=AsyncMock(side_effect=session.execute),
            )

        service = KnowledgeRecycleService(SimpleNamespace(is_admin=lambda: True))
        module = "bisheng.knowledge.domain.services.knowledge_recycle_service"
        with (
            patch(f"{module}.get_async_db_session", fake_session),
            patch(f"{module}.KnowledgeDao.aquery_by_id", AsyncMock(return_value=None)),
            patch.object(service, "_can_restore_original", AsyncMock(return_value=True)),
        ):
            result = await service.list_items(
                name_keyword=name_keyword, space_level=space_level, page=page, page_size=1,
            )
        assert [item.name for item in result.data] == expected_names
        assert result.total == expected_total
    engine.dispose()
