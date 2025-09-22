import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from io import BytesIO
from typing import Dict, List, Optional, AsyncGenerator, Tuple, Any
from urllib.parse import unquote

from e2b.sandbox.filesystem.filesystem import WriteEntry
from fastapi import UploadFile
from langchain_core.tools import BaseTool
from loguru import logger

from bisheng.api.errcode import BaseErrorCode
from bisheng.api.errcode.http_error import UnAuthorizedError
from bisheng.api.errcode.linsight import LinsightToolInitError, LinsightBishengLLMError, LinsightGenerateSopError
from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.services.knowledge_imp import read_chunk_text, decide_vectorstores
from bisheng.api.services.linsight.sop_manage import SOPManageService
from bisheng.api.services.llm import LLMService
from bisheng.api.services.tool import ToolServices
from bisheng.api.services.user_service import UserPayload
from bisheng.api.services.workstation import WorkStationService
from bisheng.api.v1.schema.linsight_schema import LinsightQuestionSubmitSchema, BatchDownloadFilesSchema, \
    SubmitFileSchema
from bisheng.cache.redis import redis_client
from bisheng.cache.utils import save_file_to_folder, CACHE_DIR
from bisheng.core.app_context import app_ctx
from bisheng.database.models import LinsightSessionVersion
from bisheng.database.models.flow import FlowType
from bisheng.database.models.gpts_tools import GptsToolsDao
from bisheng.database.models.knowledge import KnowledgeRead, KnowledgeTypeEnum
from bisheng.database.models.linsight_execute_task import LinsightExecuteTaskDao
from bisheng.database.models.linsight_session_version import LinsightSessionVersionDao, SessionVersionStatusEnum
from bisheng.database.models.linsight_sop import LinsightSOPRecord
from bisheng.database.models.session import MessageSessionDao, MessageSession
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.interface.llms.custom import BishengLLM
from bisheng.settings import settings
from bisheng.utils import util
from bisheng.utils.embedding import decide_embeddings
from bisheng.utils.minio_client import minio_client
from bisheng.utils.util import calculate_md5
from bisheng_langchain.linsight.const import ExecConfig


@dataclass
class TaskNode:
    """任务节点，用于构建任务树"""
    task: Any  # LinsightExecuteTask 对象
    children: List['TaskNode'] = None

    def __post_init__(self):
        if self.children is None:
            self.children = []

    def to_dict(self) -> Dict:
        """将任务节点转换为字典格式"""
        task_dict = self.task.model_dump()
        task_dict['children'] = [child.to_dict() for child in self.children]
        return task_dict


