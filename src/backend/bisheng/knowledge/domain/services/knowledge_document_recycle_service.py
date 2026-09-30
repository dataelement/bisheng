"""管理文档及其版本、分享的可恢复生命周期。"""

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge import KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument, KnowledgeDocumentLifecycleStatus
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileEntryStatus
from bisheng.knowledge.domain.models.knowledge_recycle_item import KnowledgeRecycleItem
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_recycle_repository_impl import (
    KnowledgeDocumentRecycleRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
    KnowledgeDocumentPermissionActivationService,
)


class KnowledgeDocumentRecycleService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = KnowledgeDocumentRecycleRepositoryImpl(session)

    @staticmethod
    def _invalidate_projection(entry: KnowledgeFile) -> None:
        entry.desired_entry_generation += 1
        entry.projection_status = "pending"
        entry.projection_retry_count = 0
        entry.projection_next_retry_at = None
        entry.projection_lease_owner = None
        entry.projection_lease_until = None

    async def recycle(
        self,
        document: KnowledgeDocument,
        manager: KnowledgeFile,
        entries: Sequence[KnowledgeFile],
        *,
        actor_id: int = 0,
        actor_name: str = "system",
    ) -> None:
        _, _, versions, physical = await self.repository.load_document(int(document.id))
        if any(int(file.tenant_id or 0) != int(document.tenant_id) for file in [*entries, *physical]):
            raise ValueError("文档版本或关联入口的租户不一致, 无法安全回收")
        if not versions or len(physical) != len({version.knowledge_file_id for version in versions}):
            raise ValueError("文档版本链不完整, 无法安全回收")
        if any(entry.entry_status == "preparing" for entry in entries):
            raise ValueError("文档仍有准备中的发布或分享, 请稍后重试")
        active = [entry for entry in entries if entry.entry_status == "active"]
        active_ids = {int(entry.id) for entry in active}
        records = {int(file.id): file for file in [*physical, *active]}
        days, spaces, scopes, folders = await self.repository.snapshot_context(records.values())
        now, batch_id = datetime.now(), uuid.uuid4().hex
        version_ids = [int(version.knowledge_file_id) for version in versions]
        labels = {
            "public": "公共知识库",
            "department": "部门知识库",
            "team": "团队/科室知识库",
            "team_ks": "团队/科室知识库",
            "personal": "个人知识库",
        }
        for file in records.values():
            path = str(file.file_level_path or "")
            parent_ids = [int(part) for part in path.split("/") if part.isdigit()]
            space, scope = spaces.get(int(file.knowledge_id)), scopes.get(int(file.knowledge_id))
            level = str(getattr(scope, "value", scope or "personal"))
            rule = file.split_rule or {}
            if isinstance(rule, str):
                try:
                    rule = json.loads(rule)
                except (ValueError, TypeError):
                    rule = {}
            if not isinstance(rule, dict):
                rule = {}
            self.session.add(
                KnowledgeRecycleItem(
                    tenant_id=int(document.tenant_id),
                    file_id=int(file.id),
                    knowledge_id=int(file.knowledge_id),
                    file_type=int(file.file_type),
                    is_list_entry=file.id == manager.id,
                    display_name=file.file_name or "",
                    file_category_code=rule.get("file_category_code"),
                    file_subcategory_code=file.file_subcategory_code,
                    business_domain_code=rule.get("business_domain_code")
                    or (
                        (file.file_encoding or "").split("-")[2]
                        if len((file.file_encoding or "").split("-")) >= 3
                        else None
                    ),
                    file_encoding=file.file_encoding,
                    file_size=file.file_size,
                    md5=file.md5,
                    space_level=level,
                    space_level_label=labels.get(level, level),
                    original_knowledge_id=int(file.knowledge_id),
                    original_parent_id=parent_ids[-1] if parent_ids else None,
                    original_path="/"
                    + "/".join(
                        [
                            space.name if space else str(file.knowledge_id),
                            *[folders[pid].file_name if pid in folders else str(pid) for pid in parent_ids],
                            file.file_name or "",
                        ]
                    ),
                    original_file_level_path=path,
                    original_path_fingerprint=hashlib.sha256(path.encode()).hexdigest()[:32],
                    deleted_by=actor_id,
                    deleted_by_name=actor_name,
                    deleted_at=now,
                    expire_at=now + timedelta(days=days),
                    recycle_batch_id=batch_id,
                    recycle_root_id=int(manager.id),
                    document_id=int(document.id),
                    version_file_ids=version_ids if int(file.id) in active_ids else None,
                )
            )
            file.deleted_at = now
            self.session.add(file)
        for entry in active:
            entry.entry_status = KnowledgeFileEntryStatus.INVALID.value
            self._invalidate_projection(entry)
            self.session.add(entry)
        document.lifecycle_status = KnowledgeDocumentLifecycleStatus.RECYCLED.value
        self.session.add(document)
        await self.session.flush()

    async def _load_recycled(
        self, item: KnowledgeRecycleItem
    ) -> tuple[
        KnowledgeDocument,
        list[KnowledgeFile],
        list[KnowledgeDocumentVersion],
        list[KnowledgeFile],
        list[KnowledgeRecycleItem],
    ]:
        document, entries, versions, physical = await self.repository.load_document(int(item.document_id))
        snapshots = await self.repository.document_items(int(item.document_id))
        if (
            document is None
            or document.lifecycle_status != "recycled"
            or not any(row.id == item.id for row in snapshots)
        ):
            raise ValueError("回收条目已被还原或清理, 请刷新后重试")
        return document, entries, versions, physical, snapshots

    async def restore(
        self, item: KnowledgeRecycleItem, *, target_knowledge_id: int, target_path: str
    ) -> tuple[list[KnowledgeFile], list[int]]:
        document, entries, versions, physical, snapshots = await self._load_recycled(item)
        snapshot_ids = {int(row.file_id) for row in snapshots}
        files = {int(file.id): file for file in [*physical, *entries] if int(file.id) in snapshot_ids}
        manager = files.get(int(item.file_id))
        if (
            manager is None
            or len(files) != len(snapshot_ids)
            or {int(v.knowledge_file_id) for v in versions} != set(item.version_file_ids or [])
        ):
            raise ValueError("回收文档或版本链不完整, 无法还原")
        if await self.repository.restore_conflicts(manager, target_knowledge_id):
            raise ValueError("目标库已有同名或同内容文件, 请先移走或回收重复文件再还原")
        target = manager.model_copy(update={"knowledge_id": target_knowledge_id, "file_level_path": target_path})
        _, spaces, _, folders = await self.repository.snapshot_context([*files.values(), target])
        target_space = spaces.get(int(target_knowledge_id))
        if (
            target_space is None
            or target_space.type != KnowledgeTypeEnum.SPACE.value
            or target_space.state != KnowledgeState.PUBLISHED.value
            or int(target_space.tenant_id) != int(document.tenant_id)
        ):
            raise ValueError("目标知识库不存在、正在删除或不属于当前租户")
        target_parent_ids = [int(part) for part in target_path.split("/") if part.isdigit()]
        if any(
            pid not in folders
            or folders[pid].deleted_at is not None
            or int(folders[pid].knowledge_id) != int(target_knowledge_id)
            or folders[pid].file_type != 0
            for pid in target_parent_ids
        ):
            raise ValueError("目标目录已不存在, 无法还原")
        restorable_entry_ids = {int(row.file_id) for row in snapshots if row.version_file_ids is not None}
        file_repository = KnowledgeFileRepositoryImpl(self.session)
        # 分享仍回原位置, 原位置失效时保持整份文档可恢复, 避免静默丢失关系。
        for entry in entries:
            if entry.id not in restorable_entry_ids or entry.id == manager.id:
                continue
            space = spaces.get(int(entry.knowledge_id))
            if space is None or space.state != KnowledgeState.PUBLISHED.value:
                raise ValueError("关联分享的原知识库已不存在或正在删除, 无法还原")
            parent_ids = [int(part) for part in str(entry.file_level_path or "").split("/") if part.isdigit()]
            if any(pid not in folders or folders[pid].deleted_at is not None for pid in parent_ids):
                raise ValueError("关联分享的原目录已不存在, 无法还原")
        activation = KnowledgeDocumentPermissionActivationService(file_repository=file_repository)
        old_parent = activation.build_parent_operation(manager, action="delete")
        new_parent = activation.build_parent_operation(target, action="write")
        if old_parent.user != new_parent.user:
            # 文档尚处回收状态; 权限失败时不激活, 重试可幂等收敛。
            await activation.tuple_writer([old_parent, new_parent])
        for file in physical:
            file.knowledge_id = target_knowledge_id
            file.file_level_path = target_path
            file.level = len([part for part in target_path.split("/") if part])
        manager.knowledge_id = target_knowledge_id
        manager.file_level_path = target_path
        manager.level = len([part for part in target_path.split("/") if part])
        for file in files.values():
            file.deleted_at = None
            self.session.add(file)
        projection_ids = []
        for entry in entries:
            if entry.id in restorable_entry_ids:
                entry.entry_status = KnowledgeFileEntryStatus.ACTIVE.value
                self._invalidate_projection(entry)
                self.session.add(entry)
                projection_ids.append(int(entry.id))
        document.knowledge_id = target_knowledge_id
        document.file_level_path = target_path
        document.level = manager.level
        document.lifecycle_status = KnowledgeDocumentLifecycleStatus.ACTIVE.value
        self.session.add(document)
        await self.repository.remove_document_items(int(document.id))
        await self.session.flush()
        return list(files.values()), projection_ids

    async def purge(self, item: KnowledgeRecycleItem) -> tuple[int, list[int]]:
        document, entries, _, _, snapshots = await self._load_recycled(item)
        document.lifecycle_status = KnowledgeDocumentLifecycleStatus.DELETING.value
        self.session.add(document)
        for entry in entries:
            entry.entry_status = KnowledgeFileEntryStatus.DELETING.value
            self._invalidate_projection(entry)
            self.session.add(entry)
        await self.repository.remove_document_items(int(document.id))
        await self.session.flush()
        return len(snapshots), [int(entry.id) for entry in entries]
