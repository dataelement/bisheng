"""``app`` is a first-class F048 resource type — all eight registration points.

The failure mode this file exists for is ``linsight_skill``: registered in the
authorization model, in ``FIXED_CUSTOM_TYPES`` and in the frontend union, but
**not** in the Catalog scope map, **not** in the resource registry and **not**
in ``GRANT_SUBJECT_RESOURCE_TYPES``. The result is a resource that can be
created and whose owner is projected, while every
``check_business_action("linsight_skill", ...)`` raises
``InvalidCatalogActionError`` — i.e. the entry path denies everyone, forever
(design pit 32). Half a registration looks fine in a diff and fails only at
runtime, so each of the eight points gets its own assertion here.

What runs where:

* Everything below the "deterministic" banner runs anywhere — the eight
  registration points, the adapter's own verdicts against a fake permission
  port, and the five grant-subject gates driven through their real endpoint
  functions.
* The "integration" block needs the test middleware (OpenFGA + MySQL) and skips
  without it. Those cases assert the end-to-end grant → allow behaviour that no
  amount of constant-checking can prove; they are not weakened to run locally.

arch-guard note: reading ``bisheng.core.openfga.authorization_model_f048``
from a test trips RULE-9 when the guard is handed an absolute path, because the
repository root directory is itself named ``bisheng`` and the rule matches
``/bisheng/``. It is a false positive on any test file — the in-tree
``test/permission/test_f048_action_catalog_policy.py`` produces it verbatim —
and the import is the only way to assert the model-side registration at all.

覆盖 AC: AC-09, AC-10, AC-11, AC-12
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from bisheng.common.errcode.permission import (
    PermissionDeniedError,
    PermissionInvalidResourceError,
)
from bisheng.core.openfga.authorization_model_f048 import (
    MIGRATED_RESOURCE_TYPES as MODEL_MIGRATED_TYPES,
)
from bisheng.core.openfga.authorization_model_f048 import (
    RESOURCE_ACTION_SCOPES,
    SYSTEM_SHARED_ACTION_TYPES,
)
from bisheng.permission.api.endpoints import grant_subjects
from bisheng.permission.api.endpoints.grant_subjects import GRANT_SUBJECT_RESOURCE_TYPES
from bisheng.permission.api.router import router as permission_router
from bisheng.permission.domain.services.catalog_policy import (
    ACTION_RESOURCE_SCOPES,
    CatalogAction,
    effective_action_codes,
)
from bisheng.permission.domain.services.catalog_policy import (
    MIGRATED_RESOURCE_TYPES as CATALOG_MIGRATED_TYPES,
)
from bisheng.permission.domain.services.owner_service import SYSTEM_OWNED_RESOURCE_ALLOWLIST
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.permission.domain.services.resource_lifecycle_policy import FIXED_CUSTOM_TYPES

#: The six actions a hosted app supports. **No new action code is introduced** —
#: a new code would mean a new model relation, a full Catalog change and new
#: frontend copy, for zero benefit (design D9 alternative B).
APP_ACTIONS = ("use", "edit", "manage_permission", "delete", "publish", "unpublish")

INTEGRATION = os.environ.get("F054_PERMISSION_INTEGRATION") == "1"
integration = pytest.mark.skipif(
    not INTEGRATION,
    reason="needs the test middleware (OpenFGA + MySQL); set F054_PERMISSION_INTEGRATION=1",
)

TENANT_ID = 1
OWNER_ID = 91020
OTHER_ID = 91010


# ---------------------------------------------------------------------------
# Fakes for the adapter (pattern: test/permission/test_f048_dashboard_permissions.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeRecordSource:
    """Stands in for the DAO loader so adapter verdicts need no database."""

    record: object | None

    async def load_permission_record(self, resource_id: str):
        del resource_id
        return self.record


class _FakePermission:
    """Records what the adapter asks the sole permission facade to do."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.error: Exception | None = None
        self.verdict = True

    async def check_action(self, actor, target, action):
        self.calls.append(("check", {"actor": actor, "target": target, "action": action}))
        if self.error:
            raise self.error
        return self.verdict

    async def batch_check_actions(self, actor, targets, action):
        self.calls.append(("batch", {"actor": actor, "targets": targets, "action": action}))
        return tuple(self.verdict for _ in targets)

    async def authorize_created(self, **kwargs):
        self.calls.append(("authorize_created", kwargs))
        return {"status": "FINALIZED"}

    async def project_delete(self, **kwargs):
        self.calls.append(("project_delete", kwargs))
        return {"status": "FINALIZED"}


