"""Prepare a local-authoritative folder tree for provider (WeKnora) nested uploads.

Creates KnowledgeFile(DIR) rows + folder mappings so subsequent per-file
provider-uploads can target parent_id. Does not stream file bodies.
"""

from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlmodel import col, select

from bisheng.common.errcode.knowledge_space import (
    SpaceFolderDepthError,
    SpaceFolderDuplicateError,
    SpaceFolderNotFoundError,
    SpaceFolderUploadCountExceededError,
)
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.provider_upload_v1 import upload_admission
from bisheng.knowledge.application.provider_v1_runtime import ProviderFeatureUnavailable, resolve_space_route
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderMapping as Mapping
from bisheng.knowledge.domain.services.knowledge_space_service import MAX_FOLDER_LEVEL

# Keep in sync with KnowledgeSpaceService.MAX_FOLDER_UPLOAD_FILES.
_MAX_FOLDER_UPLOAD_FILES = 1000


class ProviderFolderPrepareRequest(BaseModel):
    parent_id: int | None = Field(default=None, gt=0)
    paths: list[str] = Field(..., min_length=1)


class ProviderFolderPrepareFolder(BaseModel):
    relative_dir: str
    folder_id: int


class ProviderFolderPrepareResponse(BaseModel):
    root_name: str
    folders: list[ProviderFolderPrepareFolder]


def _segments(path: str) -> list[str]:
    return [part for part in path.replace("\\", "/").split("/") if part and part not in (".", "..")]


async def _existing_tree(space_id: int, root_name: str, base_path: str) -> dict[tuple[str, ...], int] | None:
    """Reusable DIR-only leftover tree at the drop point, or ``None`` on a real clash.

    A retried folder upload (C03: retry only the unfinished files) must not be
    rejected by the tree its own earlier attempt left behind, so a subtree that
    holds nothing but directories is reused. Any file inside it — or a same-named
    file at the drop point — means a real folder already exists: that stays a
    whole-batch ``SpaceFolderDuplicateError``, never a silent merge.
    """
    async with get_async_db_session() as db:
        named = (
            await db.execute(
                select(
                    KnowledgeFile.id,
                    KnowledgeFile.file_name,
                    KnowledgeFile.file_type,
                    KnowledgeFile.file_level_path,
                ).where(
                    KnowledgeFile.knowledge_id == space_id,
                    KnowledgeFile.file_name == root_name,
                    KnowledgeFile.file_level_path == base_path,
                )
            )
        ).all()
        if not named:
            return {}
        if any(row.file_type != FileType.DIR.value for row in named):
            return None
        root = named[0]
        prefix = f"{base_path}/{root.id}"
        subtree = (
            await db.execute(
                select(
                    KnowledgeFile.id,
                    KnowledgeFile.file_name,
                    KnowledgeFile.file_type,
                    KnowledgeFile.file_level_path,
                ).where(
                    KnowledgeFile.knowledge_id == space_id,
                    or_(
                        col(KnowledgeFile.file_level_path) == prefix,
                        col(KnowledgeFile.file_level_path).like(f"{prefix}/%"),
                    ),
                )
            )
        ).all()
    if any(row.file_type != FileType.DIR.value for row in subtree):
        return None
    names = {root.id: root.file_name} | {row.id: row.file_name for row in subtree}
    # Chains are relative to the drop point: the root's own ancestors are skipped.
    chains: dict[tuple[str, ...], int] = {(root_name,): root.id}
    for row in subtree:
        parts = [int(part) for part in (row.file_level_path or "").split("/") if part.isdigit()]
        if root.id not in parts:
            return None
        tail = parts[parts.index(root.id) + 1 :]
        if any(parent not in names for parent in tail):
            return None
        chains[(root_name,) + tuple(names[parent] for parent in tail) + (row.file_name,)] = row.id
    return chains


