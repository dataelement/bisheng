"""昆联候选运行任务,只由隔离环境显式装配。"""

from asyncio import to_thread
from functools import partial

from loguru import logger

from bisheng.common.errcode.permission import (
    PermissionCheckFailedError,
    PermissionPublishNotReadyError,
    PermissionServiceUnavailableError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import (
    RunError,
    RunOutput,
    read_run_control,
    validate_interaction_input,
)
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest
from bisheng.workflow.graph.kunlian_interaction import capture_wait, prepare_thread, restore_wait
from bisheng.workflow.graph.workflow import Workflow


class ResultCallback(BaseCallback):
    def __init__(self, output_node):
        self.output_node = output_node
        self.result = None
        self.input_node = None

    def on_user_input(self, data):
        self.input_node = data.node_id

    def on_output_msg(self, data):
        if data.node_id != self.output_node or data.files or self.result is not None:
            raise RunError("INVALID_OUTPUT")
        self.result = data.msg


def build_workflow(row, user, *, node_entry_check=None):
    material = row.material
    callback = ResultCallback(material["output_node"])
    config = settings.get_workflow_conf()
    workflow = Workflow(
        workflow_id=row.workflow_id,
        user_id=user.user_id,
        workflow_data=material["graph"],
        max_steps=config.max_steps,
        timeout=config.timeout,
        callback=callback,
        tenant_id=user.tenant_id,
        redact_errors=True,
        node_entry_check=node_entry_check,
    )
    return workflow, callback


def graph_result(status, callback):
    if status != WorkflowStatus.SUCCESS.value:
        raise RunError("EXECUTION_FAILED")
    if callback.result is None:
        raise RunError("INVALID_OUTPUT")
    return RunOutput(result=callback.result).model_dump()


def execute_graph(row, user, **options):
    workflow, callback = build_workflow(row, user, **options)
    status, _ = workflow.run()
    if (
        status == WorkflowStatus.INPUT.value
        and row.material["input_node"] == callback.input_node
        and callback.input_node
    ):
        status, _ = workflow.run({callback.input_node: row.material["input"]})
    return graph_result(status, callback)


def pause_graph(row, user, **options):
    workflow, callback = build_workflow(row, user, **options)
    prepare_thread(workflow, row.session_id)
    status, _ = workflow.run()
    if status != WorkflowStatus.INPUT.value or callback.input_node != row.material["input_node"]:
        raise RunError("EXECUTION_FAILED")
    return capture_wait(workflow, row, callback.input_node)


def resume_graph(row, user, *, node_entry_check=None):
    if node_entry_check is not None:
        node_entry_check()
    try:
        material = row.material
        answer = material["answer"]
        schema = material["input_schema"]
        validate_interaction_input(schema, answer)
        if canonical_digest(answer) != material["receipt"]["answer_digest"]:
            raise RunError("RESUME_STATE_INVALID")
        workflow, callback = build_workflow(row, user, node_entry_check=node_entry_check)
        restore_wait(workflow, row, material["snapshot"])
        # 节点把文本字段的配置值用作标签,省略的答案须显式传入空文本。
        inputs = {material["input_node"]: {key: answer.get(key, "") for key in schema["properties"]}}
    except Exception as exc:
        raise RunError("RESUME_STATE_INVALID") from exc
    status, _ = workflow.run(inputs)
    return graph_result(status, callback)


async def execute_run(service, tenant_id, session_id, interaction_id=None):
    repository = service.repository
    resuming = interaction_id is not None
    with tenant_execution_scope(tenant_id):
        row = await to_thread(repository.load, tenant_id, session_id)
        if row is None or row.status != ("RESUME_QUEUED" if resuming else "QUEUED"):
            return
        if resuming and (row.material or {}).get("interaction_id") != interaction_id:
            return
        try:
            user = await service.authorize_run(row)
        except RunError as exc:
            if str(exc) != "FORBIDDEN":
                if resuming and str(exc) == "UNAVAILABLE":
                    return
                raise
            if resuming:
                await to_thread(repository.claim_resume, tenant_id, session_id, interaction_id, error="FORBIDDEN")
            else:
                await to_thread(repository.fail_before_claim, tenant_id, session_id, "FORBIDDEN")
            return
        except (PermissionCheckFailedError, PermissionPublishNotReadyError, PermissionServiceUnavailableError):
            if resuming:
                return
            raise

        if resuming:
            claim = await to_thread(repository.claim_resume, tenant_id, session_id, interaction_id)
        else:
            claim = await to_thread(repository.claim, tenant_id, session_id)
        if claim is None:
            return
        logger.info("昆联运行已领取,session_id={} version_id={}", session_id, row.workflow_version_id)
        output, error = None, None
        try:
            options = {}
            if read_run_control(row.material) is not None:
                options["node_entry_check"] = partial(
                    repository.assert_node_entry,
                    tenant_id,
                    row.connection_id,
                    session_id,
                    claim,
                    "RESUMING" if resuming else "RUNNING",
                )
            if resuming:
                output = await to_thread(resume_graph, row, user, **options)
            elif row.material.get("mode") == "interactive":
                snapshot = await to_thread(pause_graph, row, user, **options)
                stored = await to_thread(repository.wait_for_input, tenant_id, session_id, claim, snapshot)
                if stored:
                    logger.info("昆联运行等待输入,session_id={}", session_id)
                elif options and await to_thread(repository.confirm_cancel, tenant_id, session_id, claim):
                    logger.info("昆联运行确认取消,session_id={} source=worker", session_id)
                return
            else:
                output = await to_thread(execute_graph, row, user, **options)
        except RunError as exc:
            error = str(exc)
        except Exception as exc:
            error = "EXECUTION_FAILED"
            logger.warning("昆联运行执行失败,session_id={} error_type={}", session_id, type(exc).__name__)
        finish = repository.finish_resume if resuming else repository.finish
        if await to_thread(finish, tenant_id, session_id, claim, output=output, error=error):
            logger.info("昆联运行结束,session_id={} outcome={}", session_id, error or "SUCCEEDED")
        else:
            logger.info("昆联运行已过期或结束,session_id={}", session_id)


def register_task(celery_app, service):
    @celery_app.task(name="kunlian.workflow_run", shared=False)
    def run(session_id, interaction_id=None, *, phase="initial"):
        headers = getattr(getattr(run, "request", None), "headers", None) or {}
        tenant_id = headers.get("tenant_id")
        if type(tenant_id) is not int or tenant_id <= 0:
            logger.warning("昆联运行任务缺少可信租户")
            return
        if not ((phase == "initial" and interaction_id is None) or (phase == "resume" and interaction_id)):
            logger.warning("昆联运行任务阶段无效")
            return
        run_async_task(lambda: execute_run(service, tenant_id, session_id, interaction_id))

    return run


def dispatch_task(task, tenant_id, session_id, interaction_id=None):
    headers = {"tenant_id": tenant_id}
    if interaction_id is None:
        task.apply_async(args=[session_id], headers=headers)
    else:
        task.apply_async(args=[session_id, interaction_id], kwargs={"phase": "resume"}, headers=headers)
