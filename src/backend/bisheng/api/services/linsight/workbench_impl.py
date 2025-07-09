import asyncio
import uuid
from io import BytesIO
from typing import Dict, List

from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng_langchain.vectorstores import Milvus, ElasticKeywordsSearch
from fastapi import UploadFile
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import run_in_executor
from langchain_core.tools import BaseTool

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.services.knowledge_imp import read_chunk_text, decide_vectorstores
from bisheng.api.services.linsight.sop_manage import SOPManageService
from bisheng.api.services.llm import LLMService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schema.linsight_schema import LinsightQuestionSubmitSchema
from bisheng.cache.redis import redis_client
from bisheng.cache.utils import save_uploaded_file, file_download
from bisheng.core.app_context import app_ctx
from bisheng.database.models import LinsightSessionVersion
from bisheng.database.models.flow import FlowType
from bisheng.database.models.linsight_execute_task import LinsightExecuteTaskDao, LinsightExecuteTask
from bisheng.database.models.linsight_session_version import LinsightSessionVersionDao
from bisheng.database.models.session import MessageSessionDao, MessageSession
from bisheng.interface.llms.custom import BishengLLM
from bisheng.utils.embedding import decide_embeddings
from bisheng_langchain.linsight.agent import LinsightAgent


class LinsightWorkbenchImpl(object):
    collection_name = "col_linsight_file_"
    file_info_redis_key = "linsight_file:"

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

        files = submit_obj.files

        if files:
            file_ids = [file.file_id for file in files]

            files = await redis_client.amget([f"{cls.file_info_redis_key}{file_id}" for file_id in file_ids])

        # 灵思会话版本
        linsight_session_version_model = LinsightSessionVersion(
            session_id=chat_id,
            user_id=login_user.user_id,
            question=submit_obj.question,
            tools=submit_obj.tools,
            org_knowledge_enabled=submit_obj.org_knowledge_enabled,
            personal_knowledge_enabled=submit_obj.personal_knowledge_enabled,
            files=files
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
            workbench_conf = await LLMService.get_workbench_llm()
            if not workbench_conf:
                raise ValueError("未配置灵思生成摘要模型，请从工作台配置中设置")

            summary_model = workbench_conf.task_model
            if not summary_model:
                raise ValueError("未配置灵思生成摘要模型，请从工作台配置中设置")

            # 创建 BishengLLM
            llm = BishengLLM(model_id=summary_model.id)

            # prompt实例化
            prompt_service = app_ctx.get_prompt_loader()
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

    @classmethod
    async def get_linsight_session_version_list(cls, session_id: str):
        """
        获取灵思会话版本列表
        :param session_id:
        :return:
        """

        linsight_session_version_models = await LinsightSessionVersionDao.get_session_versions_by_session_id(session_id)
        return linsight_session_version_models

    @classmethod
    async def modify_sop(cls, linsight_session_version_id: str, sop_content: str):
        """
        修改灵思会话版本的SOP内容
        :param linsight_session_version_id:
        :param sop_content:
        :return:
        """

        try:
            await LinsightSessionVersionDao.modify_sop_content(
                linsight_session_version_id=linsight_session_version_id,
                sop_content=sop_content
            )
            return {
                "success": True,
                "message": "modify sop content successfully"
            }
        except Exception as e:
            return {
                "success": False,
                "message": str(e)
            }

    @classmethod
    async def generate_sop(cls, linsight_session_version_id: str, feedback_content: str = None,
                           reexecute: bool = False,
                           login_user: UserPayload = None):
        """
        灵思生成SOP内容
        :param linsight_session_version_id:
        :param feedback_content:
        :param reexecute:
        :param login_user:
        :return:
        """

        # 获取生成模型
        workbench_conf = await LLMService.get_workbench_llm()
        if not workbench_conf and not workbench_conf.task_model:
            yield {
                "event": "error",
                "data": "未配置任务执行模型"
            }

        # 创建 BishengLLM
        llm = BishengLLM(model_id=workbench_conf.task_model.id)

        linsight_session_version_model = await LinsightSessionVersionDao.get_by_id(linsight_session_version_id)
        if not linsight_session_version_model:
            yield {
                "event": "error",
                "data": "灵思会话版本不存在"
            }

        tools: List[BaseTool] = []
        # TODO: 获取工具合集
        if linsight_session_version_model.tools:
            tool_ids = []
            for tool in linsight_session_version_model.tools:
                if tool.get("children"):
                    for child in tool["children"]:
                        tool_ids.append(child.get("id"))
            tools.extend(await AssistantAgent.init_tools_by_tool_ids(tool_ids, llm=llm))

        history_summary = []

        # 如果需要重新执行任务，则查询所有执行任务信息
        if reexecute:
            # 查询所有执行任务信息
            execute_task_models = await cls.get_execute_task_detail(linsight_session_version_id)

            for execute_task_model in execute_task_models:
                if execute_task_model.result:
                    history_summary.append(execute_task_model.result)

        linsight_agent = LinsightAgent(file_dir="",
                                       query=linsight_session_version_model.question,
                                       llm=llm,
                                       tools=tools)
        content = ""

        # 没有反馈内容
        if feedback_content is None:

            # 检索SOP模板
            sop_template = await SOPManageService.search_sop(query=linsight_session_version_model.question)
            sop_template = sop_template[0].page_content if sop_template else ""

            async for res in linsight_agent.generate_sop(sop=sop_template):
                content += res.content
                yield {
                    "event": "generate_sop_content",
                    "data": res.model_dump_json()
                }

        else:

            sop_template = linsight_session_version_model.sop if linsight_session_version_model.sop else ""

            async for res in linsight_agent.feedback_sop(sop=sop_template,
                                                         feedback=feedback_content,
                                                         history_summary=history_summary if history_summary else None):
                content += res.content
                yield {
                    "event": "generate_sop_content",
                    "data": res.model_dump_json()
                }

        # 更新SOP内容
        await LinsightSessionVersionDao.modify_sop_content(
            linsight_session_version_id=linsight_session_version_id,
            sop_content=content
        )

    @classmethod
    async def get_execute_task_detail(cls, session_version_id: str,
                                      login_user: UserPayload = None) -> List[LinsightExecuteTask]:
        """
        获取执行任务详情
        :param session_version_id: 灵思会话版本ID
        :param login_user: 登录用户信息
        :return: 执行任务详情
        """
        execute_task_models = await LinsightExecuteTaskDao.get_by_session_version_id(session_version_id)

        if not execute_task_models:
            return []

        return execute_task_models

    @classmethod
    async def upload_file(cls, file: UploadFile):
        """
        灵思工作台上传文件
        :param file:
        :return:
        """

        # 原始文件名
        original_filename = file.filename
        file_id = uuid.uuid4().hex
        # 生成唯一的文件名
        unique_filename = f"{file_id}.{original_filename.split('.')[-1]}"

        # 保存文件
        file_path = save_uploaded_file(file.file, 'bisheng', unique_filename)

        # 缓存文件信息
        file_info = {
            "file_id": file_id,
            "filename": unique_filename,
            "original_filename": original_filename,
            "file_path": file_path,
            "parsing_status": "pending",
        }

        return file_info

    @classmethod
    async def parse_file(cls, upload_result):

        """
        解析上传的文件
        :param upload_result: 上传结果
        :return: 解析结果
        """
        # 获取文件信息
        file_id = upload_result.get("file_id")
        filename = upload_result.get("filename")
        original_filename = upload_result.get("original_filename")
        file_path = upload_result.get("file_path")

        # 写入向量库
        # 获取当前全局配置的embedding模型
        workbench_conf = await LLMService.get_workbench_llm()

        collection_name = f"{cls.collection_name}{workbench_conf.embedding_model.id}"

        # 包装同步处理函数
        def wrap_sunc_func(file_id, file_path, original_filename, collection_name, workbench_conf):
            filepath, _ = file_download(file_path)
            texts, _, parse_type, _ = read_chunk_text(
                input_file=filepath,
                file_name=original_filename,
                separator=['\n\n', '\n'],
                separator_rule=['after', 'after'],
                chunk_size=1000,
                chunk_overlap=100
            )

            markdown_str = ""
            for text in texts:
                markdown_str += f"{text}\n"

            # 写成markdown文件bytes
            markdown_file_bytes = BytesIO()
            markdown_file_bytes.write(markdown_str.encode('utf-8'))
            markdown_file_bytes.seek(0)

            # 生成唯一的文件名
            markdown_filename = f"{uuid.uuid4().hex}.md"
            # 保存markdown文件
            markdown_file_path = save_uploaded_file(markdown_file_bytes, 'bisheng', markdown_filename)

            emb_model_id = workbench_conf.embedding_model.id
            embeddings = decide_embeddings(emb_model_id)

            vector_client: Milvus = decide_vectorstores(
                collection_name, "Milvus", embeddings
            )

            es_client: ElasticKeywordsSearch = decide_vectorstores(
                collection_name, "ElasticKeywordsSearch", FakeEmbedding()
            )
            metadatas = [{"file_id": file_id} for _ in texts]
            vector_client.add_texts(texts, metadatas=metadatas)
            es_client.add_texts(texts, metadatas=metadatas)

            # 缓存解析结果
            parse_result = {
                "file_id": file_id,
                "original_filename": original_filename,
                "file_path": file_path,
                "parsing_status": "completed",
                "parse_type": parse_type,
                "markdown_file_path": markdown_file_path,
                "embedding_model_id": emb_model_id,
                "collection_name": collection_name
            }

            return parse_result

        parse_result = await run_in_executor(None, wrap_sunc_func, file_id, file_path, original_filename,
                                             collection_name,
                                             workbench_conf)

        parse_result["filename"] = filename

        key = f"{cls.file_info_redis_key}{file_id}"
        # 将文件信息存储到缓存中
        await redis_client.aset(
            key=key,
            value=parse_result,
            expiration=60 * 60 * 24  # 设置过期时间为24小时
        )

        return parse_result
