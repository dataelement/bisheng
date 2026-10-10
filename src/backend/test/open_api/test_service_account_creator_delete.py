"""A service account may delete the resources it created, and nothing more.

The decision port is stubbed to deny (the OpenFGA answer for a level-3
"manager" grant asked for level-4 delete). The SQL roster stub holds the
grants that ``authorize_created`` writes for a service-account creation.
"""

from types import SimpleNamespace

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.permission.application.control_state import RuntimeCatalogSnapshot, RuntimeModelSnapshot
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceRecord,
    GrantSourceService,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.permission.domain.services.permission_explain_service import InheritedGrantSet

TENANT = 4
CREATOR_SA = 7
OTHER_SA = 8
OWNER_USER = 22
LIBRARY_ID = "91"
FILE_ID = "501"

MANAGER = GrantModelSnapshot("manager", True, ("use", "edit", "manage_permission"), 3, False)
VIEWER = GrantModelSnapshot("viewer", True, ("use",), 1, False)


def _source(subject_type="service_account", subject_id=CREATOR_SA, *, source_type="CREATOR_GRANT", active=True):
    return GrantSourceRecord(
        source_id=1,
        subject_type=subject_type,
        subject_id=str(subject_id),
        userset_relation=None,
        include_children=False,
        source_type=source_type,
        source_ref=f"knowledge_library:{LIBRARY_ID}",
        source_locator="locator",
        source_fingerprint="fingerprint",
        projected_subject=f"{subject_type}:{subject_id}",
        protected=False,
        active=active,
    )


def _grant(model=MANAGER, sources=None, *, resource_id=LIBRARY_ID, active=True):
    sources = (_source(),) if sources is None else sources
    return GrantSnapshot(
        grant_id=f"grant-{model.model_key}",
        tenant_id=TENANT,
        resource_type="knowledge_library",
        resource_id=resource_id,
        model=model,
        active=active and bool(sources),
        sources=sources,
    )


class State:
    """SQL roster stub: library 91 is CUSTOM; file 501 inherits from it."""

    def __init__(self, library_grants, *, file_mode="INHERIT", file_grants=()):
        self.library_grants = tuple(library_grants)
        self.file_mode = file_mode
        self.file_grants = tuple(file_grants)
        self.reads = 0

    async def current_catalog(self):
        models = tuple(
            RuntimeModelSnapshot(snapshot=model, name=model.model_key, kind="STANDARD", version=1)
            for model in (MANAGER, VIEWER)
        )
        return RuntimeCatalogSnapshot(
            release_id=1,
            release_key="current",
            version=1,
            checksum="catalog",
            store_id="store",
            model_id="model",
            model_checksum="checksum",
            models=models,
        )

    async def mode_for_target(self, target):
        self.reads += 1
        if target.resource_type == "knowledge_library":
            return SimpleNamespace(
                mode="CUSTOM", version=0, parent_type=None, parent_id=None, projection_state="CURRENT"
            )
        return SimpleNamespace(
            mode=self.file_mode,
            version=0,
            parent_type="knowledge_library",
            parent_id=LIBRARY_ID,
            projection_state="CURRENT",
        )

    async def load_grants(self, *, target, models):
        keys = {model.model_key for model in models}
        grants = self.library_grants if target.resource_type == "knowledge_library" else self.file_grants
        return tuple(grant for grant in grants if grant.model.model_key in keys)

    async def inherited_grant_set(self, *, target, models):
        keys = {model.model_key for model in models}
        return InheritedGrantSet(
            resource_type="knowledge_library",
            resource_id=LIBRARY_ID,
            grants=tuple(grant for grant in self.library_grants if grant.model.model_key in keys),
        )


class DenyDecision:
    """OpenFGA answer for a manager grant: no level-4 delete."""

    def __init__(self, allow_actions=()):
        self.allow_actions = set(allow_actions)

    async def check_action(self, actor, target, action):
        return action in self.allow_actions

    async def batch_check_actions(self, actor, targets, action):
        return tuple(action in self.allow_actions for _ in targets)


def _runtime(state, decision=None) -> F048PermissionRuntime:
    return F048PermissionRuntime(
        client=SimpleNamespace(store_id="store", model_id="model"),
        state=state,
        marker=SimpleNamespace(),
        decision=decision or DenyDecision(),
        projection=SimpleNamespace(),
        sources=GrantSourceService(),
        owner=SimpleNamespace(),
        grants=SimpleNamespace(),
        modes=SimpleNamespace(),
        explain=SimpleNamespace(),
    )


