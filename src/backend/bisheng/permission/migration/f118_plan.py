"""Pure F118 use-retirement plans over immutable, explicitly acquired facts.

These values neither acquire a baseline nor authorize SQL/FGA publication.
The formal migration owns the original artifacts and their run/hash binding.
"""

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime
from hashlib import sha256
from itertools import zip_longest

from pydantic import BaseModel

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.permission.domain.schemas import VisibleSourceProjectionDTO
from bisheng.permission.domain.services.catalog_policy import (
    MIGRATED_RESOURCE_TYPES,
    REGISTERED_ACTION_CODES,
    CatalogAction,
    derive_action_release,
    effective_action_codes,
)
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceRecord,
    GrantSourceService,
    is_visibility_only_model,
    model_snapshot_for_target,
)
from bisheng.permission.domain.services.model_policy import CustomModelSelection, derive_permission_models
from bisheng.permission.domain.services.visibility_projection_service import VisibilityProjectionCompiler


def _blocked(reason):
    raise PermissionMigrationBlockedError(reason=f"f118_permission_{reason}")


def _json(value):
    if is_dataclass(value):
        return {item.name: _json(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_json(item) for item in value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _checksum(value):
    return sha256(
        json.dumps(_json(value), sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _digest(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        _blocked("invalid_digest")


def _positive(value):
    return type(value) is int and value > 0


@dataclass(frozen=True, slots=True)
class CatalogReleaseBaseline:
    id: int
    release_key: str
    version: int
    checksum: str
    required_authorization_model_release_id: int
    status: str = "CURRENT"
    write_fenced: bool = False
    predecessor_id: int | None = None
    commit_checksum: str | None = None
    draft_owner_id: int = 0
    idempotency_key: str = ""
    projection_checkpoint: int = 0
    expires_at: datetime | None = None
    published_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AuthorizationPinBaseline:
    id: int
    environment: str
    store_id: str
    model_id: str
    model_checksum: str
    required_relations_checksum: str
    status: str = "ACTIVE"
    model_version: str = ""
    predecessor_model_id: str | None = None
    openfga_version: str = ""


@dataclass(frozen=True, slots=True)
class PermissionModelBaseline:
    id: int
    model_key: str
    name: str
    normalized_name: str
    kind: str
    config_scope: str
    derived_level: int | None
    active: bool
    allow_same_level: bool
    selected_action_codes: tuple[str, ...]
    effective_action_codes: tuple[str, ...]
    visibility_only_resource_types: tuple[str, ...] = ()
    visibility_level: int | None = None
    legacy_source_key: str | None = None
    retired_use_level_floor: int | None = None

    def __post_init__(self):
        if any(
            type(value) is not tuple
            for value in (self.selected_action_codes, self.effective_action_codes, self.visibility_only_resource_types)
        ):
            raise TypeError("model snapshots require immutable action/provenance tuples")
        floor = self.retired_use_level_floor
        if floor is not None:
            provenance = GrantModelSnapshot(
                self.model_key,
                self.active,
                (),
                floor,
                visibility_only_resource_types=self.visibility_only_resource_types,
                visibility_level=self.visibility_level,
                visibility_only=True,
            )
            if (
                type(floor) is not int
                or floor not in {1, 2, 3, 4}
                or self.kind != "CUSTOM"
                or type(self.derived_level) is not int
                or self.derived_level < floor
                or self.visibility_level != floor
                or not is_visibility_only_model(provenance)
            ):
                raise ValueError("existing retired-use floor requires its original tier and controlled provenance")


@dataclass(frozen=True, slots=True)
class PermissionCatalogBaseline:
    release: CatalogReleaseBaseline
    authorization: AuthorizationPinBaseline
    actions: tuple[CatalogAction, ...]
    models: tuple[PermissionModelBaseline, ...]

    def __post_init__(self):
        if (
            type(self.actions) is not tuple
            or type(self.models) is not tuple
            or any(type(action.resource_types) is not frozenset for action in self.actions)
        ):
            raise TypeError("catalog snapshots require immutable records/scopes")


@dataclass(frozen=True, slots=True)
class ResourceModeBaseline:
    id: int
    tenant_id: int
    resource_type: str
    resource_id: str
    mode: str
    parent_type: str | None = None
    parent_id: str | None = None
    version: int = 1
    projection_state: str = "CURRENT"
    operation_id: int | None = None


@dataclass(frozen=True, slots=True)
class PermissionGrantBaseline:
    id: int
    tenant_id: int
    resource_type: str
    resource_id: str
    model_key: str
    state: str
    version: int = 1
    projection_state: str = "CURRENT"


@dataclass(frozen=True, slots=True)
class PermissionAssigneeBaseline:
    id: int
    grant_id: int
    tenant_id: int
    subject_type: str
    subject_id: str
    userset_relation: str | None
    include_children: bool
    source_type: str
    source_ref: str
    source_locator: str
    source_fingerprint: str
    projected_subject: str
    protected: bool
    state: str
    version: int = 1

    def to_source_record(self):
        return GrantSourceRecord(
            self.id,
            self.subject_type,
            self.subject_id,
            self.userset_relation,
            self.include_children,
            self.source_type,
            self.source_ref,
            self.source_locator,
            self.source_fingerprint,
            self.projected_subject,
            self.protected,
            self.state == "ACTIVE",
            self.version,
        )


@dataclass(frozen=True, slots=True)
class PermissionVisibleSourceBaseline:
    id: int
    source: VisibleSourceProjectionDTO


@dataclass(frozen=True, slots=True)
class PermissionResourceBaseline:
    tenant_id: int
    resource_type: str
    resource_id: str
    mode: ResourceModeBaseline
    grants: tuple[PermissionGrantBaseline, ...]
    assignees: tuple[PermissionAssigneeBaseline, ...]
    visible_sources: tuple[PermissionVisibleSourceBaseline, ...]

    def __post_init__(self):
        if any(type(value) is not tuple for value in (self.grants, self.assignees, self.visible_sources)):
            raise TypeError("resource snapshots require immutable record tuples")


@dataclass(frozen=True, slots=True)
class ModelApplicabilityChange:
    model_key: str
    from_resource_type: str
    to_resource_type: str
    before_action_codes: tuple[str, ...]
    after_action_codes: tuple[str, ...]
    reason: str

    def __post_init__(self):
        if any(
            type(codes) is not tuple or any(type(code) is not str for code in codes)
            for codes in (self.before_action_codes, self.after_action_codes)
        ):
            raise TypeError("namespace applicability requires immutable action tuples")


@dataclass(frozen=True, slots=True)
class CatalogRetirementPlan:
    run_id: str
    writer_contract_version: str
    before: PermissionCatalogBaseline
    target_model_checksum: str
    after_actions: tuple[CatalogAction, ...]
    after_models: tuple[PermissionModelBaseline, ...]
    action_checksum: str
    model_checksum: str
    checksum: str
    namespace_type_mappings: tuple[tuple[str, str], ...] = ()
    namespace_applicability_changes: tuple[ModelApplicabilityChange, ...] = ()


@dataclass(frozen=True, slots=True)
class ResourceRetirementPlan:
    catalog_plan: CatalogRetirementPlan
    before: PermissionResourceBaseline
    after_grants: tuple[GrantSnapshot, ...]
    visible_subjects: tuple[str, ...]
    visibility_deltas: tuple
    expected_use_changes: tuple[str, ...]
    checksum: str
    after: PermissionResourceBaseline | None = None
    namespace_target: ResourceModeBaseline | None = None


def _validate_catalog(before):
    if not isinstance(before, PermissionCatalogBaseline):
        _blocked("catalog_snapshot_required")
    release, pin = before.release, before.authorization
    if (
        not _positive(release.id)
        or not _positive(release.version)
        or release.status != "CURRENT"
        or release.write_fenced
        or release.required_authorization_model_release_id != pin.id
        or pin.status != "ACTIVE"
        or not all(
            isinstance(value, str) and value
            for value in (release.release_key, pin.environment, pin.store_id, pin.model_id)
        )
    ):
        _blocked("catalog_pin_not_ready")
    for digest in (release.checksum, pin.model_checksum, pin.required_relations_checksum):
        _digest(digest)
    codes = tuple(action.code for action in before.actions)
    if set(codes) not in (set(REGISTERED_ACTION_CODES), {*REGISTERED_ACTION_CODES, "use"}):
        _blocked("unknown_or_incomplete_actions")
    try:
        derive_action_release(before.actions, registered_action_codes=codes)
    except (TypeError, ValueError) as error:
        raise PermissionMigrationBlockedError(reason="f118_permission_invalid_actions") from error
    if len({model.model_key for model in before.models}) != len(before.models) or len(
        {model.id for model in before.models}
    ) != len(before.models):
        _blocked("duplicate_models")
    by_code = {action.code: action for action in before.actions}
    for model in before.models:
        if (
            not _positive(model.id)
            or type(model.active) is not bool
            or type(model.allow_same_level) is not bool
            or model.kind not in {"STANDARD", "CUSTOM"}
            or model.config_scope != "PLATFORM"
            or model.normalized_name != model.name.casefold()
            or not model.name
            or len(set(model.selected_action_codes)) != len(model.selected_action_codes)
            or not set(model.selected_action_codes) <= set(by_code)
        ):
            _blocked("invalid_model")
        effective = tuple(
            code for code in model.selected_action_codes if by_code[code].active and by_code[code].level is not None
        )
        if set(effective) != set(model.effective_action_codes):
            _blocked("model_action_drift")
        if not effective and not model.visibility_only_resource_types:
            _blocked("unexplained_empty_model")


def _compile_catalog(before, *, namespace_type_mappings=()):
    actions = derive_action_release(action for action in before.actions if action.code != "use")
    by_code = {action.code: action for action in before.actions}
    selections = []
    expected_floors = {model.model_key: model.retired_use_level_floor for model in before.models}
    for model in before.models:
        if model.kind != "CUSTOM":
            continue
        selected = tuple(code for code in model.selected_action_codes if code != "use")
        types = set(model.visibility_only_resource_types)
        floor = model.retired_use_level_floor
        level = model.visibility_level
        if "use" in model.effective_action_codes:
            types.update(by_code["use"].resource_types)
            if floor is None:
                original_levels = tuple(by_code[code].level for code in model.effective_action_codes)
                if (
                    type(model.derived_level) is not int
                    or model.derived_level not in {1, 2, 3, 4}
                    or any(type(value) is not int or value not in {1, 2, 3, 4} for value in original_levels)
                    or model.derived_level != max(original_levels)
                ):
                    _blocked("original_use_tier_changed")
                if level is not None and level != model.derived_level:
                    _blocked("original_use_visibility_tier_conflict")
                remaining = tuple(by_code[code].level for code in model.effective_action_codes if code != "use")
                if remaining and max(remaining) < model.derived_level:
                    floor = model.derived_level
                    expected_floors[model.model_key] = floor
        if namespace_type_mappings and "knowledge_library" in types:
            types.add("knowledge_space")
        if types:
            if type(model.derived_level) is not int or model.derived_level not in {1, 2, 3, 4}:
                _blocked("visibility_tier_missing")
            level = model.derived_level if level is None else level
        selections.append(
            CustomModelSelection(
                model.model_key,
                model.name,
                selected,
                model.active,
                model.allow_same_level,
                model.config_scope,
                tuple(sorted(types)),
                level,
                retired_use_level_floor=floor,
            )
        )
    models = derive_permission_models(
        actions,
        custom_models=tuple(selections),
        standard_allow_same_level={
            model.model_key: model.allow_same_level for model in before.models if model.kind == "STANDARD"
        },
    )
    if models.blockers or {item.model_key for item in models.models} != {item.model_key for item in before.models}:
        _blocked("model_release_not_ready")
    originals = {model.model_key: model for model in before.models}
    result = []
    for model in models.models:
        original = originals[model.model_key]
        if (
            model.derived_level != original.derived_level
            or model.name != original.name
            or model.config_scope != original.config_scope
            or model.active != original.active
            or model.allow_same_level != original.allow_same_level
            or model.kind != original.kind
            or model.retired_use_level_floor != expected_floors[model.model_key]
            or set(model.action_codes) != set(original.effective_action_codes) - {"use"}
            or set(model.selected_action_codes) != set(original.selected_action_codes) - {"use"}
        ):
            _blocked("non_use_or_management_changed")
        result.append(
            replace(
                original,
                selected_action_codes=model.selected_action_codes,
                effective_action_codes=model.action_codes,
                visibility_only_resource_types=model.visibility_only_resource_types,
                visibility_level=model.visibility_level,
                retired_use_level_floor=model.retired_use_level_floor,
            )
        )
    return actions, models, tuple(result)


def _catalog_payload(plan):
    original = (
        plan.run_id,
        plan.writer_contract_version,
        plan.before,
        plan.target_model_checksum,
        plan.after_actions,
        plan.after_models,
        plan.action_checksum,
        plan.model_checksum,
    )
    if plan.namespace_type_mappings:
        return (*original, plan.namespace_type_mappings, plan.namespace_applicability_changes)
    return original


def _namespace_applicability(before, actions, models):
    previous_codes = effective_action_codes(before.actions, "knowledge_library")
    current_codes = effective_action_codes(actions, "knowledge_space")
    by_key = {model.model_key: model for model in models}
    result = []
    for previous in before.models:
        current = by_key[previous.model_key]
        old_selected, new_selected = set(previous.effective_action_codes), set(current.effective_action_codes)
        result.append(
            ModelApplicabilityChange(
                previous.model_key,
                "knowledge_library",
                "knowledge_space",
                tuple(code for code in previous_codes if code in old_selected),
                tuple(code for code in current_codes if code in new_selected),
                "document_library_to_knowledge_space_existing_capabilities",
            )
        )
    return tuple(result)


def build_catalog_retirement_plan(
    *,
    run_id,
    writer_contract_version,
    before: PermissionCatalogBaseline,
    target_model_checksum,
    namespace_type_mappings=(),
) -> CatalogRetirementPlan:
    if (
        type(namespace_type_mappings) is not tuple
        or any(type(pair) is not tuple for pair in namespace_type_mappings)
        or any(type(part) is not str for pair in namespace_type_mappings for part in pair)
        or namespace_type_mappings not in ((), (("knowledge_library", "knowledge_space"),))
    ):
        _blocked("invalid_namespace_mapping")
    if (
        not isinstance(run_id, str)
        or not run_id.strip()
        or len(run_id) > 64
        or not isinstance(writer_contract_version, str)
        or not writer_contract_version.strip()
        or len(writer_contract_version) > 32
    ):
        _blocked("invalid_run")
    _digest(target_model_checksum)
    _validate_catalog(before)
    try:
        actions, models, records = _compile_catalog(before, namespace_type_mappings=namespace_type_mappings)
    except (TypeError, ValueError) as error:
        raise PermissionMigrationBlockedError(reason="f118_permission_invalid_retirement") from error
    plan = CatalogRetirementPlan(
        run_id,
        writer_contract_version,
        before,
        target_model_checksum,
        actions.actions,
        records,
        actions.checksum,
        models.checksum,
        "",
        namespace_type_mappings,
        _namespace_applicability(before, actions.actions, records) if namespace_type_mappings else (),
    )
    return replace(plan, checksum=_checksum(_catalog_payload(plan)))


def _validate_resource(before):
    if (
        not isinstance(before, PermissionResourceBaseline)
        or not _positive(before.tenant_id)
        or before.resource_type not in MIGRATED_RESOURCE_TYPES
        or not before.resource_id
    ):
        _blocked("resource_snapshot_required")
    key = (before.tenant_id, before.resource_type, before.resource_id)
    rows = (before.mode, *before.grants)
    if any(
        (row.tenant_id, row.resource_type, row.resource_id) != key
        or row.projection_state != "CURRENT"
        or not _positive(row.id)
        or not _positive(row.version)
        for row in rows
    ):
        _blocked("resource_projection_not_ready")
    if before.mode.mode not in {"CUSTOM", "INHERIT"} or (
        (before.mode.parent_type is None) != (before.mode.parent_id is None)
    ):
        _blocked("invalid_resource_mode")
    if (
        len({row.id for row in before.grants}) != len(before.grants)
        or len({row.id for row in before.assignees}) != len(before.assignees)
        or len({row.id for row in before.visible_sources}) != len(before.visible_sources)
    ):
        _blocked("duplicate_resource_rows")
    ids = {grant.id for grant in before.grants}
    if any(grant.state not in {"ACTIVE", "INACTIVE"} for grant in before.grants):
        _blocked("grant_not_terminal")
    if any(
        source.grant_id not in ids
        or source.tenant_id != before.tenant_id
        or source.state not in {"ACTIVE", "INACTIVE"}
        or type(source.protected) is not bool
        or type(source.include_children) is not bool
        or not _positive(source.id)
        or not _positive(source.version)
        for source in before.assignees
    ):
        _blocked("invalid_source_parent_or_state")
    for source in before.assignees:
        try:
            canonical = GrantSourceService().canonicalize_source(
                source_id=source.id,
                subject_type=source.subject_type,
                subject_id=source.subject_id,
                source_type=source.source_type,
                userset_relation=source.userset_relation,
                include_children=source.include_children,
                source_ref=source.source_ref,
                protected=source.protected,
            )
            if replace(source.to_source_record(), active=True, version=1) != canonical:
                _blocked("noncanonical_source")
        except (TypeError, ValueError, AttributeError) as error:
            raise PermissionMigrationBlockedError(reason="f118_permission_invalid_source") from error
    for row in before.visible_sources:
        source = row.source
        if (
            not _positive(row.id)
            or (source.tenant_id, source.resource_type, source.resource_id) != key
            or source.state not in {"ACTIVE", "RETIRED"}
        ):
            _blocked("visible_source_not_ready")


def _grants(resource, by_model, scopes, sources_by_grant):
    result = []
    for grant in resource.grants:
        if grant.model_key not in by_model:
            _blocked("grant_model_missing")
        model = by_model[grant.model_key]
        snapshot = GrantModelSnapshot(
            model.model_key,
            model.active,
            model.effective_action_codes,
            model.derived_level,
            model.allow_same_level,
            model.visibility_only_resource_types,
            model.visibility_level,
        )
        snapshot = model_snapshot_for_target(
            snapshot,
            resource_type=resource.resource_type,
            applicable_action_codes=tuple(
                code for code in model.effective_action_codes if resource.resource_type in scopes[code]
            ),
        )
        result.append(
            GrantSnapshot(
                str(grant.id),
                resource.tenant_id,
                resource.resource_type,
                resource.resource_id,
                snapshot,
                grant.state == "ACTIVE",
                sources_by_grant.get(grant.id, ()),
                grant.version,
            )
        )
    return tuple(result)


def _resource_payload(plan):
    original = (
        plan.catalog_plan.checksum,
        plan.before,
        plan.after_grants,
        plan.visible_subjects,
        plan.visibility_deltas,
        plan.expected_use_changes,
    )
    if plan.catalog_plan.namespace_type_mappings:
        return (*original, plan.namespace_target, plan.after)
    return original


@dataclass(frozen=True, slots=True)
class _ResourceRetirementContext:
    catalog_plan: CatalogRetirementPlan
    before_models: dict[str, PermissionModelBaseline]
    after_models: dict[str, PermissionModelBaseline]
    before_scopes: dict[str, frozenset[str]]
    after_scopes: dict[str, frozenset[str]]


def _resource_context(catalog_plan):
    if not isinstance(catalog_plan, CatalogRetirementPlan):
        _blocked("catalog_plan_required")
    rebuilt = build_catalog_retirement_plan(
        run_id=catalog_plan.run_id,
        writer_contract_version=catalog_plan.writer_contract_version,
        before=catalog_plan.before,
        target_model_checksum=catalog_plan.target_model_checksum,
        namespace_type_mappings=catalog_plan.namespace_type_mappings,
    )
    if rebuilt != catalog_plan:
        _blocked("catalog_plan_changed")
    return _ResourceRetirementContext(
        catalog_plan,
        {model.model_key: model for model in catalog_plan.before.models},
        {model.model_key: model for model in catalog_plan.after_models},
        {action.code: action.resource_types for action in catalog_plan.before.actions},
        {action.code: action.resource_types for action in catalog_plan.after_actions},
    )


def _namespace_after(before, target):
    if type(target) is not ResourceModeBaseline:
        _blocked("namespace_resource_target_required")
    previous = before.mode
    if (
        any(
            type(getattr(previous, name)) is not str
            for name in ("resource_type", "resource_id", "mode", "projection_state")
        )
        or any(
            getattr(previous, name) is not None and type(getattr(previous, name)) is not str
            for name in ("parent_type", "parent_id")
        )
        or (previous.operation_id is not None and not _positive(previous.operation_id))
    ):
        _blocked("namespace_mode_baseline_invalid")
    if (
        any(
            type(getattr(target, field.name)) is not type(getattr(previous, field.name))
            or getattr(target, field.name) != getattr(previous, field.name)
            for field in fields(previous)
            if field.name not in {"resource_type", "parent_type"}
        )
        or type(target.resource_type) is not str
        or (
            target.resource_type != previous.resource_type
            and (previous.resource_type, target.resource_type) != ("knowledge_library", "knowledge_space")
        )
        or (
            target.parent_type != previous.parent_type
            and (previous.parent_type, target.parent_type) != ("knowledge_library", "knowledge_space")
        )
        or type(target.parent_type) is not type(previous.parent_type)
    ):
        _blocked("namespace_target_mode_changed")
    return replace(
        before,
        resource_type=target.resource_type,
        mode=target,
        grants=tuple(replace(row, resource_type=target.resource_type) for row in before.grants),
    )


def _namespace_visible(before, after, old_grants, new_grants, compiler):
    canonical = {}
    for previous, current in zip(old_grants, new_grants, strict=True):
        for source in previous.sources:
            old = compiler._compile_source(before.tenant_id, previous, source)
            new = compiler._compile_source(before.tenant_id, current, source)
            if old.contribution_fingerprint in canonical:
                _blocked("namespace_source_duplicate")
            canonical[old.contribution_fingerprint] = old, new
    visible, seen = [], set()
    for row in before.visible_sources:
        if (
            type(row.source.source_version) is not int
            or row.source.source_version < 0
            or any(
                value is not None and not _positive(value)
                for value in (row.source.operation_id, row.source.migration_item_id)
            )
        ):
            _blocked("namespace_source_metadata_invalid")
        key = row.source.contribution_fingerprint
        if key not in canonical or key in seen:
            _blocked("namespace_source_backing_missing_or_duplicate")
        seen.add(key)
        old, new = canonical[key]
        compiler._assert_same_canonical_source(row.source, old)
        changed = row.source.model_copy(
            update={"resource_type": after.resource_type, "tuple_fingerprint": new.tuple_fingerprint}
        )
        compiler._assert_same_canonical_source(changed, new)
        visible.append(replace(row, source=changed))
    return replace(after, visible_sources=tuple(visible))


def _build_resource_retirement_plan(context, before, namespace_target=None):
    _validate_resource(before)
    mapped = bool(context.catalog_plan.namespace_type_mappings)
    if not mapped and namespace_target is not None:
        _blocked("namespace_mapping_required")
    after_resource = _namespace_after(before, namespace_target) if mapped else before
    try:
        sources_by_grant = {}
        for source in before.assignees:
            sources_by_grant.setdefault(source.grant_id, []).append(source.to_source_record())
        sources_by_grant = {key: tuple(sources) for key, sources in sources_by_grant.items()}
        old = _grants(before, context.before_models, context.before_scopes, sources_by_grant)
        after = _grants(after_resource, context.after_models, context.after_scopes, sources_by_grant)
        if (
            mapped
            and before.resource_type == "knowledge_space"
            and any(
                not previous.model.action_codes and not previous.model.visibility_only and current.model.visibility_only
                for previous, current in zip(old, after, strict=True)
            )
        ):
            _blocked("existing_space_scope_hole")
        existing = tuple(row.source for row in before.visible_sources)
        compiler = VisibilityProjectionCompiler()
        first = compiler.compile(tenant_id=before.tenant_id, grants=old, existing_sources=existing)
        if first.deltas or first.retired_sources:
            _blocked("visible_source_drift")
        if mapped:
            after_resource = _namespace_visible(before, after_resource, old, after, compiler)
            existing = tuple(row.source for row in after_resource.visible_sources)
        second = compiler.compile(tenant_id=before.tenant_id, grants=after, existing_sources=existing)
        if (
            second.deltas
            or second.retired_sources
            or (not mapped and first.active_sources != second.active_sources)
            or {row.contribution_fingerprint for row in first.active_sources}
            != {row.contribution_fingerprint for row in second.active_sources}
            or {row.projected_subject for row in first.active_sources}
            != {row.projected_subject for row in second.active_sources}
        ):
            _blocked("visible_source_drift")
        deltas = (
            compiler._aggregate_deltas(
                before={(row.resource_type, row.resource_id, row.projected_subject) for row in first.active_sources},
                after={(row.resource_type, row.resource_id, row.projected_subject) for row in second.active_sources},
            )
            if mapped
            else second.deltas
        )
        subjects = tuple(sorted({row.projected_subject for row in first.active_sources}))
        previous_use = {
            source.projected_subject
            for grant in old
            if grant.active and grant.model.active and "use" in grant.model.action_codes
            for source in grant.sources
            if source.active
        }
        changes = tuple(sorted(set(subjects) - previous_use))
    except (TypeError, ValueError, KeyError) as error:
        raise PermissionMigrationBlockedError(reason="f118_permission_invalid_visibility") from error
    plan = ResourceRetirementPlan(
        context.catalog_plan, before, after, subjects, deltas, changes, "", after_resource, namespace_target
    )
    return replace(plan, checksum=_checksum(_resource_payload(plan)))


def build_resource_retirement_plans(
    *,
    catalog_plan: CatalogRetirementPlan,
    before: Iterable[PermissionResourceBaseline],
    target_modes: Iterable[ResourceModeBaseline] | None = None,
) -> Iterator[ResourceRetirementPlan]:
    """Compile one frozen directory per batch; retain no context beyond iteration."""
    context = _resource_context(catalog_plan)
    if not catalog_plan.namespace_type_mappings:
        if target_modes is not None:
            _blocked("namespace_mapping_required")
        for resource in before:
            yield _build_resource_retirement_plan(context, resource)
    else:
        if target_modes is None:
            _blocked("namespace_resource_target_required")
        missing = object()
        for resource, target in zip_longest(before, target_modes, fillvalue=missing):
            if resource is missing or target is missing:
                _blocked("namespace_target_batch_length_changed")
            yield _build_resource_retirement_plan(context, resource, target)


def build_resource_retirement_plan(
    *,
    catalog_plan: CatalogRetirementPlan,
    before: PermissionResourceBaseline,
    namespace_target: ResourceModeBaseline | None = None,
) -> ResourceRetirementPlan:
    return next(
        build_resource_retirement_plans(
            catalog_plan=catalog_plan,
            before=(before,),
            target_modes=None if namespace_target is None else (namespace_target,),
        )
    )
