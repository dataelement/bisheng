"""F056 T012 — ``app.visibility_change`` written from the F048 grant hook.

Two of these tests exist because the naive implementation passes every other
test and still produces a useless audit trail:

* ``test_removed_carries_subject_identity`` — a REMOVE request carries only
  ``assignee_id`` and a version, and the mutation result drops the revoked
  source row entirely rather than marking it inactive. Reconstructing "who lost
  access" afterwards is impossible; ADD-only scenarios never notice.
* ``test_idempotent_replay_writes_nothing`` — ``mutate_grants`` is idempotent,
  so a retried request returns success without changing anything. An unchecked
  hook turns one network retry into a second "visibility changed" record.

The permission stack is faked rather than started: OpenFGA is not reachable in a
unit run, and what is under test is the hook's contract with ``mutate_grants``,
not F048's decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import PermissionActor

from .conftest import ROOT_TENANT_ID, TENANT_ADMIN_USER_ID

CATALOG_RELEASE_ID = 7


@dataclass
class _RosterRow:
    source_id: int
    subject_type: str
    subject_id: str


class _FakeRuntime:
    """Just enough of ``F048PermissionRuntime`` for ``mutate_grants`` to run."""

    def __init__(self, roster: list[_RosterRow], *, idempotent: bool = False, roster_has_more: bool = False):
        self.roster = roster
        self.idempotent = idempotent
        self.roster_has_more = roster_has_more
        self.roster_reads = 0
        self.mutations: list[tuple] = []

    async def list_permission_sources_page(self, *, actor, target, after_id, limit):
        self.roster_reads += 1
        return tuple(self.roster), self.roster_has_more

    async def allocate_source_ids(self, count):
        return tuple(range(9000, 9000 + count))

    async def mutate_grants(self, *, actor, target, changes, **kwargs):
        self.mutations.append(changes)
        return SimpleNamespace(
            grants=(),
            resource_version=target.resource_version + 1,
            projection=SimpleNamespace(idempotent=self.idempotent),
        )


class _FakeSubjects:
    async def canonical_source(self, *, tenant_id, source_id, subject_type, subject_id, **kwargs):
        return SimpleNamespace(
            source_id=source_id,
            subject_type=subject_type,
            subject_id=subject_id,
            protected=False,
            include_children=False,
            source_type="DIRECT",
            version=1,
            active=True,
        )


class _FakeResources:
    def __init__(self, target: VerifiedPermissionTarget, denied: bool = False):
        self.target = target
        self.denied = denied

    async def resolve(self, *, resource_type, resource_id, actor, action):
        if self.denied:
            from bisheng.common.errcode.permission import PermissionDeniedError

            raise PermissionDeniedError()
        return self.target


def _target(app_id: str) -> VerifiedPermissionTarget:
    # Only the owning business Service may mint one of these — the factory is
    # the sanctioned door, and hand-validating the dict is refused by design.
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=ROOT_TENANT_ID,
        resource_type="app",
        resource_id=app_id,
        resource_version=3,
        context_version="v1",
    )


def _request(changes: list[dict], key: str = "idem-1"):
    from bisheng.permission.domain.schemas import GrantMutationRequest

    return GrantMutationRequest.model_validate(
        {
            "idempotency_key": key,
            "expected_resource_version": 3,
            "expected_catalog_release_id": CATALOG_RELEASE_ID,
            "changes": changes,
        }
    )


def _api(runtime, target, *, denied: bool = False, register_app: bool = True):
    from bisheng.app_runtime.domain.services.visibility_audit import HostedAppVisibilityAuditListener
    from bisheng.permission.application.resource_api import (
        F048ResourcePermissionApi,
        GrantChangeListenerRegistry,
    )

    listeners = GrantChangeListenerRegistry()
    if register_app:
        listeners.register("app", HostedAppVisibilityAuditListener())
    return F048ResourcePermissionApi(
        resources=_FakeResources(target, denied=denied),
        runtime=runtime,
        subjects=_FakeSubjects(),
        grant_listeners=listeners,
    )


def _actor(user_id: int = TENANT_ADMIN_USER_ID) -> PermissionActor:
    return PermissionActor(user_id=user_id, current_tenant_id=ROOT_TENANT_ID)


async def _mutate(api, app_id, request, actor=None):
    return await api.mutate_grants(
        resource_type="app",
        resource_id=app_id,
        actor=actor or _actor(),
        request=request,
    )


# ---------------------------------------------------------------------------


def test_callback_registered_for_app():
    """The composition root, not an import side effect, installs the hook.

    A missing registration is a no-op with no error anywhere — the audit page is
    simply empty forever — which is why this is asserted against the real
    builder rather than a hand-made registry.
    """
    import inspect

    from bisheng.api.services import f048_permission_runtime

    source = inspect.getsource(f048_permission_runtime.initialize_f048_api_runtime)
    assert 'grant_listeners.register("app", HostedAppVisibilityAuditListener())' in source
    assert "grant_listeners=grant_listeners" in source


async def test_audit_written_once_on_grant(app_db, app_factory, audit_sink):
    app, _ = await app_factory(name="Reporting", slug="reporting")
    runtime = _FakeRuntime(roster=[])

    await _mutate(
        _api(runtime, _target(app.id)),
        app.id,
        _request([{"op": "ADD", "model_key": "viewer", "subject": {"type": "user_group", "id": "42"}}]),
    )

    assert len(audit_sink) == 1
    entry = audit_sink[0]
    assert entry["action"] == "app.visibility_change"
    assert entry["target_type"] == "app"
    assert entry["target_id"] == app.id
    assert entry["object_name"] == "Reporting"
    assert entry["operator_id"] == TENANT_ADMIN_USER_ID
    assert entry["metadata"]["app_slug"] == "reporting"
    assert entry["metadata"]["added"] == [{"type": "user_group", "id": "42"}]
    assert entry["metadata"]["removed"] == []
    assert entry["metadata"]["model_keys"] == ["viewer"]


async def test_idempotent_replay_writes_nothing(app_db, app_factory, audit_sink):
    app, _ = await app_factory()
    runtime = _FakeRuntime(roster=[], idempotent=True)

    await _mutate(
        _api(runtime, _target(app.id)),
        app.id,
        _request([{"op": "ADD", "model_key": "viewer", "subject": {"type": "user", "id": "9"}}]),
    )

    assert audit_sink == []


async def test_removed_carries_subject_identity(app_db, app_factory, audit_sink):
    """``removed`` names the subject, not the opaque row id."""
    app, _ = await app_factory()
    runtime = _FakeRuntime(roster=[_RosterRow(source_id=8143, subject_type="user_group", subject_id="42")])

    await _mutate(
        _api(runtime, _target(app.id)),
        app.id,
        _request([{"op": "REMOVE", "assignee_id": "8143", "expected_assignee_version": 1}]),
    )

    assert audit_sink[0]["metadata"]["removed"] == [{"type": "user_group", "id": "42"}]
    assert "roster_truncated" not in audit_sink[0]["metadata"]


async def test_removed_marks_truncated_roster(app_db, app_factory, audit_sink):
    """Beyond one roster page the record says it is incomplete instead of guessing."""
    app, _ = await app_factory()
    runtime = _FakeRuntime(roster=[], roster_has_more=True)

    await _mutate(
        _api(runtime, _target(app.id)),
        app.id,
        _request([{"op": "REMOVE", "assignee_id": "8143", "expected_assignee_version": 1}]),
    )

    metadata = audit_sink[0]["metadata"]
    assert metadata["removed"] == [{"assignee_id": "8143"}]
    assert metadata["roster_truncated"] is True


async def test_pure_add_does_not_preread_roster(app_db, app_factory, audit_sink):
    """The extra read is paid only by revocations, not by the common case."""
    app, _ = await app_factory()
    runtime = _FakeRuntime(roster=[])

    await _mutate(
        _api(runtime, _target(app.id)),
        app.id,
        _request([{"op": "ADD", "model_key": "viewer", "subject": {"type": "user", "id": "9"}}]),
    )

    assert runtime.roster_reads == 0


async def test_no_listener_no_preread(app_db, app_factory, audit_sink):
    """Resource types without a listener behave exactly as before F056."""
    app, _ = await app_factory()
    runtime = _FakeRuntime(roster=[_RosterRow(source_id=1, subject_type="user", subject_id="9")])

    await _mutate(
        _api(runtime, _target(app.id), register_app=False),
        app.id,
        _request([{"op": "REMOVE", "assignee_id": "1", "expected_assignee_version": 1}]),
    )

    assert runtime.roster_reads == 0
    assert audit_sink == []


async def test_tenant_admin_operator_is_self(app_db, app_factory, audit_sink):
    """A tenant administrator acting for the owner is recorded as themselves."""
    app, _ = await app_factory(owner_user_id=98765)
    runtime = _FakeRuntime(roster=[])

    await _mutate(
        _api(runtime, _target(app.id)),
        app.id,
        _request([{"op": "ADD", "model_key": "viewer", "subject": {"type": "user", "id": "9"}}]),
        actor=_actor(TENANT_ADMIN_USER_ID),
    )

    assert audit_sink[0]["operator_id"] == TENANT_ADMIN_USER_ID
    assert audit_sink[0]["operator_id"] != app.owner_user_id


async def test_non_owner_denied(app_db, app_factory, audit_sink):
    """The backend gate is ``manage_permission`` on ``_target`` — and it runs first."""
    from bisheng.common.errcode.permission import PermissionDeniedError

    app, _ = await app_factory()
    runtime = _FakeRuntime(roster=[])

    with pytest.raises(PermissionDeniedError):
        await _mutate(
            _api(runtime, _target(app.id), denied=True),
            app.id,
            _request([{"op": "ADD", "model_key": "viewer", "subject": {"type": "user", "id": "9"}}]),
        )

    assert runtime.mutations == []
    assert audit_sink == []


async def test_audit_failure_does_not_rollback_grant(app_db, app_factory, monkeypatch):
    """A dead audit insert must not report a failure for a mutation that succeeded."""
    from bisheng.database.models.audit_log import AuditLogDao

    app, _ = await app_factory()
    runtime = _FakeRuntime(roster=[])

    async def _boom(*args, **kwargs):
        raise RuntimeError("audit table unavailable")

    monkeypatch.setattr(AuditLogDao, "ainsert_v2", classmethod(lambda cls, *a, **kw: _boom()))

    result = await _mutate(
        _api(runtime, _target(app.id)),
        app.id,
        _request([{"op": "ADD", "model_key": "viewer", "subject": {"type": "user", "id": "9"}}]),
    )

    assert result["resource_version"] == 4
    assert len(runtime.mutations) == 1


async def test_move_records_subject_and_model(app_db, app_factory, audit_sink):
    """A model change is a visibility change; its subject is equally unrecoverable."""
    app, _ = await app_factory()
    runtime = _FakeRuntime(roster=[_RosterRow(source_id=55, subject_type="department", subject_id="d-1")])

    await _mutate(
        _api(runtime, _target(app.id)),
        app.id,
        _request(
            [
                {
                    "op": "MOVE",
                    "assignee_id": "55",
                    "expected_assignee_version": 2,
                    "target_model_key": "editor",
                }
            ]
        ),
    )

    metadata = audit_sink[0]["metadata"]
    assert metadata["moved"] == [{"type": "department", "id": "d-1", "model_key": "editor"}]
    assert metadata["model_keys"] == ["editor"]


def test_registry_rejects_duplicate_registration():
    """Registering twice is a wiring bug, not a last-one-wins."""
    from bisheng.permission.application.resource_api import GrantChangeListenerRegistry

    registry = GrantChangeListenerRegistry()
    registry.register("app", object())
    with pytest.raises(ValueError):
        registry.register("APP", object())
    assert registry.registered_types() == frozenset({"app"})
