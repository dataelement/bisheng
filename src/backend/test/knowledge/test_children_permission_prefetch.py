"""F046 — file-menu permission prefetch.

The visibility fast-path (`_filter_visible_child_items`) already computes each
item's effective action permissions; F046 exposes them through the optional
``collect_permission_ids`` sink so the children/search listings can attach them
per item. These tests pin the four collection branches (spec AC-01/AC-04):

  - normal item      -> inherited ancestor-chain ids
  - bound item       -> its own per-item evaluation
  - uploader-owned   -> chain ids ∪ owner defaults (rename/delete own file)
  - bypassed context -> nothing collected (client falls back to lazy checks)
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.knowledge_space_permission_template import (
    default_permission_ids_for_relation,
)

_USER_ID = 5
_SPACE_ID = 101


def _service() -> KnowledgeSpaceService:
    return KnowledgeSpaceService(
        request=SimpleNamespace(),
        login_user=SimpleNamespace(user_id=_USER_ID, user_name="u5", tenant_id=1, is_admin=lambda: False),
    )


def _file(file_id: int, *, user_id: int = 999, file_type: int = 1, path: str = "/1"):
    return SimpleNamespace(
        id=file_id,
        file_type=file_type,
        user_id=user_id,
        file_level_path=path,
    )


def _context(bound: set[tuple[str, str]] | None = None) -> dict:
    return {
        "read_permission_bypassed": False,
        "binding_index": {key: object() for key in (bound or set())},
    }


CHAIN_IDS = {"view_file", "view_folder", "download_file", "download_folder"}
BOUND_IDS = {"view_file"}  # visible but no download — the fine-grained deny case


async def test_normal_item_collects_inherited_chain_ids():
    svc = _service()
    collected: dict[int, list[str]] = {}
    with (
        patch.object(svc, "_chain_effective_permission_ids", new=AsyncMock(return_value=set(CHAIN_IDS))),
        patch.object(svc, "_get_child_item_effective_permission_ids", new=AsyncMock()) as per_item,
    ):
        visible = await svc._filter_visible_child_items(
            [_file(11)],
            space_id=_SPACE_ID,
            context=_context(),
            collect_permission_ids=collected,
        )
    assert [f.id for f in visible] == [11]
    assert collected[11] == sorted(CHAIN_IDS)
    per_item.assert_not_awaited()  # normal items never pay the per-item eval


async def test_bound_item_collects_its_own_evaluation():
    svc = _service()
    collected: dict[int, list[str]] = {}
    with (
        patch.object(svc, "_chain_effective_permission_ids", new=AsyncMock(return_value=set(CHAIN_IDS))),
        patch.object(
            svc,
            "_get_child_item_effective_permission_ids",
            new=AsyncMock(return_value=set(BOUND_IDS)),
        ),
    ):
        visible = await svc._filter_visible_child_items(
            [_file(12)],
            space_id=_SPACE_ID,
            context=_context(bound={("knowledge_file", "12")}),
            collect_permission_ids=collected,
        )
    assert [f.id for f in visible] == [12]
    # The fine-grained result wins — download_file absent even though the chain has it.
    assert collected[12] == sorted(BOUND_IDS)


async def test_owned_item_collects_chain_plus_owner_defaults():
    svc = _service()
    collected: dict[int, list[str]] = {}
    with patch.object(svc, "_chain_effective_permission_ids", new=AsyncMock(return_value=set(CHAIN_IDS))):
        visible = await svc._filter_visible_child_items(
            [_file(13, user_id=_USER_ID)],
            space_id=_SPACE_ID,
            context=_context(),
            collect_permission_ids=collected,
        )
    assert [f.id for f in visible] == [13]
    expected = sorted(CHAIN_IDS | default_permission_ids_for_relation("owner"))
    assert collected[13] == expected
    assert "rename_file" in collected[13]  # owner additive grant surfaces


async def test_invisible_item_is_dropped_and_not_collected():
    svc = _service()
    collected: dict[int, list[str]] = {}
    with patch.object(
        svc,
        "_chain_effective_permission_ids",
        new=AsyncMock(return_value={"download_file"}),  # no view_file -> invisible
    ):
        visible = await svc._filter_visible_child_items(
            [_file(14)],
            space_id=_SPACE_ID,
            context=_context(),
            collect_permission_ids=collected,
        )
    assert visible == []
    assert collected == {}


async def test_bypassed_context_collects_nothing():
    svc = _service()
    collected: dict[int, list[str]] = {}
    items = [_file(15)]
    visible = await svc._filter_visible_child_items(
        items,
        space_id=_SPACE_ID,
        context={"read_permission_bypassed": True},
        collect_permission_ids=collected,
    )
    assert visible == items  # unfiltered passthrough, unchanged behavior
    assert collected == {}  # null on the wire -> client lazy fallback


async def test_collection_is_opt_in():
    """Callers that do not pass the sink (QA/citation paths) see zero behavior change."""
    svc = _service()
    with patch.object(svc, "_chain_effective_permission_ids", new=AsyncMock(return_value=set(CHAIN_IDS))):
        visible = await svc._filter_visible_child_items(
            [_file(16)],
            space_id=_SPACE_ID,
            context=_context(),
        )
    assert [f.id for f in visible] == [16]


@pytest.mark.parametrize("present", [True, False])
async def test_listing_attaches_permission_ids_per_item(present):
    """list_space_children maps collected ids onto the response dicts; absent -> None."""
    collected = {21: ["download_file", "view_file"]} if present else {}
    data = [{"id": 21, "file_type": 1}]
    for item in data:
        item["permission_ids"] = collected.get(int(item["id"]))
    assert data[0]["permission_ids"] == (["download_file", "view_file"] if present else None)
