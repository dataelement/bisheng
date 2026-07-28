"""Knowledge space recycle-bin service."""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import col, delete, select, update

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeRecycleBusinessDomainError,
    KnowledgeRecycleCrossSpaceError,
    KnowledgeRecycleFolderConflictError,
    KnowledgeRecycleForbiddenError,
    KnowledgeRecycleItemNotFoundError,
    KnowledgeRecycleOriginalPathGoneError,
    KnowledgeRecycleOverwriteRequiredError,
    KnowledgeRecycleRetentionInvalidError,
    KnowledgeRecycleTargetPathNotFoundError,
)
from bisheng.common.models.config import ConfigDao
from bisheng.common.schemas.api import PageData
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileDao
from bisheng.knowledge.domain.models.knowledge_recycle_item import KnowledgeRecycleItem
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum, KnowledgeSpaceScopeDao
from bisheng.knowledge.domain.schemas.knowledge_recycle import (
    RecycleConfigResponse,
    RecycleConfigUpdateRequest,
    RecycleConflict,
    RecycleItemResponse,
    RecyclePurgeRequest,
    RecycleRestorePreviewRequest,
    RecycleRestorePreviewResponse,
    RecycleRestoreRequest,
)

logger = logging.getLogger(__name__)

RECYCLE_RETENTION_CONFIG_KEY = "knowledge_recycle_bin.retention_days"
DEFAULT_RETENTION_DAYS = 7

_SPACE_LEVEL_LABELS = {
    KnowledgeSpaceLevelEnum.PUBLIC.value: "公共知识库",
    KnowledgeSpaceLevelEnum.DEPARTMENT.value: "部门知识库",
    KnowledgeSpaceLevelEnum.TEAM.value: "团队/科室知识库",
    KnowledgeSpaceLevelEnum.TEAM_KS.value: "团队/科室知识库",
    KnowledgeSpaceLevelEnum.PERSONAL.value: "个人知识库",
}


