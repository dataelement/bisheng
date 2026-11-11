"""Freeze reviewable knowledge deletion plans without changing business resources."""

from dataclasses import asdict
from datetime import timedelta

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.knowledge.application import deletion_admission as admission
from bisheng.knowledge.domain.repositories.knowledge_deletion_execution_repository import OPERATIONS
from bisheng.knowledge.domain.repositories.operation_plan_repository import _now
from bisheng.knowledge.domain.repositories.source_move_input_repository import SourceMoveInputRepository
from bisheng.knowledge.domain.schemas.direct_delete_scope import select_delete_scope as _selected
from bisheng.knowledge.domain.schemas.processing_job import OperationInvalidItem, OperationItem, ResourceVersionTarget
from bisheng.knowledge.domain.services.knowledge_processing_guard import require_space_processing_idle
from bisheng.knowledge.domain.services.knowledge_reference_service import impact_digest
from bisheng.resource_reference.application.contracts import SourceType


async def _denied_review(owner, *, space_id, reference, selections):
    """No permitted target: report only submitted IDs and no dependency facts."""
    pin = await owner._pin()
    async with owner._session() as session:
        result = await owner.plans.acreate(
            session,
            operation="knowledge_file_delete",
            space_id=space_id,
            actor_reference=reference,
            targets=[],
            target_revisions={},
            source_revisions={},
            parameters={
                "can_execute": False,
                "selections": [],
                "requested_selections": [asdict(row) for row in selections],
                "authorized_positions": [],
                "valid_positions": [],
                "force": False,
                "pin": pin,
            },
            impact={
                "source_counts": {kind.value: 0 for kind in SourceType},
                "restricted_counts": {kind.value: 0 for kind in SourceType},
                "file_count": 0,
                "source_page": {"data": [], "page_size": 50, "has_more": False, "next_cursor": None},
            },
            expires_at=_now() + timedelta(minutes=5),
        )
    return result.model_copy(
        update={
            "can_execute": False,
            "valid_items": [],
            "invalid_items": [
                OperationInvalidItem(
                    id=row.resource_id,
                    type="folder" if row.resource_type == "folder" else "file",
                    reason="no_permission",
                )
                for row in selections
            ],
        }
    )


