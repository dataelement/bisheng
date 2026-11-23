"""Keep legacy response shapes while dispatching by the actual Knowledge type."""

from starlette.concurrency import run_in_threadpool

from bisheng.common.errcode.http_error import NotFoundError
from bisheng.knowledge.application.knowledge_deletion import get_deletion_application
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def space_deletion_service(request, identity):
    service = KnowledgeSpaceService(request=request, login_user=identity)
    service.deletion_application_factory = get_deletion_application
    return service


async def delete_legacy_resource(*, request, identity, knowledge_id, only_clear=False):
    row = await KnowledgeDao.aquery_by_id(knowledge_id)
    if row is None:
        raise NotFoundError.http_exception()
    if row.type == KnowledgeTypeEnum.SPACE.value:
        service = space_deletion_service(request, identity)
        if only_clear:
            await service.clear_space(knowledge_id)
        else:
            await service.delete_space(knowledge_id)
        return True
    # QA and retired personal/workstation types retain their original path.
    return await run_in_threadpool(
        KnowledgeService.delete_knowledge, request, identity, knowledge_id, only_clear=only_clear
    )


async def delete_legacy_files(*, request, identity, file_ids):
    ids = tuple(dict.fromkeys(file_ids))
    if not ids or any(type(ident) is not int or ident <= 0 for ident in ids):
        raise NotFoundError.http_exception()
    files = []
    for start in range(0, len(ids), 200):
        files.extend(await KnowledgeFileDao.aget_file_by_ids(list(ids[start : start + 200])))
    if not files:
        raise NotFoundError.http_exception()
    knowledge_id = files[0].knowledge_id
    root = await KnowledgeDao.aquery_by_id(knowledge_id)
    if root is None:
        raise NotFoundError.http_exception()
    if root.type != KnowledgeTypeEnum.SPACE.value:
        return await run_in_threadpool(KnowledgeService.delete_knowledge_file, request, identity, list(ids))
    if (
        {row.id for row in files} != set(ids)
        or len({row.knowledge_id for row in files}) != 1
        or any(row.file_type not in (0, 1) for row in files)
    ):
        raise NotFoundError.http_exception()
    service = space_deletion_service(request, identity)
    await service.batch_delete(
        knowledge_id,
        [row.id for row in files if row.file_type == 1],
        [row.id for row in files if row.file_type == 0],
    )
    # Preserve the legacy scheduler and audit hooks after the actual cutover.
    await run_in_threadpool(KnowledgeService._purge_files_from_scheduler, files)
    KnowledgeService.audit_telemetry_service.telemetry_delete_knowledge_file(identity)
    await run_in_threadpool(KnowledgeService.delete_knowledge_file_hook, request, identity, knowledge_id, files)
    return True
