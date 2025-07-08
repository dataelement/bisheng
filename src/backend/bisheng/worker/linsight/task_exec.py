import asyncio
import logging
from typing import Optional, List
from uuid import UUID

from celery import Task
from langchain_core.tools import BaseTool

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.api.services.llm import LLMService
from bisheng.core.app_context import app_ctx
from bisheng.database.models import LinsightExecuteTask
from bisheng.database.models.linsight_execute_task import LinsightExecuteTaskDao, ExecuteTaskStatusEnum, \
    ExecuteTaskTypeEnum
from bisheng.database.models.linsight_session_version import LinsightSessionVersionDao, SessionVersionStatusEnum, \
    LinsightSessionVersion
from bisheng.interface.llms.custom import BishengLLM
from bisheng.utils import util
from bisheng.worker import bisheng_celery
from bisheng.worker.linsight.state_message_manager import LinsightStateMessageManager
from bisheng_langchain.linsight.agent import LinsightAgent
from bisheng_langchain.linsight.event import NeedUserInput, GenerateSubTask, ExecStep

logger = logging.getLogger(__name__)


class LinsightWorkflowTask(Task):
    name = "linsight_workflow_task"

    def __init__(self):
        super().__init__()
        self._state_message_manager: Optional[LinsightStateMessageManager] = None

    def before_start(self, task_id, args, kwargs):
        """
        任务开始前执行的初始化逻辑
        """
        pass

    @staticmethod
    def delay(linsight_session_version_id):
        """使用 Celery 异步加入任务队列"""
        return bisheng_celery.send_task(LinsightWorkflowTask.name, args=(linsight_session_version_id,))

    @staticmethod
    async def get_bisheng_llm():
        """
        获取Bisheng LLM实例
        """

        workbench_conf = await LLMService.get_workbench_llm()

        # 创建 BishengLLM
        llm = BishengLLM(model_id=workbench_conf.task_model.id)

        return llm

    @staticmethod
    async def generate_tools(session_version_model, llm):
        """
        生成工具列表
        """
        tools: List[BaseTool] = []
        # TODO: 获取工具合集
        if session_version_model.tools:
            tool_ids = []
            for tool in session_version_model.tools:
                if tool.get("children"):
                    for child in tool["children"]:
                        tool_ids.append(child.get("id"))
            tools.extend(await AssistantAgent.init_tools_by_tool_ids(tool_ids, llm=llm))

        return tools

    # 将任务信息入库
    async def save_task_info(self, session_version_model: LinsightSessionVersion, task_info: List[dict]):
        """
        保存任务信息到数据库
        """
        try:
            # 将任务信息转换为 LinsightExecuteTask 实例
            tasks = []
            for info in task_info:
                previous_task_id = None
                for t in task_info:
                    if t["id"] == info["id"]:
                        continue
                    if info["id"] in t.get("next_id", []):
                        previous_task_id = t["id"]
                        break
                task = LinsightExecuteTask(
                    id=info["id"],
                    parent_task_id=info["parent_id"] if info.get("parent_id") else None,
                    session_version_id=session_version_model.id,
                    previous_task_id=previous_task_id if previous_task_id else None,
                    next_task_id=info["next_id"][0] if info.get("next_id") else None,
                    task_type=ExecuteTaskTypeEnum.COMPOSITE if info.get("node_loop") else ExecuteTaskTypeEnum.SINGLE,
                    task_data=info
                )

                tasks.append(task)

            await LinsightExecuteTaskDao.batch_create_tasks(tasks)

            await self._state_message_manager.set_execution_task(tasks)
        except Exception as e:
            logger.error(f"Error saving task info: {str(e)}")
            raise e

    # 任务需要等待用户输入时，使用此方法
    async def task_wait_for_user_input(self, agent: LinsightAgent, event: NeedUserInput):
        """
        任务需要等待用户输入时，使用此方法
        """
        try:
            # 更新状态为等待用户输入
            await self._state_message_manager.update_execution_task_status(event.task_id,
                                                                           status=ExecuteTaskStatusEnum.WAITING_FOR_USER_INPUT,
                                                                           input_prompt=event.call_reason)
            # 循环检查任务状态是否为已输入
            while True:
                task_model = await self._state_message_manager.get_execution_task(event.task_id)
                logger.info(f"Checking task {event.task_id} status: {task_model.status}")
                if task_model is None:
                    logger.error(f"Task {event.task_id} not found.")
                    raise ValueError(f"Task {event.task_id} not found.")
                if task_model.status == ExecuteTaskStatusEnum.USER_INPUT_COMPLETED:
                    logger.info(f"User input for task {event.task_id} completed.")
                    break

                await asyncio.sleep(1)  # 每秒检查一次

            # 回调agent.continue_task
            logger.info(f"Continuing task {event.task_id} with user input: {task_model.user_input}")
            await agent.continue_task(event.task_id, task_model.user_input)

        except Exception as e:
            logger.error(f"Error waiting for user input task {event.task_id}: {str(e)}")
            raise e

    # 执行步骤事件处理
    async def handle_exec_step(self, event: ExecStep):
        """
        处理执行步骤事件
        """
        # 记录步骤
        await self._state_message_manager.set_execution_task_steps(event.task_id, event=event)

    async def async_run(self, linsight_session_version_id: UUID):
        """
        异步任务执行逻辑
        """
        try:
            # 获取会话任务
            session_version_model = await LinsightSessionVersionDao.get_by_id(linsight_session_version_id)

            # # 判断是否以在执行
            # if session_version_model.status == SessionVersionStatusEnum.IN_PROGRESS:
            #     logger.info(f"Session version {linsight_session_version_id} is already in progress.")
            #     return
            # 更新会话状态为进行中
            session_version_model.status = SessionVersionStatusEnum.IN_PROGRESS
            # 刷新session_version_info
            await self._state_message_manager.set_session_version_info(session_version_model)

            bisheng_llm = await self.get_bisheng_llm()

            tools = await self.generate_tools(session_version_model, bisheng_llm)

            agent = LinsightAgent(llm=bisheng_llm, query=session_version_model.question, tools=tools, file_dir="")

            # 生成任务
            # task_info = await agent.generate_task(session_version_model.sop)

            task_info = [
                {
                    "step_id": "step_1",
                    "description": "收集市场预测信息",
                    "profile": "市场预测收集器",
                    "target": "获取2025年苹果新品的相关新闻和博客",
                    "sop": "使用Bing搜索引擎搜索关键词'Apple new products 2025'",
                    "prompt": "请使用Bing搜索引擎搜索关键词'Apple new products 2025'，并返回相关结果。",
                    "input":
                        [
                            "query"
                        ],
                    "node_loop": False,
                    "id": "3b4bfaee0a0a4a80bde17c10a1bea57b",
                    "next_id":
                        [
                            "bb583d7c118e4e6cab01241792d099f3"
                        ]
                },
                {
                    "step_id": "step_2",
                    "description": "收集专业评测信息",
                    "profile": "专业评测收集器",
                    "target": "获取特定型号或系列的专业评测视频或文章链接",
                    "sop": "使用Bing搜索引擎搜索关键词'Apple [产品名称] 2025 review'",
                    "prompt": "请使用Bing搜索引擎搜索关键词'Apple [产品名称] 2025 review'，并返回相关结果。",
                    "input":
                        [
                            "step_1"
                        ],
                    "node_loop": True,
                    "id": "bb583d7c118e4e6cab01241792d099f3",
                    "next_id":
                        [
                            "0a59a917101f4cdeb2c20a1aa60eef82"
                        ]
                },
                {
                    "step_id": "step_3",
                    "description": "信息整合与评估",
                    "profile": "信息整合与评估",
                    "target": "根据个人偏好筛选出最有价值的信息",
                    "sop": "将从不同来源获取的所有信息汇总起来，根据个人偏好（例如预算、功能需求）进行筛选",
                    "prompt": "请根据以下信息和个人偏好（例如预算、功能需求），筛选出最有价值的信息。",
                    "input":
                        [
                            "step_2"
                        ],
                    "node_loop": False,
                    "id": "0a59a917101f4cdeb2c20a1aa60eef82",
                    "next_id":
                        [
                            "55f319b385e144e7a9856f2cad070947"
                        ]
                },
                {
                    "step_id": "step_4",
                    "description": "生成推荐清单",
                    "profile": "推荐清单生成器",
                    "target": "基于综合考量后选出几款最具吸引力的产品作为最终推荐",
                    "sop": "根据筛选后的信息，生成最终的推荐清单",
                    "prompt": "请根据以下筛选后的信息，生成最终的推荐清单。",
                    "input":
                        [
                            "step_3"
                        ],
                    "node_loop": False,
                    "id": "55f319b385e144e7a9856f2cad070947"
                }
            ]

            # 保存任务信息到数据库
            await self.save_task_info(session_version_model, task_info)

            # 执行任务
            async for event in agent.ainvoke(task_info, session_version_model.sop):

                if isinstance(event, GenerateSubTask):
                    # 保存子任务信息到数据库
                    await self.save_task_info(session_version_model, event.subtask)
                    logger.info(f"Generated sub-task: {event}")

                elif isinstance(event, NeedUserInput):
                    # 任务需要等待用户输入
                    asyncio.create_task(
                        self.task_wait_for_user_input(agent, event)
                    )

                elif isinstance(event, ExecStep):
                    # TODO: 执行步骤
                    await self.handle_exec_step(event)
                    logger.info(f"Executing : {event}")


        except Exception as e:
            logger.error(f"Error in LinsightWorkflowTask: {str(e)}")
            raise e

    def run(self, linsight_session_version_id: UUID):
        """同步 Celery 任务执行入口"""
        self._state_message_manager = LinsightStateMessageManager(linsight_session_version_id)
        util.run_async(self.async_run(linsight_session_version_id), loop=app_ctx.get_event_loop())


# 注册任务
bisheng_celery.register_task(LinsightWorkflowTask())
