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
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.flow import (
    CurVersionDelError,
    NotFoundVersionError,
    VersionNameExistsError,
    WorkFlowOnlineEditError,
)
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.services import telemetry_service
from bisheng.common.services.base import BaseService
from bisheng.core.context.tenant import strict_tenant_filter, tenant_execution_scope
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import Flow, FlowDao, FlowStatus, FlowType
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
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.utils import get_request_ip

from .f048_application_permission import ApplicationPermissionRecord


class FlowService(BaseService):
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
        from bisheng.workflow.application.kunlian_workflow_management import workflow_scope

        flow = await FlowDao.aget_flow_by_id(flow_id)
        if not flow:
            return resp_200(data={"data": [], "total": 0})
        scope = workflow_scope(flow.tenant_id, flow_id, user=user)
        data = FlowVersionDao.get_list_by_flow(flow_id)
        if scope:
            from bisheng.workflow.domain.repositories.kunlian_registration import RegistrationRepository

            drafts = RegistrationRepository().draft_versions(scope, flow_id)
            data = [{**version.model_dump(), **drafts[version.id]} for version in data if version.id in drafts]
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
        from bisheng.workflow.application.kunlian_workflow_management import version_revision, workflow_scope

        flow = await FlowDao.aget_flow_by_id(data.flow_id)
        if not flow:
            return NotFoundVersionError.return_resp()
        if scope := workflow_scope(flow.tenant_id, flow.id, user=user):
            if data.tenant_id != scope.tenant_id:
                raise UnAuthorizedError()
            return resp_200(data={**data.model_dump(), "draft_revision": version_revision(data)})
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
        version_info = FlowVersionDao.get_version_by_id(version_id)
        if not version_info:
            return NotFoundVersionError.return_resp()

        flow_info = FlowDao.get_flow_by_id(version_info.flow_id)
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

        from bisheng.workflow.application.kunlian_workflow_management import workflow_scope
        from bisheng.workflow.domain.repositories.kunlian_registration import RegistrationRepository

        if scope := workflow_scope(flow_info.tenant_id, flow_info.id, user=user):
            RegistrationRepository().manage_offline_version(scope, flow_info.id, version_id, delete=True)
            return resp_200()

        from bisheng.workflow.application.platform_node_publication import uses_platform_nodes

        if uses_platform_nodes(version_info.data) or uses_platform_nodes(flow_info.data):
            from bisheng.workflow.application.platform_agent import get_service

            get_service().repository.delete_version(version_id)
        else:
            FlowVersionDao.delete_flow_version(version_id)
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

        from bisheng.workflow.application.kunlian_workflow_management import workflow_scope
        from bisheng.workflow.domain.repositories.kunlian_registration import RegistrationRepository

        scope = workflow_scope(flow_info.tenant_id, flow_id, user=login_user)
        if flow_info.status == FlowStatus.ONLINE.value:
            return WorkFlowOnlineEditError.return_resp()

        # Switch versions
        version_info = await FlowVersionDao.aget_version_by_id(version_id)
        if not version_info or version_info.flow_id != flow_id:
            return NotFoundVersionError.return_resp()
        if version_info.is_current == 1:
            return resp_200()

        if scope:
            RegistrationRepository().manage_offline_version(scope, flow_id, version_id)
            await cls.update_flow_hook(request, login_user, flow_info)
            return resp_200()

        # Modify the version selected by the user for the current version
        from bisheng.workflow.application.platform_node_publication import uses_platform_nodes

        if uses_platform_nodes(version_info.data) or uses_platform_nodes(flow_info.data):
            from bisheng.workflow.application.platform_agent import get_service

            get_service().repository.change_version(flow_id, version_id)
            changed = True
        else:
            changed = await FlowVersionDao.change_current_version(flow_id, version_info)
        if not changed:
            return NotFoundVersionError.return_resp()

        await cls.update_flow_hook(request, login_user, flow_info)
        return resp_200()

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
        flow = await cls.judge_flow_write_permission(user, flow_id)
        from bisheng.workflow.application.kunlian_workflow_management import workflow_scope

        scope = workflow_scope(flow.tenant_id, flow_id, user=user)

        exist_version = FlowVersionDao.get_version_by_name(flow_id, flow_version.name)
        if exist_version:
            return VersionNameExistsError.return_resp()

        from bisheng.workflow.application.platform_node_publication import uses_platform_nodes
        from bisheng.workflow.domain.repositories.platform_node_publication import PlatformNodePublication

        if uses_platform_nodes(flow_version.data):
            flow_version.data = PlatformNodePublication.candidate_graph(flow_version.data)
        flow_version = FlowVersion(
            flow_id=flow_id,
            name=flow_version.name,
            description=flow_version.description,
            user_id=user.user_id,
            data=flow_version.data,
            original_version_id=flow_version.original_version_id,
            flow_type=flow_version.flow_type,
        )
        if scope:
            flow_version.tenant_id = scope.tenant_id

        # Create New Version
        flow_version = FlowVersionDao.create_version(flow_version)

        return resp_200(data=flow_version)

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

        from bisheng.workflow.application.kunlian_workflow_management import workflow_scope
        from bisheng.workflow.domain.repositories.kunlian_registration import RegistrationRepository

        if scope := workflow_scope(flow_info.tenant_id, flow_info.id, user=user):
            updated = RegistrationRepository().save_draft(
                scope, flow_info.id, version_id, request.headers.get("If-Match"),
                data=flow_version.data, name=flow_version.name, description=flow_version.description,
            )
            await cls.update_flow_hook(request, user, flow_info)
            return resp_200(data=updated)

        if version_info.is_current == 1 and flow_info.status == FlowStatus.ONLINE.value and flow_version.data:
            return WorkFlowOnlineEditError.return_resp()

        from bisheng.workflow.application.platform_node_publication import uses_platform_nodes

        if any(uses_platform_nodes(graph) for graph in (version_info.data, flow_info.data, flow_version.data)):
            from bisheng.workflow.application.platform_agent import get_service

            updated = get_service().repository.save_version(
                version_id, data=flow_version.data, name=flow_version.name, description=flow_version.description
            )
            await cls.update_flow_hook(request, user, flow_info)
            return resp_200(data=updated)

        version_info.name = flow_version.name if flow_version.name else version_info.name
        version_info.description = flow_version.description if flow_version.description else version_info.description
        version_info.data = flow_version.data if flow_version.data else version_info.data
        version_info.is_delete = 0

        flow_version = await FlowVersionDao.aupdate_version(version_info)

        await cls.update_flow_hook(request, user, flow_info)
        return resp_200(data=flow_version)

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

        from bisheng.workflow.application.kunlian_workflow_management import workflow_scope
        from bisheng.workflow.domain.repositories.kunlian_registration import RegistrationRepository

        scope = workflow_scope(flow_info.tenant_id, flow_info.id, user=login_user)
        flow_info.logo = await cls.get_logo_share_link_async(flow_info.logo)
        payload = jsonable_encoder(flow_info)
        if scope and not has_share_grant:
            payload["kunlian_registration"] = RegistrationRepository().status(scope, flow_id)
        payload["can_share"] = await check_business_action(
            login_user,
            resource_type="workflow",
            resource_id=flow_id,
            action="share",
        )
        return resp_200(data=payload)

    @classmethod
    async def get_management_flow(cls, user: UserPayload, flow_id: str, *, for_edit: bool = False):
        with tenant_execution_scope(user.tenant_id), strict_tenant_filter():
            result = await cls.get_one_flow(user, flow_id)
            if for_edit:
                await require_business_action(user, resource_type="workflow", resource_id=flow_id, action="edit")
                return result
            versions = await cls.get_version_list_by_flow(user, flow_id)
            summary = {
                key: result.data[key]
                for key in ("id", "name", "description", "status", "logo")
                if key in result.data
            }
            summary["versions"] = [
                {key: version[key] for key in ("id", "name", "is_current") if key in version}
                for version in jsonable_encoder(versions.data["data"])
            ]
            return resp_200(data=summary)

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
