import asyncio
import copy
from collections.abc import AsyncGenerator
from hashlib import sha256
from typing import Union

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from loguru import logger

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.v1.schemas import (
    FlowCompareReq,
    FlowVersionCreate,
    StreamData,
    UnifiedResponseModel,
    resp_200,
    resp_500,
)
from bisheng.common.chat.utils import process_node_data
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.flow import (
    CurVersionDelError,
    NotFoundVersionError,
    VersionNameExistsError,
    WorkflowNameExistsError,
    WorkFlowOnlineEditError,
)
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.common.schemas.telemetry.event_data_schema import NewApplicationEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.base import BaseService
from bisheng.core.database import get_async_db_session
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import Flow, FlowCreate, FlowDao, FlowRead, FlowStatus, FlowType
from bisheng.database.models.flow_version import FlowVersion, FlowVersionDao, FlowVersionRead
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.session import MessageSessionDao
from bisheng.permission.application.access import get_f048_resource_adapter
from bisheng.permission.application.business_authorization import (
    check_business_action,
    require_business_action,
)
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.public_endpoints.domain.services.guest_link import delete_app_guest_link
from bisheng.resource_reference.application.access import get_reference_binding_runtime
from bisheng.resource_reference.application.contracts import SourceKey, reference_set_digest
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.utils import get_request_ip
from bisheng.workflow.domain.repositories.workflow_version_repository import WorkflowVersionRepository
from bisheng.workflow.domain.services.reference_extractor import (
    WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
    extract_workflow_version_references,
)

from .f048_application_permission import ApplicationPermissionRecord