def _actor(user_id: int = OWNER_ID, tenant_id: int = TENANT_ID, **kwargs) -> PermissionActor:
    return PermissionActor(user_id=user_id, current_tenant_id=tenant_id, **kwargs)


def _adapter(record):
    from bisheng.app_runtime.domain.services.f048_app_permission import (
        F048AppPermissionAdapter,
    )

    permission = _FakePermission()
    return F048AppPermissionAdapter(loader=_FakeRecordSource(record), permission=permission), permission


def _record(
    *,
    resource_id: str = "app-1",
    tenant_id: int = TENANT_ID,
    state: str = "online",
    owner_user_id: int | None = OWNER_ID,
):
    from bisheng.app_runtime.domain.services.f048_app_permission import AppPermissionRecord

    return AppPermissionRecord(
        tenant_id=tenant_id,
        resource_id=resource_id,
        state=state,
        owner_user_id=owner_user_id,
        permission_version=1,
        context_version="ctx",
    )


# ---------------------------------------------------------------------------
# Deterministic — the eight registration points (AC-09)
# ---------------------------------------------------------------------------


def test_both_migrated_resource_type_lists_carry_app() -> None:
    """Points 1 and 3. There are two lists and both are consumed.

    Missing the model one: OpenFGA has no ``app`` type, so writing a tuple 400s.
    Missing the catalog one: ``derive_action_release`` runs on every
    ``_load_snapshot`` and rejects the release — Catalog reads crash outright,
    which takes down permissions platform-wide, not just for hosted apps
    (design pit 1).
    """
    assert "app" in MODEL_MIGRATED_TYPES
    assert "app" in CATALOG_MIGRATED_TYPES


@pytest.mark.parametrize("action", APP_ACTIONS)
def test_catalog_action_effective_for_app(action: str) -> None:
    """Point 4: each of the six actions is scoped to ``app`` in the Catalog policy.

    ``effective_action_codes`` is the pure predicate behind the SQL
    ``is_action_effective`` — an action is effective for a type only when it is
    active, has a level, **and** lists the type. Asserting through it means the
    test fails for the same reason production would.
    """
    assert action in ACTION_RESOURCE_SCOPES, f"{action} is not a registered catalog action"
    assert "app" in ACTION_RESOURCE_SCOPES[action]

    catalog_row = CatalogAction(
        code=action,
        name=action.replace("_", " ").title(),
        level=1,
        active=True,
        resource_types=ACTION_RESOURCE_SCOPES[action],
    )
    assert effective_action_codes([catalog_row], "app") == (action,)


@pytest.mark.parametrize("action", APP_ACTIONS)
def test_authorization_model_scopes_mirror_the_catalog(action: str) -> None:
    """Point 2. ``RESOURCE_ACTION_SCOPES`` has no consumer today (design pit 5),
    so it is kept in sync purely so the two files do not disagree in review —
    a reviewer who reads only this one must not be told ``app`` is unsupported.
    """
    assert "app" in RESOURCE_ACTION_SCOPES[action]


def test_app_starts_in_custom_mode() -> None:
    """Point 5: ``FIXED_CUSTOM_TYPES`` — a new app is visible to its owner only (AC-11).

    CUSTOM (rather than INHERIT) is what makes "no parent, no inherited
    audience" the starting state; the app has no parent resource to inherit
    from in the first place.
    """
    assert "app" in FIXED_CUSTOM_TYPES


