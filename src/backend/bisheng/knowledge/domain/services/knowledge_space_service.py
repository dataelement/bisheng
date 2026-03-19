import asyncio
import tempfile
from pathlib import Path
from typing import List, Optional

from fastapi import Request

from bisheng.api.v1.schemas import KnowledgeFileOne, FileProcessBase, ExcelRule
from bisheng.common.dependencies.user_deps import UserPayload  # noqa: F401 – kept for type hints
from bisheng.common.errcode.knowledge_space import (
    SpaceLimitError, SpaceNotFoundError,
    SpaceFolderNotFoundError, SpaceFolderDepthError, SpaceFolderDuplicateError,
    SpaceFileNotFoundError, SpaceFileExtensionError, SpaceFileNameDuplicateError,
    SpaceSubscribePrivateError, SpaceAlreadySubscribedError, SpaceSubscribeLimitError,
    SpacePermissionDeniedError,
)
from bisheng.common.errcode.llm import WorkbenchEmbeddingError
from bisheng.common.models.space_channel_member import (
    SpaceChannelMember, SpaceChannelMemberDao, BusinessTypeEnum, UserRoleEnum
)
from bisheng.database.models.user_group import UserGroupDao
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao, KnowledgeTypeEnum, AuthTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile, KnowledgeFileDao, KnowledgeFileStatus, SpaceFileDao
)
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils
from bisheng.llm.domain import LLMService
from bisheng.user.domain.models.user import UserDao
from bisheng.utils import generate_uuid
from bisheng.worker.knowledge import file_worker

# Maximum number of Knowledge Spaces a user can create
_MAX_SPACE_PER_USER = 30
# Maximum number of spaces a user can subscribe to (not as creator)
_MAX_SUBSCRIBE_PER_USER = 50


