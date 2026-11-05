"""F118 defaults resolution, sparse overrides and atomic settings replacement.

Resource/menu/scope authorization belongs to the calling business owner. This
internal service receives its external SQL transaction and never commits it.
System defaults and dedicated parser rules are supplied by that owner's real
legacy adapter, avoiding a second FileProcessBase/default implementation.
"""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.repositories.processing_settings_repository import ProcessingSettingsRepository
from bisheng.knowledge.domain.schemas.processing_settings import (
    DocumentProcessingRule,
    EffectiveProcessingSnapshot,
    PartialDocumentRule,
    PartialTableRule,
    ProcessingDefaults,
    ProcessingOverrides,
    ProcessingSettingsRead,
    ProcessingSettingsWrite,
    TableProcessingRule,
)


class ProcessingSettingsService:
    def __init__(self, repository: ProcessingSettingsRepository):
        self.repository = repository

    async def get_settings(
        self, session: AsyncSession, space_id: int, *, system_defaults: ProcessingDefaults
    ) -> ProcessingSettingsRead:
        record = await self.repository.aget(session, space_id)
        saved = ProcessingDefaults.model_validate(record.saved_defaults) if record.saved_defaults is not None else None
        return ProcessingSettingsRead(
            space_id=record.space_id,
            config_version=record.config_version,
            saved_defaults=saved,
            effective_defaults=saved if saved is not None else system_defaults.model_copy(deep=True),
        )

    async def save_settings(
        self,
        session: AsyncSession,
        space_id: int,
        change: ProcessingSettingsWrite,
        *,
        system_defaults: ProcessingDefaults,
    ) -> ProcessingSettingsRead:
        validated = ProcessingSettingsWrite.model_validate(change.model_dump(mode="json"))
        record = await self.repository.areplace(
            session,
            space_id,
            expected_config_version=validated.expected_config_version,
            defaults=validated.defaults,
        )
        saved = ProcessingDefaults.model_validate(record.saved_defaults)
        return ProcessingSettingsRead(
            space_id=record.space_id,
            config_version=record.config_version,
            saved_defaults=saved,
            effective_defaults=saved.model_copy(deep=True),
        )

    @staticmethod
    def _overrides(
        value: ProcessingOverrides | Mapping[str, Any] | None,
        *,
        table: bool,
    ) -> dict:
        if value is None:
            return {}
        raw = (
            value.model_dump(mode="json", exclude_none=True)
            if isinstance(value, ProcessingOverrides)
            else deepcopy(value)
        )
        parsed = ProcessingOverrides.model_validate(raw)
        selected = parsed.table if table else parsed.document
        return selected.model_dump(mode="json", exclude_none=True) if selected is not None else {}

    @classmethod
    def resolve_effective_snapshot(
        cls,
        *,
        file_kind: str,
        system_defaults: ProcessingDefaults,
        space_defaults: ProcessingDefaults | None = None,
        space_config_version: int = 0,
        batch_overrides: ProcessingOverrides | Mapping[str, Any] | None = None,
        file_overrides: ProcessingOverrides | Mapping[str, Any] | None = None,
        specialized_overrides: PartialDocumentRule | PartialTableRule | Mapping[str, Any] | None = None,
    ) -> EffectiveProcessingSnapshot:
        """Resolve once at acceptance, then keep the resulting actual snapshot.

        A dedicated owner may deliberately supply an empty override when its
        current media loader keeps ordinary splitting. It must make that
        selection explicitly; generic defaults cannot replace a dedicated
        web/audio/video path by omission.
        """
        table = file_kind == "table"
        rule_model = TableProcessingRule if table else DocumentProcessingRule
        partial_model = PartialTableRule if table else PartialDocumentRule
        if file_kind in {"web", "audio", "video"} and specialized_overrides is None:
            raise ValueError("dedicated parser rule selection is required for this file kind")

        system = ProcessingDefaults.model_validate(system_defaults.model_dump(mode="json"))
        merged = (system.table if table else system.document).model_dump(mode="json")
        provenance = {"system": sorted(merged)}
        if space_defaults is not None:
            space = ProcessingDefaults.model_validate(space_defaults.model_dump(mode="json"))
            layer = (space.table if table else space.document).model_dump(mode="json")
            merged.update(layer)
            provenance["space"] = sorted(layer)
        for name, value in (("batch", batch_overrides), ("file", file_overrides)):
            if value is not None:
                layer = cls._overrides(value, table=table)
                merged.update(layer)
                provenance[name] = sorted(layer)
        if specialized_overrides is not None:
            raw = (
                specialized_overrides.model_dump(mode="json", exclude_none=True)
                if isinstance(specialized_overrides, (PartialDocumentRule, PartialTableRule))
                else deepcopy(specialized_overrides)
            )
            layer = partial_model.model_validate(raw).model_dump(mode="json", exclude_none=True)
            merged.update(layer)
            provenance["specialized"] = sorted(layer)
        # Cross-field ranges apply to the final merged rule, not just each
        # sparse input. Raw dictionaries and saved defaults are never mutated.
        effective = rule_model.model_validate(merged)
        return EffectiveProcessingSnapshot(
            file_kind=file_kind,
            effective_rule=effective,
            space_config_version=space_config_version,
            supplied_fields_by_layer=provenance,
        )
