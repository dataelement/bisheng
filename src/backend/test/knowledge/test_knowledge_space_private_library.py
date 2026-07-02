"""Service-layer tests for the auto-tag custom-tags / private-library flow.

These cover the resolve/cleanup behaviour newly added to
``KnowledgeSpaceService`` plus the response decorator. Heavy collaborators
(workstation config, DAO writes) are mocked — the DAO itself is covered by
its own DB-backed tests.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge import KnowledgeSpaceTagLibraryInvalidError
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_tag_library import (
    KnowledgeSpaceTagLibrary,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    KnowledgeSpaceInfoResp,
)
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
)


def _make_space(space_id: int = 42) -> Knowledge:
    return Knowledge(
        id=space_id,
        name="space",
        type=KnowledgeTypeEnum.SPACE.value,
        tenant_id=1,
        user_id=7,
    )


# ──────────────────────────── _apply_auto_tag_binding ──────────────────────────


@pytest.mark.asyncio
async def test_apply_disabled_binds_public_libraries_without_auto_tag():
    space = _make_space()

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeSpaceTagLibraryDao.adelete_private_for_knowledge",
            new=AsyncMock(),
        ) as delete_private,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeSpaceTagLibraryService.validate_bindable_libraries",
            new=AsyncMock(),
        ) as validate,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeTagLibraryLinkDao.areplace_for_knowledge",
            new=AsyncMock(),
        ) as replace_links,
    ):
        enabled, library_id = await KnowledgeSpaceService._apply_auto_tag_binding(
            knowledge=space,
            auto_tag_enabled=False,
            auto_tag_library_id=99,
            auto_tag_custom_tags=["should", "be", "ignored"],
            user_id=7,
            tenant_id=1,
        )

    assert enabled is False
    assert library_id == 99
    delete_private.assert_awaited_once_with(space.id)
    validate.assert_awaited_once_with([99])
    replace_links.assert_awaited_once_with(space.id, 1, [99])


@pytest.mark.asyncio
async def test_apply_disabled_preserves_links_when_library_fields_omitted():
    space = _make_space()

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeSpaceTagLibraryDao.adelete_private_for_knowledge",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge",
            new=AsyncMock(return_value=[12, 15]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeTagLibraryLinkDao.areplace_for_knowledge",
            new=AsyncMock(),
        ) as replace_links,
    ):
        enabled, library_id = await KnowledgeSpaceService._apply_auto_tag_binding(
            knowledge=space,
            auto_tag_enabled=False,
            auto_tag_library_id=None,
            auto_tag_library_ids=None,
            auto_tag_custom_tags=None,
            user_id=7,
            tenant_id=1,
        )

    assert enabled is False
    assert library_id == 12
    replace_links.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_rejects_both_library_and_custom_tags():
    space = _make_space()

    with pytest.raises(KnowledgeSpaceTagLibraryInvalidError):
        await KnowledgeSpaceService._apply_auto_tag_binding(
            knowledge=space,
            auto_tag_enabled=True,
            auto_tag_library_id=10,
            auto_tag_custom_tags=["x"],
            user_id=7,
            tenant_id=1,
        )


@pytest.mark.asyncio
async def test_apply_custom_tags_upserts_private_and_returns_its_id():
    space = _make_space()
    private = KnowledgeSpaceTagLibrary(
        id=555,
        tenant_id=1,
        name="__private__42",
        tags=["合同", "制度"],
        tag_count=2,
        owner_knowledge_id=space.id,
        user_id=7,
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceTagLibraryDao.aupsert_private",
            new=AsyncMock(return_value=private),
        ) as upsert,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeTagLibraryLinkDao.areplace_for_knowledge",
            new=AsyncMock(),
        ) as replace_links,
    ):
        enabled, library_id = await KnowledgeSpaceService._apply_auto_tag_binding(
            knowledge=space,
            auto_tag_enabled=True,
            auto_tag_library_id=None,
            auto_tag_custom_tags=[" 合同 ", "", "制度", "合同"],
            user_id=7,
            tenant_id=1,
        )

    assert enabled is True
    assert library_id == 555
    # normalize_tags trims + drops empties but keeps duplicates so the LLM
    # sees the exact candidate list users typed.
    args, kwargs = upsert.await_args
    assert kwargs["knowledge_id"] == space.id
    assert kwargs["tenant_id"] == 1
    assert kwargs["user_id"] == 7
    assert kwargs["tags"] == ["合同", "制度", "合同"]
    replace_links.assert_awaited_once_with(space.id, 1, [555])


@pytest.mark.asyncio
async def test_apply_custom_tags_rejects_empty_after_normalize():
    space = _make_space()

    with pytest.raises(KnowledgeSpaceTagLibraryInvalidError):
        await KnowledgeSpaceService._apply_auto_tag_binding(
            knowledge=space,
            auto_tag_enabled=True,
            auto_tag_library_id=None,
            auto_tag_custom_tags=["", "  "],
            user_id=7,
            tenant_id=1,
        )


@pytest.mark.asyncio
async def test_apply_library_mode_validates_and_clears_orphan_private():
    space = _make_space()

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeSpaceTagLibraryService.validate_bindable_libraries",
            new=AsyncMock(),
        ) as validate,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeSpaceTagLibraryDao.adelete_private_for_knowledge",
            new=AsyncMock(),
        ) as delete_private,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeTagLibraryLinkDao.areplace_for_knowledge",
            new=AsyncMock(),
        ) as replace_links,
    ):
        enabled, library_id = await KnowledgeSpaceService._apply_auto_tag_binding(
            knowledge=space,
            auto_tag_enabled=True,
            auto_tag_library_id=10,
            auto_tag_custom_tags=None,
            user_id=7,
            tenant_id=1,
        )

    assert enabled is True
    assert library_id == 10
    validate.assert_awaited_once_with([10])
    delete_private.assert_awaited_once_with(space.id)
    replace_links.assert_awaited_once_with(space.id, 1, [10])


# ──────────────────────────── _decorate_auto_tag_for_info ──────────────────────


@pytest.mark.asyncio
async def test_decorate_no_library_sets_library_mode_and_clears_tags():
    result = KnowledgeSpaceInfoResp(
        id=42,
        name="space",
        type=KnowledgeTypeEnum.SPACE.value,
        auto_tag_library_id=None,
        auto_tag_custom_tags=["leftover"],
    )

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service."
        "KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge",
        new=AsyncMock(return_value=[]),
    ):
        await KnowledgeSpaceService._decorate_auto_tag_for_info(result)

    assert result.auto_tag_mode == "library"
    assert result.auto_tag_custom_tags is None
    assert result.auto_tag_library_id is None


@pytest.mark.asyncio
async def test_decorate_private_library_masks_id_and_returns_tags():
    result = KnowledgeSpaceInfoResp(
        id=42,
        name="space",
        type=KnowledgeTypeEnum.SPACE.value,
        auto_tag_library_id=555,
    )
    private = KnowledgeSpaceTagLibrary(
        id=555,
        tenant_id=1,
        name="__private__42",
        tags=["合同", "制度"],
        tag_count=2,
        owner_knowledge_id=42,
        user_id=7,
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(return_value=private),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.TagLibraryTagService.list_tag_names",
            new=AsyncMock(return_value=(["合同", "制度"], [], [])),
        ),
    ):
        await KnowledgeSpaceService._decorate_auto_tag_for_info(result)

    assert result.auto_tag_mode == "custom"
    assert result.auto_tag_custom_tags == ["合同", "制度"]
    # Private library id must never reach the client.
    assert result.auto_tag_library_id is None


@pytest.mark.asyncio
async def test_decorate_public_library_keeps_id_and_marks_library_mode():
    result = KnowledgeSpaceInfoResp(
        id=42,
        name="space",
        type=KnowledgeTypeEnum.SPACE.value,
        auto_tag_library_id=10,
    )
    public = KnowledgeSpaceTagLibrary(
        id=10,
        tenant_id=1,
        name="业务标签",
        tags=["合同"],
        tag_count=1,
        owner_knowledge_id=None,
        user_id=7,
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(return_value=public),
        ),
    ):
        await KnowledgeSpaceService._decorate_auto_tag_for_info(result)

    assert result.auto_tag_mode == "library"
    assert result.auto_tag_custom_tags is None
    assert result.auto_tag_library_id == 10
    assert result.auto_tag_library_ids == [10]


@pytest.mark.asyncio
async def test_decorate_private_library_owned_by_other_space_treated_as_library():
    """Defensive: if a space somehow points at another space's private library
    we must not leak its tags. Falls back to library mode and exposes only the
    raw id so audits can spot the inconsistency."""
    result = KnowledgeSpaceInfoResp(
        id=42,
        name="space",
        type=KnowledgeTypeEnum.SPACE.value,
        auto_tag_library_id=999,
    )
    foreign_private = KnowledgeSpaceTagLibrary(
        id=999,
        tenant_id=1,
        name="__private__7",
        tags=["secret"],
        tag_count=1,
        owner_knowledge_id=7,
        user_id=7,
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(return_value=foreign_private),
        ),
    ):
        await KnowledgeSpaceService._decorate_auto_tag_for_info(result)

    assert result.auto_tag_mode == "library"
    assert result.auto_tag_custom_tags is None
    assert result.auto_tag_library_id == 999


# ──────────────────────────── visibility gate ──────────────────────────────────


@pytest.mark.asyncio
async def test_visibility_gate_defaults_to_visible_when_config_missing():
    import bisheng.knowledge.domain.services.knowledge_space_service as svc

    fake_workstation = SimpleNamespace(
        get_knowledge_space_config_with_meta=AsyncMock(return_value=(None, False, "", False))
    )
    with patch.object(svc, "WorkStationService", fake_workstation):
        assert await KnowledgeSpaceService._is_auto_tag_feature_visible() is True


@pytest.mark.asyncio
async def test_visibility_gate_honours_auto_tag_visible_flag():
    import bisheng.knowledge.domain.services.knowledge_space_service as svc

    cfg = SimpleNamespace(auto_tag_visible=True)
    fake_workstation = SimpleNamespace(
        get_knowledge_space_config_with_meta=AsyncMock(return_value=(cfg, False, "", True))
    )
    with patch.object(svc, "WorkStationService", fake_workstation):
        assert await KnowledgeSpaceService._is_auto_tag_feature_visible() is True


@pytest.mark.asyncio
async def test_visibility_gate_honours_explicit_auto_tag_hidden_flag():
    import bisheng.knowledge.domain.services.knowledge_space_service as svc

    cfg = SimpleNamespace(auto_tag_visible=False)
    fake_workstation = SimpleNamespace(
        get_knowledge_space_config_with_meta=AsyncMock(return_value=(cfg, False, "", True))
    )
    with patch.object(svc, "WorkStationService", fake_workstation):
        assert await KnowledgeSpaceService._is_auto_tag_feature_visible() is False
