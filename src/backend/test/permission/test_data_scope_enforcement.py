"""F066: the data-scope narrowing wins over every identity shortcut.

覆盖 AC: AC-P23, AC-P24, AC-P26
"""

from __future__ import annotations

import pytest

import bisheng.permission.domain.services.data_scope as data_scope_module
from bisheng.common.errcode.open_api import PersonalTokenDataScopeError
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.data_scope import DATA_SCOPE_PERSONAL
from bisheng.permission.domain.services.permission_action_service import (
    F048PermissionService,
    PermissionActor,
)


class StubCatalog:
    async def ensure_runtime_ready(self):
        return None

    async def is_action_effective(self, resource_type, action):
        return True

    async def effective_actions(self, resource_type):
        return ("use",)


class StubFence:
    async def ensure_readable(self, target):
        return False

    async def ensure_readable_batch(self, targets):
        return [False] * len(targets)


class StubMarker:
    async def consistency_for(self, *, tenant_id, resource_type, resource_id):
        return None


class StubFGA:
    def __init__(self, *, allow=True, objects=()):
        self.calls: list[tuple] = []
        self.allow = allow
        self.objects = list(objects)

    async def check(self, **kwargs):
        self.calls.append(("check", kwargs))
        return self.allow

    async def batch_check(self, checks, consistency=None):
        self.calls.append(("batch", checks))
        return [self.allow] * len(checks)

    async def list_objects(self, **kwargs):
        self.calls.append(("list", kwargs))
        return self.objects

    async def stream_list_objects(self, **kwargs):
        self.calls.append(("stream", kwargs))
        return self.objects


class StubListPolicy:
    async def allows(self, *args, **kwargs):
        return True


class FakeResolver:
    def __init__(self, owned: dict[str, set[str]]):
        self.owned = owned

    def governed_resource_types(self) -> frozenset[str]:
        return frozenset({"knowledge_library", "knowledge_space", "knowledge_file"})

    async def filter_owned(self, *, holder_user_id, tenant_id, resource_type, resource_ids):
        return frozenset(rid for rid in resource_ids if rid in self.owned.get(resource_type, set()))

    async def owned_ids(self, *, holder_user_id, tenant_id, resource_type):
        return frozenset(self.owned.get(resource_type, set()))


def service(fga: StubFGA) -> F048PermissionService:
    return F048PermissionService(
        catalog=StubCatalog(),
        scope_fence=StubFence(),
        marker=StubMarker(),
        fga=fga,
        list_policy=StubListPolicy(),
    )


def target(rid: str = "7", rtype: str = "knowledge_library") -> VerifiedPermissionTarget:
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=1,
        resource_type=rtype,
        resource_id=rid,
        resource_version=0,
        context_version="ctx",
    )


def narrowed_super_admin() -> PermissionActor:
    """The strongest identity there is — the narrowing must still win."""

    return PermissionActor(
        subject_type="user",
        subject_id=5,
        tenant_id=1,
        super_admin=True,
        data_scope=DATA_SCOPE_PERSONAL,
    )


@pytest.fixture
def resolver(monkeypatch):
    fake = FakeResolver({"knowledge_library": {"7"}, "knowledge_space": {"20"}})
    monkeypatch.setattr(data_scope_module, "_resolver", fake)
    return fake


@pytest.fixture
def no_resolver(monkeypatch):
    monkeypatch.setattr(data_scope_module, "_resolver", None)


async def test_check_action_denies_before_super_admin_shortcut_and_fga(resolver):
    fga = StubFGA()

    with pytest.raises(PersonalTokenDataScopeError):
        await service(fga).check_action(narrowed_super_admin(), target("8"), "use")

    assert fga.calls == []  # never reached OpenFGA — denial precedes everything


async def test_check_action_owned_resource_still_passes_shortcut(resolver):
    fga = StubFGA()

    allowed = await service(fga).check_action(narrowed_super_admin(), target("7"), "use")

    assert allowed is True
    assert fga.calls == []  # super-admin shortcut, reached only because owned


async def test_check_visible_denies_before_fga(resolver):
    fga = StubFGA()

    with pytest.raises(PersonalTokenDataScopeError):
        await service(fga).check_visible(narrowed_super_admin(), target("8"))

    assert fga.calls == []


async def test_batch_checks_narrow_silently_instead_of_raising(resolver):
    fga = StubFGA()
    svc = service(fga)
    targets = (target("7"), target("8"), target("9"))

    actions = await svc.batch_check_actions(narrowed_super_admin(), targets, "use")
    visible = await svc.batch_check_visible(narrowed_super_admin(), targets)

    assert actions == (True, False, False)
    assert visible == (True, False, False)


