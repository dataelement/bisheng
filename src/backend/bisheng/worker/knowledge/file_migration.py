"""跨知识库迁移的异步预检、正式执行与异常恢复任务。"""

from __future__ import annotations

import asyncio
from datetime import datetime

from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_lock_repository_impl import (
    KnowledgeMigrationLockRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_operations_impl import (
    KnowledgeMigrationOperationsImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_preflight_inspector_impl import (
    KnowledgeMigrationPreflightInspectorImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_repository_context import (
    KnowledgeMigrationRepositoryContextFactoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_repository_impl import (
    KnowledgeMigrationRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_source_repository_impl import (
    KnowledgeMigrationSourceRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_migration_executor import (
    KnowledgeMigrationExecutionService,
    KnowledgeMigrationReconcileService,
)
from bisheng.knowledge.domain.services.knowledge_migration_planner import (
    KnowledgeMigrationPlannerService,
)
from bisheng.knowledge.domain.services.knowledge_migration_service import (
    CeleryKnowledgeMigrationTaskDispatcher,
)
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


async def _preflight(batch_id: int) -> None:
    stopped = asyncio.Event()
    repository_factory = KnowledgeMigrationRepositoryContextFactoryImpl()

    async def heartbeat() -> None:
        while True:
            try:
                await asyncio.wait_for(stopped.wait(), timeout=60)
                return
            except asyncio.TimeoutError:
                pass
            async with repository_factory() as repository:
                await repository.touch_preflight_batch(
                    batch_id,
                    touched_at=datetime.now(),
                )
                await repository.commit()

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        async with get_async_db_session() as session:
            service = KnowledgeMigrationPlannerService(
                repository=KnowledgeMigrationRepositoryImpl(session),
                source_repository=KnowledgeMigrationSourceRepositoryImpl(
                    session
                ),
                preflight_inspector=(
                    KnowledgeMigrationPreflightInspectorImpl()
                ),
            )
            await service.run_preflight(batch_id)
    finally:
        stopped.set()
        await heartbeat_task


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    name="bisheng.worker.knowledge.file_migration.preflight",
)
def preflight_knowledge_migration(task, batch_id: int):
    return run_async_task(lambda: _preflight(int(batch_id)))


@bisheng_celery.task(
    bind=True,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    name="bisheng.worker.knowledge.file_migration.execute",
)
def execute_knowledge_migration(
    task,
    batch_id: int,
    round_no: int,
):
    repository_factory = KnowledgeMigrationRepositoryContextFactoryImpl()
    service = KnowledgeMigrationExecutionService(
        repository_factory=repository_factory,
        lock_repository=KnowledgeMigrationLockRepositoryImpl(),
        operations=KnowledgeMigrationOperationsImpl(),
        dispatcher=CeleryKnowledgeMigrationTaskDispatcher(),
    )
    return run_async_task(
        lambda: service.execute(
            requested_batch_id=int(batch_id),
            requested_round_no=int(round_no),
            worker_task_id=str(task.request.id or ""),
        )
    )


@bisheng_celery.task(
    acks_late=True,
    name="bisheng.worker.knowledge.file_migration.reconcile",
)
def reconcile_knowledge_migrations(limit: int = 100):
    service = KnowledgeMigrationReconcileService(
        repository_factory=KnowledgeMigrationRepositoryContextFactoryImpl(),
        lock_repository=KnowledgeMigrationLockRepositoryImpl(),
        dispatcher=CeleryKnowledgeMigrationTaskDispatcher(),
    )
    return run_async_task(lambda: service.reconcile(limit=int(limit)))