async def precheck_deletion(
    owner,
    *,
    identity,
    space_id,
    selections=(),
    operation="knowledge_file_delete",
    force=False,
    historical_version_id=None,
):
    if operation not in OPERATIONS or type(force) is not bool or (force and operation != "knowledge_space_delete"):
        raise ResourceReferenceInvalidError(reason="knowledge_delete_force_not_supported")
    reference = await admission.capture(identity, space_id=space_id)
    async with admission.identity(reference, current=identity) as (actual, _):
        whole = operation != "knowledge_file_delete"
        requested = selections
        authorized = tuple(range(len(selections))) if whole else await admission.selected_positions(actual, selections)
        if not whole:
            if not selections:
                raise ResourceReferenceInvalidError(reason="knowledge_delete_selection_required")
            if not authorized:
                return await _denied_review(owner, space_id=space_id, reference=reference, selections=requested)
            selections = tuple(requested[position] for position in authorized)
        inspection = await owner.references.ainspect(
            identity=actual, space_id=space_id, selections=selections, whole_space=whole
        )
        scope, facts = inspection.facts.scope, inspection.facts
        if historical_version_id is not None:
            chosen_ids = {ident for unit in scope.units for ident in unit.version_ids}
            version = next((row for row in scope.versions if row.id == historical_version_id), None)
            if (
                operation != "knowledge_file_delete"
                or chosen_ids != {historical_version_id}
                or version is None
                or version.is_primary
            ):
                raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_historical_version_changed")
        allowed = None if whole else await owner._permissions(actual, scope)
        authorized_set = frozenset(authorized)
        invalid = [
            OperationInvalidItem(
                id=row.resource_id, type="folder" if row.resource_type == "folder" else "file", reason="no_permission"
            )
            for position, row in enumerate(requested)
            if not whole and position not in authorized_set
        ]
        valid_positions = []
        referenced = {row.unit_index for row in facts.references}
        for issue in scope.issues:
            invalid.extend(
                OperationInvalidItem(
                    id=scope.selections[pos].resource_id,
                    type="folder" if scope.selections[pos].resource_type == "folder" else "file",
                    reason=issue.reason,
                )
                for pos in issue.positions
            )
        for index, unit in enumerate(scope.units):
            reason = (
                "referenced"
                if index in referenced and not whole
                else "processing"
                if unit.processing_file_ids
                else "no_permission"
                if allowed is not None and not set(unit.resource_ids) <= allowed
                else None
            )
            if reason is None:
                valid_positions.extend(unit.selection_positions)
            else:
                invalid.extend(
                    OperationInvalidItem(
                        id=scope.selections[pos].resource_id,
                        type="folder" if scope.selections[pos].resource_type == "folder" else "file",
                        reason=reason,
                    )
                    for pos in unit.selection_positions
                )
        if whole:
            valid_positions = list(range(len(scope.selections)))
        positions = tuple(sorted(set(valid_positions)))
        chosen = _selected(scope, positions)
        executable = (
            (whole or bool(chosen.resources))
            and (not whole or not inspection.blocked or force)
            and (not whole or not any(unit.processing_file_ids for unit in scope.units))
        )
        pin = await owner._pin()
        async with owner._session() as session:
            root, root_revision = await owner.execution.aroot(session, space_id, lock=True)
            require_space_processing_idle(root, operation="delete")
            if whole:
                await SourceMoveInputRepository().arequire_released(session, space_id=space_id)
            current = await owner._collect(session, space_id=space_id, selections=selections, operation=operation)
            if current != facts:
                raise KnowledgeOperationPlanConflictError(reason="knowledge_delete_precheck_changed")
            ids = {ident for unit in chosen.units for ident in unit.version_ids}
            result = await owner.plans.acreate(
                session,
                operation=operation,
                space_id=space_id,
                actor_reference=reference,
                targets=[
                    ResourceVersionTarget(file_id=row.knowledge_file_id, document_id=row.document_id, version_id=row.id)
                    for row in chosen.versions
                    if row.id in ids
                ],
                target_revisions={
                    "scope": inspection.scope_digest,
                    "selected_scope": impact_digest(asdict(chosen)),
                },
                source_revisions={
                    "inbound": inspection.inbound_digest,
                    "root": root_revision,
                    "epoch": facts.coverage_epoch,
                    "inventory": facts.inventory_hash,
                },
                parameters={
                    "selections": [asdict(row) for row in selections],
                    "requested_selections": [asdict(row) for row in requested],
                    "authorized_positions": list(authorized),
                    "valid_positions": list(positions),
                    "force": force,
                    "can_execute": executable,
                    "historical_version_id": historical_version_id,
                    "pin": pin,
                },
                impact={
                    "source_counts": dict(inspection.source_counts),
                    "restricted_counts": dict(inspection.restricted_counts),
                    "source_page": asdict(inspection.source_page),
                    "file_count": len(chosen.resources),
                },
                expires_at=_now() + timedelta(minutes=5),
            )
        names = {fact.id: fact.file_name for fact in scope.resources}
        valid = (
            [OperationItem(id=space_id, type="space", name=scope.cleanup_identity.get("name"))]
            if whole
            else [
                OperationItem(
                    id=row.resource_id,
                    type="folder" if row.resource_type == "folder" else "file",
                    name=names.get(row.resource_id),
                )
                for row in chosen.selections
            ]
        )
        return result.model_copy(
            update={
                "check_complete": True,
                "can_execute": executable,
                "valid_items": valid,
                "invalid_items": invalid,
                "requires_skip_confirmation": bool(invalid and valid),
            }
        )