def _parse_paths(paths: list[str]) -> tuple[str, set[tuple[str, ...]]]:
    """Return (root_name, dir_set) from file relative paths. Rejects hidden roots."""
    if len(paths) > _MAX_FOLDER_UPLOAD_FILES:
        raise SpaceFolderUploadCountExceededError()
    dir_set: set[tuple[str, ...]] = set()
    root_name: str | None = None
    for raw in paths:
        if type(raw) is not str or not raw.strip():
            raise SpaceFolderNotFoundError()
        parts = _segments(raw)
        if len(parts) < 2:
            # A folder upload always has at least root/file; bare filenames are flat uploads.
            raise SpaceFolderNotFoundError()
        if any(part.startswith(".") for part in parts):
            raise SpaceFolderNotFoundError()
        root = parts[0]
        if root_name is None:
            root_name = root
        elif root != root_name:
            raise SpaceFolderNotFoundError()
        dir_parts = tuple(parts[:-1])
        for depth in range(1, len(dir_parts) + 1):
            dir_set.add(dir_parts[:depth])
    if not root_name or not dir_set:
        raise SpaceFolderNotFoundError()
    return root_name, dir_set


async def prepare_folder_tree(
    service, space_id: int, request: ProviderFolderPrepareRequest
) -> ProviderFolderPrepareResponse:
    route = await resolve_space_route(space_id)
    if route is None:
        raise ProviderFeatureUnavailable()
    if await upload_admission(service, route) is None:
        raise ProviderFeatureUnavailable()

    root_name, dir_set = _parse_paths(request.paths)
    parent_id = request.parent_id
    space = await service.require_upload_container(space_id, parent_id)
    if space.tenant_id != get_current_tenant_id() or space.tenant_id != route.tenant_id:
        raise ProviderFeatureUnavailable()

    base_path = ""
    base_child_level = 0
    if parent_id:
        parent_folder = await service._get_folder_for_action(space_id, parent_id)
        base_path = f"{parent_folder.file_level_path}/{parent_id}"
        base_child_level = parent_folder.level + 1

    max_chain = max(len(d) for d in dir_set)
    if base_child_level + max_chain - 1 > MAX_FOLDER_LEVEL:
        raise SpaceFolderDepthError()

    existing = await _existing_tree(space_id, root_name, base_path)
    if existing is None:
        raise SpaceFolderDuplicateError()

    application = service.upload_application_factory()
    # Maps dir chain → folder_id; empty chain is the drop point.
    node_ids: dict[tuple[str, ...], int | None] = {(): parent_id} | existing
    folders: list[ProviderFolderPrepareFolder] = []
    created_ids: list[int] = []
    tenant = route.tenant_id
    try:
        for dir_parts in sorted(dir_set, key=len):
            if dir_parts in existing:
                # Leftover from an earlier attempt: reuse it, create nothing.
                folders.append(
                    ProviderFolderPrepareFolder(
                        relative_dir="/".join(dir_parts),
                        folder_id=existing[dir_parts],
                    )
                )
                continue
            parent_node = node_ids[dir_parts[:-1]]
            folder_row = await application.acreate_folder(
                knowledge=space,
                parent_id=parent_node,
                folder_name=dir_parts[-1],
            )
            node_ids[dir_parts] = folder_row.id
            created_ids.append(folder_row.id)
            async with get_async_db_session() as db, db.begin():
                db.add(
                    Mapping(
                        tenant_id=tenant,
                        space_id=space_id,
                        generation=route.generation,
                        resource_type="folder",
                        local_resource_id=folder_row.id,
                        remote_object_id=f"lf:{route.generation}:{folder_row.id}",
                        lifecycle_state="active",
                        ready_revision=0,
                        operation_epoch=1,
                    )
                )
            folders.append(
                ProviderFolderPrepareFolder(
                    relative_dir="/".join(dir_parts),
                    folder_id=folder_row.id,
                )
            )
    except BaseException:
        if created_ids:
            async with get_async_db_session() as db, db.begin():
                from sqlalchemy import delete

                await db.execute(
                    delete(Mapping).where(
                        Mapping.tenant_id == tenant,
                        Mapping.space_id == space_id,
                        Mapping.generation == route.generation,
                        Mapping.resource_type == "folder",
                        Mapping.local_resource_id.in_(created_ids),
                    )
                )
        await service._compensate_upload(application)
        raise

    return ProviderFolderPrepareResponse(root_name=root_name, folders=folders)
