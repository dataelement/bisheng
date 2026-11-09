"""Actual processing commands; existing four-kind kernels retain their algorithms."""

from datetime import timedelta
from uuid import UUID, uuid5

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication
from bisheng.knowledge.application.processing_identity import capture_processing_actor
from bisheng.knowledge.application.processing_owner import KnowledgeProcessingOwner
from bisheng.knowledge.domain.schemas.processing_job import (
    OperationItem,
    ProcessingCreateRequest,
    ProcessingPrecheckRequest,
)
from bisheng.knowledge.domain.services.processing_job_service import ProcessingJobService


class KnowledgeProcessingCommands:
    def __init__(self, *, session_factory=get_async_db_session, service=None):
        self.sessions = session_factory
        self.service = (
            service
            if service is not None
            else ProcessingJobService(
                owner=KnowledgeProcessingOwner(),
                available_kinds={"embedding_rebuild", "file_reprocess", "file_resplit", "metadata_schema_change"},
            )
        )

    @staticmethod
    def _clean(session):
        if session.new or session.dirty or session.deleted:
            raise KnowledgeOperationPlanChangedError()

    async def aprecheck(self, space_id, request, *, identity, entry_kind="web"):
        request = ProcessingPrecheckRequest.model_validate(request.model_dump(mode="json"))
        selected = request.parameters.embedding_model_id if request.kind == "embedding_rebuild" else None
        if selected is not None:
            async with self.sessions() as session:
                await self.service._authorize(identity, space_id)
                scope = await self.service.scope.aload_scope(session, space_id)
                row = await KnowledgeModelReferenceApplication.repository.aget(session, space_id)
                if not any(item.status == 2 for item in scope) and row is not None and str(row.model) != str(selected):
                    self.service.require_rebuild_scope_ready(scope)
                    await self.service.scope.aassert_empty_model_change(session, space_id)
                    preview = await self.service.owner.apreview(
                        session, space_id, identity=identity, parameters=request.parameters.model_dump(mode="json")
                    )
                    target_revisions, source_revisions = self.service._versions(preview, scope)
                    actor = await capture_processing_actor(
                        identity, space_id=space_id, required_action="edit", entry_kind=entry_kind
                    )
                    result = await self.service.plans.acreate(
                        session,
                        operation=request.kind,
                        space_id=space_id,
                        actor_reference=actor.reference,
                        targets=[item.target for item in scope],
                        target_revisions=target_revisions,
                        source_revisions=source_revisions,
                        parameters=request.parameters.model_dump(mode="json"),
                        impact={
                            "configuration_only": True,
                            "retrieval_paused": False,
                            "preserves_chunks": True,
                            "whole_version_count": len(scope),
                        },
                        expires_at=self.service.plans.clock() + timedelta(minutes=5),
                    )
                    self._clean(session)
                    await session.commit()
                    return result.model_copy(
                        update={"can_execute": True, "valid_items": [OperationItem(id=space_id, type="space")]}
                    )
        async with self.sessions() as session:
            result = await self.service.aprecheck(session, space_id, request, identity=identity, entry_kind=entry_kind)
            self._clean(session)
            await session.commit()
            return result

    async def aconfirm(self, space_id, request, *, identity, entry_kind="web"):
        return await self._confirm(space_id, request, identity, entry_kind)

    async def alegacy_model_confirm(self, space_id, request, *, identity, name=None, description=None):
        return await self._confirm(
            space_id, request, identity, "web", metadata=(name, description), kind="embedding_rebuild"
        )

    async def alegacy_file_confirm(self, space_id, request, *, identity, file_id):
        return await self._confirm(space_id, request, identity, "web", file_id=file_id)

    async def _confirm(self, space_id, request, identity, entry_kind, *, metadata=None, kind=None, file_id=None):
        request = ProcessingCreateRequest.model_validate(request.model_dump(mode="json"))
        async with self.sessions() as session:
            plan = await self.service.plans._locked(session, request.confirmation_id)
            if kind is not None and plan.operation != kind:
                raise KnowledgeOperationPlanChangedError()
            if file_id is not None and (
                plan.operation not in {"file_reprocess", "file_resplit"}
                or {item["file_id"] for item in plan.target_manifest} != {file_id}
            ):
                raise KnowledgeOperationPlanChangedError()
            if not plan.impact.get("configuration_only"):
                result = await self.service.acreate(
                    session, space_id, request, identity=identity, entry_kind=entry_kind
                )
            else:
                result = await self._configuration(session, space_id, request, plan, identity, entry_kind)
            if metadata is not None:
                row = await KnowledgeModelReferenceApplication.repository.aget(session, space_id, for_update=True)
                name, description = metadata
                if name is not None:
                    row.name = name
                row.description = description
                await KnowledgeModelReferenceApplication.repository.asave(session, row)
            self._clean(session)
            await session.commit()
            return result

    async def _configuration(self, session, space_id, request, plan, identity, entry_kind):
        await self.service._authorize(identity, space_id)
        actor = await capture_processing_actor(
            identity, space_id=space_id, required_action="edit", entry_kind=entry_kind
        )
        plan = await self.service.plans.aget_for_execution(
            session,
            request.confirmation_id,
            space_id=space_id,
            operation="embedding_rebuild",
            actor_reference=actor.reference,
            plan_digest=request.plan_digest,
        )
        operation_id = str(uuid5(UUID(plan.id), request.idempotency_key))
        if plan.operation_id not in (None, operation_id):
            raise KnowledgeOperationPlanChangedError()
        selected = plan.parameters["embedding_model_id"]
        if plan.operation_id is None:
            scope = await self.service.scope.aload_scope(session, space_id)
            self.service.require_rebuild_scope_ready(scope)
            prepared = await KnowledgeModelReferenceApplication.aprepare_empty_model_change(
                session,
                space_id,
                selected,
                login_user=await self.service.owner._operator(identity),
                expected_model_config_revision=plan.source_revisions["model_config_revision"],
                expected_index_generation=plan.source_revisions["index_generation"],
                operation_id=plan.id,
            )
            targets, source = self.service._versions(prepared, scope)
            if targets != plan.target_revisions or source != plan.source_revisions:
                raise KnowledgeOperationPlanChangedError()
            row = await KnowledgeModelReferenceApplication.aapply_model_change(session, prepared)
            await self.service.plans.aconsume(
                session, plan.id, operation_id=operation_id, expected_digest=plan.plan_digest
            )
        else:
            current = await self.service.owner.aread_current(session, space_id, identity=identity)
            row = await KnowledgeModelReferenceApplication.repository.aget(session, space_id)
            if (
                str(current.model_id) != str(selected)
                or row.model_transition is not None
                or row.model_config_revision != plan.source_revisions["model_config_revision"] + 1
            ):
                raise KnowledgeOperationPlanChangedError()
        return {
            "completed": True,
            "operation": "embedding_rebuild",
            "space_id": space_id,
            "model_config_revision": row.model_config_revision,
        }
