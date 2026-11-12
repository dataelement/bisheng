"""Action-specific ordinary batch classification, without business side effects."""

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
from bisheng.knowledge.domain.repositories.knowledge_batch_repository import valid_path
from bisheng.knowledge.domain.schemas.knowledge_batch import BatchInspection
from bisheng.knowledge.domain.schemas.processing_job import OperationInvalidItem, OperationItem


def classify(scope, command, allowed):
    rows = {row["id"]: row for row in scope["files"]}
    valid, invalid, physical, positions = [], [], {}, []
    for index, item in enumerate(command.items):
        row = rows.get(item.id)
        members = [rows[ident] for ident in scope["units"][index]]
        reason = (
            "not_found"
            if row is None
            else "type_mismatch"
            if row["file_type"] != (0 if item.type == "folder" else 1)
            else None
        )
        chosen = members
        if reason is None and any(not valid_path(member) for member in members):
            reason = "unsupported"
        if reason is None and command.operation == "tag":
            reason = "unsupported" if item.type == "folder" else "processing" if row["status"] in (1, 5) else None
        elif reason is None and command.operation == "retry":
            chosen = [
                child
                for child in members
                if child["file_type"] == 1 and KnowledgeFileStatus.is_abnormal(child["status"])
            ]
            if not chosen:
                reason = "processing" if row["status"] in (1, 5) else "unsupported"
        elif reason is None and command.operation == "download":
            for child in chosen:
                if child["file_type"] not in (0, 1):
                    reason = "unsupported"
                    break
                if child["file_type"] == 1 and not (
                    child["preview_file_object_name"]
                    if child["file_source"] == "channel" and child["preview_file_object_name"]
                    else child["object_name"]
                ):
                    reason = "processing" if child["status"] in (1, 5) else "unsupported"
                    break
        needed = {child["id"] for child in chosen} | {item.id}
        if reason is None and not needed <= allowed:
            reason = "no_permission"
        if reason:
            invalid.append(
                OperationInvalidItem(
                    id=item.id,
                    type=item.type,
                    name=row["file_name"] if row and item.id in allowed else None,
                    reason=reason,
                )
            )
        else:
            positions.append(index)
            valid.append(OperationItem(id=item.id, type=item.type, name=row["file_name"]))
            physical.update((child["id"], child) for child in chosen)
    review = BatchInspection(
        can_execute=bool(valid),
        valid_items=valid,
        invalid_items=invalid,
        requires_skip_confirmation=bool(valid and invalid),
        impact={"item_count": len(valid), "file_count": sum(row["file_type"] == 1 for row in physical.values())},
    )
    return review, positions, [physical[key] for key in sorted(physical)]
