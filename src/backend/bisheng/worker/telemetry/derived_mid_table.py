from __future__ import annotations

from collections.abc import Callable

from loguru import logger

from bisheng.core.logger import trace_id_var
from bisheng.telemetry.domain.mid_table.derived_events import (
    MidActiveUserJob,
    MidDocParseDtlJob,
    MidModelCallDtlJob,
    MidSessionRunDtlJob,
    MidSessionsIncrementJob,
    MidToolCallDtlJob,
)
from bisheng.telemetry.domain.mid_table.knowledge_file_increment import MidKnowledgeFileIncrementJob
from bisheng.utils import generate_uuid
from bisheng.worker.main import bisheng_celery


def _run_one_day_job(task_name: str, job_factory: Callable):
    trace_id_var.set(f"{task_name}_{generate_uuid()}")
    logger.info("Starting telemetry task '{}'.", task_name)
    job = job_factory()
    job.add_one_day_data()
    logger.info("Finished telemetry task '{}'.", task_name)


@bisheng_celery.task()
def sync_mid_active_user():
    _run_one_day_job("sync_mid_active_user", MidActiveUserJob)


@bisheng_celery.task()
def sync_mid_doc_parse_dtl():
    _run_one_day_job("sync_mid_doc_parse_dtl", MidDocParseDtlJob)


@bisheng_celery.task()
def sync_mid_knowledge_file_increment():
    _run_one_day_job("sync_mid_knowledge_file_increment", MidKnowledgeFileIncrementJob)


@bisheng_celery.task()
def sync_mid_model_call_dtl():
    _run_one_day_job("sync_mid_model_call_dtl", MidModelCallDtlJob)


@bisheng_celery.task()
def sync_mid_sessions_increment():
    _run_one_day_job("sync_mid_sessions_increment", MidSessionsIncrementJob)


@bisheng_celery.task()
def sync_mid_tool_call_dtl():
    _run_one_day_job("sync_mid_tool_call_dtl", MidToolCallDtlJob)


@bisheng_celery.task()
def sync_mid_session_run_dtl():
    _run_one_day_job("sync_mid_session_run_dtl", MidSessionRunDtlJob)
