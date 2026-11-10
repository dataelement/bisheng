"""F118 force/repair fixtures, using only real public business APIs.

This suite uses a separate prefixed Child from the ordinary journeys. Cleanup
first removes its exact owned source apps, then uses ordinary target deletion.
It never forces cleanup, rewrites SQL or touches old migration fixtures.
"""

import asyncio
import time

import httpx
import pytest_asyncio

from test.e2e.helpers.f118_cas_creator import CasCreator
from test.e2e.helpers.f118_unification import F118Environment


class ForceEnvironment(F118Environment):
    @property
    def prefix(self):
        return super().prefix + "force-"

    async def prepare(self):
        await super().prepare()
        self.creator_fixture = CasCreator(self, member="owner")
        await self.creator_fixture.install()

    async def cleanup(self):
        # Remove real AS/WF sources, targets and models before their writer's
        # added qualification. A failed business cleanup retains it for audit.
        await super().cleanup()
        if creator := getattr(self, "creator_fixture", None):
            await creator.cleanup()

    async def clean_business_resources(self):
        if self.owner:
            for kind, path, suffix in (
                ("assistant", "/assistant", "assistant"),
                ("workflow", "/workflow/list", "workflow"),
            ):
                name = self.prefix + suffix
                page = await self.ok("GET", path, params={"name": name, "page_size": 200})
                assert not page["has_more"], "refuse incomplete source cleanup"
                exact = [row for row in page["data"] if row["name"] == name]
                assert len(exact) <= 1
                for row in exact:
                    info = await self.ok(
                        "GET", f"/assistant/info/{row['id']}" if kind == "assistant" else f"/flows/{row['id']}"
                    )
                    assert info["user_id"] == self.owner_id and info["tenant_id"] == self.tenant_id
                    if kind == "assistant":
                        await self.ok("POST", "/assistant/delete", params={"assistant_id": row["id"]})
                    else:
                        await self.ok("DELETE", f"/flows/{row['id']}")
        await super().clean_business_resources()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def force_target():
    async with httpx.AsyncClient(timeout=45, trust_env=False, follow_redirects=False) as client:
        environment = ForceEnvironment.from_environment(client)
        try:
            await environment.prepare()
            yield environment
        finally:
            await environment.cleanup()


def knowledge_graph(space_id):
    return {
        "nodes": [
            {
                "id": "canvas-retriever",
                "data": {
                    "id": "retriever",
                    "type": "knowledge_retriever",
                    "group_params": [
                        {
                            "name": "settings",
                            "params": [
                                {
                                    "key": "knowledge",
                                    "value": {"type": "space", "value": [{"key": space_id, "label": "test space"}]},
                                }
                            ],
                        }
                    ],
                },
            }
        ],
        "edges": [],
    }


async def create_sources(target, space_id):
    assistant = await target.ok(
        "POST", "/assistant", json={"name": target.prefix + "assistant", "prompt": "F118 repair test", "logo": ""}
    )
    await save_assistant(target, assistant["id"], space_id)
    response = await target.request(
        "POST",
        "/workflow/create",
        json={"name": target.prefix + "workflow", "flow_type": 10, "data": knowledge_graph(space_id)},
    )
    assert response.status_code == 201 and response.json()["status_code"] == 200
    workflow = response.json()["data"]
    versions = await target.ok("GET", "/workflow/versions", params={"flow_id": workflow["id"]})
    assert len(versions["data"]) == 1
    return assistant["id"], workflow["id"], versions["data"][0]["id"]


async def save_assistant(target, assistant_id, space_id):
    return await target.ok(
        "PUT",
        "/assistant",
        json={
            "id": assistant_id,
            "name": target.prefix + "assistant",
            "prompt": "F118 repair test",
            "model_name": str(target.models[target.model_fixture["chat_model_name"]]["id"]),
            "temperature": 1,
            "knowledge_list": [space_id],
            "tool_list": [],
            "flow_list": [],
        },
    )


async def wait_deletion(target, space_id, command):
    accepted = await target.ok("POST", f"/knowledge/space/{space_id}/deletion/confirm", json=command)
    deadline = time.monotonic() + target.timeout
    while time.monotonic() < deadline:
        state = await target.ok("GET", f"/knowledge/space/{space_id}/deletion/{accepted['job_id']}")
        if state["state"] in {"succeeded", "failed"}:
            assert state["state"] == "succeeded" and state["business_phase"] == "finalized"
            return state
        await asyncio.sleep(1)
    raise AssertionError("force deletion did not reach its actual finalized state")
