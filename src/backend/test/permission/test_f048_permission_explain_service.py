"""F048 minimal, non-authoritative permission explanation contracts.

覆盖 AC: AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-65
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)
from bisheng.permission.domain.services.permission_explain_service import (
    InheritedGrantSet,
    PermissionExplainContext,
    PermissionExplainService,
)


class FakeEvents:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.rows = []

    async def emit(self, name: str, fields: dict) -> None:
        if self.fail:
            raise RuntimeError("display/telemetry dependency unavailable")
        self.rows.append((name, fields))


def _grant(
    grant_id: str,
    model_key: str,
    level: int,
    actions: tuple[str, ...],
) -> GrantSnapshot:
    return GrantSnapshot(
        grant_id=grant_id,
        tenant_id=7,
        resource_type="folder",
        resource_id="42",
        model=GrantModelSnapshot(
            model_key=model_key,
            active=True,
            action_codes=actions,
            derived_level=level,
        ),
        active=False,
        sources=(),
    )


def _sources():
    return GrantSourceService()


@pytest.mark.asyncio
async def test_custom_mode_keeps_direct_and_department_sources_as_separate_rows() -> None:
    sources = _sources()
    direct = sources.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="100",
        source_type="DIRECT",
    )
    department = sources.canonicalize_source(
        source_id=2,
        subject_type="department",
        subject_id="17",
        source_type="DEPARTMENT",
    )
    editor = sources.add_source(
        _grant("g-editor", "editor", 2, ("download", "edit")),
        direct,
    ).grant
    editor = sources.add_source(editor, department).grant
    service = PermissionExplainService(events=FakeEvents())
    explanation = await service.explain(
        PermissionExplainContext(
            tenant_id=7,
            resource_type="folder",
            resource_id="42",
            resource_version=3,
            mode="CUSTOM",
            parent_type="knowledge_space",
            parent_id="10",
            local_grants=(editor,),
            inherited=None,
            actor_projected_subjects=frozenset({"user:100", "department:17#member"}),
            can_manage_roster=True,
        )
    )
    assert [row.subject_type for row in explanation.sources] == [
        "user",
        "department",
    ]
    assert [row.source_type for row in explanation.sources] == [
        "DIRECT",
        "DEPARTMENT",
    ]
    assert explanation.action_codes == ("download", "edit")
    assert explanation.roster_complete is True
    assert not hasattr(explanation.sources[0], "subject_name")


@pytest.mark.asyncio
async def test_inherit_mode_uses_inherited_ordinary_and_local_protected_only() -> None:
    sources = _sources()
    local_ordinary = sources.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="200",
        source_type="DIRECT",
    )
    local_protected = sources.canonicalize_source(
        source_id=2,
        subject_type="user",
        subject_id="201",
        source_type="CREATOR",
        source_ref="folder:42",
        protected=True,
    )
    inherited_department = sources.canonicalize_source(
        source_id=3,
        subject_type="department",
        subject_id="17",
        source_type="DEPARTMENT",
    )
    owner = sources.add_source(
        _grant("g-owner", "owner", 4, ("delete",)),
        local_protected,
    ).grant
    editor = sources.add_source(
        _grant("g-local", "editor", 2, ("edit",)),
        local_ordinary,
    ).grant
    inherited = sources.add_source(
        _grant("g-parent", "editor", 2, ("download", "edit")),
        inherited_department,
    ).grant
    explanation = await PermissionExplainService().explain(
        PermissionExplainContext(
            tenant_id=7,
            resource_type="folder",
            resource_id="42",
            resource_version=3,
            mode="INHERIT",
            parent_type="knowledge_space",
            parent_id="10",
            local_grants=(editor, owner),
            inherited=InheritedGrantSet(
                resource_type="knowledge_space",
                resource_id="10",
                grants=(inherited,),
            ),
            actor_projected_subjects=frozenset({"user:201", "department:17#member"}),
            can_manage_roster=True,
        )
    )
    assert {row.source_id for row in explanation.sources} == {2, 3}
    inherited_row = next(row for row in explanation.sources if row.source_id == 3)
    assert inherited_row.scope == "INHERITED"
    assert inherited_row.inherited_from == "knowledge_space:10"
    assert inherited_row.editable is False
    protected_row = next(row for row in explanation.sources if row.source_id == 2)
    assert protected_row.scope == "LOCAL"
    assert protected_row.protected is True
    assert protected_row.editable is False


@pytest.mark.asyncio
async def test_without_roster_permission_only_actor_sources_are_returned() -> None:
    sources = _sources()
    actor = sources.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="100",
        source_type="DIRECT",
    )
    other = sources.canonicalize_source(
        source_id=2,
        subject_type="user",
        subject_id="200",
        source_type="DIRECT",
    )
    grant = sources.add_source(
        _grant("g-editor", "editor", 2, ("edit",)),
        actor,
    ).grant
    grant = sources.add_source(grant, other).grant
    explanation = await PermissionExplainService().explain(
        PermissionExplainContext(
            tenant_id=7,
            resource_type="folder",
            resource_id="42",
            resource_version=3,
            mode="CUSTOM",
            parent_type="knowledge_space",
            parent_id="10",
            local_grants=(grant,),
            inherited=None,
            actor_projected_subjects=frozenset({"user:100"}),
            can_manage_roster=False,
        )
    )
    assert [row.source_id for row in explanation.sources] == [1]
    assert explanation.roster_complete is False
    assert explanation.action_codes == ("edit",)


@pytest.mark.asyncio
async def test_inactive_model_or_grant_never_appears_in_explanation() -> None:
    sources = _sources()
    source = sources.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="100",
        source_type="DIRECT",
    )
    grant = sources.add_source(
        _grant("g-editor", "editor", 2, ("edit",)),
        source,
    ).grant
    inactive_model = replace(
        grant,
        model=replace(grant.model, active=False),
    )
    inactive_grant = replace(grant, active=False)
    for candidate in (inactive_model, inactive_grant):
        explanation = await PermissionExplainService().explain(
            PermissionExplainContext(
                tenant_id=7,
                resource_type="folder",
                resource_id="42",
                resource_version=3,
                mode="CUSTOM",
                parent_type="knowledge_space",
                parent_id="10",
                local_grants=(candidate,),
                inherited=None,
                actor_projected_subjects=frozenset({"user:100"}),
                can_manage_roster=True,
            )
        )
        assert explanation.sources == ()
        assert explanation.action_codes == ()


@pytest.mark.asyncio
async def test_observability_or_display_failure_cannot_change_explanation() -> None:
    sources = _sources()
    source = sources.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="100",
        source_type="DIRECT",
    )
    grant = sources.add_source(
        _grant("g-editor", "editor", 2, ("edit",)),
        source,
    ).grant
    context = PermissionExplainContext(
        tenant_id=7,
        resource_type="folder",
        resource_id="42",
        resource_version=3,
        mode="CUSTOM",
        parent_type="knowledge_space",
        parent_id="10",
        local_grants=(grant,),
        inherited=None,
        actor_projected_subjects=frozenset({"user:100"}),
        can_manage_roster=False,
    )
    healthy = await PermissionExplainService(events=FakeEvents()).explain(context)
    degraded = await PermissionExplainService(events=FakeEvents(fail=True)).explain(context)
    assert degraded == healthy