class FlowService(BaseService):
    @classmethod
    async def create_workflow(
        cls, request: Request, user: UserPayload, flow: FlowCreate
    ) -> UnifiedResponseModel[FlowRead]:
        runtime = await get_reference_binding_runtime()
        async with get_async_db_session() as session:
            if await WorkflowVersionRepository.aget_root_by_name(session, user.tenant_id, user.user_id, flow.name):
                raise WorkflowNameExistsError.http_exception()
            root = Flow.model_validate(flow)
            root.user_id = user.user_id
            root.tenant_id = user.tenant_id
            root.flow_type = FlowType.WORKFLOW.value
            root.create_time = None
            root.update_time = None
            root, version = await WorkflowVersionRepository.acreate_workflow(session, root)
            source = SourceKey(root.tenant_id, "workflow_version", root.id, str(version.id))
            prepared = await runtime.aprepare_source_bindings(
                session,
                source,
                extract_workflow_version_references(version.data),
                extractor_version=WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
                lock_source_root=lambda sql: WorkflowVersionRepository.alock_root(sql, root.id, root.tenant_id),
                new_source=True,
            )
            await runtime.aapply_source_bindings(session, prepared)
            # The adapter consumes the new root's explicit business record;
            # it does not reload an uncommitted Flow. Its durable projection
            # completes before this one SQL unit is finalized.
            await cls.create_flow_hook(request, user, root)
            await session.commit()
            await session.refresh(root)
            result = FlowRead.model_validate(root)
            result.version_id = version.id
        await telemetry_service.log_event(
            user_id=user.user_id,
            event_type=BaseTelemetryTypeEnum.NEW_APPLICATION,
            trace_id=trace_id_var.get(),
            event_data=NewApplicationEventData(
                app_id=root.id, app_name=root.name, app_type=ApplicationTypeEnum.WORKFLOW
            ),
        )
        return resp_200(data=result)

    @classmethod
    async def get_version_list_by_flow(
        cls,
        user: UserPayload,
        flow_id: str,
    ) -> UnifiedResponseModel[list[FlowVersionRead]]:
        """
        By SkillID Get all versions of a skill
        """
        await require_business_action(
            user,
            resource_type="workflow",
            resource_id=flow_id,
            action="visible",
        )
        data = FlowVersionDao.get_list_by_flow(flow_id)
        # Include Deleted Versions
        all_version_num = FlowVersionDao.count_list_by_flow(flow_id, include_delete=True)
        return resp_200(data={"data": data, "total": all_version_num})

    @classmethod
    async def get_version_info(
        cls,
        user: UserPayload,
        version_id: int,
    ) -> UnifiedResponseModel[FlowVersion]:
        """
        According to versionIDGet version details
        """
        data = FlowVersionDao.get_version_by_id(version_id)
        if data is None:
            return NotFoundVersionError.return_resp()
        await require_business_action(
            user,
            resource_type="workflow",
            resource_id=data.flow_id,
            action="visible",
        )
        return resp_200(data=data)

    @classmethod
    async def delete_version(
        cls,
        user: UserPayload,
        version_id: int,
    ) -> UnifiedResponseModel[None]:
        """
        According to versionIDRemove Version
        """
        telemetry_service.log_event_sync(
            user_id=user.user_id, event_type=BaseTelemetryTypeEnum.EDIT_APPLICATION, trace_id=trace_id_var.get()
        )
        version_info = await FlowVersionDao.aget_version_by_id(version_id)
        if not version_info:
            return NotFoundVersionError.return_resp()

        flow_info = await FlowDao.aget_flow_by_id(version_info.flow_id)
        if not flow_info or flow_info.flow_type != FlowType.WORKFLOW.value:
            return NotFoundError.return_resp()

        await require_business_action(
            user,
            resource_type="workflow",
            resource_id=flow_info.id,
            action="edit",
        )

        if version_info.is_current == 1:
            return CurVersionDelError.return_resp()

        runtime = await get_reference_binding_runtime()
        async with get_async_db_session() as session:
            root = await WorkflowVersionRepository.aget_root(session, flow_info.id, user.tenant_id)
            current = await WorkflowVersionRepository.aget_version(session, root, version_id)
            candidate = cls._workflow_version_snapshot(current)

            async def lock_root(sql):
                locked = await WorkflowVersionRepository.alock_root(sql, root.id, user.tenant_id)
                version = await WorkflowVersionRepository.aget_version(sql, locked, version_id, for_update=True)
                if cls._workflow_version_snapshot(version) != candidate:
                    raise KnowledgeOperationPlanConflictError(reason="workflow_version_changed")
                if version.is_current == 1:
                    raise CurVersionDelError()

            prepared = await runtime.aprepare_source_bindings(
                session,
                SourceKey(root.tenant_id, "workflow_version", root.id, str(version_id)),
                (),
                extractor_version=WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
                lock_source_root=lock_root,
                effective=False,
            )
            current = await WorkflowVersionRepository.aget_version(session, root, version_id, for_update=True)
            cls._assert_workflow_source_configuration(current, prepared)
            await WorkflowVersionRepository.asoft_delete_version(session, root, version_id)
            await runtime.aapply_source_bindings(session, prepared)
            await session.commit()
        return resp_200()

    @classmethod
    async def judge_flow_write_permission(cls, user: UserPayload, flow_id: str) -> Flow:
        flow_info = await FlowDao.aget_flow_by_id(flow_id)
        if not flow_info or flow_info.flow_type != FlowType.WORKFLOW.value:
            raise NotFoundError.http_exception()

        await require_business_action(
            user,
            resource_type="workflow",
            resource_id=flow_info.id,
            action="edit",
        )
        return flow_info

    @classmethod
    async def change_current_version(
        cls, request: Request, login_user: UserPayload, flow_id: str, version_id: int
    ) -> UnifiedResponseModel[None]:
        """
        Modify Current Version
        """
        await telemetry_service.log_event(
            user_id=login_user.user_id, event_type=BaseTelemetryTypeEnum.EDIT_APPLICATION, trace_id=trace_id_var.get()
        )
        flow_info = await cls.judge_flow_write_permission(login_user, flow_id)

        if flow_info.status == FlowStatus.ONLINE.value:
            return WorkFlowOnlineEditError.return_resp()

        # Switch versions
        version_info = await FlowVersionDao.aget_version_by_id(version_id)
        if not version_info or version_info.flow_id != flow_id:
            return NotFoundVersionError.return_resp()
        root = await cls.transition_current_version(login_user, flow_id, version_id)
        await cls.update_flow_hook(request, login_user, root)
        return resp_200()

    @classmethod
    async def transition_current_version(cls, user, flow_id, version_id, *, status=None, validate_version=None) -> Flow:
        """Persist current/publish changes through one target-first SQL unit.

        The caller retains its existing edit or publish/unpublish authorization.
        Other saved versions remain effective reference sources throughout.
        """
        runtime = await get_reference_binding_runtime()
        async with get_async_db_session() as session:
            root = await WorkflowVersionRepository.aget_root(session, flow_id, user.tenant_id)
            version = await WorkflowVersionRepository.aget_version(session, root, version_id)
            if status is not None and status != FlowStatus.ONLINE.value:
                # Stopping a business does not change its saved slots and must
                # remain possible when targets are deleted or being deleted.
                root = await WorkflowVersionRepository.alock_root(session, flow_id, user.tenant_id)
                await WorkflowVersionRepository.aget_version(session, root, version_id, for_update=True)
                root.status = status
            else:
                candidate = cls._workflow_version_snapshot(version)
                references = extract_workflow_version_references(version.data)
                source = SourceKey(root.tenant_id, "workflow_version", root.id, str(version_id))

                async def lock_root(sql):
                    locked = await WorkflowVersionRepository.alock_root(sql, flow_id, user.tenant_id)
                    current = await WorkflowVersionRepository.aget_version(sql, locked, version_id, for_update=True)
                    if cls._workflow_version_snapshot(current) != candidate:
                        raise KnowledgeOperationPlanConflictError(reason="workflow_version_changed")
                    if status is None and locked.status == FlowStatus.ONLINE.value:
                        raise WorkFlowOnlineEditError()

                prepared = await runtime.aprepare_source_bindings(
                    session,
                    source,
                    references,
                    extractor_version=WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
                    lock_source_root=lock_root,
                )
                version = await WorkflowVersionRepository.aget_version(session, root, version_id, for_update=True)
                cls._assert_workflow_source_configuration(version, prepared)
                await runtime.arequire_source_valid(session, source, references=references)
                if validate_version is not None:
                    validate_version(root, version)
                await WorkflowVersionRepository.aswitch_current(session, root, version_id)
                if status is not None:
                    root.status = status
                await runtime.aapply_source_bindings(session, prepared)
            await session.commit()
            await session.refresh(root)
        return root

    @classmethod
    async def create_new_version(
        cls, user: UserPayload, flow_id: str, flow_version: FlowVersionCreate
    ) -> UnifiedResponseModel[FlowVersion]:
        """
        Create New Version
        """
        await telemetry_service.log_event(
            user_id=user.user_id, event_type=BaseTelemetryTypeEnum.EDIT_APPLICATION, trace_id=trace_id_var.get()
        )
        await cls.judge_flow_write_permission(user, flow_id)
        runtime = await get_reference_binding_runtime()
        async with get_async_db_session() as session:
            root = await WorkflowVersionRepository.aget_root(session, flow_id, user.tenant_id)
            if await WorkflowVersionRepository.aget_version_by_name(session, root, flow_version.name):
                return VersionNameExistsError.return_resp()
            version = await WorkflowVersionRepository.acreate_version(
                session,
                root,
                FlowVersion(
                    flow_id=flow_id,
                    name=flow_version.name,
                    description=flow_version.description,
                    user_id=user.user_id,
                    data=copy.deepcopy(flow_version.data),
                    original_version_id=flow_version.original_version_id,
                ),
            )

            async def lock_root(sql):
                locked = await WorkflowVersionRepository.alock_root(sql, flow_id, user.tenant_id)
                if any(
                    candidate.id != version.id and candidate.name == version.name
                    for candidate in await WorkflowVersionRepository.alist_versions(sql, locked, for_update=True)
                ):
                    raise VersionNameExistsError()

            prepared = await runtime.aprepare_source_bindings(
                session,
                SourceKey(root.tenant_id, "workflow_version", root.id, str(version.id)),
                extract_workflow_version_references(version.data),
                extractor_version=WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
                lock_source_root=lock_root,
                new_source=True,
            )
            await runtime.aapply_source_bindings(session, prepared)
            await session.commit()
            await session.refresh(version)
        return resp_200(data=version)

    @classmethod
    async def update_version_info(
        cls, request: Request, user: UserPayload, version_id: int, flow_version: FlowVersionCreate
    ) -> UnifiedResponseModel[FlowVersion]:
        """
        It updates version information.
        """
        await telemetry_service.log_event(
            user_id=user.user_id, event_type=BaseTelemetryTypeEnum.EDIT_APPLICATION, trace_id=trace_id_var.get()
        )
        # Contains the deleted version. If the version is deleted, revert to this version
        version_info = await FlowVersionDao.aget_version_by_id(version_id, include_delete=True)
        if not version_info:
            return NotFoundVersionError.return_resp()
        flow_info = await cls.judge_flow_write_permission(user, version_info.flow_id)

        if (
            version_info.is_current == 1
            and flow_info.status == FlowStatus.ONLINE.value
            and flow_version.data is not None
        ):
            return WorkFlowOnlineEditError.return_resp()

        runtime = await get_reference_binding_runtime()
        async with get_async_db_session() as session:
            root = await WorkflowVersionRepository.aget_root(session, flow_info.id, user.tenant_id)
            current = await WorkflowVersionRepository.aget_version(session, root, version_id, include_deleted=True)
            candidate = cls._workflow_version_snapshot(current)
            next_version = FlowVersion(
                id=current.id,
                flow_id=root.id,
                tenant_id=root.tenant_id,
                name=flow_version.name or current.name,
                description=flow_version.description or current.description,
                data=copy.deepcopy(flow_version.data if flow_version.data is not None else current.data),
                is_delete=0,
            )

            async def lock_root(sql):
                locked = await WorkflowVersionRepository.alock_root(sql, root.id, user.tenant_id)
                locked_version = await WorkflowVersionRepository.aget_version(
                    sql, locked, version_id, include_deleted=True, for_update=True
                )
                if cls._workflow_version_snapshot(locked_version) != candidate:
                    raise KnowledgeOperationPlanConflictError(reason="workflow_version_changed")
                if (
                    locked_version.is_current == 1
                    and locked.status == FlowStatus.ONLINE.value
                    and flow_version.data is not None
                ):
                    raise WorkFlowOnlineEditError()

            prepared = await runtime.aprepare_source_bindings(
                session,
                SourceKey(root.tenant_id, "workflow_version", root.id, str(version_id)),
                extract_workflow_version_references(next_version.data),
                extractor_version=WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
                lock_source_root=lock_root,
            )
            current = await WorkflowVersionRepository.aget_version(
                session, root, version_id, include_deleted=True, for_update=True
            )
            cls._assert_workflow_source_configuration(current, prepared)
            version = await WorkflowVersionRepository.aupdate_version(session, root, next_version)
            await runtime.aapply_source_bindings(session, prepared)
            await session.commit()
            await session.refresh(version)
        await cls.update_flow_hook(request, user, root)
        return resp_200(data=version)

    @staticmethod
    def _workflow_version_snapshot(version: FlowVersion) -> tuple:
        return (copy.deepcopy(version.data), version.name, version.description, version.is_current, version.is_delete)

    @staticmethod
    def _assert_workflow_source_configuration(version: FlowVersion, prepared) -> None:
        # A deleted version retains historical JSON but has no live binding
        # slots until restored. A live source must match its indexed old set;
        # ordinary saves cannot repair migration/index drift implicitly.
        old = extract_workflow_version_references(version.data) if version.is_delete == 0 else ()
        if reference_set_digest(old) != prepared.verified.context.old_references_digest:
            raise ReferenceCoverageNotReadyError(reason="source_configuration_drift")

    @classmethod
    async def get_one_flow(
        cls, login_user: UserPayload, flow_id: str, share_link: Union["ShareLink", None] = None
    ) -> UnifiedResponseModel[Flow]:
        flow_info = await FlowDao.aget_flow_by_id(flow_id)
        if not flow_info or flow_info.flow_type != FlowType.WORKFLOW.value:
            raise NotFoundError()
        # A valid share-token grants view access to any logged-in recipient
        # who lacks a direct app permission grant. Workflow chat shares
        # (resource_type='workflow') generated by ShareChat.tsx store the
        # conversation id in resource_id and the actual flow id under
        # meta_data.flowId; direct flow shares store the flow id in
        # resource_id. Try meta_data.flowId first, then fall back to
        # resource_id so both shapes work.
        has_share_grant = False
        if share_link is not None:
            meta_data = share_link.meta_data or {}
            share_flow_id = str(meta_data.get("flowId") or share_link.resource_id or "")
            has_share_grant = share_flow_id == str(flow_id)
        if not has_share_grant and not await check_business_action(
            login_user,
            resource_type="workflow",
            resource_id=flow_info.id,
            action="visible",
        ):
            raise UnAuthorizedError()

        flow_info.logo = await cls.get_logo_share_link_async(flow_info.logo)

        payload = jsonable_encoder(flow_info, exclude={"is_delete"})
        payload["can_share"] = await check_business_action(
            login_user,
            resource_type="workflow",
            resource_id=flow_id,
            action="share",
        )
        return resp_200(data=payload)

    @classmethod
    async def get_compare_tasks(cls, user: UserPayload, req: FlowCompareReq) -> list:
        """
        Get Comparison Tasks
        """
        if req.question_list is None or len(req.question_list) == 0:
            return []
        if req.version_list is None or len(req.version_list) == 0:
            return []
        if req.node_id is None:
            return []

        # Get version data
        version_infos = FlowVersionDao.get_list_by_ids(req.version_list)
        # Start a new event loop
        tasks = []
        for index, question in enumerate(req.question_list):
            question_index = index
            tmp_inputs = copy.deepcopy(req.inputs)
            tmp_inputs, tmp_tweaks = cls.parse_compare_inputs(tmp_inputs, question)
            for version in version_infos:
                task = asyncio.create_task(
                    cls.exec_flow_node(copy.deepcopy(tmp_inputs), tmp_tweaks, question_index, [version])
                )
                tasks.append(task)
        return tasks

    @classmethod
    def parse_compare_inputs(cls, inputs: dict, question) -> (dict, dict):
        # Under special treatmentinputs, Hold and PasswebsocketSessions are formatted consistently
        if inputs.get("data", None):
            for one in inputs["data"]:
                one["id"] = one["nodeId"]
                if "InputFile" in one["id"]:
                    one["file_path"] = one["value"]

        # Paddingquestion and Generate Replacementtweaks
        for key, _val in inputs.items():
            if key != "data" and key != "id":
                # Default inputkey, replace the firstkey
                logger.info(f"replace_inputs {key} replace to {question}")
                inputs[key] = question
                break
        if "id" in inputs:
            inputs.pop("id")
        # Replacement Node Parameters, GantiinputFileNodeAndVariableNodeParameters
        tweaks = {}
        if "data" in inputs:
            node_data = inputs.pop("data")
            if node_data:
                tweaks = process_node_data(node_data)
        return inputs, tweaks

    @classmethod
    async def compare_flow_node(cls, user: UserPayload, req: FlowCompareReq) -> UnifiedResponseModel[dict]:
        """
        Compare nodes in two versions Output Results
        """
        tasks = await cls.get_compare_tasks(user, req)
        if len(tasks) == 0:
            return resp_200(data=[])
        res = [{} for _ in range(len(req.question_list))]
        try:
            for one in asyncio.as_completed(tasks):
                index, answer = await one
                if res[index]:
                    res[index].update(answer)
                else:
                    res[index] = answer
        except Exception as e:
            return resp_500(message=f"Workflow comparison error:{e!s}")
        return resp_200(data=res)

    @classmethod
    async def compare_flow_stream(cls, user: UserPayload, req: FlowCompareReq) -> AsyncGenerator:
        """
        Compare nodes in two versions Output Results
        """
        tasks = await cls.get_compare_tasks(user, req)
        if len(tasks) == 0:
            return
        for one in asyncio.as_completed(tasks):
            index, answer_dict = await one
            for version_id, answer in answer_dict.items():
                yield str(
                    StreamData(
                        event="message", data={"question_index": index, "version_id": version_id, "answer": answer}
                    )
                )

    @classmethod
    async def exec_flow_node(cls, inputs: dict, tweaks: dict, index: int, versions: list[FlowVersion]):
        # Gantianswer
        raise ValueError("flow is not supported")

    @classmethod
    async def create_flow_hook(
        cls,
        request: Request,
        login_user: UserPayload,
        flow_info: Flow,
    ) -> bool:
        logger.info(f"create_flow_hook flow: {flow_info.id}, user_payload: {login_user.user_id}")

        adapter = await get_f048_resource_adapter("workflow")
        await adapter.authorize_created(
            record=cls._new_permission_record(flow_info),
            actor=await resolve_permission_actor(login_user),
        )

        AuditLogService.create_build_workflow(login_user, get_request_ip(request), flow_info.id)

        cls.get_logo_share_link(flow_info.logo)
        return True

    @classmethod
    async def update_flow_hook(cls, request: Request, login_user: UserPayload, flow_info: Flow) -> bool:
        # Write Audit Log
        await AuditLogService.update_build_workflow(login_user, get_request_ip(request), flow_info.id)

        # WritelogoCeacle
        await cls.get_logo_share_link_async(flow_info.logo)
        return True

    @classmethod
    async def project_flow_delete(
        cls,
        login_user: UserPayload,
        flow_info: Flow,
    ) -> None:
        await require_business_action(
            login_user,
            resource_type="workflow",
            resource_id=flow_info.id,
            action="delete",
        )
        adapter = await get_f048_resource_adapter("workflow")
        record = await adapter.load_permission_record(
            resource_type="workflow",
            resource_id=str(flow_info.id),
        )
        if record is None:
            raise NotFoundError()
        await adapter.project_delete(
            record=record,
            actor=await resolve_permission_actor(login_user),
        )

    @classmethod
    def delete_flow_hook(cls, request: Request, login_user: UserPayload, flow_info: Flow) -> bool:
        logger.info(f"delete_flow_hook flow: {flow_info.id}, user_payload: {login_user.user_id}")

        # Write Audit Log
        AuditLogService.delete_build_workflow(login_user, get_request_ip(request), flow_info)

        # Delete Skills Associated Under User Group
        GroupResourceDao.delete_group_resource_by_third_id(flow_info.id, ResourceTypeEnum.WORK_FLOW)

        # Update session information
        MessageSessionDao.update_session_info_by_flow(
            flow_info.name, flow_info.description, flow_info.logo, flow_info.id, flow_info.flow_type
        )
        delete_app_guest_link("workflow", str(flow_info.id))
        return True

    @staticmethod
    def _new_permission_record(
        flow_info: Flow,
    ) -> ApplicationPermissionRecord:
        context_version = sha256(
            (f"workflow|{flow_info.id}|{flow_info.tenant_id}|{flow_info.user_id}|{flow_info.status}").encode()
        ).hexdigest()
        return ApplicationPermissionRecord(
            tenant_id=int(flow_info.tenant_id or 0),
            resource_type="workflow",
            resource_id=str(flow_info.id),
            status=FlowStatus(flow_info.status).name,
            owner_user_id=int(flow_info.user_id or 0),
            permission_version=0,
            context_version=context_version,
        )
