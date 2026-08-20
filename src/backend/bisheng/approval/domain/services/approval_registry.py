from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.approval.domain.ports.decision_subscriber import (
    APPROVAL_DECISION_EVENT_VERSION,
    APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION,
    ApprovalDecisionSubscriber,
)
from bisheng.approval.domain.ports.scenario_policy import (
    APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION,
    DECISION_DELIVERY_COMPLETION_MODE,
    ApprovalScenarioPolicy,
)
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalScenarioPreset
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session

SYSTEM_FILE_CHANGE_SCENARIO_CODE = "knowledge_space_file_change_request"
SYSTEM_FILE_CHANGE_FLOW_CODE = "knowledge_space_file_change_default_flow"
SYSTEM_FILE_CHANGE_APPROVER_SOURCES = [
    {"type": "knowledge_space_owner"},
    {"type": "knowledge_space_manager"},
]


async def _ensure_system_file_change_scenario_in_session(
    *,
    tenant_id: int,
    session: AsyncSession,
) -> ApprovalScenario:
    try:
        async with session.begin_nested():
            with bypass_tenant_filter():
                existing = (
                    await session.exec(
                        select(ApprovalScenario).where(
                            ApprovalScenario.tenant_id == tenant_id,
                            ApprovalScenario.scenario_code == SYSTEM_FILE_CHANGE_SCENARIO_CODE,
                        )
                    )
                ).first()
                if existing is not None:
                    return existing

                scenario = ApprovalScenario(
                    tenant_id=tenant_id,
                    scenario_code=SYSTEM_FILE_CHANGE_SCENARIO_CODE,
                    scenario_name="知识空间文件变更审批",
                    enabled=True,
                )
                session.add(scenario)
                await session.flush()
                await session.refresh(scenario)

                flow = ApprovalFlowDefinition(
                    tenant_id=tenant_id,
                    scenario_id=scenario.id,
                    flow_code=SYSTEM_FILE_CHANGE_FLOW_CODE,
                    flow_name="默认文件变更审批流程",
                    is_active=True,
                )
                session.add(flow)
                await session.flush()
                await session.refresh(flow)

                node_snapshot = {
                    "node_code": "knowledge_space_owner_manager",
                    "node_name": "知识空间负责人审批",
                    "node_order": 1,
                    "node_mode": "or",
                    "approver_config": {"sources": SYSTEM_FILE_CHANGE_APPROVER_SOURCES},
                }
                version = ApprovalFlowVersion(
                    tenant_id=tenant_id,
                    flow_definition_id=flow.id,
                    version_no=1,
                    is_active=True,
                    definition_snapshot={"nodes": [node_snapshot]},
                )
                session.add(version)
                await session.flush()
                await session.refresh(version)

                session.add(
                    ApprovalNodeDefinition(
                        tenant_id=tenant_id,
                        flow_version_id=version.id,
                        **node_snapshot,
                    )
                )
                session.add(
                    ApprovalRouteRule(
                        tenant_id=tenant_id,
                        scenario_id=scenario.id,
                        route_name="默认分支",
                        route_type="flow",
                        sort_order=1,
                        flow_definition_id=flow.id,
                        match_config={},
                        enabled=True,
                    )
                )
                await session.flush()
                return scenario
    except IntegrityError:
        # The savepoint owns the failed INSERT. The caller's outer transaction
        # remains active and must never be rolled back by this helper.
        with bypass_tenant_filter():
            existing = (
                await session.exec(
                    select(ApprovalScenario)
                    .where(
                        ApprovalScenario.tenant_id == tenant_id,
                        ApprovalScenario.scenario_code == SYSTEM_FILE_CHANGE_SCENARIO_CODE,
                    )
                    .with_for_update()
                )
            ).first()
        if existing is None:
            raise
        return existing


async def ensure_system_file_change_scenario(
    *,
    tenant_id: int,
    session: AsyncSession | None = None,
) -> ApprovalScenario:
    """Create the immutable F046 approval bundle once for a tenant."""
    if session is not None:
        return await _ensure_system_file_change_scenario_in_session(
            tenant_id=tenant_id,
            session=session,
        )

    async with get_async_db_session() as owned_session:
        scenario = await ensure_system_file_change_scenario(
            tenant_id=tenant_id,
            session=owned_session,
        )
        await owned_session.commit()
        return scenario


