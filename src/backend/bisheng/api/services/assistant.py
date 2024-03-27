from typing import List

from bisheng.api.errcode.assistant import AssistantNotExistsError
from bisheng.api.v1.schemas import AssistantInfo, AssistantUpdateReq, UnifiedResponseModel, resp_200
from bisheng.database.models.assistant import Assistant, AssistantDao, AssistantLinkDao
from bisheng.settings import settings


class AssistantService:

    # 创建助手
    @classmethod
    def create_assistant(cls, assistant: Assistant) -> UnifiedResponseModel[AssistantInfo]:

        # 通过算法接口自动选择工具和技能
        assistant, tool_list, flow_list = cls.get_auto_info(assistant)

        # 保存数据到数据库
        assistant = AssistantDao.create_assistant(assistant)
        # 保存大模型自动选择的工具和技能
        AssistantLinkDao.insert_batch(assistant.id, tool_list=tool_list, flow_list=flow_list)

        return resp_200(data=AssistantInfo(**assistant.dict(),
                                           tool_list=tool_list,
                                           flow_list=flow_list))

    @classmethod
    def auto_update(cls, assistant_id: int, prompt: str) -> UnifiedResponseModel[AssistantInfo]:
        """ 重新生成助手的提示词和工具选择, 只调用模型能力不修改数据库数据 """
        # todo zgq: 改为流失返回
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        assistant.prompt = prompt
        assistant, tool_list, flow_list = cls.get_auto_info(assistant)
        return resp_200(data=AssistantInfo(**assistant.dict(),
                                           tool_list=tool_list,
                                           flow_list=flow_list))

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
            AssistantLinkDao.update_assistant_knowledge(assistant.id, knowledge_list=req.knowledge_list)
        return resp_200(data=AssistantInfo(**assistant.dict(),
                                           tool_list=req.tool_list,
                                           flow_list=req.flow_list,
                                           knowledge_list=req.knowledge_list))

    @classmethod
    def update_prompt(cls, assistant_id: int, prompt: str) -> UnifiedResponseModel:
        """ 更新助手的提示词 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        assistant.prompt = prompt
        AssistantDao.update_assistant(assistant)
        return resp_200()

    @classmethod
    def update_flow_list(cls, assistant_id: int, flow_list: List[str]) -> UnifiedResponseModel:
        """  更新助手的技能列表 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        AssistantLinkDao.update_assistant_flow(assistant_id, flow_list=flow_list)
        return resp_200()

    @classmethod
    def update_tool_list(cls, assistant_id: int, tool_list: List[int]) -> UnifiedResponseModel:
        """  更新助手的工具列表 """
        assistant = AssistantDao.get_one_assistant(assistant_id)
        if not assistant:
            return AssistantNotExistsError.return_resp()
        AssistantLinkDao.update_assistant_tool(assistant_id, tool_list=tool_list)
        return resp_200()

    @classmethod
    def get_gpts_conf(cls, key=None):
        gpts_conf = settings.get_from_db('gpts_conf')
        if key:
            return gpts_conf.get(key)
        return gpts_conf

    @classmethod
    def get_llm_conf(cls, llm_name: str) -> dict:
        llm_list = cls.get_gpts_conf('llms')
        for one in llm_list:
            if one['model_name'] == llm_name:
                return one.copy()
        return llm_list[0].copy()

    @classmethod
    def get_auto_info(cls, assistant: Assistant) -> (Assistant, List[int], List[int]):
        """
        自动生成助手的prompt，自动选择工具和技能
        return：助手信息，工具ID列表，技能ID列表
        """
        # todo zgq: 和算法联调自动生成prompt和工具列表
        # 根据助手 选择大模型配置
        llm_conf = cls.get_llm_conf(assistant.model_name)

        assistant.system_prompt = '临时生成的默认系统prompt'
        assistant.prompt = '用户可见的临时prompt'
        assistant.model_name = llm_conf['name']
        assistant.temperature = llm_conf['temperature']

        return assistant, [], []