class KnowledgeRecycleService:
    def __init__(self, login_user: UserPayload):
        self.login_user = login_user

    def _require_admin(self) -> None:
        if not (self.login_user.is_admin() or getattr(self.login_user, "is_global_super", False)):
            raise KnowledgeRecycleForbiddenError()

    @staticmethod
    async def get_retention_days() -> int:
        row = await ConfigDao.aget_config_by_key(RECYCLE_RETENTION_CONFIG_KEY)
        if not row or not row.value:
            return DEFAULT_RETENTION_DAYS
        try:
            return max(1, min(365, int(str(row.value).strip())))
        except (TypeError, ValueError):
            return DEFAULT_RETENTION_DAYS

    async def get_config(self) -> RecycleConfigResponse:
        self._require_admin()
        days = await self.get_retention_days()
        return RecycleConfigResponse(retention_days=days)

    async def update_config(self, req: RecycleConfigUpdateRequest) -> RecycleConfigResponse:
        self._require_admin()
        if req.retention_days < 1 or req.retention_days > 365:
            raise KnowledgeRecycleRetentionInvalidError()
        await ConfigDao.insert_or_update_config(RECYCLE_RETENTION_CONFIG_KEY, str(req.retention_days))
        return RecycleConfigResponse(retention_days=req.retention_days)

    @classmethod
    async def list_recycled_file_ids(cls, knowledge_id: int) -> list[int]:
        return await cls.list_recycled_file_ids_by_knowledge_ids([knowledge_id])

    @classmethod
    async def list_recycled_file_ids_by_knowledge_ids(cls, knowledge_ids: Sequence[int]) -> list[int]:
        kids = [int(k) for k in knowledge_ids if k is not None]
        if not kids:
            return []
        async with get_async_db_session() as session:
            result = await session.execute(
                select(KnowledgeFile.id).where(
                    col(KnowledgeFile.knowledge_id).in_(kids),
                    col(KnowledgeFile.deleted_at).is_not(None),
                )
            )
            return [int(row[0]) for row in result.all()]

    async def soft_delete_file_ids(
        self,
        *,
        space_id: int,
        root_id: int,
        file_ids: Sequence[int],
        folder_ids: Sequence[int] | None = None,
        list_entry_ids: Sequence[int] | None = None,
    ) -> str:
        """Mark files/folders as recycled and write snapshot rows. Returns batch id."""
        now = datetime.now()
        retention_days = await self.get_retention_days()
        expire_at = now + timedelta(days=retention_days)
        batch_id = uuid.uuid4().hex
        folder_ids = list(folder_ids or [])
        all_ids = list(dict.fromkeys([*file_ids, *folder_ids]))
        if not all_ids:
            return batch_id

        space = await KnowledgeDao.aquery_by_id(space_id)
        space_level, space_level_label = await self._resolve_space_level(space_id)
        list_entry_set = set(list_entry_ids or [root_id])

        records = await KnowledgeFileDao.aget_file_by_ids(all_ids)
        by_id = {int(r.id): r for r in records if r}
        folder_name_map = await self._build_folder_name_map(space_id, records)
        tags_by_file = await self._snapshot_tags_by_file_ids(all_ids)

        items: list[KnowledgeRecycleItem] = []
        for fid in all_ids:
            rec = by_id.get(int(fid))
            if not rec:
                continue
            parent_id = self._parent_id_from_path(rec.file_level_path)
            original_path = self._build_display_path(space.name if space else "", rec, folder_name_map)
            fingerprint = self._path_fingerprint(rec.file_level_path)
            biz = self._extract_business_domain(rec)
            category = None
            if rec.split_rule:
                try:
                    import json

                    rule = json.loads(rec.split_rule) if isinstance(rec.split_rule, str) else rec.split_rule
                    if isinstance(rule, dict):
                        category = rule.get("file_category_code")
                        biz = biz or rule.get("business_domain_code")
                except Exception:
                    pass

            items.append(
                KnowledgeRecycleItem(
                    tenant_id=getattr(space, "tenant_id", None) or self.login_user.tenant_id,
                    file_id=int(rec.id),
                    knowledge_id=space_id,
                    file_type=self._coerce_file_type(rec.file_type),
                    is_list_entry=int(rec.id) in list_entry_set,
                    display_name=rec.file_name or "",
                    file_category_code=category,
                    file_subcategory_code=rec.file_subcategory_code,
                    business_domain_code=biz,
                    tags_snapshot=tags_by_file.get(int(rec.id), []),
                    file_encoding=rec.file_encoding,
                    file_size=rec.file_size,
                    md5=rec.md5,
                    space_level=space_level,
                    space_level_label=space_level_label,
                    original_knowledge_id=space_id,
                    original_parent_id=parent_id,
                    original_path=original_path,
                    original_file_level_path=rec.file_level_path or "",
                    original_path_fingerprint=fingerprint,
                    deleted_by=self.login_user.user_id,
                    deleted_by_name=self.login_user.user_name,
                    deleted_at=now,
                    expire_at=expire_at,
                    recycle_batch_id=batch_id,
                    recycle_root_id=root_id,
                    document_id=None,
                    version_file_ids=None,
                )
            )

        async with get_async_db_session() as session:
            await session.execute(
                update(KnowledgeFile).where(col(KnowledgeFile.id).in_(all_ids)).values(deleted_at=now)
            )
            for item in items:
                session.add(item)
            await session.commit()

        logger.info(
            "recycle soft-delete batch=%s space=%s root=%s count=%s by=%s",
            batch_id,
            space_id,
            root_id,
            len(all_ids),
            self.login_user.user_id,
        )
        return batch_id

    async def list_items(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: str | None = None,
        knowledge_id: int | None = None,
        space_level: str | None = None,
        file_type: int | None = None,
    ) -> PageData[RecycleItemResponse]:
        self._require_admin()
        async with get_async_db_session() as session:
            stmt = select(KnowledgeRecycleItem).where(KnowledgeRecycleItem.is_list_entry.is_(True))
            if knowledge_id is not None:
                stmt = stmt.where(KnowledgeRecycleItem.knowledge_id == knowledge_id)
            if file_type is not None:
                stmt = stmt.where(KnowledgeRecycleItem.file_type == file_type)
            if space_level:
                if space_level == KnowledgeSpaceLevelEnum.TEAM.value:
                    stmt = stmt.where(
                        col(KnowledgeRecycleItem.space_level).in_(
                            [KnowledgeSpaceLevelEnum.TEAM.value, KnowledgeSpaceLevelEnum.TEAM_KS.value]
                        )
                    )
                else:
                    stmt = stmt.where(KnowledgeRecycleItem.space_level == space_level)
            if keyword:
                like = f"%{keyword}%"
                stmt = stmt.where(
                    (col(KnowledgeRecycleItem.display_name).like(like))
                    | (col(KnowledgeRecycleItem.file_encoding).like(like))
                    | (col(KnowledgeRecycleItem.original_path).like(like))
                )
            count_stmt = (
                select(KnowledgeRecycleItem.id).where(stmt.whereclause)
                if stmt.whereclause is not None
                else select(KnowledgeRecycleItem.id).where(KnowledgeRecycleItem.is_list_entry.is_(True))
            )
            # simpler count
            from sqlalchemy import func

            total = (
                await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeRecycleItem)
                    .where(KnowledgeRecycleItem.is_list_entry.is_(True))
                )
                or 0
            )
            # Re-apply filters for total — rebuild
            total_stmt = (
                select(func.count())
                .select_from(KnowledgeRecycleItem)
                .where(KnowledgeRecycleItem.is_list_entry.is_(True))
            )
            if knowledge_id is not None:
                total_stmt = total_stmt.where(KnowledgeRecycleItem.knowledge_id == knowledge_id)
            if file_type is not None:
                total_stmt = total_stmt.where(KnowledgeRecycleItem.file_type == file_type)
            if space_level:
                if space_level == KnowledgeSpaceLevelEnum.TEAM.value:
                    total_stmt = total_stmt.where(
                        col(KnowledgeRecycleItem.space_level).in_(
                            [KnowledgeSpaceLevelEnum.TEAM.value, KnowledgeSpaceLevelEnum.TEAM_KS.value]
                        )
                    )
                else:
                    total_stmt = total_stmt.where(KnowledgeRecycleItem.space_level == space_level)
            if keyword:
                like = f"%{keyword}%"
                total_stmt = total_stmt.where(
                    (col(KnowledgeRecycleItem.display_name).like(like))
                    | (col(KnowledgeRecycleItem.file_encoding).like(like))
                    | (col(KnowledgeRecycleItem.original_path).like(like))
                )
            total = int(await session.scalar(total_stmt) or 0)

            stmt = stmt.order_by(col(KnowledgeRecycleItem.deleted_at).desc())
            stmt = stmt.offset(max(page - 1, 0) * page_size).limit(page_size)
            rows = (await session.execute(stmt)).scalars().all()

        data = []
        for row in rows:
            space = await KnowledgeDao.aquery_by_id(row.original_knowledge_id)
            can_original = await self._can_restore_original(row)
            data.append(
                RecycleItemResponse(
                    id=int(row.id),
                    file_id=int(row.file_id),
                    file_type=int(row.file_type),
                    name=row.display_name,
                    space_level=row.space_level,
                    space_level_label=row.space_level_label,
                    file_category=row.file_category_code,
                    file_category_code=row.file_category_code,
                    business_domain_code=row.business_domain_code,
                    tags=row.tags_snapshot or [],
                    file_encoding=row.file_encoding,
                    file_size=row.file_size,
                    deleted_by=int(row.deleted_by),
                    deleted_by_name=row.deleted_by_name,
                    deleted_at=row.deleted_at,
                    expire_at=row.expire_at,
                    original_path=row.original_path,
                    original_knowledge_id=int(row.original_knowledge_id),
                    original_knowledge_name=space.name if space else None,
                    can_restore_original=can_original,
                    children_count=0,
                )
            )
        return PageData(data=data, total=total)

    async def purge(self, req: RecyclePurgeRequest) -> dict[str, Any]:
        self._require_admin()
        async with get_async_db_session() as session:
            if req.all:
                rows = (await session.execute(select(KnowledgeRecycleItem))).scalars().all()
            else:
                if not req.item_ids:
                    return {"purged": 0}
                rows = (
                    (
                        await session.execute(
                            select(KnowledgeRecycleItem).where(col(KnowledgeRecycleItem.id).in_(req.item_ids))
                        )
                    )
                    .scalars()
                    .all()
                )

            if not rows:
                return {"purged": 0}

            batch_ids = {r.recycle_batch_id for r in rows}
            all_items = (
                (
                    await session.execute(
                        select(KnowledgeRecycleItem).where(col(KnowledgeRecycleItem.recycle_batch_id).in_(batch_ids))
                    )
                )
                .scalars()
                .all()
            )
            file_ids = [int(i.file_id) for i in all_items]
            knowledge_ids = {int(i.knowledge_id) for i in all_items}

        # Hard-delete vectors + minio + DB rows via existing celery path per knowledge
        from bisheng.worker.knowledge.file_worker import delete_knowledge_file_celery

        for kid in knowledge_ids:
            kids_files = [fid for fid, item in zip(file_ids, all_items) if int(item.knowledge_id) == kid]
            # regroup properly
            kids_files = [int(i.file_id) for i in all_items if int(i.knowledge_id) == kid]
            if not kids_files:
                continue
            delete_knowledge_file_celery.apply_async(
                kwargs={
                    "file_ids": kids_files,
                    "knowledge_id": kid,
                    "clear_minio": True,
                },
                headers={"tenant_id": int(self.login_user.tenant_id)},
            )

        async with get_async_db_session() as session:
            if file_ids:
                await session.execute(delete(KnowledgeFile).where(col(KnowledgeFile.id).in_(file_ids)))
            await session.execute(
                delete(KnowledgeRecycleItem).where(col(KnowledgeRecycleItem.recycle_batch_id).in_(batch_ids))
            )
            await session.commit()
        return {"purged": len(file_ids)}

    async def purge_expired(self) -> int:
        return await KnowledgeRecycleService.purge_expired_items()

    @classmethod
    async def purge_expired_items(cls) -> int:
        """Beat-safe expired purge (no interactive admin user required)."""
        now = datetime.now()
        async with get_async_db_session() as session:
            expired = (
                (
                    await session.execute(
                        select(KnowledgeRecycleItem).where(
                            KnowledgeRecycleItem.is_list_entry.is_(True),
                            KnowledgeRecycleItem.expire_at < now,
                        )
                    )
                )
                .scalars()
                .all()
            )
        if not expired:
            return 0
        # Use a lightweight admin-bypass path via direct purge body
        item_ids = [int(r.id) for r in expired]
        # Construct service with a stub user that passes _require_admin via monkey patch:
        # call internal purge logic without admin check by temporarily using a fake payload.
        from types import SimpleNamespace

        stub = SimpleNamespace(
            user_id=0,
            user_name="system",
            tenant_id=1,
            is_admin=lambda: True,
            is_global_super=True,
        )
        svc = cls(stub)  # type: ignore[arg-type]
        await svc.purge(RecyclePurgeRequest(item_ids=item_ids, all=False))
        return len(expired)

    async def preview_restore(self, req: RecycleRestorePreviewRequest) -> RecycleRestorePreviewResponse:
        self._require_admin()
        items = await self._load_list_items(req.item_ids)
        blockers: list[RecycleConflict] = []
        warnings: list[RecycleConflict] = []
        need_merge = False
        need_overwrite = False

        for item in items:
            target_kid, target_folder_id = await self._resolve_target(req, item)
            if target_kid is None:
                blockers.append(
                    RecycleConflict(
                        code="ORIGINAL_PATH_GONE" if req.mode == "original" else "TARGET_PATH_NOT_FOUND",
                        message="原位置已不存在，无法还原" if req.mode == "original" else "目标路径不存在",
                        item_ids=[int(item.id)],
                    )
                )
                continue

            target_space = await KnowledgeDao.aquery_by_id(target_kid)
            if not target_space or target_space.type != KnowledgeTypeEnum.SPACE.value:
                blockers.append(
                    RecycleConflict(
                        code="TARGET_PATH_NOT_FOUND",
                        message="目标路径不存在",
                        item_ids=[int(item.id)],
                    )
                )
                continue

            # Business domain
            if item.business_domain_code:
                codes = getattr(target_space, "business_domain_codes", None) or []
                if codes and item.business_domain_code not in codes:
                    blockers.append(
                        RecycleConflict(
                            code="BUSINESS_DOMAIN_MISSING",
                            message=f"目标库不存在{item.business_domain_code}业务域，请先修改以下文件的业务域：{item.display_name}",
                            item_ids=[int(item.id)],
                            conflicts=[{"name": item.display_name, "business_domain_code": item.business_domain_code}],
                        )
                    )

            target_path = await self._target_file_level_path(target_kid, target_folder_id)

            if int(item.file_type) == FileType.DIR.value:
                dup = await self._count_active_folder_name(target_kid, item.display_name, target_path)
                if dup > 0 and not req.merge_folder:
                    need_merge = True
                    warnings.append(
                        RecycleConflict(
                            code="FOLDER_NAME_CONFLICT",
                            message="存在重名文件夹，是否合并？",
                            conflicts=[{"name": item.display_name}],
                            item_ids=[int(item.id)],
                        )
                    )
                if dup > 0 and req.merge_folder:
                    file_conflicts = await self._find_file_conflicts_for_folder_merge(item, target_kid)
                    if file_conflicts and not req.overwrite_files:
                        need_overwrite = True
                        warnings.append(
                            RecycleConflict(
                                code="FILE_OVERWRITE_CONFLICT",
                                message="文件冲突，是否用回收站中的文件覆盖目标知识库已有文件？",
                                conflicts=file_conflicts,
                                item_ids=[int(item.id)],
                            )
                        )
            else:
                conflicts = await self._find_file_conflicts(
                    target_kid, item.display_name, item.md5, exclude_id=int(item.file_id)
                )
                if conflicts and not req.overwrite_files:
                    need_overwrite = True
                    warnings.append(
                        RecycleConflict(
                            code="FILE_OVERWRITE_CONFLICT",
                            message="文件冲突，是否用回收站中的文件覆盖目标知识库已有文件？",
                            conflicts=conflicts,
                            item_ids=[int(item.id)],
                        )
                    )

            # Cross-space embedding check
            if int(item.original_knowledge_id) != int(target_kid):
                source = await KnowledgeDao.aquery_by_id(item.original_knowledge_id)
                if source and target_space and getattr(source, "model", None) != getattr(target_space, "model", None):
                    blockers.append(
                        RecycleConflict(
                            code="EMBEDDING_MISMATCH",
                            message="跨空间还原失败：embedding 模型不一致",
                            item_ids=[int(item.id)],
                        )
                    )

        ok = not blockers and not need_merge and not need_overwrite
        return RecycleRestorePreviewResponse(
            ok=ok,
            blockers=blockers,
            warnings=warnings,
            need_confirm_merge=need_merge,
            need_confirm_overwrite=need_overwrite,
        )

    async def restore(self, req: RecycleRestoreRequest) -> dict[str, Any]:
        self._require_admin()
        preview = await self.preview_restore(req)
        if preview.need_confirm_merge and not req.merge_folder:
            raise KnowledgeRecycleFolderConflictError()
        if preview.need_confirm_overwrite and not req.overwrite_files:
            raise KnowledgeRecycleOverwriteRequiredError()
        if preview.blockers:
            code = preview.blockers[0].code
            if code == "ORIGINAL_PATH_GONE":
                raise KnowledgeRecycleOriginalPathGoneError()
            if code == "BUSINESS_DOMAIN_MISSING":
                raise KnowledgeRecycleBusinessDomainError(msg=preview.blockers[0].message)
            if code == "EMBEDDING_MISMATCH":
                raise KnowledgeRecycleCrossSpaceError(msg=preview.blockers[0].message)
            raise KnowledgeRecycleTargetPathNotFoundError()

        items = await self._load_list_items(req.item_ids)
        restored = 0
        for item in items:
            target_kid, target_folder_id = await self._resolve_target(req, item)
            assert target_kid is not None
            target_path = await self._target_file_level_path(target_kid, target_folder_id)
            cross = int(item.original_knowledge_id) != int(target_kid)

            batch_file_ids = await self._batch_file_ids(item.recycle_batch_id, item.recycle_root_id)

            if req.overwrite_files:
                await self._overwrite_conflicts(item, target_kid)

            # Clear soft-delete and reattach path for same-space; for cross-space update knowledge_id too
            async with get_async_db_session() as session:
                root_rec = await session.get(KnowledgeFile, int(item.file_id))
                old_root_path = (root_rec.file_level_path if root_rec else item.original_file_level_path) or ""
                old_prefix = f"{old_root_path}/{item.file_id}" if old_root_path else str(item.file_id)
                new_prefix = f"{target_path}/{item.file_id}" if target_path else str(item.file_id)

                for fid in batch_file_ids:
                    rec = await session.get(KnowledgeFile, fid)
                    if not rec:
                        continue
                    rec.deleted_at = None
                    if cross:
                        rec.knowledge_id = target_kid
                    if int(fid) == int(item.file_id):
                        rec.file_level_path = target_path
                        rec.level = target_path.count("/") if target_path else 0
                    else:
                        cur = rec.file_level_path or ""
                        if cur == old_prefix or cur.startswith(old_prefix + "/"):
                            suffix = cur[len(old_prefix) :]
                            rec.file_level_path = f"{new_prefix}{suffix}"
                            rec.level = rec.file_level_path.count("/") if rec.file_level_path else 0
                    session.add(rec)
                await session.execute(
                    delete(KnowledgeRecycleItem).where(KnowledgeRecycleItem.recycle_batch_id == item.recycle_batch_id)
                )
                await session.commit()

            if cross:
                await self._copy_vectors_cross_space(item.original_knowledge_id, target_kid, batch_file_ids)

            restored += 1

        return {"restored": restored}

    # --- helpers ---

    @staticmethod
    async def _snapshot_tags_by_file_ids(file_ids: Sequence[int]) -> dict[int, list[dict[str, Any]]]:
        """Capture approved + pending review tags before soft-delete cleanup."""
        import asyncio

        from bisheng.database.models.group_resource import ResourceTypeEnum
        from bisheng.database.models.review_tags import ReviewTagDao
        from bisheng.database.models.tag import TagDao

        resource_ids = [str(fid) for fid in file_ids]
        if not resource_ids:
            return {}
        types = [ResourceTypeEnum.SPACE_FILE]
        approved = await asyncio.to_thread(TagDao.get_tags_by_resource_batch, types, resource_ids)
        pending = await asyncio.to_thread(ReviewTagDao.get_tags_by_resource_batch, types, resource_ids)
        out: dict[int, list[dict[str, Any]]] = {}
        for rid in resource_ids:
            tags: list[dict[str, Any]] = []
            for tag in approved.get(rid, []) or []:
                tags.append({"id": getattr(tag, "id", None), "name": getattr(tag, "name", None), "status": "approved"})
            for tag in pending.get(rid, []) or []:
                tags.append(
                    {
                        "id": getattr(tag, "id", None),
                        "name": getattr(tag, "name", None),
                        "status": "pending",
                        "review_status": getattr(tag, "review_status", None),
                    }
                )
            out[int(rid)] = tags
        return out

    async def _copy_vectors_cross_space(self, source_kid: int, target_kid: int, file_ids: list[int]) -> None:
        from bisheng.api.services.knowledge_imp import delete_vector_files
        from bisheng.worker.knowledge.file_worker import copy_vector

        source = await KnowledgeDao.aquery_by_id(source_kid)
        target = await KnowledgeDao.aquery_by_id(target_kid)
        if not source or not target:
            raise KnowledgeRecycleCrossSpaceError()
        for fid in file_ids:
            try:
                copy_vector(source, target, fid, fid)
            except Exception:
                logger.exception("copy_vector failed file_id=%s", fid)
                raise KnowledgeRecycleCrossSpaceError()
        try:
            delete_vector_files(file_ids, source)
        except Exception:
            logger.exception("delete source vectors failed after cross-space restore")

    async def _load_list_items(self, item_ids: Sequence[int]) -> list[KnowledgeRecycleItem]:
        if not item_ids:
            raise KnowledgeRecycleItemNotFoundError()
        async with get_async_db_session() as session:
            rows = (
                (
                    await session.execute(
                        select(KnowledgeRecycleItem).where(
                            col(KnowledgeRecycleItem.id).in_(list(item_ids)),
                            KnowledgeRecycleItem.is_list_entry.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
        if not rows:
            raise KnowledgeRecycleItemNotFoundError()
        return list(rows)

    async def _batch_file_ids(self, batch_id: str, root_id: int) -> list[int]:
        async with get_async_db_session() as session:
            rows = (
                await session.execute(
                    select(KnowledgeRecycleItem.file_id).where(
                        KnowledgeRecycleItem.recycle_batch_id == batch_id,
                        KnowledgeRecycleItem.recycle_root_id == root_id,
                    )
                )
            ).all()
        return [int(r[0]) for r in rows]

    async def _resolve_target(
        self, req: RecycleRestorePreviewRequest, item: KnowledgeRecycleItem
    ) -> tuple[int | None, int | None]:
        if req.mode == "original":
            if not await self._can_restore_original(item):
                return None, None
            return int(item.original_knowledge_id), item.original_parent_id
        if req.target_knowledge_id is None:
            return None, None
        if req.target_folder_id is not None:
            folder = await KnowledgeFileDao.query_by_id(req.target_folder_id)
            if (
                not folder
                or folder.file_type != FileType.DIR.value
                or int(folder.knowledge_id) != int(req.target_knowledge_id)
                or folder.deleted_at is not None
            ):
                return None, None
        return int(req.target_knowledge_id), req.target_folder_id

    async def _can_restore_original(self, item: KnowledgeRecycleItem) -> bool:
        space = await KnowledgeDao.aquery_by_id(item.original_knowledge_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            return False
        if item.original_parent_id is None:
            return True
        parent = await KnowledgeFileDao.query_by_id(item.original_parent_id)
        if not parent or parent.file_type != FileType.DIR.value or parent.deleted_at is not None:
            return False
        if int(parent.knowledge_id) != int(item.original_knowledge_id):
            return False
        expected = self._path_fingerprint(item.original_file_level_path)
        # Parent chain fingerprint: original_file_level_path itself
        return expected == (item.original_path_fingerprint or expected)

    async def _target_file_level_path(self, knowledge_id: int, folder_id: int | None) -> str:
        if folder_id is None:
            return ""
        folder = await KnowledgeFileDao.query_by_id(folder_id)
        if not folder:
            return ""
        return f"{folder.file_level_path}/{folder.id}" if folder.file_level_path else f"/{folder.id}"

    async def _count_active_folder_name(self, knowledge_id: int, name: str, path: str) -> int:
        async with get_async_db_session() as session:
            from sqlalchemy import func

            return int(
                await session.scalar(
                    select(func.count(KnowledgeFile.id)).where(
                        KnowledgeFile.knowledge_id == knowledge_id,
                        KnowledgeFile.file_type == FileType.DIR.value,
                        KnowledgeFile.file_name == name,
                        KnowledgeFile.file_level_path == path,
                        col(KnowledgeFile.deleted_at).is_(None),
                    )
                )
                or 0
            )

    async def _find_file_conflicts(
        self,
        knowledge_id: int,
        name: str,
        md5: str | None,
        exclude_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Conflict scope = entire target knowledge space (name OR md5)."""
        async with get_async_db_session() as session:
            stmt = select(KnowledgeFile).where(
                KnowledgeFile.knowledge_id == knowledge_id,
                KnowledgeFile.file_type == FileType.FILE.value,
                col(KnowledgeFile.deleted_at).is_(None),
            )
            if exclude_id is not None:
                stmt = stmt.where(KnowledgeFile.id != exclude_id)
            rows = (await session.execute(stmt)).scalars().all()
        matched: list[tuple[KnowledgeFile, str]] = []
        for r in rows:
            reason = None
            if r.file_name == name:
                reason = "filename"
            elif md5 and r.md5 and r.md5 == md5:
                reason = "md5"
            if reason:
                matched.append((r, reason))
        if not matched:
            return []
        folder_name_map = await self._build_folder_name_map(knowledge_id, [r for r, _ in matched])
        return [
            {
                "name": r.file_name,
                "reason": reason,
                "target_file_id": int(r.id),
                "path": self._conflict_parent_display_path(r, folder_name_map),
            }
            for r, reason in matched
        ]

    @staticmethod
    def _conflict_parent_display_path(rec: KnowledgeFile, folder_name_map: dict[int, str]) -> str:
        segments: list[str] = []
        for part in (rec.file_level_path or "").split("/"):
            if part.isdigit():
                segments.append(folder_name_map.get(int(part), part))
        return "/" + "/".join(segments) if segments else "/"

    async def _find_file_conflicts_for_folder_merge(
        self, item: KnowledgeRecycleItem, target_kid: int
    ) -> list[dict[str, Any]]:
        # Conflict check within the whole target knowledge space
        return await self._find_file_conflicts(target_kid, item.display_name, item.md5)

    async def _overwrite_conflicts(self, item: KnowledgeRecycleItem, target_kid: int) -> None:
        conflicts = await self._find_file_conflicts(
            target_kid, item.display_name, item.md5, exclude_id=int(item.file_id)
        )
        if not conflicts:
            return
        target_ids = [int(c["target_file_id"]) for c in conflicts]
        files = await KnowledgeFileDao.aget_file_by_ids(target_ids)
        if not files:
            return

        knowledge_file_snapshots = self._build_minio_deletion_snapshots(files)
        pdf_artifact_snapshots: list[dict[str, Any]] = []
        tenant_id = getattr(self.login_user, "tenant_id", None)
        if tenant_id is not None:
            try:
                from bisheng.knowledge.domain.services.knowledge_pdf_artifact_service import (
                    get_pdf_artifact_deletion_snapshots,
                )

                snapshots = await get_pdf_artifact_deletion_snapshots(int(tenant_id), target_ids)
                pdf_artifact_snapshots = [s.to_dict() for s in snapshots]
            except Exception:
                logger.exception(
                    "overwrite conflict: failed to load pdf artifact snapshots file_ids=%s",
                    target_ids,
                )

        # Clear vectors + MinIO before removing DB rows. Snapshots are required
        # because object keys live on KnowledgeFile and would be lost after delete.
        knowledge = await KnowledgeDao.aquery_by_id(target_kid)
        if knowledge:
            import asyncio

            from bisheng.api.services.knowledge_imp import (
                delete_minio_file_snapshot_objects,
                delete_vector_files,
            )

            await asyncio.to_thread(delete_vector_files, target_ids, knowledge)
            await asyncio.to_thread(
                delete_minio_file_snapshot_objects,
                knowledge_file_snapshots,
                pdf_artifact_snapshots,
            )

        async with get_async_db_session() as session:
            await session.execute(delete(KnowledgeFile).where(col(KnowledgeFile.id).in_(target_ids)))
            await session.commit()

    @staticmethod
    def _build_minio_deletion_snapshots(files: Sequence[KnowledgeFile]) -> list[dict[str, Any]]:
        return [
            {
                "id": file.id,
                "file_name": getattr(file, "file_name", "") or "",
                "object_name": getattr(file, "object_name", None),
                "preview_file_object_name": getattr(file, "preview_file_object_name", None),
                "bbox_object_name": getattr(file, "bbox_object_name", None),
                "thumbnails": getattr(file, "thumbnails", None),
                "user_metadata": getattr(file, "user_metadata", None) or {},
            }
            for file in files
        ]

    async def _resolve_space_level(self, space_id: int) -> tuple[str, str]:
        try:
            scope = await KnowledgeSpaceScopeDao.aget_by_space_id(space_id)
            level = scope.level if scope else KnowledgeSpaceLevelEnum.PERSONAL
            value = level.value if isinstance(level, KnowledgeSpaceLevelEnum) else str(level)
        except Exception:
            value = KnowledgeSpaceLevelEnum.PERSONAL.value
        return value, _SPACE_LEVEL_LABELS.get(value, value)

    @staticmethod
    def _parent_id_from_path(path: str | None) -> int | None:
        if not path:
            return None
        parts = [p for p in path.split("/") if p]
        if not parts:
            return None
        try:
            return int(parts[-1])
        except ValueError:
            return None

    @staticmethod
    def _coerce_file_type(file_type: int | FileType | None) -> int:
        """Preserve DIR=0; only default to FILE when value is missing."""
        if file_type is None:
            return int(FileType.FILE.value)
        return int(file_type)

    @staticmethod
    def _path_fingerprint(path: str | None) -> str:
        raw = path or ""
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    async def _build_folder_name_map(self, space_id: int, records: Sequence[KnowledgeFile]) -> dict[int, str]:
        ids: set[int] = set()
        for r in records:
            for part in (r.file_level_path or "").split("/"):
                if part.isdigit():
                    ids.add(int(part))
        if not ids:
            return {}
        folders = await KnowledgeFileDao.aget_file_by_ids(list(ids))
        return {int(f.id): f.file_name for f in folders if f}

    def _build_display_path(self, space_name: str, rec: KnowledgeFile, folder_name_map: dict[int, str]) -> str:
        segments = [space_name or ""]
        for part in (rec.file_level_path or "").split("/"):
            if part.isdigit():
                segments.append(folder_name_map.get(int(part), part))
        segments.append(rec.file_name or "")
        return "/" + "/".join(s for s in segments if s)

    @staticmethod
    def _extract_business_domain(rec: KnowledgeFile) -> str | None:
        enc = rec.file_encoding or ""
        parts = enc.split("-")
        if len(parts) >= 3:
            return parts[2]
        return None
