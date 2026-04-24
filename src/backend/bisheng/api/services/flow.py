import asyncio
import copy
from typing import List, Dict, AsyncGenerator, Union

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from loguru import logger

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200, FlowVersionCreate, FlowCompareReq, resp_500, \
    StreamData
from bisheng.common.chat.utils import process_node_data
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.flow import NotFoundVersionError, CurVersionDelError, VersionNameExistsError, \
    WorkFlowOnlineEditError
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.services import telemetry_service
from bisheng.common.services.base import BaseService
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import FlowDao, FlowStatus, Flow, FlowType
from bisheng.database.models.flow_version import FlowVersionDao, FlowVersionRead, FlowVersion
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum, GroupResource
from bisheng.database.models.role_access import AccessType
from bisheng.permission.domain.services.owner_service import OwnerService
from bisheng.permission.domain.workflow_app_permission import user_may_share_app
from bisheng.database.models.session import MessageSessionDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.permission.domain.services.application_permission_service import ApplicationPermissionService
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.utils import get_request_ip


class FlowService(BaseService):

    @classmethod
    def get_version_list_by_flow(cls, user: UserPayload, flow_id: str) -> UnifiedResponseModel[List[FlowVersionRead]]:
        """
        By SkillID Get all versions of a skill
        """
        data = FlowVersionDao.get_list_by_flow(flow_id)
        # Include Deleted Versions
        all_version_num = FlowVersionDao.count_list_by_flow(flow_id, include_delete=True)
        return resp_200(data={
            'data': data,
            'total': all_version_num
        })

    @classmethod
    def get_version_info(cls, user: UserPayload, version_id: int) -> UnifiedResponseModel[FlowVersion]:
        """
        According to versionIDGet version details
        """
        data = FlowVersionDao.get_version_by_id(version_id)
        return resp_200(data=data)

    @classmethod
    def delete_version(cls, user: UserPayload, version_id: int) -> UnifiedResponseModel[None]:
        """
        According to versionIDRemove Version
        """
        telemetry_service.log_event_sync(
            user_id=user.user_id,
            event_type=BaseTelemetryTypeEnum.EDIT_APPLICATION,
            trace_id=trace_id_var.get()
        )
        version_info = FlowVersionDao.get_version_by_id(version_id)
        if not version_info:
            return NotFoundVersionError.return_resp()

        flow_info = FlowDao.get_flow_by_id(version_info.flow_id)
        if not flow_info or flow_info.flow_type != FlowType.WORKFLOW.value:
            return NotFoundError.return_resp()

        # Determine permissions
        if not ApplicationPermissionService.has_any_permission_sync(
            user,
            'workflow',
            str(flow_info.id),
            ['edit_app'],
        ):
            return UnAuthorizedError.return_resp()

        if version_info.is_current == 1:
            return CurVersionDelError.return_resp()

        FlowVersionDao.delete_flow_version(version_id)
        return resp_200()

    @classmethod
    async def judge_flow_write_permission(cls, user: UserPayload, flow_id: str) -> Flow:
        flow_info = await FlowDao.aget_flow_by_id(flow_id)
        if not flow_info or flow_info.flow_type != FlowType.WORKFLOW.value:
            raise NotFoundError.http_exception()

        # Determine permissions
        if not await ApplicationPermissionService.has_any_permission_async(
            user,
            'workflow',
            str(flow_info.id),
            ['edit_app'],
        ):
            raise UnAuthorizedError.http_exception()
        return flow_info

    @classmethod
    async def change_current_version(cls, request: Request, login_user: UserPayload, flow_id: str, version_id: int) \
            -> UnifiedResponseModel[None]:
        """
        Modify Current Version
        """
        await telemetry_service.log_event(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.EDIT_APPLICATION,
            trace_id=trace_id_var.get()
        )
        flow_info = await cls.judge_flow_write_permission(login_user, flow_id)

        if flow_info.status == FlowStatus.ONLINE.value:
            return WorkFlowOnlineEditError.return_resp()

        # Switch versions
        version_info = await FlowVersionDao.aget_version_by_id(version_id)
        if not version_info:
            return NotFoundVersionError.return_resp()
        if version_info.is_current == 1:
            return resp_200()

        # Modify the version selected by the user for the current version
        await FlowVersionDao.change_current_version(flow_id, version_info)

        await cls.update_flow_hook(request, login_user, flow_info)
        return resp_200()

    @classmethod
    async def create_new_version(cls, user: UserPayload, flow_id: str, flow_version: FlowVersionCreate) \
            -> UnifiedResponseModel[FlowVersion]:
        """
        Create New Version
        """
        await telemetry_service.log_event(
            user_id=user.user_id,
            event_type=BaseTelemetryTypeEnum.EDIT_APPLICATION,
            trace_id=trace_id_var.get()
        )
        await cls.judge_flow_write_permission(user, flow_id)

        exist_version = FlowVersionDao.get_version_by_name(flow_id, flow_version.name)
        if exist_version:
            return VersionNameExistsError.return_resp()

        flow_version = FlowVersion(flow_id=flow_id, name=flow_version.name, description=flow_version.description,
                                   user_id=user.user_id, data=flow_version.data,
                                   original_version_id=flow_version.original_version_id,
                                   flow_type=flow_version.flow_type)

        # Create New Version
        flow_version = FlowVersionDao.create_version(flow_version)

        return resp_200(data=flow_version)

    @classmethod
    async def update_version_info(cls, request: Request, user: UserPayload, version_id: int,
                                  flow_version: FlowVersionCreate) \
            -> UnifiedResponseModel[FlowVersion]:
        """
        It updates version information.
        """
        await telemetry_service.log_event(
            user_id=user.user_id,
            event_type=BaseTelemetryTypeEnum.EDIT_APPLICATION,
            trace_id=trace_id_var.get()
        )
        # Contains the deleted version. If the version is deleted, revert to this version
        version_info = await FlowVersionDao.aget_version_by_id(version_id, include_delete=True)
        if not version_info:
            return NotFoundVersionError.return_resp()
        flow_info = await cls.judge_flow_write_permission(user, version_info.flow_id)

        if version_info.is_current == 1 and flow_info.status == FlowStatus.ONLINE.value and flow_version.data:
            return WorkFlowOnlineEditError.return_resp()

        version_info.name = flow_version.name if flow_version.name else version_info.name
        version_info.description = flow_version.description if flow_version.description else version_info.description
        version_info.data = flow_version.data if flow_version.data else version_info.data
        version_info.is_delete = 0

        flow_version = await FlowVersionDao.aupdate_version(version_info)

        await cls.update_flow_hook(request, user, flow_info)
        return resp_200(data=flow_version)

    @classmethod
    async def get_one_flow(cls, login_user: UserPayload, flow_id: str, share_link: Union['ShareLink', None] = None) -> \
            UnifiedResponseModel[Flow]:
        flow_info = await FlowDao.aget_flow_by_id(flow_id)
        if not flow_info or flow_info.flow_type != FlowType.WORKFLOW.value:
            raise NotFoundError()
        if not await ApplicationPermissionService.has_any_permission_async(
            login_user,
            'workflow',
            str(flow_info.id),
            ['view_app', 'use_app'],
        ):
            raise UnAuthorizedError()

        flow_info.logo = await cls.get_logo_share_link_async(flow_info.logo)

        payload = jsonable_encoder(flow_info)
        payload['can_share'] = await user_may_share_app(login_user, 'workflow', flow_id)
        return resp_200(data=payload)

    @classmethod
    async def get_compare_tasks(cls, user: UserPayload, req: FlowCompareReq) -> List:
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
                task = asyncio.create_task(cls.exec_flow_node(
                    copy.deepcopy(tmp_inputs), tmp_tweaks, question_index, [version]))
                tasks.append(task)
        return tasks

    @classmethod
    def parse_compare_inputs(cls, inputs: Dict, question) -> (Dict, Dict):
        # Under special treatmentinputs, Hold and PasswebsocketSessions are formatted consistently
        if inputs.get('data', None):
            for one in inputs['data']:
                one['id'] = one['nodeId']
                if 'InputFile' in one['id']:
                    one['file_path'] = one['value']

        # Paddingquestion and Generate Replacementtweaks
        for key, val in inputs.items():
            if key != 'data' and key != 'id':
                # Default inputkey, replace the firstkey
                logger.info(f"replace_inputs {key} replace to {question}")
                inputs[key] = question
                break
        if 'id' in inputs:
            inputs.pop('id')
        # Replacement Node Parameters, GantiinputFileNodeAndVariableNodeParameters
        tweaks = {}
        if 'data' in inputs:
            node_data = inputs.pop('data')
            if node_data:
                tweaks = process_node_data(node_data)
        return inputs, tweaks

    @classmethod
    async def compare_flow_node(cls, user: UserPayload, req: FlowCompareReq) -> UnifiedResponseModel[Dict]:
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
            return resp_500(message="Workflow comparison error:{}".format(str(e)))
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
                yield str(StreamData(event='message',
                                     data={'question_index': index,
                                           'version_id': version_id,
                                           'answer': answer}))

    @classmethod
    async def exec_flow_node(cls, inputs: Dict, tweaks: Dict, index: int, versions: List[FlowVersion]):
        # Gantianswer
        raise ValueError("flow is not supported")

    @classmethod
    def create_flow_hook(cls, request: Request, login_user: UserPayload, flow_info: Flow) -> bool:
        logger.info(f'create_flow_hook flow: {flow_info.id}, user_payload: {login_user.user_id}')

        # F008: Write owner tuple to OpenFGA (INV-2)
        from bisheng.permission.domain.services.owner_service import OwnerService
        OwnerService.write_owner_tuple_sync(login_user.user_id, 'workflow', str(flow_info.id))

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
    def delete_flow_hook(cls, request: Request, login_user: UserPayload, flow_info: Flow) -> bool:
        logger.info(f'delete_flow_hook flow: {flow_info.id}, user_payload: {login_user.user_id}')

        # Write Audit Log
        AuditLogService.delete_build_workflow(login_user, get_request_ip(request), flow_info)

        # Delete Skills Associated Under User Group
        GroupResourceDao.delete_group_resource_by_third_id(flow_info.id, ResourceTypeEnum.WORK_FLOW)

        # F008: Clean up all ReBAC tuples for the deleted workflow.
        OwnerService.delete_resource_tuples_sync('workflow', str(flow_info.id))

        # Update session information
        MessageSessionDao.update_session_info_by_flow(flow_info.name, flow_info.description, flow_info.logo,
                                                      flow_info.id, flow_info.flow_type)
        return True
