import asyncio
import uuid
from typing import Dict, Optional, List
from bisheng.worker.workflow.tasks import execute_workflow
from bisheng.database.models.group import GroupDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.utils import generate_uuid
import json
import os
from tempfile import TemporaryDirectory
from typing import Dict, Optional
from uuid import UUID

from fastapi import UploadFile
from fastapi.encoders import jsonable_encoder
from langchain.memory import ConversationBufferWindowMemory

from bisheng.api.errcode.base import NotFoundError, UnAuthorizedError
from bisheng.api.errcode.flow import WorkFlowInitError
from bisheng.api.services.base import BaseService
from bisheng.api.services.knowledge_imp import read_chunk_text
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import ChatResponse
from bisheng.api.v1.schema.workflow import WorkflowEvent, WorkflowEventType, WorkflowInputSchema, WorkflowInputItem, \
    WorkflowOutputSchema, WorkflowStream
from bisheng.api.v1.schema.workflow import WorkflowEvent, WorkflowEventType, WorkflowOutputSchema, WorkflowInputSchema, \
    WorkflowInputItem
from bisheng.api.v1.schemas import ChatResponse
from bisheng.cache.redis import redis_client
from bisheng.cache.utils import save_uploaded_file
from bisheng.chat.utils import SourceType
from bisheng.database.models.flow import FlowDao, FlowType, FlowStatus
from bisheng.database.models.flow_version import FlowVersionDao
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.tag import TagDao
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_role import UserRoleDao
from bisheng.utils import generate_uuid
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.node import BaseNodeData, NodeType
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.graph.graph_state import GraphState
from bisheng.workflow.graph.workflow import Workflow
from bisheng.workflow.nodes.node_manage import NodeFactory
from loguru import logger


class WorkFlowService(BaseService):

    @classmethod
    def get_company_members_by_uid(cls,user_id: int) -> List[int]:
        user_groups = UserGroupDao.get_user_group(user_id)
        if not user_groups:
            return []
        group_ids = [ug.group_id for ug in user_groups]
        group_infos = GroupDao.get_group_by_ids(group_ids)
        codes = set([str(g.code).split("|")[0] for g in group_infos if g.code])
        all_group_id = []
        for code in codes:
            group_info = GroupDao.get_child_groups(code)
            all_group_id.extend([g.id for g in group_info])
        all_user_id = UserGroupDao.get_groups_user(all_group_id)
        logger.info(f"WorkFlowService get_company_members_by_uid user_id={user_id} all_user_id={all_user_id}")
        return list(set(all_user_id))

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
            ret = TagDao.get_resources_by_tags_batch([tag_id], [ResourceTypeEnum.FLOW, ResourceTypeEnum.WORK_FLOW,
                                                                ResourceTypeEnum.ASSISTANT])
            if not ret:
                return [], 0
            flow_ids = [one.resource_id for one in ret]

        # 获取用户可见的技能列表
        if user.is_admin():
            data, total = FlowDao.get_all_apps(name, status, flow_ids, flow_type, None, None, page, page_size)
        else:
#<<<<<<< HEAD
            # user_role = UserRoleDao.get_user_roles(user.user_id)
            # role_ids = [role.role_id for role in user_role]
# DONE merge_check 用下方
#=======
            role_ids = user.user_role
