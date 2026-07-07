import asyncio
import logging
from fastapi import Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeState
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao, KnowledgeFileStatus, FileType
from bisheng.worker.knowledge.file_worker import copy_normal
from bisheng.worker.main import bisheng_celery

_logger = logging.getLogger(__name__)
_PAGE_SIZE = 20


async def _delete_source_space(source_id: int, op_user_id: int) -> None:
    """迁移成功后删源库；传 migrate_free_space=False 跳过前置判定避免死循环。"""
    from bisheng.knowledge.domain.services.knowledge_space_service import (
        KnowledgeSpaceService,
    )
    login_user = UserPayload(user_id=op_user_id, user_name="system-worker", role="user")
    request = Request(scope={"type": "http"})
    svc = KnowledgeSpaceService(request=request, login_user=login_user)
    await svc.delete_space(source_id, migrate_free_space=False)
    _logger.info("space_migrate 源库已删除 source=%s", source_id)


def _do_migrate(source_id: int, target_id: int, op_user_id: int) -> None:
    source = KnowledgeDao.query_by_id(source_id)
    target = KnowledgeDao.query_by_id(target_id)
    existing = KnowledgeFileDao.get_file_by_condition(target_id) or []
    target_md5 = {f.md5 for f in existing if getattr(f, "md5", None)}

    migrated = 0
    dedup_skipped = 0
    dir_skipped = 0
    page = 1
    while True:
        files = KnowledgeFileDao.get_file_by_filters(
            source_id, status=[KnowledgeFileStatus.SUCCESS.value],
            page=page, page_size=_PAGE_SIZE,
        )
        if not files:
            break
        for one in files:
            if one.file_type == FileType.DIR.value:
                dir_skipped += 1
                continue
            if one.md5 and one.md5 in target_md5:
                dedup_skipped += 1
                continue
            copied = copy_normal(one, source, target, op_user_id)
            if copied is None or copied.status == KnowledgeFileStatus.FAILED.value:
                _logger.error(
                    "space_migrate copy 失败 source=%s target=%s file_id=%s（已迁 %s，将回滚）",
                    source_id, target_id, getattr(one, "id", None), migrated,
                )
                raise RuntimeError(f"copy_normal failed for source file id={getattr(one, 'id', None)}")
            migrated += 1
            _logger.info(
                "space_migrate copy ok source=%s file_id=%s → target=%s new_file_id=%s",
                source_id, getattr(one, "id", None), target_id, getattr(copied, "id", None),
            )
            if one.md5:
                target_md5.add(one.md5)
        if len(files) < _PAGE_SIZE:
            break
        page += 1
    _logger.info(
        "space_migrate 复制完成 source=%s target=%s 迁移=%s 去重跳过=%s 目录跳过=%s",
        source_id, target_id, migrated, dedup_skipped, dir_skipped,
    )


@bisheng_celery.task(acks_late=True)
def space_migrate_celery(param: dict) -> str:
    source_id = param["source_id"]
    target_id = param["target_id"]
    op_user_id = param["op_user_id"]
    _logger.info("space_migrate start source=%s target=%s", source_id, target_id)
    try:
        _do_migrate(source_id, target_id, op_user_id)
        asyncio.run(_delete_source_space(source_id, op_user_id))
        _logger.info("space_migrate done source=%s", source_id)
        return "space migrate done"
    except Exception as e:  # 回滚：源库状态恢复，保留源库
        _logger.exception("space_migrate failed source=%s: %s", source_id, e)
        KnowledgeDao.update_state(knowledge_id=source_id, state=KnowledgeState.PUBLISHED)
        return "space migrate failed"