class KnowledgeSpaceService:
    """ Service for Knowledge Space operations.
    Instance-based; each method receives login_user as an argument.
    All business logic is async; DB access is delegated to DAO classes.
    """

    def __init__(self, request: Request, login_user: UserPayload):
        self.request = request
        self.login_user = login_user

    # ──────────────────────────── Permission helpers ───────────────────────────

    # Roles with write access to a space
    _WRITE_ROLES = {UserRoleEnum.CREATOR, UserRoleEnum.ADMIN}

    async def _require_write_permission(self, space_id: int) -> None:
        """
        Verify that the current user (self.login_user) is an active CREATOR or ADMIN
        of the given space. Raises SpacePermissionDeniedError otherwise.
        """
        role = await SpaceChannelMemberDao.async_get_active_member_role(
            space_id, self.login_user.user_id
        )
        if role not in self._WRITE_ROLES:
            raise SpacePermissionDeniedError()

    async def _require_read_permission(self, space_id: int) -> None:
        role = await SpaceChannelMemberDao.async_get_active_member_role(
            space_id, self.login_user.user_id
        )
        if not role:
            raise SpacePermissionDeniedError()

    # ──────────────────────────── Space CRUD ──────────────────────────────────

    async def create_knowledge_space(
            self,
            name: str,
            description: Optional[str] = None,
            icon: Optional[str] = None,
            auth_type: AuthTypeEnum = AuthTypeEnum.PUBLIC,
    ) -> Knowledge:
        """ Create a new knowledge space (max 30 per user). """

        count = await KnowledgeDao.async_count_spaces_by_user(self.login_user.user_id)
        if count >= _MAX_SPACE_PER_USER:
            raise SpaceLimitError()

        workbench_llm = await LLMService.get_workbench_llm()
        if not workbench_llm or not workbench_llm.embedding_model:
            raise WorkbenchEmbeddingError()

        db_knowledge = Knowledge(
            name=name,
            description=description,
            icon=icon,
            auth_type=auth_type,
            type=KnowledgeTypeEnum.SPACE.value,
            model=workbench_llm.embedding_model.id
        )

        knowledge_space = KnowledgeService.create_knowledge_base(self.request, self.login_user, db_knowledge)

        member = SpaceChannelMember(
            business_id=str(knowledge_space.id),
            business_type=BusinessTypeEnum.SPACE,
            user_id=self.login_user.user_id,
            user_role=UserRoleEnum.CREATOR,
        )
        await SpaceChannelMemberDao.async_insert_member(member)

        return knowledge_space

    async def update_knowledge_space(
            self,
            space_id: int,
            name: Optional[str] = None,
            description: Optional[str] = None,
            icon: Optional[str] = None,
            auth_type: Optional[AuthTypeEnum] = None,
    ) -> Knowledge:
        """ Modify an existing knowledge space. """
        space = await KnowledgeDao.aquery_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()

        await self._require_write_permission(space_id)

        old_auth_type = space.auth_type

        if name is not None:
            space.name = name
        if description is not None:
            space.description = description
        if icon is not None:
            space.icon = icon
        if auth_type is not None:
            space.auth_type = auth_type

        space = await KnowledgeDao.async_update_space(space)

        # When switching to PRIVATE, remove all non-creator members
        if old_auth_type != AuthTypeEnum.PRIVATE and auth_type == AuthTypeEnum.PRIVATE:
            await SpaceChannelMemberDao.async_delete_non_creator_members(space_id)

        return space

    # ──────────────────────────── Listings ────────────────────────────────────

    async def get_my_created_spaces(
            self, order_by: str = 'update_time'
    ) -> List[Knowledge]:
        return await KnowledgeDao.async_get_spaces_by_user(self.login_user.user_id, order_by)

    async def get_my_followed_spaces(
            self, order_by: str = 'update_time'
    ) -> List[Knowledge]:
        """
        Return the spaces the current user follows (non-creator).
        Pinned spaces always appear first; within each pinned/non-pinned group
        the caller-specified order_by is applied.
        """
        # Fetch members ordered by is_pinned DESC so we know which are pinned
        members = await SpaceChannelMemberDao.async_get_user_followed_members(self.login_user.user_id)
        if not members:
            return []

        # Split into pinned and non-pinned while preserving relative order
        pinned_ids = [int(m.business_id) for m in members if m.is_pinned]
        normal_ids = [int(m.business_id) for m in members if not m.is_pinned]

        # Fetch each group sorted by the caller's order_by preference
        pinned_spaces = await KnowledgeDao.async_get_spaces_by_ids(pinned_ids, order_by) if pinned_ids else []
        normal_spaces = await KnowledgeDao.async_get_spaces_by_ids(normal_ids, order_by) if normal_ids else []

        return list(pinned_spaces) + list(normal_spaces)

    async def get_knowledge_square(
            self, order_by: str = 'update_time', page: int = 1, page_size: int = 20
    ) -> dict:
        """
        Return PUBLIC/APPROVAL spaces for the Knowledge Square with pagination, sorted by:
        1. Not-joined first (easier to explore)
        2. Already-joined or pending last
        3. Within each group: sorted by update_time DESC (or caller's order_by)
        Returns: {"total": int, "page": int, "page_size": int, "data": List[dict]}
        """
        spaces = await KnowledgeDao.async_get_public_spaces(order_by)
        if not spaces:
            return {"total": 0, "page": page, "page_size": page_size, "data": []}

        all_members = await SpaceChannelMemberDao.async_get_all_members_for_spaces(
            self.login_user.user_id, [str(s.id) for s in spaces]
        )
        joined_ids = {m.business_id for m in all_members}
        pending_ids = {m.business_id for m in all_members if not m.status}

        not_joined: list = []
        already_joined: list = []
        for s in spaces:
            sid = str(s.id)
            entry = {
                "space": s,
                "is_followed": sid in joined_ids and sid not in pending_ids,
                "is_pending": sid in pending_ids,
            }
            (already_joined if sid in joined_ids else not_joined).append(entry)

        sorted_list = not_joined + already_joined
        total = len(sorted_list)
        start = (page - 1) * page_size
        paged = sorted_list[start: start + page_size]

        return {"total": total, "page": page, "page_size": page_size, "data": paged}

    # ──────────────────────────── Members ─────────────────────────────────────

    async def get_space_members(
            self, space_id: int, order_by: str = 'user_id'
    ) -> List[dict]:
        """Return space members enriched with user_name, avatar, and group info."""
        await self._require_write_permission(space_id)

        members = await SpaceChannelMemberDao.async_get_members_by_space(space_id, order_by)
        if not members:
            return []

        user_ids = [m.user_id for m in members]

        # Batch-fetch user records and group memberships in parallel
        users = await UserDao.aget_user_by_ids(user_ids)
        user_map = {u.user_id: u for u in (users or [])}
        user_groups_map = await UserGroupDao.aget_user_groups_batch(user_ids)

        result = []
        for m in members:
            user = user_map.get(m.user_id)
            groups = user_groups_map.get(m.user_id, [])
            entry = m.model_dump()
            entry['user_name'] = user.user_name if user else None
            entry['avatar'] = user.avatar if user else None
            entry['groups'] = [
                {'id': g.id, 'group_name': g.group_name} for g in groups
            ]
            result.append(entry)
        return result

    async def list_space_children(
            self,
            space_id: int,
            parent_id: Optional[int] = None,
            page: int = 1,
            page_size: int = 20,
    ) -> dict:
        """
        Return direct children (folders first, then files) under a parent folder.
        When parent_id is None, returns root-level items of the space.
        Returns: {"total": int, "page": int, "page_size": int, "data": List[KnowledgeFile]}
        """
        await self._require_read_permission(space_id)
        total, items = await asyncio.gather(
            SpaceFileDao.async_count_children(space_id, parent_id),
            SpaceFileDao.async_list_children(space_id, parent_id, page, page_size),
        )
        return {"total": total, "page": page, "page_size": page_size, "data": items}

    # ──────────────────────────── Folders ─────────────────────────────────────

    async def add_folder(
            self,
            knowledge_id: int,
            folder_name: str,
            parent_id: Optional[int] = None,
    ) -> KnowledgeFile:
        await self._require_write_permission(knowledge_id)
        level = 0
        file_level_path = ""

        if parent_id:
            parent_folder = KnowledgeFileDao.query_by_id_sync(parent_id)
            if (
                    not parent_folder
                    or parent_folder.knowledge_id != knowledge_id
                    or parent_folder.file_type != 0
            ):
                raise SpaceFolderNotFoundError()
            level = parent_folder.level + 1
            if level > 10:
                raise SpaceFolderDepthError()
            file_level_path = f"{parent_folder.file_level_path}/{parent_id}"

        if SpaceFileDao.count_folder_by_name(knowledge_id, folder_name, file_level_path) > 0:
            raise SpaceFolderDuplicateError()

        return KnowledgeFileDao.add_file(KnowledgeFile(
            knowledge_id=knowledge_id,
            user_id=self.login_user.user_id,
            user_name=self.login_user.user_name,
            updater_id=self.login_user.user_id,
            updater_name=self.login_user.user_name,
            file_name=folder_name,
            file_type=0,
            level=level,
            file_level_path=file_level_path,
            status=KnowledgeFileStatus.SUCCESS.value,
        ))

    async def rename_folder(
            self, folder_id: int, new_name: str
    ) -> KnowledgeFile:
        folder = KnowledgeFileDao.query_by_id_sync(folder_id)
        if not folder or folder.file_type != 0:
            raise SpaceFolderNotFoundError()

        await self._require_write_permission(folder.knowledge_id)

        if SpaceFileDao.count_folder_by_name(
                folder.knowledge_id, new_name, folder.file_level_path, exclude_id=folder_id
        ) > 0:
            raise SpaceFolderDuplicateError()

        folder.file_name = new_name
        return KnowledgeFileDao.update(folder)

    async def delete_folder(self, space_id: int, folder_id: int):
        from bisheng.worker.knowledge.file_worker import delete_knowledge_file_celery

        folder = KnowledgeFileDao.query_by_id_sync(folder_id)
        if not folder or folder.file_type != 0:
            raise SpaceFolderNotFoundError()

        await self._require_write_permission(space_id)

        prefix = f"{folder.file_level_path}/{folder.id}"
        children = SpaceFileDao.get_children_by_prefix(folder.knowledge_id, prefix)
        floder_ids = [folder_id]
        file_ids = []
        for child in children:
            if child.file_name == 0:
                floder_ids.append(child.id)
            else:
                file_ids.append(child.id)

        if file_ids:
            delete_knowledge_file_celery.delay(file_ids=file_ids, knowledge_id=folder.knowledge_id, clear_minio=True)
        await KnowledgeFileDao.adelete_batch(file_ids + floder_ids)

    # ──────────────────────────── Files ───────────────────────────────────────

    async def add_file(
            self,
            knowledge_id: int,
            file_path: List[str],
            parent_id: Optional[int] = None,
    ) -> List[KnowledgeFile]:
        await self._require_write_permission(knowledge_id)

        db_knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
        if not db_knowledge:
            raise SpaceFolderNotFoundError()

        level = 0
        file_level_path = ""

        if parent_id:
            parent_folder = KnowledgeFileDao.query_by_id_sync(parent_id)
            if (
                    not parent_folder
                    or parent_folder.knowledge_id != knowledge_id
                    or parent_folder.file_type != 0
            ):
                raise SpaceFolderNotFoundError()
            level = parent_folder.level + 1
            file_level_path = f"{parent_folder.file_level_path}/{parent_id}"

        # todo max file size limit
        file_split_rule = FileProcessBase(knowledge_id=knowledge_id)
        process_files = []
        failed_files = []
        preview_cache_keys = []
        for one in file_path:
            db_file = KnowledgeService.process_one_file(self.login_user, knowledge=db_knowledge,
                                                        file_info=KnowledgeFileOne(
                                                            file_path=one,
                                                            excel_rule=ExcelRule()
                                                        ), split_rule=file_split_rule.model_dump(),
                                                        file_kwargs={"level": level,
                                                                     "file_level_path": file_level_path}, )
            if db_file.status != KnowledgeFileStatus.FAILED.value:
                # Get a preview cache of this filekey
                cache_key = KnowledgeUtils.get_preview_cache_key(
                    knowledge_id, one
                )
                preview_cache_keys.append(cache_key)
                process_files.append(db_file)
            else:
                failed_file_info = db_file.model_dump()
                failed_file_info["file_path"] = one
                failed_files.append(failed_file_info)
        for index, one in enumerate(process_files):
            file_worker.parse_knowledge_file_celery.delay(one.id, preview_cache_keys[index])
        return failed_files + process_files

    async def rename_file(
            self, file_id: int, new_name: str
    ) -> KnowledgeFile:
        file_record = KnowledgeFileDao.query_by_id_sync(file_id)
        if not file_record or file_record.file_type != 1:
            raise SpaceFileNotFoundError()

        await self._require_write_permission(file_record.knowledge_id)

        old_suffix = file_record.file_name.rsplit('.', 1)[-1] if '.' in file_record.file_name else ''
        new_suffix = new_name.rsplit('.', 1)[-1] if '.' in new_name else ''
        if old_suffix != new_suffix:
            raise SpaceFileExtensionError()

        if SpaceFileDao.count_file_by_name(file_record.knowledge_id, new_name, exclude_id=file_id) > 0:
            raise SpaceFileNameDuplicateError()

        file_record.file_name = new_name
        updated_file = KnowledgeFileDao.update(file_record)

        if updated_file.status == KnowledgeFileStatus.SUCCESS.value:
            # TODO: Rebuild chunks metadata and update vector store
            pass

        return updated_file

    async def delete_file(self, file_id: int):
        from bisheng.worker.knowledge.file_worker import delete_knowledge_file_celery

        file_record = KnowledgeFileDao.query_by_id_sync(file_id)
        if not file_record or file_record.file_type != 1:
            raise SpaceFileNotFoundError()

        await self._require_write_permission(file_record.knowledge_id)

        KnowledgeFileDao.delete_batch([file_id])
        delete_knowledge_file_celery.delay(file_ids=[file_id], knowledge_id=file_record.knowledge_id, clear_minio=True)

    async def get_file_preview(self, file_id: int) -> dict:
        file_record = await KnowledgeFileDao.query_by_id(file_id)
        if not file_record or file_record.file_type != 1:
            raise SpaceFileNotFoundError()

        await self._require_read_permission(file_record.knowledge_id)

        original_url, preview_url = KnowledgeService.get_file_share_url(file_id)

        return {
            "original_url": original_url,
            "preview_url": preview_url,
        }

    # ──────────────────────────── Batch Ops ───────────────────────────────────

    async def batch_delete(
            self, knowledge_id: int, file_ids: List[int], folder_ids: List[int]
    ):
        from bisheng.worker.knowledge.file_worker import delete_knowledge_file_celery

        knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
        if not knowledge:
            raise SpaceNotFoundError()

        await self._require_write_permission(knowledge_id)

        for folder_id in folder_ids:
            folder = KnowledgeFileDao.query_by_id_sync(folder_id)
            if folder and folder.file_type == 0:
                await self.delete_folder(knowledge.id, folder_id)

        if file_ids:
            KnowledgeFileDao.delete_batch(file_ids)
            delete_knowledge_file_celery.delay(file_ids=file_ids, knowledge_id=knowledge.id,
                                               clear_minio=True)

    async def batch_download(
            self, space_id: int, file_ids: List[int], folder_ids: List[int]
    ) -> str:
        """
        Download selected files and folders, preserving the original directory structure,
        compress into a zip archive, upload to the MinIO tmp bucket, and return a
        presigned URL (valid for 7 days).

        Directory structure is reconstructed from file_level_path (e.g. '/7/42') by
        resolving each segment id to the corresponding folder name.
        """
        await self._require_read_permission(space_id)

        # ── 1. Collect all file records to include ────────────────────────────
        # Explicit files requested directly
        direct_files: List[KnowledgeFile] = KnowledgeFileDao.get_file_by_ids(file_ids) if file_ids else []

        # Files & sub-folders under every requested folder_id
        folder_db_records: List[KnowledgeFile] = []
        for folder_id in folder_ids:
            folder = KnowledgeFileDao.query_by_id_sync(folder_id)
            if not folder or folder.file_type != 0:
                continue
            prefix = f"{folder.file_level_path}/{folder.id}"
            descendants = SpaceFileDao.get_children_by_prefix(folder.knowledge_id, prefix)
            folder_db_records.append(folder)
            folder_db_records.extend(descendants)

        # All KnowledgeFile objects this download touches
        all_records: List[KnowledgeFile] = direct_files + folder_db_records

        # ── 2. Build id→name map for every folder encountered ─────────────────
        #       We need this to translate '/7/42' → 'Reports/Q1'
        folder_id_to_name: dict[int, str] = {}
        for rec in all_records:
            if rec.file_type == 0:
                folder_id_to_name[rec.id] = rec.file_name

        # Collect any ancestor folder IDs referenced in file_level_path but not yet known
        missing_ids: set[int] = set()
        for rec in all_records:
            if not rec.file_level_path:
                continue
            for part in rec.file_level_path.split('/'):
                if not part:
                    continue
                try:
                    fid = int(part)
                    if fid not in folder_id_to_name:
                        missing_ids.add(fid)
                except ValueError:
                    pass

        if missing_ids:
            extra_folders = KnowledgeFileDao.get_file_by_ids(list(missing_ids))
            for f in extra_folders:
                if f.file_type == 0:
                    folder_id_to_name[f.id] = f.file_name

        def resolve_dir_path(file_level_path: Optional[str]) -> str:
            """Convert '/7/42' to 'FolderA/SubFolderB' using the name map."""
            if not file_level_path:
                return ''
            parts = [p for p in file_level_path.split('/') if p]
            names = []
            for part in parts:
                try:
                    fid = int(part)
                    names.append(folder_id_to_name.get(fid, str(fid)))
                except ValueError:
                    names.append(part)
            return '/'.join(names)

        # ── 3. Download files from MinIO and write into a temp dir ────────────
        from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
        minio = get_minio_storage_sync()

        import os
        import zipfile
        from datetime import datetime

        with tempfile.TemporaryDirectory() as tmp_dir:
            for rec in all_records:
                if rec.file_type != 1:  # skip folders
                    continue
                if not rec.object_name:  # no stored object – skip
                    continue

                rel_dir = resolve_dir_path(rec.file_level_path)
                local_dir = os.path.join(tmp_dir, rel_dir) if rel_dir else tmp_dir
                os.makedirs(local_dir, exist_ok=True)
                local_path = os.path.join(local_dir, rec.file_name)

                try:
                    response = minio.download_object_sync(object_name=rec.object_name)
                    with open(local_path, 'wb') as f:
                        for one in response.stream(65536):
                            f.write(one)
                except Exception:
                    # Skip files that cannot be fetched (e.g. not yet parsed)
                    continue
                finally:
                    response.close()
                    response.release_conn()

            # ── 4. Create zip archive ─────────────────────────────────────────
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            zip_folder = generate_uuid()
            zip_name = f"{timestamp}_{zip_folder[:6]}.zip"
            zip_path = os.path.join(tmp_dir, zip_name)

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(tmp_dir):
                    for filename in files:
                        if filename == zip_name:
                            continue  # don't zip the zip itself
                        full_path = os.path.join(root, filename)
                        arcname = os.path.relpath(full_path, tmp_dir)
                        zf.write(full_path, arcname)

            # ── 5. Upload zip to MinIO tmp bucket & return presigned URL ──────
            minio_object_name = f"download/{zip_folder}/{zip_name}"
            await minio.put_object_tmp(minio_object_name, Path(zip_path), content_type='application/zip')
            share_url = await minio.get_share_link(minio_object_name, bucket=minio.tmp_bucket, clear_host=True,
                                                   expire_days=7)

        return share_url

    # ──────────────────────────── Subscribe ───────────────────────────────────

    async def subscribe_space(self, space_id: int) -> dict:
        """
        Subscribe the current user to a knowledge space.
        - PRIVATE spaces cannot be subscribed.
        - PUBLIC spaces: status = active (True) → 'subscribed'
        - APPROVAL spaces: status = pending (False) → 'pending'
        Returns {"status": "subscribed" | "pending", "space_id": space_id}
        """
        space = KnowledgeDao.query_by_id(space_id)
        if not space or space.type != KnowledgeTypeEnum.SPACE.value:
            raise SpaceNotFoundError()

        if space.auth_type == AuthTypeEnum.PRIVATE:
            raise SpaceSubscribePrivateError()

        existing = await SpaceChannelMemberDao.async_find_member(space_id, self.login_user.user_id)
        if existing is not None:
            raise SpaceAlreadySubscribedError()

        count = await SpaceChannelMemberDao.async_count_user_space_subscriptions(self.login_user.user_id)
        if count >= self._MAX_SUBSCRIBE_PER_USER:
            raise SpaceSubscribeLimitError()

        is_active = space.auth_type == AuthTypeEnum.PUBLIC
        member = SpaceChannelMember(
            business_id=str(space_id),
            business_type=BusinessTypeEnum.SPACE,
            user_id=self.login_user.user_id,
            user_role=UserRoleEnum.MEMBER,
            status=is_active,
        )
        # todo 发送站内信
        await SpaceChannelMemberDao.async_insert_member(member)

        return {
            "status": "subscribed" if is_active else "pending",
            "space_id": space_id,
        }
