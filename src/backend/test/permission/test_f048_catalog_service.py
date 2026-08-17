"""F048 Catalog publisher crash-matrix contracts.

覆盖 AC: AC-03, AC-06, AC-13, AC-14, AC-16, AC-17, AC-18,
AC-27, AC-66, AC-67, AC-68, AC-69, AC-143, AC-156, AC-164, AC-165, AC-167
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from bisheng.common.errcode.permission import (
    AuthorizationModelMismatchError,
    PermissionImpactExpiredError,
    PermissionModelStateConflictError,
    PermissionProjectionFailedError,
    PermissionPublishNotReadyError,
    PermissionVersionConflictError,
)
from bisheng.permission.domain.services.catalog_policy import (
    ACTION_RESOURCE_SCOPES,
    REGISTERED_ACTION_CODES,
    CatalogAction,
    derive_action_release,
)
from bisheng.permission.domain.services.catalog_service import (
    CatalogCommitUnknownError,
    CatalogDraftBuildInput,
    CatalogDraftSnapshot,
    CatalogImpactSummary,
    CatalogPublishContext,
    CatalogService,
)
from bisheng.permission.domain.services.model_policy import (
    CustomModelSelection,
    ModelReferenceSummary,
    derive_permission_models,
)


class FakeCatalogState:
    def __init__(self, draft: CatalogDraftSnapshot) -> None:
        self.draft = draft
        self.current_release_id = draft.predecessor_release_id
        self.status = "DRAFT"
        self.fenced = False
        self.log: list[str] = []
        self.fail_finalize = False

    async def prepare_publish(
        self,
        *,
        draft_id: int,
        expected_current_release_id: int,
        idempotency_key: str,
    ) -> CatalogPublishContext:
        self.log.append("prepare")
        assert draft_id == self.draft.release_id
        assert idempotency_key
        if self.status == "CURRENT":
            return self._context(already_current=True)
        if expected_current_release_id != self.current_release_id:
            raise PermissionVersionConflictError()
        self.fenced = True
        return self._context()

    async def mark_projecting(self, context: CatalogPublishContext) -> None:
        self.log.append("projecting")
        assert self.fenced
        self.status = "PROJECTING"

    async def mark_committed(
        self,
        context: CatalogPublishContext,
        *,
        commit_checksum: str,
    ) -> None:
        self.log.append("committed")
        assert commit_checksum
        self.status = "COMMITTED"

    async def finalize_publish(self, context: CatalogPublishContext) -> None:
        self.log.append("finalize")
        if self.fail_finalize:
            raise RuntimeError("SQL finalize crash")
        self.status = "CURRENT"
        self.current_release_id = self.draft.release_id
        self.fenced = False

    async def abort_before_commit(
        self,
        context: CatalogPublishContext,
        *,
        reason: str,
    ) -> None:
        self.log.append("abort")
        assert reason
        self.status = "DRAFT"
        self.fenced = False

    async def fail_closed(
        self,
        context: CatalogPublishContext,
        *,
        reason: str,
    ) -> None:
        self.log.append("failed_closed")
        assert reason
        self.status = "FAILED_CLOSED"
        self.fenced = True

    async def get_publish_context(self, draft_id: int) -> CatalogPublishContext:
        assert draft_id == self.draft.release_id
        return self._context(already_current=self.status == "CURRENT")

    async def save_draft(
        self,
        draft: CatalogDraftSnapshot,
    ) -> CatalogDraftSnapshot:
        self.log.append("save_draft")
        self.draft = draft
        return draft

    def _context(self, *, already_current: bool = False) -> CatalogPublishContext:
        return CatalogPublishContext(
            draft=self.draft,
            current_release_id=self.draft.predecessor_release_id,
            current_release_key=self.draft.predecessor_release_key,
            status=self.status,
            already_current=already_current,
        )


class FakeImpact:
    def __init__(
        self,
        *checksums: str,
        analysis: CatalogImpactSummary | None = None,
    ) -> None:
        self.checksums = list(checksums)
        self.calls = 0
        self.analysis = analysis
        self.analyzed = None

    async def recalculate(self, draft: CatalogDraftSnapshot) -> str:
        self.calls += 1
        if self.checksums:
            return self.checksums.pop(0)
        return draft.impact_checksum

    async def analyze_draft(
        self,
        *,
        action_impact,
        model_impact,
        **_release_context,
    ):
        self.analyzed = (action_impact, model_impact)
        assert self.analysis is not None
        return self.analysis


class FakeProjector:
    def __init__(self, draft: CatalogDraftSnapshot) -> None:
        self.draft = draft
        self.active = {draft.predecessor_release_key}
        self.available_actions = set(draft.required_action_codes)
        self.log: list[str] = []
        self.commits: list[tuple] = []
        self.fail_at: str | None = None
        self.commit_attempts = 0

    async def validate_required_actions(self, action_codes: tuple[str, ...]) -> None:
        self.log.append("validate")
        missing = set(action_codes) - self.available_actions
        if missing:
            raise AuthorizationModelMismatchError(msg=f"missing action relations: {sorted(missing)}")

    async def stage_model_releases(self, draft: CatalogDraftSnapshot) -> None:
        self.log.append("stage")
        if self.fail_at == "stage":
            raise RuntimeError("stage failed")

    async def run_model_tests(self, draft: CatalogDraftSnapshot) -> None:
        self.log.append("model_tests")
        if self.fail_at == "model_tests":
            raise RuntimeError("model tests failed")

    async def arm_recent_marker(self, draft: CatalogDraftSnapshot) -> None:
        self.log.append("recent")
        if self.fail_at == "recent":
            raise RuntimeError("recent marker failed")

    async def commit_active(self, changes: tuple) -> str:
        self.log.append("commit")
        self.commit_attempts += 1
        self.commits.append(changes)
        if self.fail_at == "timeout_new":
            self.active = {self.draft.release_key}
            self.fail_at = None
            raise CatalogCommitUnknownError("timeout after commit")
        if self.fail_at == "timeout_old":
            self.fail_at = None
            raise CatalogCommitUnknownError("timeout before commit")
        if self.fail_at == "timeout_both":
            self.active = {
                self.draft.predecessor_release_key,
                self.draft.release_key,
            }
            raise CatalogCommitUnknownError("invariant unknown")
        if self.fail_at == "timeout_none":
            self.active = set()
            raise CatalogCommitUnknownError("invariant unknown")
        self.active = {self.draft.release_key}
        return "c" * 64

    async def read_active_release_keys(self) -> frozenset[str]:
        self.log.append("read_active")
        return frozenset(self.active)


class FakeEvents:
    def __init__(self) -> None:
        self.audit: list[tuple[str, dict]] = []
        self.metrics: list[tuple[str, dict]] = []

    async def record_audit(self, event: str, fields: dict) -> None:
        self.audit.append((event, fields))

    async def emit_metric(self, event: str, fields: dict) -> None:
        self.metrics.append((event, fields))


def _draft(**changes) -> CatalogDraftSnapshot:
    base = CatalogDraftSnapshot(
        release_id=2,
        release_key="catalog-v2",
        predecessor_release_id=1,
        predecessor_release_key="catalog-v1",
        release_checksum="a" * 64,
        impact_checksum="b" * 64,
        required_action_codes=("edit", "download"),
        blockers=(),
    )
    return replace(base, **changes)


def _assigned_actions(*, edit_level: int = 2) -> tuple[CatalogAction, ...]:
    levels = {
        "download": 1,
        "use": 1,
        "rename": 2,
        "edit": edit_level,
        "create_folder": 2,
        "upload_file": 2,
        "move": 2,
        "manage_permission": 3,
        "share": 3,
        "publish": 3,
        "unpublish": 3,
        "delete": 4,
    }
    return tuple(
        CatalogAction(
            code=code,
            name=code,
            level=levels[code],
            resource_types=ACTION_RESOURCE_SCOPES[code],
        )
        for code in REGISTERED_ACTION_CODES
    )


def _service(
    draft: CatalogDraftSnapshot,
    *,
    impact: FakeImpact | None = None,
):
    state = FakeCatalogState(draft)
    projector = FakeProjector(draft)
    events = FakeEvents()
    service = CatalogService(
        state=state,
        impact=impact or FakeImpact(),
        projector=projector,
        events=events,
    )
    return service, state, projector, events


async def _publish(service: CatalogService):
    return await service.publish(
        draft_id=2,
        expected_current_release_id=1,
        idempotency_key="publish-2",
    )


@pytest.mark.asyncio
async def test_build_draft_recomputes_complete_release_and_cross_tenant_impact() -> None:
    before_actions = derive_action_release(_assigned_actions(edit_level=2))
    custom = CustomModelSelection(
        model_key="shared",
        name="共享模型",
        action_codes=("edit",),
    )
    before_models = derive_permission_models(
        before_actions,
        custom_models=(custom,),
    )
    analysis = CatalogImpactSummary(
        checksum="9" * 64,
        resource_count=7,
        grant_count=11,
        assignee_count=13,
        expansion_count=0,
        revocation_count=4,
        blockers=(),
    )
    impact = FakeImpact(analysis=analysis)
    seed = _draft()
    service, state, _projector, _events = _service(seed, impact=impact)
    draft = await service.build_draft(
        CatalogDraftBuildInput(
            release_id=2,
            release_key="catalog-v2",
            predecessor_release_id=1,
            predecessor_release_key="catalog-v1",
            before_actions=before_actions,
            before_models=before_models,
            actions=_assigned_actions(edit_level=3),
            custom_models=(custom,),
            grant_references={"shared": ("g-1", "g-2")},
        )
    )
    assert draft.action_release is not None
    assert draft.model_release is not None
    assert draft.impact == analysis
    action_impact, model_impact = impact.analyzed
    assert action_impact.changed_action_codes == ("edit",)
    assert {"viewer", "editor", "manager", "owner"} <= set(action_impact.affected_model_keys)
    assert model_impact.affected_grant_refs == ("g-1", "g-2")
    assert state.log == ["save_draft"]


@pytest.mark.asyncio
async def test_delete_model_accepts_active_zero_reference_and_preserves_history() -> None:
    actions = derive_action_release(_assigned_actions())
    custom = CustomModelSelection(
        model_key="delete-directly",
        name="直接删除",
        action_codes=("edit", "manage_permission"),
        active=True,
    )
    before_models = derive_permission_models(actions, custom_models=(custom,))
    analysis = CatalogImpactSummary(
        checksum="8" * 64,
        resource_count=0,
        grant_count=0,
        assignee_count=0,
        expansion_count=0,
        revocation_count=0,
    )
    service, state, _projector, _events = _service(
        _draft(),
        impact=FakeImpact(analysis=analysis),
    )

    draft = await service.build_draft(
        CatalogDraftBuildInput(
            release_id=2,
            release_key="catalog-v2",
            predecessor_release_id=1,
            predecessor_release_key="catalog-v1",
            before_actions=actions,
            before_models=before_models,
            actions=_assigned_actions(),
            custom_models=(),
            model_reference_summaries={
                "delete-directly": ModelReferenceSummary(),
            },
        )
    )

    assert draft.model_release is not None
    assert "delete-directly" not in {model.model_key for model in draft.model_release.models}
    assert "delete-directly" in {model.model_key for model in before_models.models}
    assert state.log == ["save_draft"]


@pytest.mark.asyncio
async def test_delete_model_fails_closed_for_unknown_or_nonzero_references() -> None:
    actions = derive_action_release(_assigned_actions())
    custom = CustomModelSelection(
        model_key="blocked-delete",
        name="阻断删除",
        action_codes=("edit",),
    )
    before_models = derive_permission_models(actions, custom_models=(custom,))

    for summaries in (
        {},
        {
            "blocked-delete": ModelReferenceSummary(
                failed_source_count=1,
                residual_checksum="a" * 64,
            )
        },
    ):
        service, state, _projector, _events = _service(_draft())
        with pytest.raises(PermissionModelStateConflictError):
            await service.build_draft(
                CatalogDraftBuildInput(
                    release_id=2,
                    release_key="catalog-v2",
                    predecessor_release_id=1,
                    predecessor_release_key="catalog-v1",
                    before_actions=actions,
                    before_models=before_models,
                    actions=_assigned_actions(),
                    custom_models=(),
                    model_reference_summaries=summaries,
                )
            )
        assert state.log == []


@pytest.mark.asyncio
async def test_publish_orders_fence_stage_marker_two_tuple_commit_and_finalize() -> None:
    service, state, projector, events = _service(_draft())
    outcome = await _publish(service)
    assert outcome.status == "CURRENT"
    assert state.fenced is False
    assert state.log == ["prepare", "projecting", "committed", "finalize"]
    assert projector.log == [
        "validate",
        "stage",
        "model_tests",
        "recent",
        "commit",
    ]
    assert [change.action for change in projector.commits[0]] == [
        "DELETE",
        "WRITE",
    ]
    assert len(projector.commits[0]) == 2
    assert events.audit[-1][0] == "permission_catalog_publish"
    assert events.metrics[-1][0] == "permission_catalog_publish"


@pytest.mark.asyncio
async def test_changed_impact_checksum_expires_and_releases_fence() -> None:
    service, state, projector, _ = _service(
        _draft(),
        impact=FakeImpact("d" * 64),
    )
    with pytest.raises(PermissionImpactExpiredError):
        await _publish(service)
    assert state.status == "DRAFT"
    assert state.fenced is False
    assert "stage" not in projector.log


@pytest.mark.asyncio
async def test_concurrent_admin_expected_current_conflict_does_not_fence() -> None:
    service, state, _, _ = _service(_draft())
    with pytest.raises(PermissionVersionConflictError):
        await service.publish(
            draft_id=2,
            expected_current_release_id=999,
            idempotency_key="stale-admin",
        )
    assert state.fenced is False
    assert state.status == "DRAFT"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["stage", "model_tests", "recent"])
async def test_precommit_failure_keeps_old_release_and_clears_fence(
    failure: str,
) -> None:
    service, state, projector, _ = _service(_draft())
    projector.fail_at = failure
    with pytest.raises(PermissionProjectionFailedError):
        await _publish(service)
    assert projector.active == {"catalog-v1"}
    assert "commit" not in projector.log
    assert state.status == "DRAFT"
    assert state.fenced is False


@pytest.mark.asyncio
async def test_missing_pinned_action_relation_is_rejected_before_stage() -> None:
    service, state, projector, _ = _service(_draft())
    projector.available_actions.remove("download")
    with pytest.raises(AuthorizationModelMismatchError):
        await _publish(service)
    assert state.status == "DRAFT"
    assert state.fenced is False
    assert "stage" not in projector.log


@pytest.mark.asyncio
async def test_finalize_crash_keeps_fence_and_reconciles_forward() -> None:
    service, state, projector, _ = _service(_draft())
    state.fail_finalize = True
    with pytest.raises(PermissionProjectionFailedError):
        await _publish(service)
    assert state.status == "COMMITTED"
    assert state.fenced is True
    assert projector.active == {"catalog-v2"}

    state.fail_finalize = False
    outcome = await service.reconcile(draft_id=2)
    assert outcome.status == "CURRENT"
    assert state.fenced is False


@pytest.mark.asyncio
async def test_commit_timeout_with_new_active_finalizes_without_recommit() -> None:
    service, state, projector, _ = _service(_draft())
    projector.fail_at = "timeout_new"
    outcome = await _publish(service)
    assert outcome.reconciled is True
    assert state.status == "CURRENT"
    assert projector.commit_attempts == 1


@pytest.mark.asyncio
async def test_commit_timeout_with_old_active_retries_exact_commit() -> None:
    service, state, projector, _ = _service(_draft())
    projector.fail_at = "timeout_old"
    outcome = await _publish(service)
    assert outcome.reconciled is True
    assert state.status == "CURRENT"
    assert projector.commit_attempts == 2
    assert projector.commits[0] == projector.commits[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout_both", "timeout_none"])
async def test_invalid_active_state_fails_closed_and_keeps_global_fence(
    failure: str,
) -> None:
    service, state, projector, _ = _service(_draft())
    projector.fail_at = failure
    with pytest.raises(PermissionProjectionFailedError):
        await _publish(service)
    assert state.status == "FAILED_CLOSED"
    assert state.fenced is True


@pytest.mark.asyncio
async def test_blocked_draft_never_stages_and_repeat_publish_is_idempotent() -> None:
    blocked_service, blocked_state, blocked_projector, _ = _service(
        _draft(blockers=("active custom model has no actions",))
    )
    with pytest.raises(PermissionPublishNotReadyError):
        await _publish(blocked_service)
    assert blocked_state.fenced is False
    assert blocked_projector.log == []

    service, _state, projector, _ = _service(_draft())
    first = await _publish(service)
    second = await _publish(service)
    assert first.release_id == second.release_id == 2
    assert second.idempotent is True
    assert projector.commit_attempts == 1
