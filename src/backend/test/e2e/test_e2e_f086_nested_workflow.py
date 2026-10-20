"""Live E2E coverage for F086 nested workflows (subflow node).

Runs against a dedicated deployment of the F086 branch. Set ``F086_E2E=1``,
``E2E_API_BASE`` (``http://<host>:<port>/api/v1``) and, when the admin
password is not the default, ``E2E_ADMIN_PASSWORD``.

Workflows are debug-run over the platform WebSocket exactly like the editor's
run panel (``init_data`` with the draft graph), so a parent never needs to be
online; AC-18 goes through ``/api/v2/workflow/invoke`` with a service-account
key. Every object this suite creates is named ``e2e-f086-*`` and removed in
teardown; the run also clears leftovers of a previous run first.
"""

from __future__ import annotations

import asyncio
import json
import os
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
import websockets

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, create_test_user, get_admin_token, get_user_token

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("F086_E2E") != "1",
        reason="set F086_E2E=1 only against a dedicated F086 test deployment",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]

PREFIX = "e2e-f086-"
USER_NAME = "e2e-f086-user"
USER_PASSWORD = "E2e-f086-pass"
API_ORIGIN = API_BASE.removesuffix("/api/v1")
WS_BASE = API_BASE.replace("http", "ws", 1)
RUN_TIMEOUT = 180

ONLINE = 2
OFFLINE = 1


# ---------------------------------------------------------------- graph builders


def _node(node_id: str, node_type: str, params: list[dict], v: int = 2, **extra) -> dict:
    data = {
        "id": node_id,
        "type": node_type,
        "name": node_id,
        "description": "",
        "v": v,
        "group_params": [{"name": "", "params": params}],
        **extra,
    }
    return {"id": node_id, "type": "flowNode", "position": {"x": 0, "y": 0}, "data": data}


def var_key(name: str) -> str:
    """Key of a custom variable; the editor generates a random key and shows the label."""
    return f"key_{name}"


def start(node_id: str, variables: dict[str, str] | None = None, guide_word: str = "") -> dict:
    custom = [{"key": var_key(k), "label": k, "value": v} for k, v in (variables or {}).items()]
    return _node(
        node_id,
        "start",
        [
            {"key": "guide_word", "value": guide_word},
            {"key": "guide_question", "value": ["child question"] if guide_word else []},
            {"key": "user_info", "value": ""},
            {"key": "current_time", "value": ""},
            {"key": "chat_history", "value": 10},
            {"key": "preset_question", "value": []},
            {"key": "custom_variables", "value": custom},
        ],
        v=3,
    )


def var_ref(start_id: str, name: str) -> str:
    return f"{start_id}.custom_variables#{var_key(name)}"


def end(node_id: str, results: dict[str, str] | None = None) -> dict:
    """End node; ``results`` maps return name -> variable reference, ``None`` = switch off."""
    return _node(
        node_id,
        "end",
        [
            {"key": "return_enabled", "value": results is not None},
            {
                "key": "return_results",
                "value": [{"key": k, "type": "ref", "label": v, "value": v} for k, v in (results or {}).items()],
            },
        ],
    )


def subflow(
    node_id: str, child_id: str, inputs: dict[str, str] | None = None, outputs: list[str] | None = None
) -> dict:
    rows = [{"key": k, "type": "input", "label": "", "value": v} for k, v in (inputs or {}).items()]
    return _node(
        node_id,
        "subflow",
        [
            {"key": "subflow_id", "value": {"id": child_id, "name": "snapshot"}},
            {"key": "subflow_inputs", "value": rows},
            {"key": "subflow_outputs", "value": [{"key": one} for one in outputs or []]},
        ],
        v=1,
    )


def output(node_id: str, msg: str) -> dict:
    return _node(
        node_id,
        "output",
        [
            {"key": "output_msg", "value": {"msg": msg, "files": []}},
            {"key": "output_result", "value": {"type": "", "value": ""}},
        ],
    )


