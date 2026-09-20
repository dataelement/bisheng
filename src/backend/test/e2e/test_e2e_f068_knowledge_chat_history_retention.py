"""E2E coverage for F068 knowledge-chat history retention.

Prerequisites:
- API and knowledge Celery worker run the current branch.
- ``E2E_F068_TOKEN`` is a JWT for a user in a dedicated disposable tenant.
- ``E2E_API_BASE`` points at that API (default: http://localhost:7860/api/v1).

The suite creates only ``e2e-f068-*`` spaces, performs setup and teardown
cleanup by that prefix, and never deletes unrelated data.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers

PREFIX = "e2e-f068-"


async def _cleanup_spaces(client: httpx.AsyncClient, token: str) -> None:
    response = await client.get(f"{API_BASE}/knowledge/space/mine", headers=auth_headers(token))
    if response.status_code != 200 or response.json().get("status_code") != 200:
        return
    spaces = response.json().get("data") or []
    for space in spaces:
        if str(space.get("name", "")).startswith(PREFIX):
            await client.delete(
                f"{API_BASE}/knowledge/space/{space['id']}",
                headers=auth_headers(token),
            )


async def _create_space(client: httpx.AsyncClient, token: str, suffix: str) -> dict:
    response = await client.post(
        f"{API_BASE}/knowledge/space",
        json={"name": f"{PREFIX}{suffix}", "description": "F068 E2E"},
        headers=auth_headers(token),
    )
    return assert_resp_200(response)


async def _create_folder(
    client: httpx.AsyncClient,
    token: str,
    space_id: int,
    suffix: str,
    parent_id: int | None = None,
) -> dict:
    response = await client.post(
        f"{API_BASE}/knowledge/space/{space_id}/folders",
        json={"name": f"{PREFIX}{suffix}", "parent_id": parent_id},
        headers=auth_headers(token),
    )
    return assert_resp_200(response)


async def _create_folder_session(
    client: httpx.AsyncClient,
    token: str,
    space_id: int,
    folder_id: int,
) -> dict:
    response = await client.post(
        f"{API_BASE}/knowledge/space/{space_id}/chat/folder/session",
        json={"folder_id": folder_id},
        headers=auth_headers(token),
    )
    return assert_resp_200(response)


async def _list_sessions(
    client: httpx.AsyncClient,
    token: str,
    space_id: int,
    folder_id: int,
) -> list[dict]:
    response = await client.get(
        f"{API_BASE}/knowledge/space/{space_id}/chat/folder/session",
        params={"folder_id": folder_id},
        headers=auth_headers(token),
    )
    return assert_resp_200(response)


async def _wait_for_session_at_root(
    client: httpx.AsyncClient,
    token: str,
    space_id: int,
    chat_id: str,
) -> dict:
    for _ in range(30):
        sessions = await _list_sessions(client, token, space_id, 0)
        matched = [session for session in sessions if session["chat_id"] == chat_id]
        if matched:
            return matched[0]
        await asyncio.sleep(1)
    pytest.fail(f"chat {chat_id[:3]}... was not recovered to source root within 30 seconds")


@pytest.fixture(scope="module")
def f068_token() -> str:
    token = os.environ.get("E2E_F068_TOKEN", "").strip()
    if not token:
        pytest.skip("E2E_F068_TOKEN is required and must belong to a disposable test tenant")
    return token


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(timeout=45) as value:
        yield value


@pytest.fixture(scope="module", autouse=True)
async def isolated_f068_data(client: httpx.AsyncClient, f068_token: str):
    await _cleanup_spaces(client, f068_token)
    yield
    await _cleanup_spaces(client, f068_token)


class TestE2EF068KnowledgeChatHistoryRetention:
    async def test_ac02_ac04_ac10_delete_folder_recovers_session_once(
        self,
        client: httpx.AsyncClient,
        f068_token: str,
    ):
        """AC-02/04/10/15: committed folder delete eventually exposes one source-root session."""
        space = await _create_space(client, f068_token, "delete-folder")
        folder = await _create_folder(client, f068_token, space["id"], "deleted")
        chat = await _create_folder_session(client, f068_token, space["id"], folder["id"])

        assert chat["flow_id"] == f"space_{space['id']}_folder_{folder['id']}"
        assert "entry_flow_id" not in chat
        assert_resp_200(
            await client.delete(
                f"{API_BASE}/knowledge/space/{space['id']}/folders/{folder['id']}",
                headers=auth_headers(f068_token),
            )
        )

        recovered = await _wait_for_session_at_root(client, f068_token, space["id"], chat["chat_id"])
        root_sessions = await _list_sessions(client, f068_token, space["id"], 0)
        assert sum(session["chat_id"] == chat["chat_id"] for session in root_sessions) == 1
        assert recovered["flow_id"] == chat["flow_id"]
        assert "entry_flow_id" not in recovered

    async def test_ac05_ac07_cross_space_move_keeps_history_only_in_source_root(
        self,
        client: httpx.AsyncClient,
        f068_token: str,
    ):
        """AC-05/06/07/18: cross-space move recovers source history without target leakage."""
        source = await _create_space(client, f068_token, "move-source")
        target = await _create_space(client, f068_token, "move-target")
        folder = await _create_folder(client, f068_token, source["id"], "moved")
        chat = await _create_folder_session(client, f068_token, source["id"], folder["id"])

        move_response = await client.post(
            f"{API_BASE}/knowledge/space/{source['id']}/files/move",
            json={
                "items": [{"id": folder["id"], "type": "folder"}],
                "target_space_id": target["id"],
                "target_folder_id": None,
                "skip_invalid": False,
            },
            headers=auth_headers(f068_token),
        )
        moved = assert_resp_200(move_response)
        assert moved["moved"] and not moved["invalid"]

        await _wait_for_session_at_root(client, f068_token, source["id"], chat["chat_id"])
        target_sessions = await _list_sessions(client, f068_token, target["id"], 0)
        assert all(session["chat_id"] != chat["chat_id"] for session in target_sessions)

    async def test_ac08_same_space_move_does_not_rehome_folder_session(
        self,
        client: httpx.AsyncClient,
        f068_token: str,
    ):
        """AC-08: same-space move keeps the session on its folder entry."""
        space = await _create_space(client, f068_token, "same-space")
        parent = await _create_folder(client, f068_token, space["id"], "parent")
        child = await _create_folder(client, f068_token, space["id"], "child")
        chat = await _create_folder_session(client, f068_token, space["id"], child["id"])

        assert_resp_200(
            await client.post(
                f"{API_BASE}/knowledge/space/{space['id']}/files/move",
                json={
                    "items": [{"id": child["id"], "type": "folder"}],
                    "target_space_id": space["id"],
                    "target_folder_id": parent["id"],
                    "skip_invalid": False,
                },
                headers=auth_headers(f068_token),
            )
        )
        await asyncio.sleep(7)
        folder_sessions = await _list_sessions(client, f068_token, space["id"], child["id"])
        root_sessions = await _list_sessions(client, f068_token, space["id"], 0)
        assert any(session["chat_id"] == chat["chat_id"] for session in folder_sessions)
        assert all(session["chat_id"] != chat["chat_id"] for session in root_sessions)

    async def test_ac22_deleted_session_is_not_recovered(
        self,
        client: httpx.AsyncClient,
        f068_token: str,
    ):
        """AC-22: a user-deleted session remains absent after its folder is deleted."""
        space = await _create_space(client, f068_token, "soft-delete")
        folder = await _create_folder(client, f068_token, space["id"], "soft-delete-folder")
        chat = await _create_folder_session(client, f068_token, space["id"], folder["id"])
        delete_session = await client.request(
            "DELETE",
            f"{API_BASE}/knowledge/space/{space['id']}/chat/folder/session",
            json={"folder_id": folder["id"], "chat_id": chat["chat_id"]},
            headers=auth_headers(f068_token),
        )
        assert_resp_200(delete_session)
        assert_resp_200(
            await client.delete(
                f"{API_BASE}/knowledge/space/{space['id']}/folders/{folder['id']}",
                headers=auth_headers(f068_token),
            )
        )
        await asyncio.sleep(7)
        root_sessions = await _list_sessions(client, f068_token, space["id"], 0)
        assert all(session["chat_id"] != chat["chat_id"] for session in root_sessions)
