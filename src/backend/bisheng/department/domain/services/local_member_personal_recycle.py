"""Move deleted member personal-library content into recycle bin."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import bindparam, func, select, text
from sqlmodel import col

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.constants import AdminRole
from bisheng.department.domain.services.local_member_asset_transfer import _resolve_transfer_operator
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileDao
from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao
from bisheng.knowledge.domain.services.knowledge_recycle_service import KnowledgeRecycleService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


class _LocalMemberDeleteRequest:
    state = SimpleNamespace()


@dataclass
class LocalMemberPersonalRecycleResult:
    performed: bool = False
    recycled_count: int = 0
    folder_name: str = ""
    recycle_batch_id: str | None = None
    host_space_id: int | None = None


async def _build_recycle_login_user(operator: object) -> UserPayload:
    transfer_operator = await _resolve_transfer_operator(operator)
    user_id = int(getattr(transfer_operator, "user_id", 0) or 0)
    user_name = str(getattr(transfer_operator, "user_name", "") or "")
    tenant_id = int(getattr(transfer_operator, "tenant_id", 1) or 1)
    user_role = list(getattr(transfer_operator, "user_role", None) or [])
    if AdminRole not in user_role:
        user_role = [*user_role, AdminRole]

    if user_id > 0 and not user_name.strip():
        from bisheng.user.domain.models.user import UserDao

        db_user = await UserDao.aget_user(user_id)
        if db_user is not None and getattr(db_user, "user_name", None):
            user_name = str(db_user.user_name)

    return UserPayload(
        user_id=user_id,
        user_name=user_name or "admin",
        tenant_id=tenant_id,
        user_role=user_role,
    )


async def _count_active_files(space_id: int) -> int:
    async with get_async_db_session() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(KnowledgeFile)
                .where(
                    KnowledgeFile.knowledge_id == space_id,
                    col(KnowledgeFile.deleted_at).is_(None),
                )
            )
            or 0
        )


async def _list_root_items(space_id: int) -> list[KnowledgeFile]:
    """List active root-level files/folders in a personal space."""
    items: list[KnowledgeFile] = []
    page = 1
    page_size = 500
    while True:
        batch = await SpaceFileDao.async_list_children(
            int(space_id),
            None,
            page=page,
            page_size=page_size,
        )
        if not batch:
            break
        items.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
    return items


async def _pick_host_space_id(space_ids: list[int]) -> int:
    best_id = space_ids[0]
    best_score: tuple[int, int, int] | None = None
    for space_id in space_ids:
        space = await KnowledgeDao.aquery_by_id(space_id)
        file_count = await _count_active_files(space_id)
        is_favorite = bool(getattr(space, "is_favorite", False)) if space else False
        score = (file_count, 0 if not is_favorite else -1, -int(space_id))
        if best_score is None or score > best_score:
            best_score = score
            best_id = int(space_id)
    return best_id


def _resolve_folder_name(user_name: str, user_id: int) -> str:
    cleaned = (user_name or "").strip()
    return cleaned or f"user_{user_id}"


async def _sync_recycled_file_metadata(
    *,
    file_ids: list[int],
    folder_ids: list[int],
    from_user_id: int,
    operator: UserPayload,
) -> None:
    """Align denormalized uploader/updater columns with the delete operator (admin)."""
    all_ids = list(dict.fromkeys([*file_ids, *folder_ids]))
    if not all_ids:
        return

    operator_id = int(operator.user_id)
    operator_name = str(operator.user_name or operator_id)
    stmt = text(
        "UPDATE knowledgefile SET "
        "user_id = :to_uid, "
        "user_name = :to_user_name, "
        "updater_id = :to_uid, "
        "updater_name = :to_user_name, "
        "original_uploader_id = CASE "
        "WHEN original_uploader_id IS NULL OR original_uploader_id = :from_uid "
        "THEN :to_uid ELSE original_uploader_id END "
        "WHERE id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            await session.execute(
                stmt,
                {
                    "to_uid": operator_id,
                    "to_user_name": operator_name,
                    "from_uid": int(from_user_id),
                    "ids": all_ids,
                },
            )
            await session.commit()


async def _move_root_folder_for_personal_recycle(
    *,
    space_id: int,
    folder_id: int,
    target_folder_id: int,
    login_user: UserPayload,
) -> None:
    """Move a folder subtree by path only; skips document-entry resolution."""
    folder = await KnowledgeFileDao.query_by_id(folder_id)
    if (
        folder is None
        or int(folder.knowledge_id) != int(space_id)
        or int(folder.file_type) != FileType.DIR.value
    ):
        return

    target = await KnowledgeFileDao.query_by_id(target_folder_id)
    if (
        target is None
        or int(target.knowledge_id) != int(space_id)
        or int(target.file_type) != FileType.DIR.value
    ):
        return

    old_folder_path = folder.file_level_path or ""
    old_level = int(folder.level or 0)
    old_prefix = f"{old_folder_path}/{folder_id}" if old_folder_path else f"/{folder_id}"

    target_path = target.file_level_path or ""
    if target_path == old_prefix or target_path.startswith(f"{old_prefix}/"):
        return

    new_parent_path = f"{target_path}/{target_folder_id}" if target_path else f"/{target_folder_id}"
    new_level = int(target.level or 0) + 1
    new_prefix = f"{new_parent_path}/{folder_id}" if new_parent_path else f"/{folder_id}"
    level_diff = new_level - old_level

    folder.file_level_path = new_parent_path
    folder.level = new_level
    folder.updater_id = int(login_user.user_id)
    folder.updater_name = str(login_user.user_name or login_user.user_id)
    await SpaceFileDao.update_descendants_path(
        space_id=int(space_id),
        old_prefix=old_prefix,
        new_prefix=new_prefix,
        level_diff=level_diff,
        folder=folder,
    )


async def _move_root_file_for_personal_recycle(
    *,
    space_id: int,
    file_id: int,
    target_folder_id: int,
    login_user: UserPayload,
) -> None:
    """Move a root file by path only; skips document-entry resolution."""
    file_record = await KnowledgeFileDao.query_by_id(file_id)
    if (
        file_record is None
        or int(file_record.knowledge_id) != int(space_id)
        or int(file_record.file_type) == FileType.DIR.value
    ):
        return

    target_folder = await KnowledgeFileDao.query_by_id(target_folder_id)
    if (
        target_folder is None
        or int(target_folder.knowledge_id) != int(space_id)
        or int(target_folder.file_type) != FileType.DIR.value
    ):
        return

    target_path = target_folder.file_level_path or ""
    next_file_level_path = (
        f"{target_path}/{target_folder_id}" if target_path else f"/{target_folder_id}"
    )
    file_record.file_level_path = next_file_level_path
    file_record.level = int(target_folder.level or 0) + 1
    file_record.updater_id = int(login_user.user_id)
    file_record.updater_name = str(login_user.user_name or login_user.user_id)
    await KnowledgeFileDao.async_update(file_record)


async def _collect_recycle_ids(user_folder: KnowledgeFile) -> tuple[list[int], list[int]]:
    space_id = int(user_folder.knowledge_id)
    prefix = (
        f"{user_folder.file_level_path}/{user_folder.id}"
        if user_folder.file_level_path
        else f"/{user_folder.id}"
    )
    children = await SpaceFileDao.get_children_by_prefix(space_id, prefix)
    folder_ids = [int(user_folder.id)]
    file_ids: list[int] = []
    for child in children:
        if int(child.file_type) == FileType.DIR.value:
            folder_ids.append(int(child.id))
        else:
            file_ids.append(int(child.id))
    return file_ids, folder_ids


async def recycle_local_member_personal_knowledge_spaces(
    *,
    user_id: int,
    user_name: str,
    space_ids: list[int],
    operator: object,
) -> LocalMemberPersonalRecycleResult:
    """Create a user-named folder per personal space, move content in, then recycle."""
    if not space_ids:
        return LocalMemberPersonalRecycleResult()

    folder_name = _resolve_folder_name(user_name, user_id)
    login_user = await _build_recycle_login_user(operator)
    space_service = KnowledgeSpaceService(_LocalMemberDeleteRequest(), login_user)
    recycle_service = KnowledgeRecycleService(login_user)

    host_space_id = await _pick_host_space_id(space_ids)
    host_user_folder_id: int | None = None
    all_file_ids: list[int] = []
    all_folder_ids: list[int] = []

    with bypass_tenant_filter():
        for space_id in space_ids:
            if await _count_active_files(space_id) <= 0:
                continue

            user_folder = await space_service.find_or_create_folder_for_file_sync(
                int(space_id),
                folder_name,
                parent_id=None,
            )
            if int(space_id) == host_space_id:
                host_user_folder_id = int(user_folder.id)

            root_items = await _list_root_items(space_id)
            for item in root_items:
                item_id = int(item.id)
                if item_id == int(user_folder.id):
                    continue
                if int(item.file_type) == FileType.DIR.value:
                    await _move_root_folder_for_personal_recycle(
                        space_id=int(space_id),
                        folder_id=item_id,
                        target_folder_id=int(user_folder.id),
                        login_user=login_user,
                    )
                else:
                    await _move_root_file_for_personal_recycle(
                        space_id=int(space_id),
                        file_id=item_id,
                        target_folder_id=int(user_folder.id),
                        login_user=login_user,
                    )

            file_ids, folder_ids = await _collect_recycle_ids(user_folder)
            all_file_ids.extend(file_ids)
            all_folder_ids.extend(folder_ids)

        if host_user_folder_id is None or not (all_file_ids or all_folder_ids):
            return LocalMemberPersonalRecycleResult(folder_name=folder_name)

        await _sync_recycled_file_metadata(
            file_ids=all_file_ids,
            folder_ids=all_folder_ids,
            from_user_id=user_id,
            operator=login_user,
        )

        batch_id = await recycle_service.soft_delete_member_personal_batch(
            recycle_root_id=host_user_folder_id,
            file_ids=all_file_ids,
            folder_ids=all_folder_ids,
            list_entry_ids=[host_user_folder_id],
        )

    return LocalMemberPersonalRecycleResult(
        performed=True,
        recycled_count=len(set(all_file_ids + all_folder_ids)),
        folder_name=folder_name,
        recycle_batch_id=batch_id,
        host_space_id=host_space_id,
    )