def dialog_input(node_id: str) -> dict:
    return _node(
        node_id,
        "input",
        [
            {"key": "user_input", "value": ""},
            {"key": "dialog_files_content", "value": []},
            {"key": "dialog_files_content_size", "value": 15000},
            {"key": "dialog_file_accept", "value": "all"},
            {"key": "dialog_image_files", "value": []},
            {"key": "dialog_file_paths", "value": []},
        ],
        v=3,
        tab={"value": "dialog_input", "options": []},
    )


def code(node_id: str, source: str, outputs: list[str]) -> dict:
    return _node(
        node_id,
        "code",
        [
            {"key": "code_input", "value": []},
            {"key": "code", "value": source},
            {"key": "code_output", "value": [{"key": one, "type": "str"} for one in outputs]},
        ],
        v=1,
    )


def chain(*nodes: dict) -> dict:
    edges = [
        {
            "id": f"edge_{a['id']}_{b['id']}",
            "source": a["id"],
            "sourceHandle": "right_handle",
            "target": b["id"],
            "targetHandle": "left_handle",
        }
        for a, b in zip(nodes, nodes[1:])
    ]
    return {"nodes": list(nodes), "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 1}}


# ---------------------------------------------------------------- API helpers


class Flows:
    """Workflow operations of one caller."""

    def __init__(self, client: httpx.AsyncClient, token: str):
        self.client = client
        self.token = token
        self.headers = auth_headers(token)

    async def create(self, name: str, data: dict) -> dict:
        resp = await self.client.post(
            f"{API_BASE}/workflow/create",
            json={"name": f"{PREFIX}{name}", "description": "", "data": data},
            headers=self.headers,
        )
        # The create route answers 201 with the usual envelope.
        assert resp.status_code == 201, f"HTTP {resp.status_code}: {resp.text[:200]}"
        body = resp.json()
        assert body["status_code"] == 200, body
        created = body["data"]
        return {"id": created["id"], "version_id": created["version_id"], "name": created["name"]}

    async def get(self, flow_id: str) -> dict:
        return assert_resp_200(
            await self.client.get(f"{API_BASE}/workflow/get_one_flow/{flow_id}", headers=self.headers)
        )

    async def save(self, flow: dict, data: dict) -> dict:
        """Save the current version the way the editor does; return the response data."""
        resp = await self.client.put(
            f"{API_BASE}/workflow/versions/{flow['version_id']}",
            json={"data": data, "flow_type": 10},
            headers=self.headers,
        )
        return assert_resp_200(resp)

    async def new_version(self, flow: dict, name: str, data: dict) -> int:
        resp = await self.client.post(
            f"{API_BASE}/workflow/versions",
            params={"flow_id": flow["id"]},
            json={"name": name, "description": "", "data": data, "original_version_id": flow["version_id"]},
            headers=self.headers,
        )
        return assert_resp_200(resp)["id"]

    async def change_version(self, flow: dict, version_id: int) -> httpx.Response:
        return await self.client.post(
            f"{API_BASE}/workflow/change_version",
            params={"flow_id": flow["id"], "version_id": version_id},
            headers=self.headers,
        )

    async def set_status(self, flow: dict, status: int) -> httpx.Response:
        return await self.client.patch(
            f"{API_BASE}/workflow/status",
            json={"flow_id": flow["id"], "version_id": flow["version_id"], "status": status},
            headers=self.headers,
        )

    async def delete(self, flow_id: str) -> httpx.Response:
        return await self.client.delete(f"{API_BASE}/flows/{flow_id}", headers=self.headers)

    async def candidates(self, keyword: str, exclude_flow_id: str | None = None) -> list[dict]:
        params = {"name": keyword, "page_size": 100}
        if exclude_flow_id:
            params["exclude_flow_id"] = exclude_flow_id
        resp = await self.client.get(f"{API_BASE}/workflow/subflow/candidates", params=params, headers=self.headers)
        return assert_resp_200(resp)["data"]

    async def interface(self, flow_id: str) -> httpx.Response:
        return await self.client.get(f"{API_BASE}/workflow/subflow/{flow_id}/interface", headers=self.headers)

    async def run(self, flow_id: str, data: dict) -> list[dict]:
        """Debug-run ``data`` as the editor's run panel does; return every pushed message."""
        events: list[dict] = []
        async with websockets.connect(
            f"{WS_BASE}/workflow/chat/{flow_id}",
            additional_headers=self.headers,
            max_size=None,
        ) as ws:
            await ws.send(json.dumps({"action": "init_data", "flow_id": flow_id, "data": data}))
            while True:
                message = json.loads(await asyncio.wait_for(ws.recv(), RUN_TIMEOUT))
                events.append(message)
                if message.get("category") == "processing" and message.get("type") == "close":
                    return events


def node_end(events: list[dict], node_id: str) -> dict:
    ends = [
        e["message"]
        for e in events
        if e.get("category") == "node_run" and e.get("type") == "end" and e["message"]["node_id"] == node_id
    ]
    assert ends, f"node {node_id} never finished: {[e.get('category') for e in events]}"
    return ends[-1]


def log_item(node_message: dict, key: str):
    for round_items in node_message.get("log_data") or []:
        for item in round_items:
            if item["key"] == key:
                return item["value"]
    raise AssertionError(f"log item {key} missing in {node_message}")


def run_error(events: list[dict]) -> dict | None:
    errors = [e["message"] for e in events if e.get("category") == "error"]
    return errors[-1] if errors else None


def assert_run_ok(events: list[dict]) -> None:
    error = run_error(events)
    assert error is None, f"run failed: {error}"


async def cleanup(flows: Flows) -> None:
    """Delete every ``e2e-f086-`` workflow; parents go first because referenced children refuse."""
    for _ in range(5):
        resp = await flows.client.get(
            f"{API_BASE}/workflow/list",
            params={"name": PREFIX, "page_num": 1, "page_size": 100, "flow_type": 10},
            headers=flows.headers,
        )
        rows = [one for one in assert_resp_200(resp)["data"] if one["name"].startswith(PREFIX)]
        if not rows:
            return
        for one in rows:
            if one["status"] == ONLINE:
                version = next((v for v in one.get("version_list") or [] if v.get("is_current")), None)
                if version:
                    await flows.set_status({"id": one["id"], "version_id": version["id"]}, OFFLINE)
            await flows.delete(one["id"])
    raise AssertionError("could not remove e2e-f086 workflows")


async def grant(client: httpx.AsyncClient, admin_token: str, flow_id: str, user_id: int, model_key: str) -> None:
    context = assert_resp_200(
        await client.get(
            f"{API_BASE}/permissions/resources/workflow/{flow_id}/context",
            headers=auth_headers(admin_token),
        )
    )
    assert_resp_200(
        await client.post(
            f"{API_BASE}/permissions/resources/workflow/{flow_id}/grants:mutate",
            json={
                "idempotency_key": f"{PREFIX}{uuid4().hex}",
                "expected_resource_version": context["resource_version"],
                "expected_catalog_release_id": context["catalog_release_id"],
                "changes": [{"op": "ADD", "model_key": model_key, "subject": {"type": "user", "id": str(user_id)}}],
            },
            headers=auth_headers(admin_token),
        )
    )


async def revoke(client: httpx.AsyncClient, admin_token: str, flow_id: str, user_id: int) -> None:
    headers = auth_headers(admin_token)
    context = assert_resp_200(
        await client.get(f"{API_BASE}/permissions/resources/workflow/{flow_id}/context", headers=headers)
    )
    grants = assert_resp_200(
        await client.get(f"{API_BASE}/permissions/resources/workflow/{flow_id}/grants", headers=headers)
    )
    changes = [
        {"op": "REMOVE", "assignee_id": one["assignee_id"], "expected_assignee_version": one.get("assignee_version")}
        for one in grants["data"]
        if one["subject"]["type"] == "user" and one["subject"]["id"] == str(user_id)
    ]
    assert changes, f"user {user_id} has no grant on {flow_id}"
    for change in changes:
        if change["expected_assignee_version"] is None:
            change.pop("expected_assignee_version")
    assert_resp_200(
        await client.post(
            f"{API_BASE}/permissions/resources/workflow/{flow_id}/grants:mutate",
            json={
                "idempotency_key": f"{PREFIX}{uuid4().hex}",
                "expected_resource_version": context["resource_version"],
                "expected_catalog_release_id": context["catalog_release_id"],
                "changes": changes,
            },
            headers=headers,
        )
    )


# ---------------------------------------------------------------- fixtures


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client():
    async with httpx.AsyncClient(timeout=60.0) as value:
        yield value


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def admin(client: httpx.AsyncClient):
    flows = Flows(client, await get_admin_token(client))
    await cleanup(flows)
    yield flows
    await cleanup(flows)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def user(client: httpx.AsyncClient, admin: Flows) -> tuple[int, Flows]:
    """A plain user, created once and reused by later runs."""
    try:
        token = await get_user_token(client, USER_NAME, USER_PASSWORD)
    except AssertionError:
        await create_test_user(client, admin.token, USER_NAME, password=USER_PASSWORD)
        token = await get_user_token(client, USER_NAME, USER_PASSWORD)
    info = assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=auth_headers(token)))
    return info["user_id"], Flows(client, token)


