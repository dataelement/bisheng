from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, or_, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import (
    PORTAL_USER_UPLOAD_FILE_SOURCES,
    FileSource,
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeLockScope,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.models.knowledge_space_upload_stage import KnowledgeSpaceUploadStage
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_footprint_repository import (
    FootprintEntry,
)
from bisheng.user.domain.models.user_role import UserRole


@dataclass(frozen=True, slots=True)
class FormalUploadBundle:
    file: KnowledgeFile
    document: KnowledgeDocument
    version: KnowledgeDocumentVersion
    created_folders: tuple[KnowledgeFile, ...] = ()


class KnowledgeSpaceMutationRepository:
    """Session-bound persistence primitives for formal Knowledge upload rows.

    Every method only flushes into the caller-owned transaction. External
    storage, OpenFGA and worker dispatch are intentionally outside this owner.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_upload_stage(
        self,
        *,
        tenant_id: int,
        upload_stage_id: int,
        for_update: bool = False,
    ) -> KnowledgeSpaceUploadStage | None:
        statement = select(KnowledgeSpaceUploadStage).where(
            KnowledgeSpaceUploadStage.tenant_id == int(tenant_id),
            KnowledgeSpaceUploadStage.id == int(upload_stage_id),
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.exec(statement)).first()

    async def lock_space(self, *, tenant_id: int, space_id: int) -> Knowledge | None:
        statement = (
            select(Knowledge)
            .where(
                Knowledge.tenant_id == int(tenant_id),
                Knowledge.id == int(space_id),
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            )
            .with_for_update()
        )
        return (await self.session.exec(statement)).first()

    async def get_current_user_role_ids(self, *, tenant_id: int, user_id: int) -> list[int]:
        """Read the applicant's current tenant roles in the caller-owned UoW."""
        rows = (
            await self.session.exec(
                select(UserRole.role_id).where(
                    UserRole.tenant_id == int(tenant_id),
                    UserRole.user_id == int(user_id),
                )
            )
        ).all()
        return [int(row[0] if isinstance(row, tuple) else row) for row in rows]

    async def lock_spaces(self, *, tenant_id: int, space_ids: list[int]) -> list[Knowledge]:
        normalized_ids = sorted({int(space_id) for space_id in space_ids})
        if not normalized_ids:
            return []
        statement = (
            select(Knowledge)
            .where(
                Knowledge.tenant_id == int(tenant_id),
                Knowledge.id.in_(normalized_ids),
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            )
            .order_by(Knowledge.id.asc())
            .with_for_update()
        )
        return list((await self.session.exec(statement)).all())

    async def build_rename_manifest(
        self,
        *,
        tenant_id: int,
        space_id: int,
        resource_id: int,
        resource_type: str,
        old_name: str,
        new_name: str,
    ) -> dict:
        root = await self.get_formal_file(
            tenant_id=tenant_id,
            space_id=space_id,
            file_id=resource_id,
            for_update=True,
        )
        if root is None or not self._resource_type_matches(root, resource_type):
            raise LookupError(f"F046 rename resource not found: {resource_id}")
        if root.file_name != old_name:
            raise ValueError("F046 rename source name changed after approval")
        if not new_name or len(new_name) > 500:
            raise ValueError("F046 rename target name is invalid")
        if int(root.file_type) == FileType.FILE.value and root.file_source != FileSource.WEB_LINK.value:
            old_suffix = root.file_name.rsplit(".", 1)[-1] if "." in root.file_name else ""
            new_suffix = new_name.rsplit(".", 1)[-1] if "." in new_name else ""
            if old_suffix != new_suffix:
                raise ValueError("F046 rename cannot change the file extension")
        if await self._name_conflicts(
            tenant_id=tenant_id,
            space_id=space_id,
            root=root,
            target_name=new_name,
        ):
            raise ValueError("F046 rename target name conflicts with an existing resource")
        return {
            "version": 1,
            "action": "rename",
            "root": self._row_snapshot(root),
            "new_name": str(new_name),
            "rows": [self._row_snapshot(root)],
            "subtree_root_id": int(root.id) if int(root.file_type) == FileType.DIR.value else None,
        }

    async def build_move_manifest(
        self,
        *,
        tenant_id: int,
        source_space_id: int,
        target_space_id: int,
        target_parent_id: int | None,
        resource_id: int,
        resource_type: str,
        source_path: str | None,
        source_level: int | None,
    ) -> dict:
        spaces = await self.lock_spaces(
            tenant_id=tenant_id,
            space_ids=[source_space_id, target_space_id],
        )
        if {int(space.id) for space in spaces} != {int(source_space_id), int(target_space_id)}:
            raise LookupError("F046 move source or target space not found")
        root = await self.get_formal_file(
            tenant_id=tenant_id,
            space_id=source_space_id,
            file_id=resource_id,
            for_update=True,
        )
        if root is None or not self._resource_type_matches(root, resource_type):
            raise LookupError(f"F046 move resource not found: {resource_id}")
        if source_path is not None and self._path(root.file_level_path) != self._path(source_path):
            raise ValueError("F046 move source path changed after approval")
        if source_level is not None and int(root.level or 0) != int(source_level):
            raise ValueError("F046 move source level changed after approval")

        if target_parent_id is None:
            target_parent = None
            target_path = ""
            target_level = 0
        else:
            target_parent = await self.get_folder(
                tenant_id=tenant_id,
                space_id=target_space_id,
                folder_id=target_parent_id,
                for_update=True,
            )
            if target_parent is None:
                raise LookupError(f"F046 move target folder not found: {target_parent_id}")
            target_path = f"{self._path(target_parent.file_level_path)}/{int(target_parent.id)}"
            target_level = int(target_parent.level or 0) + 1

        cross_space = int(source_space_id) != int(target_space_id)
        old_path = self._path(root.file_level_path)
        old_self_prefix = f"{old_path}/{int(root.id)}"
        if not cross_space and target_parent_id == int(root.id):
            raise ValueError("F046 move cannot move a folder into itself")
        if (
            int(root.file_type) == FileType.DIR.value
            and not cross_space
            and (target_path == old_self_prefix or target_path.startswith(f"{old_self_prefix}/"))
        ):
            raise ValueError("F046 move cannot move a folder into its subtree")
        if not cross_space and target_path == old_path:
            raise ValueError("F046 move target is the current parent")
        if int(root.file_type) == FileType.DIR.value and await self._folder_move_name_conflicts(
            tenant_id=tenant_id,
            target_space_id=target_space_id,
            target_path=target_path,
            root=root,
        ):
            raise ValueError("F046 move target contains a folder with the same name")

        rows = await self._lock_move_rows(
            tenant_id=tenant_id,
            source_space_id=source_space_id,
            root=root,
        )
        subtree_resource_ids = sorted(int(row.id) for row in rows)
        max_folder_level = max(
            (int(row.level or 0) for row in rows if int(row.file_type) == FileType.DIR.value),
            default=int(root.level or 0),
        )
        level_delta = int(target_level) - int(root.level or 0)
        if int(root.file_type) == FileType.DIR.value and max_folder_level + level_delta > 9:
            raise ValueError("F046 move target exceeds the folder depth limit")

        row_entries: dict[int, dict] = {}
        new_self_prefix = f"{target_path}/{int(root.id)}"
        for row in rows:
            old_row_path = self._path(row.file_level_path)
            if int(row.id) == int(root.id):
                new_path = target_path
                new_level = target_level
            else:
                if not (old_row_path == old_self_prefix or old_row_path.startswith(f"{old_self_prefix}/")):
                    raise ValueError("F046 move subtree changed while building the manifest")
                new_path = new_self_prefix + old_row_path[len(old_self_prefix) :]
                new_level = int(row.level or 0) + level_delta
            entry = self._row_snapshot(row)
            entry.update(
                {
                    "new_space_id": int(target_space_id),
                    "new_path": new_path,
                    "new_level": int(new_level),
                }
            )
            row_entries[int(row.id)] = entry

        document_entries = await self._expand_version_chains(
            tenant_id=tenant_id,
            source_space_id=source_space_id,
            target_space_id=target_space_id,
            row_entries=row_entries,
            old_self_prefix=old_self_prefix,
            new_self_prefix=new_self_prefix,
            level_delta=level_delta,
        )
        root_entry = row_entries[int(root.id)]
        tag_resource_ids = sorted(
            entry["id"] for entry in row_entries.values() if entry["file_type"] == FileType.FILE.value
        )
        return {
            "version": 1,
            "action": "move",
            "root": dict(root_entry),
            "source_space_id": int(source_space_id),
            "target_space_id": int(target_space_id),
            "target_parent_id": int(target_parent_id) if target_parent_id is not None else None,
            "target_parent": self._row_snapshot(target_parent) if target_parent is not None else None,
            "cross_space": cross_space,
            "rows": [row_entries[row_id] for row_id in sorted(row_entries)],
            "subtree_resource_ids": subtree_resource_ids,
            "documents": document_entries,
            "parent_tuple": {
                "resource_type": "folder" if int(root.file_type) == FileType.DIR.value else "knowledge_file",
                "resource_id": int(root.id),
                "old_parent_type": "folder" if old_path else "knowledge_space",
                "old_parent_id": int(old_path.split("/")[-1]) if old_path else int(source_space_id),
                "new_parent_type": "folder" if target_parent_id is not None else "knowledge_space",
                "new_parent_id": int(target_parent_id) if target_parent_id is not None else int(target_space_id),
            },
            "tag_resource_ids": tag_resource_ids,
            "tag_snapshot": await self._load_tag_snapshot(
                tenant_id=tenant_id,
                resource_ids=tag_resource_ids,
            ),
            "index_resource_ids": sorted(
                entry["id"]
                for entry in row_entries.values()
                if entry["file_type"] == FileType.FILE.value
                and entry["old_status"] == KnowledgeFileStatus.SUCCESS.value
            ),
        }

    async def build_delete_manifest(
        self,
        *,
        tenant_id: int,
        space_id: int,
        resource_id: int,
        resource_type: str,
        source_name: str | None,
        source_path: str | None,
        source_level: int | None,
    ) -> dict:
        """Lock and snapshot every DB/external resource affected by delete.

        This is deliberately read-only apart from row locks. In particular it
        never calls the legacy delete worker and never changes formal rows.
        """

        space = await self.lock_space(tenant_id=tenant_id, space_id=space_id)
        if space is None:
            raise LookupError(f"F046 delete knowledge space not found: {space_id}")
        root = await self.get_formal_file(
            tenant_id=tenant_id,
            space_id=space_id,
            file_id=resource_id,
            for_update=True,
        )
        if root is None or not self._resource_type_matches(root, resource_type):
            raise LookupError(f"F046 delete resource not found: {resource_id}")
        if source_name is not None and str(root.file_name) != str(source_name):
            raise ValueError("F046 delete source name changed after approval")
        if source_path is not None and self._path(root.file_level_path) != self._path(source_path):
            raise ValueError("F046 delete source path changed after approval")
        if source_level is not None and int(root.level or 0) != int(source_level):
            raise ValueError("F046 delete source level changed after approval")

        selected_rows = (
            await self._lock_move_rows(
                tenant_id=tenant_id,
                source_space_id=space_id,
                root=root,
            )
            if int(root.file_type) == FileType.DIR.value
            else [root]
        )
        selected_file_ids = {int(row.id) for row in selected_rows if int(row.file_type) == FileType.FILE.value}
        subtree_resource_ids = sorted(int(row.id) for row in selected_rows)
        version_rows = (
            list(
                (
                    await self.session.exec(
                        select(KnowledgeDocumentVersion)
                        .where(KnowledgeDocumentVersion.knowledge_file_id.in_(sorted(selected_file_ids)))
                        .order_by(KnowledgeDocumentVersion.document_id.asc(), KnowledgeDocumentVersion.id.asc())
                        .with_for_update()
                    )
                ).all()
            )
            if selected_file_ids
            else []
        )

        selected_versions_by_document: dict[int, list[KnowledgeDocumentVersion]] = {}
        for version in version_rows:
            selected_versions_by_document.setdefault(int(version.document_id), []).append(version)

        delete_version_ids: set[int] = set()
        delete_document_ids: set[int] = set()
        expanded_file_ids = set(selected_file_ids)
        for document_id, selected_versions in selected_versions_by_document.items():
            chain = list(
                (
                    await self.session.exec(
                        select(KnowledgeDocumentVersion)
                        .where(KnowledgeDocumentVersion.document_id == int(document_id))
                        .order_by(KnowledgeDocumentVersion.id.asc())
                        .with_for_update()
                    )
                ).all()
            )
            selected_version_ids = {int(version.id) for version in selected_versions}
            remove_chain = any(bool(version.is_primary) for version in selected_versions) or len(chain) == len(
                selected_version_ids
            )
            versions_to_remove = chain if remove_chain else selected_versions
            delete_version_ids.update(int(version.id) for version in versions_to_remove)
            expanded_file_ids.update(int(version.knowledge_file_id) for version in versions_to_remove)
            if remove_chain:
                delete_document_ids.add(int(document_id))

        selected_row_ids = {int(row.id) for row in selected_rows}
        sibling_ids = sorted(expanded_file_ids - selected_row_ids)
        if sibling_ids:
            siblings = list(
                (
                    await self.session.exec(
                        select(KnowledgeFile)
                        .where(
                            KnowledgeFile.tenant_id == int(tenant_id),
                            KnowledgeFile.knowledge_id == int(space_id),
                            KnowledgeFile.id.in_(sibling_ids),
                        )
                        .order_by(KnowledgeFile.id.asc())
                        .with_for_update()
                    )
                ).all()
            )
            if {int(row.id) for row in siblings} != set(sibling_ids):
                raise ValueError("F046 delete version chain changed during preparation")
            selected_rows.extend(siblings)

        document_rows = (
            list(
                (
                    await self.session.exec(
                        select(KnowledgeDocument)
                        .where(
                            KnowledgeDocument.knowledge_id == int(space_id),
                            KnowledgeDocument.id.in_(sorted(delete_document_ids)),
                        )
                        .order_by(KnowledgeDocument.id.asc())
                        .with_for_update()
                    )
                ).all()
            )
            if delete_document_ids
            else []
        )
        if {int(row.id) for row in document_rows} != delete_document_ids:
            raise ValueError("F046 delete document chain changed during preparation")

        rows = sorted(selected_rows, key=lambda row: int(row.id))
        row_snapshots = [self._row_snapshot(row) for row in rows]
        object_names = sorted(
            {
                str(value)
                for row in rows
                for value in (
                    row.object_name,
                    row.preview_file_object_name,
                    row.bbox_object_name,
                    row.thumbnails,
                    str(row.id) if int(row.file_type) == FileType.FILE.value else None,
                )
                if value
            }
        )
        file_ids = sorted(int(row.id) for row in rows if int(row.file_type) == FileType.FILE.value)
        folder_ids = sorted(int(row.id) for row in rows if int(row.file_type) == FileType.DIR.value)
        return {
            "version": 1,
            "action": "delete",
            "root": self._row_snapshot(root),
            "rows": row_snapshots,
            "subtree_resource_ids": subtree_resource_ids,
            "file_ids": file_ids,
            "folder_ids": folder_ids,
            "version_ids": sorted(delete_version_ids),
            "document_ids": sorted(delete_document_ids),
            "fga_resources": [
                {
                    "resource_type": "folder" if int(row.file_type) == FileType.DIR.value else "knowledge_file",
                    "resource_id": int(row.id),
                }
                for row in rows
            ],
            "object_names": object_names,
            "index_resource_ids": sorted(
                int(row.id)
                for row in rows
                if int(row.file_type) == FileType.FILE.value
                and int(row.status or 0) == KnowledgeFileStatus.SUCCESS.value
            ),
            # Ancestors are intentionally not part of delete. Folder cleanup
            # elsewhere must use list_successful_file_paths_using_folders()
            # before pruning shared upload-created directories.
            "ancestor_folder_ids": [int(part) for part in self._path(root.file_level_path).split("/") if part],
        }

    async def validate_delete_manifest_current(self, *, tenant_id: int, manifest: dict) -> None:
        await self.validate_manifest_current(tenant_id=tenant_id, manifest=manifest)
        version_ids = sorted({int(version_id) for version_id in manifest.get("version_ids", [])})
        if version_ids:
            current_version_ids = {
                int(version_id)
                for version_id in (
                    await self.session.exec(
                        select(KnowledgeDocumentVersion.id).where(KnowledgeDocumentVersion.id.in_(version_ids))
                    )
                ).all()
            }
            if current_version_ids != set(version_ids):
                raise ValueError("F046 delete version set changed before cutover")
        document_ids = sorted({int(document_id) for document_id in manifest.get("document_ids", [])})
        if document_ids:
            current_document_ids = {
                int(document_id)
                for document_id in (
                    await self.session.exec(
                        select(KnowledgeDocument.id).where(
                            KnowledgeDocument.knowledge_id == int(manifest["root"]["old_space_id"]),
                            KnowledgeDocument.id.in_(document_ids),
                        )
                    )
                ).all()
            }
            if current_document_ids != set(document_ids):
                raise ValueError("F046 delete document set changed before cutover")

    async def apply_delete_cutover(self, *, tenant_id: int, manifest: dict) -> None:
        """Hard-delete only the prepared formal DB graph in caller's UoW."""

        await self.validate_delete_manifest_current(tenant_id=tenant_id, manifest=manifest)
        version_ids = sorted({int(version_id) for version_id in manifest.get("version_ids", [])})
        document_ids = sorted({int(document_id) for document_id in manifest.get("document_ids", [])})
        row_ids = sorted({int(entry["id"]) for entry in manifest.get("rows", [])})
        space_id = int(manifest["root"]["old_space_id"])
        if document_ids:
            await self.session.exec(
                update(KnowledgeDocument)
                .where(
                    KnowledgeDocument.knowledge_id == space_id,
                    KnowledgeDocument.id.in_(document_ids),
                )
                .values(primary_version_id=None)
            )
        if version_ids:
            await self.session.exec(
                delete(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.id.in_(version_ids))
            )
        if document_ids:
            await self.session.exec(
                delete(KnowledgeDocument).where(
                    KnowledgeDocument.knowledge_id == space_id,
                    KnowledgeDocument.id.in_(document_ids),
                )
            )
        if row_ids:
            await self.session.exec(
                delete(KnowledgeFile).where(
                    KnowledgeFile.tenant_id == int(tenant_id),
                    KnowledgeFile.knowledge_id == space_id,
                    KnowledgeFile.id.in_(row_ids),
                )
            )
        await self.session.flush()

    async def validate_manifest_current(self, *, tenant_id: int, manifest: dict) -> None:
        row_ids = [int(entry["id"]) for entry in manifest.get("rows", [])]
        if not row_ids:
            raise ValueError("F046 mutation manifest has no resource rows")
        statement = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.tenant_id == int(tenant_id),
                KnowledgeFile.id.in_(row_ids),
            )
            .order_by(KnowledgeFile.id.asc())
            .with_for_update()
        )
        current = {int(row.id): row for row in (await self.session.exec(statement)).all()}
        if set(current) != set(row_ids):
            raise ValueError("F046 mutation resource set changed after preparation")
        for entry in manifest["rows"]:
            row = current[int(entry["id"])]
            if (
                int(row.knowledge_id) != int(entry["old_space_id"])
                or self._path(row.file_level_path) != self._path(entry["old_path"])
                or int(row.level or 0) != int(entry["old_level"])
                or str(row.file_name) != str(entry["old_name"])
                or int(row.file_type) != int(entry["file_type"])
            ):
                raise ValueError("F046 mutation resource changed before cutover")
        if manifest.get("action") in {"move", "delete"} and int(manifest["root"]["file_type"]) == FileType.DIR.value:
            root_entry = manifest["root"]
            root = current[int(root_entry["id"])]
            current_subtree = await self._lock_move_rows(
                tenant_id=tenant_id,
                source_space_id=int(root_entry["old_space_id"]),
                root=root,
            )
            if sorted(int(row.id) for row in current_subtree) != sorted(
                int(row_id) for row_id in manifest.get("subtree_resource_ids", [])
            ):
                raise ValueError(f"F046 {manifest.get('action')} subtree changed before cutover")
        target_parent = manifest.get("target_parent")
        if target_parent is not None:
            parent = current.get(int(target_parent["id"]))
            if parent is None:
                parent = await self.get_folder(
                    tenant_id=tenant_id,
                    space_id=int(target_parent["old_space_id"]),
                    folder_id=int(target_parent["id"]),
                    for_update=True,
                )
            if parent is None or self._path(parent.file_level_path) != self._path(target_parent["old_path"]):
                raise ValueError("F046 move target folder changed before cutover")

    async def apply_rename_cutover(
        self,
        *,
        tenant_id: int,
        manifest: dict,
        updater_user_id: int,
        updater_user_name: str,
    ) -> None:
        await self.validate_manifest_current(tenant_id=tenant_id, manifest=manifest)
        root = await self.get_formal_file(
            tenant_id=tenant_id,
            space_id=int(manifest["root"]["old_space_id"]),
            file_id=int(manifest["root"]["id"]),
            for_update=True,
        )
        if root is None:
            raise LookupError("F046 rename resource disappeared before cutover")
        if await self._name_conflicts(
            tenant_id=tenant_id,
            space_id=int(root.knowledge_id),
            root=root,
            target_name=str(manifest["new_name"]),
        ):
            raise ValueError("F046 rename target name now conflicts with an existing resource")
        root.file_name = str(manifest["new_name"])
        root.updater_id = int(updater_user_id)
        root.updater_name = str(updater_user_name)
        if root.file_source == FileSource.WEB_LINK.value:
            metadata = dict(root.user_metadata or {})
            metadata["web_title"] = root.file_name
            root.user_metadata = metadata
        self.session.add(root)
        await self.session.flush()

    async def apply_move_cutover(
        self,
        *,
        tenant_id: int,
        manifest: dict,
        updater_user_id: int,
        updater_user_name: str,
    ) -> None:
        await self.validate_manifest_current(tenant_id=tenant_id, manifest=manifest)
        root_entry = manifest["root"]
        root = await self.get_formal_file(
            tenant_id=tenant_id,
            space_id=int(root_entry["old_space_id"]),
            file_id=int(root_entry["id"]),
            for_update=True,
        )
        if root is None:
            raise LookupError("F046 move resource disappeared before cutover")
        if int(root.file_type) == FileType.DIR.value and await self._folder_move_name_conflicts(
            tenant_id=tenant_id,
            target_space_id=int(manifest["target_space_id"]),
            target_path=str(root_entry["new_path"]),
            root=root,
        ):
            raise ValueError("F046 move target now contains a folder with the same name")
        for entry in manifest["rows"]:
            row = await self.get_formal_file(
                tenant_id=tenant_id,
                space_id=int(entry["old_space_id"]),
                file_id=int(entry["id"]),
                for_update=True,
            )
            if row is None:
                raise LookupError("F046 move resource disappeared before cutover")
            row.knowledge_id = int(entry["new_space_id"])
            row.file_level_path = str(entry["new_path"])
            row.level = int(entry["new_level"])
            row.updater_id = int(updater_user_id)
            row.updater_name = str(updater_user_name)
            self.session.add(row)
        for entry in manifest.get("documents", []):
            document = await self.session.get(KnowledgeDocument, int(entry["id"]), with_for_update=True)
            if document is None:
                raise LookupError("F046 move document disappeared before cutover")
            if (
                int(document.knowledge_id) != int(entry["old_space_id"])
                or self._path(document.file_level_path) != self._path(entry["old_path"])
                or int(document.level or 0) != int(entry["old_level"])
            ):
                raise ValueError("F046 move document changed before cutover")
            document.knowledge_id = int(entry["new_space_id"])
            document.file_level_path = str(entry["new_path"])
            document.level = int(entry["new_level"])
            self.session.add(document)
        tag_resource_ids = sorted({str(resource_id) for resource_id in manifest.get("tag_resource_ids", [])})
        if tag_resource_ids:
            await self.session.exec(
                delete(TagLink).where(
                    TagLink.tenant_id == int(tenant_id),
                    TagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
                    TagLink.resource_id.in_(tag_resource_ids),
                )
            )
        await self.session.flush()

    async def validate_manifest_applied(self, *, tenant_id: int, manifest: dict) -> None:
        """Verify the formal DB cutover after a crash before external finalize."""

        row_ids = [int(entry["id"]) for entry in manifest.get("rows", [])]
        rows = list(
            (
                await self.session.exec(
                    select(KnowledgeFile)
                    .where(
                        KnowledgeFile.tenant_id == int(tenant_id),
                        KnowledgeFile.id.in_(row_ids),
                    )
                    .order_by(KnowledgeFile.id.asc())
                    .with_for_update()
                )
            ).all()
        )
        if {int(row.id) for row in rows} != set(row_ids):
            raise RuntimeError("F046 cutover resource set is incomplete")
        by_id = {int(row.id): row for row in rows}
        if manifest.get("action") == "rename":
            root = by_id[int(manifest["root"]["id"])]
            if str(root.file_name) != str(manifest["new_name"]):
                raise RuntimeError("F046 rename cutover is not durably applied")
            return
        for entry in manifest["rows"]:
            row = by_id[int(entry["id"])]
            if (
                int(row.knowledge_id) != int(entry["new_space_id"])
                or self._path(row.file_level_path) != self._path(entry["new_path"])
                or int(row.level or 0) != int(entry["new_level"])
            ):
                raise RuntimeError("F046 move cutover is not durably applied")
        resource_keys = sorted({str(resource_id) for resource_id in manifest.get("tag_resource_ids", [])})
        if resource_keys:
            remaining = int(
                (
                    await self.session.exec(
                        select(func.count(TagLink.id)).where(
                            TagLink.tenant_id == int(tenant_id),
                            TagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
                            TagLink.resource_id.in_(resource_keys),
                        )
                    )
                ).one()
            )
            if remaining:
                raise RuntimeError("F046 move tag cutover is incomplete")

    async def _lock_move_rows(
        self,
        *,
        tenant_id: int,
        source_space_id: int,
        root: KnowledgeFile,
    ) -> list[KnowledgeFile]:
        if int(root.file_type) == FileType.FILE.value:
            return [root]
        prefix = f"{self._path(root.file_level_path)}/{int(root.id)}"
        statement = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.tenant_id == int(tenant_id),
                KnowledgeFile.knowledge_id == int(source_space_id),
                or_(
                    KnowledgeFile.id == int(root.id),
                    KnowledgeFile.file_level_path == prefix,
                    KnowledgeFile.file_level_path.like(f"{prefix}/%"),
                ),
            )
            .order_by(KnowledgeFile.id.asc())
            .with_for_update()
        )
        return list((await self.session.exec(statement)).all())

    async def _expand_version_chains(
        self,
        *,
        tenant_id: int,
        source_space_id: int,
        target_space_id: int,
        row_entries: dict[int, dict],
        old_self_prefix: str,
        new_self_prefix: str,
        level_delta: int,
    ) -> list[dict]:
        visible_file_ids = [
            row_id for row_id, entry in row_entries.items() if entry["file_type"] == FileType.FILE.value
        ]
        if not visible_file_ids:
            return []
        versions = list(
            (
                await self.session.exec(
                    select(KnowledgeDocumentVersion).where(
                        KnowledgeDocumentVersion.knowledge_file_id.in_(visible_file_ids)
                    )
                )
            ).all()
        )
        document_ids = sorted({int(version.document_id) for version in versions})
        if not document_ids:
            return []
        all_versions = list(
            (
                await self.session.exec(
                    select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id.in_(document_ids))
                )
            ).all()
        )
        chain_ids = sorted({int(version.knowledge_file_id) for version in all_versions})
        chain_rows = list(
            (
                await self.session.exec(
                    select(KnowledgeFile)
                    .where(
                        KnowledgeFile.tenant_id == int(tenant_id),
                        KnowledgeFile.knowledge_id == int(source_space_id),
                        KnowledgeFile.id.in_(chain_ids),
                    )
                    .order_by(KnowledgeFile.id.asc())
                    .with_for_update()
                )
            ).all()
        )
        if {int(row.id) for row in chain_rows} != set(chain_ids):
            raise ValueError("F046 move version chain crosses the tenant or source space boundary")
        for row in chain_rows:
            if int(row.id) in row_entries:
                continue
            old_path = self._path(row.file_level_path)
            new_path = (
                new_self_prefix + old_path[len(old_self_prefix) :]
                if old_path == old_self_prefix or old_path.startswith(f"{old_self_prefix}/")
                else old_path
            )
            entry = self._row_snapshot(row)
            entry.update(
                {
                    "new_space_id": int(target_space_id),
                    "new_path": new_path,
                    "new_level": int(row.level or 0) + int(level_delta),
                }
            )
            row_entries[int(row.id)] = entry

        versions_by_id = {int(version.id): version for version in all_versions}
        documents = list(
            (
                await self.session.exec(
                    select(KnowledgeDocument)
                    .where(
                        KnowledgeDocument.id.in_(document_ids),
                        KnowledgeDocument.knowledge_id == int(source_space_id),
                    )
                    .order_by(KnowledgeDocument.id.asc())
                    .with_for_update()
                )
            ).all()
        )
        if {int(document.id) for document in documents} != set(document_ids):
            raise ValueError("F046 move document chain crosses the source space boundary")
        result = []
        for document in documents:
            primary = versions_by_id.get(int(document.primary_version_id or 0))
            representative = row_entries.get(int(primary.knowledge_file_id)) if primary is not None else None
            if representative is None:
                representative = next(
                    (
                        row_entries[int(version.knowledge_file_id)]
                        for version in all_versions
                        if int(version.document_id) == int(document.id)
                        and int(version.knowledge_file_id) in row_entries
                    ),
                    None,
                )
            if representative is None:
                raise ValueError("F046 move cannot resolve a document position")
            result.append(
                {
                    "id": int(document.id),
                    "old_space_id": int(document.knowledge_id),
                    "old_path": self._path(document.file_level_path),
                    "old_level": int(document.level or 0),
                    "new_space_id": int(target_space_id),
                    "new_path": str(representative["new_path"]),
                    "new_level": int(representative["new_level"]),
                }
            )
        return result

    async def _load_tag_snapshot(self, *, tenant_id: int, resource_ids: list[int]) -> dict[str, list[int]]:
        if not resource_ids:
            return {}
        resource_keys = [str(resource_id) for resource_id in resource_ids]
        statement = (
            select(TagLink.resource_id, TagLink.tag_id)
            .where(
                TagLink.tenant_id == int(tenant_id),
                TagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
                TagLink.resource_id.in_(resource_keys),
            )
            .order_by(TagLink.resource_id.asc(), TagLink.tag_id.asc())
        )
        snapshot = {resource_key: [] for resource_key in resource_keys}
        for resource_id, tag_id in (await self.session.exec(statement)).all():
            snapshot.setdefault(str(resource_id), []).append(int(tag_id))
        return snapshot

    async def _name_conflicts(
        self,
        *,
        tenant_id: int,
        space_id: int,
        root: KnowledgeFile,
        target_name: str,
    ) -> bool:
        conditions = [
            KnowledgeFile.tenant_id == int(tenant_id),
            KnowledgeFile.knowledge_id == int(space_id),
            KnowledgeFile.file_name == str(target_name),
            KnowledgeFile.id != int(root.id),
            KnowledgeFile.file_type == int(root.file_type),
        ]
        if int(root.file_type) == FileType.DIR.value:
            conditions.append(self._same_path_condition(self._path(root.file_level_path)))
        statement = select(func.count(KnowledgeFile.id)).where(*conditions)
        return int((await self.session.exec(statement)).one()) > 0

    async def _folder_move_name_conflicts(
        self,
        *,
        tenant_id: int,
        target_space_id: int,
        target_path: str,
        root: KnowledgeFile,
    ) -> bool:
        statement = select(func.count(KnowledgeFile.id)).where(
            KnowledgeFile.tenant_id == int(tenant_id),
            KnowledgeFile.knowledge_id == int(target_space_id),
            KnowledgeFile.file_type == FileType.DIR.value,
            KnowledgeFile.file_name == root.file_name,
            KnowledgeFile.id != int(root.id),
            self._same_path_condition(target_path),
        )
        return int((await self.session.exec(statement)).one()) > 0

    @staticmethod
    def _same_path_condition(path: str):
        if path:
            return KnowledgeFile.file_level_path == path
        return or_(KnowledgeFile.file_level_path == "", KnowledgeFile.file_level_path.is_(None))

    @staticmethod
    def _path(value: str | None) -> str:
        return str(value or "")

    @staticmethod
    def _resource_type_matches(row: KnowledgeFile, resource_type: str) -> bool:
        if resource_type == "folder":
            return int(row.file_type) == FileType.DIR.value
        if resource_type == "knowledge_file":
            return int(row.file_type) == FileType.FILE.value
        return False

    @classmethod
    def _row_snapshot(cls, row: KnowledgeFile | None) -> dict | None:
        if row is None:
            return None
        return {
            "id": int(row.id),
            "old_space_id": int(row.knowledge_id),
            "old_path": cls._path(row.file_level_path),
            "old_level": int(row.level or 0),
            "old_name": str(row.file_name),
            "old_status": int(row.status or 0),
            "file_type": int(row.file_type),
        }

    async def get_user_uploaded_file_size(
        self,
        *,
        tenant_id: int,
        user_id: int,
    ) -> int:
        """Mirror the upload quota owner's usage query with explicit tenant scope."""
        statement = select(func.coalesce(func.sum(KnowledgeFile.file_size), 0)).where(
            KnowledgeFile.tenant_id == int(tenant_id),
            KnowledgeFile.user_id == int(user_id),
            KnowledgeFile.file_type == FileType.FILE.value,
            col(KnowledgeFile.file_source).in_([*PORTAL_USER_UPLOAD_FILE_SOURCES, FileSource.CHANNEL.value]),
        )
        return int((await self.session.exec(statement)).one() or 0)

    async def get_formal_file(
        self,
        *,
        tenant_id: int,
        space_id: int,
        file_id: int,
        for_update: bool = False,
    ) -> KnowledgeFile | None:
        statement = select(KnowledgeFile).where(
            KnowledgeFile.tenant_id == int(tenant_id),
            KnowledgeFile.knowledge_id == int(space_id),
            KnowledgeFile.id == int(file_id),
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.exec(statement)).first()

    async def resolve_file_change_footprints(self, *, tenant_id: int, command) -> list[FootprintEntry]:
        """Expand one mutation into normalized relational conflict locks."""
        if command.action == "upload":
            return [
                FootprintEntry(
                    space_id=int(command.space_id),
                    resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
                    resource_id=0,
                )
            ]
        root = await self.get_formal_file(
            tenant_id=tenant_id,
            space_id=int(command.space_id),
            file_id=int(command.resource_id),
        )
        if root is None:
            raise LookupError(f"knowledge-space mutation resource not found: {command.resource_id}")
        parts = [int(part) for part in (root.file_level_path or "").split("/") if part]
        root_path = f"/{'/'.join(str(part) for part in [*parts, root.id])}/"
        entries = [
            FootprintEntry(
                space_id=int(command.space_id),
                resource_type="folder" if int(root.file_type) == FileType.DIR.value else "knowledge_file",
                resource_id=int(root.id),
                path_root=root_path,
                lock_scope=(
                    KnowledgeSpaceFileChangeLockScope.SUBTREE
                    if int(root.file_type) == FileType.DIR.value
                    else KnowledgeSpaceFileChangeLockScope.EXACT
                ),
            )
        ]
        if int(root.file_type) == FileType.FILE.value:
            document_id = (
                await self.session.exec(
                    select(KnowledgeDocumentVersion.document_id).where(
                        KnowledgeDocumentVersion.knowledge_file_id == int(root.id)
                    )
                )
            ).first()
            if document_id is not None:
                sibling_ids = (
                    await self.session.exec(
                        select(KnowledgeDocumentVersion.id)
                        .join(KnowledgeFile, KnowledgeFile.id == KnowledgeDocumentVersion.knowledge_file_id)
                        .where(
                            KnowledgeDocumentVersion.document_id == int(document_id),
                            KnowledgeFile.tenant_id == int(tenant_id),
                            KnowledgeFile.knowledge_id == int(command.space_id),
                        )
                    )
                ).all()
                entries.extend(
                    FootprintEntry(
                        space_id=int(command.space_id),
                        resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE_VERSION,
                        resource_id=int(row[0] if isinstance(row, tuple) else row),
                    )
                    for row in sibling_ids
                )
        if command.action != "move":
            return entries

        target_space_id = int(command.target_space_id)
        if command.target_parent_id is None:
            entries.append(
                FootprintEntry(
                    space_id=target_space_id,
                    resource_type="knowledge_space",
                    resource_id=target_space_id,
                    path_root="/",
                    lock_scope=KnowledgeSpaceFileChangeLockScope.DESTINATION,
                )
            )
            return entries

        parent = await self.get_folder(
            tenant_id=tenant_id,
            space_id=target_space_id,
            folder_id=int(command.target_parent_id),
        )
        if parent is None:
            raise LookupError(f"knowledge-space move target folder not found: {command.target_parent_id}")
        parent_parts = [int(part) for part in (parent.file_level_path or "").split("/") if part]
        for index, ancestor_id in enumerate(parent_parts):
            entries.append(
                FootprintEntry(
                    space_id=target_space_id,
                    resource_type="folder",
                    resource_id=ancestor_id,
                    path_root=f"/{'/'.join(str(part) for part in parent_parts[: index + 1])}/",
                )
            )
        entries.append(
            FootprintEntry(
                space_id=target_space_id,
                resource_type="folder",
                resource_id=int(parent.id),
                path_root=f"/{'/'.join(str(part) for part in [*parent_parts, parent.id])}/",
                lock_scope=KnowledgeSpaceFileChangeLockScope.DESTINATION,
            )
        )
        return entries

    async def list_successful_file_paths_using_folders(
        self,
        *,
        tenant_id: int,
        space_ids: list[int],
        ancestor_folder_ids: list[int],
    ) -> list[tuple[int, str]]:
        """Return published child paths that may release shared upload folders."""
        normalized_space_ids = sorted({int(space_id) for space_id in space_ids})
        normalized_folder_ids = sorted({int(folder_id) for folder_id in ancestor_folder_ids})
        if not normalized_space_ids or not normalized_folder_ids:
            return []
        path_conditions = []
        for folder_id in normalized_folder_ids:
            token = f"/{folder_id}"
            path_conditions.extend(
                (
                    KnowledgeFile.file_level_path == token,
                    KnowledgeFile.file_level_path.like(f"{token}/%"),
                    KnowledgeFile.file_level_path.like(f"%{token}/%"),
                    KnowledgeFile.file_level_path.like(f"%{token}"),
                )
            )
        statement = (
            select(KnowledgeFile.id, KnowledgeFile.file_level_path)
            .where(
                KnowledgeFile.tenant_id == int(tenant_id),
                KnowledgeFile.knowledge_id.in_(normalized_space_ids),
                KnowledgeFile.file_type == FileType.FILE.value,
                KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
                KnowledgeFile.file_level_path.is_not(None),
                or_(*path_conditions),
            )
            .order_by(KnowledgeFile.id.asc())
        )
        rows = (await self.session.exec(statement)).all()
        return [(int(file_id), str(file_level_path)) for file_id, file_level_path in rows]

    async def get_folder(
        self,
        *,
        tenant_id: int,
        space_id: int,
        folder_id: int,
        for_update: bool = False,
    ) -> KnowledgeFile | None:
        statement = select(KnowledgeFile).where(
            KnowledgeFile.tenant_id == int(tenant_id),
            KnowledgeFile.knowledge_id == int(space_id),
            KnowledgeFile.id == int(folder_id),
            KnowledgeFile.file_type == FileType.DIR.value,
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.exec(statement)).first()

    async def find_duplicate_file(
        self,
        *,
        tenant_id: int,
        space_id: int,
        file_name: str,
        content_hash: str,
    ) -> KnowledgeFile | None:
        statement = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.tenant_id == int(tenant_id),
                KnowledgeFile.knowledge_id == int(space_id),
                KnowledgeFile.file_type == FileType.FILE.value,
                or_(KnowledgeFile.file_name == file_name, KnowledgeFile.md5 == content_hash),
            )
            .order_by(KnowledgeFile.id.asc())
            .with_for_update()
        )
        return (await self.session.exec(statement)).first()

    async def get_folder_by_name_and_path(
        self,
        *,
        tenant_id: int,
        space_id: int,
        folder_name: str,
        file_level_path: str,
    ) -> KnowledgeFile | None:
        statement = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.tenant_id == int(tenant_id),
                KnowledgeFile.knowledge_id == int(space_id),
                KnowledgeFile.file_type == FileType.DIR.value,
                KnowledgeFile.file_name == folder_name,
                KnowledgeFile.file_level_path == file_level_path,
            )
            .order_by(KnowledgeFile.id.asc())
            .with_for_update()
        )
        return (await self.session.exec(statement)).first()

    async def add_folder(self, folder: KnowledgeFile) -> KnowledgeFile:
        self.session.add(folder)
        await self.session.flush()
        return folder

    async def add_formal_upload_bundle(
        self,
        *,
        file: KnowledgeFile,
        document: KnowledgeDocument,
        version: KnowledgeDocumentVersion,
    ) -> FormalUploadBundle:
        self.session.add(file)
        await self.session.flush()
        document.knowledge_id = int(file.knowledge_id)
        document.file_level_path = file.file_level_path
        document.level = int(file.level or 0)
        self.session.add(document)
        await self.session.flush()
        version.document_id = int(document.id)
        version.knowledge_file_id = int(file.id)
        self.session.add(version)
        await self.session.flush()
        document.primary_version_id = int(version.id)
        self.session.add(document)
        await self.session.flush()
        return FormalUploadBundle(file=file, document=document, version=version)
