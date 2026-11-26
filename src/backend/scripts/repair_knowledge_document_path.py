"""Repair one unambiguous legacy document path; preview first, then apply its digest."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

_BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def inspect_path(session, *, tenant_id, space_id, file_id, lock=False):
    from sqlmodel import select

    from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
    from bisheng.knowledge.domain.repositories.source_move_input_repository import SourceMoveInputRepository
    from bisheng.knowledge.domain.schemas.move_processing import move_path_ids
    from bisheng.permission.domain.models import ResourcePermissionMode

    if get_current_tenant_id() != tenant_id:
        raise ValueError("tenant context mismatch")

    async def rows(model, *conditions):
        query = select(model).where(*conditions)
        with strict_tenant_filter():
            return (await session.exec(query.with_for_update() if lock else query)).all()

    def one(values):
        if len(values) != 1:
            raise ValueError("a unique, existing resource is required")
        return values[0]

    space = one(await rows(Knowledge, Knowledge.id == space_id))
    if space.tenant_id != tenant_id or space.type != 3 or space.state != 1 or space.model_transition is not None:
        raise ValueError("space must be current, published and idle in the selected tenant")
    await SourceMoveInputRepository().arequire_released(session, space_id=space_id)
    active = await rows(
        KnowledgeProcessingJob,
        KnowledgeProcessingJob.space_id == space_id,
        KnowledgeProcessingJob.state.in_(("accepted", "running")),
    )
    if active:
        raise ValueError("processing job is active")
    file = one(await rows(KnowledgeFile, KnowledgeFile.id == file_id))
    if file.tenant_id != tenant_id or file.knowledge_id != space_id or file.file_type != 1 or file.status in (1, 4, 5):
        raise ValueError("file must be an idle physical file in this space")
    version = one(await rows(KnowledgeDocumentVersion, KnowledgeDocumentVersion.knowledge_file_id == file_id))
    doc = one(await rows(KnowledgeDocument, KnowledgeDocument.id == version.document_id))
    versions = await rows(KnowledgeDocumentVersion, KnowledgeDocumentVersion.document_id == doc.id)
    if (
        doc.knowledge_id != space_id
        or len(versions) != 1
        or not version.is_primary
        or doc.primary_version_id != version.id
    ):
        raise ValueError("only an unambiguous single primary version can be repaired")
    path = move_path_ids(file.file_level_path)
    if file.level != len(path) or file.file_level_path != ("/" + "/".join(map(str, path)) if path else ""):
        raise ValueError("physical file path is not canonical")
    parents = []
    for index, ident in enumerate(path):
        folder = one(await rows(KnowledgeFile, KnowledgeFile.id == ident))
        if (
            folder.tenant_id != tenant_id
            or folder.knowledge_id != space_id
            or folder.file_type != 0
            or folder.level != index
            or move_path_ids(folder.file_level_path) != path[:index]
        ):
            raise ValueError("physical parent chain is invalid")
        parents.append({"id": folder.id, "path": folder.file_level_path, "level": folder.level})
    mode = one(
        await rows(
            ResourcePermissionMode,
            ResourcePermissionMode.resource_type == "knowledge_file",
            ResourcePermissionMode.resource_id == str(file_id),
        )
    )
    expected_parent = ("folder", str(path[-1])) if path else ("knowledge_space", str(space_id))
    if (
        mode.tenant_id != tenant_id
        or mode.projection_state != "CURRENT"
        or (mode.parent_type, mode.parent_id) != expected_parent
    ):
        raise ValueError("current permission parent does not confirm the physical path")
    facts = {
        "tenant_id": tenant_id,
        "space_id": space_id,
        "file_id": file_id,
        "model_config_revision": space.model_config_revision,
        "index_generation": space.index_generation,
        "file": {"path": file.file_level_path, "level": file.level, "status": file.status},
        "document": {
            "id": doc.id,
            "path": doc.file_level_path,
            "level": doc.level,
            "primary_version_id": doc.primary_version_id,
        },
        "version": {"id": version.id, "version_no": version.version_no},
        "parents": parents,
        "permission_mode": {"id": mode.id, "version": mode.version, "parent": expected_parent},
    }
    # JSON normalization makes persisted previews and their in-memory facts identical.
    facts = json.loads(json.dumps(facts))
    return facts, doc


async def repair(session, *, tenant_id, space_id, file_id, apply=False, expected_digest=None, backup=None):
    from bisheng.knowledge.domain.models.knowledge_processing_job import processing_now

    facts, doc = await inspect_path(session, tenant_id=tenant_id, space_id=space_id, file_id=file_id, lock=apply)
    checksum = digest(facts)
    result = {"facts": facts, "digest": checksum, "applied": False}
    if apply and (expected_digest != checksum or backup is None):
        raise ValueError("apply requires the unchanged preview digest and a new private backup path")
    if (doc.file_level_path, doc.level) == (facts["file"]["path"], facts["file"]["level"]):
        return {**result, "already_consistent": True}
    if apply:
        descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        doc.file_level_path, doc.level = facts["file"]["path"], facts["file"]["level"]
        doc.update_time = processing_now()
        session.add(doc)
        await session.flush()
        # The caller commits only after the exact validated document is changed.
        result["applied"] = True
    return result


async def main():
    from bisheng.core.context.manager import close_app_context
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
    from bisheng.core.database import get_async_db_session, get_database_connection

    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("tenant-id", "space-id", "file-id"):
        parser.add_argument("--" + field, type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-digest")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if min(args.tenant_id, args.space_id, args.file_id) <= 0:
        parser.error("identifiers must be positive")
    token = set_current_tenant_id(args.tenant_id)
    try:
        async with get_async_db_session() as session:
            result = await repair(
                session,
                tenant_id=args.tenant_id,
                space_id=args.space_id,
                file_id=args.file_id,
                apply=args.apply,
                expected_digest=args.expected_digest,
                backup=args.backup,
            )
            if args.apply:
                await session.commit()
            else:
                await session.rollback()
            print(json.dumps(result, ensure_ascii=False))
    finally:
        current_tenant_id.reset(token)
        await (await get_database_connection()).close()
        await close_app_context()


if __name__ == "__main__":
    asyncio.run(main())
