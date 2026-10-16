import asyncio
import hashlib
import json
from datetime import datetime
from typing import Any

from bisheng.common.cursor import decode_cursor, encode_cursor
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.knowledge.domain.repositories.interfaces.knowledge_mcp_repository import KnowledgeMcpRepository
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


class KnowledgeMcpQueryService:
    BATCH_SIZE = 100
    SCAN_BUDGET = 1000

    def __init__(self, repository: KnowledgeMcpRepository, owner: KnowledgeSpaceService) -> None:
        self.repository = repository
        self.owner = owner
        self.user = owner.login_user
        self._permission_cache: dict[tuple, set[str]] = {}

    async def permissions(self, kind: str, resource_id: int, space_id: int | None = None) -> set[str]:
        key = (kind, resource_id, space_id)
        if key not in self._permission_cache:
            self._permission_cache[key] = set(
                await self.owner._get_effective_permission_ids(
                    kind,
                    resource_id,
                    **({"space_id": space_id} if space_id is not None else {}),
                )
            )
        return self._permission_cache[key]

    async def require_space(self, knowledge_id: int) -> Any:
        space = await self.repository.get_space(knowledge_id)
        if (
            space is None
            or space.type != 3
            or space.state == 5
            or int(space.tenant_id or 1) != int(self.user.tenant_id)
            or "view_space" not in await self.permissions("knowledge_space", knowledge_id)
        ):
            raise SpacePermissionDeniedError()
        return space

    async def folder_path(self, knowledge_id: int, folder_id: int | None) -> str:
        if folder_id is None:
            return ""
        folder = await self.repository.find_by_id(folder_id)
        if (
            folder is None
            or folder.file_type != 0
            or folder.knowledge_id != knowledge_id
            or int(folder.tenant_id or 1) != int(self.user.tenant_id)
            or getattr(folder, "deleted_at", None) is not None
            or "view_folder" not in await self.permissions("folder", folder_id, knowledge_id)
        ):
            raise SpacePermissionDeniedError()
        return f"{folder.file_level_path or ''}/{folder_id}"

    def context(self, tool: str, params: dict) -> str:
        payload = {"tool": tool, "user": self.user.user_id, "tenant": self.user.tenant_id, **params}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    @staticmethod
    def cursor_key(cursor: str | None, context: str) -> list | None:
        key = decode_cursor(cursor, expected_key_len=2, expected_context=context)
        if key is not None and (not isinstance(key[0], str) or type(key[1]) is not int or key[1] <= 0):
            raise ValueError("invalid cursor key")
        return key

    @staticmethod
    def file_key(file: Any, sort_by: str) -> list:
        value = (
            file.file_name
            if sort_by == "file_name"
            else (file.update_time or getattr(file, "create_time", None) or datetime(1970, 1, 1)).isoformat()
        )
        return [value, int(file.id)]

    @staticmethod
    def page(data: list[dict], page_size: int, has_more: bool, cursor: str | None) -> dict:
        return {"data": data, "page_size": page_size, "has_more": has_more, "next_cursor": cursor if has_more else None}

    async def visible(self, file: Any) -> bool:
        if (
            int(file.tenant_id or 1) != int(self.user.tenant_id)
            or getattr(file, "deleted_at", None) is not None
            or (file.reference_document_id is not None and file.entry_status != "active")
        ):
            return False
        kind, action = ("folder", "view_folder") if file.file_type == 0 else ("knowledge_file", "view_file")
        if action not in await self.permissions(kind, int(file.id), int(file.knowledge_id)):
            return False
        if file.file_type == 1 and file.status in {3, 6, 7} and file.user_id != self.user.user_id:
            context = await self.owner._build_child_permission_context(int(file.knowledge_id))
            return bool(context.get("can_view_all_statuses", False))
        return True

    @staticmethod
    def file_item(file: Any) -> dict:
        parents = [int(part) for part in (file.file_level_path or "").split("/") if part.isdigit()]
        return {
            "id": int(file.id),
            "knowledge_id": int(file.knowledge_id),
            "name": str(file.file_name or ""),
            "size": int(file.file_size or 0),
            "status": int(file.status),
            "update_time": file.update_time.isoformat() if file.update_time else "",
            "parent_id": parents[-1] if parents else None,
        }

    async def path_items(self, file: Any) -> dict:
        ids, names = [], []
        for part in (file.file_level_path or "").split("/"):
            if not part.isdigit():
                continue
            parent = await self.repository.find_by_id(int(part))
            if parent is not None and parent.knowledge_id == file.knowledge_id and parent.file_type == 0:
                if await self.visible(parent):
                    ids.append(int(parent.id))
                    names.append(str(parent.file_name or ""))
        return {"path_ids": ids, "path_names": names}

    async def _has_writable_folders(self, space_id: int) -> bool:
        after = None
        while True:
            rows = await self.repository.scan_files(
                [space_id], file_type=0, sort_by="file_name", order="asc", after=after
            )
            for folder in rows:
                if await self.visible(folder) and "upload_file_to_folder" in await self.permissions(
                    "folder", folder.id, space_id
                ):
                    expected = [int(part) for part in (folder.file_level_path or "").split("/") if part.isdigit()]
                    if (await self.path_items(folder))["path_ids"] == expected:
                        return True
            if len(rows) < self.BATCH_SIZE:
                return False
            after = self.file_key(rows[-1], "file_name")

    async def list_knowledge(
        self, *, name: str | None = None, writable_only: bool = False, cursor: str | None = None, page_size: int = 20
    ) -> dict:
        levels = await self.owner.get_existing_portal_visible_space_levels()
        context = self.context("list_knowledge", {"name": name, "writable_only": writable_only})
        after = self.cursor_key(cursor, context)
        data, scanned, last = [], 0, after
        while scanned < self.SCAN_BUDGET:
            rows = await self.repository.spaces(list(levels), name=name, after=last)
            for space in rows:
                scanned += 1
                key = [str(space.name), int(space.id)]
                if int(space.tenant_id or 1) != int(self.user.tenant_id):
                    last = key
                    continue
                permissions = await self.permissions("knowledge_space", space.id)
                if "view_space" not in permissions:
                    last = key
                    continue
                favorite = bool(space.is_favorite)
                root = not favorite and "upload_file_to_space" in permissions
                folders = not favorite and await self._has_writable_folders(space.id)
                if not writable_only or root or folders:
                    if len(data) == page_size:
                        return self.page(data, page_size, True, encode_cursor(last, context=context))
                    level = levels[int(space.id)]
                    data.append(
                        {
                            "id": int(space.id),
                            "name": str(space.name),
                            "space_level": str(getattr(level, "value", level)),
                            "description": str(space.description or ""),
                            "can_upload_to_root": root,
                            "has_writable_folders": folders,
                        }
                    )
                last = key
            if len(rows) < self.BATCH_SIZE:
                return self.page(data, page_size, False, None)
        return self.page(data, page_size, True, encode_cursor(last, context=context))

    async def _files_page(
        self,
        *,
        context: str,
        space_ids: list[int],
        parent_path: str | None,
        file_type: int,
        cursor: str | None,
        page_size: int,
        sort_by: str = "update_time",
        order: str = "desc",
        statuses: list[int] | None = None,
        recursive: bool = False,
        keyword: str | None = None,
        search_mode: str = "name",
    ) -> dict:
        after = self.cursor_key(cursor, context)
        last, data, scanned = after, [], 0
        while scanned < self.SCAN_BUDGET:
            rows = await self.repository.scan_files(
                space_ids,
                file_type=file_type,
                parent_path=parent_path,
                recursive=recursive,
                statuses=statuses,
                after=last,
                sort_by=sort_by,
                order=order,
            )
            semaphore = asyncio.Semaphore(16)

            async def allowed(file: Any, semaphore: asyncio.Semaphore = semaphore) -> bool:
                async with semaphore:
                    return await self.visible(file)

            decisions = await asyncio.gather(*(allowed(file) for file in rows))
            permitted = [file for file, ok in zip(rows, decisions, strict=True) if ok]
            content_ids = (
                await self.repository.content_matches(permitted, keyword)
                if keyword and search_mode in {"content", "all"}
                else set()
            )
            for file, ok in zip(rows, decisions, strict=True):
                scanned += 1
                key = self.file_key(file, sort_by)
                match = (
                    not keyword
                    or (search_mode in {"name", "all"} and keyword.casefold() in (file.file_name or "").casefold())
                    or int(file.id) in content_ids
                )
                if ok and match:
                    if len(data) == page_size:
                        return self.page(data, page_size, True, encode_cursor(last, context=context))
                    item = self.file_item(file)
                    if file_type == 0:
                        item.update(await self.path_items(file))
                        item["path_ids"].append(int(file.id))
                        item["path_names"].append(str(file.file_name))
                        space = await self.repository.get_space(file.knowledge_id)
                        item["can_upload"] = not bool(
                            space.is_favorite
                        ) and "upload_file_to_folder" in await self.permissions(
                            "folder",
                            file.id,
                            file.knowledge_id,
                        )
                    elif keyword:
                        item.update(await self.path_items(file))
                        item["parent_id"] = item["path_ids"][-1] if item["path_ids"] else None
                    data.append(item)
                last = key
            if len(rows) < self.BATCH_SIZE:
                return self.page(data, page_size, False, None)
        return self.page(data, page_size, True, encode_cursor(last, context=context))

    async def list_folders(
        self, *, knowledge_id: int, folder_id: int | None = None, cursor: str | None = None, page_size: int = 20
    ) -> dict:
        await self.require_space(knowledge_id)
        path = await self.folder_path(knowledge_id, folder_id)
        context = self.context("list_folders", {"knowledge_id": knowledge_id, "folder_id": folder_id})
        return await self._files_page(
            context=context,
            space_ids=[knowledge_id],
            parent_path=path,
            file_type=0,
            cursor=cursor,
            page_size=page_size,
            sort_by="file_name",
            order="asc",
        )

    async def list_files(
        self,
        *,
        knowledge_id: int,
        folder_id: int | None = None,
        statuses: list[int] | None = None,
        sort_by: str = "update_time",
        order: str = "desc",
        cursor: str | None = None,
        page_size: int = 20,
    ) -> dict:
        await self.require_space(knowledge_id)
        path = await self.folder_path(knowledge_id, folder_id)
        context = self.context(
            "list_files",
            {
                "knowledge_id": knowledge_id,
                "folder_id": folder_id,
                "statuses": sorted(set(statuses)) if statuses is not None else None,
                "sort_by": sort_by,
                "order": order,
            },
        )
        return await self._files_page(
            context=context,
            space_ids=[knowledge_id],
            parent_path=path,
            file_type=1,
            cursor=cursor,
            page_size=page_size,
            statuses=statuses,
            sort_by=sort_by,
            order=order,
        )

    async def search_files(
        self,
        *,
        keyword: str,
        knowledge_ids: list[int] | None = None,
        folder_scope: dict | None = None,
        search_mode: str = "all",
        cursor: str | None = None,
        page_size: int = 20,
    ) -> dict:
        ids = sorted(set(knowledge_ids or await self.owner.get_existing_portal_visible_space_levels()))
        for space_id in ids:
            await self.require_space(space_id)
        path = None
        if folder_scope:
            if folder_scope["knowledge_id"] not in ids:
                raise SpacePermissionDeniedError()
            ids = [folder_scope["knowledge_id"]]
            path = await self.folder_path(ids[0], folder_scope["folder_id"])
        context = self.context(
            "search_files",
            {"keyword": keyword, "knowledge_ids": ids, "folder_scope": folder_scope, "search_mode": search_mode},
        )
        return await self._files_page(
            context=context,
            space_ids=ids,
            parent_path=path,
            file_type=1,
            cursor=cursor,
            page_size=page_size,
            statuses=[2],
            recursive=path is not None,
            keyword=keyword,
            search_mode=search_mode,
        )
