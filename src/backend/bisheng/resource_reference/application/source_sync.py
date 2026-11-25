"""Best-effort reverse hints, scheduled only after the business commit."""

import asyncio
import json

from kombu.exceptions import KombuError
from loguru import logger
from redis.exceptions import RedisError

from bisheng.app_publish.domain.services.saved_bindings import saved_bindings
from bisheng.assistant.domain.services.reference_extractor import (
    ASSISTANT_REFERENCE_EXTRACTOR_VERSION,
    extract_assistant_references,
    unresolved_assistant_model_name,
)
from bisheng.channel.domain.services.reference_extractor import (
    CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION,
    extract_channel_sync_references,
)
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.services.model_reference_extractor import (
    KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
    knowledge_model_source_configuration,
)
from bisheng.llm.domain.services.default_reference_extractor import (
    MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
    extract_model_default_references,
)
from bisheng.resource_reference.application.contracts import SourceType
from bisheng.resource_reference.domain.repositories.reference_sync_repository import ReferenceSyncRepository
from bisheng.workflow.domain.services.reference_extractor import (
    WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
    extract_workflow_version_references,
)


def extract_snapshot(kind, source_id, row, old):
    version = row["version"]
    complete = True
    if kind == SourceType.WORKFLOW_VERSION:
        refs, extractor = extract_workflow_version_references(row["data"]), WORKFLOW_REFERENCE_EXTRACTOR_VERSION
    elif kind == SourceType.HOSTED_APP_VERSION:
        _, refs, missing = saved_bindings(
            row["capabilities"], row["injections"], tuple(value for value in old if value.source_version == version)
        )
        extractor, complete = "hosted-app-v1", not missing
    elif kind == SourceType.ASSISTANT:
        name = row["model_name"]
        unresolved = unresolved_assistant_model_name(name)
        refs = extract_assistant_references(model_name="" if unresolved else name, knowledge_ids=row["knowledge_ids"])
        extractor, complete = ASSISTANT_REFERENCE_EXTRACTOR_VERSION, not unresolved
    elif kind == SourceType.CHANNEL_SYNC:
        refs, extractor = (
            extract_channel_sync_references(row["rows"], skip_legacy_folders=True),
            CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION,
        )
    elif kind == SourceType.KNOWLEDGE:
        extractor, refs = knowledge_model_source_configuration(
            model=row["model"], model_transition=row["model_transition"], retain_legacy=True
        )
        complete = extractor == KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION
    else:
        refs, extractor = (
            extract_model_default_references(source_id, json.loads(row["value"]) if row["value"] else {}),
            MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
        )
    return version, refs, extractor, complete


async def refresh_root(tenant_id, source_type, source_id, *, session_factory=get_async_db_session, repository=None):
    if type(tenant_id) is not int or tenant_id <= 0 or not isinstance(source_id, str) or not source_id:
        raise ValueError("reference sync requires a tenant and source identity")
    kind = SourceType(source_type)
    repository = repository or ReferenceSyncRepository()
    with tenant_execution_scope(tenant_id):
        async with session_factory() as session, session.begin():
            rows = await repository.aload_root(session, tenant_id, kind, source_id)
            old, revisions = await repository.aold(session, tenant_id, kind, source_id)
            snapshots = tuple(extract_snapshot(kind, source_id, row, old) for row in rows)
            targets = await repository.atargets(session, tuple(ref for _, refs, _, _ in snapshots for ref in refs))
            result = await repository.areplace(session, tenant_id, kind, source_id, snapshots, old, revisions, targets)
    if result["skipped"]:
        logger.warning(
            "Reference sync skipped unknown owners tenant={} type={} source={} count={}",
            tenant_id,
            kind.value,
            source_id,
            result["skipped"],
        )
    return result


def notify_reference_sync_sync(tenant_id, source_type, source_id):
    if type(tenant_id) is not int or tenant_id <= 0:
        raise ValueError("reference notification requires a tenant")
    kind = SourceType(source_type)
    try:
        from bisheng.worker.main import bisheng_celery
        from bisheng.worker.resource_reference import sync_reference_root

        with bisheng_celery.connection_for_write(connect_timeout=1) as connection:
            sync_reference_root.apply_async(
                kwargs={"tenant_id": tenant_id, "source_type": kind.value, "source_id": str(source_id)},
                headers={"tenant_id": tenant_id},
                queue="celery",
                connection=connection,
                retry=True,
                retry_policy={"max_retries": 2, "interval_start": 0.2, "interval_step": 0.2, "interval_max": 1},
            )
    except (ImportError, KombuError, RedisError, OSError) as error:
        # Hints are auxiliary; the caller's business transaction already committed.
        logger.warning(
            "Reference notification failed tenant={} type={} source={} error={}",
            tenant_id,
            kind.value,
            source_id,
            type(error).__name__,
        )


async def notify_reference_sync(tenant_id, source_type, source_id):
    await asyncio.to_thread(notify_reference_sync_sync, tenant_id, source_type, source_id)


async def notify_current_source(source_type, source_id):
    await notify_reference_sync(get_current_tenant_id(), source_type, source_id)