#>>>>>>> feat/zyrs_0527
            role_access = RoleAccessDao.get_role_access_batch(role_ids, [AccessType.FLOW, AccessType.WORK_FLOW,
                                                                         AccessType.ASSISTANT_READ])
            flow_id_extra = []
            if role_access:
                flow_id_extra = [access.third_id for access in role_access]
            all_user_id = cls.get_company_members_by_uid(user.user_id)
            data, total = FlowDao.get_all_apps(name, status, flow_ids, flow_type, None, flow_id_extra, page,
                                               page_size,all_user_id)

        # 应用ID列表
        resource_ids = []
        # 技能创建用户的ID列表
        user_ids = []
        for one in data:
            one['id'] = one['id']
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
            one['id'] = one['id']

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
                        'key': k,
                        'value': v,
                        'type': 'input'
                    } for k, v in node_input.items()
                ]
            })
        elif node_data.type == NodeType.TOOL.value:
            user_input = {}
            for k, v in node_input.items():
                user_input[k] = v
            node.handle_input(user_input)
        else:
            for key, val in node_input.items():
                graph_state.set_variable_by_str(key, val)

        exec_id = generate_uuid()
        result = node._run(exec_id)
        log_data = node.parse_log(exec_id, result)
        res = []
        for one_batch in log_data:
            ret = []
            for one in one_batch:
                if node_data.type == NodeType.QA_RETRIEVER.value and one['key'] != 'retrieved_result':
                    continue
                if node_data.type == NodeType.RAG.value and one['key'] != 'retrieved_result' and one['type'] != 'variable':
                    continue
                if node_data.type == NodeType.LLM.value and one['type'] != 'variable':
                    continue
                if node_data.type == NodeType.AGENT.value and one['type'] not in ['tool', 'variable']:
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
            res.append(ret)
        return res

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

    @classmethod
    async def process_input_file(cls, login_user: UserPayload, upload_file: UploadFile):
        """
        处理工作流对话框输入的文件
        """
        file_id = generate_uuid()
        # 保存文件内容到本地，并解析出文件内容
        texts = []
        with TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, upload_file.filename)
            with open(file_path, 'wb') as tmp_file:
                tmp_file.write(upload_file.file.read())
            texts, _, _, _ = read_chunk_text(file_path, upload_file.filename,
                                             ['\n\n', '\n'], ['after', 'after'], 1000, 500)
            if len(texts) == 0:
                raise ValueError('文件解析为空')
        upload_file.file.seek(0)
        # 文件上传到minio
        file_path = save_uploaded_file(upload_file.file, 'tmp', file_id)

        # 数据存储到redis内
        redis_client.set(f"workflow:dialog_file:{file_id}", json.dumps({
            "path": file_path,
            "content": "\n".join(texts),
            "name": upload_file.filename
        }, ensure_ascii=False))
        return {
            'id': file_id,
            'name': upload_file.filename,
            'size': upload_file.size,
        }


    @classmethod
    def convert_chat_response_to_workflow_event(cls, chat_response: ChatResponse) -> WorkflowEvent:
        workflow_event = WorkflowEvent(
            event=chat_response.category,
            message_id=chat_response.message_id,
            status='end',
            node_id=chat_response.message.get('node_id'),
            node_execution_id=chat_response.message.get('unique_id'),
        )
        match workflow_event.event:
            case WorkflowEventType.UserInput.value:
                return cls.convert_user_input_event(chat_response, workflow_event)
            case WorkflowEventType.GuideWord.value:
                workflow_event.output_schema = WorkflowOutputSchema(
                    message=chat_response.message.get('guide_word')
                )
            case WorkflowEventType.GuideQuestion.value:
                workflow_event.output_schema = WorkflowOutputSchema(
                    message=chat_response.message.get('guide_question')
                )
            case WorkflowEventType.OutputMsg.value:
                return cls.convert_output_event(chat_response, workflow_event)
            case WorkflowEventType.OutputWithChoose.value:
                return cls.convert_output_choose_event(chat_response, workflow_event)
            case WorkflowEventType.OutputWithInput.value:
                return cls.convert_output_input_event(chat_response, workflow_event)
            case WorkflowEventType.StreamMsg.value:
                workflow_event.status = chat_response.type
                workflow_event.output_schema = WorkflowOutputSchema(
                    message=chat_response.message.get('msg'),
                    reasoning_content=chat_response.message.get('reasoning_content'),
                    output_key=chat_response.message.get('output_key'),
                )
                cls.handle_source(chat_response, workflow_event)
            case WorkflowEventType.Error.value:
                workflow_event.event = WorkflowEventType.Close.value
                workflow_event.output_schema = WorkflowOutputSchema(
                    message=chat_response.message
                )

        return workflow_event

    @classmethod
    def handle_source(cls, chat_response: ChatResponse, workflow_event: WorkflowEvent):
        if chat_response.source == SourceType.FILE.value:
            workflow_event.output_schema.source_url = f'resouce/{chat_response.chat_id}/{chat_response.message_id}'
        elif chat_response.source in [SourceType.LINK.value, SourceType.QA.value]:
            workflow_event.output_schema.extra = chat_response.extra


    @classmethod
    def convert_user_input_event(cls, chat_response: ChatResponse, workflow_event: WorkflowEvent) -> WorkflowEvent:
        event_input_schema = chat_response.message.get('input_schema')
        input_schema = WorkflowInputSchema(
            input_type=event_input_schema.get('tab'),
        )
        if input_schema.input_type == 'form_input':
            # 前端的表单定义转为后端的表单定义
            input_schema.value = [WorkflowInputItem(**one) for one in event_input_schema.get('value', [])]
            for one in input_schema.value:
                one.label = one.value
                one.value = ''
        else:
            # 说明是输入框输入
            input_schema.value = [
                WorkflowInputItem(
                    key=event_input_schema.get('key'),
                    type='text',
                    required=True,
                    value=''
                ),
                WorkflowInputItem(
                    key='dialog_files_content',
                    type='dialog_file',
                )
            ]
            for one in event_input_schema.get('value', []):
                tmp = WorkflowInputItem(**one)
                if tmp.key == 'dialog_files_content':
                    tmp.type = 'dialog_file'
                    tmp.value = []
                elif tmp.key == 'dialog_file_accept':
                    tmp.type = 'dialog_file_accept'
                input_schema.value.append(tmp)

        workflow_event.input_schema = input_schema
        return workflow_event

    @classmethod
    def convert_output_event(cls, chat_response: ChatResponse, workflow_event: WorkflowEvent) -> WorkflowEvent:
        workflow_event.output_schema = WorkflowOutputSchema(
            message=chat_response.message.get('msg'),
            files=chat_response.files,
            output_key=chat_response.message.get('output_key')
        )
        cls.handle_source(chat_response, workflow_event)
        return workflow_event

    @classmethod
    def convert_output_input_event(cls, chat_response: ChatResponse, workflow_event: WorkflowEvent) -> WorkflowEvent:
        workflow_event = cls.convert_output_event(chat_response, workflow_event)
        workflow_event.input_schema = WorkflowInputSchema(
            input_type='message_inline_input',
            value=[WorkflowInputItem(
                key=chat_response.message.get('key'),
                type='text',
                required=True,
                value=chat_response.message.get('input_msg', '')
            )]
        )
        return workflow_event

    @classmethod
    def convert_output_choose_event(cls, chat_response: ChatResponse, workflow_event: WorkflowEvent) -> WorkflowEvent:
        workflow_event = cls.convert_output_event(chat_response, workflow_event)
        workflow_event.input_schema = WorkflowInputSchema(
            input_type='message_inline_option',
            value=[WorkflowInputItem(
                key=chat_response.message.get('key'),
                type='select',
                required=True,
                value='',
                options=chat_response.message.get('options', [])
            )]
        )
        return workflow_event

    @classmethod
    async def invoke_workflow(cls,workflow_id: str,
                              version:int,
                          user_input: Optional[dict],
                          message_id: Optional[int],
                          session_id: Optional[str],
                          stream: Optional[bool] = False):
        from bisheng.api.v2.utils import get_default_operator
        from bisheng.worker import RedisCallback
        login_user = get_default_operator()
        workflow_id = workflow_id

        # 解析出chat_id和unique_id
        if not session_id:
            chat_id = uuid.uuid4().hex
            unique_id = f'{chat_id}_async_task_id'
            session_id = unique_id
        else:
            chat_id = session_id.split('_', 1)[0]
            unique_id = session_id
        logger.debug(f'invoke_workflow: {workflow_id}, {session_id}')
        workflow = RedisCallback(unique_id, workflow_id, chat_id, str(login_user.user_id))

        # 查询工作流信息
        logger.info("workflow_id,version",workflow_id,version)
        workflow_info = FlowVersionDao.get_version_by_id(version)
        if not workflow_info:
            raise NotFoundError.http_exception()
        if workflow_info.flow_type != FlowType.WORKFLOW.value:
            raise NotFoundError.http_exception()

        # 查询工作流状态
        status_info = workflow.get_workflow_status()
        if not status_info:
            # 初始化工作流
            workflow.set_workflow_data(workflow_info.data)
            workflow.set_workflow_status(WorkflowStatus.WAITING.value)
            # 发起异步任务
            execute_workflow.delay(unique_id, workflow_id, chat_id, str(login_user.user_id))
        else:
            # 设置用户的输入
            if status_info['status'] == WorkflowStatus.INPUT.value and user_input:
                workflow.set_user_input(user_input, message_id)
                workflow.set_workflow_status(WorkflowStatus.INPUT_OVER.value)

        logger.debug(f'waiting workflow over or input: {workflow_id}, {session_id}')

        async def handle_workflow_event(event_list: List):
            async for event in workflow.get_response_until_break():
                if event.category == WorkflowEventType.NodeRun.value:
                    continue
                logger.debug(f'handle_workflow_event workflow event: {event}')
                # 非流式请求，过滤掉节点产生的流式输出事件
                if not stream and event.category == WorkflowEventType.StreamMsg.value and event.type == 'stream':
                    continue
                workflow_stream = WorkflowStream(session_id=session_id,
                                                 data=WorkFlowService.convert_chat_response_to_workflow_event(event))
                event_list.append(workflow_stream.data)
                yield workflow_stream
            tmp_status_info = workflow.get_workflow_status()
            if tmp_status_info['status'] in [WorkflowStatus.SUCCESS.value, WorkflowStatus.FAILED.value]:
                workflow.clear_workflow_status()
            if tmp_status_info['status'] == WorkflowStatus.SUCCESS.value:
                workflow_stream = WorkflowStream(session_id=session_id,
                                                 data=WorkflowEvent(event=WorkflowEventType.Close.value))
                event_list.append(workflow_stream.data)
                yield workflow_stream

        res = []
        # 非流式返回累计的事件列表
        if not stream:
            async for _ in handle_workflow_event(res):
                pass
            return {
                'session_id': session_id,
                'events': res
            }

    # 仅处理一问一答的workflow
    @classmethod
    async def run_workflow_1Q1A(cls, workflow_id: str, version: int, input: str) -> str:
        events = await cls.invoke_workflow(workflow_id, version, None, None, None, False)
        session_id = events['session_id']
        message_id = None
        node_id = None
        evens = events['events']
        for even in evens:
            if even.event != WorkflowEventType.UserInput.value:
                continue
            message_id = even.message_id
            node_id = even.node_id
            break
        out_put = ""
        if node_id and message_id:
            result = await cls.invoke_workflow(workflow_id, version, {node_id:{"user_input": str(input)}}, message_id, session_id, False)
            for even in result['events']:
                if even.event!= WorkflowEventType.OutputMsg.value:
                    continue
                out_put = even.output_schema.message
                break
        return out_put