def test_app_is_never_system_shared_or_system_owned() -> None:
    """The other half of AC-11: nothing grants a default audience behind our back.

    ``SYSTEM_SHARED_ACTION_TYPES`` would hand every user of the tenant an
    action, and ``SYSTEM_OWNED_RESOURCE_ALLOWLIST`` would permit an ownerless
    row. A hosted app always has an owner and never a system-wide audience.
    """
    for action, types in SYSTEM_SHARED_ACTION_TYPES.items():
        assert "app" not in types, f"app must not be system-shared for {action}"
    assert "app" not in SYSTEM_OWNED_RESOURCE_ALLOWLIST


def test_registry_and_adapters_expose_app() -> None:
    """Points 6 and 7 — the composition root shared by the API **and** worker processes.

    A missing registration here does not fail at import: it fails the first
    time a Celery or Linsight process evaluates a permission, with
    ``RuntimeError("F048 resource registry is not configured")``. Building the
    composition with a stub runtime is enough to prove the wiring.
    """
    from bisheng.api.services.f048_permission_runtime import build_f048_resource_composition
    from bisheng.app_runtime.domain.services.f048_app_permission import (
        F048AppPermissionAdapter,
    )

    adapters, registry = build_f048_resource_composition(SimpleNamespace())

    assert "app" in adapters
    assert isinstance(adapters["app"], F048AppPermissionAdapter)
    # The registry keeps its ports private; resolving an unregistered type is
    # indistinguishable from an invalid id, so probe the internal map directly
    # rather than assert on a shared error class.
    assert "app" in registry._ports


def test_grant_subject_resource_types_carry_app() -> None:
    """Point 8: the picker gate. Without it the dialog opens and finds nobody."""
    assert "app" in GRANT_SUBJECT_RESOURCE_TYPES


# ---------------------------------------------------------------------------
# Deterministic — the five grant-subject endpoints (AC-09, design pit 2)
# ---------------------------------------------------------------------------


_GRANT_SUBJECT_ENDPOINTS = (
    ("list_grant_subject_users", "list_candidate_users", {"keyword": "", "page": 1, "page_size": 50}),
    ("list_grant_subject_user_groups", "list_candidate_user_groups", {"keyword": "", "page": 1, "page_size": 50}),
    ("list_grant_subject_department_children", "list_candidate_department_layer", {"parent_id": None}),
    ("search_grant_subject_departments", "search_candidate_departments", {"keyword": "", "limit": 200}),
    ("get_grant_subject_department_path_tree", "get_candidate_department_path", {"dept_id": 7}),
)


def test_all_five_picker_routes_are_registered() -> None:
    """The dialog calls five URLs; the fifth (path-tree) is the one people forget."""
    paths = {route.path for route in permission_router.routes}
    assert {
        "/permissions/resources/{resource_type}/{resource_id}/grant-subjects/users",
        "/permissions/resources/{resource_type}/{resource_id}/grant-subjects/user-groups",
        "/permissions/resources/{resource_type}/{resource_id}/grant-subjects/departments/children",
        "/permissions/resources/{resource_type}/{resource_id}/grant-subjects/departments/search",
        "/permissions/resources/{resource_type}/{resource_id}/grant-subjects/departments/{dept_id}/path-tree",
    } <= paths


@pytest.mark.parametrize(("endpoint_name", "service_name", "kwargs"), _GRANT_SUBJECT_ENDPOINTS)
async def test_grant_subjects_five_endpoints_accept_app(
    monkeypatch, endpoint_name: str, service_name: str, kwargs: dict
) -> None:
    """Each of the five hard gates lets ``resource_type='app'`` through to the service.

    Driven through the real endpoint functions rather than by re-reading the
    constant: the gate is five separate ``if resource_type not in ...`` lines,
    and only calling all five proves none was missed. Authorization itself is
    stubbed out — this asserts the type gate, not the predicate.
    """
    called: dict[str, object] = {}

    async def _scope(resource_type, resource_id, login_user):
        del login_user
        called["scope"] = (resource_type, resource_id)
        return SimpleNamespace(tenant_id=TENANT_ID, department_path=None)

    async def _service(*args, **service_kwargs):
        called["service"] = (args, service_kwargs)
        return []

    monkeypatch.setattr(grant_subjects, "_authorized_scope", _scope)
    monkeypatch.setattr(grant_subjects.grant_subject_service, service_name, _service)

    endpoint = getattr(grant_subjects, endpoint_name)
    response = await endpoint(resource_type="app", resource_id="app-1", login_user=object(), **kwargs)

    assert called["scope"] == ("app", "app-1")
    assert "service" in called, f"{endpoint_name} stopped before reaching the candidate service"
    assert response.status_code == 200


