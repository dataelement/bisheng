import asyncio
import os
import shutil
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, List, Dict, Callable

from loguru import logger

from bisheng.api.services.invite_code.invite_code import InviteCodeService
from bisheng.api.services.linsight.workbench_impl import LinsightWorkbenchImpl
from bisheng.api.services.tool import ToolServices
from bisheng.api.v1.schema.linsight_schema import UserInputEventSchema
from bisheng.cache.utils import create_cache_folder_async, CACHE_DIR
from bisheng.core.app_context import app_ctx
from bisheng.database.models import LinsightExecuteTask
from bisheng.database.models.linsight_execute_task import LinsightExecuteTaskDao, ExecuteTaskStatusEnum, \
    ExecuteTaskTypeEnum
from bisheng.database.models.linsight_session_version import LinsightSessionVersionDao, SessionVersionStatusEnum, \
    LinsightSessionVersion
from bisheng.linsight import utils as linsight_execute_utils
from bisheng.linsight.state_message_manager import LinsightStateMessageManager, MessageData, MessageEventType
from bisheng.llm.domain.llm import BishengLLM
from bisheng.llm.domain.services import LLMService
from bisheng.common.services.config_service import settings
from bisheng.utils.minio_client import minio_client
from bisheng_langchain.linsight.agent import LinsightAgent
from bisheng_langchain.linsight.const import TaskStatus, ExecConfig
from bisheng_langchain.linsight.event import NeedUserInput, GenerateSubTask, ExecStep, TaskStart, TaskEnd, BaseEvent


class TaskExecutionError(Exception):
    """任务执行异常"""
    pass


class UserTerminationError(Exception):
    """用户主动终止异常"""
    pass


# 任务已在进行中异常
class TaskAlreadyInProgressError(Exception):
    """任务已在进行中异常"""
    pass


