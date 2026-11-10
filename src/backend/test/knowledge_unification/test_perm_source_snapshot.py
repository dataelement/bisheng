"""F118 target-scoped Grant snapshots. 覆盖 AC: AC-78, AC-80, AC-81, AC-83."""

from dataclasses import replace

import pytest

from bisheng.common.errcode.permission import PermissionModelStateConflictError
from bisheng.permission.domain.services import grant_source_service as module
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)


def scoped(*, active=True, level=3):
    return module.model_snapshot_for_target(
        GrantModelSnapshot(
            "mixed",
            active,
            ("download",),
            derived_level=1,
            visibility_only_resource_types=("tool",),
            visibility_level=level,
        ),
        resource_type="tool",
        applicable_action_codes=(),
    )


def grant(model):
    return GrantSnapshot("g1", 101, "tool", "tool-1", model, False, ())


def test_target_scope_retains_original_tier_without_download():
    result = scoped()
    assert result.visibility_only and result.derived_level == 3 and result.action_codes == ()
    original = GrantModelSnapshot(
        "mixed", True, ("download",), derived_level=1, visibility_only_resource_types=("tool",), visibility_level=3
    )
    file_result = module.model_snapshot_for_target(
        original, resource_type="knowledge_file", applicable_action_codes=("download",)
    )
    assert (
        not file_result.visibility_only and file_result.action_codes == ("download",) and file_result.derived_level == 1
    )
    assert original.derived_level == 1 and original.action_codes == ("download",)


@pytest.mark.parametrize("level", [None, True, 0, 5])
def test_invalid_marker_level_is_not_a_visibility_capability(level):
    with pytest.raises(ValueError, match="visibility"):
        scoped(level=level)


def test_source_add_and_remove_preserve_other_contribution_for_same_subject():
    service = GrantSourceService()
    first = service.canonicalize_source(source_id=1, subject_type="user", subject_id="42", source_type="DIRECT")
    second = service.canonicalize_source(
        source_id=2, subject_type="user", subject_id="42", source_type="OTHER", source_ref="retained-business"
    )
    created = service.add_source(grant(scoped()), first)
    assert {delta.relation for delta in created.deltas} == {"model", "grant", "ordinary_assignee"}
    added = service.add_source(created.grant, second)
    assert added.deltas == ()
    removed = service.remove_source(added.grant, source_id=1)
    assert removed.deltas == () and removed.grant.active
    assert removed.grant.sources == (second,) and second.source_fingerprint == added.grant.sources[1].source_fingerprint
    last = service.remove_source(removed.grant, source_id=2)
    assert not last.grant.active and {delta.relation for delta in last.deltas} == {"model", "grant", "ordinary_assignee"}


def test_inactive_existing_source_can_be_removed_but_not_added():
    service = GrantSourceService()
    source = service.canonicalize_source(source_id=1, subject_type="user", subject_id="42", source_type="DIRECT")
    inactive = replace(grant(scoped(active=False)), active=True, sources=(source,))
    assert not service.remove_source(inactive, source_id=1).grant.active
    with pytest.raises(PermissionModelStateConflictError):
        service.add_source(inactive, source)


def test_unmarked_empty_or_marker_for_other_type_cannot_be_added():
    service = GrantSourceService()
    source = service.canonicalize_source(source_id=1, subject_type="user", subject_id="42", source_type="DIRECT")
    for model in (
        GrantModelSnapshot("empty", True, (), derived_level=1),
        replace(scoped(), visibility_only_resource_types=("app",)),
    ):
        with pytest.raises(PermissionModelStateConflictError):
            service.add_source(grant(model), source)
