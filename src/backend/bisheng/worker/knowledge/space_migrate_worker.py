import logging

from fastapi import Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeState
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
)
from bisheng.utils.async_utils import run_async_safe
from bisheng.worker.knowledge.file_worker import copy_normal
from bisheng.worker.main import bisheng_celery

_logger = logging.getLogger(__name__)
_PAGE_SIZE = 20


def _worker_request() -> Request:
    """worker 侧调用 delete_space 需要一个 ASGI Request。delete_space 的审计日志会调
    get_request_ip(request)，它读 request.headers，并在无 X-Forwarded-For/X-Real-IP 时
    读 request.client.host —— 故 scope 必须同时带 headers 与 client，否则删源库时
    starlette 会在 list(scope["headers"]) 处抛 KeyError: 'headers'，导致迁移失败。"""
    return Request(scope={"type": "http", "headers": [], "client": ("127.0.0.1", 0)})


async def _delete_source_space(source_id: int, op_user_id: int) -> None:
    """迁移成功后删源库；传 migrate_free_space=False 跳过前置判定避免死循环。"""
    from bisheng.knowledge.domain.services.knowledge_space_service import (
        KnowledgeSpaceService,
    )

    login_user = UserPayload(user_id=op_user_id, user_name="system-worker", role="user")
    svc = KnowledgeSpaceService(request=_worker_request(), login_user=login_user)
    await svc.delete_space(source_id, migrate_free_space=False)
    _logger.info("space_migrate 源库已删除 source=%s", source_id)


def _folder_path(folder: KnowledgeFile) -> str:
    return f"{folder.file_level_path or ''}/{folder.id}"


def _parent_folder_id(file_level_path: str | None) -> int | None:
    parts = [part for part in (file_level_path or "").split("/") if part]
    return int(parts[-1]) if parts else None


async def _create_target_folder(
    target_id: int,
    folder_name: str,
    op_user_id: int,
    parent_folder: KnowledgeFile | None = None,
) -> KnowledgeFile:
    """Create a target folder with inherited ReBAC access."""
    from bisheng.knowledge.domain.services.knowledge_space_service import (
        KnowledgeSpaceService,
    )

    login_user = UserPayload(user_id=op_user_id, user_name="system-worker", role="user")
    svc = KnowledgeSpaceService(request=_worker_request(), login_user=login_user)
    parent_type = "knowledge_space"
    parent_id = target_id
    level = 0
    file_level_path = ""
    if parent_folder is not None:
        parent_type = "folder"
        parent_id = int(parent_folder.id)
        level = int(parent_folder.level or 0) + 1
        file_level_path = _folder_path(parent_folder)

    folder = await KnowledgeFileDao.aadd_file(
        KnowledgeFile(
            knowledge_id=target_id,
            user_id=op_user_id,
            user_name=login_user.user_name,
            updater_id=op_user_id,
            updater_name=login_user.user_name,
            file_name=folder_name,
            file_type=FileType.DIR.value,
            level=level,
            file_level_path=file_level_path,
            status=KnowledgeFileStatus.SUCCESS.value,
        )
    )
    try:
        await svc._initialize_child_resource_permissions(
            "folder",
            int(folder.id),
            parent_type,
            parent_id,
        )
    except Exception:
        await svc._cleanup_resource_tuples([("folder", int(folder.id))])
        await KnowledgeFileDao.adelete_batch([int(folder.id)])
        raise
    return folder


def _get_or_create_target_folder(
    *,
    target_id: int,
    folder_name: str,
    target_files: list[KnowledgeFile],
    op_user_id: int,
    parent_folder: KnowledgeFile | None = None,
) -> KnowledgeFile:
    """Reuse a same-named folder under the target parent, creating it only when absent."""
    parent_path = _folder_path(parent_folder) if parent_folder is not None else ""
    for item in target_files:
        if (
            item.file_type == FileType.DIR.value
            and item.file_name == folder_name
            and (item.file_level_path or "") == parent_path
        ):
            _logger.info(
                "space_migrate 复用目标文件夹 name=%s target=%s parent_path=%s folder_id=%s",
                folder_name,
                target_id,
                parent_path,
                item.id,
            )
            return item

    folder = run_async_safe(
        _create_target_folder(target_id, folder_name, op_user_id, parent_folder),
        timeout=None,
    )
    target_files.append(folder)
    _logger.info(
        "space_migrate 创建目标文件夹 name=%s target=%s parent_path=%s folder_id=%s",
        folder_name,
        target_id,
        parent_path,
        folder.id,
    )
    return folder


