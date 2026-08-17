"""Single-slot visible source projection compiler contracts.

覆盖 AC: AC-159, AC-164, AC-165, AC-166, AC-168, AC-169, AC-171
"""

from __future__ import annotations

from dataclasses import replace

from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceRecord,
    GrantSourceService,
)
from bisheng.permission.domain.services.visibility_projection_service import (
    VisibilityProjectionCompiler,
)


def _grant(
    *,
    grant_id: str,
    model_key: str,
    sources: tuple[GrantSourceRecord, ...],
    model_active: bool = True,
    actions: tuple[str, ...] = ("edit",),
) -> GrantSnapshot:
    return GrantSnapshot(
        grant_id=grant_id,
        tenant_id=7,
        resource_type="knowledge_space",
        resource_id="100",
        model=GrantModelSnapshot(
            model_key=model_key,
            active=model_active,
            action_codes=actions,
        ),
        active=True,
        sources=sources,
    )


def test_direct_department_subtree_group_and_protected_compile_shallow_sources() -> None:
    source_service = GrantSourceService()
    sources = (
        source_service.canonicalize_source(
            source_id=1,
            subject_type="user",
            subject_id="10",
            source_type="DIRECT",
        ),
        source_service.canonicalize_source(
            source_id=2,
            subject_type="department",
            subject_id="17",
            source_type="DEPARTMENT",
        ),
        source_service.canonicalize_source(
            source_id=3,
            subject_type="department",
            subject_id="18",
            source_type="DEPARTMENT",
            include_children=True,
        ),
        source_service.canonicalize_source(
            source_id=4,
            subject_type="user_group",
            subject_id="8",
            source_type="USER_GROUP",
            userset_relation="admin",
        ),
        source_service.canonicalize_source(
            source_id=5,
            subject_type="user",
            subject_id="11",
            source_type="CREATOR",
            source_ref="knowledge_space:100",
            protected=True,
        ),
    )

    result = VisibilityProjectionCompiler().compile(
        tenant_id=7,
        grants=(_grant(grant_id="g1", model_key="manager", sources=sources),),
        existing_sources=(),
    )

    assert {row.projected_subject for row in result.active_sources} == {
        "user:10",
        "department:17#member",
        "department:18#subtree_member",
        "user_group:8#admin",
        "user:11",
    }
    assert {row.visibility_class for row in result.active_sources} == {
        "ordinary",
        "protected",
    }
    assert {row.source_owner_key for row in result.active_sources} == {
        f"grant_assignee:{source.source_id}" for source in sources
    }
    assert {(row.action, row.relation) for row in result.deltas} == {
        ("WRITE", "visible"),
    }
    assert all(row.object == "knowledge_space:100" for row in result.deltas)


def test_multiple_models_and_sources_share_one_aggregate_until_last_revoke() -> None:
    source_service = GrantSourceService()
    direct = source_service.canonicalize_source(
        source_id=10,
        subject_type="user",
        subject_id="42",
        source_type="DIRECT",
    )
    membership = source_service.canonicalize_source(
        source_id=11,
        subject_type="user",
        subject_id="42",
        source_type="SPACE_MEMBERSHIP",
        source_ref="573",
    )
    compiler = VisibilityProjectionCompiler()
    initial = compiler.compile(
        tenant_id=7,
        grants=(
            _grant(grant_id="g-editor", model_key="editor", sources=(direct,)),
            _grant(grant_id="g-viewer", model_key="viewer", sources=(membership,)),
        ),
        existing_sources=(),
    )
    assert len(initial.active_sources) == 2
    assert len({row.contribution_fingerprint for row in initial.active_sources}) == 2
    assert [(row.action, row.relation) for row in initial.deltas] == [
        ("WRITE", "visible")
    ]

    one_remaining = compiler.compile(
        tenant_id=7,
        grants=(_grant(grant_id="g-viewer", model_key="viewer", sources=(membership,)),),
        existing_sources=initial.active_sources,
    )
    assert len(one_remaining.active_sources) == 1
    assert len(one_remaining.retired_sources) == 1
    assert one_remaining.deltas == ()

    none_remaining = compiler.compile(
        tenant_id=7,
        grants=(),
        existing_sources=one_remaining.active_sources,
    )
    assert none_remaining.active_sources == ()
    assert len(none_remaining.retired_sources) == 1
    assert [(row.action, row.relation) for row in none_remaining.deltas] == [
        ("DELETE", "visible")
    ]


def test_inactive_and_visibility_only_existing_grants_still_contribute() -> None:
    source = GrantSourceService().canonicalize_source(
        source_id=20,
        subject_type="user",
        subject_id="42",
        source_type="DIRECT",
    )
    result = VisibilityProjectionCompiler().compile(
        tenant_id=7,
        grants=(
            _grant(
                grant_id="g-inactive",
                model_key="inactive-custom",
                sources=(source,),
                model_active=False,
                actions=(),
            ),
        ),
        existing_sources=(),
    )
    assert len(result.active_sources) == 1
    assert result.active_sources[0].model_key == "inactive-custom"
    assert [(row.action, row.relation) for row in result.deltas] == [
        ("WRITE", "visible")
    ]


def test_system_public_and_shared_sources_do_not_enter_grant_projection() -> None:
    direct = GrantSourceService().canonicalize_source(
        source_id=30,
        subject_type="user",
        subject_id="42",
        source_type="DIRECT",
    )
    system_source = replace(
        direct,
        source_id=31,
        source_type="PUBLIC",
        source_locator="public_policy:1",
        source_fingerprint="a" * 64,
    )
    result = VisibilityProjectionCompiler().compile(
        tenant_id=7,
        grants=(_grant(grant_id="g1", model_key="viewer", sources=(system_source,)),),
        existing_sources=(),
    )
    assert result.active_sources == ()
    assert result.retired_sources == ()
    assert result.deltas == ()


def test_compiler_is_deterministic_and_has_no_visibility_slot() -> None:
    source = GrantSourceService().canonicalize_source(
        source_id=40,
        subject_type="user",
        subject_id="42",
        source_type="DIRECT",
    )
    compiler = VisibilityProjectionCompiler()
    first = compiler.compile(
        tenant_id=7,
        grants=(_grant(grant_id="g1", model_key="viewer", sources=(source,)),),
        existing_sources=(),
    )
    second = compiler.compile(
        tenant_id=7,
        grants=(_grant(grant_id="g1", model_key="viewer", sources=(source,)),),
        existing_sources=(),
    )
    assert first == second
    assert first.source_checksum == second.source_checksum
    assert first.aggregate_checksum == second.aggregate_checksum
    assert all(not hasattr(row, "visibility_slot") for row in first.active_sources)
