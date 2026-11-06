"""Pure verification of a frozen permission subplan, without live I/O."""

from dataclasses import dataclass, replace

from bisheng.permission.migration.f118_plan import (
    CatalogRetirementPlan,
    PermissionCatalogBaseline,
    PermissionResourceBaseline,
    ResourceRetirementPlan,
    _blocked,
    _checksum,
    _digest,
    _validate_catalog,
    _validate_resource,
    build_catalog_retirement_plan,
    build_resource_retirement_plan,
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
    rebuilt = build_resource_retirement_plan(catalog_plan=plan.catalog_plan, before=plan.before)
    if rebuilt != plan:
        _blocked("resource_plan_changed")
    _validate_resource(actual)
    if actual != plan.before:
        _blocked("resource_provenance_changed")
    return PermissionVerification(True, plan.checksum, _checksum(actual), plan.expected_use_changes)
