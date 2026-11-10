"""CAS creator HTTP contract with the native effective-menu oracle; not live E2E."""

import json
from inspect import signature
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.tenant.api.endpoints.tenant_crud import get_tenant
from bisheng.user.domain.services.auth import DepartmentDao, LoginUser, UserDao, _effective_web_menu_strip_orphans
from test.e2e.helpers.f118_cas_creator import CREATOR_MENUS, CasCreator
from test.e2e.helpers.f118_mysql_cas import CasEnvironment

TENANT_METADATA_GATE = signature(get_tenant).parameters["login_user"].default.dependency


@pytest.mark.parametrize("global_super", [False, True])
async def test_native_tenant_metadata_gate_excludes_child_administrator(monkeypatch, global_super):
    identity = UserPayload(
        user_id=131, user_name="unit-owner", tenant_id=1 if global_super else 31, user_role=[1] if global_super else [2]
    )

    async def current_user(_auth):
        return identity

    monkeypatch.setattr(UserPayload, "get_login_user", current_user)
    if global_super:
        assert await TENANT_METADATA_GATE(None) is identity
    else:
        with pytest.raises(HTTPException) as refused:
            await TENANT_METADATA_GATE(None)
        assert refused.value.status_code == 403


@pytest.mark.parametrize("existing", [None, "creator", "assigned", "orphan", "broad"])
@pytest.mark.parametrize("broken", [None, "ineffective", "admin", "child_admin", "lost_role", "occupied"])
async def test_creator_assignment_preserves_roles_and_cleans_only_own_role(monkeypatch, existing, broken):
    menus = {2: {"workstation", "home"}}
    if existing:
        menus[7] = (
            {"create_app"} if existing == "orphan" else CREATOR_MENUS | ({"model"} if existing == "broad" else set())
        )
    state = {"roles": {2}, "created": [], "deleted": [], "calls": [], "form_reads": 0}
    if existing == "assigned":
        state["roles"].add(7)
    env = None
    reader = SimpleNamespace(user_id=231, is_admin=lambda: False)
    root = UserPayload(user_id=1, user_name="unit-root", user_role=[1], tenant_id=1)

    async def current_user(*_args, **_kwargs):
        return root if _args and _args[0] == "unit-root" else reader

    async def admin_departments(*_args):
        return []

    async def effective_menus(*_args, **_kwargs):
        return "user", _effective_web_menu_strip_orphans(list(set().union(*(menus[r] for r in state["roles"]))))

    monkeypatch.setattr(LoginUser, "get_login_user", current_user)
    monkeypatch.setattr(UserDao, "aget_user", current_user)
    monkeypatch.setattr(DepartmentDao, "aget_user_admin_departments", admin_departments)
    monkeypatch.setattr(LoginUser, "get_roles_web_menu", effective_menus)

    async def login(client, username, password):
        assert username == env.prefix + "reader" and password == "unit-password"
        return "unit-reader"

    monkeypatch.setattr("test.e2e.helpers.f118_cas_creator.get_user_token", login)

    async def transport(request):
        path = request.url.path.removeprefix("/api/v1")
        method = request.method
        state["calls"].append((method, path))
        if path == "/tenants/31":
            try:
                await TENANT_METADATA_GATE(request.headers["Cookie"])
            except HTTPException as exc:
                return httpx.Response(200, json={"status_code": exc.status_code, "status_message": "refused"})
            data = {"root_dept_id": 41}
        elif path == "/departments/41":
            assert request.headers["Cookie"] == "unit-root"
            data = {"id": 41, "dept_id": "unit-dept", "name": env.prefix + "tenant", "parent_id": 1}
        elif path == "/user/info":
            assert request.headers["Cookie"] == "access_token_cookie=unit-reader"
            effective = _effective_web_menu_strip_orphans(list(set().union(*(menus[r] for r in state["roles"]))))
            data = {
                "user_name": env.prefix + "reader",
                "leaf_tenant_id": 31,
                "role": "admin" if broken == "admin" else "user",
                "is_child_admin": broken == "child_admin",
                "web_menu": [] if broken == "ineffective" else effective,
            }
        else:
            assert request.headers["Cookie"] == "unit-owner"
            assert request.headers["X-Management-Tenant"] == "31"
            if path.endswith("/assignable-roles"):
                data = [{"id": rid, "role_name": "ordinary" if rid == 2 else "existing-creator"} for rid in menus]
            elif path.endswith("/menu"):
                data = sorted(menus[int(path.split("/")[2])])
            elif path.endswith("/edit-form"):
                state["form_reads"] += 1
                if broken == "lost_role" and state["form_reads"] > 1:
                    state["roles"].discard(2)
                data = {
                    "edit_mode": "local_primary",
                    "affiliate_rows": [],
                    "primary_department": {"id": 41, "role_ids": sorted(state["roles"])},
                }
            elif path.endswith("/apply-edit"):
                state["roles"] = set(json.loads(request.content)["primary_role_ids"])
                if broken == "lost_role":
                    state["roles"].discard(2)
                data = None
            elif path == "/roles" and method == "POST":
                body = json.loads(request.content)
                assert body == {
                    "role_name": env.prefix + "creator",
                    "department_id": 41,
                    "menu_ids": sorted(CREATOR_MENUS),
                }
                state["created"].append(8)
                menus[8] = set(body["menu_ids"])
                data = {"id": 8, "role_type": "tenant", "role_name": body["role_name"], "department_id": 41}
            elif path == "/roles/8" and method == "GET":
                data = {
                    "role_name": env.prefix + "creator",
                    "role_type": "tenant",
                    "department_id": 41,
                    "user_count": int(broken == "occupied"),
                }
            elif path == "/roles/8" and method == "DELETE":
                state["deleted"].append(8)
                data = None
            else:
                pytest.fail(f"Unexpected contract request: {method} {path}")
        return httpx.Response(200, json={"status_code": 200, "status_message": "success", "data": data})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        env = CasEnvironment(client, "unit", 1, "unit-password", {}, {})
        env.tenant_id, env.reader_id = 31, 231
        env.root = {"Cookie": "unit-root", "X-Management-Tenant": "1"}
        env.owner = {"Cookie": "unit-owner", "X-Management-Tenant": "31"}
        fixture = CasCreator(env)
        # Exercise the unchanged native create dependency: ordinary login alone
        # is rejected before any Flow can be written; this is the live failure.
        if existing == "assigned":
            assert await LoginUser.get_app_creator_user(None) is reader
        else:
            with pytest.raises(HTTPException) as refused:
                await LoginUser.get_app_creator_user(None)
            assert refused.value.status_code == 403
        if broken in {"ineffective", "admin", "child_admin", "lost_role"}:
            with pytest.raises(AssertionError):
                await fixture.install()
            return
        await fixture.install()
        assert await LoginUser.get_app_creator_user(None) is reader
        reused = existing in {"creator", "assigned"}
        assert state["created"] == ([] if reused else [8])
        assert state["roles"] == {2, 7 if reused else 8}
        # A later unrelated assignment must survive teardown too.
        state["roles"].add(19)
        if broken == "occupied" and not reused:
            with pytest.raises(AssertionError):
                await fixture.cleanup()
            assert state["deleted"] == []
        else:
            await fixture.cleanup()
            assert state["deleted"] == ([] if reused else [8])
        assert state["roles"] == ({2, 7, 19} if existing == "assigned" else {2, 19})
        assert not any(method == "PUT" or path == "/roles/7" for method, path in state["calls"])


@pytest.mark.parametrize("fails", [False, True])
async def test_cas_cleanup_keeps_creator_until_business_cleanup_succeeds(monkeypatch, fails):
    from test.e2e.helpers.f118_unification import F118Environment

    calls = []

    async def failed_cleanup(_env):
        calls.append("business")
        if fails:
            raise AssertionError("business resource retained")

    class Creator:
        async def cleanup(self):
            calls.append("role")

    monkeypatch.setattr(F118Environment, "cleanup", failed_cleanup)
    async with httpx.AsyncClient() as client:
        env = CasEnvironment(client, "unit", 1, "unit-password", {}, {})
        env.creator_fixture = Creator()
        if fails:
            with pytest.raises(AssertionError, match="business resource retained"):
                await env.cleanup()
        else:
            await env.cleanup()
    assert calls == (["business"] if fails else ["business", "role"])