class LinsightWorkbenchImpl:
    """Linsight工作台实现类"""

    # 类常量
    COLLECTION_NAME_PREFIX = "col_linsight_file_"
    FILE_INFO_REDIS_KEY_PREFIX = "linsight_file:"
    CACHE_EXPIRATION_HOURS = 24

    class LinsightError(Exception):
        """Linsight相关错误"""
        pass

    class SearchSOPError(Exception):
        """SOP检索错误"""

        def __init__(self, error_class: BaseErrorCode):
            super().__init__(error_class.Msg)
            self.error_class = error_class

    class ToolsInitializationError(Exception):
        """工具初始化错误"""

    class BishengLLMError(Exception):
        """Bisheng LLM相关错误"""

    @classmethod
    async def _get_llm(cls) -> (BishengLLM, Any):
        # 获取并验证工作台配置
        workbench_conf = await cls._get_workbench_config()

        # 创建LLM实例
        linsight_conf = settings.get_linsight_conf()
        llm = BishengLLM(model_id=workbench_conf.task_model.id, temperature=linsight_conf.default_temperature)
        return llm, workbench_conf

    @classmethod
    async def submit_user_question(cls, submit_obj: LinsightQuestionSubmitSchema,
                                   login_user: UserPayload) -> tuple[MessageSession, LinsightSessionVersion]:
        """
        提交用户问题并创建会话

        Args:
            submit_obj: 提交的问题对象
            login_user: 登录用户信息

        Returns:
            tuple: (消息会话模型, 灵思会话版本模型)

        Raises:
            LinsightError: 当创建会话失败时
        """
        try:
            # 生成唯一会话ID
            chat_id = uuid.uuid4().hex

            # 创建消息会话
            message_session = MessageSession(
                chat_id=chat_id,
                flow_id='',
                flow_name='新对话',
                flow_type=FlowType.LINSIGHT.value,
                user_id=login_user.user_id
            )
            await MessageSessionDao.async_insert_one(message_session)

            # 处理文件（如果存在）
            processed_files = await cls._process_submitted_files(submit_obj.files, chat_id)

            # 创建灵思会话版本
            linsight_session_version = LinsightSessionVersion(
                session_id=chat_id,
                user_id=login_user.user_id,
                question=submit_obj.question,
                tools=submit_obj.tools,
                org_knowledge_enabled=submit_obj.org_knowledge_enabled,
                personal_knowledge_enabled=submit_obj.personal_knowledge_enabled,
                files=processed_files
            )
            linsight_session_version = await LinsightSessionVersionDao.insert_one(linsight_session_version)

            return message_session, linsight_session_version

        except Exception as e:
            logger.error(f"提交用户问题失败: {str(e)}")
            raise cls.LinsightError(f"提交用户问题失败: {str(e)}")

    @classmethod
    async def _process_submitted_files(cls, files: Optional[List[SubmitFileSchema]], chat_id: str) -> Optional[List]:
        """
        处理提交的文件

        Args:
            files: 文件列表
            chat_id: 会话ID

        Returns:
            处理后的文件列表
        """
        if not files:
            return None

        file_ids = []

        for file in files:
            if file.parsing_status != "completed":
                raise cls.LinsightError(f"文件 {file.file_name} 解析状态不正确: {file.parsing_status}")
            file_ids.append(file.file_id)

        redis_keys = [f"{cls.FILE_INFO_REDIS_KEY_PREFIX}{file_id}" for file_id in file_ids]

        processed_files = await redis_client.amget(redis_keys)

        for file_info in processed_files:
            if file_info:
                await cls._copy_file_to_session_storage(file_info, chat_id)

        return processed_files

    @classmethod
    async def _copy_file_to_session_storage(cls, file_info: Dict, chat_id: str) -> None:
        """
        复制文件到会话存储

        Args:
            file_info: 文件信息
            chat_id: 会话ID
        """
        source_object_name = file_info.get("markdown_file_path")
        if source_object_name:
            original_filename = file_info.get("original_filename")
            markdown_filename = f"{original_filename.rsplit('.', 1)[0]}.md"
            new_object_name = f"linsight/{chat_id}/{source_object_name}"
            minio_client.copy_object(
                source_object_name=source_object_name,
                target_object_name=new_object_name,
                bucket_name=minio_client.tmp_bucket,
                target_bucket_name=minio_client.bucket
            )
            file_info["markdown_file_path"] = new_object_name
            file_info["markdown_filename"] = markdown_filename

    @classmethod
    async def task_title_generate(cls, question: str, chat_id: str,
                                  login_user: UserPayload) -> Dict:
        """
        生成任务标题

        Args:
            question: 用户问题
            chat_id: 会话ID
            login_user: 登录用户信息

        Returns:
            包含任务标题的字典
        """
        try:
            llm, _ = await cls._get_llm()

            # 生成prompt
            prompt = await cls._generate_title_prompt(question)

            # 生成任务标题
            task_title = await llm.ainvoke(prompt)

            if not task_title.content:
                raise ValueError("生成任务标题失败，请检查模型配置或输入内容")

            # 更新会话标题
            await cls._update_session_title(chat_id, task_title.content)

            return {
                "task_title": task_title.content,
                "chat_id": chat_id,
                "error_message": None
            }

        except Exception as e:
            logger.error(f"生成任务标题失败: {str(e)}")
            return {
                "task_title": "新对话",
                "chat_id": chat_id,
                "error_message": str(e)
            }

    @classmethod
    async def _get_workbench_config(cls):
        """获取并验证工作台配置"""
        workbench_conf = await LLMService.get_workbench_llm()
        if not workbench_conf or not workbench_conf.task_model:
            raise cls.BishengLLMError("任务已终止，请联系管理员检查灵思任务执行模型状态")
        return workbench_conf

    @classmethod
    async def _generate_title_prompt(cls, question: str) -> List[Tuple[str, str]]:
        """生成标题生成的prompt"""
        prompt_service = app_ctx.get_prompt_loader()
        prompt_obj = prompt_service.render_prompt(
            namespace="gen_title",
            prompt_name="linsight",
            USER_GOAL=question
        )
        return [
            ("system", prompt_obj.prompt.system),
            ("user", prompt_obj.prompt.user)
        ]

    @classmethod
    async def _update_session_title(cls, chat_id: str, title: str) -> None:
        """更新会话标题"""
        session = await MessageSessionDao.async_get_one(chat_id)
        if session:
            session.flow_name = title
            await MessageSessionDao.async_insert_one(session)

    @classmethod
    async def get_linsight_session_version_list(cls, session_id: str) -> List[LinsightSessionVersion]:
        """
        获取灵思会话版本列表

        Args:
            session_id: 会话ID

        Returns:
            灵思会话版本列表
        """
        return await LinsightSessionVersionDao.get_session_versions_by_session_id(session_id)

    @classmethod
    async def modify_sop(cls, linsight_session_version_id: str, sop_content: str) -> Dict:
        """
        修改灵思会话版本的SOP内容

        Args:
            linsight_session_version_id: 会话版本ID
            sop_content: SOP内容

        Returns:
            操作结果
        """
        try:
            await LinsightSessionVersionDao.modify_sop_content(
                linsight_session_version_id=linsight_session_version_id,
                sop_content=sop_content
            )
            return {"success": True, "message": "modify sop content successfully"}
        except Exception as e:
            logger.error(f"修改SOP内容失败: {str(e)}")
            raise cls.LinsightError(str(e))

    @classmethod
    async def generate_sop(cls, linsight_session_version_id: str,
                           previous_session_version_id: Optional[str] = None,
                           feedback_content: Optional[str] = None,
                           reexecute: bool = False,
                           login_user: Optional[UserPayload] = None,
                           knowledge_list: List[KnowledgeRead] = None,
                           sop_id: Optional[int] = None) -> AsyncGenerator[Dict, None]:
        """
        生成SOP内容

        Args:
            linsight_session_version_id: 当前会话版本ID
            previous_session_version_id: 上一个会话版本ID
            feedback_content: 反馈内容
            reexecute: 是否重新执行
            login_user: 登录用户信息
            knowledge_list: 知识库列表

        Yields:
            生成的SOP内容事件
        """
        error_message = None
        try:
            # 获取工作台配置和会话版本
            session_version = await cls._get_session_version(linsight_session_version_id)

            if login_user.user_id != session_version.user_id:
                yield UnAuthorizedError().to_sse_event_instance()
                return
            try:
                # 创建LLM和工具
                llm, workbench_conf = await cls._get_llm()
            except Exception as e:
                logger.error(f"生成SOP内容失败: session_version_id={linsight_session_version_id}, error={str(e)}")
                raise cls.BishengLLMError(str(e))
            tools = await cls._prepare_tools(session_version, llm)

            # 准备历史摘要
            history_summary = await cls._prepare_history_summary(
                reexecute, previous_session_version_id
            )

            # 创建代理并生成SOP
            agent = await cls._create_linsight_agent(session_version, llm, tools, workbench_conf)

            if previous_session_version_id:
                session_version = await LinsightSessionVersionDao.get_by_id(previous_session_version_id)

            example_sop = None
            if sop_id:
                sop_db = await SOPManageService.get_sop_by_id(sop_id)
                example_sop = sop_db.content if sop_db else None

            content = ""
            async for res in cls._generate_sop_content(
                    agent, session_version, feedback_content, history_summary, knowledge_list, example_sop=example_sop
            ):
                if isinstance(res, cls.SearchSOPError):
                    yield res.error_class.to_sse_event(event="search_sop_error")
                    continue

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

            logger.info(f"生成SOP内容成功: session_version_id={linsight_session_version_id}")


        except cls.ToolsInitializationError as e:
            logger.exception(
                f"初始化灵思工作台工具失败: session_version_id={linsight_session_version_id}, error={str(e)}")
            error_message = LinsightToolInitError(exception=e)
        except cls.BishengLLMError as e:
            logger.exception(f"Bisheng LLM错误: session_version_id={linsight_session_version_id}, error={str(e)}")
            error_message = LinsightBishengLLMError(exception=e)
        except Exception as e:
            logger.exception(f"生成SOP内容失败: session_version_id={linsight_session_version_id}, error={str(e)}")
            error_message = LinsightGenerateSopError(exception=e)

        finally:
            if error_message:
                session_version = await LinsightSessionVersionDao.get_by_id(linsight_session_version_id)
                if session_version:
                    session_version.sop = f"{error_message.Msg}: {str(error_message.exception)}"
                    session_version.status = SessionVersionStatusEnum.SOP_GENERATION_FAILED
                    await LinsightSessionVersionDao.insert_one(session_version)
                yield error_message.to_sse_event_instance()

    @classmethod
    async def _get_session_version(cls, session_version_id: str) -> LinsightSessionVersion:
        """获取会话版本"""
        session_version = await LinsightSessionVersionDao.get_by_id(session_version_id)
        if not session_version:
            raise cls.LinsightError("灵思会话版本不存在")
        return session_version

    @classmethod
    async def _prepare_tools(cls, session_version: LinsightSessionVersion,
                             llm: BishengLLM) -> List[BaseTool]:
        """准备工具列表"""
        try:
            tools = await cls.init_linsight_config_tools(session_version, llm)

            root_path = os.path.join(CACHE_DIR, "linsight", session_version.id)
            os.makedirs(root_path, exist_ok=True)

            linsight_tools = await ToolServices.init_linsight_tools(root_path=root_path)
            tools.extend(linsight_tools)

            return tools
        except Exception as e:
            raise cls.ToolsInitializationError(str(e))

    @classmethod
    async def prepare_file_list(cls, session_version: LinsightSessionVersion) -> List[str]:
        """准备文件列表"""
        file_list = []
        template_str = """@{filename}的文件储存信息:{{'文件储存在语义检索库中的id':'{file_id}','文件储存地址':'{markdown}'}}@"""
        if not session_version.files:
            return file_list
        for file in session_version.files:
            file_list.append(template_str.format(filename=file['original_filename'],
                                                 file_id=file['file_id'],
                                                 markdown=f"./{file['markdown_filename']}"))
        return file_list

    @classmethod
    async def prepare_knowledge_list(cls, knowledge_list: list[KnowledgeRead]) -> List[str]:
        res = []
        if not knowledge_list:
            return res
        # 查询是否有个人知识库
        template_str = """@{name}的储存信息:{{'知识库储存在语义检索库中的id':'{id}'}}@"""
        for one in knowledge_list:
            if one.type == KnowledgeTypeEnum.PRIVATE.value:
                res.append(template_str.format(name="个人知识库", id=one.id))
            else:
                knowledge_str = template_str.format(name=one.name, id=one.id)
                if one.description:
                    knowledge_str += f"，{one.name}的描述是{one.description}"
                res.append(knowledge_str)
        return res

    @classmethod
    async def _prepare_history_summary(cls, reexecute: bool,
                                       previous_session_version_id: str) -> List[str]:
        """准备历史摘要"""
        history_summary = []

        if reexecute and previous_session_version_id:
            execute_tasks = await LinsightExecuteTaskDao.get_by_session_version_id(previous_session_version_id)

            for task in execute_tasks:
                if task.result:
                    answer = task.result.get("answer", "")
                    if answer:
                        history_summary.append(answer)

        return history_summary

    @classmethod
    async def _create_linsight_agent(cls, session_version: LinsightSessionVersion,
                                     llm: BishengLLM, tools: List[BaseTool],
                                     workbench_conf):
        """创建Linsight代理"""
        from bisheng_langchain.linsight.agent import LinsightAgent

        root_path = os.path.join(CACHE_DIR, "linsight", session_version.id[:8])
        linsight_conf = settings.get_linsight_conf()
        exec_config = ExecConfig(**linsight_conf.model_dump(), debug_id=session_version.id)
        return LinsightAgent(
            file_dir=root_path,
            query=session_version.question,
            llm=llm,
            tools=tools,
            task_mode=workbench_conf.linsight_executor_mode,
            exec_config=exec_config,
        )

    @classmethod
    async def _generate_sop_content(cls, agent, session_version: LinsightSessionVersion,
                                    feedback_content: Optional[str],
                                    history_summary: List[str],
                                    knowledge_list: List[KnowledgeRead] = None,
                                    example_sop: str = None) -> AsyncGenerator:
        """生成SOP内容"""
        file_list = await cls.prepare_file_list(session_version)
        knowledge_list = await cls.prepare_knowledge_list(knowledge_list)
        if example_sop:
            async for res in agent.generate_sop(sop=example_sop, file_list=file_list, knowledge_list=knowledge_list):
                yield res
        elif feedback_content is None:
            # 检索SOP模板
            sop_template, search_sop_error = await SOPManageService.search_sop(
                query=session_version.question, k=3
            )

            if search_sop_error:
                search_sop_error: BaseErrorCode
                logger.error(f"检索SOP模板失败: {search_sop_error.Msg}")
                yield cls.SearchSOPError(error_class=search_sop_error)

            sop_template = "\n\n".join([
                f"例子:\n\n{sop.page_content}"
                for sop in sop_template if sop.page_content
            ])

            async for res in agent.generate_sop(sop=sop_template, file_list=file_list, knowledge_list=knowledge_list):
                yield res
        else:

            sop_template = session_version.sop if session_version.sop else ""

            async for res in agent.feedback_sop(
                    sop=sop_template,
                    feedback=feedback_content,
                    history_summary=history_summary if history_summary else None,
                    file_list=file_list,
                    knowledge_list=knowledge_list
            ):
                yield res

    @classmethod
    async def get_execute_task_detail(cls, session_version_id: str,
                                      login_user: Optional[UserPayload] = None):
        """
        获取执行任务详情

        Args:
            session_version_id: 灵思会话版本ID
            login_user: 登录用户信息

        Returns:
            执行任务详情列表
        """
        execute_tasks = await LinsightExecuteTaskDao.get_by_session_version_id(session_version_id)

        if not execute_tasks:
            return []

        # 1. 获取一级任务 parent_task_id 是 None 的任务
        root_tasks = [task for task in execute_tasks if task.parent_task_id is None]

        # 2. 根据previous_task_id与next_task_id排序一级任务
        def sort_tasks_by_chain(tasks: List[Any]) -> List[Any]:
            """
            根据任务链排序任务列表
            previous_task_id是None则是第一个任务，next_task_id是None则是最后一个任务
            """
            if not tasks:
                return []

            # 创建任务字典以便快速查找
            task_dict = {task.id: task for task in tasks}

            # 找到链的开始节点（previous_task_id 为 None）
            start_tasks = [task for task in tasks if task.previous_task_id is None]

            sorted_tasks = []

            for start_task in start_tasks:
                # 从每个开始节点构建任务链
                current_task = start_task
                chain = []

                while current_task is not None:
                    chain.append(current_task)
                    # 通过next_task_id找到下一个任务
                    next_task_id = current_task.next_task_id
                    current_task = task_dict.get(next_task_id) if next_task_id else None

                sorted_tasks.extend(chain)

            # 处理可能存在的孤立任务（既没有previous也没有next指向它们）
            processed_ids = {task.id for task in sorted_tasks}
            orphan_tasks = [task for task in tasks if task.id not in processed_ids]
            sorted_tasks.extend(orphan_tasks)

            return sorted_tasks

        # 排序一级任务
        sorted_root_tasks = sort_tasks_by_chain(root_tasks)

        # 3. 构建任务树 使用 parent_task_id 将子任务与父任务关联起来
        def build_task_tree(parent_tasks: List[Any], all_tasks: List[Any]) -> List[TaskNode]:
            """
            构建任务树
            """
            # 创建任务映射
            task_map = {task.id: task for task in all_tasks}

            # 按父任务ID分组子任务
            children_map = {}
            for task in all_tasks:
                if task.parent_task_id:
                    if task.parent_task_id not in children_map:
                        children_map[task.parent_task_id] = []
                    children_map[task.parent_task_id].append(task)

            def build_node(task: Any) -> TaskNode:
                """递归构建任务节点"""
                node = TaskNode(task=task)

                # 获取子任务
                child_tasks = children_map.get(task.id, [])

                # 对子任务进行排序
                sorted_child_tasks = sort_tasks_by_chain(child_tasks)

                # 递归构建子节点
                for child_task in sorted_child_tasks:
                    child_node = build_node(child_task)
                    node.children.append(child_node)

                return node

            # 构建根节点列表
            root_nodes = []
            for parent_task in parent_tasks:
                root_node = build_node(parent_task)
                root_nodes.append(root_node)

            return root_nodes

        # 构建任务树
        task_tree = build_task_tree(sorted_root_tasks, execute_tasks)

        # 4. 返回任务树的根节点列表
        result = [node.to_dict() for node in task_tree]

        return result

    @classmethod
    async def upload_file(cls, file: UploadFile) -> Dict:
        """
        上传文件到灵思工作台

        Args:
            file: 上传的文件

        Returns:
            文件信息字典
        """
        # 生成文件信息
        file_id = uuid.uuid4().hex[:8]  # 生成8位唯一文件ID
        # url 编码 decode 文件名
        original_filename = unquote(file.filename)
        file_extension = original_filename.split('.')[-1] if '.' in original_filename else ''
        unique_filename = f"{file_id}.{file_extension}"

        # 保存文件
        file_path = await save_file_to_folder(file, 'linsight', unique_filename)

        upload_result = {
            "file_id": file_id,
            "filename": unique_filename,
            "original_filename": original_filename,
            "file_path": file_path,
            "parsing_status": "running",
        }

        # 缓存解析结果
        await cls._cache_parse_result(file_id, upload_result)

        return upload_result

    @classmethod
    async def parse_file(cls, upload_result: Dict) -> Dict:
        """
        解析上传的文件

        Args:
            upload_result: 上传结果

        Returns:
            解析结果
        """
        logger.info(f"开始解析文件: {upload_result}")

        file_id = upload_result["file_id"]
        original_filename = upload_result["original_filename"]
        file_path = upload_result["file_path"]
        try:
            # 获取工作台配置
            workbench_conf = await cls._get_workbench_config()
            collection_name = f"{cls.COLLECTION_NAME_PREFIX}{workbench_conf.embedding_model.id}"

            # 异步执行文件解析
            parse_result = await util.sync_func_to_async(cls._parse_file_sync)(file_id, file_path, original_filename,
                                                                               collection_name, workbench_conf)

            # 缓存解析结果
            await cls._cache_parse_result(file_id, parse_result)

            logger.info(f"文件解析完成: {parse_result}")
        except Exception as e:
            logger.error(f"文件解析失败: file_id={file_id}, error={str(e)}")
            parse_result = {
                "file_id": file_id,
                "original_filename": original_filename,
                "parsing_status": "failed",
                "error_message": str(e)
            }
            await cls._cache_parse_result(file_id, parse_result)

        return parse_result

    @classmethod
    def _parse_file_sync(cls, file_id: str, file_path: str, original_filename: str,
                         collection_name: str, workbench_conf) -> Dict:
        """
        同步解析文件

        Args:
            file_id: 文件ID
            file_path: 文件路径
            original_filename: 原始文件名
            collection_name: 集合名称
            workbench_conf: 工作台配置

        Returns:
            解析结果
        """
        # 读取文件内容
        try:
            texts, _, parse_type, _ = read_chunk_text(
                input_file=file_path,
                file_name=original_filename,
                separator=['\n\n', '\n'],
                separator_rule=['after', 'after'],
                chunk_size=1000,
                chunk_overlap=100,
                no_summary=True
            )

            # 生成markdown内容
            markdown_content = "\n".join(texts)
            markdown_bytes = markdown_content.encode('utf-8')

            # 保存markdown文件
            markdown_filename = f"{file_id}.md"
            minio_client.upload_tmp(markdown_filename, markdown_bytes)
            markdown_md5 = calculate_md5(markdown_bytes)

            # 处理向量存储
            cls._process_vector_storage(texts, file_id, collection_name, workbench_conf)

            return {
                "file_id": file_id,
                "original_filename": original_filename,
                "parsing_status": "completed",
                "parse_type": parse_type,
                "markdown_filename": markdown_filename,
                "markdown_file_path": markdown_filename,
                "markdown_file_md5": markdown_md5,
                "embedding_model_id": workbench_conf.embedding_model.id,
                "collection_name": collection_name
            }
        except Exception as e:
            logger.error(f"文件解析失败: file_id={file_id}, error={str(e)}")
            return {
                "file_id": file_id,
                "original_filename": original_filename,
                "parsing_status": "failed",
                "error_message": str(e)
            }

    @classmethod
    def _process_vector_storage(cls, texts: List[str], file_id: str,
                                collection_name: str, workbench_conf) -> None:
        """处理向量存储"""
        # 创建embeddings
        embeddings = decide_embeddings(workbench_conf.embedding_model.id)

        # 创建向量存储
        vector_client = decide_vectorstores(collection_name, "Milvus", embeddings)
        es_client = decide_vectorstores(collection_name, "ElasticKeywordsSearch", FakeEmbedding())

        # 添加文本到向量存储
        metadatas = [{"file_id": file_id} for _ in texts]
        vector_client.add_texts(texts, metadatas=metadatas)
        es_client.add_texts(texts, metadatas=metadatas)

    @classmethod
    async def _cache_parse_result(cls, file_id: str, parse_result: Dict) -> None:
        """缓存解析结果"""
        key = f"{cls.FILE_INFO_REDIS_KEY_PREFIX}{file_id}"
        await redis_client.aset(
            key=key,
            value=parse_result,
            expiration=60 * 60 * cls.CACHE_EXPIRATION_HOURS
        )

    @classmethod
    async def _init_bisheng_code_tool(cls, config_tool_ids: List[int], file_dir: str) -> List[BaseTool]:
        """
        特殊处理初始化毕昇的代码解释器工具
        """
        tools = []
        bisheng_code_tool = await GptsToolsDao.aget_tool_by_tool_key(tool_key='bisheng_code_interpreter')
        if not bisheng_code_tool or bisheng_code_tool.id not in config_tool_ids:
            return tools
        # 单独初始化代码解释器工具
        config_tool_ids.remove(bisheng_code_tool.id)
        code_config = json.loads(bisheng_code_tool.extra) if bisheng_code_tool.extra else {}
        if "config" not in code_config:
            code_config["config"] = {}
        if "e2b" not in code_config["config"]:
            code_config["config"]["e2b"] = {}
        # 默认60分钟的有效期
        code_config["config"]["e2b"]["timeout"] = 3600
        code_config["config"]["e2b"]["keep_sandbox"] = True
        file_list = []
        for root, dirs, files in os.walk(file_dir):
            for file in files:
                file_path = os.path.join(root, file)
                file_list.append(WriteEntry(data=file_path, path=file_path.replace(file_dir, ".")))
        code_config["config"]["e2b"]["file_list"] = file_list
        bisheng_code_tool.extra = code_config

        tools = AssistantAgent.sync_init_preset_tools([bisheng_code_tool], None, None)
        return tools

    @classmethod
    async def init_linsight_config_tools(cls, session_version: LinsightSessionVersion,
                                         llm: BishengLLM, need_upload: bool = False, file_dir: str = None) -> List[
        BaseTool]:
        """
        初始化灵思配置的工具

        Args:
            session_version: 会话版本模型
            llm: LLM实例
            need_upload: 是否需要给代码解释器绑定用户上传的文件
            file_dir: 用户上传文件的根目录

        Returns:
            工具列表
        """
        tools = []

        if not session_version.tools:
            return tools

        # 提取工具ID
        tool_ids = cls._extract_tool_ids(session_version.tools)

        # 获取工作台配置的工具ID
        ws_config = await WorkStationService.aget_config()
        config_tool_ids = cls._extract_tool_ids(ws_config.linsightConfig.tools or [])

        # todo 更好的工具初始化方案
        if need_upload and file_dir:
            bisheng_code_tool = await cls._init_bisheng_code_tool(config_tool_ids, file_dir)
            tools.extend(bisheng_code_tool)

        # 过滤有效的工具ID
        valid_tool_ids = [tid for tid in tool_ids if tid in config_tool_ids]

        # 初始化工具
        if valid_tool_ids:
            tools.extend(await AssistantAgent.init_tools_by_tool_ids(valid_tool_ids, llm=llm))

        return tools

    @classmethod
    def _extract_tool_ids(cls, tools: List[Dict]) -> List[int]:
        """
        从工具配置中提取工具ID

        Args:
            tools: 工具配置列表

        Returns:
            工具ID列表
        """
        tool_ids = []
        for tool in tools:
            if tool.get("children"):
                tool_ids.extend(int(child.get("id")) for child in tool["children"] if child.get("id"))
        return tool_ids

    @classmethod
    async def feedback_regenerate_sop_task(cls, session_version_model: LinsightSessionVersion,
                                           feedback: str) -> None:
        """
        根据反馈重新生成SOP任务

        Args:
            session_version_model: 灵思会话版本模型
            feedback: 反馈内容
        """
        try:
            file_list = await cls.prepare_file_list(session_version_model)

            # 创建LLM和工具
            llm, workbench_conf = await cls._get_llm()
            tools = await cls._prepare_tools(session_version_model, llm)

            # 获取历史摘要
            history_summary = await cls._get_history_summary(session_version_model.id)

            # 创建代理并生成SOP
            agent = await cls._create_linsight_agent(session_version_model, llm, tools, workbench_conf)

            sop_content = ""
            sop_template = session_version_model.sop or ''

            async for res in agent.feedback_sop(
                    sop=sop_template,
                    feedback=feedback,
                    history_summary=history_summary if history_summary else None,
                    file_list=file_list
            ):
                sop_content += res.content

            # sop写到记录表里，这个sop不需要关联会话，因为不需要更新分数
            await SOPManageService.add_sop_record(LinsightSOPRecord(
                name=session_version_model.title,
                description=None,
                user_id=session_version_model.user_id,
                content=sop_content,
            ))
        except cls.ToolsInitializationError as e:
            logger.exception(f"初始化灵思工作台工具失败: session_version_id={session_version_model.id}, error={str(e)}")

        except Exception as e:
            logger.exception(f"反馈重新生成SOP任务失败: session_version_id={session_version_model.id}, error={str(e)}")

    @classmethod
    async def _get_history_summary(cls, session_version_id: str) -> List[str]:
        """获取历史摘要"""
        history_summary = []
        execute_tasks = await LinsightExecuteTaskDao.get_by_session_version_id(session_version_id)

        for task in execute_tasks:
            if task.result:
                answer = task.result.get("answer", "")
                if answer:
                    history_summary.append(answer)

        return history_summary

    @classmethod
    async def batch_download_files(cls, file_info_list: List[BatchDownloadFilesSchema]) -> bytes:
        """
        批量下载文件

        Args:
            file_info_list: 文件信息列表

        Returns:
            包含文件下载信息的列表
        """

        async def download_file(file_info: BatchDownloadFilesSchema) -> Tuple[str, bytes]:
            """下载单个文件"""
            object_name = file_info.file_url
            object_name = object_name.replace(f"/{minio_client.bucket}/", "")
            try:

                bytes_io = BytesIO()

                file_byte = await util.sync_func_to_async(minio_client.get_object)(bucket_name=minio_client.bucket,
                                                                                   object_name=object_name)
                bytes_io.write(file_byte)

                bytes_io.seek(0)

                return file_info.file_name, bytes_io.getvalue()

            except Exception as e:
                logger.error(f"下载文件失败 {object_name}: {e}")
                return object_name, b''

        # 批量下载文件
        download_tasks = [download_file(file_info) for file_info in file_info_list]

        results = await asyncio.gather(*download_tasks)

        # 过滤掉下载失败的文件
        successful_files = [res for res in results if res[1]]

        if not successful_files:
            raise ValueError("没有成功下载的文件，无法生成ZIP")

        zip_bytes = util.bytes_to_zip(successful_files)
        return zip_bytes
