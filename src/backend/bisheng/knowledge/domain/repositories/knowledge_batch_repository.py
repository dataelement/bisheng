"""Native ordinary-batch facts and atomic effects. Caller owns transaction/commit."""

from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import update
from sqlmodel import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services.knowledge_processing_guard import require_space_processing_idle
from bisheng.resource_reference.application.contracts import TransactionIdentity

_FIELDS = (
    "id",
    "knowledge_id",
    "tenant_id",
    "user_id",
    "file_type",
    "file_name",
    "file_level_path",
    "status",
    "object_name",
    "preview_file_object_name",
    "file_source",
    "split_rule",
    "update_time",
)


def fact(row):
    values = {
        name: (getattr(row, name).isoformat() if hasattr(getattr(row, name), "isoformat") else getattr(row, name))
        for name in _FIELDS
    }
    # Bind retry configuration without persisting its potentially sensitive raw JSON.
    values["split_rule"] = sha256((row.split_rule or "").encode()).hexdigest()
    return values


def ancestors(row):
    # Only canonical numeric path segments identify ancestors. An unrelated
    # malformed path must not turn an ordinary batch into a global audit.
    parts = [part for part in (row["file_level_path"] or "").split("/") if part]
    return tuple(
        int(part) for part in parts if part.isascii() and part.isdigit() and int(part) > 0 and str(int(part)) == part
    )


def valid_path(row):
    parts = [part for part in (row["file_level_path"] or "").split("/") if part]
    return all(part.isascii() and part.isdigit() and int(part) > 0 and str(int(part)) == part for part in parts)