async def test_list_visible_objects_intersects_with_owned_ids(resolver):
    fga = StubFGA(objects=["knowledge_space:10", "knowledge_space:20", "knowledge_space:30"])

    result = await service(fga).list_visible_objects(
        narrowed_super_admin(),
        resource_type="knowledge_space",
        max_results=100,
    )

    assert result.object_ids == ("20",)


async def test_unregistered_resolver_fails_closed(no_resolver):
    fga = StubFGA(objects=["knowledge_library:7"])
    svc = service(fga)

    with pytest.raises(PersonalTokenDataScopeError):
        await svc.check_action(narrowed_super_admin(), target("7"), "use")
    result = await svc.list_visible_objects(
        narrowed_super_admin(),
        resource_type="knowledge_library",
        max_results=100,
    )
    assert result.object_ids == ()


async def test_ungoverned_resource_type_is_untouched(resolver):
    fga = StubFGA()

    allowed = await service(fga).check_action(narrowed_super_admin(), target("3", rtype="workflow"), "use")

    assert allowed is True  # super-admin shortcut as before — narrowing is knowledge-domain only


async def test_default_scope_changes_nothing(no_resolver):
    """AC-P23: with the wide default nothing consults the resolver at all."""

    fga = StubFGA()
    actor = PermissionActor(subject_type="user", subject_id=5, tenant_id=1)

    allowed = await service(fga).check_action(actor, target("8"), "use")

    assert allowed is True  # decided by the stubbed OpenFGA, not by the narrowing
    assert [name for name, _ in fga.calls] == ["check"]


# ── F066 e2e regression: the application-layer super-admin shortcut ──────────
# Caught live on 105: check_business_action returned True for a narrowed super
# admin before the runtime (and its data-scope denial) was ever reached.


class StubRegistry:
    def __init__(self):
        self.calls = 0

    async def resolve(self, *, resource_type, resource_id, actor, action):
        self.calls += 1
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=1,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_version=0,
            context_version="ctx",
        )


def _wire_business_layer(monkeypatch, runtime):
    import bisheng.permission.application.business_authorization as ba

    registry = StubRegistry()

    async def get_registry():
        return registry

    async def get_runtime():
        return runtime

    monkeypatch.setattr(ba, "get_f048_resource_registry", get_registry)
    monkeypatch.setattr(ba, "get_f048_runtime", get_runtime)
    return ba, registry


async def test_business_action_shortcut_yields_to_narrowed_scope(resolver, monkeypatch):
    from types import SimpleNamespace

    from bisheng.permission.application.identity import (
        reset_current_permission_actor,
        set_current_permission_actor,
    )

    ba, registry = _wire_business_layer(monkeypatch, service(StubFGA()))
    login = SimpleNamespace(user_id=5, tenant_id=1, is_global_super=True)
    token = set_current_permission_actor(narrowed_super_admin())
    try:
        with pytest.raises(PersonalTokenDataScopeError):
            await ba.check_business_action(
                login, resource_type="knowledge_library", resource_id="8", action="use"
            )
        allowed = await ba.check_business_action(
            login, resource_type="knowledge_library", resource_id="7", action="use"
        )
        assert allowed is True  # owned: reaches the runtime, then the shortcut
        batch = await ba.batch_check_business_actions(
            login,
            resource_type="knowledge_library",
            resource_ids=["7", "8"],
            actions=["use"],
        )
        assert batch == {"7": frozenset({"use"}), "8": frozenset()}
        assert registry.calls > 0  # the foregone-conclusion path was NOT taken
    finally:
        reset_current_permission_actor(token)


async def test_business_action_shortcut_intact_for_wide_scope(monkeypatch, no_resolver):
    from types import SimpleNamespace

    from bisheng.permission.application.identity import (
        reset_current_permission_actor,
        set_current_permission_actor,
    )

    ba, registry = _wire_business_layer(monkeypatch, service(StubFGA()))
    login = SimpleNamespace(user_id=5, tenant_id=1, is_global_super=True)
    wide_super = PermissionActor(subject_type="user", subject_id=5, tenant_id=1, super_admin=True)
    token = set_current_permission_actor(wide_super)
    try:
        allowed = await ba.check_business_action(
            login, resource_type="knowledge_library", resource_id="8", action="use"
        )
        batch = await ba.batch_check_business_actions(
            login,
            resource_type="knowledge_library",
            resource_ids=["8"],
            actions=["use"],
        )
    finally:
        reset_current_permission_actor(token)
    assert allowed is True
    assert batch == {"8": frozenset({"use"})}
    assert registry.calls == 0  # untouched default-scope behaviour (AC-P23)
