"""Safety contracts for the F048 user-group admin Grant cleanup CLI."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import cleanup_f048_user_group_admin_grants as cli


def _candidate(
    assignee_id: int,
    *,
    resource_type: str = "workflow",
    resource_id: str = "wf-1",
    model_key: str = "manager",
    **overrides,
) -> cli.AdminGrantCandidate:
    values = {
        "assignee_id": assignee_id,
        "assignee_version": 1,
        "grant_id": assignee_id + 100,
        "grant_version": 3,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "model_key": model_key,
        "source_type": "USER_GROUP",
        "source_ref": "2#admin",
        "source_locator": "user_group:2#admin",
        "source_fingerprint": f"{assignee_id:064x}",
        "projected_subject": "user_group:2#admin",
        "protected": False,
        "grant_state": "ACTIVE",
        "grant_projection_state": "CURRENT",
        "resource_mode": "CUSTOM",
        "resource_version": 8,
        "resource_projection_state": "CURRENT",
        "resource_parent_type": None,
        "resource_parent_id": None,
    }
    values.update(overrides)
    return cli.AdminGrantCandidate(**values)


def _args(*extra: str):
    return cli.parse_args(
        [
            "--tenant-id",
            "1",
            "--user-group-id",
            "2",
            *extra,
        ]
    )


def test_parse_defaults_to_dry_run_and_apply_requires_exact_confirmations() -> None:
    args = _args()
    assert args.apply is False
    assert args.max_resources == 100
    assert args.after_assignee_id == 0
    assert args.resource_type == ()
    assert args.online is False
    assert args.delay_ms == 100
    assert args.allow_orphan_applications is False
    assert args.allow_unpublished_knowledge_containers is False
    assert args.allow_orphan_knowledge_containers is False
    assert args.quiet is False

    with pytest.raises(SystemExit) as exc_info:
        _args("--apply")
    assert exc_info.value.code == 2

    args = _args(
        "--resource-type",
        "workflow",
        "--resource-type",
        "workflow",
        "--apply",
        "--operator-id",
        "7",
        "--confirm-store-id",
        "store-live",
        "--confirm-model-id",
        "model-live",
        "--confirm-plan-checksum",
        "c" * 64,
    )
    assert args.apply is True
    assert args.resource_type == ("workflow",)


def test_online_mode_requires_apply_and_accepts_non_negative_delay() -> None:
    with pytest.raises(SystemExit) as exc_info:
        _args("--online")
    assert exc_info.value.code == 2

    args = _args(
        "--apply",
        "--online",
        "--delay-ms",
        "0",
        "--operator-id",
        "7",
        "--confirm-store-id",
        "store-live",
        "--confirm-model-id",
        "model-live",
        "--confirm-plan-checksum",
        "c" * 64,
    )
    assert args.online is True
    assert args.delay_ms == 0

    args = _args("--allow-orphan-applications")
    assert args.allow_orphan_applications is True

    args = _args("--allow-unpublished-knowledge-containers")
    assert args.allow_unpublished_knowledge_containers is True

    args = _args("--allow-orphan-knowledge-containers")
    assert args.allow_orphan_knowledge_containers is True

    with pytest.raises(SystemExit) as exc_info:
        _args("--delay-ms", "-1")
    assert exc_info.value.code == 2


def test_parse_rejects_unbounded_or_unknown_resource_selection() -> None:
    with pytest.raises(SystemExit) as exc_info:
        _args("--max-resources", "50001")
    assert exc_info.value.code == 2

    with pytest.raises(SystemExit) as exc_info:
        _args("--resource-type", "unknown")
    assert exc_info.value.code == 2


def test_select_resource_batch_keeps_all_assignees_for_one_resource() -> None:
    candidates = (
        _candidate(10, resource_id="wf-1"),
        _candidate(30, resource_id="wf-2"),
        _candidate(11, resource_id="wf-1", model_key="viewer"),
        _candidate(40, resource_type="assistant", resource_id="as-1"),
    )

    selected, remaining = cli._select_resource_batch(
        candidates,
        after_assignee_id=0,
        max_resources=2,
    )

    assert [(row.resource_type, row.resource_id) for row in selected] == [
        ("workflow", "wf-1"),
        ("workflow", "wf-2"),
    ]
    assert [row.assignee_id for row in selected[0].candidates] == [10, 11]
    assert remaining == 1

    resumed, remaining = cli._select_resource_batch(
        candidates,
        after_assignee_id=30,
        max_resources=2,
    )
    assert [(row.resource_type, row.resource_id) for row in resumed] == [
        ("assistant", "as-1"),
    ]
    assert remaining == 0


def test_candidate_blockers_fail_closed_on_non_current_or_protected_rows() -> None:
    assert cli._candidate_blockers(_candidate(10)) == ()

    blockers = cli._candidate_blockers(
        _candidate(
            10,
            protected=True,
            grant_projection_state="FAILED_CLOSED",
            resource_mode="INHERIT",
            resource_projection_state="FAILED_CLOSED",
        )
    )
    assert any(row.endswith(":protected") for row in blockers)
    assert any("grant_projection_state=FAILED_CLOSED" in row for row in blockers)
    assert any("resource_mode=INHERIT" in row for row in blockers)
    assert any("resource_projection_state=FAILED_CLOSED" in row for row in blockers)


def test_state_matrix_blocks_unfinished_rows_but_allows_inactive_history() -> None:
    blockers = cli._state_matrix_blockers(
        {
            "assignee=ACTIVE|grant=ACTIVE|grant_projection=CURRENT": 10,
            "assignee=INACTIVE|grant=INACTIVE|grant_projection=CURRENT": 8,
            "assignee=PENDING_DELETE|grant=ACTIVE|grant_projection=PROJECTING": 1,
        }
    )

    assert blockers == ("matching_state:assignee=PENDING_DELETE|grant=ACTIVE|grant_projection=PROJECTING:count=1",)


def test_source_match_binds_identity_version_model_and_canonical_subject() -> None:
    candidate = _candidate(10)
    source = SimpleNamespace(
        active=True,
        source_id=10,
        version=1,
        subject_type="user_group",
        subject_id="2",
        userset_relation="admin",
        projected_subject="user_group:2#admin",
        source_type="USER_GROUP",
        source_ref="2#admin",
        source_locator="user_group:2#admin",
        source_fingerprint=candidate.source_fingerprint,
        protected=False,
    )

    assert cli._source_matches_candidate(
        source,
        model_key="manager",
        user_group_id=2,
        candidate=candidate,
    )
    assert not cli._source_matches_candidate(
        source,
        model_key="viewer",
        user_group_id=2,
        candidate=candidate,
    )
    source.version = 2
    assert not cli._source_matches_candidate(
        source,
        model_key="manager",
        user_group_id=2,
        candidate=candidate,
    )


def test_plan_checksum_is_bound_to_store_cursor_and_exact_candidate_versions() -> None:
    args = _args("--max-resources", "1")
    selected, _ = cli._select_resource_batch(
        (_candidate(10),),
        after_assignee_id=0,
        max_resources=1,
    )
    checksum = cli._plan_checksum(
        args=args,
        store_id="store-live",
        model_id="model-live",
        catalog_release_id=8,
        selected=selected,
    )
    changed, _ = cli._select_resource_batch(
        (_candidate(10, assignee_version=2),),
        after_assignee_id=0,
        max_resources=1,
    )
    changed_checksum = cli._plan_checksum(
        args=args,
        store_id="store-live",
        model_id="model-live",
        catalog_release_id=8,
        selected=changed,
    )

    assert len(checksum) == 64
    assert checksum != changed_checksum


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("record", "expected_context_version"),
    [
        (
            SimpleNamespace(
                tenant_id=1,
                resource_type="knowledge_library",
                resource_id="lib-1",
                permission_version=8,
                context_version="knowledge:8",
                status="FAILED",
            ),
            "knowledge:8",
        ),
        (None, "orphan-cleanup:8"),
    ],
)
async def test_resolve_target_supports_unpublished_and_orphan_knowledge_flags_together(
    record,
    expected_context_version: str,
) -> None:
    class FakeResources:
        async def resolve(self, **kwargs):
            raise cli.PermissionInvalidResourceError()

    class FakeAdapter:
        async def load_permission_record(self, **kwargs):
            return record

    runtime = cli.CleanupRuntime(
        client=SimpleNamespace(),
        permission=SimpleNamespace(),
        resources=FakeResources(),
        adapters={"knowledge_library": FakeAdapter()},
    )
    resource = cli.ResourceCleanupPlan(
        resource_type="knowledge_library",
        resource_id="lib-1",
        first_assignee_id=10,
        candidates=(
            _candidate(
                10,
                resource_type="knowledge_library",
                resource_id="lib-1",
                resource_parent_type="knowledge_space",
                resource_parent_id="space-1",
            ),
        ),
    )

    target = await cli._resolve_target(
        args=_args(
            "--allow-unpublished-knowledge-containers",
            "--allow-orphan-knowledge-containers",
        ),
        runtime=runtime,
        actor=cli.PermissionActor(user_id=7, current_tenant_id=1, super_admin=True),
        resource=resource,
    )

    assert target.context_version == expected_context_version
    assert target.resource_version == 8


@pytest.mark.asyncio
async def test_apply_resource_uses_bounded_normal_grant_mutations() -> None:
    candidates = tuple(_candidate(row_id) for row_id in range(1, 42))
    resource = cli.ResourceCleanupPlan(
        resource_type="workflow",
        resource_id="wf-1",
        first_assignee_id=1,
        candidates=candidates,
    )

    class FakeResources:
        def __init__(self) -> None:
            self.version = 8

        async def resolve(self, **kwargs):
            assert kwargs["action"] == "visible"
            return SimpleNamespace(
                tenant_id=1,
                resource_type="workflow",
                resource_id="wf-1",
                resource_version=self.version,
            )

    class FakePermission:
        def __init__(self, resources) -> None:
            self.resources = resources
            self.active = {row.assignee_id: row for row in candidates}
            self.calls: list[tuple[int, ...]] = []

        async def build_grant_context(self, **kwargs):
            sources = tuple(
                SimpleNamespace(
                    active=True,
                    source_id=row.assignee_id,
                    version=row.assignee_version,
                    subject_type="user_group",
                    subject_id="2",
                    userset_relation="admin",
                    projected_subject="user_group:2#admin",
                    source_type=row.source_type,
                    source_ref=row.source_ref,
                    source_locator=row.source_locator,
                    source_fingerprint=row.source_fingerprint,
                    protected=False,
                )
                for row in self.active.values()
            )
            return SimpleNamespace(
                grants=(
                    SimpleNamespace(
                        model=SimpleNamespace(model_key="manager"),
                        sources=sources,
                    ),
                ),
                current_catalog_release_id=8,
            )

        async def mutate_grants(self, **kwargs):
            ids = tuple(change.assignee_id for change in kwargs["changes"])
            self.calls.append(ids)
            for assignee_id in ids:
                del self.active[assignee_id]
            self.resources.version += 1
            return SimpleNamespace(projection=SimpleNamespace(operation_id=100 + len(self.calls)))

    resources = FakeResources()
    permission = FakePermission(resources)
    runtime = cli.CleanupRuntime(
        client=SimpleNamespace(),
        permission=permission,
        resources=resources,
        adapters={},
    )
    removed, operation_ids = await cli._apply_resource(
        args=_args(),
        runtime=runtime,
        actor=cli.PermissionActor(user_id=7, current_tenant_id=1, super_admin=True),
        resource=resource,
        plan_checksum="c" * 64,
    )

    assert removed == 41
    assert [len(call) for call in permission.calls] == [40, 1]
    assert operation_ids == (101, 102)
    assert permission.active == {}