def _library():
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=TENANT,
        resource_type="knowledge_library",
        resource_id=LIBRARY_ID,
        resource_version=0,
        context_version="0:CURRENT",
    )


def _file():
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=TENANT,
        resource_type="knowledge_file",
        resource_id=FILE_ID,
        resource_version=0,
        context_version="0:CURRENT",
        parent_type="knowledge_library",
        parent_id=LIBRARY_ID,
    )


def _sa(subject_id=CREATOR_SA, tenant_id=TENANT):
    return PermissionActor(subject_type="service_account", subject_id=subject_id, tenant_id=tenant_id)


async def test_creator_service_account_can_delete_its_library():
    runtime = _runtime(State([_grant()]))
    assert await runtime.check_action(_sa(), _library(), "delete") is True


async def test_creator_service_account_can_delete_files_of_its_library():
    runtime = _runtime(State([_grant()]))
    assert await runtime.check_action(_sa(), _file(), "delete") is True
    # The file delete endpoint uses the batch path.
    assert await runtime.batch_check_actions(_sa(), (_file(), _file()), "delete") == (True, True)


async def test_other_service_account_cannot_delete():
    runtime = _runtime(State([_grant()]))
    assert await runtime.check_action(_sa(OTHER_SA), _library(), "delete") is False
    assert await runtime.batch_check_actions(_sa(OTHER_SA), (_file(),), "delete") == (False,)


async def test_service_account_cannot_delete_a_library_it_did_not_create():
    # A manager grant from an ordinary DIRECT share is not a creator grant.
    shared = _grant(sources=(_source(source_type="DIRECT"),))
    runtime = _runtime(State([shared]))
    assert await runtime.check_action(_sa(), _library(), "delete") is False


async def test_revoked_creator_grant_no_longer_allows_delete():
    # Revocation leaves no active source, so the grant itself is inactive.
    runtime = _runtime(State([_grant(sources=())]))
    assert await runtime.check_action(_sa(), _library(), "delete") is False
    assert await runtime.check_action(_sa(), _file(), "delete") is False
    inactive = _grant(sources=(_source(active=False),))
    runtime = _runtime(State([inactive]))
    assert await runtime.check_action(_sa(), _library(), "delete") is False


async def test_creator_grant_moved_to_another_model_does_not_allow_delete():
    runtime = _runtime(State([_grant(model=VIEWER)]))
    assert await runtime.check_action(_sa(), _library(), "delete") is False


async def test_custom_file_detached_from_the_library_is_not_covered():
    # The file stopped inheriting and has no creator grant of its own.
    runtime = _runtime(State([_grant()], file_mode="CUSTOM", file_grants=()))
    assert await runtime.check_action(_sa(), _file(), "delete") is False


async def test_only_delete_is_added():
    runtime = _runtime(State([_grant()]))
    for action in ("manage_permission", "edit", "use"):
        assert await runtime.check_action(_sa(), _library(), action) is False
    assert await runtime.batch_check_actions(_sa(), (_library(),), "edit") == (False,)


async def test_user_subjects_never_take_the_exception():
    # Delegated (D mode) calls and PATs authorize as a user subject.
    state = State([_grant(sources=(_source(subject_type="user", subject_id=CREATOR_SA),))])
    runtime = _runtime(state)
    user = PermissionActor(subject_type="user", subject_id=CREATOR_SA, tenant_id=TENANT)
    assert await runtime.check_action(user, _library(), "delete") is False
    assert await runtime.batch_check_actions(user, (_file(),), "delete") == (False,)
    assert state.reads == 0


async def test_other_tenant_target_is_denied_without_reading_the_roster():
    state = State([_grant()])
    runtime = _runtime(state)
    assert await runtime.check_action(_sa(tenant_id=TENANT + 1), _library(), "delete") is False
    assert state.reads == 0


async def test_stale_projection_denies():
    class StaleState(State):
        async def mode_for_target(self, target):
            raise PermissionPublishNotReadyError(msg="missing")

    runtime = _runtime(StaleState([_grant()]))
    assert await runtime.check_action(_sa(), _library(), "delete") is False


async def test_openfga_allow_is_kept():
    runtime = _runtime(State([]), DenyDecision(allow_actions={"delete"}))
    assert await runtime.check_action(_sa(OTHER_SA), _library(), "delete") is True
