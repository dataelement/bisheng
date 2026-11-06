"""Pure SQL-conversion commands; values alone grant no migration authority."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ConversionCommand:
    schema_version: int
    run_id: str
    writer_contract_version: str
    tenant_id: int
    command_key: str
    operation: str


@dataclass(frozen=True, slots=True)
class ResourceConversionCommand(ConversionCommand):
    knowledge_id: int
    before_business_digest: str
    after_business_digest: str
    before_neutral_digest: str
    after_neutral_digest: str
    after_inventory_business_revision_digest: str
    after_owner_configuration_digest: str
    target_type: int
    target_is_released: bool
    target_migration_origin: str


@dataclass(frozen=True, slots=True)
class InitializeV1Command(ConversionCommand):
    knowledge_id: int
    file_id: int
    file_business_digest: str
    before_relation_digest: str
    natural_key: str
    document_template_digest: str
    version_template_digest: str
    file_level_path: str | None
    level: int | None
    planned_at: datetime


@dataclass(frozen=True, slots=True)
class TagConversionCommand(ConversionCommand):
    tag_id: int
    knowledge_id: int
    before_digest: str
    after_digest: str
    from_business_type: str
    to_business_type: str


@dataclass(frozen=True, slots=True)
class TagLinkConversionCommand(ConversionCommand):
    link_id: int
    file_id: int
    knowledge_id: int
    tag_id: int
    before_digest: str
    after_digest: str | None
    from_type: int
    to_type: int
    action: str
    survivor_link_id: int
    survivor_digest: str


@dataclass(frozen=True, slots=True)
class DefaultSlotProvenance:
    source_slot: str
    target_slot: str
    target_id: str


@dataclass(frozen=True, slots=True)
class DefaultConversionCommand(ConversionCommand):
    row_id: int
    key: str
    before_raw_row_digest: str
    before_configuration_digest: str
    after_configuration_digest: str
    after_business_revision_digest: str
    before_refs_digest: str
    after_refs_digest: str
    action: str
    selected_linsight_id: str | None
    selected_chat_id: str | None
    drop_task_model: bool
    drop_executor_mode: bool
    algorithm_version: str
    provenance: tuple[DefaultSlotProvenance, ...]


def initial_version_templates(*, knowledge_id, file_id, file_level_path, level, planned_at, natural_key):
    document = {
        "knowledge_id": knowledge_id,
        "file_level_path": file_level_path,
        "level": level,
        "primary_version_key": natural_key,
        "create_time": planned_at,
        "update_time": planned_at,
    }
    version = {
        "document_key": natural_key,
        "knowledge_file_id": file_id,
        "version_no": 1,
        "is_primary": True,
        "create_time": planned_at,
        "update_time": planned_at,
    }
    return document, version
