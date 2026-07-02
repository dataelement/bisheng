import time

from loguru import logger

from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task(
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.knowledge.space_init_worker.init_knowledge_space_indices",
)
def init_knowledge_space_indices(knowledge_id: int, invoke_user_id: int) -> str:
    start = time.perf_counter()
    logger.info(
        "knowledge_space_index_init start knowledge_id={} invoke_user_id={}",
        knowledge_id,
        invoke_user_id,
    )
    try:
        knowledge = KnowledgeDao.query_by_id(knowledge_id)
        if not knowledge:
            logger.warning("knowledge_space_index_init skipped knowledge_id={} reason=not_found", knowledge_id)
            return f"knowledge {knowledge_id} not found"

        vector_client = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
            invoke_user_id,
            knowledge=knowledge,
            metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA,
        )
        KnowledgeService.ensure_milvus_schema_ready(
            invoke_user_id=invoke_user_id,
            knowledge=knowledge,
            vector_client=vector_client,
        )

        es_client = KnowledgeRag.init_knowledge_es_vectorstore_sync(
            knowledge=knowledge,
            metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA,
        )
        es_client._store._create_index_if_not_exists()
        logger.info(
            "knowledge_space_index_init done knowledge_id={} elapsed_ms={:.2f}",
            knowledge_id,
            (time.perf_counter() - start) * 1000,
        )
        return f"knowledge {knowledge_id} indices initialized"
    except Exception:
        logger.exception(
            "knowledge_space_index_init failed knowledge_id={} elapsed_ms={:.2f}",
            knowledge_id,
            (time.perf_counter() - start) * 1000,
        )
        raise


@bisheng_celery.task(
    acks_late=True,
    time_limit=900,
    soft_time_limit=840,
    name="bisheng.worker.knowledge.space_init_worker.grant_knowledge_space_scope_permissions",
)
def grant_knowledge_space_scope_permissions(
    *,
    space_id: int,
    level: str,
    owner_id: int,
) -> str:
    return run_async_task(
        lambda: _grant_knowledge_space_scope_permissions_async(
            space_id=space_id,
            level=level,
            owner_id=owner_id,
        )
    )


async def _grant_knowledge_space_scope_permissions_async(
    *,
    space_id: int,
    level: str,
    owner_id: int,
) -> str:
    start = time.perf_counter()
    logger.info(
        "knowledge_space_scope_permission start space_id={} level={} owner_id={}",
        space_id,
        level,
        owner_id,
    )
    try:
        if level not in {
            KnowledgeSpaceLevelEnum.PUBLIC.value,
            KnowledgeSpaceLevelEnum.DEPARTMENT.value,
        }:
            logger.info(
                "knowledge_space_scope_permission skipped space_id={} level={} reason=no_default_scope_grant",
                space_id,
                level,
            )
            return f"space {space_id} has no default scope grant"

        await PermissionService.authorize(
            object_type="knowledge_space",
            object_id=str(space_id),
            grants=[
                AuthorizeGrantItem(
                    subject_type="department",
                    subject_id=int(owner_id),
                    relation="viewer",
                    include_children=True,
                )
            ],
            enforce_fga_success=True,
        )
        logger.info(
            "knowledge_space_scope_permission done space_id={} elapsed_ms={:.2f}",
            space_id,
            (time.perf_counter() - start) * 1000,
        )
        return f"space {space_id} scope permissions granted"
    except Exception:
        logger.exception(
            "knowledge_space_scope_permission failed space_id={} level={} owner_id={} elapsed_ms={:.2f}",
            space_id,
            level,
            owner_id,
            (time.perf_counter() - start) * 1000,
        )
        raise