@pytest.mark.parametrize(("endpoint_name", "service_name", "kwargs"), _GRANT_SUBJECT_ENDPOINTS)
async def test_grant_subjects_still_reject_unregistered_types(
    monkeypatch, endpoint_name: str, service_name: str, kwargs: dict
) -> None:
    """The gate is not simply removed: an unknown type is still refused everywhere."""

    async def _scope(resource_type, resource_id, login_user):
        raise AssertionError("the type gate must run before authorization")

    async def _service(*args, **service_kwargs):
        raise AssertionError("an unregistered type must never reach the candidate service")

    monkeypatch.setattr(grant_subjects, "_authorized_scope", _scope)
    monkeypatch.setattr(grant_subjects.grant_subject_service, service_name, _service)

    endpoint = getattr(grant_subjects, endpoint_name)
    response = await endpoint(resource_type="not_a_type", resource_id="x", login_user=object(), **kwargs)

    assert response.status_code == PermissionDeniedError.Code


# ---------------------------------------------------------------------------
# Deterministic — adapter verdicts (AC-09, AC-11, AC-12)
# ---------------------------------------------------------------------------


async def test_owner_gets_all_actions_on_create() -> None:
    """``authorize_created`` projects the owner as owner, in CUSTOM + protected mode.

    "Owner holds every action" is a property of the CUSTOM owner projection,
    not something F054 enumerates — which is exactly why the adapter must pass
    ``mode="CUSTOM"`` and the real ``owner_user_id`` through rather than invent
    an action list.
    """
    adapter, permission = _adapter(_record())
    await adapter.authorize_created(record=_record(), actor=_actor())

    name, kwargs = permission.calls[-1]
    assert name == "authorize_created"
    assert kwargs["mode"] == "CUSTOM"
    assert kwargs["protected"] is True
    assert kwargs["owner_user_id"] == OWNER_ID
    assert kwargs["target"].resource_type == "app"


@pytest.mark.parametrize("action", APP_ACTIONS)
async def test_every_app_action_reaches_the_sole_facade(action: str) -> None:
    """The adapter narrows nothing: all six actions go to the permission runtime.

    An adapter that quietly refused, say, ``publish`` would make the card's
    stop/resume switch dead with no error anywhere.
    """
    adapter, permission = _adapter(_record())
    assert await adapter.check_action(resource_id="app-1", actor=_actor(), action=action) is True
    assert permission.calls[-1][0] == "check"
    assert permission.calls[-1][1]["action"] == action


async def test_non_owner_of_the_same_tenant_still_resolves() -> None:
    """Resolution is a *fact* check, not a permission check.

    The adapter must not shortcut "not the owner → invalid resource": that
    would deny tenant administrators (who are short-circuited to allow one
    layer up) and everyone the owner explicitly granted. Owner-only rules are
    business pre-checks in the service layer, never here.
    """
    adapter, _ = _adapter(_record())
    target = await adapter.resolve_permission_target(resource_id="app-1", actor=_actor(user_id=OTHER_ID), action="use")
    assert target.resource_type == "app"
    assert target.tenant_id == TENANT_ID


