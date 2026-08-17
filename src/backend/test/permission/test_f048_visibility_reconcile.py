"""F048 flattened visibility reconciliation contracts.

覆盖 AC: AC-165, AC-167, AC-168, AC-170, AC-171
"""

from __future__ import annotations

import pytest

from bisheng.common.errcode.permission import (
    PermissionPublishNotReadyError,
)
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)
from bisheng.permission.domain.services.model_policy import (
    DerivedPermissionModel,
    ModelReferenceSummary,
    ensure_model_deletable,
)
from bisheng.permission.domain.services.visibility_projection_service import (
    VisibilityProjectionCompiler,
    VisibilityProjectionReconciler,
)


def _sources(*, second_model: bool = False):
    service = GrantSourceService()
    direct = service.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="100",
        source_type="DIRECT",
    )
    membership = service.canonicalize_source(
        source_id=2,
        subject_type="user",
        subject_id="100",
        source_type="SPACE_MEMBERSHIP",
        source_ref="space:42:user:100",
    )
    grants = []
    for index, source in enumerate((direct, membership)):
        model_key = "editor" if second_model and index else "viewer"
        grants.append(
            GrantSnapshot(
                grant_id=f"g-{model_key}-{index}",
                tenant_id=7,
                resource_type="workflow",
                resource_id="42",
                model=GrantModelSnapshot(
                    model_key=model_key,
                    active=True,
                    action_codes=("download",),
                    derived_level=1,
                ),
                active=True,
                sources=(source,),
            )
        )
    return VisibilityProjectionCompiler().compile(
        tenant_id=7,
        grants=tuple(grants),
        existing_sources=(),
    ).active_sources


def _live_key(source):
    return (
        source.projected_subject,
        "visible",
        f"{source.resource_type}:{source.resource_id}",
    )


def test_multiple_sources_and_models_keep_one_live_tuple_and_repair_only_missing_source() -> None:
    canonical = _sources(second_model=True)
    live = frozenset({_live_key(canonical[0])})

    plan = VisibilityProjectionReconciler().plan(
        canonical_sources=canonical,
        persisted_sources=(canonical[0],),
        live_tuples=live,
    )

    assert [row.contribution_fingerprint for row in plan.upsert_sources] == [
        canonical[1].contribution_fingerprint,
    ]
    assert plan.retire_sources == ()
    assert plan.deltas == ()
    assert plan.blockers == ()


def test_missing_and_orphan_live_tuples_produce_only_exact_aggregate_deltas() -> None:
    canonical = _sources()
    desired_key = _live_key(canonical[0])
    orphan_key = ("user:999", "visible", "workflow:42")

    missing = VisibilityProjectionReconciler().plan(
        canonical_sources=canonical,
        persisted_sources=canonical,
        live_tuples=frozenset(),
    )
    assert [(row.action, row.key) for row in missing.deltas] == [("WRITE", desired_key)]

    orphan = VisibilityProjectionReconciler().plan(
        canonical_sources=canonical,
        persisted_sources=canonical,
        live_tuples=frozenset({desired_key, orphan_key}),
    )
    assert [(row.action, row.key) for row in orphan.deltas] == [("DELETE", orphan_key)]


def test_mixed_source_and_live_drift_does_not_touch_valid_contribution() -> None:
    canonical = _sources(second_model=True)
    valid = canonical[0]
    missing = canonical[1]
    orphan = valid.model_copy(
        update={
            "projected_subject": "user:999",
            "contribution_fingerprint": "a" * 64,
            "tuple_fingerprint": "b" * 64,
            "source_owner_key": "grant_assignee:999",
            "source_locator": "direct:user:999",
            "source_fingerprint": "c" * 64,
        }
    )
    valid_key = _live_key(valid)
    orphan_key = _live_key(orphan)

    plan = VisibilityProjectionReconciler().plan(
        canonical_sources=canonical,
        persisted_sources=(valid, orphan),
        live_tuples=frozenset({valid_key, orphan_key}),
    )

    assert plan.upsert_sources == (missing,)
    assert plan.retire_sources == (orphan,)
    assert {(row.action, row.key) for row in plan.deltas} == {
        ("DELETE", orphan_key),
    }
    assert all(row.key != valid_key for row in plan.deltas)
    assert plan.target_checksum != plan.live_checksum


def test_failed_closed_or_incomplete_snapshot_is_never_guessed_ready() -> None:
    canonical = _sources()
    failed = canonical[0].model_copy(update={"state": "FAILED_CLOSED"})
    reconciler = VisibilityProjectionReconciler()

    plan = reconciler.plan(
        canonical_sources=canonical,
        persisted_sources=(failed,),
        live_tuples=frozenset(),
        ledger_complete=False,
    )

    assert plan.blockers
    with pytest.raises(PermissionPublishNotReadyError):
        reconciler.ensure_ready(plan)


def test_model_delete_remains_blocked_until_source_and_live_residuals_are_zero() -> None:
    model = DerivedPermissionModel(
        model_key="custom",
        name="Custom",
        kind="CUSTOM",
        config_scope="PLATFORM",
        derived_level=1,
        active=True,
        allow_same_level=False,
        selected_action_codes=("download",),
        action_codes=("download",),
    )
    with pytest.raises(ValueError, match="still referenced"):
        ensure_model_deletable(
            model,
            references=ModelReferenceSummary(
                pending_source_count=1,
                live_tuple_count=1,
                residual_checksum="a" * 64,
            ),
        )

    ensure_model_deletable(
        model,
        references=ModelReferenceSummary(),
    )
