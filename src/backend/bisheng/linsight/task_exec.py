import asyncio
import json
import logging
import os
import shutil
from datetime import datetime
from typing import Optional, List, Dict

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import BaseTool

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.services.linsight.sop_manage import SOPManageService
from bisheng.api.services.llm import LLMService
from bisheng.api.v1.schema.inspiration_schema import SOPManagementSchema
from bisheng.cache.utils import create_cache_folder_async, CACHE_DIR
from bisheng.core.app_context import app_ctx
from bisheng.database.models import LinsightExecuteTask
from bisheng.database.models.linsight_execute_task import LinsightExecuteTaskDao, ExecuteTaskStatusEnum, \
    ExecuteTaskTypeEnum
from bisheng.database.models.linsight_session_version import LinsightSessionVersionDao, SessionVersionStatusEnum, \
    LinsightSessionVersion
from bisheng.interface.llms.custom import BishengLLM
from bisheng.utils.minio_client import minio_client
from bisheng.linsight.state_message_manager import LinsightStateMessageManager, MessageData, MessageEventType
from bisheng_langchain.linsight.agent import LinsightAgent
from bisheng_langchain.linsight.const import TaskStatus
from bisheng_langchain.linsight.event import NeedUserInput, GenerateSubTask, ExecStep, TaskStart, TaskEnd

logger = logging.getLogger(__name__)


