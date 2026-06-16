"""F037: channel-list ReBAC evaluation reuses one shared per-request context.

``get_my_channels`` resolves effective permission ids for every channel in the
list. The user subject strings / bindings / models / binding index are identical
across all channels in a single request, so the optimization computes them once
(``_build_channel_permission_context``) and passes them to each
``get_effective_permission_ids_async`` call instead of letting it recompute them
per channel.

These tests lock the equivalence guarantee:
  1. the context builder delegates to *exactly* the FGPS helpers that
     ``get_effective_permission_ids_async`` falls back to when the kwargs are
     omitted -- so passing the context is equivalent to omitting it;
  2. ``get_my_channels`` forwards one and the same context to every channel.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.schemas.channel_manager_schema import (
    MyChannelQueryRequest,
    QueryTypeEnum,
    SortByEnum,
)
from bisheng.channel.domain.services import channel_service as channel_service_module
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.models.space_channel_member import MembershipStatusEnum, UserRoleEnum

_RP = "bisheng.permission.api.endpoints.resource_permission._get_bindings"
_FGPS = "bisheng.channel.domain.services.channel_service.FineGrainedPermissionService"


class _User:
    user_id = 7
    tenant_id = 1

    def is_admin(self):
        return False


def _service(channel_repository=None, member_repository=None):
    return ChannelService(
        channel_repository=channel_repository or SimpleNamespace(),
        space_channel_member_repository=member_repository or SimpleNamespace(),
        channel_info_source_repository=SimpleNamespace(),
        article_es_service=SimpleNamespace(
            count_articles=AsyncMock(return_value=0),
            count_articles_batch=AsyncMock(side_effect=lambda requests: [0] * len(requests)),
        ),
    )


@pytest.mark.asyncio
async def test_context_builder_delegates_to_fgps_fallback_sources():
    """Each context value must come from the same helper FGPS uses internally.

    If the builder ever diverges (inlines a different computation, drops a key,
    or transforms a value), sharing the context would change the evaluation
    result. Patching the helpers to sentinels proves the builder forwards them
    verbatim and derives ``binding_index`` from the shared bindings.
    """
    service = _service()
    user = _User()

    bindings = [
        {"resource_type": "channel", "resource_id": "ch-1", "subject_type": "user", "subject_id": 7},
        {"resource_type": "channel", "resource_id": "ch-2", "subject_type": "department", "subject_id": 3},
    ]
    models = {"m1": {"id": "m1", "permissions": ["view_channel"]}}
    subjects = {"user:7", "user_group:5#member"}
    dept_paths = {3: "/root/3"}

    with (
        patch(_RP, new=AsyncMock(return_value=bindings)),
        patch(f"{_FGPS}.get_relation_models_map", new=AsyncMock(return_value=models)),
        patch(f"{_FGPS}.get_current_user_subject_strings", new=AsyncMock(return_value=subjects)),
        patch(f"{_FGPS}.get_binding_department_paths", new=AsyncMock(return_value=dept_paths)),
    ):
        ctx = await service._build_channel_permission_context(user)

    # Same objects FGPS would have produced from its None-fallbacks.
    assert ctx["bindings"] == bindings
    assert ctx["models"] is models
    assert ctx["user_subject_strings"] is subjects
    assert ctx["binding_department_paths"] is dept_paths
    # binding_index is the canonical index of the *same* shared bindings.
    assert ctx["binding_index"] == channel_service_module.FineGrainedPermissionService.build_binding_index(bindings)
    # No object-specific lineage leaks into the shared context.
    assert "lineage" not in ctx


@pytest.mark.asyncio
async def test_get_my_channels_forwards_one_shared_context_to_every_channel():
    """Every per-channel evaluation in a list request receives the same context."""
    channels = [
        SimpleNamespace(
            id=f"ch-{i}",
            name=f"频道{i}",
            source_list=[],
            filter_rules=[],
            visibility=ChannelVisibilityEnum.PUBLIC,
            is_released=True,
            latest_article_update_time=None,
            create_time=None,
            user_id=999,
            is_pinned=False,
        )
        for i in range(3)
    ]
    channel_repository = SimpleNamespace(find_channels_by_ids=AsyncMock(return_value=channels))
    member_repository = SimpleNamespace(
        find_channel_memberships=AsyncMock(
            return_value=[
                SimpleNamespace(
                    business_id=c.id,
                    user_role=UserRoleEnum.CREATOR,
                    relation=None,
                    is_pinned=False,
                    status=MembershipStatusEnum.ACTIVE,
                    create_time=None,
                    update_time=None,
                )
                for c in channels
            ]
        )
    )
    service = _service(channel_repository, member_repository)
    service._calculate_unread_count = AsyncMock(return_value=0)

    sentinel_ctx = {
        "models": {},
        "bindings": [],
        "binding_department_paths": {},
        "user_subject_strings": {"user:7"},
        "binding_index": {},
    }
    service._build_channel_permission_context = AsyncMock(return_value=sentinel_ctx)

    seen_kwargs: list[dict] = []

    async def _capture(login_user, object_type, object_id, **kwargs):
        seen_kwargs.append(kwargs)
        return {"view_channel"}

    with patch(f"{_FGPS}.get_effective_permission_ids_async", new=AsyncMock(side_effect=_capture)):
        result = await service.get_my_channels(
            MyChannelQueryRequest(query_type=QueryTypeEnum.CREATED, sort_by=SortByEnum.LATEST_UPDATE),
            _User(),
        )

    # One eval per channel, and every call got the identical shared context.
    assert len(seen_kwargs) == len(channels)
    for kwargs in seen_kwargs:
        assert kwargs["models"] is sentinel_ctx["models"]
        assert kwargs["bindings"] is sentinel_ctx["bindings"]
        assert kwargs["binding_department_paths"] is sentinel_ctx["binding_department_paths"]
        assert kwargs["user_subject_strings"] is sentinel_ctx["user_subject_strings"]
        assert kwargs["binding_index"] is sentinel_ctx["binding_index"]
        # lineage stays object-specific (omitted -> FGPS builds it per channel).
        assert "lineage" not in kwargs
    assert {item.id for item in result} == {c.id for c in channels}
