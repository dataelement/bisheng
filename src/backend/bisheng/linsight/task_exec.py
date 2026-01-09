import asyncio
import os
import shutil
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, List, Dict, Callable

from langchain_core.language_models import BaseChatModel
from loguru import logger

from bisheng.api.services.invite_code.invite_code import InviteCodeService
from bisheng.api.services.linsight.workbench_impl import LinsightWorkbenchImpl
from bisheng.api.v1.schema.linsight_schema import UserInputEventSchema
from bisheng.common.services.config_service import settings
from bisheng.core.cache.utils import create_cache_folder_async, CACHE_DIR
from bisheng.core.external.http_client.http_client_manager import get_http_client
from bisheng.core.logger import trace_id_var
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models import LinsightExecuteTask
from bisheng.database.models.linsight_execute_task import LinsightExecuteTaskDao, ExecuteTaskStatusEnum, \
    ExecuteTaskTypeEnum
from bisheng.database.models.linsight_session_version import LinsightSessionVersionDao, SessionVersionStatusEnum, \
    LinsightSessionVersion
from bisheng.linsight import utils as linsight_execute_utils
from bisheng.linsight.state_message_manager import LinsightStateMessageManager, MessageData, MessageEventType
from bisheng.llm.domain.services import LLMService
from bisheng.tool.domain.services.tool import ToolServices
from bisheng_langchain.linsight.agent import LinsightAgent
from bisheng_langchain.linsight.const import TaskStatus, ExecConfig
from bisheng_langchain.linsight.event import NeedUserInput, GenerateSubTask, ExecStep, TaskStart, TaskEnd, BaseEvent


class TaskExecutionError(Exception):
    """Task Execution Exception"""
    pass


class UserTerminationError(Exception):
    """User proactively terminates exceptions"""
    pass


# Task already in progress Exception
class TaskAlreadyInProgressError(Exception):
    """Task already in progress Exception"""
    pass


