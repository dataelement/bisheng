"""Authorized metadata schema acceptance; orchestration owns job dispatch."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from weakref import WeakKeyDictionary

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.knowledge.application.model_reference_read import get_knowledge_model_read_runtime
from bisheng.knowledge.application.processing_identity import capture_processing_actor
from bisheng.knowledge.domain.repositories.metadata_execution_repository import MetadataExecutionRepository
from bisheng.knowledge.domain.repositories.metadata_processing_repository import metadata_digest
from bisheng.knowledge.domain.repositories.processing_job_repository import (
    NewProcessingItem,
    ProcessingConfiguration,
    ProcessingJobRepository,
    _MetadataCompletionAuthority,
)
from bisheng.knowledge.domain.schemas.processing_job import MetadataSchemaParameters
from bisheng.knowledge.domain.services.metadata_processing_service import MetadataProcessingService
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.resource_reference.application.contracts import TransactionIdentity


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class PreparedMetadataOperation:
    space_id: int
    configuration: ProcessingConfiguration
    parameters: dict = field(repr=False)
    source_revisions: dict = field(repr=False)
    core_plan: object = field(repr=False)


@dataclass(frozen=True, slots=True)
class AcceptedMetadataOperation:
    space_id: int
    configuration: ProcessingConfiguration
    actor_user_id: int
    actor_reference: dict = field(repr=False)
    parameters: dict = field(repr=False)
    items: tuple[NewProcessingItem, ...] = field(repr=False)
    metadata_acceptance: object = field(default=None, repr=False)


class MetadataProcessingOwner:
    def __init__(self, *, jobs=None, model_owner=None):
        self.jobs = jobs if jobs is not None else ProcessingJobRepository()
        self.execution = MetadataExecutionRepository(jobs=self.jobs)
        self.core = MetadataProcessingService()
        self.model_owner = model_owner
        self._issued = WeakKeyDictionary()
        self._completion = _MetadataCompletionAuthority(self)

    @staticmethod
    async def _actor(identity, space_id):
        actor = await capture_processing_actor(
            identity,
            space_id=space_id,
            required_action="edit",
            entry_kind="open_api" if isinstance(identity, OpenApiPrincipal) else "web",
        )
        await require_business_action(identity, resource_type="knowledge_space", resource_id=space_id, action="edit")
        return actor

    def _signature(self, prepared):
        return metadata_digest(
            {
                "space_id": prepared.space_id,
                "configuration": asdict(prepared.configuration),
                "parameters": prepared.parameters,
                "sources": prepared.source_revisions,
                "core": self.core._signature(prepared.core_plan),
            }
        )

    async def _amodel_configuration(self, session, space_id, *, identity):
        if self.model_owner is not None:
            return (await self.model_owner.aread_current(session, space_id, identity=identity)).configuration
        runtime = await get_knowledge_model_read_runtime()
        admitted = await runtime.arequire(
            space_id, login_user=None if isinstance(identity, OpenApiPrincipal) else identity, session=session
        )
        return ProcessingConfiguration(admitted.model_config_revision, admitted.index_generation)

    def _check(self, session, prepared):
        issued = self._issued.get(prepared) if isinstance(prepared, PreparedMetadataOperation) else None
        try:
            if issued is None:
                raise ValueError("metadata operation was not issued")
            issued[0].assert_current(session)
            if self._signature(prepared) != issued[1]:
                raise ValueError("metadata operation changed")
            self.core._check(session, prepared.core_plan)
        except (ValueError, TypeError, AttributeError) as error:
            raise ResourceReferenceInvalidError(reason="metadata_owner_plan_invalid") from error
        return issued

    async def apreview(self, session, space_id, *, identity, parameters):
        parameters = MetadataSchemaParameters.model_validate(parameters.model_dump(mode="json"))
        actor = await self._actor(identity, space_id)
        core = await self.core.apreview(session, space_id, parameters)
        if core.items:
            current = await self._amodel_configuration(session, space_id, identity=identity)
            if (current.model_config_revision, current.index_generation) != (
                core.model_config_revision,
                core.index_generation,
            ):
                raise KnowledgeOperationPlanConflictError(reason="metadata_owner_model_changed")
        configuration = ProcessingConfiguration(
            core.model_config_revision,
            core.index_generation,
            metadata_schema_revision=core.after_schema_revision,
            metadata_schema_digest=metadata_digest(core.after_schema),
        )
        sources = {
            "model_config_revision": core.model_config_revision,
            "index_generation": core.index_generation,
            "metadata_schema_revision": core.before_schema_revision,
            "metadata_schema_digest": metadata_digest(core.before_schema),
            "scope_digest": metadata_digest(self.core._scope_facts(core._scope)),
            "versions": {
                f"{item.target.file_id}:{item.target.version_id}": {
                    "source_revision": item.source_revision,
                    "values_revision": item.before_values_digest,
                    "parent_id": item.parent_id,
                    "status": item.original_status,
                }
                for item in core.items
            },
        }
        prepared = PreparedMetadataOperation(space_id, configuration, parameters.model_dump(mode="json"), sources, core)
        self._issued[prepared] = (TransactionIdentity.capture(session), self._signature(prepared), actor.payload_json)
        return prepared

    async def _aperform_metadata_acceptance(self, session, prepared, *, identity):
        issued = self._check(session, prepared)
        actor = await self._actor(identity, prepared.space_id)
        if actor.payload_json != issued[2]:
            raise ResourceReferenceInvalidError(reason="metadata_owner_actor_changed")
        if prepared.core_plan.items:
            current = await self._amodel_configuration(session, prepared.space_id, identity=identity)
            if (current.model_config_revision, current.index_generation) != (
                prepared.configuration.model_config_revision,
                prepared.configuration.index_generation,
            ):
                raise KnowledgeOperationPlanConflictError(reason="metadata_owner_model_changed")
        core = await self.core.aaccept(session, prepared.core_plan)
        actual = await self.execution.aread_configuration(session, prepared.space_id)
        if asdict(actual) != asdict(prepared.configuration):
            raise KnowledgeOperationPlanConflictError(reason="metadata_owner_schema_changed")
        affected = tuple(
            dict.fromkeys(
                name
                for change in core.changes
                for name in (change["field_name"], change.get("new_field_name"))
                if name is not None
            )
        )
        items = tuple(
            NewProcessingItem(
                target=deepcopy(item.target),
                expected_space_id=prepared.space_id,
                expected_parent_id=item.parent_id,
                processing_snapshot={
                    "schema_version": 1,
                    "mode": "metadata_schema_change",
                    "target": item.target.model_dump(mode="json"),
                    "parent_id": item.parent_id,
                    "source_revision": item.source_revision,
                    "before_values": deepcopy(item.before_values),
                    "after_values": deepcopy(item.after_values),
                    "before_values_digest": item.before_values_digest,
                    "after_values_digest": item.after_values_digest,
                    "original_status": item.original_status,
                    "affected_fields": list(affected),
                },
            )
            for item in core.items
        )
        del self._issued[prepared]
        return AcceptedMetadataOperation(
            prepared.space_id,
            prepared.configuration,
            actor.actor_user_id,
            actor.reference,
            {
                "request_parameters": deepcopy(prepared.parameters),
                "metadata_schema_revision": core.after_schema_revision,
                "metadata_schema_digest": metadata_digest(core.after_schema),
                "after_schema": deepcopy(list(core.after_schema)),
                "changed_at": core.changed_at,
            },
            items,
        )

    async def aaccept(self, session, prepared, *, identity):
        self._check(session, prepared)
        accepted, receipt = await self._completion.aaccept(session, prepared, identity=identity)
        return replace(accepted, metadata_acceptance=receipt)