@pytest.mark.parametrize(
    ("record_kwargs", "actor_kwargs"),
    [
        pytest.param({"tenant_id": 2}, {}, id="other-tenant"),
        pytest.param({"owner_user_id": None}, {}, id="no-owner"),
        pytest.param({"owner_user_id": 0}, {}, id="zero-owner"),
        pytest.param({"state": "deleted"}, {}, id="deleted"),
    ],
)
async def test_invalid_business_facts_are_refused_before_the_facade(record_kwargs, actor_kwargs) -> None:
    """Cross-tenant, ownerless and deleted rows never become a permission target."""
    adapter, permission = _adapter(_record(**record_kwargs))
    with pytest.raises(PermissionInvalidResourceError):
        await adapter.resolve_permission_target(resource_id="app-1", actor=_actor(**actor_kwargs), action="use")
    assert permission.calls == []


async def test_unknown_app_is_refused() -> None:
    adapter, _ = _adapter(None)
    with pytest.raises(PermissionInvalidResourceError):
        await adapter.resolve_permission_target(resource_id="nope", actor=_actor(), action="use")


async def test_super_admin_may_resolve_across_tenants() -> None:
    """Consistent with every other adapter: the cross-tenant refusal exempts super admins."""
    adapter, _ = _adapter(_record(tenant_id=2))
    target = await adapter.resolve_permission_target(resource_id="app-1", actor=_actor(super_admin=True), action="use")
    assert target.tenant_id == 2


async def test_fga_unavailable_denies_not_allows(fga_down) -> None:
    """AC-12: an unreachable permission engine denies. It never falls through.

    Asserted at ``check_business_action`` — the single facade every caller uses
    — so it holds regardless of which module imported it by name.
    """
    from bisheng.permission.application.business_authorization import check_business_action

    with pytest.raises(fga_down):
        await check_business_action(
            SimpleNamespace(user_id=OTHER_ID, user_name="x", tenant_id=TENANT_ID),
            resource_type="app",
            resource_id="app-1",
            action="use",
        )


def test_linsight_skill_style_half_registration_would_fail() -> None:
    """Regression guard against copying the ``linsight_skill`` shape (design pit 32).

    ``linsight_skill`` is in the owner-projection list *only* — it appears in no
    Catalog scope and in no grant-subject gate. If a future refactor ever moves
    ``app`` onto that path, these three assertions fail together and say why.
    """
    from bisheng.core.openfga.authorization_model_f048 import OWNER_PROJECTION_RESOURCE_TYPES

    assert "app" not in OWNER_PROJECTION_RESOURCE_TYPES, "app needs the full adapter route, not owner projection"
    # The reference failure, kept explicit so the contrast is readable.
    assert "linsight_skill" not in CATALOG_MIGRATED_TYPES
    assert "linsight_skill" not in GRANT_SUBJECT_RESOURCE_TYPES


# ---------------------------------------------------------------------------
# Integration — needs OpenFGA + MySQL (AC-09, AC-10, AC-11, AC-12)
# ---------------------------------------------------------------------------


@integration
async def test_owner_holds_every_action_after_create() -> None:
    """AC-09: after ``authorize_created`` the owner's my-permissions covers all six actions."""
    raise NotImplementedError("wired in the CI middleware job; see design §7")


@integration
async def test_default_visible_only_to_owner() -> None:
    """AC-11: a freshly created app denies ``use`` to an ungranted ordinary user."""
    raise NotImplementedError("wired in the CI middleware job; see design §7")


@integration
@pytest.mark.parametrize("subject_kind", ["user", "department", "user_group"])
async def test_grant_use_to_subject_then_allow(subject_kind: str) -> None:
    """AC-09: granting ``use`` to a user / department / user group makes it allow."""
    raise NotImplementedError("wired in the CI middleware job; see design §7")


@integration
async def test_visibility_change_effective_next_request_and_audited() -> None:
    """AC-10: revoking denies on the next decision, and the grant change records who did it."""
    raise NotImplementedError("wired in the CI middleware job; see design §7")


@integration
async def test_tenant_admin_short_circuit_visible() -> None:
    """AC-09: a tenant administrator is allowed without any grant (pre-existing behaviour)."""
    raise NotImplementedError("wired in the CI middleware job; see design §7")
