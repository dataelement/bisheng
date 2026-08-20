from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.permission.domain.services.resource_grant_executor_registry import (
    ResourceGrantExecutorRegistry,
)

F045_SCENARIO = "resource_user_invite_confirmation"
F046_SCENARIO = "knowledge_space_file_change_request"
REQUIRED_DECISION_SCENARIOS = frozenset({F045_SCENARIO, F046_SCENARIO})
REQUIRED_RESOURCE_TYPES = frozenset({"knowledge_space", "channel"})
REQUIRED_LEGACY_SCENARIOS = frozenset(
    {
        "menu_access_request",
        "channel_subscribe_request",
        "knowledge_space_subscribe_request",
    }
)


@dataclass(frozen=True, slots=True)
class ApprovalScenarioBootstrapComponents:
    policies: tuple[Any, ...]
    subscribers: tuple[Any, ...]
    legacy_handlers: tuple[tuple[str, Any], ...]
    resource_executor_registry: ResourceGrantExecutorRegistry
    resource_executors: dict[str, Any]


_approval_scenario_registry: ApprovalRegistry | None = None
_resource_grant_executor_registry: ResourceGrantExecutorRegistry | None = None


def bootstrap_approval_scenarios(
    *,
    component_factory: Callable[[], ApprovalScenarioBootstrapComponents] | None = None,
) -> ApprovalRegistry:
    """Synchronously assemble and freeze all approval runtime extensions."""

    global _approval_scenario_registry, _resource_grant_executor_registry
    if _approval_scenario_registry is not None:
        return _approval_scenario_registry
    components = (component_factory or _build_default_components)()
    registry = ApprovalRegistry.with_default_presets()
    for policy in components.policies:
        registry.register_policy(policy)
    for subscriber in components.subscribers:
        registry.register_subscriber(subscriber)

    seen_handlers: set[str] = set()
    for scenario_code, handler in components.legacy_handlers:
        if scenario_code in seen_handlers:
            raise ValueError(f"approval handler already registered for scenario_code={scenario_code}")
        seen_handlers.add(scenario_code)
        registry.register_handler(scenario_code, handler)
    missing_handlers = sorted(REQUIRED_LEGACY_SCENARIOS - seen_handlers)
    if missing_handlers:
        raise ValueError(f"approval legacy handler missing: {', '.join(missing_handlers)}")

    for resource_type, executor in components.resource_executors.items():
        components.resource_executor_registry.register(resource_type, executor)
    registry.freeze_decision_delivery(required_scenario_codes=set(REQUIRED_DECISION_SCENARIOS))
    components.resource_executor_registry.freeze(required_resource_types=set(REQUIRED_RESOURCE_TYPES))

    _configure_runtime_providers(registry)
    _resource_grant_executor_registry = components.resource_executor_registry
    _approval_scenario_registry = registry
    return registry


def get_approval_scenario_registry() -> ApprovalRegistry:
    if _approval_scenario_registry is None:
        raise RuntimeError("approval scenario registry is not bootstrapped")
    return _approval_scenario_registry


def get_resource_grant_executor_registry() -> ResourceGrantExecutorRegistry:
    if _resource_grant_executor_registry is None:
        raise RuntimeError("resource grant executor registry is not bootstrapped")
    return _resource_grant_executor_registry


def _configure_runtime_providers(registry: ApprovalRegistry) -> None:
    from bisheng.approval.api.dependencies import configure_approval_submission_port_factory
    from bisheng.approval.domain.services.approval_status_read_service import ApprovalStatusReadService
    from bisheng.approval.domain.services.approval_submission_service import ApprovalSubmissionService
    from bisheng.permission.domain.services.resource_user_invite_application_service import (
        configure_resource_user_invite_query_and_retry_factories,
        configure_resource_user_invite_submission_port_factory,
    )

    def submission_factory():
        return ApprovalSubmissionService(registry=registry)

    configure_approval_submission_port_factory(submission_factory)
    configure_resource_user_invite_submission_port_factory(submission_factory)
    configure_resource_user_invite_query_and_retry_factories(
        approval_status_port_factory=ApprovalStatusReadService,
        dispatcher_factory=_build_resource_user_invite_dispatcher,
    )


def _build_resource_user_invite_dispatcher():
    from bisheng.worker.permission.resource_user_invite_tasks import CeleryResourceUserInviteDispatcher

    return CeleryResourceUserInviteDispatcher()


