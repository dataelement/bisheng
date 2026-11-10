"""F118 CAS setup HTTP contract; local transport, not live E2E evidence."""

import json

import httpx
import pytest

from test.e2e.helpers.f118_mysql_cas import CasEnvironment
from test.e2e.helpers.f118_unification import F118Environment


@pytest.mark.parametrize("broken_decision", [None, "visible", "edit", "delete"])
async def test_cas_setup_separates_visibility_from_empty_explained_actions(monkeypatch, broken_decision):
    spaces, reads, decisions = {}, [], []

    async def prepared_child(env):
        env.tenant_id, env.owner_id, env.reader_id = 31, 131, 231
        env.root = {"Cookie": "unit-root"}
        env.owner = {"Cookie": "unit-child-owner"}
        env.reader = {"Cookie": "unit-child-reader"}

    monkeypatch.setattr(F118Environment, "prepare", prepared_child)

    async def transport(request):
        path = request.url.path.removeprefix("/api/v1")
        actor = request.headers["Cookie"]
        if path == "/user/info":
            assert actor == "unit-child-reader"
            data = {"role": "user", "is_child_admin": False, "leaf_tenant_id": 31}
        elif path == "/knowledge/space" and request.method == "POST":
            assert actor == "unit-child-owner"
            body = json.loads(request.content)
            sid = 101 + len(spaces)
            data = {"id": sid, "tenant_id": 31, "user_id": 131, "name": body["name"]}
            spaces[sid] = data
        elif path == "/permissions/catalog":
            assert actor == "unit-root"
            data = {
                "models": [
                    {"key": "unit-visible", "action_codes": [], "visibility_only_resource_types": ["knowledge_space"]}
                ]
            }
        elif path.endswith("/grantable-models"):
            data = [{"key": "unit-visible", "active": True, "visibility_only": True}]
        elif path.endswith("/context"):
            data = {"resource_version": 1, "catalog_release_id": 1}
        elif path.endswith("/grants:mutate"):
            body = json.loads(request.content)
            assert actor == "unit-child-owner"
            assert body["changes"] == [
                {"op": "ADD", "model_key": "unit-visible", "subject": {"type": "user", "id": "231"}}
            ]
            data = {}
        elif path.endswith("/my-permissions"):
            assert actor == "unit-child-reader"
            data = {"mode": "CUSTOM", "actions": [], "projection_degraded": False}
        elif path == "/permissions/check":
            body = json.loads(request.content)
            assert actor == "unit-child-reader"
            assert body["resource_type"] == "knowledge_space"
            sid, action = int(body["resource_id"]), body["action"]
            assert sid in spaces and action in {"visible", "edit", "delete"}
            decisions.append((sid, action))
            allowed = action == "visible"
            data = {"allowed": not allowed if action == broken_decision else allowed}
        elif path.startswith("/knowledge/space/") and path.endswith("/info"):
            assert actor == "unit-child-reader"
            sid = int(path.split("/")[-2])
            reads.append(sid)
            data = spaces[sid]
        else:
            pytest.fail(f"Unexpected local contract route: {request.method} {path}")
        return httpx.Response(200, json={"status_code": 200, "status_message": "success", "data": data})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        fixture = CasEnvironment(client, "unit", 1, "unit-only", {}, {})
        if broken_decision is not None:
            with pytest.raises(AssertionError):
                await fixture.prepare_cas()
        else:
            await fixture.prepare_cas()
            assert reads == [101, 102, 103]
            assert decisions == [(sid, action) for sid in (101, 102, 103) for action in ("visible", "edit", "delete")]