def _rebuild_source_folder_tree(
    *,
    source_folders: list[KnowledgeFile],
    target_id: int,
    target_files: list[KnowledgeFile],
    migration_root: KnowledgeFile,
    op_user_id: int,
) -> dict[int, KnowledgeFile]:
    """Create or reuse the source folder tree beneath the migration root."""
    folder_map: dict[int, KnowledgeFile] = {}
    for source_folder in sorted(source_folders, key=lambda item: (int(item.level or 0), int(item.id))):
        source_parent_id = _parent_folder_id(source_folder.file_level_path)
        if source_parent_id is None:
            target_parent = migration_root
        else:
            target_parent = folder_map.get(source_parent_id)
            if target_parent is None:
                raise RuntimeError(
                    f"source folder {source_folder.id} has missing parent {source_parent_id}"
                )
        folder_map[int(source_folder.id)] = _get_or_create_target_folder(
            target_id=target_id,
            folder_name=source_folder.file_name,
            target_files=target_files,
            op_user_id=op_user_id,
            parent_folder=target_parent,
        )
    return folder_map


def _do_migrate(source_id: int, target_id: int, op_user_id: int) -> None:
    source = KnowledgeDao.query_by_id(source_id)
    target = KnowledgeDao.query_by_id(target_id)
    existing = KnowledgeFileDao.get_file_by_condition(target_id) or []
    source_items = KnowledgeFileDao.get_file_by_condition(source_id) or []
    target_md5 = {f.md5 for f in existing if getattr(f, "md5", None)}
    target_folder = _get_or_create_target_folder(
        target_id=target_id,
        folder_name=source.name,
        target_files=existing,
        op_user_id=op_user_id,
    )
    target_folder_map = _rebuild_source_folder_tree(
        source_folders=[item for item in source_items if item.file_type == FileType.DIR.value],
        target_id=target_id,
        target_files=existing,
        migration_root=target_folder,
        op_user_id=op_user_id,
    )

    migrated = 0
    dedup_skipped = 0
    dir_skipped = 0
    page = 1
    while True:
        files = KnowledgeFileDao.get_file_by_filters(
            source_id,
            status=[KnowledgeFileStatus.SUCCESS.value],
            page=page,
            page_size=_PAGE_SIZE,
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
            source_parent_id = _parent_folder_id(one.file_level_path)
            destination_folder = target_folder
            if source_parent_id is not None:
                destination_folder = target_folder_map.get(source_parent_id)
                if destination_folder is None:
                    raise RuntimeError(
                        f"source file {one.id} has missing parent folder {source_parent_id}"
                    )
            copied = copy_normal(
                one,
                source,
                target,
                op_user_id,
                target_level=int(destination_folder.level or 0) + 1,
                target_file_level_path=_folder_path(destination_folder),
            )
            if copied is None or copied.status == KnowledgeFileStatus.FAILED.value:
                _logger.error(
                    "space_migrate copy 失败 source=%s target=%s file_id=%s（已迁 %s，将回滚）",
                    source_id,
                    target_id,
                    getattr(one, "id", None),
                    migrated,
                )
                raise RuntimeError(f"copy_normal failed for source file id={getattr(one, 'id', None)}")
            migrated += 1
            _logger.info(
                "space_migrate copy ok source=%s file_id=%s → target=%s folder_id=%s new_file_id=%s",
                source_id,
                getattr(one, "id", None),
                target_id,
                destination_folder.id,
                getattr(copied, "id", None),
            )
            if one.md5:
                target_md5.add(one.md5)
        if len(files) < _PAGE_SIZE:
            break
        page += 1
    _logger.info(
        "space_migrate 复制完成 source=%s target=%s 迁移=%s 去重跳过=%s 目录跳过=%s",
        source_id,
        target_id,
        migrated,
        dedup_skipped,
        dir_skipped,
    )


@bisheng_celery.task(acks_late=True)
def space_migrate_celery(param: dict) -> str:
    source_id = param["source_id"]
    target_id = param["target_id"]
    op_user_id = param["op_user_id"]
    _logger.info("space_migrate start source=%s target=%s", source_id, target_id)
    try:
        _do_migrate(source_id, target_id, op_user_id)
        run_async_safe(_delete_source_space(source_id, op_user_id), timeout=None)
        _logger.info("space_migrate done source=%s", source_id)
        return "space migrate done"
    except Exception as e:  # 回滚：源库状态恢复，保留源库
        _logger.exception("space_migrate failed source=%s: %s", source_id, e)
        KnowledgeDao.update_state(knowledge_id=source_id, state=KnowledgeState.PUBLISHED)
        return "space migrate failed"
