from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalException,
    ApprovalExceptionType,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.approval.domain.models.approval_scenario import (
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.approval.domain.ports.scenario_policy import (
    APPROVAL_SUBMISSION_PROTOCOL_VERSION,
    DECISION_DELIVERY_COMPLETION_MODE,
    ApprovalPostCommitCallback,
    ApprovalSubmissionCommand,
    ApprovalSubmissionResult,
)
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.common.errcode.approval import (
    ApprovalConfirmationFlowRequiredError,
    ApprovalScenarioDisabledError,
)
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session


class ApprovalSubmissionService:
    """Create a decision-delivery approval bundle in a caller-owned UoW."""

    def __init__(
        self,
        *,
        registry: ApprovalRegistry,
        repository: type[ApprovalInstanceRepository] = ApprovalInstanceRepository,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]] = get_async_db_session,
    ) -> None:
        self.registry = registry
        self.repository = repository
        self.session_factory = session_factory

    @asynccontextmanager
    async def scenario_guard(
        self,
        *,
        tenant_id: int,
        scenario_code: str,
    ):
        current_tenant_id = get_current_tenant_id()
        if current_tenant_id is None or int(current_tenant_id) != int(tenant_id):
            raise ValueError("approval scenario guard requires the matching tenant context")
        async with self.session_factory() as session, session.begin():
            scenario = await self.repository.lock_submission_scenario_in_session(
                session,
                tenant_id=int(tenant_id),
                scenario_code=scenario_code,
            )
            if scenario is None or not scenario.enabled:
                raise ApprovalScenarioDisabledError()
            yield

    async def submit_in_uow(
        self,
        *,
        session: AsyncSession,
        command: ApprovalSubmissionCommand,
    ) -> ApprovalSubmissionResult:
        self._validate_command(command)
        policy = self.registry.get_policy(command.scenario_code)
        subscriber = self.registry.get_subscriber(command.scenario_code)
        await policy.validate_submission(command)

        scenario = await self.repository.get_submission_scenario_in_session(
            session,
            tenant_id=command.tenant_id,
            scenario_code=command.scenario_code,
        )
        if scenario is None or not scenario.enabled:
            raise ApprovalScenarioDisabledError()

        routes = await self.repository.list_submission_routes_in_session(
            session,
            tenant_id=command.tenant_id,
            scenario_id=int(scenario.id),
        )
        route = self._match_route(routes, command)
        if route is None:
            return await self._create_exception_submission(
                session=session,
                command=command,
                scenario=scenario,
                subscriber_key=subscriber.subscriber_key,
                exception_type=ApprovalExceptionType.ROUTE_MISSING,
            )
        if route.route_type != "flow" or route.flow_definition_id is None:
            raise ApprovalConfirmationFlowRequiredError()

        flow_version = await self.repository.get_submission_flow_version_in_session(
            session,
            tenant_id=command.tenant_id,
            flow_definition_id=int(route.flow_definition_id),
        )
        if flow_version is None or flow_version.id is None:
            return await self._create_exception_submission(
                session=session,
                command=command,
                scenario=scenario,
                subscriber_key=subscriber.subscriber_key,
                exception_type=ApprovalExceptionType.ROUTE_MISSING,
                route=route,
            )

        nodes = await self.repository.list_flow_nodes_in_session(
            session,
            tenant_id=command.tenant_id,
            flow_version_id=int(flow_version.id),
        )
        first_node = nodes[0] if nodes else None
        approver_user_ids = self._normalize_approver_user_ids(command.initial_approver_user_ids)
        if first_node is None or not approver_user_ids:
            return await self._create_exception_submission(
                session=session,
                command=command,
                scenario=scenario,
                subscriber_key=subscriber.subscriber_key,
                exception_type=ApprovalExceptionType.APPROVER_EMPTY,
                route=route,
                flow_version_id=int(flow_version.id),
                node=first_node,
            )

        instance = self._build_instance(
            command=command,
            scenario=scenario,
            subscriber_key=subscriber.subscriber_key,
            status=ApprovalInstanceStatus.PENDING,
            route=route,
            flow_version_id=int(flow_version.id),
            node=first_node,
        )
        tasks = [
            ApprovalTask(
                tenant_id=command.tenant_id,
                instance_id=0,
                flow_version_id=int(flow_version.id),
                node_code=first_node.node_code,
                node_name=first_node.node_name,
                node_order=first_node.node_order,
                approver_user_id=approver_user_id,
                approver_source_type="business_policy",
                node_mode=first_node.node_mode,
                status=ApprovalTaskStatus.PENDING,
            )
            for approver_user_id in approver_user_ids
        ]
        instance, tasks = await self.repository.create_submission_bundle_in_session(
            session,
            instance=instance,
            tasks=tasks,
            action_log=self._build_submission_log(command),
        )
        instance_id = self._required_id(instance.id, "approval instance")
        task_ids = tuple(self._required_id(task.id, "approval task") for task in tasks)
        effects = tuple(
            self._build_task_notification_effect(
                command=command,
                instance_id=instance_id,
                task_id=task_id,
                approver_user_id=approver_user_id,
            )
            for task_id, approver_user_id in zip(task_ids, approver_user_ids, strict=True)
        )
        return ApprovalSubmissionResult(
            instance_id=instance_id,
            task_ids=task_ids,
            post_commit_effects=effects,
        )

    async def _create_exception_submission(
        self,
        *,
        session: AsyncSession,
        command: ApprovalSubmissionCommand,
        scenario: ApprovalScenario,
        subscriber_key: str,
        exception_type: str,
        route: ApprovalRouteRule | None = None,
        flow_version_id: int | None = None,
        node: ApprovalNodeDefinition | None = None,
    ) -> ApprovalSubmissionResult:
        instance = self._build_instance(
            command=command,
            scenario=scenario,
            subscriber_key=subscriber_key,
            status=ApprovalInstanceStatus.EXCEPTION,
            route=route,
            flow_version_id=flow_version_id,
            node=node,
        )
        exception = ApprovalException(
            tenant_id=command.tenant_id,
            instance_id=0,
            exception_type=exception_type,
            detail={
                "scenario_code": command.scenario_code,
                "business_request_type": command.business_request_type,
                "business_request_id": command.business_request_id,
                "current_node_name": node.node_name if node is not None else None,
            },
        )
        instance, _ = await self.repository.create_submission_bundle_in_session(
            session,
            instance=instance,
            tasks=[],
            action_log=self._build_submission_log(command),
            exception=exception,
        )
        instance_id = self._required_id(instance.id, "approval instance")
        return ApprovalSubmissionResult(
            instance_id=instance_id,
            post_commit_effects=(
                self._build_exception_notification_effect(
                    command=command,
                    instance_id=instance_id,
                    exception_type=exception_type,
                ),
            ),
        )

    @staticmethod
    def _validate_command(command: ApprovalSubmissionCommand) -> None:
        if command.protocol_version != APPROVAL_SUBMISSION_PROTOCOL_VERSION:
            raise ValueError(f"unsupported approval submission protocol version: {command.protocol_version}")
        if command.completion_mode != DECISION_DELIVERY_COMPLETION_MODE:
            raise ValueError(f"unsupported approval completion mode: {command.completion_mode}")
        if int(command.tenant_id) <= 0:
            raise ValueError("a positive tenant_id is required for approval submission")
        current_tenant_id = get_current_tenant_id()
        if current_tenant_id is None or int(current_tenant_id) != int(command.tenant_id):
            raise ValueError("approval submission tenant does not match the current tenant context")
        if not command.business_request_type or not command.business_request_id:
            raise ValueError("approval submission requires a business request identity")
        if not command.request_fingerprint:
            raise ValueError("approval submission requires a request fingerprint")

    @staticmethod
    def _match_route(
        routes: list[ApprovalRouteRule],
        command: ApprovalSubmissionCommand,
    ) -> ApprovalRouteRule | None:
        values = dict(command.link_snapshot)
        values.update(command.detail_snapshot)
        for route in routes:
            match_config = route.match_config or {}
            field = str(match_config.get("field") or "")
            if not field:
                return route
            actual = values.get(field)
            if actual is not None and str(actual) == str(match_config.get("value") or ""):
                return route
        return None

    @staticmethod
    def _normalize_approver_user_ids(user_ids: tuple[int, ...]) -> tuple[int, ...]:
        normalized: list[int] = []
        seen: set[int] = set()
        for value in user_ids:
            user_id = int(value)
            if user_id <= 0:
                raise ValueError("approval approver user ids must be positive")
            if user_id not in seen:
                seen.add(user_id)
                normalized.append(user_id)
        return tuple(normalized)

    @staticmethod
    def _build_instance(
        *,
        command: ApprovalSubmissionCommand,
        scenario: ApprovalScenario,
        subscriber_key: str,
        status: str,
        route: ApprovalRouteRule | None = None,
        flow_version_id: int | None = None,
        node: ApprovalNodeDefinition | None = None,
    ) -> ApprovalInstance:
        return ApprovalInstance(
            tenant_id=command.tenant_id,
            scenario_code=command.scenario_code,
            scenario_name=scenario.scenario_name,
            handler_key=subscriber_key,
            business_key=command.business_key,
            business_resource_type=command.business_request_type,
            business_resource_id=command.business_request_id,
            business_name=command.title,
            applicant_user_id=command.applicant.user_id,
            applicant_user_name=command.applicant.user_name,
            applicant_department_id=command.applicant.department_id,
            flow_version_id=flow_version_id,
            route_rule_id=int(route.id) if route is not None and route.id is not None else None,
            status=status,
            payload_snapshot={
                "protocol_version": command.protocol_version,
                "completion_mode": command.completion_mode,
                "business_request_type": command.business_request_type,
                "business_request_id": command.business_request_id,
                "request_fingerprint": command.request_fingerprint,
                "link_snapshot": dict(command.link_snapshot),
            },
            detail_snapshot=dict(command.detail_snapshot),
            current_node_name=node.node_name if node is not None else None,
        )

    @staticmethod
    def _build_submission_log(command: ApprovalSubmissionCommand) -> ApprovalActionLog:
        return ApprovalActionLog(
            tenant_id=command.tenant_id,
            instance_id=0,
            action="submitted",
            operator_user_id=command.applicant.user_id,
            operator_user_name=command.applicant.user_name,
            detail={
                "business_request_type": command.business_request_type,
                "business_request_id": command.business_request_id,
                "request_fingerprint": command.request_fingerprint,
            },
        )

    @staticmethod
    def _required_id(value: int | None, label: str) -> int:
        if value is None:
            raise RuntimeError(f"{label} id was not assigned during submission")
        return int(value)

    @staticmethod
    def _build_task_notification_effect(
        *,
        command: ApprovalSubmissionCommand,
        instance_id: int,
        task_id: int,
        approver_user_id: int,
    ) -> ApprovalPostCommitCallback:
        async def notify() -> None:
            await ApprovalNotificationService.notify_user(
                sender=command.applicant.user_id,
                receiver_user_id=approver_user_id,
                action_code="approval_task_pending",
                business_name=command.title,
                instance_id=instance_id,
                scenario_code=command.scenario_code,
                task_id=task_id,
            )

        return notify

    @staticmethod
    def _build_exception_notification_effect(
        *,
        command: ApprovalSubmissionCommand,
        instance_id: int,
        exception_type: str,
    ) -> ApprovalPostCommitCallback:
        async def notify() -> None:
            await ApprovalNotificationService.notify_admins(
                tenant_id=command.tenant_id,
                applicant_user_id=command.applicant.user_id,
                action_code=f"approval_exception_{exception_type}",
                business_name=command.title,
                instance_id=instance_id,
                scenario_code=command.scenario_code,
            )

        return notify