def _build_default_components() -> ApprovalScenarioBootstrapComponents:
    from bisheng.approval.domain.services.channel_subscribe_scenario_handler import (
        ChannelSubscribeScenarioHandler,
    )
    from bisheng.approval.domain.services.knowledge_space_subscribe_scenario_handler import (
        KnowledgeSpaceSubscribeScenarioHandler,
    )
    from bisheng.approval.domain.services.menu_access_handler import MenuAccessApprovalHandler
    from bisheng.channel.domain.services.channel_authorization_service import (
        ChannelAuthorizationService,
        ChannelResourceGrantExecutor,
    )
    from bisheng.channel.domain.services.channel_service import ChannelService
    from bisheng.common.models.space_channel_member import SpaceChannelMemberDao
    from bisheng.knowledge.domain.services.knowledge_space_file_change_approval_policy import (
        KnowledgeSpaceFileChangeApprovalPolicy,
    )
    from bisheng.knowledge.domain.services.knowledge_space_file_change_decision_subscriber import (
        KnowledgeSpaceFileChangeDecisionSubscriber,
    )
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
    from bisheng.permission.domain.services.resource_authorization_service import (
        KnowledgeSpaceResourceGrantExecutor,
    )
    from bisheng.permission.domain.services.resource_user_invite_approval_policy import (
        ResourceUserInviteApprovalPolicy,
    )
    from bisheng.permission.domain.services.resource_user_invite_decision_subscriber import (
        ResourceUserInviteDecisionSubscriber,
    )

    channel_service = ChannelAuthorizationService(
        channel_repository=_SessionBackedChannelRepository(),
        space_channel_member_repository=_SessionBackedSpaceChannelMemberRepository(),
    )
    return ApprovalScenarioBootstrapComponents(
        policies=(
            ResourceUserInviteApprovalPolicy(),
            KnowledgeSpaceFileChangeApprovalPolicy(),
        ),
        subscribers=(
            ResourceUserInviteDecisionSubscriber(dispatcher=_LazyResourceUserInviteDispatcher()),
            KnowledgeSpaceFileChangeDecisionSubscriber(dispatcher=_LazyKnowledgeSpaceFileChangeDispatcher()),
        ),
        legacy_handlers=(
            ("menu_access_request", MenuAccessApprovalHandler()),
            (
                "channel_subscribe_request",
                ChannelSubscribeScenarioHandler(
                    _AsyncSpaceChannelMembershipAdapter(),
                    sync_permissions=ChannelService.sync_direct_channel_user_permissions,
                ),
            ),
            (
                "knowledge_space_subscribe_request",
                KnowledgeSpaceSubscribeScenarioHandler(
                    find_member=SpaceChannelMemberDao.async_find_member,
                    update_member=SpaceChannelMemberDao.update,
                    sync_permissions=KnowledgeSpaceService.sync_direct_space_user_permissions,
                ),
            ),
        ),
        resource_executor_registry=ResourceGrantExecutorRegistry(),
        resource_executors={
            "knowledge_space": KnowledgeSpaceResourceGrantExecutor(),
            "channel": ChannelResourceGrantExecutor(authorization_service=channel_service),
        },
    )


class _LazyResourceUserInviteDispatcher:
    async def dispatch(self, *, tenant_id: int, request_id: int) -> None:
        await _build_resource_user_invite_dispatcher().dispatch(
            tenant_id=tenant_id,
            request_id=request_id,
        )


class _LazyKnowledgeSpaceFileChangeDispatcher:
    async def dispatch(self, *, tenant_id: int, request_id: int) -> None:
        from bisheng.worker.knowledge.file_change_tasks import CeleryKnowledgeSpaceFileChangeDispatcher

        await CeleryKnowledgeSpaceFileChangeDispatcher().dispatch(
            tenant_id=tenant_id,
            request_id=request_id,
        )


class _SessionBackedChannelRepository:
    async def find_by_id(self, channel_id: str):
        from bisheng.channel.domain.repositories.implementations.channel_repository_impl import (
            ChannelRepositoryImpl,
        )
        from bisheng.core.database import get_async_db_session

        async with get_async_db_session() as session:
            return await ChannelRepositoryImpl(session).find_by_id(channel_id)


class _SessionBackedSpaceChannelMemberRepository:
    async def get_effective_channel_relation(self, channel_id: str, user_id: int):
        from bisheng.common.repositories.implementations.space_channel_member_repository_impl import (
            SpaceChannelMemberRepositoryImpl,
        )
        from bisheng.core.database import get_async_db_session

        async with get_async_db_session() as session:
            return await SpaceChannelMemberRepositoryImpl(session).get_effective_channel_relation(
                channel_id,
                user_id,
            )


class _AsyncSpaceChannelMembershipAdapter:
    async def find_membership(self, business_id, business_type, user_id):
        from bisheng.common.repositories.implementations.space_channel_member_repository_impl import (
            SpaceChannelMemberRepositoryImpl,
        )
        from bisheng.core.database import get_async_db_session

        async with get_async_db_session() as session:
            return await SpaceChannelMemberRepositoryImpl(session).find_membership(
                business_id=business_id,
                business_type=business_type,
                user_id=user_id,
                include_inactive=True,
            )

    async def update(self, membership):
        from bisheng.common.models.space_channel_member import SpaceChannelMemberDao

        return await SpaceChannelMemberDao.update(membership)

    async def delete(self, membership_id: int) -> bool:
        from bisheng.common.repositories.implementations.space_channel_member_repository_impl import (
            SpaceChannelMemberRepositoryImpl,
        )
        from bisheng.core.database import get_async_db_session

        async with get_async_db_session() as session:
            return await SpaceChannelMemberRepositoryImpl(session).delete(membership_id)


__all__ = [
    "ApprovalScenarioBootstrapComponents",
    "bootstrap_approval_scenarios",
    "get_approval_scenario_registry",
    "get_resource_grant_executor_registry",
]