class ApprovalRegistry:
    def __init__(self) -> None:
        self._presets: dict[str, ApprovalScenarioPreset] = {}
        self._hidden_preset_codes: set[str] = set()
        self._handlers: dict[str, Any] = {}
        self._policies: dict[str, ApprovalScenarioPolicy] = {}
        self._subscribers: dict[str, ApprovalDecisionSubscriber] = {}
        self._decision_delivery_frozen = False

    @classmethod
    def with_default_presets(cls) -> ApprovalRegistry:
        registry = cls()
        registry.register_preset(
            ApprovalScenarioPreset(
                scenario_code="menu_access_request",
                scenario_name="菜单权限申请",
                handler_key="menu_access_request",
                # applicant_role: admin / dept_admin / regular_user
                # menu_key: specific menu key from payload_snapshot
                condition_fields=["applicant_role", "menu_key"],
                approver_source_types=["direct_user", "department_admin"],
            )
        )
        registry.register_preset(
            ApprovalScenarioPreset(
                scenario_code="channel_subscribe_request",
                scenario_name="频道订阅审批",
                handler_key="channel_subscribe_request",
                condition_fields=["applicant_role"],
                approver_source_types=["direct_user", "department_admin", "channel_owner", "channel_manager"],
            )
        )
        registry.register_preset(
            ApprovalScenarioPreset(
                scenario_code="knowledge_space_subscribe_request",
                scenario_name="知识空间加入审批",
                handler_key="knowledge_space_subscribe_request",
                condition_fields=["applicant_role"],
                approver_source_types=[
                    "direct_user",
                    "department_admin",
                    "knowledge_space_owner",
                    "knowledge_space_manager",
                ],
            )
        )
        registry.register_preset(
            ApprovalScenarioPreset(
                scenario_code="resource_user_invite_confirmation",
                scenario_name="知识空间用户邀请确认",
                handler_key="resource_user_invite_confirmation",
                condition_fields=[],
                approver_source_types=["invited_user"],
            )
        )
        registry.register_preset(
            ApprovalScenarioPreset(
                scenario_code=SYSTEM_FILE_CHANGE_SCENARIO_CODE,
                scenario_name="知识空间文件变更审批",
                handler_key=SYSTEM_FILE_CHANGE_SCENARIO_CODE,
                condition_fields=["applicant_role", "action", "resource_type"],
                approver_source_types=[
                    "knowledge_space_owner",
                    "knowledge_space_manager",
                ],
            ),
            hidden=True,
        )
        return registry

    def register_preset(self, preset: ApprovalScenarioPreset, *, hidden: bool = False) -> None:
        self._presets[preset.scenario_code] = preset
        if hidden:
            self._hidden_preset_codes.add(preset.scenario_code)

    def list_presets(self) -> list[ApprovalScenarioPreset]:
        return [preset for code, preset in self._presets.items() if code not in self._hidden_preset_codes]

    def get_preset(self, scenario_code: str) -> ApprovalScenarioPreset | None:
        return self._presets.get(scenario_code)

    def register_handler(self, scenario_code: str, handler: Any) -> None:
        self._handlers[scenario_code] = handler

    async def get_handler(self, scenario_code: str) -> Any:
        handler = self._handlers.get(scenario_code)
        if handler is None:
            raise KeyError(f"handler not registered for scenario_code={scenario_code}")
        return handler

    def register_policy(self, policy: ApprovalScenarioPolicy) -> None:
        if self._decision_delivery_frozen:
            raise RuntimeError("approval decision-delivery registry is frozen")
        scenario_code = policy.scenario_code
        if scenario_code in self._policies:
            raise ValueError(f"approval policy already registered for scenario_code={scenario_code}")
        self._policies[scenario_code] = policy

    def register_subscriber(self, subscriber: ApprovalDecisionSubscriber) -> None:
        if self._decision_delivery_frozen:
            raise RuntimeError("approval decision-delivery registry is frozen")
        scenario_code = subscriber.scenario_code
        if scenario_code in self._subscribers:
            raise ValueError(f"approval subscriber already registered for scenario_code={scenario_code}")
        self._subscribers[scenario_code] = subscriber

    def get_policy(self, scenario_code: str) -> ApprovalScenarioPolicy:
        policy = self._policies.get(scenario_code)
        if policy is None:
            raise KeyError(f"policy not registered for scenario_code={scenario_code}")
        return policy

    def get_subscriber(self, scenario_code: str) -> ApprovalDecisionSubscriber:
        subscriber = self._subscribers.get(scenario_code)
        if subscriber is None:
            raise KeyError(f"subscriber not registered for scenario_code={scenario_code}")
        return subscriber

    def freeze_decision_delivery(self, *, required_scenario_codes: set[str]) -> None:
        scenario_codes = required_scenario_codes | self._policies.keys() | self._subscribers.keys()
        for scenario_code in sorted(scenario_codes):
            policy = self._policies.get(scenario_code)
            if policy is None:
                raise ValueError(f"approval policy missing for scenario_code={scenario_code}")
            subscriber = self._subscribers.get(scenario_code)
            if subscriber is None:
                raise ValueError(f"approval subscriber missing for scenario_code={scenario_code}")
            if (
                policy.completion_mode != DECISION_DELIVERY_COMPLETION_MODE
                or subscriber.completion_mode != DECISION_DELIVERY_COMPLETION_MODE
                or policy.completion_mode != subscriber.completion_mode
            ):
                raise ValueError(f"approval completion mode mismatch for scenario_code={scenario_code}")
            if policy.protocol_version != APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION:
                raise ValueError(f"approval policy protocol version mismatch for scenario_code={scenario_code}")
            if subscriber.protocol_version != APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION:
                raise ValueError(f"approval subscriber protocol version mismatch for scenario_code={scenario_code}")
            if subscriber.event_version != APPROVAL_DECISION_EVENT_VERSION:
                raise ValueError(f"approval subscriber event version mismatch for scenario_code={scenario_code}")
        self._decision_delivery_frozen = True
