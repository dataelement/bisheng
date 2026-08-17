"""T016 — version records: when they are written, what a terminal state may be (AC-02 / AC-18 / AC-39 / AC-40 / AC-43).

``app_version`` is INSERT-only with one single-column latch, which makes *when*
a row appears the whole design (design D6):

* **After the gate, never before.** The approval gate writes and commits on its
  own session and can raise ("this deployment never seeded the scenario") or
  resolve no approver at all. Inserting first would leave a row that AC-40 says
  may never be deleted, with no terminal state and no approval request attached
  — a zombie version in every owner's version list.
* **After precheck and the scan, never before.** A submission that failed
  precheck exists only in ``app_deployment`` (AC-02 / 决议-9). The guard is on
  the service, not on the caller's discipline.
* **``EXCEPTION`` still counts as "entered approval".** An empty approver set is
  an administrator's problem (AC-18); if no version row exists, there is nothing
  for the administrator to publish once they fix it.
* **The gate is not transactional with the INSERT.** It commits on its own
  session, so "both or neither" is impossible and is not pretended: the failure
  path explicitly cancels the request it just created and records
  ``app.release.rollback``.

"待上线" is asserted to be a *derived* display, not a fifth ``terminal_state``:
the version-outcome line and the app-availability line are orthogonal (spec
§3.0.2) and collapsing them into one column is how they stop being orthogonal.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.asyncio


class _FakeApproval:
    """Stand-in for Wave 3's ``publish_approval_service`` — the port ``record_version`` needs.

    Two coroutines: ``submit(deployment)`` returning something with ``decision``
    and ``instance_id``, and ``cancel(instance_id, reason=...)``. Wave 3 fills
    it in; the ordering invariant is owned here, so it must be testable without
    the approval module being wired up.
    """

    def __init__(self, *, decision=None, instance_id: int = 501, raises: Exception | None = None):
        from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision

        self.decision = decision or ApprovalGateDecision.PENDING
        self.instance_id = instance_id
        self.raises = raises
        self.submitted: list[str] = []
        self.cancelled: list[tuple[int, str]] = []

    async def submit(self, deployment, **_):
        from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateResult

        self.submitted.append(deployment.id)
        if self.raises is not None:
            raise self.raises
        return ApprovalGateResult(decision=self.decision, instance_id=self.instance_id)

    async def cancel(self, instance_id: int, *, reason: str = "") -> None:
        self.cancelled.append((instance_id, reason))


async def _service():
    from bisheng.app_publish.domain.services.version_service import VersionService

    return VersionService


async def _versions(publish_db, app_id: str):
    from bisheng.database.models.app_version import AppVersionDao

    async with publish_db() as session:
        return await AppVersionDao.alist_by_app(session, app_id)


# ---------------------------------------------------------------------------
# Write timing (AC-02 / AC-18)
# ---------------------------------------------------------------------------


async def test_version_row_only_created_after_precheck_and_scan_pass(
    publish_db, app_factory, deployment_factory, audit_sink
):
    """A failed attempt never reaches the version list — guarded here, not left to the caller (决议-9)."""
    from bisheng.app_publish.domain.models.app_deployment import STATUS_FAILED

    service = await _service()
    app_row, _ = await app_factory(with_version=False)
    failed = await deployment_factory(
        app_id=app_row.id, status=STATUS_FAILED, failure={"stage": "secret_scan", "code": 16241}
    )

    with pytest.raises(ValueError):
        await service.record_version(failed, approval=_FakeApproval())
    assert await _versions(publish_db, app_row.id) == []


async def test_version_row_created_after_gate_not_before(publish_db, app_factory, deployment_factory, audit_sink):
    """Ordering is observable: the gate is called, and only then does the row exist (design D6-B's defect)."""
    service = await _service()
    app_row, _ = await app_factory(with_version=False)
    deployment = await deployment_factory(app_id=app_row.id, version_id="ver-1")
    approval = _FakeApproval()

    version = await service.record_version(deployment, approval=approval)

    assert approval.submitted == [deployment.id]
    assert version.id == "ver-1", "the version id minted at receive time is reused (design D2)"
    rows = await _versions(publish_db, app_row.id)
    assert [row.id for row in rows] == ["ver-1"]
    assert rows[0].terminal_state is None


async def test_gate_exception_approver_empty_still_inserts_version(publish_db, app_factory, deployment_factory, audit_sink):
    """AC-18: no approver is an administrator's problem, not a reason to have nothing to publish."""
    from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision

    service = await _service()
    app_row, _ = await app_factory(with_version=False)
    deployment = await deployment_factory(app_id=app_row.id, version_id="ver-x")

    await service.record_version(deployment, approval=_FakeApproval(decision=ApprovalGateDecision.EXCEPTION))

    assert [row.id for row in await _versions(publish_db, app_row.id)] == ["ver-x"]
    assert "app.release.approval_exception" in {call["action"] for call in audit_sink}


async def test_gate_raises_scenario_disabled_marks_deployment_failed_16225_no_version(
    publish_db, app_factory, deployment_factory, audit_sink
):
    """16225 is only ever "the approval scenario is not enabled" — and it leaves no version behind."""
    from bisheng.app_publish.domain.models.app_deployment import STATUS_FAILED, AppDeploymentDao
    from bisheng.common.errcode.app_publish import AppApprovalScenarioDisabledError

    service = await _service()
    app_row, _ = await app_factory(with_version=False)
    deployment = await deployment_factory(app_id=app_row.id, version_id="ver-y")

    with pytest.raises(AppApprovalScenarioDisabledError):
        await service.record_version(
            deployment, approval=_FakeApproval(raises=AppApprovalScenarioDisabledError(msg="not seeded"))
        )

    assert await _versions(publish_db, app_row.id) == []
    async with publish_db() as session:
        stored = await AppDeploymentDao.aget(session, deployment.id)
    assert stored.status == STATUS_FAILED
    assert stored.failure["code"] == 16225
    assert set(stored.failure) == {"stage", "code", "message", "details", "hints"}


async def test_compensation_cancels_approval_when_insert_fails(
    publish_db, app_factory, deployment_factory, audit_sink, monkeypatch
):
    """Two explicit phases, not a pretend transaction: the gate committed, so it has to be undone (design D6)."""
    from bisheng.app_publish.domain.models.app_deployment import STATUS_FAILED, AppDeploymentDao
    from bisheng.database.models.app_version import AppVersionDao

    service = await _service()
    app_row, _ = await app_factory(with_version=False)
    deployment = await deployment_factory(app_id=app_row.id, version_id="ver-z")
    approval = _FakeApproval(instance_id=777)

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("insert blew up")

    monkeypatch.setattr(AppVersionDao, "ainsert", classmethod(_boom))

    with pytest.raises(RuntimeError):
        await service.record_version(deployment, approval=approval)

    assert [instance for instance, _ in approval.cancelled] == [777]
    assert await _versions(publish_db, app_row.id) == []
    async with publish_db() as session:
        stored = await AppDeploymentDao.aget(session, deployment.id)
    assert stored.status == STATUS_FAILED
    assert "app.release.rollback" in {call["action"] for call in audit_sink}


# ---------------------------------------------------------------------------
# Version numbering and kind (AC-39 / AC-40)
# ---------------------------------------------------------------------------


async def test_version_no_is_max_plus_one_with_unique_constraint(publish_db, app_factory, deployment_factory, audit_sink):
    from sqlalchemy.exc import IntegrityError

    from bisheng.database.models.app_version import AppVersion, AppVersionDao

    service = await _service()
    app_row, _ = await app_factory(with_version=False)
    first = await service.record_version(
        await deployment_factory(app_id=app_row.id, version_id="v-1"), approval=_FakeApproval()
    )
    second = await service.record_version(
        await deployment_factory(app_id=app_row.id, version_id="v-2"), approval=_FakeApproval()
    )
    assert (first.version_no, second.version_no) == (1, 2)

    # The unique constraint is the second gate behind AC-03's in-flight check.
    with pytest.raises(IntegrityError):
        async with publish_db() as session:
            await AppVersionDao.ainsert(
                session,
                AppVersion(
                    app_id=app_row.id,
                    version_no=2,
                    kind="iteration",
                    code_object_key="k",
                    tier_id="light",
                    runtime="python3.11",
                ),
            )
            await session.commit()


async def test_kind_initial_vs_iteration(publish_db, app_factory, deployment_factory, audit_sink):
    from bisheng.database.models.app_version import VERSION_KIND_INITIAL, VERSION_KIND_ITERATION

    service = await _service()
    app_row, _ = await app_factory(with_version=False)
    first = await service.record_version(
        await deployment_factory(app_id=app_row.id, version_id="v-1"), approval=_FakeApproval()
    )
    second = await service.record_version(
        await deployment_factory(app_id=app_row.id, version_id="v-2"), approval=_FakeApproval()
    )
    assert (first.kind, second.kind) == (VERSION_KIND_INITIAL, VERSION_KIND_ITERATION)


# ---------------------------------------------------------------------------
# Terminal state (AC-39 / AC-40)
# ---------------------------------------------------------------------------


async def test_terminal_state_only_four_values():
    """F055 does not get to add a process value to this column."""
    from bisheng.app_publish.domain.services.version_service import TERMINAL_STATES

    assert set(TERMINAL_STATES) == {"online", "rejected", "withdrawn"}, (
        "the fourth value is NULL (undecided) and is not a member"
    )


async def test_pending_online_is_derived_display_not_column(publish_db, app_factory):
    """待上线 / 待审 are computed at read time — the two status lines stay orthogonal (spec §3.0.2)."""
    service = await _service()
    app_row, version = await app_factory()

    assert service.derive_display_state(app_row, version) is None
    assert service.derive_display_state(app_row, version, has_active_approval=True) == "under_approval"

    app_row.pending_version_id = version.id
    assert service.derive_display_state(app_row, version) == "pending_online"

    version.terminal_state = "online"
    assert service.derive_display_state(app_row, version) == "online", "a decided version reports its decision"


async def test_manual_publish_flips_null_to_online_without_new_row(publish_db, app_factory):
    """决议-6: manual publish latches the existing row; it does not mint a version."""
    from bisheng.database.models.app_version import AppVersionDao

    service = await _service()
    app_row, version = await app_factory()

    assert await service.mark_terminal_state(app_row.id, version.id, "online") is True
    async with publish_db() as session:
        rows = await AppVersionDao.alist_by_app(session, app_row.id)
    assert len(rows) == 1 and rows[0].terminal_state == "online"

    # A second latch attempt loses: the decision already on the row wins.
    assert await service.mark_terminal_state(app_row.id, version.id, "rejected") is False


async def test_app_deleted_cancel_keeps_terminal_state_null(publish_db, app_factory):
    """Deleting the app hides the whole version list — no fifth terminal value is needed (design D6)."""
    service = await _service()
    app_row, version = await app_factory()
    with pytest.raises(ValueError):
        await service.mark_terminal_state(app_row.id, version.id, "cancelled")


async def test_mark_terminal_state_is_the_only_update_writer():
    """One writer for the one column that may be updated (F054 D8's single exception)."""
    from bisheng.database.models.app_version import AppVersionDao

    writers = [name for name in dir(AppVersionDao) if name.startswith("a") and name not in {"aget", "alist_by_app", "amax_version_no", "ainsert"}]
    assert writers == ["amark_terminal"], f"app_version gained another writer: {writers}"


async def test_version_row_never_deleted():
    from bisheng.app_publish.domain.services import version_service
    from bisheng.database.models.app_version import AppVersionDao

    assert [name for name in dir(AppVersionDao) if "delete" in name.lower()] == []
    assert [name for name in dir(version_service.VersionService) if "delete" in name.lower()] == []


async def test_read_by_version_id_requires_app_scope():
    """``app_version`` has no ``tenant_id``: the ``app_id`` argument *is* the isolation (design 坑 19)."""
    from bisheng.app_publish.domain.services.version_service import VersionService

    offenders = []
    for name, member in inspect.getmembers(VersionService, predicate=inspect.iscoroutinefunction):
        if name.startswith("_"):
            continue
        params = inspect.signature(member).parameters
        if "version_id" in params and "app_id" not in params:
            offenders.append(name)
    assert offenders == [], f"these take a version_id without an app_id scope: {offenders}"


async def test_snapshot_retrievable_and_immutable_for_any_version(publish_db, app_factory, fake_minio, tarball_factory):
    """AC-43 — the snapshot of any version comes back whole, through the version record's key."""
    from bisheng.app_publish.domain.services.package_service import store_package

    service = await _service()
    app_row, version = await app_factory()
    package = tarball_factory()
    key = await store_package(package, app_id=app_row.id, version_id=version.id)

    async with publish_db() as session:
        from bisheng.database.models.app_version import AppVersion

        stored = await session.get(AppVersion, version.id)
        stored.code_object_key = key
        session.add(stored)
        await session.commit()

    assert await service.get_snapshot(app_row.id, version.id) == package.read_bytes()
