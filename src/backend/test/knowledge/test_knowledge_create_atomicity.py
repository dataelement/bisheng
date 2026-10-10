"""A knowledge base must not outlive a failure to build its permission mirror.

The business row and the permission mirror live in different places and cannot
share a transaction, so the row used to be committed first and the mirror built
afterwards. When the mirror could not be built the create call failed, but the
row stayed, and what it left behind could not be used or removed: every
permission question about it answered "Resource permission projection is not
current", and deleting also asks the permission layer first.

A live tenant collected seven of these in one afternoon while the permission
runtime refused to start after an authorization-model change. Creating a
knowledge base looked like it failed each time; seven rows stayed.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

KNOWLEDGE_ID = 4274


def _login_user() -> SimpleNamespace:
    return SimpleNamespace(user_id=3, tenant_id=1)


def _inserted() -> Knowledge:
    # QA skips vector and search index creation, which this test is not about.
    return Knowledge(
        id=KNOWLEDGE_ID,
        name="123123123",
        type=KnowledgeTypeEnum.QA.value,
        user_id=3,
        tenant_id=1,
    )


async def test_a_failed_permission_mirror_takes_the_row_back_out() -> None:
    deleted = AsyncMock()

    with (
        patch.object(KnowledgeDao, "async_insert_one", AsyncMock(return_value=_inserted())),
        patch.object(KnowledgeDao, "async_delete_knowledge", deleted),
        patch.object(
            KnowledgeService,
            "_project_library_created",
            AsyncMock(side_effect=RuntimeError("authorization_model_migration_required")),
        ),
    ):
        with pytest.raises(RuntimeError):
            await KnowledgeService.acreate_knowledge_base(
                MagicMock(),
                _login_user(),
                _inserted(),
            )

    deleted.assert_awaited_once_with(KNOWLEDGE_ID)


async def test_a_successful_create_keeps_the_row() -> None:
    deleted = AsyncMock()

    with (
        patch.object(KnowledgeDao, "async_insert_one", AsyncMock(return_value=_inserted())),
        patch.object(KnowledgeDao, "async_delete_knowledge", deleted),
        patch.object(KnowledgeService, "_project_library_created", AsyncMock()),
        patch.object(KnowledgeService, "audit_telemetry_service", MagicMock()),
    ):
        created = await KnowledgeService.acreate_knowledge_base(
            MagicMock(),
            _login_user(),
            _inserted(),
        )

    assert created.id == KNOWLEDGE_ID
    deleted.assert_not_awaited()


async def test_the_mirror_is_built_before_any_external_store() -> None:
    """Ordering is the point: an undone create must leave nothing behind.

    Index creation is best-effort and swallows its own errors, so a mirror
    failure after it would leak a vector collection and a search index for a
    row that no longer exists. This one uses a normal knowledge base, not QA,
    precisely so the index path really runs.
    """

    order: list[str] = []

    async def _project(*_args, **_kwargs):
        order.append("mirror")

    async def _milvus(*_args, **_kwargs):
        order.append("milvus")
        return MagicMock()

    async def _es(*_args, **_kwargs):
        order.append("es")
        return MagicMock()

    normal = _inserted()
    normal.type = KnowledgeTypeEnum.NORMAL.value

    with (
        patch.object(KnowledgeDao, "async_insert_one", AsyncMock(return_value=normal)),
        patch.object(KnowledgeService, "_project_library_created", _project),
        patch.object(KnowledgeService, "ensure_milvus_schema_ready", MagicMock()),
        patch.object(KnowledgeService, "audit_telemetry_service", MagicMock()),
        patch(
            "bisheng.knowledge.domain.services.knowledge_service.KnowledgeRag.init_knowledge_milvus_vectorstore",
            _milvus,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_service.KnowledgeRag.init_knowledge_es_vectorstore",
            _es,
        ),
    ):
        await KnowledgeService.acreate_knowledge_base(MagicMock(), _login_user(), normal)

    assert order and order[0] == "mirror", order
    assert "milvus" in order, order


async def test_skip_hook_still_skips_the_mirror() -> None:
    """The caller that opts out of the hook owns the mirror itself."""

    project = AsyncMock()

    with (
        patch.object(KnowledgeDao, "async_insert_one", AsyncMock(return_value=_inserted())),
        patch.object(KnowledgeService, "_project_library_created", project),
    ):
        await KnowledgeService.acreate_knowledge_base(
            MagicMock(),
            _login_user(),
            _inserted(),
            skip_hook=True,
        )

    project.assert_not_awaited()
