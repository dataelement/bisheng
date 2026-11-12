"""Atomic metadata preparation; the authorized Owner owns the transaction.

This core has no public route, credential restoration, task dispatch, model
admission, index I/O or File value writer. Those join through later Owners.
"""

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from weakref import WeakKeyDictionary

from pydantic import ValidationError

from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.common.errcode.knowledge import (
    KnowledgeMetadataFieldConflictError,
    KnowledgeMetadataFieldExistError,
    KnowledgeMetadataFieldImmutableError,
    KnowledgeMetadataFieldNotExistError,
    KnowledgeOperationPlanConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.knowledge.domain.repositories.metadata_processing_repository import (
    MetadataProcessingRepository,
    MetadataScope,
    metadata_digest,
)
from bisheng.knowledge.domain.schemas.knowledge_schema import MetadataField
from bisheng.knowledge.domain.schemas.processing_job import MetadataSchemaParameters, ResourceVersionTarget
from bisheng.resource_reference.application.contracts import TransactionIdentity


def metadata_change_timestamp() -> int:
    return int(datetime.now(UTC).timestamp())


@dataclass(frozen=True, slots=True)
class PreparedMetadataItem:
    target: ResourceVersionTarget
    parent_id: int | None
    original_status: int
    source_revision: str
    before_values_digest: str
    after_values_digest: str
    before_values: dict | None = field(repr=False)
    after_values: dict | None = field(repr=False)


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class PreparedMetadataSchema:
    tenant_id: int
    space_id: int
    before_schema_revision: int
    after_schema_revision: int
    model_config_revision: int
    index_generation: str | None
    changed_at: int
    parameters_digest: str
    before_schema: tuple[dict, ...] = field(repr=False)
    after_schema: tuple[dict, ...] = field(repr=False)
    changes: tuple[dict, ...] = field(repr=False)
    items: tuple[PreparedMetadataItem, ...]
    _scope: MetadataScope = field(repr=False)
    accepted: bool = False


@dataclass(slots=True)
class _IssuedMetadataPlan:
    transaction: TransactionIdentity
    signature: str
    consumed: bool = False


class MetadataProcessingService:
    def __init__(self, repository=None):
        self.repository = repository if repository is not None else MetadataProcessingRepository()
        self._issued = WeakKeyDictionary()

    @staticmethod
    def _scope_facts(scope):
        return {
            "tenant_id": scope.tenant_id,
            "space_id": scope.space_id,
            "schema_revision": scope.schema_revision,
            "model_config_revision": scope.model_config_revision,
            "index_generation": scope.index_generation,
            "schema_fields": scope.schema_fields,
            "items": [
                {
                    "target": item.target.model_dump(mode="json"),
                    "parent_id": item.parent_id,
                    "status": item.status,
                    "source_revision": item.source_revision,
                    "values_revision": item.values_revision,
                    "user_metadata": item.user_metadata,
                }
                for item in scope.items
            ],
        }

    @classmethod
    def _signature(cls, plan):
        return metadata_digest(
            {
                "tenant_id": plan.tenant_id,
                "space_id": plan.space_id,
                "before_schema_revision": plan.before_schema_revision,
                "after_schema_revision": plan.after_schema_revision,
                "model_config_revision": plan.model_config_revision,
                "index_generation": plan.index_generation,
                "changed_at": plan.changed_at,
                "parameters_digest": plan.parameters_digest,
                "before_schema": plan.before_schema,
                "after_schema": plan.after_schema,
                "changes": plan.changes,
                "accepted": plan.accepted,
                "scope": cls._scope_facts(plan._scope),
                "items": [
                    {
                        "target": item.target.model_dump(mode="json"),
                        "parent_id": item.parent_id,
                        "original_status": item.original_status,
                        "source_revision": item.source_revision,
                        "before_values_digest": item.before_values_digest,
                        "after_values_digest": item.after_values_digest,
                        "before_values": item.before_values,
                        "after_values": item.after_values,
                    }
                    for item in plan.items
                ],
            }
        )

    @staticmethod
    def _after_schema(scope, changes, timestamp):
        result = deepcopy(list(scope.schema_fields))
        try:
            names = [MetadataField.model_validate(value).field_name for value in result]
        except ValidationError as error:
            raise KnowledgeOperationPlanConflictError(reason="metadata_saved_schema_invalid") from error
        if len(set(names)) != len(names):
            raise KnowledgeOperationPlanConflictError(reason="metadata_saved_schema_invalid")
        current = {value["field_name"]: value for value in result}
        builtins = {value.field_name for value in KNOWLEDGE_RAG_METADATA_SCHEMA}
        touched = set()
        for change in changes:
            operation, name = change["operation"], change["field_name"]
            target = change.get("new_field_name")
            if name in builtins:
                if operation == "add":
                    raise KnowledgeMetadataFieldConflictError(field_name=name)
                raise KnowledgeMetadataFieldImmutableError(field_name=name)
            if target in builtins:
                raise KnowledgeMetadataFieldConflictError(field_name=target)
            if (operation == "add" and name in current) or (operation == "rename" and target in current):
                raise KnowledgeMetadataFieldExistError(field_name=name if operation == "add" else target)
            if operation != "add" and name not in current:
                raise KnowledgeMetadataFieldNotExistError(field_name=name)
            affected = {name, target} if operation == "rename" else {name}
            if affected & touched:
                raise KnowledgeOperationPlanConflictError(reason="metadata_ambiguous_change")
            touched.update(affected)
            if operation == "add":
                value = {"field_name": name, "field_type": change["field_type"], "updated_at": timestamp}
                result.append(value)
                current[name] = value
            elif operation == "rename":
                value = current.pop(name)
                value["field_name"], value["updated_at"] = target, timestamp
                current[target] = value
            else:
                current.pop(name)
        return tuple(value for value in result if value["field_name"] in current)

    @staticmethod
    def _after_values(before, changes, timestamp):
        values = deepcopy(before) if before is not None else {}
        for change in changes:
            operation, name = change["operation"], change["field_name"]
            if operation in {"add", "delete"}:
                values.pop(name, None)
            else:
                target = change["new_field_name"]
                original = values.pop(name, None)
                # An undeclared destination may contain failed-delete residue.
                # An absent old value must remain empty after the rename too.
                values.pop(target, None)
                if original is not None:
                    if not isinstance(original, dict):
                        raise KnowledgeOperationPlanConflictError(reason="metadata_saved_value_invalid")
                    original["updated_at"] = timestamp
                    values[target] = original
        return None if before is None and not values else values

    async def apreview(self, session, space_id, parameters: MetadataSchemaParameters) -> PreparedMetadataSchema:
        parameters = MetadataSchemaParameters.model_validate(parameters.model_dump(mode="json"))
        scope = await self.repository.aload_scope(session, space_id)
        if parameters.expected_schema_revision != scope.schema_revision:
            raise KnowledgeOperationPlanConflictError(reason="metadata_schema_changed")
        changes = tuple(value.model_dump(mode="json") for value in parameters.changes)
        timestamp = metadata_change_timestamp()
        after_schema = self._after_schema(scope, changes, timestamp)
        items = []
        for item in scope.items:
            before = deepcopy(item.user_metadata)
            after = self._after_values(before, changes, timestamp)
            items.append(
                PreparedMetadataItem(
                    ResourceVersionTarget.model_validate(item.target.model_dump(mode="json")),
                    item.parent_id,
                    item.status,
                    item.source_revision,
                    metadata_digest(before),
                    metadata_digest(after),
                    before,
                    after,
                )
            )
        prepared = PreparedMetadataSchema(
            scope.tenant_id,
            scope.space_id,
            scope.schema_revision,
            scope.schema_revision + 1,
            scope.model_config_revision,
            scope.index_generation,
            timestamp,
            metadata_digest(parameters.model_dump(mode="json")),
            deepcopy(scope.schema_fields),
            deepcopy(after_schema),
            deepcopy(changes),
            tuple(items),
            deepcopy(scope),
        )
        self._issued[prepared] = _IssuedMetadataPlan(TransactionIdentity.capture(session), self._signature(prepared))
        return prepared

    def _check(self, session, prepared):
        issued = self._issued.get(prepared) if isinstance(prepared, PreparedMetadataSchema) else None
        if issued is None or issued.consumed:
            raise ResourceReferenceInvalidError(reason="metadata_plan_not_issued")
        try:
            issued.transaction.assert_current(session)
            signature = self._signature(prepared)
        except (TypeError, ValueError, AttributeError) as error:
            raise ResourceReferenceInvalidError(reason="metadata_plan_changed") from error
        if signature != issued.signature:
            raise ResourceReferenceInvalidError(reason="metadata_plan_changed")
        return issued

    async def aaccept(self, session, prepared) -> PreparedMetadataSchema:
        issued = self._check(session, prepared)
        current = await self.repository.aload_scope(session, prepared.space_id, for_update=True)
        self._check(session, prepared)
        if metadata_digest(self._scope_facts(current)) != metadata_digest(self._scope_facts(prepared._scope)):
            raise KnowledgeOperationPlanConflictError(reason="metadata_scope_changed")
        await self.repository.areplace_schema(session, current, after_schema=prepared.after_schema)
        issued.consumed = True
        return replace(
            prepared,
            before_schema=deepcopy(prepared.before_schema),
            after_schema=deepcopy(prepared.after_schema),
            changes=deepcopy(prepared.changes),
            items=deepcopy(prepared.items),
            _scope=deepcopy(prepared._scope),
            accepted=True,
        )
