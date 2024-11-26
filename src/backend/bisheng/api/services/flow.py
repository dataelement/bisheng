import asyncio
import copy
from typing import List, Dict, AsyncGenerator, Optional
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from fastapi import Request
from loguru import logger

from bisheng.api.errcode.base import UnAuthorizedError, NotFoundError
from bisheng.api.errcode.flow import NotFoundVersionError, CurVersionDelError, VersionNameExistsError, \
    NotFoundFlowError, \
    FlowOnlineEditError
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.base import BaseService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.utils import get_L2_param_from_flow, get_request_ip
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200, FlowVersionCreate, FlowCompareReq, resp_500, \
    StreamData
from bisheng.chat.utils import process_node_data
from bisheng.database.models.flow import FlowDao, FlowStatus, Flow, FlowType
from bisheng.database.models.flow_version import FlowVersionDao, FlowVersionRead, FlowVersion
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum, GroupResource
from bisheng.database.models.role_access import RoleAccessDao, AccessType
from bisheng.database.models.tag import TagDao
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.database.models.user_role import UserRoleDao
from bisheng.database.models.variable_value import VariableDao
from bisheng.processing.process import process_graph_cached, process_tweaks


class FlowService(BaseService):

    @classmethod
    def get_version_list_by_flow(cls, user: UserPayload, flow_id: str) -> UnifiedResponseModel[List[FlowVersionRead]]:
        """
        根据技能ID 获取技能的所有版本信息
        """
        data = FlowVersionDao.get_list_by_flow(flow_id)
        # 包含已删除版本
        all_version_num = FlowVersionDao.count_list_by_flow(flow_id, include_delete=True)
        return resp_200(data={
            'data': data,
            'total': all_version_num
        })

    @classmethod
    def get_version_info(cls, user: UserPayload, version_id: int) -> UnifiedResponseModel[FlowVersion]:
        """
        根据版本ID获取版本详细信息
        """
        data = FlowVersionDao.get_version_by_id(version_id)
        return resp_200(data=data)

    @classmethod
    def delete_version(cls, user: UserPayload, version_id: int) -> UnifiedResponseModel[None]:
        """
        根据版本ID删除版本
        """
        version_info = FlowVersionDao.get_version_by_id(version_id)
        if not version_info:
            return NotFoundVersionError.return_resp()

        flow_info = FlowDao.get_flow_by_id(version_info.flow_id)
        if not flow_info:
            return NotFoundFlowError.return_resp()

        atype = AccessType.FLOW_WRITE
        if flow_info.flow_type == FlowType.WORKFLOW.value:
            atype = AccessType.WORK_FLOW_WRITE

        # 判断权限
        if not user.access_check(flow_info.user_id, flow_info.id.hex, atype):
            return UnAuthorizedError.return_resp()

        if version_info.is_current == 1:
            return CurVersionDelError.return_resp()

        FlowVersionDao.delete_flow_version(version_id)
        return resp_200()

    @classmethod
    def change_current_version(cls, request: Request, login_user: UserPayload, flow_id: str, version_id: int) \
            -> UnifiedResponseModel[None]:
        """
        修改当前版本
        """
        flow_info = FlowDao.get_flow_by_id(flow_id)
        if not flow_info:
            return NotFoundFlowError.return_resp()

        atype = AccessType.FLOW_WRITE
        if flow_info.flow_type == FlowType.WORKFLOW.value:
            atype = AccessType.WORK_FLOW_WRITE


        # 判断权限
        if not login_user.access_check(flow_info.user_id, flow_info.id.hex, atype):
            return UnAuthorizedError.return_resp()

        # 技能上线状态不允许 切换版本
        if flow_info.status == FlowStatus.ONLINE:
            return FlowOnlineEditError.return_resp()

        # 切换版本
        version_info = FlowVersionDao.get_version_by_id(version_id)
        if not version_info:
            return NotFoundVersionError.return_resp()
        if version_info.is_current == 1:
            return resp_200()

        # 修改当前版本为用户选择的版本
        FlowVersionDao.change_current_version(flow_id, version_info)

        cls.update_flow_hook(request, login_user, flow_info)
        return resp_200()

    @classmethod
    def create_new_version(cls, user: UserPayload, flow_id: str, flow_version: FlowVersionCreate) \
            -> UnifiedResponseModel[FlowVersion]:
        """
        创建新版本
        """
        flow_info = FlowDao.get_flow_by_id(flow_id)
        if not flow_info:
            return NotFoundFlowError.return_resp()

        # 判断权限
        if not user.access_check(flow_info.user_id, flow_info.id.hex, AccessType.FLOW_WRITE):
            return UnAuthorizedError.return_resp()

        exist_version = FlowVersionDao.get_version_by_name(flow_id, flow_version.name)
        if exist_version:
            return VersionNameExistsError.return_resp()

        flow_version = FlowVersion(flow_id=flow_id, name=flow_version.name, description=flow_version.description,
                                   user_id=user.user_id, data=flow_version.data,
                                   original_version_id=flow_version.original_version_id,flow_type=flow_version.flow_type)

        # 创建新版本
        flow_version = FlowVersionDao.create_version(flow_version)

        # 将原始版本的表单数据拷贝到新版本内
        VariableDao.copy_variables(flow_version.flow_id, flow_version.original_version_id, flow_version.id)

        try:
            # 重新整理此版本的表单数据
            if not get_L2_param_from_flow(flow_version.data, flow_version.flow_id, flow_version.id):
                logger.error(f'flow_id={flow_version.id} version_id={flow_version.id} extract file_node fail')
        except:
            pass

        return resp_200(data=flow_version)

    @classmethod
    def update_version_info(cls, request: Request, user: UserPayload, version_id: int, flow_version: FlowVersionCreate) \
            -> UnifiedResponseModel[FlowVersion]:
        """
        更新版本信息
        """
        # 包含已删除的版本，若版本已删除，则重新恢复此版本
        version_info = FlowVersionDao.get_version_by_id(version_id, include_delete=True)
        if not version_info:
            return NotFoundVersionError.return_resp()
        flow_info = FlowDao.get_flow_by_id(version_info.flow_id)
        if not flow_info:
            return NotFoundFlowError.return_resp()

        atype = AccessType.FLOW_WRITE
        if flow_info.flow_type == FlowType.WORKFLOW.value:
            atype = AccessType.WORK_FLOW_WRITE
        # 判断权限
        if not user.access_check(flow_info.user_id, flow_info.id.hex, atype):
            return UnAuthorizedError.return_resp()

        # 版本是当前版本, 且技能处于上线状态则不可编辑
        if version_info.is_current == 1 and flow_info.status == FlowStatus.ONLINE.value:
            return FlowOnlineEditError.return_resp()

        version_info.name = flow_version.name if flow_version.name else version_info.name
        version_info.description = flow_version.description if flow_version.description else version_info.description
        version_info.data = flow_version.data if flow_version.data else version_info.data
        # 恢复此技能版本
        version_info.is_delete = 0

        flow_version = FlowVersionDao.update_version(version_info)

        try:
            # 重新整理此版本的表单数据
            if not get_L2_param_from_flow(flow_version.data, flow_version.flow_id, flow_version.id):
                logger.error(f'flow_id={flow_version.id} version_id={flow_version.id} extract file_node fail')
        except:
            pass
        cls.update_flow_hook(request, user, flow_info)
        return resp_200(data=flow_version)

    @classmethod
    def get_one_flow(cls, login_user: UserPayload, flow_id: str) -> UnifiedResponseModel[Flow]:
        """
        获取单个技能的详情
        """
        flow_info = FlowDao.get_flow_by_id(flow_id)
        if not flow_info:
            raise NotFoundFlowError.http_exception()
        atype = AccessType.FLOW
        if flow_info.flow_type == FlowType.WORKFLOW.value:
            atype = AccessType.WORK_FLOW
        if not login_user.access_check(flow_info.user_id, flow_info.id.hex, atype):
            raise UnAuthorizedError.http_exception()
        flow_info.logo = cls.get_logo_share_link(flow_info.logo)

        return resp_200(data=flow_info)

    @classmethod
    def get_all_flows(cls, user: UserPayload, name: str, status: int, tag_id: int = 0, page: int = 1,
                      page_size: int = 10, flow_type :Optional[int] = FlowType.FLOW.value) -> UnifiedResponseModel[List[Dict]]:
        """
        获取所有技能
        """
        flow_ids = []
        if tag_id:
            ret = TagDao.get_resources_by_tags([tag_id], ResourceTypeEnum.FLOW)
            flow_ids = [UUID(one.resource_id) for one in ret]
            assistant_ids = [UUID(one.resource_id) for one in ret]
            if not assistant_ids:
                return resp_200(data={
                    'data': [],
                    'total': 0
                })
        # 获取用户可见的技能列表
        if user.is_admin():
            data = FlowDao.get_flows(user.user_id, "admin", name, status, flow_ids, page, page_size,flow_type)
            total = FlowDao.count_flows(user.user_id, "admin", name, status, flow_ids,flow_type)
        else:
            user_role = UserRoleDao.get_user_roles(user.user_id)
            role_ids = [role.role_id for role in user_role]
            role_access = RoleAccessDao.get_role_access(role_ids, AccessType.FLOW)
            flow_id_extra = []
            if role_access:
                flow_id_extra = [access.third_id for access in role_access]
            data = FlowDao.get_flows(user.user_id, flow_id_extra, name, status, flow_ids, page, page_size,flow_type)
            total = FlowDao.count_flows(user.user_id, flow_id_extra, name, status, flow_ids,flow_type)

        # 获取技能列表对应的用户信息和版本信息
        # 技能ID列表
        flow_ids = []
        # 技能创建用户的ID列表
        user_ids = []
        for one in data:
            flow_ids.append(one.id.hex)
            user_ids.append(one.user_id)
        # 获取列表内的用户信息
        user_infos = UserDao.get_user_by_ids(user_ids)
        user_dict = {one.user_id: one.user_name for one in user_infos}

        # 获取列表内的版本信息
        version_infos = FlowVersionDao.get_list_by_flow_ids(flow_ids)
        flow_versions = {}
        for one in version_infos:
            if one.flow_id not in flow_versions:
                flow_versions[one.flow_id] = []
            flow_versions[one.flow_id].append(jsonable_encoder(one))

        # 获取技能所属的分组
        flow_groups = GroupResourceDao.get_resources_group(ResourceTypeEnum.FLOW, flow_ids)
        flow_group_dict = {}
        for one in flow_groups:
            if one.third_id not in flow_group_dict:
                flow_group_dict[one.third_id] = []
            flow_group_dict[one.third_id].append(one.group_id)

        # 获取技能关联的tag
        flow_tags = TagDao.get_tags_by_resource(ResourceTypeEnum.FLOW, flow_ids)

        # 重新拼接技能列表list信息
        res = []
        for one in data:
            one.logo = cls.get_logo_share_link(one.logo)
            flow_info = jsonable_encoder(one)
            flow_info['user_name'] = user_dict.get(one.user_id, one.user_id)
            flow_info['write'] = True if user.is_admin() or user.user_id == one.user_id else False
            flow_info['version_list'] = flow_versions.get(one.id.hex, [])
            flow_info['group_ids'] = flow_group_dict.get(one.id.hex, [])
            flow_info['tags'] = flow_tags.get(one.id.hex, [])

            res.append(flow_info)

        return resp_200(data={
            "data": res,
            "total": total
        })

    @classmethod
    async def get_compare_tasks(cls, user: UserPayload, req: FlowCompareReq) -> List:
        """
        获取比较任务
        """
        if req.question_list is None or len(req.question_list) == 0:
            return []
        if req.version_list is None or len(req.version_list) == 0:
            return []
        if req.node_id is None:
            return []

        # 获取版本数据
        version_infos = FlowVersionDao.get_list_by_ids(req.version_list)
        # 启动一个新的事件循环
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
        # 特殊处理下inputs, 保持和通过websocket会话的格式一致
        if inputs.get('data', None):
            for one in inputs['data']:
                one['id'] = one['nodeId']
                if 'InputFile' in one['id']:
                    one['file_path'] = one['value']

        # 填充question 和生成替换的tweaks
        for key, val in inputs.items():
            if key != 'data' and key != 'id':
                # 默认输入key，替换第一个需要输入的key
                logger.info(f"replace_inputs {key} replace to {question}")
                inputs[key] = question
                break
        if 'id' in inputs:
            inputs.pop('id')
        # 替换节点的参数, 替换inputFileNode和VariableNode的参数
        tweaks = {}
        if 'data' in inputs:
            node_data = inputs.pop('data')
            if node_data:
                tweaks = process_node_data(node_data)
        return inputs, tweaks

    @classmethod
    async def compare_flow_node(cls, user: UserPayload, req: FlowCompareReq) -> UnifiedResponseModel[Dict]:
        """
        比较两个版本中某个节点的 输出结果
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
            return resp_500(message="技能对比错误：{}".format(str(e)))
        return resp_200(data=res)

    @classmethod
    async def compare_flow_stream(cls, user: UserPayload, req: FlowCompareReq) -> AsyncGenerator:
        """
        比较两个版本中某个节点的 输出结果
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
        # 替换answer
        answer_result = {}
        # 执行两个版本的节点
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
                answer_result[one.id] = f"{one.name}版本技能执行出错： {str(e)}"
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
    def create_flow_hook(cls, request: Request, login_user: UserPayload, flow_info: Flow, version_id,flow_type:Optional[int]=None) -> bool:
        logger.info(f'create_flow_hook flow: {flow_info.id}, user_payload: {login_user.user_id}')
        # 将技能所需的表单写到数据库内
        try:
            if flow_info.data and not get_L2_param_from_flow(flow_info.data, flow_info.id.hex, version_id):
                logger.error(f'flow_id={flow_info.id} extract file_node fail')
        except Exception:
            pass
        # 将技能关联到对应的用户组下
        user_group = UserGroupDao.get_user_group(login_user.user_id)
        if user_group:
            batch_resource = []
            resource_type = ResourceTypeEnum.FLOW.value
            if flow_type and flow_type == FlowType.WORKFLOW.value:
                resource_type = ResourceTypeEnum.WORK_FLOW.value

            for one in user_group:
                batch_resource.append(
                    GroupResource(group_id=one.group_id,
                                  third_id=flow_info.id.hex,
                                  type=resource_type))
            GroupResourceDao.insert_group_batch(batch_resource)
        # 写入审计日志
        AuditLogService.create_build_flow(login_user, get_request_ip(request), flow_info.id.hex,flow_type)

        # 写入logo缓存
        cls.get_logo_share_link(flow_info.logo)
        return True

    @classmethod
    def update_flow_hook(cls, request: Request, login_user: UserPayload, flow_info: Flow) -> bool:
        # 写入审计日志
        AuditLogService.update_build_flow(login_user, get_request_ip(request), flow_info.id.hex,flow_type=flow_info.flow_type)

        # 写入logo缓存
        cls.get_logo_share_link(flow_info.logo)
        return True

    @classmethod
    def delete_flow_hook(cls, request: Request, login_user: UserPayload, flow_info: Flow) -> bool:
        logger.info(f'delete_flow_hook flow: {flow_info.id}, user_payload: {login_user.user_id}')

        # 写入审计日志
        AuditLogService.delete_build_flow(login_user, get_request_ip(request), flow_info,flow_type=flow_info.flow_type)

        # 将用户组下关联的技能删除
        GroupResourceDao.delete_group_resource_by_third_id(flow_info.id.hex, ResourceTypeEnum.FLOW)
        return True