class LinsightWorkflowTask:
    """工作流任务执行器 - 负责管理整个任务的生命周期"""

    USER_TERMINATION_CHECK_INTERVAL = 2

    def __init__(self):
        self._state_manager: Optional[LinsightStateMessageManager] = None
        self._is_terminated = False
        self._termination_task: Optional[asyncio.Task] = None
        self._final_result: Optional[TaskEnd] = None
        self.file_dir: Optional[str] = None
        self.session_version_id: Optional[str] = None
        self.step_event_extra_files: List[Dict] = []  # 用于存储步骤事件额外处理的文件信息
        self.llm: Optional[BishengLLM] = None  # 用于存储LLM实例

    # ==================== 资源管理 ====================

    @asynccontextmanager
    async def _managed_execution(self):
        """管理执行资源的上下文管理器"""

        self._state_manager = LinsightStateMessageManager(self.session_version_id)
        session_model = await self._get_session_model(self.session_version_id)

        # 检查会话状态
        if await self._is_session_in_progress(session_model):
            raise TaskAlreadyInProgressError("任务已在进行中")

        try:

            # 启动终止监控
            await self._start_termination_monitor(session_model)

            # 初始化文件目录
            self.file_dir = await self._init_file_directory(session_model)

            yield session_model

        finally:
            await self._cleanup_resources()

    async def _cleanup_resources(self):
        """清理资源"""
        try:
            # 停止终止监控
            await self._stop_termination_monitor()

            # 清理文件目录
            if self.file_dir and os.path.exists(self.file_dir):
                shutil.rmtree(self.file_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"资源清理失败: {e}")

    # ==================== 核心执行逻辑 ====================

    async def async_run(self, session_version_id: str) -> None:
        """异步任务执行入口"""

        self.session_version_id = session_version_id

        with logger.contextualize(trace_id=self.session_version_id):
            logger.info(f"开始执行任务: session_version_id={self.session_version_id}")

            try:

                async with self._managed_execution() as session_model:
                    await self._execute_workflow(session_model)

            except UserTerminationError:
                logger.info(f"任务被用户主动终止: session_version_id={self.session_version_id}")
            except TaskAlreadyInProgressError:
                logger.warning(f"任务已在进行中: session_version_id={self.session_version_id}")
            except TaskExecutionError as e:
                logger.error(f"任务执行失败: session_version_id={self.session_version_id}")
                await self._handle_execution_error(e)
            except Exception as e:
                logger.error(f"未知错误: session_version_id={self.session_version_id}, error={e}")
                await self._handle_execution_error(e)

    async def _execute_workflow(self, session_model: LinsightSessionVersion):
        """执行工作流的核心逻辑"""

        # 更新会话状态为进行中
        await self._update_session_status(session_model, SessionVersionStatusEnum.IN_PROGRESS)

        # 初始化执行组件
        self.llm = await self._get_llm()
        tools = await self._generate_tools(session_model)
        try:
            # 生成工具列表
            linsight_tools = await ToolServices.init_linsight_tools(root_path=self.file_dir)
            tools.extend(linsight_tools)
            # 创建智能体
            agent = await self._create_agent(session_model, tools)

            # 检查是否在初始化过程中被终止
            self._check_termination()

            # 生成并保存任务
            task_info = await agent.generate_task(session_model.sop)
            await self._save_task_info(session_model, task_info)

            # 执行任务
            success = await self._execute_agent_tasks(agent, task_info, session_model)
        finally:
            # 清理代码解释器的沙盒
            for one in tools:
                if one.name == "bisheng_code_interpreter":
                    one.close()
                    break

        if success:
            await self._handle_task_completion(session_model)
        else:
            await self._handle_user_termination(session_model)
            raise UserTerminationError("任务被用户终止")

    # ==================== 会话和状态管理 ====================

    async def _get_session_model(self, session_version_id: str) -> LinsightSessionVersion:
        """获取会话模型"""
        try:
            return await LinsightSessionVersionDao.get_by_id(session_version_id)
        except Exception as e:
            raise TaskExecutionError(f"获取会话模型失败: {e}")

    async def _is_session_in_progress(self, session_model: LinsightSessionVersion) -> bool:
        """检查会话是否已在进行中"""
        if session_model.status == SessionVersionStatusEnum.IN_PROGRESS:
            logger.info(f"会话 {session_model.id} 已在进行中")
            return True
        return False

    async def _update_session_status(self, session_model: LinsightSessionVersion, status: SessionVersionStatusEnum):
        """更新会话状态"""
        session_model.status = status
        await self._state_manager.set_session_version_info(session_model)

    # ==================== 组件初始化 ====================

    async def _get_llm(self) -> BishengLLM:
        """获取LLM实例"""
        try:
            workbench_conf = await LLMService.get_workbench_llm()
            linsight_conf = settings.get_linsight_conf()
            return BishengLLM(model_id=workbench_conf.task_model.id, temperature=linsight_conf.default_temperature)
        except Exception as e:
            raise TaskExecutionError("任务已终止，请联系管理员检查灵思任务执行模型状态")

    @create_cache_folder_async
    async def _init_file_directory(self, session_model: LinsightSessionVersion) -> str:
        """初始化文件目录"""
        file_dir = os.path.join(CACHE_DIR, "linsight", session_model.id[:8])
        file_dir = os.path.normpath(file_dir)
        os.makedirs(file_dir, exist_ok=True)

        if not session_model.files:
            return file_dir

        # 并发下载文件
        download_tasks = [
            self._download_file(file_info, file_dir)
            for file_info in session_model.files
        ]

        results = await asyncio.gather(*download_tasks, return_exceptions=True)

        # 记录下载失败的文件
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                file_name = os.path.basename(session_model.files[i]["markdown_file_path"])
                logger.error(f"文件下载失败 {file_name}: {result}")

        return file_dir

    async def _download_file(self, file_info: dict, target_dir: str) -> str:
        """下载单个文件"""
        object_name = file_info["markdown_file_path"]
        file_name = file_info.get("markdown_filename", os.path.basename(object_name))
        file_path = os.path.join(target_dir, file_name)

        try:
            file_url = minio_client.get_share_link(object_name)
            http_client = await app_ctx.get_http_client()

            with open(file_path, "wb") as f:
                async for chunk in http_client.stream(method="GET", url=str(file_url)):
                    f.write(chunk)

            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                raise ValueError(f"文件下载失败或为空: {object_name}")

            return file_path

        except Exception as e:
            logger.error(f"下载文件失败 {object_name}: {e}")
            raise

    async def _generate_tools(self, session_model: LinsightSessionVersion) -> List:
        """生成工具列表"""
        if not session_model.tools:
            return []

        return await LinsightWorkbenchImpl.init_linsight_config_tools(session_version=session_model, llm=self.llm,
                                                                      need_upload=True, file_dir=self.file_dir)

    async def _create_agent(self, session_model: LinsightSessionVersion, tools: List) -> LinsightAgent:

        workbench_conf = await LLMService.get_workbench_llm()
        linsight_conf = settings.get_linsight_conf()
        exec_config = ExecConfig(**linsight_conf.model_dump(), debug_id=session_model.id)

        """创建智能体"""
        return LinsightAgent(
            llm=self.llm,
            query=session_model.question,
            tools=tools,
            file_dir=self.file_dir,
            task_mode=workbench_conf.linsight_executor_mode,
            exec_config=exec_config,
        )

    # ==================== 任务执行 ====================

    async def _save_task_info(self, session_model: LinsightSessionVersion, task_info: List[dict]):
        """保存任务信息"""
        try:
            tasks = []
            # step_id不一定是规律的step_int, 从agent拿到的task_info顺序即为执行顺序
            sorted_data = task_info

            for index, task_info in enumerate(sorted_data):
                previous_task_id = sorted_data[index - 1]["id"] if index > 0 else None
                next_task_id = sorted_data[index + 1]["id"] if index < len(sorted_data) - 1 else None
                task = LinsightExecuteTask(
                    id=task_info["id"],
                    parent_task_id=task_info.get("parent_id"),
                    session_version_id=session_model.id,
                    previous_task_id=previous_task_id,
                    next_task_id=next_task_id,
                    task_type=ExecuteTaskTypeEnum.COMPOSITE if task_info.get(
                        "node_loop") else ExecuteTaskTypeEnum.SINGLE,
                    task_data=task_info
                )
                tasks.append(task)

            await LinsightExecuteTaskDao.batch_create_tasks(tasks)
            await self._state_manager.set_execution_tasks(tasks)

            # 推送生成任务消息
            await self._state_manager.push_message(MessageData(
                event_type=MessageEventType.TASK_GENERATE,
                data={"tasks": [task.model_dump() for task in tasks]}
            ))

            logger.info(f"Set {len(tasks)} execution tasks")

        except Exception as e:
            logger.error(f"保存任务信息失败: {e}")
            raise TaskExecutionError(f"保存任务信息失败: {e}")

    async def _execute_agent_tasks(self, agent, task_info: List[dict],
                                   session_model) -> bool:
        """执行智能体任务 - 修改版本支持用户终止"""

        async def agent_execution():
            """智能体执行任务"""
            file_list = await LinsightWorkbenchImpl.prepare_file_list(session_model)
            async for event in agent.ainvoke(task_info, session_model.sop, file_list=file_list):
                await self._handle_event(agent, event, session_model)
            return True

        async def termination_monitor():
            """终止监控任务"""
            while True:
                await asyncio.sleep(0.5)  # 每0.5秒检查一次
                self._check_termination()

        try:
            # 创建两个并发任务
            # 准备用户上传的文件
            agent_task = asyncio.create_task(agent_execution())
            monitor_task = asyncio.create_task(termination_monitor())

            # 等待任何一个任务完成
            done, pending = await asyncio.wait(
                [agent_task, monitor_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            # 取消未完成的任务
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.debug("成功取消挂起的任务")
                    pass

            # 检查完成的任务结果
            for task in done:
                if task.exception():
                    if isinstance(task.exception(), UserTerminationError):
                        logger.info("智能体任务被用户终止")
                        return False
                    else:
                        raise task.exception()
                else:
                    # 如果是智能体任务正常完成
                    if task == agent_task:
                        logger.info("智能体任务正常完成")
                        return True

            return True

        except UserTerminationError:
            logger.info("智能体任务被用户终止")
            return False
        except Exception as e:
            logger.error(f"task_exec_error {traceback.format_exc()}")
            raise TaskExecutionError(f"智能体任务执行失败: {e}")

    # ==================== 事件处理 ====================

    async def _handle_event(self, agent: LinsightAgent, event: BaseEvent, session_model: LinsightSessionVersion):
        """处理事件"""

        event_handlers: Dict[type[BaseEvent], Callable] = {
            GenerateSubTask: self._handle_generate_subtask,
            TaskStart: self._handle_task_start,
            TaskEnd: self._handle_task_end,
            NeedUserInput: self._handle_need_user_input,
            ExecStep: self._handle_exec_step,
        }

        handler = event_handlers.get(type(event))
        if handler:
            await handler(agent, event, session_model)
        else:
            logger.warning(f"未知事件类型: {type(event)}")

    async def _handle_generate_subtask(self, agent: LinsightAgent, event: GenerateSubTask,
                                       session_model: LinsightSessionVersion):
        """处理生成子任务事件"""
        await self._save_task_info(session_model, event.subtask)
        logger.debug(f"生成子任务: {event}")

    async def _handle_task_start(self, agent: LinsightAgent, event: TaskStart, session_model: LinsightSessionVersion):
        """处理任务开始事件"""
        task_data = await self._state_manager.update_execution_task_status(
            task_id=event.task_id,
            status=ExecuteTaskStatusEnum.IN_PROGRESS
        )

        await self._state_manager.push_message(
            MessageData(event_type=MessageEventType.TASK_START, data=task_data)
        )

    async def _handle_task_end(self, agent: LinsightAgent, event: TaskEnd, session_model: LinsightSessionVersion):
        """处理任务结束事件"""
        status = ExecuteTaskStatusEnum.SUCCESS if event.status == TaskStatus.SUCCESS.value else ExecuteTaskStatusEnum.FAILED

        task_data = await self._state_manager.update_execution_task_status(
            task_id=event.task_id,
            status=status,
            result={"answer": event.answer},
            task_data=event.data
        )

        await self._state_manager.push_message(
            MessageData(event_type=MessageEventType.TASK_END, data=task_data)
        )

        # 保存最终结果
        self._final_result = event

    async def _handle_need_user_input(self, agent: LinsightAgent, event: NeedUserInput,
                                      session_model: LinsightSessionVersion):
        """处理需要用户输入事件"""
        asyncio.create_task(self._wait_for_user_input(agent, event))

    async def _handle_exec_step(self, agent: LinsightAgent, event: ExecStep, session_model: LinsightSessionVersion):
        """处理执行步骤事件"""

        # 额外处理步骤事件
        event = await linsight_execute_utils.handle_step_event_extra(event, self)

        await self._state_manager.add_execution_task_step(event.task_id, step=event)
        await self._state_manager.push_message(
            MessageData(event_type=MessageEventType.TASK_EXECUTE_STEP, data=event.model_dump())
        )

    async def _wait_for_user_input(self, agent: LinsightAgent, event: NeedUserInput):
        """等待用户输入"""
        try:

            await self._state_manager.add_execution_task_step(event.task_id, step=event)

            # 更新状态为等待用户输入
            await self._state_manager.update_execution_task_status(
                event.task_id,
                status=ExecuteTaskStatusEnum.WAITING_FOR_USER_INPUT,
            )

            # 推送用户输入事件
            await self._state_manager.push_message(
                MessageData(event_type=MessageEventType.USER_INPUT, data=event.model_dump())
            )

            # 等待用户输入完成
            task_model = await self._wait_for_input_completion(event.task_id)

            user_input_event = task_model.history[-1] if task_model.history else None
            if user_input_event is None or user_input_event.get("step_type") != "call_user_input":
                raise TaskExecutionError(f"任务 {event.task_id} 在等待用户输入时未找到用户输入事件")

            user_input_event = UserInputEventSchema.model_validate(user_input_event)

            # 检查用户是否上传了文件
            if user_input_event.files:
                # 并发下载文件
                download_tasks = [
                    self._download_file(file_info, self.file_dir)
                    for file_info in user_input_event.files
                ]

                results = await asyncio.gather(*download_tasks, return_exceptions=True)

                # 记录下载失败的文件
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        file_name = os.path.basename(user_input_event.files[i]["markdown_file_path"])
                        logger.error(f"文件下载失败 {file_name}: {result}")

                user_input_event.user_input += f"\n\n已上传文件:\n" + \
                                               "\n".join([f"- {file}" for file in results if
                                                          not isinstance(file, Exception)])

            # 推送输入完成事件
            await self._state_manager.push_message(
                MessageData(event_type=MessageEventType.USER_INPUT_COMPLETED, data=task_model.model_dump())
            )

            # 继续执行任务
            await agent.continue_task(event.task_id, user_input_event.user_input)

        except Exception as e:
            raise TaskExecutionError(f"等待用户输入失败 task_id={event.task_id}: {e}")

    async def _wait_for_input_completion(self, task_id: str) -> Optional[LinsightExecuteTask]:
        """等待用户输入完成"""
        while True:
            self._check_termination()

            task_model = await self._state_manager.get_execution_task(task_id)
            if task_model is None:
                raise ValueError(f"任务 {task_id} 不存在")

            if task_model.status == ExecuteTaskStatusEnum.USER_INPUT_COMPLETED:
                return task_model

            await asyncio.sleep(1)

    # ==================== 终止检查 ====================

    def _check_termination(self):
        """检查是否被终止"""
        if self._is_terminated:
            logger.info("检测到终止信号，准备终止智能体任务")
            raise UserTerminationError("任务被用户终止")

    async def _start_termination_monitor(self, session_model: LinsightSessionVersion):
        """启动终止监控"""

        async def monitor():
            while not self._is_terminated:
                try:
                    if await self._check_user_termination():
                        self._is_terminated = True
                        break
                    await asyncio.sleep(self.USER_TERMINATION_CHECK_INTERVAL)
                except Exception as e:
                    logger.error(f"终止监控异常: {e}")
                    await asyncio.sleep(self.USER_TERMINATION_CHECK_INTERVAL)

        self._termination_task = asyncio.create_task(monitor())

    async def _stop_termination_monitor(self):
        """停止终止监控"""
        if self._termination_task and not self._termination_task.done():
            self._termination_task.cancel()
            try:
                await self._termination_task
            except asyncio.CancelledError:
                pass

    async def _check_user_termination(self) -> bool:
        """检查用户是否主动终止"""
        if self._is_terminated:
            return True

        try:
            current_session = await self._state_manager.get_session_version_info()
            return (current_session and
                    current_session.status == SessionVersionStatusEnum.TERMINATED)
        except Exception as e:
            logger.error(f"检查用户终止状态失败: {e}")
            return False

    async def _handle_user_termination(self, session_model: LinsightSessionVersion):
        """处理用户主动终止"""
        logger.info(f"处理用户终止 {session_model.id}")

        session_model.status = SessionVersionStatusEnum.TERMINATED
        session_model.output_result = {"answer": "任务已被用户主动停止"}

        await self._state_manager.set_session_version_info(session_model)

        # 设置所有任务为失败
        await self._set_tasks_failed()

        # 推送终止消息
        await self._state_manager.push_message(
            MessageData(
                event_type=MessageEventType.TASK_TERMINATED,
                data={
                    "message": "任务已被用户主动停止",
                    "session_id": session_model.id,
                    "terminated_at": datetime.now().isoformat()
                }
            )
        )

    # ==================== 任务完成处理 ====================

    async def _handle_task_completion(self, session_model: LinsightSessionVersion):
        """处理任务完成"""
        if not self._final_result:
            logger.error("没有找到最终任务结果")
            return

        if self._final_result.status == TaskStatus.SUCCESS.value:
            await self._handle_task_success(session_model)
        else:
            await self._handle_task_failure(session_model, "任务执行失败")

    async def _handle_task_success(self, session_model: LinsightSessionVersion):
        """处理任务成功"""
        try:
            # 读取文件目录文件详情
            file_details = await linsight_execute_utils.read_file_directory(self.file_dir)
            logger.debug(f"读取文件目录文件详情: {file_details}")

            final_result_files = await linsight_execute_utils.get_final_result_file(
                session_model=session_model,
                file_details=file_details,
                answer=self._final_result.answer
            )
            execution_tasks = await self._state_manager.get_execution_tasks()
            all_from_session_files = await linsight_execute_utils.get_all_files_from_session(
                execution_tasks=execution_tasks, file_details=file_details)

            # 更新会话状态
            session_model.status = SessionVersionStatusEnum.COMPLETED
            session_model.output_result = {
                "answer": self._final_result.answer,
                "final_files": final_result_files,
                "all_from_session_files": all_from_session_files
            }

            # 保存会话信息并推送消息
            await self._state_manager.set_session_version_info(session_model)
            await self._state_manager.push_message(
                MessageData(
                    event_type=MessageEventType.FINAL_RESULT,
                    data=session_model.model_dump()
                )
            )

            logger.info(f"任务成功完成，处理了 {len(final_result_files)} 个文件")

        except Exception as e:
            logger.error(f"处理任务成功时发生错误: {e}")
            raise TaskExecutionError(f"处理任务成功时发生错误: {e}")

    # 修改所有的任务失败处理逻辑
    async def _set_tasks_failed(self):
        """将所有任务设置为失败"""
        try:
            # 获取所有执行任务
            execution_tasks = await self._state_manager.get_execution_tasks()

            for task in execution_tasks:
                # 更新每个任务状态为已终止
                if task.status not in [ExecuteTaskStatusEnum.TERMINATED, ExecuteTaskStatusEnum.SUCCESS,
                                       ExecuteTaskStatusEnum.FAILED]:
                    await self._state_manager.update_execution_task_status(task_id=task.id,
                                                                           status=ExecuteTaskStatusEnum.TERMINATED)
        except Exception as e:
            logger.warning(f"设置任务失败时发生错误: {e}")

    async def _handle_task_failure(self, session_model: LinsightSessionVersion, error_msg: str):
        """处理任务失败"""
        session_model.status = SessionVersionStatusEnum.FAILED
        session_model.output_result = {"error_message": error_msg}
        await self._state_manager.set_session_version_info(session_model)

        # 设置所有任务为失败
        await self._set_tasks_failed()

        await self._state_manager.push_message(
            MessageData(event_type=MessageEventType.ERROR_MESSAGE, data={"error": error_msg})
        )
        system_config = await settings.aget_all_config()
        # 获取Linsight_invitation_code
        linsight_invitation_code = system_config.get("linsight_invitation_code", False)
        if linsight_invitation_code:
            await InviteCodeService.revoke_invite_code(user_id=session_model.user_id)

    async def _handle_execution_error(self, error: Exception):
        """处理执行错误"""
        try:
            session_model = await LinsightSessionVersionDao.get_by_id(self.session_version_id)
            await self._handle_task_failure(session_model, str(error))
        except Exception as e:
            logger.error(f"处理执行错误失败: session_version_id={self.session_version_id}, error={e}")