class LinsightWorkflowTask:
    """Workflow Task Executor - Responsible for managing the entire mission lifecycle"""

    USER_TERMINATION_CHECK_INTERVAL = 2

    def __init__(self):
        self._state_manager: Optional[LinsightStateMessageManager] = None
        self._is_terminated = False
        self._termination_task: Optional[asyncio.Task] = None
        self._final_result: Optional[TaskEnd] = None
        self.file_dir: Optional[str] = None
        self.session_version_id: Optional[str] = None
        self.step_event_extra_files: List[Dict] = []  # File information for storing additional processing of step events
        self.llm: Optional[BaseChatModel] = None  # For storageLLMInstances

    # ==================== Resource Management ====================

    @asynccontextmanager
    async def _managed_execution(self):
        """Context manager for managing execution resources"""

        self._state_manager = LinsightStateMessageManager(self.session_version_id)
        session_model = await self._get_session_model(self.session_version_id)

        # Check session status
        if await self._is_session_in_progress(session_model):
            raise TaskAlreadyInProgressError("Task already in progress")

        try:

            # Start Termination Monitoring
            await self._start_termination_monitor(session_model)

            # Initialization file directory
            self.file_dir = await self._init_file_directory(session_model)

            yield session_model

        finally:
            await self._cleanup_resources()

    async def _cleanup_resources(self):
        """Clean up resources"""
        try:
            # Stop Terminating Monitoring
            await self._stop_termination_monitor()

            # Clean File Directory
            if self.file_dir and os.path.exists(self.file_dir):
                shutil.rmtree(self.file_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"Resource cleanup failed: {e}")

    # ==================== Core Execution Logic ====================

    async def async_run(self, session_version_id: str) -> None:
        """Asynchronous Task Execution Entry"""

        self.session_version_id = session_version_id
        trace_id_var.set(self.session_version_id)
        logger.info(f"Start the task: session_version_id={self.session_version_id}")
        try:

            async with self._managed_execution() as session_model:
                await self._execute_workflow(session_model)

        except UserTerminationError:
            logger.info(f"Task was actively terminated by the user: session_version_id={self.session_version_id}")
        except TaskAlreadyInProgressError:
            logger.warning(f"Task already in progress: session_version_id={self.session_version_id}")
        except TaskExecutionError as e:
            logger.error(f"Task execution failed:<g id='1'></g> : session_version_id={self.session_version_id}")
            await self._handle_execution_error(e)
        except Exception as e:
            logger.error(f"Unknown error: session_version_id={self.session_version_id}, error={e}")
            await self._handle_execution_error(e)

    async def _execute_workflow(self, session_model: LinsightSessionVersion):
        """Execute the core logic of the workflow"""

        # Update session status to in progress
        await self._update_session_status(session_model, SessionVersionStatusEnum.IN_PROGRESS)

        # Initialization Execution Component
        self.llm = await self._get_llm(invoke_user_id=session_model.user_id)
        tools = await self._generate_tools(session_model)
        try:
            # Build Tool List
            linsight_tools = await ToolServices.init_linsight_tools(root_path=self.file_dir)
            tools.extend(linsight_tools)
            # Create agent
            agent = await self._create_agent(session_model, tools)

            # Check if terminated during initialization
            self._check_termination()

            # Generate and save tasks
            task_info = await agent.generate_task(session_model.sop)
            await self._save_task_info(session_model, task_info)

            # Do Task
            success = await self._execute_agent_tasks(agent, task_info, session_model)
        finally:
            # Clean the sandbox of the code interpreter
            for one in tools:
                if one.name == "bisheng_code_interpreter":
                    one.close()
                    break

        if success:
            await self._handle_task_completion(session_model)
        else:
            await self._handle_user_termination(session_model)
            raise UserTerminationError("Task terminated by user")

    # ==================== Session and State Management ====================

    async def _get_session_model(self, session_version_id: str) -> LinsightSessionVersion:
        """Get session model"""
        try:
            return await LinsightSessionVersionDao.get_by_id(session_version_id)
        except Exception as e:
            raise TaskExecutionError(f"Failed to get session model: {e}")

    async def _is_session_in_progress(self, session_model: LinsightSessionVersion) -> bool:
        """Check if the session is already in progress"""
        if session_model.status == SessionVersionStatusEnum.IN_PROGRESS:
            logger.info(f"Sessions {session_model.id} Already in progress")
            return True
        return False

    async def _update_session_status(self, session_model: LinsightSessionVersion, status: SessionVersionStatusEnum):
        """Update session status"""
        session_model.status = status
        await self._state_manager.set_session_version_info(session_model)

    # ==================== Component Initialization ====================

    async def _get_llm(self, invoke_user_id: int) -> BaseChatModel:
        """DapatkanLLMInstances"""
        try:
            workbench_conf = await LLMService.get_workbench_llm()
            linsight_conf = settings.get_linsight_conf()
            return await LLMService.get_bisheng_linsight_llm(invoke_user_id=invoke_user_id,
                                                             model_id=workbench_conf.task_model.id,
                                                             temperature=linsight_conf.default_temperature)
        except Exception as e:
            raise TaskExecutionError("The task has been terminated, please contact the administrator to check the status of the Ideas task execution model")

    @create_cache_folder_async
    async def _init_file_directory(self, session_model: LinsightSessionVersion) -> str:
        """Initialization file directory"""
        file_dir = os.path.join(CACHE_DIR, "linsight", session_model.id[:8])
        file_dir = os.path.normpath(file_dir)
        os.makedirs(file_dir, exist_ok=True)

        if not session_model.files:
            return file_dir

        # Concurrent downloads
        download_tasks = [
            self._download_file(file_info, file_dir)
            for file_info in session_model.files
        ]

        results = await asyncio.gather(*download_tasks, return_exceptions=True)

        # Record Download Failed Files
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                file_name = os.path.basename(session_model.files[i]["markdown_file_path"])
                logger.error(f"This content failed to load {file_name}: {result}")

        return file_dir

    async def _download_file(self, file_info: dict, target_dir: str) -> str:
        """Download individual files"""
        object_name = file_info["markdown_file_path"]
        file_name = file_info.get("markdown_filename", os.path.basename(object_name))
        file_path = os.path.join(target_dir, file_name)
        minio_client = await get_minio_storage()
        try:
            file_url = await minio_client.get_share_link(object_name, clear_host=False)
            http_client = await get_http_client()

            with open(file_path, "wb") as f:
                async for chunk in http_client.stream(method="GET", url=str(file_url)):
                    f.write(chunk)

            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                raise ValueError(f"File download failed or empty: {object_name}")

            return file_path

        except Exception as e:
            logger.error(f"Download failed {object_name}: {e}")
            raise

    async def _generate_tools(self, session_model: LinsightSessionVersion) -> List:
        """Build Tool List"""
        if not session_model.tools:
            return []

        return await LinsightWorkbenchImpl.init_linsight_config_tools(session_version=session_model, llm=self.llm,
                                                                      need_upload=True, file_dir=self.file_dir)

    async def _create_agent(self, session_model: LinsightSessionVersion, tools: List) -> LinsightAgent:

        workbench_conf = await LLMService.get_workbench_llm()
        linsight_conf = settings.get_linsight_conf()
        exec_config = ExecConfig(**linsight_conf.model_dump(), debug_id=session_model.id)

        """Create agent"""
        return LinsightAgent(
            llm=self.llm,
            query=session_model.question,
            tools=tools,
            file_dir=self.file_dir,
            task_mode=workbench_conf.linsight_executor_mode,
            exec_config=exec_config,
        )

    # ==================== Mission Execution ====================

    async def _save_task_info(self, session_model: LinsightSessionVersion, task_info: List[dict]):
        """Save Task Information"""
        try:
            tasks = []
            # step_idIt doesn't have to be regular.step_int, FROMagentGot ittask_infoThe order is the execution order
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

            # Push Generate Task Message
            await self._state_manager.push_message(MessageData(
                event_type=MessageEventType.TASK_GENERATE,
                data={"tasks": [task.model_dump() for task in tasks]}
            ))

            logger.info(f"Set {len(tasks)} execution tasks")

        except Exception as e:
            logger.error(f"Failed to save task information: {e}")
            raise TaskExecutionError(f"Failed to save task information: {e}")

    async def _execute_agent_tasks(self, agent, task_info: List[dict],
                                   session_model) -> bool:
        """Perform agent tasks - Modified version supports user termination"""

        async def agent_execution():
            """Agent performs a task"""
            file_list = await LinsightWorkbenchImpl.prepare_file_list(session_model)
            async for event in agent.ainvoke(task_info, session_model.sop, file_list=file_list):
                await self._handle_event(agent, event, session_model)
            return True

        async def termination_monitor():
            """End monitoring task"""
            while True:
                await asyncio.sleep(0.5)  # <g id="Bold">Qn,</g>0.5Seconds checked once
                self._check_termination()

        try:
            # Create two concurrent tasks
            # Preparing user-uploaded files
            agent_task = asyncio.create_task(agent_execution())
            monitor_task = asyncio.create_task(termination_monitor())

            # Waiting for any one task to be completed
            done, pending = await asyncio.wait(
                [agent_task, monitor_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel Incomplete Task
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.debug("Successfully unsuspended task")
                    pass

            # Review completed task results
            for task in done:
                if task.exception():
                    if isinstance(task.exception(), UserTerminationError):
                        logger.info("Agent task terminated by user")
                        return False
                    else:
                        raise task.exception()
                else:
                    # If the agent task is completed normally
                    if task == agent_task:
                        logger.info("The agent task is completed normally")
                        return True

            return True

        except UserTerminationError:
            logger.info("Agent task terminated by user")
            return False
        except Exception as e:
            logger.error(f"task_exec_error {traceback.format_exc()}")
            raise TaskExecutionError(f"Agent task execution failed: {e}")

    # ==================== Event processing ====================

    async def _handle_event(self, agent: LinsightAgent, event: BaseEvent, session_model: LinsightSessionVersion):
        """handle incidents"""

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
            logger.warning(f"Unknown event type: {type(event)}")

    async def _handle_generate_subtask(self, agent: LinsightAgent, event: GenerateSubTask,
                                       session_model: LinsightSessionVersion):
        """Handle build subtask events"""
        await self._save_task_info(session_model, event.subtask)
        logger.debug(f"Generate subtasks: {event}")

    async def _handle_task_start(self, agent: LinsightAgent, event: TaskStart, session_model: LinsightSessionVersion):
        """Handle task start events"""
        task_data = await self._state_manager.update_execution_task_status(
            task_id=event.task_id,
            status=ExecuteTaskStatusEnum.IN_PROGRESS
        )

        await self._state_manager.push_message(
            MessageData(event_type=MessageEventType.TASK_START, data=task_data)
        )

    async def _handle_task_end(self, agent: LinsightAgent, event: TaskEnd, session_model: LinsightSessionVersion):
        """Handle task end events"""
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

        # Save Final Result
        self._final_result = event

    async def _handle_need_user_input(self, agent: LinsightAgent, event: NeedUserInput,
                                      session_model: LinsightSessionVersion):
        """Handle events that require user input"""
        asyncio.create_task(self._wait_for_user_input(agent, event))

    async def _handle_exec_step(self, agent: LinsightAgent, event: ExecStep, session_model: LinsightSessionVersion):
        """Handle execution step events"""

        # Additional Processing Step Events
        event = await linsight_execute_utils.handle_step_event_extra(event, self)

        await self._state_manager.add_execution_task_step(event.task_id, step=event)
        await self._state_manager.push_message(
            MessageData(event_type=MessageEventType.TASK_EXECUTE_STEP, data=event.model_dump())
        )

    async def _wait_for_user_input(self, agent: LinsightAgent, event: NeedUserInput):
        """Waiting for user input"""
        try:

            await self._state_manager.add_execution_task_step(event.task_id, step=event)

            # Update status to wait for user input
            await self._state_manager.update_execution_task_status(
                event.task_id,
                status=ExecuteTaskStatusEnum.WAITING_FOR_USER_INPUT,
            )

            # Push user input events
            await self._state_manager.push_message(
                MessageData(event_type=MessageEventType.USER_INPUT, data=event.model_dump())
            )

            # Wait for user input to complete
            task_model = await self._wait_for_input_completion(event.task_id)

            user_input_event = task_model.history[-1] if task_model.history else None
            if user_input_event is None or user_input_event.get("step_type") != "call_user_input":
                raise TaskExecutionError(f"Task {event.task_id} No user input events found while waiting for user input")

            user_input_event = UserInputEventSchema.model_validate(user_input_event)

            # Check if the user uploaded a file
            if user_input_event.files:
                # Concurrent downloads
                download_tasks = [
                    self._download_file(file_info, self.file_dir)
                    for file_info in user_input_event.files
                ]

                results = await asyncio.gather(*download_tasks, return_exceptions=True)

                # Record Download Failed Files
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        file_name = os.path.basename(user_input_event.files[i]["markdown_file_path"])
                        logger.error(f"This content failed to load {file_name}: {result}")

                user_input_event.user_input += f"\n\nUploaded File:\n" + \
                                               "\n".join([f"- {file}" for file in results if
                                                          not isinstance(file, Exception)])

            # Push Input Completion Event
            await self._state_manager.push_message(
                MessageData(event_type=MessageEventType.USER_INPUT_COMPLETED, data=task_model.model_dump())
            )

            # Resume Task
            await agent.continue_task(event.task_id, user_input_event.user_input)

        except Exception as e:
            raise TaskExecutionError(f"Failed to wait for user input task_id={event.task_id}: {e}")

    async def _wait_for_input_completion(self, task_id: str) -> Optional[LinsightExecuteTask]:
        """Wait for user input to complete"""
        while True:
            self._check_termination()

            task_model = await self._state_manager.get_execution_task(task_id)
            if task_model is None:
                raise ValueError(f"Task {task_id} Does not exist")

            if task_model.status == ExecuteTaskStatusEnum.USER_INPUT_COMPLETED:
                return task_model

            await asyncio.sleep(1)

    # ==================== Terminate Inspection ====================

    def _check_termination(self):
        """Check if terminated"""
        if self._is_terminated:
            logger.info("Termination signal detected, ready to terminate agent task")
            raise UserTerminationError("Task terminated by user")

    async def _start_termination_monitor(self, session_model: LinsightSessionVersion):
        """Start Termination Monitoring"""

        async def monitor():
            while not self._is_terminated:
                try:
                    if await self._check_user_termination():
                        self._is_terminated = True
                        break
                    await asyncio.sleep(self.USER_TERMINATION_CHECK_INTERVAL)
                except Exception as e:
                    logger.error(f"Terminate Monitoring Exception: {e}")
                    await asyncio.sleep(self.USER_TERMINATION_CHECK_INTERVAL)

        self._termination_task = asyncio.create_task(monitor())

    async def _stop_termination_monitor(self):
        """Stop Terminating Monitoring"""
        if self._termination_task and not self._termination_task.done():
            self._termination_task.cancel()
            try:
                await self._termination_task
            except asyncio.CancelledError:
                pass

    async def _check_user_termination(self) -> bool:
        """Check if the user is actively terminating"""
        if self._is_terminated:
            return True

        try:
            current_session = await self._state_manager.get_session_version_info()
            return (current_session and
                    current_session.status == SessionVersionStatusEnum.TERMINATED)
        except Exception as e:
            logger.error(f"Failed to check user termination status: {e}")
            return False

    async def _handle_user_termination(self, session_model: LinsightSessionVersion):
        """Handling user unsolicited termination"""
        logger.info(f"Handling User Termination {session_model.id}")

        session_model.status = SessionVersionStatusEnum.TERMINATED
        session_model.output_result = {"answer": "Task has been actively stopped by the user"}

        await self._state_manager.set_session_version_info(session_model)

        # Set all tasks to failed
        await self._set_tasks_failed()

        # Push termination message
        await self._state_manager.push_message(
            MessageData(
                event_type=MessageEventType.TASK_TERMINATED,
                data={
                    "message": "Task has been actively stopped by the user",
                    "session_id": session_model.id,
                    "terminated_at": datetime.now().isoformat()
                }
            )
        )

    # ==================== Task Completion Processing ====================

    async def _handle_task_completion(self, session_model: LinsightSessionVersion):
        """Processing Task Completion"""
        if not self._final_result:
            logger.error("No final task results found")
            return

        if self._final_result.status == TaskStatus.SUCCESS.value:
            await self._handle_task_success(session_model)
        else:
            await self._handle_task_failure(session_model, "Task execution failed:<g id='1'></g> ")

    async def _handle_task_success(self, session_model: LinsightSessionVersion):
        """Processing task successful"""
        try:
            # Read File Directory File Details
            file_details = await linsight_execute_utils.read_file_directory(self.file_dir)
            logger.debug(f"Read File Directory File Details: {file_details}")

            final_result_files = await linsight_execute_utils.get_final_result_file(
                session_model=session_model,
                file_details=file_details,
                answer=self._final_result.answer
            )
            execution_tasks = await self._state_manager.get_execution_tasks()
            all_from_session_files = await linsight_execute_utils.get_all_files_from_session(
                execution_tasks=execution_tasks, file_details=file_details)

            # Update session status
            session_model.status = SessionVersionStatusEnum.COMPLETED
            session_model.output_result = {
                "answer": self._final_result.answer,
                "final_files": final_result_files,
                "all_from_session_files": all_from_session_files
            }

            # Save session information and push messages
            await self._state_manager.set_session_version_info(session_model)
            await self._state_manager.push_message(
                MessageData(
                    event_type=MessageEventType.FINAL_RESULT,
                    data=session_model.model_dump()
                )
            )

            logger.info(f"Task completed successfully, processed {len(final_result_files)} files")

        except Exception as e:
            logger.error(f"An error occurred while processing the task successfully: {e}")
            raise TaskExecutionError(f"An error occurred while processing the task successfully: {e}")

    # Modify All Task Failure Processing Logic
    async def _set_tasks_failed(self):
        """Set all tasks to failed"""
        try:
            # Get All Execute Tasks
            execution_tasks = await self._state_manager.get_execution_tasks()

            for task in execution_tasks:
                # Update each task status to Terminated
                if task.status not in [ExecuteTaskStatusEnum.TERMINATED, ExecuteTaskStatusEnum.SUCCESS,
                                       ExecuteTaskStatusEnum.FAILED]:
                    await self._state_manager.update_execution_task_status(task_id=task.id,
                                                                           status=ExecuteTaskStatusEnum.TERMINATED)
        except Exception as e:
            logger.warning(f"Error setting task failed: {e}")

    async def _handle_task_failure(self, session_model: LinsightSessionVersion, error_msg: str):
        """Processing task failed"""
        session_model.status = SessionVersionStatusEnum.FAILED
        session_model.output_result = {"error_message": error_msg}
        await self._state_manager.set_session_version_info(session_model)

        # Set all tasks to failed
        await self._set_tasks_failed()

        await self._state_manager.push_message(
            MessageData(event_type=MessageEventType.ERROR_MESSAGE, data={"error": error_msg})
        )
        system_config = await settings.aget_all_config()
        # DapatkanLinsight_invitation_code
        linsight_invitation_code = system_config.get("linsight_invitation_code", False)
        if linsight_invitation_code:
            await InviteCodeService.revoke_invite_code(user_id=session_model.user_id)

    async def _handle_execution_error(self, error: Exception):
        """Processing execution error"""
        try:
            session_model = await LinsightSessionVersionDao.get_by_id(self.session_version_id)
            await self._handle_task_failure(session_model, str(error))
        except Exception as e:
            logger.error(f"Processing execution error failed: session_version_id={self.session_version_id}, error={e}")
