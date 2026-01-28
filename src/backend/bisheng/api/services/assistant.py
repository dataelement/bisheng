from datetime import datetime
from typing import Any, List, Optional, Union

from fastapi import Request
from loguru import logger

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.services.assistant_base import AssistantUtils
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.base import BaseService
from bisheng.api.v1.schemas import (AssistantInfo, AssistantSimpleInfo, AssistantUpdateReq,
                                    StreamData)
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.assistant import (AssistantInitError, AssistantNameRepeatError,
                                              AssistantNotEditError, AssistantNotExistsError)
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.schemas.telemetry.event_data_schema import NewApplicationEventData
from bisheng.common.services import telemetry_service
from bisheng.core.cache import InMemoryCache
from bisheng.core.logger import trace_id_var
from bisheng.database.models.assistant import (Assistant, AssistantDao, AssistantLinkDao,
                                               AssistantStatus)
from bisheng.database.models.flow import Flow, FlowDao, FlowType
from bisheng.database.models.group_resource import GroupResourceDao, GroupResource, ResourceTypeEnum
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.session import MessageSessionDao
from bisheng.database.models.tag import TagDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.llm.domain.services import LLMService
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao, GptsTools
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.models.user_role import UserRoleDao
from bisheng.utils import get_request_ip


class AssistantService(BaseService, AssistantUtils):
    UserCache: InMemoryCache = InMemoryCache()

    @classmethod
    def get_assistant(cls,
                      user: UserPayload,
                      name: str = None,
                      status: int | None = None,
                      tag_id: int | None = None,
                      page: int = 1,
                      limit: int = 20) -> (List[AssistantSimpleInfo], int):
        """
        Get list of assistants
        """
        assistant_ids = []
        if tag_id:
            ret = TagDao.get_resources_by_tags([tag_id], ResourceTypeEnum.ASSISTANT)
            assistant_ids = [one.resource_id for one in ret]
            if not assistant_ids:
                return [], 0

        data = []
        if user.is_admin():
            res, total = AssistantDao.get_all_assistants(name, page, limit, assistant_ids, status)
        else:
            # Permission management visible assistant information
            assistant_ids_extra = []
            user_role = UserRoleDao.get_user_roles(user.user_id)
            if user_role:
                role_ids = [role.role_id for role in user_role]
                role_access = RoleAccessDao.get_role_access(role_ids, AccessType.ASSISTANT_READ)
                if role_access:
                    assistant_ids_extra = [access.third_id for access in role_access]
            res, total = AssistantDao.get_assistants(user.user_id, name, assistant_ids_extra, status, page, limit,
                                                     assistant_ids)

        assistant_ids = [one.id for one in res]
        # Query groups to which the assistant belongs
        assistant_groups = GroupResourceDao.get_resources_group(ResourceTypeEnum.ASSISTANT, assistant_ids)
        assistant_group_dict = {}
        for one in assistant_groups:
            if one.third_id not in assistant_group_dict:
                assistant_group_dict[one.third_id] = []
            assistant_group_dict[one.third_id].append(one.group_id)

        # Get assistant-associatedtag
        flow_tags = TagDao.get_tags_by_resource(ResourceTypeEnum.ASSISTANT, assistant_ids)

        for one in res:
            one.logo = cls.get_logo_share_link(one.logo)
            simple_assistant = cls.return_simple_assistant_info(one)
            if one.user_id == user.user_id or user.is_admin():
                simple_assistant.write = True
            simple_assistant.group_ids = assistant_group_dict.get(one.id, [])
            simple_assistant.tags = flow_tags.get(one.id, [])
            data.append(simple_assistant)
        return data, total

    @classmethod
    def return_simple_assistant_info(cls, one: Assistant) -> AssistantSimpleInfo:
        """
        Put the database's assistantmodelSimplified After processing, it returns to the front-end format
        """
        simple_dict = one.model_dump(include={
            'id', 'name', 'desc', 'logo', 'status', 'user_id', 'create_time', 'update_time'
        })
        simple_dict['user_name'] = cls.get_user_name(one.user_id)
        return AssistantSimpleInfo(**simple_dict)

    @classmethod
    async def get_assistant_info(cls, assistant_id: str, login_user: UserPayload,
                                 share_link: Union['ShareLink', None] = None) -> AssistantInfo:
        assistant = await AssistantDao.aget_one_assistant(assistant_id)
        if not assistant or assistant.is_delete:
            raise AssistantNotExistsError()
        # Check if you have permission to access the information
        if not await login_user.async_access_check(assistant.user_id, assistant.id, AccessType.ASSISTANT_READ):

            if (share_link is None
                    or share_link.meta_data is None
                    or share_link.meta_data.get("flowId") != assistant.id):
                raise UnAuthorizedError()

        tool_list = []
        flow_list = []
        knowledge_list = []

        links = await AssistantLinkDao.get_assistant_link(assistant_id)
        for one in links:
            if one.tool_id:
                tool_list.append(one.tool_id)
            elif one.knowledge_id:
                knowledge_list.append(one.knowledge_id)
            elif one.flow_id:
                flow_list.append(one.flow_id)
            else:
                logger.error(f'not expect link info: {one.model_dump()}')
        tool_list, flow_list, knowledge_list = cls.get_link_info(tool_list, flow_list,
                                                                 knowledge_list)
        assistant.logo = await cls.get_logo_share_link_async(assistant.logo)
        return AssistantInfo(**assistant.model_dump(),
                             tool_list=tool_list,
                             flow_list=flow_list,
                             knowledge_list=knowledge_list)

    @classmethod
    async def get_one_assistant(cls, assistant_id: str) -> Optional[Assistant]:
        assistant = await AssistantDao.aget_one_assistant(assistant_id)
        return assistant

    # Create Assistant
    @classmethod
    async def create_assistant(cls, request: Request, login_user: UserPayload, assistant: Assistant) \
            -> AssistantInfo:

        # Check if there are any duplicate names under
        if cls.judge_name_repeat(assistant.name, assistant.user_id):
            raise AssistantNameRepeatError()

        logger.info(f"assistant original prompt id: {assistant.id}, desc: {assistant.prompt}")

        # Automatically replenish default model configurations
        assistant_llm = await LLMService.get_assistant_llm()
        if assistant_llm.llm_list:
            for one in assistant_llm.llm_list:
                if one.default:
                    assistant.model_name = str(one.model_id)
                    break

        # Autogenerate Descriptions
        assistant, _, _ = await cls.get_auto_info(assistant, login_user)
        assistant = AssistantDao.create_assistant(assistant)

        # RecordTelemetryJournal
        await telemetry_service.log_event(user_id=login_user.user_id,
                                          event_type=BaseTelemetryTypeEnum.NEW_APPLICATION,
                                          trace_id=trace_id_var.get(),
                                          event_data=NewApplicationEventData(
                                              app_id=assistant.id,
                                              app_name=assistant.name,
                                              app_type=ApplicationTypeEnum.ASSISTANT
                                          ))

        cls.create_assistant_hook(request, assistant, login_user)
        return AssistantInfo(**assistant.model_dump(),
                             tool_list=[],
                             flow_list=[],
                             knowledge_list=[])

    @classmethod
    def create_assistant_hook(cls, request: Request, assistant: Assistant, user_payload: UserPayload) -> bool:
        """
        After successful creation of the assistanthook, perform some other business logic
        """
        # Query the user group the user belongs to under
        user_group = UserGroupDao.get_user_group(user_payload.user_id)
        if user_group:
            # Batch Insert Assistant Resources into Correlation Table
            batch_resource = []
            for one in user_group:
                batch_resource.append(GroupResource(
                    group_id=one.group_id,
                    third_id=assistant.id,
                    type=ResourceTypeEnum.ASSISTANT.value))
            GroupResourceDao.insert_group_batch(batch_resource)

        # Write Audit Log
        AuditLogService.create_build_assistant(user_payload, get_request_ip(request), assistant.id)

        # WritelogoCeacle
        cls.get_logo_share_link(assistant.logo)
        return True

    # Delete Assistant
    @classmethod
    def delete_assistant(cls, request: Request, login_user: UserPayload, assistant_id: str) -> bool:
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            raise AssistantNotExistsError()

        # Judgment Authorization
        if not login_user.access_check(assistant.user_id, assistant.id, AccessType.ASSISTANT_WRITE):
            raise UnAuthorizedError()

        AssistantDao.delete_assistant(assistant)
        telemetry_service.log_event_sync(user_id=login_user.user_id,
                                         event_type=BaseTelemetryTypeEnum.DELETE_APPLICATION,
                                         trace_id=trace_id_var.get())
        cls.delete_assistant_hook(request, login_user, assistant)
        return True

    @classmethod
    def delete_assistant_hook(cls, request: Request, login_user: UserPayload, assistant: Assistant) -> bool:
        """ Clean up associated assistant resources """
        logger.info(f"delete_assistant_hook id: {assistant.id}, user: {login_user.user_id}")
        # Write Audit Log
        AuditLogService.delete_build_assistant(login_user, get_request_ip(request), assistant.id)

        # Clean up associations with user groups
        GroupResourceDao.delete_group_resource_by_third_id(assistant.id, ResourceTypeEnum.ASSISTANT)

        # Update session information
        MessageSessionDao.update_session_info_by_flow(assistant.name, assistant.desc, assistant.logo,
                                                      assistant.id, FlowType.ASSISTANT.value)
        return True

    @classmethod
    async def auto_update_stream(cls, assistant_id: str, prompt: str, login_user: UserPayload):
        """ Regenerate Assistant Prompts and Tool Selection, Only call the model capability without modifying the database data """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        assistant.prompt = prompt

        # Inisialisasillm
        auto_agent = AssistantAgent(assistant, '', login_user.user_id)
        await auto_agent.init_auto_update_llm()

        # Streaming Generation Prompts
        final_prompt = ''
        async for one_prompt in auto_agent.optimize_assistant_prompt():
            if one_prompt.content in ('```', 'markdown'):
                continue
            yield str(StreamData(event='message', data={'type': 'prompt', 'message': one_prompt.content}))
            final_prompt += one_prompt.content
        assistant.prompt = final_prompt
        yield str(StreamData(event='message', data={'type': 'end', 'message': ""}))

        # Generate opening remarks and opening questions
        guide_info = auto_agent.generate_guide(assistant.prompt)
        yield str(StreamData(event='message', data={'type': 'guide_word', 'message': guide_info['opening_lines']}))
        yield str(StreamData(event='message', data={'type': 'end', 'message': ""}))
        yield str(StreamData(event='message', data={'type': 'guide_question', 'message': guide_info['questions']}))
        yield str(StreamData(event='message', data={'type': 'end', 'message': ""}))

        # Automatic selection of tools and skills
        tool_info = cls.get_auto_tool_info(assistant, auto_agent)
        tool_info = [one.model_dump() for one in tool_info]
        yield str(StreamData(event='message', data={'type': 'tool_list', 'message': tool_info}))
        yield str(StreamData(event='message', data={'type': 'end', 'message': ""}))

        flow_info = cls.get_auto_flow_info(assistant, auto_agent)
        flow_info = [one.model_dump() for one in flow_info]
        yield str(StreamData(event='message', data={'type': 'flow_list', 'message': flow_info}))

    @classmethod
    async def update_assistant(cls, request: Request, login_user: UserPayload, req: AssistantUpdateReq) \
            -> AssistantInfo:
        """ Update Assistant Information """
        assistant = AssistantDao.get_one_assistant(req.id)
        if not assistant:
            raise AssistantNotExistsError()

        cls.check_update_permission(assistant, login_user)

        # Update Assistant Data
        if req.name and req.name != assistant.name:
            # Check if there are any duplicate names under
            if cls.judge_name_repeat(req.name, assistant.user_id):
                raise AssistantNameRepeatError()
            assistant.name = req.name
        assistant.desc = req.desc
        assistant.logo = req.logo if req.logo else assistant.logo
        assistant.prompt = req.prompt
        assistant.guide_word = req.guide_word
        assistant.guide_question = req.guide_question
        assistant.model_name = req.model_name
        assistant.temperature = req.temperature
        assistant.update_time = datetime.now()
        assistant.max_token = req.max_token
        AssistantDao.update_assistant(assistant)
        telemetry_service.log_event_sync(user_id=login_user.user_id, event_type=BaseTelemetryTypeEnum.EDIT_APPLICATION,
                                         trace_id=trace_id_var.get())

        # Update assistant association information
        if req.tool_list is not None:
            AssistantLinkDao.update_assistant_tool(assistant.id, tool_list=req.tool_list)
        if req.flow_list is not None:
            AssistantLinkDao.update_assistant_flow(assistant.id, flow_list=req.flow_list)
        if req.knowledge_list is not None:
            # Using Configuredflow Perform skill replenishment
            AssistantLinkDao.update_assistant_knowledge(assistant.id,
                                                        knowledge_list=req.knowledge_list,
                                                        flow_id='')
        tool_list, flow_list, knowledge_list = cls.get_link_info(req.tool_list, req.flow_list,
                                                                 req.knowledge_list)
        cls.update_assistant_hook(request, login_user, assistant)
        return AssistantInfo(**assistant.model_dump(),
                             tool_list=tool_list,
                             flow_list=flow_list,
                             knowledge_list=knowledge_list)

    @classmethod
    def update_assistant_hook(cls, request: Request, login_user: UserPayload, assistant: Assistant) -> bool:
        """ Update Assistant's Hook """
        logger.info(f"delete_assistant_hook id: {assistant.id}, user: {login_user.user_id}")

        # Write Audit Log
        AuditLogService.update_build_assistant(login_user, get_request_ip(request), assistant.id)

        # Write cache
        cls.get_logo_share_link(assistant.logo)
        return True

    @classmethod
    async def update_status(cls, request: Request, login_user: UserPayload, assistant_id: str,
                            status: int) -> bool:
        """ Update Assistant Status """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            raise AssistantNotExistsError()
        # Determine permissions
        if not login_user.access_check(assistant.user_id, assistant.id, AccessType.ASSISTANT_WRITE):
            raise UnAuthorizedError()
        # Equal status without modification
        if assistant.status == status:
            return True

        # Try to initializeagent, go online if initialization is successful, otherwise not go online
        if status == AssistantStatus.ONLINE.value:
            tmp_agent = AssistantAgent(assistant, '', login_user.user_id)
            try:
                await tmp_agent.init_assistant()
            except Exception as e:
                logger.exception('online agent init failed')
                raise AssistantInitError(exception=e)
        assistant.status = status
        AssistantDao.update_assistant(assistant)
        telemetry_service.log_event_sync(user_id=login_user.user_id, event_type=BaseTelemetryTypeEnum.EDIT_APPLICATION,
                                         trace_id=trace_id_var.get())
        cls.update_assistant_hook(request, login_user, assistant)
        return True

    @classmethod
    def update_prompt(cls, assistant_id: str, prompt: str, user_payload: UserPayload) -> bool:
        """ Update assistant prompts """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            raise AssistantNotExistsError()

        cls.check_update_permission(assistant, user_payload)

        assistant.prompt = prompt
        AssistantDao.update_assistant(assistant)
        telemetry_service.log_event_sync(user_id=user_payload.user_id,
                                         event_type=BaseTelemetryTypeEnum.EDIT_APPLICATION,
                                         trace_id=trace_id_var.get())
        return True

    @classmethod
    def update_flow_list(cls, assistant_id: str, flow_list: List[str],
                         user_payload: UserPayload) -> bool:
        """  Update Assistant Skills List """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            raise AssistantNotExistsError()

        cls.check_update_permission(assistant, user_payload)

        AssistantLinkDao.update_assistant_flow(assistant_id, flow_list=flow_list)
        return True

    @classmethod
    def update_tool_list(cls, assistant_id: str, tool_list: List[int],
                         user_payload: UserPayload) -> bool:
        """  Update Assistant Tool List """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            raise AssistantNotExistsError()

        cls.check_update_permission(assistant, user_payload)

        AssistantLinkDao.update_assistant_tool(assistant_id, tool_list=tool_list)
        return True

    @classmethod
    def check_update_permission(cls, assistant: Assistant, user_payload: UserPayload) -> Any:
        # Determine permissions
        if not user_payload.access_check(assistant.user_id, assistant.id, AccessType.ASSISTANT_WRITE):
            raise UnAuthorizedError()

        # Changes are not allowed when online
        if assistant.status == AssistantStatus.ONLINE.value:
            raise AssistantNotEditError()
        return None

    @classmethod
    def get_link_info(cls,
                      tool_list: List[int],
                      flow_list: List[str],
                      knowledge_list: List[int] = None):
        tool_list = GptsToolsDao.get_list_by_ids(tool_list) if tool_list else []
        flow_list = FlowDao.get_flow_by_ids(flow_list) if flow_list else []
        knowledge_list = KnowledgeDao.get_list_by_ids(knowledge_list) if knowledge_list else []
        return tool_list, flow_list, knowledge_list

    @classmethod
    def get_user_name(cls, user_id: int):
        if not user_id:
            return 'system'
        user = cls.UserCache.get(user_id)
        if user:
            return user.user_name
        user = UserDao.get_user(user_id)
        if not user:
            return f'{user_id}'
        cls.UserCache.set(user_id, user)
        return user.user_name

    @classmethod
    def judge_name_repeat(cls, name: str, user_id: int) -> bool:
        """ Determine if the assistant name is a duplicate """
        assistant = AssistantDao.get_assistant_by_name_user_id(name, user_id)
        if assistant:
            return True
        return False

    @classmethod
    async def get_auto_info(cls, assistant: Assistant, login_user: UserPayload) -> (Assistant, List[int], List[int]):
        """
        Auto Generate Assistant'sprompt, Automatically select tools and skills
        return: Assistant Information, ToolsIDList, SkillsIDVertical
        """
        # Inisialisasiagent
        auto_agent = AssistantAgent(assistant, '', login_user.user_id)
        await auto_agent.init_auto_update_llm()

        # Autogenerate Descriptions
        assistant.desc = auto_agent.generate_description(assistant.prompt)

        return assistant, [], []

    @classmethod
    def get_auto_tool_info(cls, assistant: Assistant, auto_agent: AssistantAgent) -> List[GptsTools]:
        # Pagination Auto-Select Tool
        res = []
        page = 1
        page_num = 50
        while True:
            all_tool = GptsToolsDao.get_list_by_user(assistant.user_id, page, page_num)
            if len(all_tool) == 0:
                break
            logger.info(f"auto select tools: page: {page}, number: {len(all_tool)}")
            tool_list = []
            all_tool_dict = {}
            for one in all_tool:
                all_tool_dict[one.name] = one
                tool_list.append({
                    'name': one.name,
                    'description': one.desc if one.desc else '',
                })
            tool_info = []
            tool_list = auto_agent.choose_tools(tool_list, assistant.prompt)
            for one in tool_list:
                if all_tool_dict.get(one):
                    tool_info.append(all_tool_dict[one])
            res += tool_info
            page += 1
        return res

    @classmethod
    def get_auto_flow_info(cls, assistant: Assistant, auto_agent: AssistantAgent) -> List[Flow]:
        # Automatically select skills, Before picking50skills to make automatic selections
        all_flow = FlowDao.get_user_access_online_flows(assistant.user_id, 1, 50)
        flow_dict = {}
        flow_list = []
        for one in all_flow:
            flow_dict[one.name] = one
            flow_list.append({
                'name': one.name,
                'description': one.description if one.description else '',
            })

        flow_list = auto_agent.choose_tools(flow_list, assistant.prompt)
        flow_info = []
        for one in flow_list:
            if flow_dict.get(one):
                flow_info.append(flow_dict[one])
        return flow_info