class KnowledgeBatchRepository:
    async def aread(self, session, *, space_id, command, lock=False):
        tenant = get_current_tenant_id()
        if type(tenant) is not int or tenant <= 0 or is_tenant_filter_bypassed() or not session.in_transaction():
            raise KnowledgeOperationPlanChangedError(reason="batch_native_context_required")
        transaction = TransactionIdentity.capture(session)

        async def query(statement):
            transaction.assert_current(session)
            if get_current_tenant_id() != tenant or is_tenant_filter_bypassed():
                raise KnowledgeOperationPlanChangedError(reason="batch_context_changed")
            if lock:
                statement = statement.with_for_update().execution_options(populate_existing=True)
            with session.no_autoflush, strict_tenant_filter():
                rows = (await session.exec(statement)).all()
            transaction.assert_current(session)
            if get_current_tenant_id() != tenant or is_tenant_filter_bypassed():
                raise KnowledgeOperationPlanChangedError(reason="batch_context_changed")
            return rows

        roots = await query(select(Knowledge).where(Knowledge.id == space_id, Knowledge.tenant_id == tenant))
        if len(roots) != 1 or roots[0].type != 3:
            raise SpaceNotFoundError()
        if command.operation == "retry":
            require_space_processing_idle(roots[0], operation="retry")
        records = []
        base = select(KnowledgeFile).where(KnowledgeFile.knowledge_id == space_id, KnowledgeFile.tenant_id == tenant)
        if any(item.type == "folder" for item in command.items):
            after = 0
            while True:
                page = await query(base.where(KnowledgeFile.id > after).order_by(KnowledgeFile.id).limit(200))
                records.extend(page)
                if len(page) < 200:
                    break
                after = page[-1].id
        else:
            ids = sorted({item.id for item in command.items})
            for offset in range(0, len(ids), 200):
                records.extend(
                    await query(base.where(KnowledgeFile.id.in_(ids[offset : offset + 200])).order_by(KnowledgeFile.id))
                )
        by_id = {row.id: fact(row) for row in records}
        path_ids = sorted({ident for row in by_id.values() for ident in ancestors(row)} - set(by_id))
        for offset in range(0, len(path_ids), 200):
            for row in await query(
                base.where(KnowledgeFile.id.in_(path_ids[offset : offset + 200])).order_by(KnowledgeFile.id)
            ):
                by_id[row.id] = fact(row)
        selected_folders = {
            item.id
            for item in command.items
            if item.type == "folder" and item.id in by_id and by_id[item.id]["file_type"] == 0
        }
        descendants = {ident: [] for ident in selected_folders}
        for child in by_id.values():
            for ident in ancestors(child):
                if ident in descendants:
                    descendants[ident].append(child["id"])
        units = []
        for item in command.items:
            row = by_id.get(item.id)
            ids = [item.id] if row else []
            if row and item.type == "folder" and row["file_type"] == 0:
                ids.extend(descendants[item.id])
            units.append(sorted(set(ids)))
        used = {ident for unit in units for ident in unit}
        used.update(ident for key in tuple(used) for ident in ancestors(by_id[key]))
        by_id = {key: row for key, row in by_id.items() if key in used}
        tags = []
        if command.operation == "tag":
            tags = [
                {"id": row.id, "name": row.name}
                for row in await query(
                    select(Tag)
                    .where(
                        Tag.tenant_id == tenant,
                        Tag.business_type == "knowledge_space",
                        Tag.business_id == str(space_id),
                    )
                    .order_by(Tag.id)
                )
            ]
            if not set(command.tag_ids) <= {row["id"] for row in tags}:
                raise KnowledgeOperationPlanChangedError(reason="batch_tag_scope_changed")
        return {
            "root": {"id": space_id, "tenant_id": tenant},
            "files": [by_id[key] for key in sorted(by_id)],
            "units": units,
            "tags": tags,
        }

    @staticmethod
    def _write_guard(session):
        tx, tenant = TransactionIdentity.capture(session), get_current_tenant_id()

        def check():
            tx.assert_current(session)
            if get_current_tenant_id() != tenant or is_tenant_filter_bypassed():
                raise KnowledgeOperationPlanChangedError(reason="batch_write_context_changed")

        async def call(awaitable):
            try:
                check()
            except BaseException:
                if hasattr(awaitable, "close"):
                    awaitable.close()
                raise
            result = await awaitable
            check()
            return result

        return call

    async def atag(self, session, *, scope, files, command, user_id):
        if not command.tag_ids and not command.new_tag_names:
            return
        call = self._write_guard(session)
        tenant = scope["root"]["tenant_id"]
        ids = list(command.tag_ids)
        tags = {row["name"]: row["id"] for row in scope["tags"]}
        for name in command.new_tag_names:
            if name in tags:
                ids.append(tags[name])
            else:
                row = Tag(
                    tenant_id=tenant,
                    business_type="knowledge_space",
                    business_id=str(scope["root"]["id"]),
                    name=name,
                    user_id=user_id,
                )
                session.add(row)
                await call(session.flush())
                ids.append(row.id)
        ids = set(ids)
        file_ids = sorted({row["id"] for row in files})
        existing = set()
        for offset in range(0, len(file_ids), 200):
            rows = (
                await call(
                    session.exec(
                        select(TagLink).where(
                            TagLink.tenant_id == tenant,
                            TagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
                            TagLink.resource_id.in_([str(ident) for ident in file_ids[offset : offset + 200]]),
                        )
                    )
                )
            ).all()
            existing.update((row.resource_id, row.tag_id) for row in rows)
        for ident in file_ids:
            for tag_id in ids:
                if (str(ident), tag_id) not in existing:
                    session.add(
                        TagLink(
                            tenant_id=tenant,
                            resource_id=str(ident),
                            resource_type=ResourceTypeEnum.SPACE_FILE.value,
                            tag_id=tag_id,
                            user_id=user_id,
                        )
                    )
        await call(
            session.execute(
                update(Knowledge)
                .where(Knowledge.id == scope["root"]["id"], Knowledge.tenant_id == tenant)
                .values(update_time=datetime.now(UTC).replace(tzinfo=None))
            )
        )
        await call(session.flush())

    async def await_retry(self, session, *, space_id, files, folder_ids=()):
        call = self._write_guard(session)
        tenant = get_current_tenant_id()
        ids = sorted({row["id"] for row in files})
        if not ids:
            return
        for offset in range(0, len(ids), 200):
            await call(
                session.execute(
                    update(KnowledgeFile)
                    .where(
                        KnowledgeFile.tenant_id == tenant,
                        KnowledgeFile.knowledge_id == space_id,
                        KnowledgeFile.id.in_(ids[offset : offset + 200]),
                    )
                    .values(status=5, remark="batch_retry_failed_files")
                )
            )
        folders = sorted(set(folder_ids))
        for offset in range(0, len(folders), 200):
            await call(
                session.execute(
                    update(KnowledgeFile)
                    .where(
                        KnowledgeFile.tenant_id == tenant,
                        KnowledgeFile.knowledge_id == space_id,
                        KnowledgeFile.file_type == 0,
                        KnowledgeFile.id.in_(folders[offset : offset + 200]),
                    )
                    .values(update_time=datetime.now(UTC).replace(tzinfo=None))
                )
            )
        await call(
            session.execute(
                update(Knowledge)
                .where(Knowledge.id == space_id, Knowledge.tenant_id == tenant)
                .values(update_time=datetime.now(UTC).replace(tzinfo=None))
            )
        )
        await call(session.flush())
