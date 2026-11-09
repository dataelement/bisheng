"""Pure verification of a frozen permission subplan, without live I/O."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from itertools import zip_longest

from bisheng.permission.migration.f118_plan import (
    CatalogRetirementPlan,
    PermissionCatalogBaseline,
    PermissionResourceBaseline,
    ResourceRetirementPlan,
    _blocked,
    _build_resource_retirement_plan,
    _checksum,
    _digest,
    _resource_context,
    _validate_catalog,
    _validate_resource,
    build_catalog_retirement_plan,
)


@dataclass(frozen=True, slots=True)
class PermissionVerification:
    complete: bool
    plan_checksum: str
    actual_checksum: str
    expected_use_changes: tuple[str, ...] = ()


def verify_catalog_retirement(
    *, plan: CatalogRetirementPlan, actual: PermissionCatalogBaseline
) -> PermissionVerification:
    rebuilt = build_catalog_retirement_plan(
        run_id=plan.run_id,
        writer_contract_version=plan.writer_contract_version,
        before=plan.before,
        target_model_checksum=plan.target_model_checksum,
        namespace_type_mappings=plan.namespace_type_mappings,
    )
    if rebuilt != plan:
        _blocked("catalog_plan_changed")
    _validate_catalog(actual)
    before_pin, after_pin = plan.before.authorization, actual.authorization
    release = actual.release
    if (
        release.predecessor_id != plan.before.release.id
        or release.version <= plan.before.release.version
        or after_pin.environment != before_pin.environment
        or after_pin.store_id != before_pin.store_id
        or after_pin.model_checksum != plan.target_model_checksum
        or actual.actions != plan.after_actions
    ):
        _blocked("catalog_result_changed")
    by_key = {model.model_key: model for model in plan.after_models}
    if set(by_key) != {model.model_key for model in actual.models} or any(
        replace(model, id=by_key[model.model_key].id) != by_key[model.model_key] for model in actual.models
    ):
        _blocked("catalog_model_changed")
    expected = _checksum(
        {
            "actions": plan.action_checksum,
            "models": plan.model_checksum,
            "predecessor_release_id": plan.before.release.id,
            "release_key": release.release_key,
        }
    )
    if release.checksum != expected:
        _blocked("catalog_checksum_changed")
    _digest(after_pin.required_relations_checksum)
    return PermissionVerification(True, plan.checksum, _checksum(actual))


def verify_resource_retirement(
    *, plan: ResourceRetirementPlan, actual: PermissionResourceBaseline
) -> PermissionVerification:
    return next(verify_resource_retirements(catalog_plan=plan.catalog_plan, plans=(plan,), actual=(actual,)))


def verify_resource_retirements(
    *,
    catalog_plan: CatalogRetirementPlan,
    plans: Iterable[ResourceRetirementPlan],
    actual: Iterable[PermissionResourceBaseline],
) -> Iterator[PermissionVerification]:
    """Verify every paired resource; a partial iteration never proves the whole batch."""
    context = _resource_context(catalog_plan)
    missing = object()
    for plan, resource in zip_longest(plans, actual, fillvalue=missing):
        if plan is missing or resource is missing:
            _blocked("resource_batch_length_changed")
        if not isinstance(plan, ResourceRetirementPlan):
            _blocked("resource_plan_required")
        # Shared immutable plans need no repeated directory walk. Independently
        # deserialized copies still have to match every frozen catalog fact.
        if plan.catalog_plan is not catalog_plan and plan.catalog_plan != catalog_plan:
            _blocked("catalog_plan_changed")
        rebuilt = _build_resource_retirement_plan(context, plan.before)
        if rebuilt != plan:
            _blocked("resource_plan_changed")
        _validate_resource(resource)
        if resource != plan.before:
            _blocked("resource_provenance_changed")
        yield PermissionVerification(True, plan.checksum, _checksum(resource), plan.expected_use_changes)