@pytest.fixture
def tag() -> str:
    return uuid4().hex[:8]


def simple_child(value: str = "child1") -> dict:
    """Child with input ``k1`` (default ``value``) returning ``a`` = k1."""
    return chain(start("start_c", {"k1": value}), end("end_c", {"a": var_ref("start_c", "k1")}))


def calling_parent(child_id: str, inputs: dict | None = None, outputs: tuple[str, ...] = ("a",)) -> dict:
    return chain(
        start("start_p"),
        subflow("subflow_p", child_id, inputs, list(outputs)),
        end("end_p", {f"r_{one}": f"subflow_p.{one}" for one in outputs}),
    )


# ---------------------------------------------------------------- tests


class TestE2EF086NestedWorkflow:
    async def test_ac01_ac13_ac19_inputs_override_and_values_pass_through(self, admin: Flows, tag: str):
        """AC-01, AC-13, AC-19: overrides by name, unset keeps the child value, unknown names are ignored, values are not converted."""
        child = await admin.create(
            f"io-child-{tag}",
            chain(
                start("start_c", {"k1": "child1", "k2": "child2", "k3": "child3"}),
                end(
                    "end_c",
                    {
                        "a": var_ref("start_c", "k1"),
                        "b": var_ref("start_c", "k2"),
                        "c": var_ref("start_c", "k3"),
                        "d": "start_c.preset_question",
                    },
                ),
            ),
        )
        parent_data = calling_parent(child["id"], {"k1": "123", "k2": "", "gone": "x"}, ("a", "b", "c", "d"))
        parent = await admin.create(f"io-parent-{tag}", parent_data)

        events = await admin.run(parent["id"], parent_data)

        assert_run_ok(events)
        sub = node_end(events, "subflow_p")
        # The log shows what the parent passed (the empty row is left out); the child ignores ``gone``.
        assert log_item(sub, "subflow_inputs") == {"k1": "123", "gone": "x"}
        assert log_item(sub, "subflow_outputs") == {"a": "123", "b": "child2", "c": "child3", "d": {}}
        returned = log_item(node_end(events, "end_p"), "return_results")
        assert returned == {"r_a": "123", "r_b": "child2", "r_c": "child3", "r_d": {}}

    async def test_ac03_candidates_list_only_eligible_editable_flows(self, admin: Flows, user, tag: str, client):
        """AC-03, AC-08: the picker lists eligible flows only; never-online flows are listed; the edited flow is excluded."""
        ok = await admin.create(f"cand-ok-{tag}", simple_child())
        with_input = await admin.create(
            f"cand-input-{tag}", chain(start("start_c"), dialog_input("input_c"), end("end_c"))
        )
        with_subflow = await admin.create(f"cand-sub-{tag}", calling_parent(ok["id"]))
        viewer_only = await admin.create(f"cand-viewer-{tag}", simple_child())

        names = {one["name"] for one in await admin.candidates(tag, exclude_flow_id=ok["id"])}
        assert ok["name"] not in names
        assert with_input["name"] not in names and with_subflow["name"] not in names
        assert viewer_only["name"] in names

        names = {one["name"] for one in await admin.candidates(tag)}
        assert {ok["name"], viewer_only["name"]} <= names
        assert (await admin.get(ok["id"]))["status"] == OFFLINE

        user_id, user_flows = user
        await grant(client, admin.token, ok["id"], user_id, "editor")
        await grant(client, admin.token, viewer_only["id"], user_id, "viewer")
        names = {one["name"] for one in await user_flows.candidates(tag)}
        assert ok["name"] in names
        assert viewer_only["name"] not in names

    async def test_ac04_online_refused_for_ineligible_child_draft_allowed(self, admin: Flows, tag: str):
        """AC-04, AC-08: saving a draft that calls an ineligible child works, going online is refused with the reason."""
        bad_child = await admin.create(
            f"online-bad-{tag}", chain(start("start_c"), dialog_input("input_c"), end("end_c"))
        )
        parent = await admin.create(f"online-parent-{tag}", calling_parent(bad_child["id"], outputs=()))

        assert (await admin.save(parent, calling_parent(bad_child["id"], outputs=()))) is not None

        body = assert_resp_error(await admin.set_status(parent, ONLINE), 10564)
        assert bad_child["name"] in body["status_message"]
        assert body["data"]["subflow_name"] == bad_child["name"]
        assert body["data"]["reason_codes"] == ["input_node"]
        assert (await admin.get(parent["id"]))["status"] == OFFLINE

        good_child = await admin.create(f"online-good-{tag}", simple_child())
        good_parent = await admin.create(f"online-ok-{tag}", calling_parent(good_child["id"]))
        assert_resp_200(await admin.set_status(good_parent, ONLINE))
        assert (await admin.get(good_child["id"]))["status"] == OFFLINE
        assert_resp_200(await admin.set_status(good_parent, OFFLINE))

    async def test_ac05_ac12_ac06_save_warns_and_run_fails_on_forbidden_node(self, admin: Flows, tag: str):
        """AC-05, AC-12, AC-06: saving a referenced flow warns about callers; reaching a forbidden node fails the parent."""
        child = await admin.create(f"warn-child-{tag}", simple_child())
        parent_data = calling_parent(child["id"])
        parent = await admin.create(f"warn-parent-{tag}", parent_data)

        changed = chain(
            start("start_c", {"k1": "v", "k9": "new"}),
            dialog_input("input_c"),
            end("end_c", {"z": var_ref("start_c", "k9")}),
        )
        saved = await admin.save(child, changed)
        warning = saved["subflow_warning"]
        assert [one["name"] for one in warning["referenced_by"]] == [parent["name"]]
        assert [one["type"] for one in warning["forbidden_nodes"]] == ["input"]
        assert warning["interface_changes"] == {
            "inputs_added": ["k9"],
            "inputs_removed": [],
            "outputs_added": ["z"],
            "outputs_removed": ["a"],
        }

        error = run_error(await admin.run(parent["id"], parent_data))
        assert error is not None and error["status_code"] == 10563, error
        assert error["data"]["subflow_name"] == child["name"]

        unreferenced = await admin.create(f"warn-free-{tag}", simple_child())
        assert "subflow_warning" not in (await admin.save(unreferenced, changed))

    async def test_ac07_parent_runs_the_child_current_version(self, admin: Flows, tag: str):
        """AC-07: a saved child and a switched current version both take effect on the next parent run."""
        child = await admin.create(f"ver-child-{tag}", simple_child("v1"))
        parent_data = calling_parent(child["id"])
        parent = await admin.create(f"ver-parent-{tag}", parent_data)

        async def returned() -> str:
            events = await admin.run(parent["id"], parent_data)
            assert_run_ok(events)
            return log_item(node_end(events, "end_p"), "return_results")["r_a"]

        assert await returned() == "v1"
        await admin.save(child, simple_child("v2"))
        assert await returned() == "v2"

        version_id = await admin.new_version(child, f"{PREFIX}v3", simple_child("v3"))
        switched = assert_resp_200(await admin.change_version(child, version_id))
        assert switched is None or "subflow_warning" not in switched
        assert await returned() == "v3"

    async def test_ac11_delete_refused_while_referenced(self, admin: Flows, tag: str):
        """AC-11: deleting a referenced flow is refused with its callers; allowed once no one calls it."""
        child = await admin.create(f"del-child-{tag}", simple_child())
        parent = await admin.create(f"del-parent-{tag}", calling_parent(child["id"]))

        body = assert_resp_error(await admin.delete(child["id"]), 10565)
        assert body["data"]["referrers"] == [{"id": parent["id"], "name": parent["name"]}]
        assert parent["name"] in body["status_message"]
        assert (await admin.get(child["id"]))["id"] == child["id"]

        await admin.save(parent, chain(start("start_p"), end("end_p")))
        assert_resp_200(await admin.delete(child["id"]))
        assert_resp_200(await admin.delete(parent["id"]))

    async def test_ac14_missing_return_fails_with_its_name(self, admin: Flows, tag: str):
        """AC-14: a referenced return result the child no longer has fails the node and names it."""
        child = await admin.create(f"miss-child-{tag}", simple_child())
        parent_data = chain(
            start("start_p"),
            subflow("subflow_p", child["id"], outputs=["a", "gone"]),
            end("end_p", {"x": "subflow_p.gone"}),
        )
        parent = await admin.create(f"miss-parent-{tag}", parent_data)

        error = run_error(await admin.run(parent["id"], parent_data))
        assert error is not None and error["status_code"] == 10562, error
        assert "gone" in error["status_message"]
        assert error["data"]["subflow_name"] == child["name"]

    async def test_ac15_ac16_ac17_silent_child_shared_context_nested_log(self, admin: Flows, tag: str):
        """AC-15, AC-16, AC-17: the child pushes nothing, shares the parent's user and time, and its nodes are logged."""
        child = await admin.create(
            f"log-child-{tag}",
            chain(
                start("start_c", {"k1": "x"}, guide_word="child guide word"),
                output("output_c", "child says hi"),
                end("end_c", {"a": var_ref("start_c", "k1")}),
            ),
        )
        parent_data = calling_parent(child["id"])
        parent = await admin.create(f"log-parent-{tag}", parent_data)

        events = await admin.run(parent["id"], parent_data)

        assert_run_ok(events)
        pushed_from_child = [
            e
            for e in events
            if isinstance(e.get("message"), dict) and e["message"].get("node_id") in {"start_c", "output_c", "end_c"}
        ]
        assert pushed_from_child == []
        assert "child says hi" not in json.dumps(
            [e for e in events if e.get("category") != "node_run"], ensure_ascii=False
        )

        sub = node_end(events, "subflow_p")
        inner = {one["node_id"]: one for one in log_item(sub, "subflow_logs")}
        assert list(inner) == ["start_c", "output_c", "end_c"]
        for one in inner.values():
            assert one["reason"] is None and isinstance(one["duration_ms"], int)
        assert log_item(inner["end_c"], "return_results") == {"a": "x"}

        parent_start = node_end(events, "start_p")
        assert log_item(inner["start_c"], "current_time") == log_item(parent_start, "current_time")
        assert log_item(inner["start_c"], "user_info") == log_item(parent_start, "user_info")

    async def test_ac20_inner_failure_names_subflow_node_and_error(self, admin: Flows, tag: str):
        """AC-20: an inner node failure fails the parent with subflow name, inner node name and the original error."""
        child = await admin.create(
            f"fail-child-{tag}",
            chain(
                start("start_c"),
                code("code_c", "def main() -> dict:\n    raise ValueError('e2e-f086 boom')\n", ["r"]),
                end("end_c", {"a": "code_c.r"}),
            ),
        )
        parent_data = calling_parent(child["id"])
        parent = await admin.create(f"fail-parent-{tag}", parent_data)

        events = await admin.run(parent["id"], parent_data)

        error = run_error(events)
        assert error is not None and error["status_code"] == 10560, error
        assert error["data"]["subflow_name"] == child["name"]
        assert error["data"]["node_name"] == "code_c"
        assert "e2e-f086 boom" in error["data"]["reason"]
        assert "end_p" not in {e["message"].get("node_id") for e in events if e.get("category") == "node_run"}

    async def test_ac09_ac10_runs_without_permission_on_the_child(self, admin: Flows, user, tag: str, client):
        """AC-09, AC-10: a user allowed to use the parent runs it although the child is not theirs, also after edit rights are revoked."""
        user_id, user_flows = user
        child = await admin.create(f"perm-child-{tag}", simple_child("secret"))
        await grant(client, admin.token, child["id"], user_id, "editor")
        assert assert_resp_200(await user_flows.interface(child["id"]))["eligible"] is True

        parent_data = calling_parent(child["id"])
        parent = await admin.create(f"perm-parent-{tag}", parent_data)
        await grant(client, admin.token, parent["id"], user_id, "viewer")
        await revoke(client, admin.token, child["id"], user_id)

        assert (await user_flows.interface(child["id"])).json()["status_code"] != 200
        assert child["name"] not in {one["name"] for one in await user_flows.candidates(tag)}

        events = await user_flows.run(parent["id"], parent_data)
        assert_run_ok(events)
        assert log_item(node_end(events, "end_p"), "return_results") == {"r_a": "secret"}
        inner_start = next(
            one for one in log_item(node_end(events, "subflow_p"), "subflow_logs") if one["node_id"] == "start_c"
        )
        assert USER_NAME in log_item(inner_start, "user_info")

    async def test_ac18_open_api_matches_platform_run(self, admin: Flows, tag: str, client):
        """AC-18: the open API returns the parent's output and none of the child's messages."""
        child = await admin.create(
            f"api-child-{tag}",
            chain(
                start("start_c", {"k1": "from-child"}),
                output("output_c", "child says hi"),
                end("end_c", {"a": var_ref("start_c", "k1")}),
            ),
        )
        parent_data = chain(
            start("start_p"),
            subflow("subflow_p", child["id"], outputs=["a"]),
            output("output_p", "parent got {{#subflow_p.a#}}"),
            end("end_p"),
        )
        parent = await admin.create(f"api-parent-{tag}", parent_data)
        assert_resp_200(await admin.set_status(parent, ONLINE))

        headers = auth_headers(admin.token)
        account = assert_resp_200(
            await client.post(
                f"{API_BASE}/service-accounts",
                json={"name": f"{PREFIX}sa-{tag}", "description": "F086 E2E", "resource_owner_user_id": 1},
                headers=headers,
            )
        )
        try:
            key = assert_resp_200(
                await client.post(
                    f"{API_BASE}/service-accounts/{account['id']}/keys",
                    json={"name": f"{PREFIX}key", "scopes": ["workflow:invoke"], "delegate_scopes": []},
                    headers=headers,
                )
            )
            context = assert_resp_200(
                await client.get(f"{API_BASE}/permissions/resources/workflow/{parent['id']}/context", headers=headers)
            )
            assert_resp_200(
                await client.post(
                    f"{API_BASE}/service-accounts/{account['id']}/resource-grants:mutate",
                    params={"resource_type": "workflow", "resource_id": parent["id"]},
                    json={
                        "idempotency_key": f"{PREFIX}{uuid4().hex}",
                        "expected_resource_version": context["resource_version"],
                        "expected_catalog_release_id": context["catalog_release_id"],
                        "changes": [
                            {
                                "op": "ADD",
                                "model_key": "viewer",
                                "subject": {"type": "service_account", "id": str(account["id"])},
                            }
                        ],
                    },
                    headers=headers,
                )
            )

            resp = await client.post(
                f"{API_ORIGIN}/api/v2/workflow/invoke",
                json={"workflow_id": parent["id"], "stream": False},
                headers={"Authorization": f"Bearer {key['plaintext']}"},
                timeout=RUN_TIMEOUT,
            )
            events = assert_resp_200(resp)["events"]
            dumped = json.dumps(events, ensure_ascii=False)
            assert "parent got from-child" in dumped, dumped[:2000]
            assert "child says hi" not in dumped
            assert all(e.get("event") != "error" for e in events), dumped[:2000]
        finally:
            await client.delete(f"{API_BASE}/service-accounts/{account['id']}", headers=headers)
            await admin.set_status(parent, OFFLINE)
