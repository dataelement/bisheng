"""Exact restoration of the existing closed M2 wire to its Domain commands."""

from dataclasses import dataclass
from datetime import datetime

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_conversion_plan import COMMAND_RECORD_TYPES
from bisheng.knowledge.application.unification_inventory_codec import (
    InventoryRecord,
    decode_inventory_page,
    record_from_row,
)
from bisheng.knowledge.domain.schemas.unification_conversion import (
    ConversionCommand,
    DefaultConversionCommand,
    DefaultSlotProvenance,
    InitializeV1Command,
    ResourceConversionCommand,
)

_COMMANDS = {name: cls for cls, name in COMMAND_RECORD_TYPES.items()}
_DEFERRED = frozenset({"permission_plan", "source_decision"})


def _invalid():
    raise KnowledgeOperationPlanConflictError(reason="migration_conversion_codec_invalid")


@dataclass(frozen=True, slots=True)
class DecodedSQLConversionPage:
    commands: tuple[ConversionCommand, ...]
    deferred: tuple[InventoryRecord, ...]


def decode_sql_conversion_page(content, *, run_id, writer_contract_version, tenant_id, page_index):
    page = decode_inventory_page(
        content,
        run_id=run_id,
        section="conversion",
        scope="tenant",
        tenant_id=tenant_id,
        page_index=page_index,
        kind="plan",
    )
    commands, deferred = [], []
    for record in page.records:
        values = record.data
        if values.get("tenant_id") != tenant_id:
            _invalid()
        if record.record_type in _DEFERRED:
            deferred.append(record)
            continue
        cls = _COMMANDS.get(record.record_type)
        if cls is None or (values["run_id"], values["writer_contract_version"]) != (run_id, writer_contract_version):
            _invalid()
        try:
            time_key = (
                "planned_at"
                if cls is InitializeV1Command
                else "creator_planned_at"
                if cls is ResourceConversionCommand and values["creator_planned_at"] is not None
                else None
            )
            if time_key is not None:
                value = datetime.fromisoformat(values[time_key])
                if value.tzinfo is not None or value.microsecond:
                    _invalid()
                values[time_key] = value
            elif cls is DefaultConversionCommand:
                values["provenance"] = tuple(DefaultSlotProvenance(**item) for item in values["provenance"])
            command = cls(**values)
        except (ValueError, TypeError, OverflowError) as error:
            raise KnowledgeOperationPlanConflictError(reason="migration_conversion_codec_invalid") from error
        # The original encoder owns all field/type closure and canonical bytes.
        if record_from_row(command) != record:
            _invalid()
        commands.append(command)
    return DecodedSQLConversionPage(tuple(commands), tuple(deferred))
