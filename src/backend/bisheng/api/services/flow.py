import asyncio
import copy
from typing import List, Dict, AsyncGenerator, Optional, Union

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from loguru import logger

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.base import BaseService
from bisheng.api.utils import get_L2_param_from_flow
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200, FlowVersionCreate, FlowCompareReq, resp_500, \
    StreamData
from bisheng.chat.utils import process_node_data
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.flow import NotFoundVersionError, CurVersionDelError, VersionNameExistsError, \
    NotFoundFlowError, \
    FlowOnlineEditError, WorkFlowOnlineEditError
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.services import telemetry_service
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import FlowDao, FlowStatus, Flow, FlowType
from bisheng.database.models.flow_version import FlowVersionDao, FlowVersionRead, FlowVersion
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum, GroupResource
from bisheng.database.models.role_access import RoleAccessDao, AccessType
from bisheng.database.models.session import MessageSessionDao
from bisheng.database.models.tag import TagDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.database.models.variable_value import VariableDao
from bisheng.processing.process import process_graph_cached, process_tweaks
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.models.user_role import UserRoleDao
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
        if not flow_info:
            return NotFoundFlowError.return_resp()

        atype = AccessType.FLOW_WRITE
        if flow_info.flow_type == FlowType.WORKFLOW.value:
            atype = AccessType.WORKFLOW_WRITE

        # Determine permissions
        if not user.access_check(flow_info.user_id, flow_info.id, atype):
            return UnAuthorizedError.return_resp()

        if version_info.is_current == 1:
            return CurVersionDelError.return_resp()

        FlowVersionDao.delete_flow_version(version_id)
        return resp_200()

    @classmethod
    async def judge_flow_write_permission(cls, user: UserPayload, flow_id: str) -> Flow:
        flow_info = await FlowDao.aget_flow_by_id(flow_id)
        if not flow_info:
            raise NotFoundFlowError.http_exception()

        atype = AccessType.FLOW_WRITE
        if flow_info.flow_type == FlowType.WORKFLOW.value:
            atype = AccessType.WORKFLOW_WRITE

        # Determine permissions
        if not await user.async_access_check(flow_info.user_id, flow_info.id, atype):
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

        # Skill go-live status not allowed Switch versions
        if flow_info.status == FlowStatus.ONLINE:
            return FlowOnlineEditError.return_resp()

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
        flow_info = await cls.judge_flow_write_permission(user, flow_id)

        exist_version = FlowVersionDao.get_version_by_name(flow_id, flow_version.name)
        if exist_version:
            return VersionNameExistsError.return_resp()

        flow_version = FlowVersion(flow_id=flow_id, name=flow_version.name, description=flow_version.description,
                                   user_id=user.user_id, data=flow_version.data,
                                   original_version_id=flow_version.original_version_id,
                                   flow_type=flow_version.flow_type)

        # Create New Version
        flow_version = FlowVersionDao.create_version(flow_version)

        if flow_info.flow_type == FlowType.FLOW.value:
            # Copy the original version of the form data into the new version
            VariableDao.copy_variables(flow_version.flow_id, flow_version.original_version_id, flow_version.id)
            try:
                # Refresh this version of the form data
                if not get_L2_param_from_flow(flow_version.data, flow_version.flow_id, flow_version.id):
                    logger.error(f'flow_id={flow_version.id} version_id={flow_version.id} extract file_node fail')
            except:
                pass
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

        # Version is the current version, Cannot be edited if the skill is onlinedataData, names and descriptions can be edited
        if version_info.is_current == 1 and flow_info.status == FlowStatus.ONLINE.value and flow_version.data:
            if flow_info.flow_type == FlowType.WORKFLOW.value:
                return WorkFlowOnlineEditError.return_resp()
            else:
                return FlowOnlineEditError.return_resp()

        version_info.name = flow_version.name if flow_version.name else version_info.name
        version_info.description = flow_version.description if flow_version.description else version_info.description
        version_info.data = flow_version.data if flow_version.data else version_info.data
        # Restore this skill version
        version_info.is_delete = 0

        flow_version = await FlowVersionDao.aupdate_version(version_info)

        if flow_version.flow_type == FlowType.FLOW.value:
            try:
                # Refresh this version of the form data
                if not get_L2_param_from_flow(flow_version.data, flow_version.flow_id, flow_version.id):
                    logger.error(f'flow_id={flow_version.id} version_id={flow_version.id} extract file_node fail')
            except:
                pass
        await cls.update_flow_hook(request, user, flow_info)
        return resp_200(data=flow_version)

    @classmethod
    async def get_one_flow(cls, login_user: UserPayload, flow_id: str, share_link: Union['ShareLink', None] = None) -> \
            UnifiedResponseModel[Flow]:
        """
        Get details on individual skills
        """
        flow_info = await FlowDao.aget_flow_by_id(flow_id)
        if not flow_info:
            raise NotFoundFlowError()
        atype = AccessType.FLOW
        if flow_info.flow_type == FlowType.WORKFLOW.value:
            atype = AccessType.WORKFLOW
        if not await login_user.async_access_check(flow_info.user_id, flow_info.id, atype):
            if (share_link is None
                    or share_link.meta_data is None
                    or share_link.meta_data.get("flowId") != flow_info.id):
                raise UnAuthorizedError()

        flow_info.logo = await cls.get_logo_share_link_async(flow_info.logo)

        return resp_200(data=flow_info)

    @classmethod
    def get_all_flows(cls, user: UserPayload, name: str, status: int, tag_id: int = 0, page: int = 1,
                      page_size: int = 10, flow_type: Optional[int] = FlowType.FLOW.value) -> UnifiedResponseModel[
        List[Dict]]:
        """
        Get all the skills
        """
        flow_ids = []
        if tag_id:
            ret = TagDao.get_resources_by_tags_batch([tag_id], [ResourceTypeEnum.FLOW, ResourceTypeEnum.WORK_FLOW])
            flow_ids = [one.resource_id for one in ret]
            assistant_ids = [one.resource_id for one in ret]
            if not assistant_ids:
                return resp_200(data={
                    'data': [],
                    'total': 0
                })
        # Get a list of skills visible to the user
        if user.is_admin():
            data = FlowDao.get_flows(user.user_id, "admin", name, status, flow_ids, page, page_size, flow_type)
            total = FlowDao.count_flows(user.user_id, "admin", name, status, flow_ids, flow_type)
        else:
            user_role = UserRoleDao.get_user_roles(user.user_id)
            role_ids = [role.role_id for role in user_role]
            role_access = RoleAccessDao.get_role_access_batch(role_ids, [AccessType.FLOW, AccessType.WORKFLOW])
            flow_id_extra = []
            if role_access:
                flow_id_extra = [access.third_id for access in role_access]
            data = FlowDao.get_flows(user.user_id, flow_id_extra, name, status, flow_ids, page, page_size, flow_type)
            total = FlowDao.count_flows(user.user_id, flow_id_extra, name, status, flow_ids, flow_type)

        # Get the user information and version information corresponding to the skill list
        # SkillIDVertical
        flow_ids = []
        # Skill Creation User'sIDVertical
        user_ids = []
        for one in data:
            flow_ids.append(one.id)
            user_ids.append(one.user_id)
        # Get user information in the list
        user_infos = UserDao.get_user_by_ids(user_ids)
        user_dict = {one.user_id: one.user_name for one in user_infos}

        # Get version information in the list
        version_infos = FlowVersionDao.get_list_by_flow_ids(flow_ids)
        flow_versions = {}
        for one in version_infos:
            if one.flow_id not in flow_versions:
                flow_versions[one.flow_id] = []
            flow_versions[one.flow_id].append(jsonable_encoder(one))

        # Get the group to which the skill belongs
        flow_groups = GroupResourceDao.get_resources_group(ResourceTypeEnum.FLOW, flow_ids)
        flow_group_dict = {}
        for one in flow_groups:
            if one.third_id not in flow_group_dict:
                flow_group_dict[one.third_id] = []
            flow_group_dict[one.third_id].append(one.group_id)

        # Get Skill Associatedtag
        flow_tags = TagDao.get_tags_by_resource(ResourceTypeEnum.FLOW, flow_ids)

        # Re-stitch Skills ListlistMessage
        res = []
        for one in data:
            one.logo = cls.get_logo_share_link(one.logo)
            flow_info = jsonable_encoder(one)
            flow_info['user_name'] = user_dict.get(one.user_id, one.user_id)
            flow_info['write'] = True if user.is_admin() or user.user_id == one.user_id else False
            flow_info['version_list'] = flow_versions.get(one.id, [])
            flow_info['group_ids'] = flow_group_dict.get(one.id, [])
            flow_info['tags'] = flow_tags.get(one.id, [])

            res.append(flow_info)

        return resp_200(data={
            "data": res,
            "total": total
        })

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
            return resp_500(message="Skill comparison error:{}".format(str(e)))
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
        answer_result = {}
        # Execute two versions of the node
        for one in versions:
            graph_data = process_tweaks(one.data, tweaks)
            try:
                result = await process_graph_cached(graph_data,
                                                    inputs,
                                                    session_id=None,
                                                    history_count=10,
                                                    flow_id=one.flow_id)
            except Exception as e:
                logger.exception(f"exec flow node error version_id: {one.name}")
                answer_result[one.id] = f"{one.name}Version skill execution error: {str(e)}"
                continue
            if isinstance(result, dict) and 'result' in result:
                task_result = result['result']
            elif hasattr(result, 'result') and hasattr(result, 'session_id'):
                task_result = result.result
            else:
                logger.error(f"exec flow node error version_id: {one.id}, answer: {result}")
                task_result = {"answer": "flow exec error"}

            answer_result[one.id] = list(task_result.values())[0]

        return index, answer_result

    @classmethod
    def create_flow_hook(cls, request: Request, login_user: UserPayload, flow_info: Flow, version_id,
                         flow_type: Optional[int] = None) -> bool:
        logger.info(f'create_flow_hook flow: {flow_info.id}, user_payload: {login_user.user_id}')
        # Write the form required for the skill into the database
        try:
            if flow_info.data and not get_L2_param_from_flow(flow_info.data, flow_info.id, version_id):
                logger.error(f'flow_id={flow_info.id} extract file_node fail')
        except Exception:
            pass
        # Associate the skill to the corresponding user group
        user_group = UserGroupDao.get_user_group(login_user.user_id)
        if user_group:
            batch_resource = []
            resource_type = ResourceTypeEnum.FLOW.value
            if flow_type and flow_type == FlowType.WORKFLOW.value:
                resource_type = ResourceTypeEnum.WORK_FLOW.value

            for one in user_group:
                batch_resource.append(
                    GroupResource(group_id=one.group_id,
                                  third_id=flow_info.id,
                                  type=resource_type))
            GroupResourceDao.insert_group_batch(batch_resource)
        # Write Audit Log
        AuditLogService.create_build_flow(login_user, get_request_ip(request), flow_info.id, flow_type)

        # WritelogoCeacle
        cls.get_logo_share_link(flow_info.logo)
        return True

    @classmethod
    async def update_flow_hook(cls, request: Request, login_user: UserPayload, flow_info: Flow) -> bool:
        # Write Audit Log
        await AuditLogService.update_build_flow(login_user, get_request_ip(request), flow_info.id,
                                                flow_type=flow_info.flow_type)

        # WritelogoCeacle
        await cls.get_logo_share_link_async(flow_info.logo)
        return True

    @classmethod
    def delete_flow_hook(cls, request: Request, login_user: UserPayload, flow_info: Flow) -> bool:
        logger.info(f'delete_flow_hook flow: {flow_info.id}, user_payload: {login_user.user_id}')

        # Write Audit Log
        AuditLogService.delete_build_flow(login_user, get_request_ip(request), flow_info, flow_type=flow_info.flow_type)

        # Delete Skills Associated Under User Group
        GroupResourceDao.delete_group_resource_by_third_id(flow_info.id, ResourceTypeEnum.FLOW)

        # Update session information
        MessageSessionDao.update_session_info_by_flow(flow_info.name, flow_info.description, flow_info.logo,
                                                      flow_info.id, flow_info.flow_type)
        return True
