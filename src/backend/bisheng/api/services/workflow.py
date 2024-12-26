from typing import Dict, List, Optional
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder
from langchain.memory import ConversationBufferWindowMemory

from bisheng.api.errcode.base import NotFoundError, UnAuthorizedError
from bisheng.api.errcode.flow import WorkFlowInitError
from bisheng.api.services.base import BaseService
from bisheng.api.services.user_service import UserPayload
from bisheng.database.models.flow import FlowDao, FlowType, FlowStatus
from bisheng.database.models.flow_version import FlowVersionDao
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.tag import TagDao
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_role import UserRoleDao
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.node import BaseNodeData, NodeType
from bisheng.workflow.graph.graph_state import GraphState
from bisheng.workflow.graph.workflow import Workflow
from bisheng.workflow.nodes.node_manage import NodeFactory


class WorkFlowService(BaseService):

    @classmethod
    def get_all_flows(cls, user: UserPayload, name: str, status: int, tag_id: Optional[int], flow_type: Optional[int],
                      page: int = 1,
                      page_size: int = 10) -> (list[dict], int):
        """
        获取所有技能
        """
        # 通过tag获取id列表
        flow_ids = []
        if tag_id:
            ret = TagDao.get_resources_by_tags_batch([tag_id], [ResourceTypeEnum.FLOW, ResourceTypeEnum.WORK_FLOW, ResourceTypeEnum.ASSISTANT])
            if not ret:
                return [], 0
            flow_ids = [one.resource_id for one in ret]

        # 获取用户可见的技能列表
        if user.is_admin():
            data, total = FlowDao.get_all_apps(name, status, flow_ids, flow_type, None, None, page, page_size)
        else:
            user_role = UserRoleDao.get_user_roles(user.user_id)
            role_ids = [role.role_id for role in user_role]
            role_access = RoleAccessDao.get_role_access_batch(role_ids, [AccessType.FLOW, AccessType.WORK_FLOW, AccessType.ASSISTANT_READ])
            flow_id_extra = []
            if role_access:
                flow_id_extra = [access.third_id for access in role_access]
            data, total = FlowDao.get_all_apps(name, status, flow_ids, flow_type, user.user_id, flow_id_extra, page, page_size)

        # 应用ID列表
        resource_ids = []
        # 技能创建用户的ID列表
        user_ids = []
        for one in data:
            one['id'] = one['id'].hex
            resource_ids.append(one['id'])
            user_ids.append(one['user_id'])
        # 获取列表内的用户信息
        user_infos = UserDao.get_user_by_ids(user_ids)
        user_dict = {one.user_id: one.user_name for one in user_infos}

        # 获取列表内的版本信息
        version_infos = FlowVersionDao.get_list_by_flow_ids(resource_ids)
        flow_versions = {}
        for one in version_infos:
            if one.flow_id not in flow_versions:
                flow_versions[one.flow_id] = []
            flow_versions[one.flow_id].append(jsonable_encoder(one))

        resource_groups = GroupResourceDao.get_resources_group(None, resource_ids)
        resource_group_dict = {}
        for one in resource_groups:
            if one.third_id not in resource_group_dict:
                resource_group_dict[one.third_id] = []
            resource_group_dict[one.third_id].append(one.group_id)

        resource_tag_dict = TagDao.get_tags_by_resource(None, resource_ids)

        # 增加额外的信息
        for one in data:
            one['user_name'] = user_dict.get(one['user_id'], one['user_id'])
            one['write'] = True if user.is_admin() or user.user_id == one['user_id'] else False
            one['version_list'] = flow_versions.get(one['id'], [])
            one['group_ids'] = resource_group_dict.get(one['id'], [])
            one['tags'] = resource_tag_dict.get(one['id'], [])
            one['logo'] = cls.get_logo_share_link(one['logo'])
            if one['flow_type'] != FlowType.ASSISTANT.value:
                one['id'] = UUID(one['id'])

        return data, total

    @classmethod
    def run_once(cls, login_user: UserPayload, node_input: Dict[str, any], node_data: Dict[any, any]):

        node_data = BaseNodeData(**node_data.get('data', {}))
        base_callback = BaseCallback()
        graph_state = GraphState()
        graph_state.history_memory = ConversationBufferWindowMemory(k=10)
        node = NodeFactory.instance_node(node_type=node_data.type,
                                         node_data=node_data,
                                         user_id=login_user.user_id,
                                         workflow_id='tmp_workflow_single_node',
                                         graph_state=graph_state,
                                         target_edges=None,
                                         max_steps=233,
                                         callback=base_callback)
        if node_data.type == NodeType.CODE.value:
            node.handle_input({
                'code_input': [
                    {
                        'key': k.split('.')[1],
                        'value': v,
                        'type': 'input'
                    }for k, v in node_input.items()
                ]
            })
        elif node_data.type ==  NodeType.TOOL.value:

            pass
        else:
            for key, val in node_input.items():
                graph_state.set_variable_by_str(key, val)

        exec_id = uuid4().hex
        result = node._run(exec_id)
        log_data = node.parse_log(exec_id, result)
        ret = []
        for one in log_data:
            if node_data.type == NodeType.QA_RETRIEVER.value and one['key'] != 'retrieved_result':
                continue
            if node_data.type == NodeType.RAG.value and one['key'] != 'retrieved_result' and not one['key'].startswith('output'):
                continue
            if node_data.type == NodeType.LLM.value and not one['key'].startswith('output'):
                continue
            if node_data.type == NodeType.AGENT.value and one['type'] != 'tool' and not one['key'].startswith('output'):
                continue
            if node_data.type == NodeType.CODE.value and one['key'] != 'code_output':
                continue
            if node_data.type == NodeType.TOOL.value and one['key'] != 'output':
                continue
            ret.append({
                'key': one['key'],
                'value': one['value'],
                'type': one['type']
            })
        return ret

    @classmethod
    def update_flow_status(cls, login_user: UserPayload, flow_id: str, version_id: int, status: int):
        """
        修改工作流状态, 同时修改工作流的当前版本
        """
        db_flow = FlowDao.get_flow_by_id(flow_id)
        if not db_flow:
            raise NotFoundError.http_exception()
        if not login_user.access_check(db_flow.user_id, flow_id, AccessType.WORK_FLOW_WRITE):
            raise UnAuthorizedError.http_exception()

        version_info = FlowVersionDao.get_version_by_id(version_id)
        if not version_info or version_info.flow_id != flow_id:
            raise NotFoundError.http_exception()
        if status == FlowStatus.ONLINE.value:
            # workflow的初始化校验
            try:
                _ = Workflow(flow_id, login_user.user_id, version_info.data, False,
                             10,
                             10,
                             None)
            except Exception as e:
                raise WorkFlowInitError.http_exception(f'workflow init error: {str(e)}')

            FlowVersionDao.change_current_version(flow_id, version_info)
        db_flow.status = status
        FlowDao.update_flow(db_flow)
        return
