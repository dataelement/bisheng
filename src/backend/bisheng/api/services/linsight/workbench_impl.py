import uuid
from typing import Dict

from langchain_core.prompts import ChatPromptTemplate

from bisheng.api.services.llm import LLMService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schema.linsight_schema import LinsightQuestionSubmitSchema
from bisheng.core.app_context import app_ctx
from bisheng.database.models import LinsightSessionVersion
from bisheng.database.models.flow import FlowType
from bisheng.database.models.linsight_session_version import LinsightSessionVersionDao
from bisheng.database.models.session import MessageSessionDao, MessageSession
from bisheng.interface.llms.custom import BishengLLM


class LinsightWorkbenchImpl(object):

    # 提交用户问题
    @classmethod
    async def submit_user_question(cls, submit_obj: LinsightQuestionSubmitSchema, login_user: UserPayload):
        """
        Linsight工作台提交用户问题
        :param submit_obj:
        :param login_user:
        :return:
        """
        # 新增会话
        chat_id = uuid.uuid4().hex  # 使用UUID生成唯一的会话ID
        message_session_model = MessageSession(
            chat_id=chat_id,
            flow_id='',
            flow_name='New Chat',
            flow_type=FlowType.LINSIGHT.value,
            user_id=login_user.user_id
        )
        await MessageSessionDao.async_insert_one(message_session_model)

        # 灵思会话版本
        linsight_session_version_model = LinsightSessionVersion(
            session_id=chat_id,
            user_id=login_user.user_id,
            question=submit_obj.question,
            tools=submit_obj.tools,
            knowledge_enabled=submit_obj.knowledge_enabled,
            files=submit_obj.files
        )
        linsight_session_version_model = await LinsightSessionVersionDao.insert_one(linsight_session_version_model)

        return message_session_model, linsight_session_version_model

    @classmethod
    async def task_title_generate(cls, question: str, chat_id: str, login_user: UserPayload) -> Dict:
        """
        生成任务标题
        :param question:
        :param chat_id: 会话ID
        :param login_user: 登录用户信息
        :return: 生成的任务标题
        """
        try:
            # 获取生成摘要模型
            linsight_conf = await LLMService.get_linsight_llm()
            if not linsight_conf:
                raise ValueError("未配置灵思生成摘要模型，请从工作台配置中设置")

            summary_model = linsight_conf.task_summary_model
            if not summary_model:
                raise ValueError("未配置灵思生成摘要模型，请从工作台配置中设置")

            # 创建 BishengLLM
            llm = BishengLLM(model_id=summary_model.id)

            # prompt实例化
            prompt_service = await app_ctx.get_prompt_loader()
            prompt_obj = prompt_service.render_prompt(namespace="gen_title", prompt_name="linsight",
                                                      USER_GOAL=question)
            prompt = ChatPromptTemplate(
                messages=[
                    ("system", prompt_obj.prompt.system),
                    ("user", prompt_obj.prompt.user),
                ]
            ).format_prompt()

            # 生成任务标题
            task_title = await llm.ainvoke(prompt)

            if not task_title.content:
                raise ValueError("生成任务标题失败，请检查模型配置或输入内容")

        except Exception as e:
            return {
                "task_title": None,
                "chat_id": chat_id,
                "error_message": str(e)
            }

        # 更新会话标题
        session = await MessageSessionDao.async_get_one(chat_id)
        session.flow_name = task_title.content
        await MessageSessionDao.async_insert_one(session)

        return {
            "task_title": task_title.content,
            "chat_id": chat_id,
            "error_message": None
        }
