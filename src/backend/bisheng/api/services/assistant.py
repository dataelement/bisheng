from typing import Any, List
from uuid import UUID

from bisheng.api.errcode.assistant import AssistantNotExistsError
from bisheng.api.services.assistant_base import AssistantUtils
from bisheng.api.v1.schemas import (AssistantInfo, AssistantSimpleInfo, AssistantUpdateReq,
                                    UnifiedResponseModel, resp_200)
from bisheng.cache import InMemoryCache
from bisheng.database.models.assistant import Assistant, AssistantDao, AssistantLinkDao
from bisheng.database.models.gpts_tools import GptsTools, GptsToolsDao
from bisheng.database.models.role_access import AccessType, RoleAcessDao
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_role import UserRoleDao
from loguru import logger


class AssistantService(AssistantUtils):
    UserCache: InMemoryCache = InMemoryCache()

    @classmethod
    def get_assistant(cls,
                      user_id: int,
                      name: str = None,
                      page: int = 1,
                      limit: int = 20) -> UnifiedResponseModel[List[AssistantSimpleInfo]]:
        """
        获取助手列表
        """
        data = []
        # 权限管理可见的助手信息
        assistant_ids_extra = []
        user_role = UserRoleDao.get_user_roles(user_id)
        if user_role:
            role_ids = [role.id for role in user_role]
            role_access = RoleAcessDao.get_role_acess(role_ids, AccessType.ASSITANT_READ)
            if role_access:
                assistant_ids_extra = [access.id for access in role_access]

        res, total = AssistantDao.get_assistants(user_id, name, assistant_ids_extra, page, limit)

        for one in res:
            simple_dict = one.model_dump(
                include={'id', 'name', 'desc', 'logo', 'user_id', 'create_time', 'update_time'})
            simple_dict['user_name'] = cls.get_user_name(one.user_id)
            data.append(AssistantSimpleInfo(**simple_dict))
        return resp_200(data={'data': data, 'total': total})

    @classmethod
    def get_assistant_info(cls, assistant_id: UUID, user_id: str):
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        tool_list = []
        flow_list = []
        knowledge_list = []

        links = AssistantLinkDao.get_assistant_link(assistant_id)
        for one in links:
            if one.tool_id:
                tool_list.append(one.tool_id)
            elif one.flow_id:
                flow_list.append(one.flow_id)
            elif one.knowledge_id:
                knowledge_list.append(one.knowledge_id)
            else:
                logger.error(f'not expect link info: {one.dict()}')

        return resp_200(data=AssistantInfo(**assistant.dict(),
                                           tool_list=tool_list,
                                           flow_list=flow_list,
                                           knowledge_list=knowledge_list))

    # 创建助手
    @classmethod
    def create_assistant(cls, assistant: Assistant) -> UnifiedResponseModel[AssistantInfo]:

        # 通过算法接口自动选择工具和技能
        assistant, tool_list, flow_list = cls.get_auto_info(assistant)

        # 保存数据到数据库
        assistant = AssistantDao.create_assistant(assistant)
        # 保存大模型自动选择的工具和技能
        AssistantLinkDao.insert_batch(assistant.id, tool_list=tool_list, flow_list=flow_list)

        return resp_200(
            data=AssistantInfo(**assistant.dict(), tool_list=tool_list, flow_list=flow_list))

    @classmethod
    def auto_update(cls, assistant_id: UUID, prompt: str) -> UnifiedResponseModel[AssistantInfo]:
        """ 重新生成助手的提示词和工具选择, 只调用模型能力不修改数据库数据 """
        # todo zgq: 改为流式返回
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        assistant.prompt = prompt
        assistant, tool_list, flow_list = cls.get_auto_info(assistant)
        return resp_200(
            data=AssistantInfo(**assistant.dict(), tool_list=tool_list, flow_list=flow_list))

    @classmethod
    def update_assistant(cls, req: AssistantUpdateReq) -> UnifiedResponseModel[AssistantInfo]:
        """ 更新助手信息 """
        assistant = AssistantDao.get_one_assistant(req.id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        # 更新助手数据
        if req.name:
            assistant.name = req.name
        if req.desc:
            assistant.desc = req.desc
        if req.logo:
            assistant.logo = req.logo
        if req.prompt:
            assistant.prompt = req.prompt
        if req.guide_word:
            assistant.guide_word = req.guide_word
        if req.guide_question:
            assistant.guide_question = req.guide_question
        if req.model_name:
            assistant.model_name = req.model_name
        if req.temperature:
            assistant.temperature = req.temperature
        AssistantDao.update_assistant(assistant)

        # 更新助手关联信息
        if req.tool_list is not None and req.flow_list is not None and req.knowledge_list is not None:
            AssistantLinkDao.update_assistant_link(assistant.id,
                                                   tool_list=req.tool_list,
                                                   flow_list=req.flow_list,
                                                   knowledge_list=req.knowledge_list)
        elif req.tool_list is not None:
            AssistantLinkDao.update_assistant_tool(assistant.id, tool_list=req.tool_list)
        elif req.flow_list is not None:
            AssistantLinkDao.update_assistant_flow(assistant.id, flow_list=req.flow_list)
        elif req.knowledge_list is not None:
            AssistantLinkDao.update_assistant_knowledge(assistant.id,
                                                        knowledge_list=req.knowledge_list)
        return resp_200(data=AssistantInfo(**assistant.dict(),
                                           tool_list=req.tool_list,
                                           flow_list=req.flow_list,
                                           knowledge_list=req.knowledge_list))

    @classmethod
    def update_prompt(cls, assistant_id: UUID, prompt: str) -> UnifiedResponseModel:
        """ 更新助手的提示词 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        assistant.prompt = prompt
        AssistantDao.update_assistant(assistant)
        return resp_200()

    @classmethod
    def update_flow_list(cls, assistant_id: UUID, flow_list: List[str]) -> UnifiedResponseModel:
        """  更新助手的技能列表 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        AssistantLinkDao.update_assistant_flow(assistant_id, flow_list=flow_list)
        return resp_200()

    @classmethod
    def get_gpts_tools(cls, user: Any) -> List[GptsTools]:
        """ 获取用户可见的工具列表 """
        user_id = user.get('user_id')
        return GptsToolsDao.get_list_by_user(user_id)

    @classmethod
    def get_models(cls) -> UnifiedResponseModel:
        llm_list = cls.get_gpts_conf('llms')
        res = []
        for one in llm_list:
            res.append({'id': one['model_name'], 'model_name': one['model_name']})
        return resp_200(data=res)

    @classmethod
    def update_tool_list(cls, assistant_id: UUID, tool_list: List[int]) -> UnifiedResponseModel:
        """  更新助手的工具列表 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        AssistantLinkDao.update_assistant_tool(assistant_id, tool_list=tool_list)
        return resp_200()

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
    def get_auto_info(cls, assistant: Assistant) -> (Assistant, List[int], List[int]):
        """
        自动生成助手的prompt，自动选择工具和技能
        return：助手信息，工具ID列表，技能ID列表
        """
        # todo zgq: 和算法联调自动生成优化后的prompt、描述、工具、技能、开场白
        # 根据助手 选择大模型配置
        llm_conf = cls.get_llm_conf(assistant.model_name)

        assistant.system_prompt = ''
        assistant.prompt = assistant.prompt
        assistant.model_name = llm_conf['model_name']
        assistant.temperature = llm_conf['temperature']

        return assistant, [], []