class LinsightWorkflowTask(object):
    # 用户终止检查间隔（秒）
    USER_TERMINATION_CHECK_INTERVAL = 2

    def __init__(self, semaphore: asyncio.Semaphore):
        self.semaphore = semaphore
        self._state_message_manager: Optional[LinsightStateMessageManager] = None
        self.final_task_end_event: Optional[TaskEnd] = None
        self._termination_check_task: Optional[asyncio.Task] = None
        self._is_terminated = False

    @staticmethod
    async def get_bisheng_llm() -> BishengLLM:
        """获取Bisheng LLM实例"""
        workbench_conf = await LLMService.get_workbench_llm()
        return BishengLLM(model_id=workbench_conf.task_model.id)

    async def generate_sop_summary(self, sop_content: str, llm: BishengLLM) -> Dict[str, str]:
        """生成SOP摘要信息"""
        try:
            prompt_service = app_ctx.get_prompt_loader()
            prompt_obj = prompt_service.render_prompt(
                namespace="sop",
                prompt_name="gen_sop_summary",
                sop_detail=sop_content
            )

            prompt = ChatPromptTemplate(
                messages=[
                    ("system", prompt_obj.prompt.system),
                    ("user", prompt_obj.prompt.user),
                ]
            ).format_prompt()

            res = await llm.ainvoke(prompt)
            if not res.content:
                logger.error("LLM response content is None, cannot generate SOP summary.")
                return {"sop_title": "SOP名称", "sop_description": "SOP描述"}

            return json.loads(res.content)
        except Exception as e:
            logger.error(f"Error generating SOP summary: {str(e)}")
            return {"sop_title": "SOP名称", "sop_description": "SOP描述"}

    async def sop_storage(self, session_version_model: LinsightSessionVersion, llm: BishengLLM) -> None:
        """SOP存储逻辑"""
        sop_summary = await self.generate_sop_summary(session_version_model.sop, llm)

        sop_obj = SOPManagementSchema(
            name=sop_summary["sop_title"],
            description=sop_summary["sop_description"],
            content=session_version_model.sop,
            rating=0,
            linsight_session_id=session_version_model.session_id
        )

        await SOPManageService.add_sop(sop_obj, session_version_model.user_id)

    @staticmethod
    async def download_file(file_url, file_name: str, tmp_dir: str) -> str:
        """
        下载文件
        """
        logger.info(f"开始下载文件: {file_url}")

        file_path = os.path.join(tmp_dir, file_name)

        try:
            http_client = await app_ctx.get_http_client()
            # 使用with语句确保文件正确关闭
            with open(file_path, "wb") as f:
                async for chunk in http_client.stream(method="GET", url=str(file_url)):
                    f.write(chunk)

            # 检查文件是否下载成功
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                raise ValueError(f"文件下载失败或文件为空: {file_url}")

            return file_path
        except Exception as e:
            logger.error("下载文件失败: %s, 错误: %s", file_url, str(e))
            raise ValueError(f"下载文件失败: {file_url}, 错误: {str(e)}")

    @create_cache_folder_async
    async def init_file_dir(self, session_version_model: LinsightSessionVersion) -> str:
        """初始化文件目录"""

        if not session_version_model.files:
            return ""

        file_dir = os.path.join(CACHE_DIR, "linsight", session_version_model.id)
        os.makedirs(file_dir, exist_ok=True)

        for file in session_version_model.files:
            object_name = file["markdown_file_path"]
            file_url = minio_client.get_share_link(object_name)
            file_name = os.path.basename(object_name)
            try:
                await self.download_file(file_url, file_name, file_dir)
            except ValueError as e:
                logger.error(f"Error downloading file {file_name}: {str(e)}")

        return file_dir

    @staticmethod
    async def generate_tools(session_version_model: LinsightSessionVersion, llm: BishengLLM) -> List[BaseTool]:
        """生成工具列表"""
        tools: List[BaseTool] = []

        if not session_version_model.tools:
            return tools

        tool_ids = []
        for tool in session_version_model.tools:
            children = tool.get("children", [])
            tool_ids.extend(child.get("id") for child in children if child.get("id"))

        if tool_ids:
            tools.extend(await AssistantAgent.init_tools_by_tool_ids(tool_ids, llm=llm))

        return tools

    @staticmethod
    def _find_previous_task_id(target_task_id: str, task_info: List[dict]) -> Optional[str]:
        """查找前置任务ID"""
        for task in task_info:
            if task["id"] == target_task_id:
                continue
            if target_task_id in task.get("next_id", []):
                return task["id"]
        return None

    async def save_task_info(self, session_version_model: LinsightSessionVersion, task_info: List[dict]) -> None:
        """保存任务信息到数据库"""
        try:
            tasks = []
            for info in task_info:
                previous_task_id = self._find_previous_task_id(info["id"], task_info)

                task = LinsightExecuteTask(
                    id=info["id"],
                    parent_task_id=info.get("parent_id"),
                    session_version_id=session_version_model.id,
                    previous_task_id=previous_task_id,
                    next_task_id=info.get("next_id", [None])[0],
                    task_type=ExecuteTaskTypeEnum.COMPOSITE if info.get("node_loop") else ExecuteTaskTypeEnum.SINGLE,
                    task_data=info
                )
                tasks.append(task)

            await LinsightExecuteTaskDao.batch_create_tasks(tasks)
            await self._state_message_manager.set_execution_tasks(tasks)

        except Exception as e:
            logger.error(f"Error saving task info: {str(e)}")
            raise

    async def _wait_for_user_input_completion(self, task_id: str, check_interval: int = 1) -> Optional[
        LinsightExecuteTask]:
        """
        等待用户输入完成，同时检查是否被用户主动停止
        返回值: 如果用户输入完成返回task_model，如果被终止返回None
        """
        while True:
            # 检查是否被用户主动停止
            if self._is_terminated:
                logger.info(f"Task {task_id} terminated by user during waiting for input")
                return None

            task_model = await self._state_message_manager.get_execution_task(task_id)
            if task_model is None:
                raise ValueError(f"Task {task_id} not found.")

            if task_model.status == ExecuteTaskStatusEnum.USER_INPUT_COMPLETED:
                logger.info(f"User input for task {task_id} completed.")
                return task_model

            await asyncio.sleep(check_interval)

    async def task_wait_for_user_input(self, agent: LinsightAgent, event: NeedUserInput) -> None:
        """任务需要等待用户输入时，使用此方法"""
        try:
            # 更新状态为等待用户输入
            await self._state_message_manager.update_execution_task_status(
                event.task_id,
                status=ExecuteTaskStatusEnum.WAITING_FOR_USER_INPUT,
                input_prompt=event.call_reason
            )

            # 推送用户输入事件
            await self._state_message_manager.push_message(
                message=MessageData(event_type=MessageEventType.USER_INPUT, data=event.model_dump())
            )

            # 等待用户输入完成（同时检查是否被终止）
            task_model = await self._wait_for_user_input_completion(event.task_id)

            # 如果被用户终止，直接返回
            if task_model is None:
                logger.info(f"Task {event.task_id} terminated by user during waiting for input")
                return

            # 推送输入完成事件
            await self._state_message_manager.push_message(
                message=MessageData(event_type=MessageEventType.USER_INPUT_COMPLETED, data=task_model.model_dump())
            )

            # 继续执行任务
            logger.info(f"Continuing task {event.task_id} with user input: {task_model.user_input}")
            await agent.continue_task(event.task_id, task_model.user_input)

        except Exception as e:
            logger.error(f"Error waiting for user input task {event.task_id}: {str(e)}")
            raise

    async def _handle_single_event(self, agent: LinsightAgent, event, session_version_model: LinsightSessionVersion):
        """统一的事件处理逻辑"""
        if isinstance(event, GenerateSubTask):
            await self.save_task_info(session_version_model, event.subtask)
            logger.info(f"Generated sub-task: {event}")

        elif isinstance(event, TaskStart):
            await self.handle_task_start(event)

        elif isinstance(event, TaskEnd):
            await self.handle_task_end(event)

        elif isinstance(event, NeedUserInput):
            asyncio.create_task(self.task_wait_for_user_input(agent, event))

        elif isinstance(event, ExecStep):
            await self.handle_exec_step(event)
            logger.info(f"Executing: {event}")

    async def handle_exec_step(self, event: ExecStep) -> None:
        """处理执行步骤事件"""
        await self._state_message_manager.add_execution_task_step(event.task_id, step=event)
        await self._state_message_manager.push_message(
            message=MessageData(event_type=MessageEventType.TASK_EXECUTE_STEP, data=event.model_dump())
        )

    async def handle_task_start(self, event: TaskStart) -> None:
        """处理任务开始"""
        task_data = await self._state_message_manager.update_execution_task_status(
            task_id=event.task_id,
            status=ExecuteTaskStatusEnum.IN_PROGRESS
        )

        await self._state_message_manager.push_message(
            message=MessageData(event_type=MessageEventType.TASK_START, data=task_data)
        )

    async def handle_task_end(self, event: TaskEnd) -> None:
        """处理任务结束"""
        status = ExecuteTaskStatusEnum.SUCCESS if event.status == TaskStatus.SUCCESS.value else ExecuteTaskStatusEnum.FAILED

        task_data = await self._state_message_manager.update_execution_task_status(
            task_id=event.task_id,
            status=status,
            result={"answer": event.answer}
        )

        await self._state_message_manager.push_message(
            message=MessageData(event_type=MessageEventType.TASK_END, data=task_data)
        )

        # 保存最终任务结果
        self.final_task_end_event = event

    async def _start_termination_monitor(self, session_version_model: LinsightSessionVersion) -> None:
        """启动终止监控任务"""

        async def monitor_termination():
            while not self._is_terminated:
                try:
                    if await self._check_user_termination():
                        self._is_terminated = True
                        await self._handle_user_termination(session_version_model)
                        break
                    await asyncio.sleep(self.USER_TERMINATION_CHECK_INTERVAL)
                except Exception as e:
                    logger.error(f"Error in termination monitor: {str(e)}")
                    await asyncio.sleep(self.USER_TERMINATION_CHECK_INTERVAL)

        self._termination_check_task = asyncio.create_task(monitor_termination())

    async def _stop_termination_monitor(self) -> None:
        """停止终止监控任务"""
        if self._termination_check_task and not self._termination_check_task.done():
            self._termination_check_task.cancel()
            try:
                await self._termination_check_task
            except asyncio.CancelledError:
                pass

    async def _check_user_termination(self) -> bool:
        """检查用户是否主动停止任务"""
        if self._is_terminated:
            return True

        try:
            current_session = await self._state_message_manager.get_session_version_info()
            if current_session and current_session.status == SessionVersionStatusEnum.TERMINATED:
                logger.info(f"User terminated session {current_session.id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error checking user termination: {str(e)}")
            return False

    async def _handle_user_termination(self, session_version_model: LinsightSessionVersion) -> None:
        """处理用户主动停止任务"""
        logger.info(f"Handling user termination for session {session_version_model.id}")

        # 确保状态为已终止
        session_version_model.status = SessionVersionStatusEnum.TERMINATED
        session_version_model.output_result = {"answer": "任务已被用户主动停止"}

        # 刷新会话信息
        await self._state_message_manager.set_session_version_info(session_version_model)

        # 推送终止消息
        await self._state_message_manager.push_message(
            message=MessageData(
                event_type=MessageEventType.TASK_TERMINATED,
                data={
                    "message": "任务已被用户主动停止",
                    "session_id": session_version_model.id,
                    "terminated_at": datetime.now().isoformat()
                }
            )
        )

    async def _process_agent_events(self, agent: LinsightAgent, task_info: List[dict],
                                    session_version_model: LinsightSessionVersion) -> bool:
        """
        处理agent事件流 - 使用任务取消机制解决阻塞问题
        返回值: True表示正常完成，False表示被用户终止
        """

        async def process_events():
            """事件处理协程"""
            try:
                async for event in agent.ainvoke(task_info, session_version_model.sop):
                    # 在处理每个事件前检查是否被终止
                    if self._is_terminated:
                        logger.info("Agent event processing interrupted by user termination")
                        return False

                    await self._handle_single_event(agent, event, session_version_model)

                return True
            except asyncio.CancelledError:
                logger.info("Agent event processing cancelled by user")
                return False
            except Exception as e:
                logger.error(f"Error in event processing: {str(e)}")
                raise

        async def check_termination():
            """终止检查协程"""
            while not self._is_terminated:
                await asyncio.sleep(self.USER_TERMINATION_CHECK_INTERVAL)

            logger.info("Termination detected, cancelling event processing")
            return False

        # 创建事件处理任务和终止检查任务
        event_task = asyncio.create_task(process_events())
        termination_task = asyncio.create_task(check_termination())

        try:
            # 等待任一任务完成
            done, pending = await asyncio.wait(
                [event_task, termination_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            # 取消未完成的任务
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # 检查结果
            if event_task in done:
                try:
                    result = await event_task
                    return result
                except Exception as e:
                    logger.error(f"Event processing task failed: {str(e)}")
                    raise
            else:
                # 终止检查任务完成，说明被用户终止
                logger.info("Agent event processing terminated by user")
                return False

        except Exception as e:
            logger.error(f"Error in agent events processing: {str(e)}")
            # 确保清理任务
            for task in [event_task, termination_task]:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            raise

    async def _handle_final_result(self, session_version_model: LinsightSessionVersion) -> None:
        """处理最终结果"""
        if not self.final_task_end_event:
            logger.error("No final task end event found")
            return

        if self.final_task_end_event.status == TaskStatus.SUCCESS.value:
            session_version_model.status = SessionVersionStatusEnum.COMPLETED
            session_version_model.output_result = {"answer": self.final_task_end_event.answer}

            await self._state_message_manager.set_session_version_info(session_version_model)
            await self._state_message_manager.push_message(
                message=MessageData(event_type=MessageEventType.FINAL_RESULT,
                                    data=session_version_model.model_dump())
            )
        else:
            await self._handle_task_failure(session_version_model, "Task execution failed")

    async def _handle_task_failure(self, session_version_model: LinsightSessionVersion, error_msg: str) -> None:
        """处理任务失败"""
        session_version_model.status = SessionVersionStatusEnum.TERMINATED
        await self._state_message_manager.set_session_version_info(session_version_model)
        await self._state_message_manager.push_message(
            message=MessageData(event_type=MessageEventType.ERROR_MESSAGE, data={"error": error_msg})
        )

    async def _check_session_status(self, session_version_model: LinsightSessionVersion) -> bool:
        """检查会话状态，如果正在进行中则返回True"""
        if session_version_model.status == SessionVersionStatusEnum.IN_PROGRESS:
            logger.info(f"Session version {session_version_model.id} is already in progress.")
            return True
        return False

    async def async_run(self, linsight_session_version_id: str) -> None:
        """异步任务执行逻辑"""

        self._state_message_manager = LinsightStateMessageManager(linsight_session_version_id)
        session_version_model = None
        file_dir = None
        try:
            # 获取会话任务
            session_version_model = await LinsightSessionVersionDao.get_by_id(linsight_session_version_id)

            # 检查会话状态
            if await self._check_session_status(session_version_model):
                return

            # 更新会话状态为进行中
            session_version_model.status = SessionVersionStatusEnum.IN_PROGRESS
            await self._state_message_manager.set_session_version_info(session_version_model)

            # 启动终止监控
            await self._start_termination_monitor(session_version_model)

            # 初始化LLM、文件目录和工具
            bisheng_llm = await self.get_bisheng_llm()

            file_dir = await self.init_file_dir(session_version_model)

            tools = await self.generate_tools(session_version_model, bisheng_llm)

            # 创建agent并生成任务
            agent = LinsightAgent(
                llm=bisheng_llm,
                query=session_version_model.question,
                tools=tools,
                file_dir=file_dir
            )

            # 检查是否在初始化过程中被终止
            if self._is_terminated:
                logger.info(f"Task terminated during initialization for session {session_version_model.id}")
                return

            task_info = await agent.generate_task(session_version_model.sop)
            await self.save_task_info(session_version_model, task_info)

            # 使用改进的事件处理方法
            task_completed = await self._process_agent_events(agent, task_info, session_version_model)

            # 如果任务被用户终止，直接返回
            if not task_completed:
                logger.info(f"Task execution terminated by user for session {session_version_model.id}")
                return

            # 处理最终结果
            await self._handle_final_result(session_version_model)

            # SOP存储
            await self.sop_storage(session_version_model, bisheng_llm)

        except Exception as e:
            logger.error(f"Error in LinsightWorkflowTask: {str(e)}")

            # 确保能获取到session_version_model
            if session_version_model is None:
                try:
                    session_version_model = await LinsightSessionVersionDao.get_by_id(linsight_session_version_id)
                except Exception as inner_e:
                    logger.error(f"Failed to get session version model: {str(inner_e)}")
                    return

            await self._handle_task_failure(session_version_model, str(e))

        finally:
            # 停止终止监控
            await self._stop_termination_monitor()
            if file_dir and os.path.exists(file_dir):
                try:
                    # 清理临时文件目录
                    shutil.rmtree(file_dir)
                except Exception as cleanup_error:
                    logger.error(f"Error cleaning up file directory {file_dir}: {str(cleanup_error)}")
            # 释放信号量
            if self.semaphore.locked():
                self.semaphore.release()
