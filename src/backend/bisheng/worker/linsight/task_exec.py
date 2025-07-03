import asyncio
import logging
from queue import Queue as ThreadQueue
from threading import Thread
from typing import Optional, List
from uuid import UUID

from celery import Task

from bisheng.core.app_context import app_ctx
from bisheng.database.models import LinsightExecuteTask
from bisheng.database.models.linsight_execute_task import LinsightExecuteTaskDao, ExecuteTaskStatusEnum
from bisheng.database.models.linsight_session_version import LinsightSessionVersionDao, SessionVersionStatusEnum
from bisheng.utils import util
from bisheng.worker import bisheng_celery
from bisheng.worker.linsight.state_message_manager import LinsightStateMessageManager

logger = logging.getLogger(__name__)


# 任务执行器
class TaskExecutor(object):
    """
    任务执行器，用于执行具体的任务逻辑
    """

    def __init__(self, task: LinsightExecuteTask, state_message_manager: LinsightStateMessageManager,
                 queue: Optional[asyncio.Queue]):
        """
        初始化任务执行器
        :param task: 任务实例
        """
        self.task = task
        self._state_message_manager = state_message_manager
        self._queue = queue

    async def execute(self):
        """
        执行任务逻辑
        """
        try:
            # TODO: 在这里添加具体的任务执行逻辑
            pass
        except Exception as e:
            logger.error(f"Error executing task {self.task.id}: {str(e)}")
            raise e


# 任务Manager器 线程
class TaskManager(Thread):
    """
    任务管理器，用于管理和执行任务
    """

    def __init__(self, queue: ThreadQueue, state_message_manager: LinsightStateMessageManager):
        """
        初始化任务管理器
        :param queue: 可选的任务队列
        """
        super().__init__()
        self.daemon = True  # 设置为守护线程
        self._queue = queue
        self._state_message_manager = state_message_manager

    # 生成一级任务
    async def generate_one_level_tasks(self, session_version_model) -> List[LinsightExecuteTask]:
        """
        生成一级任务
        :param session_version_model: 会话版本模型
        :return: 生成的一级任务列表
        """
        sop = session_version_model.sop

        # TODO: 这里需要根据实际的SOP逻辑生成一级任务
        return []

    # 任务执行主循环
    async def async_run(self):
        """
        异步任务执行逻辑
        """
        try:
            session_version_model = await self._state_message_manager.get_session_version_info()

            # 获取所有一级任务
            one_level_tasks: List[LinsightExecuteTask] = await LinsightExecuteTaskDao.get_by_session_version_id(
                session_version_id=session_version_model.id, is_parent_task=True)

            if not one_level_tasks:
                # 如果没有一级任务，则生成一级任务
                one_level_tasks = await self.generate_one_level_tasks(session_version_model)

            for one_level_task in one_level_tasks:
                if one_level_task.status == ExecuteTaskStatusEnum.SUCCESS:
                    logger.info(f"Task {one_level_task.id} is already completed.")
                    continue
                elif one_level_task.status == ExecuteTaskStatusEnum.TERMINATED:
                    logger.info(f"Task {one_level_task.id} is terminated, skipping execution.")
                    break

                task_queue = asyncio.Queue()

                task_executor = TaskExecutor(one_level_task, state_message_manager=self._state_message_manager,
                                             queue=task_queue)

                # 执行任务
                asyncio.create_task(task_executor.execute())

                # 监听
                while True:
                    try:
                        task_data = await task_queue.get()
                        if task_data is None:
                            logger.info(f"Task {one_level_task.id} execution completed.")
                            break
                        # 处理任务数据
                        logger.info(f"Processing task data for task {one_level_task.id}: {task_data}")
                    except asyncio.CancelledError:
                        logger.info(f"Task {one_level_task.id} execution cancelled.")
                        break
                    except Exception as e:
                        logger.error(f"Error processing task {one_level_task.id}: {str(e)}")
                        break


        except Exception as e:
            logger.error(f"Error in TaskManager: {str(e)}")
            raise e

    def run(self):
        util.run_async(self.async_run(), loop=app_ctx.get_event_loop())


class LinsightWorkflowTask(Task):
    name = "linsight_workflow_task"

    def __init__(self):
        super().__init__()
        self._queue: Optional[ThreadQueue] = None
        self._state_message_manager: Optional[LinsightStateMessageManager] = None

    def before_start(self, task_id, args, kwargs):
        """
        任务开始前执行的初始化逻辑
        """

        # 创建通信队列
        self._queue = ThreadQueue()

    @staticmethod
    def delay(linsight_session_version_id):
        """使用 Celery 异步加入任务队列"""
        return bisheng_celery.send_task(LinsightWorkflowTask.name, args=(linsight_session_version_id,))

    async def async_run(self, linsight_session_version_id: UUID):
        """
        异步任务执行逻辑
        """
        try:
            # 获取会话任务
            session_version_model = await LinsightSessionVersionDao.get_by_id(linsight_session_version_id)

            # 判断是否以在执行
            if session_version_model.status == SessionVersionStatusEnum.IN_PROGRESS:
                logger.info(f"Session version {linsight_session_version_id} is already in progress.")
                return
            # 更新会话状态为进行中
            session_version_model.status = SessionVersionStatusEnum.COMPLETED
            # 刷新session_version_info
            await self._state_message_manager.set_session_version_info(session_version_model)

            # 创建任务管理器
            task_manager = TaskManager(queue=self._queue, state_message_manager=self._state_message_manager)
            # 启动任务管理器线程
            task_manager.start()

            # 监听任务
            while True:
                if not task_manager.is_alive():
                    logger.info("TaskManager thread has stopped.")
                    break
                await asyncio.sleep(1)



        except Exception as e:
            logger.error(f"Error in LinsightWorkflowTask: {str(e)}")
            raise e

    def run(self, linsight_session_version_id: UUID):
        """同步 Celery 任务执行入口"""
        self._state_message_manager = LinsightStateMessageManager(linsight_session_version_id)
        util.run_async(self.async_run(linsight_session_version_id), loop=app_ctx.get_event_loop())


# 注册任务
bisheng_celery.register_task(LinsightWorkflowTask())
