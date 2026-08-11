"""Publication and visibility E2E contract for F046.

This suite verifies that staged/pending/parsing files are not formal knowledge
resources and that delete cutover removes a resource from every API read path.
Live writes require ``E2E_F046_ENABLED=1``; worker-backed cases additionally
require ``E2E_F046_ASYNC_ENABLED=1``.  Optional failure and RAG cases state their
extra environment prerequisites in their skip reasons.
"""

from __future__ import annotations

import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE
from test.e2e.helpers.auth import auth_headers
from test.e2e.helpers.f046 import (
    RUN_PREFIX,
    F046TenantEnvironment,
    assert_error,
    assert_success,
    create_space,
    list_children,
    provision_default_tenant,
    put_policy,
    register_upload,
    require_async_workers,
    restore_and_cleanup,
    stage_upload,
    wait_for,
)

pytestmark = pytest.mark.asyncio
HOST = API_BASE.removesuffix("/api/v1")
V2_FILE_LIST = f"{HOST}/api/v2/filelib/file/list"


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(timeout=90.0) as value:
        yield value


@pytest.fixture(scope="module")
async def live_env(client):
    env = await provision_default_tenant(client)
    try:
        yield env
    finally:
        await restore_and_cleanup(client, env)


async def _detail(
    client: httpx.AsyncClient,
    token: str,
    space_id: int,
    request_id: int,
) -> dict:
    return assert_success(
        await client.get(
            f"{API_BASE}/knowledge/space/{space_id}/file-changes/{request_id}",
            headers=auth_headers(token),
        )
    )


async def _batch_approve(
    client: httpx.AsyncClient,
    token: str,
    space_id: int,
    instance_id: int,
) -> dict:
    return assert_success(
        await client.post(
            f"{API_BASE}/knowledge/space/{space_id}/file-changes/batch-approve",
            json={"approval_instance_ids": [instance_id]},
            headers=auth_headers(token),
        )
    )


async def _search_names(
    client: httpx.AsyncClient,
    token: str,
    space_id: int,
    keyword: str,
) -> set[str]:
    data = assert_success(
        await client.get(
            f"{API_BASE}/knowledge/space/{space_id}/search",
            params={"keyword": keyword, "page": 1, "page_size": 100},
            headers=auth_headers(token),
        )
    )
    items = data.get("data", []) if isinstance(data, dict) else []
    return {str(item.get("file_name") or item.get("name") or "") for item in items}


async def _v2_names(
    client: httpx.AsyncClient,
    space_id: int,
    keyword: str | None = None,
) -> set[str]:
    params: dict[str, object] = {"knowledge_id": space_id, "page_size": 100}
    if keyword:
        params["keyword"] = keyword
    data = assert_success(await client.get(V2_FILE_LIST, params=params))
    return {str(item.get("file_name") or item.get("name") or "") for item in data.get("data", [])}


async def _cleanup_upload_request(
    client: httpx.AsyncClient,
    token: str,
    space_id: int,
    request_id: int,
) -> None:
    assert_success(
        await client.delete(
            f"{API_BASE}/knowledge/space/{space_id}/file-changes/{request_id}",
            headers=auth_headers(token),
        )
    )


class TestE2EF046FileChangeVisibility:
    """F046 visibility: upload publication guard and delete cutover guard."""

    async def test_ac13_ac14_pending_upload_hidden_and_preview_stakeholder_only(
        self,
        client,
        live_env: F046TenantEnvironment,
    ):
        """AC-13/14/33/51: pending upload absent from formal reads; preview allow/deny."""
        await put_policy(client, live_env.admin_token, enabled=True, scope="all_spaces")
        viewer_grant = {
            "subject_type": "user",
            "subject_id": live_env.viewer.user_id,
            "relation": "viewer",
            "include_children": False,
        }
        space = await create_space(
            client,
            live_env,
            "pending-visibility",
            extra_grants=[viewer_grant],
        )
        space_id = int(space["id"])
        file_name = f"{RUN_PREFIX}pending-secret.txt"
        stage = await stage_upload(
            client,
            live_env.editor.token,
            space_id,
            file_name,
            b"F046 pending content must never enter formal retrieval",
        )
        pending = await register_upload(
            client,
            live_env.editor.token,
            space_id,
            stage["upload_id"],
        )
        assert pending["decision"] == "pending"

        assert file_name not in {
            str(item.get("file_name") or "") for item in await list_children(client, live_env.editor.token, space_id)
        }
        assert file_name not in await _search_names(
            client,
            live_env.editor.token,
            space_id,
            "pending-secret",
        )
        assert file_name not in await _v2_names(client, space_id, "pending-secret")

        request_id = int(pending["change_request_id"])
        applicant_preview = assert_success(
            await client.get(
                f"{API_BASE}/knowledge/space/{space_id}/file-changes/{request_id}/preview",
                headers=auth_headers(live_env.editor.token),
            )
        )
        approver_preview = assert_success(
            await client.get(
                f"{API_BASE}/knowledge/space/{space_id}/file-changes/{request_id}/preview",
                headers=auth_headers(live_env.manager.token),
            )
        )
        assert applicant_preview
        assert approver_preview
        ordinary_preview = await client.get(
            f"{API_BASE}/knowledge/space/{space_id}/file-changes/{request_id}/preview",
            headers=auth_headers(live_env.viewer.token),
        )
        assert_error(ordinary_preview, 18073)

        detail = await _detail(client, live_env.manager.token, space_id, request_id)
        assert detail["action"] == "upload"
        assert detail["resource_name"] == file_name
        assert detail["can_approve"] is True
        assert "object_name" not in detail
        await _cleanup_upload_request(client, live_env.editor.token, space_id, request_id)

    async def test_ac13_rag_and_citation_stream_do_not_reveal_pending_content(
        self,
        client,
        live_env: F046TenantEnvironment,
    ):
        """AC-13: RAG/citation SSE contains neither pending filename nor unique content."""
        model_id = os.environ.get("E2E_F046_MODEL_ID")
        if not model_id:
            pytest.skip("set E2E_F046_MODEL_ID for live RAG/citation SSE coverage")
        await put_policy(client, live_env.admin_token, enabled=True, scope="all_spaces")
        space = await create_space(client, live_env, "pending-rag")
        space_id = int(space["id"])
        file_name = f"{RUN_PREFIX}rag-hidden.txt"
        hidden_marker = f"f046-hidden-{RUN_PREFIX}"
        stage = await stage_upload(
            client,
            live_env.editor.token,
            space_id,
            file_name,
            hidden_marker.encode(),
        )
        pending = await register_upload(
            client,
            live_env.editor.token,
            space_id,
            stage["upload_id"],
        )
        session = assert_success(
            await client.post(
                f"{API_BASE}/knowledge/space/{space_id}/chat/folder/session",
                json={"folder_id": 0},
                headers=auth_headers(live_env.editor.token),
            )
        )
        chat_id = session.get("chat_id") or session.get("id")
        assert chat_id, session
        response = await client.post(
            f"{API_BASE}/knowledge/space/{space_id}/chat/folder",
            json={
                "folder_id": 0,
                "chat_id": str(chat_id),
                "query": "Summarize the exact contents of all available files.",
                "modelId": int(model_id),
                "tags": [],
            },
            headers=auth_headers(live_env.editor.token),
        )
        assert response.status_code == 200, response.text[:500]
        assert response.headers.get("content-type", "").startswith("text/event-stream")
        assert file_name not in response.text
        assert hidden_marker not in response.text
        await _cleanup_upload_request(
            client,
            live_env.editor.token,
            space_id,
            int(pending["change_request_id"]),
        )

    async def test_ac15_ac16_ac19_approved_upload_publishes_only_after_ingest(
        self,
        client,
        live_env: F046TenantEnvironment,
    ):
        """AC-15/16/19: non-published states stay hidden; SUCCESS publishes; changed content reapplies."""
        require_async_workers()
        await put_policy(client, live_env.admin_token, enabled=True, scope="all_spaces")
        space = await create_space(client, live_env, "publish-lifecycle")
        space_id = int(space["id"])
        file_name = f"{RUN_PREFIX}publish.txt"
        stage = await stage_upload(
            client,
            live_env.editor.token,
            space_id,
            file_name,
            b"F046 published content version one",
        )
        pending = await register_upload(
            client,
            live_env.editor.token,
            space_id,
            stage["upload_id"],
        )
        approved = await _batch_approve(
            client,
            live_env.manager.token,
            space_id,
            int(pending["approval_instance_id"]),
        )
        assert approved["successCount"] == 1

        observed_nonpublished: list[str] = []

        async def probe():
            detail = await _detail(
                client,
                live_env.editor.token,
                space_id,
                int(pending["change_request_id"]),
            )
            if detail["status"] != "published":
                observed_nonpublished.append(detail["status"])
                names = {
                    str(item.get("file_name") or "")
                    for item in await list_children(client, live_env.editor.token, space_id)
                }
                assert file_name not in names
                assert file_name not in await _v2_names(client, space_id, "publish")
            return detail

        published = await wait_for(
            probe,
            lambda value: (
                isinstance(value, dict) and value.get("status") in {"published", "parse_failed", "execute_failed"}
            ),
            description="approved upload to publish or fail explicitly",
            timeout=180.0,
        )
        assert published["status"] == "published", published
        assert published["resource_id"]
        assert file_name in {
            str(item.get("file_name") or "") for item in await list_children(client, live_env.editor.token, space_id)
        }
        assert file_name in await _search_names(
            client,
            live_env.editor.token,
            space_id,
            "publish",
        )
        assert file_name in await _v2_names(client, space_id, "publish")

        changed = await stage_upload(
            client,
            live_env.editor.token,
            space_id,
            file_name,
            b"F046 published content version two is a distinct body",
        )
        assert changed["upload_id"] != stage["upload_id"]
        changed_request = await register_upload(
            client,
            live_env.editor.token,
            space_id,
            changed["upload_id"],
        )
        assert changed_request["decision"] == "pending"
        assert changed_request["change_request_id"] != pending["change_request_id"]
        await _cleanup_upload_request(
            client,
            live_env.editor.token,
            space_id,
            int(changed_request["change_request_id"]),
        )

    async def test_ac17_ac18_parse_failure_retry_reuses_original_approval(
        self,
        client,
        live_env: F046TenantEnvironment,
    ):
        """AC-17/18/32: deterministic parse failure is visible; retry keeps instance/request IDs."""
        require_async_workers()
        if os.environ.get("E2E_F046_PARSE_FAILURE_ENABLED") != "1":
            pytest.skip(
                "set E2E_F046_PARSE_FAILURE_ENABLED=1 in an environment configured to reject E2E_F046_FAILURE_EXTENSION"
            )
        extension = os.environ.get("E2E_F046_FAILURE_EXTENSION", "invalid")
        await put_policy(client, live_env.admin_token, enabled=True, scope="all_spaces")
        space = await create_space(client, live_env, "parse-failure")
        space_id = int(space["id"])
        stage = await stage_upload(
            client,
            live_env.editor.token,
            space_id,
            f"{RUN_PREFIX}parse-failure.{extension}",
            b"content deliberately unsupported by the configured parser",
        )
        pending = await register_upload(
            client,
            live_env.editor.token,
            space_id,
            stage["upload_id"],
        )
        await _batch_approve(
            client,
            live_env.manager.token,
            space_id,
            int(pending["approval_instance_id"]),
        )
        failed = await wait_for(
            lambda: _detail(
                client,
                live_env.editor.token,
                space_id,
                int(pending["change_request_id"]),
            ),
            lambda value: (
                isinstance(value, dict) and value.get("status") in {"parse_failed", "execute_failed", "published"}
            ),
            description="configured parser failure",
            timeout=180.0,
        )
        assert failed["status"] in {"parse_failed", "execute_failed"}, failed
        assert failed["failure_reason"]

        retried = assert_success(
            await client.post(
                f"{API_BASE}/knowledge/space/{space_id}/file-changes/{pending['change_request_id']}/retry-ingest",
                headers=auth_headers(live_env.editor.token),
            )
        )
        assert retried["request_id"] == pending["change_request_id"]
        assert retried["approval_instance_id"] == pending["approval_instance_id"]
        assert retried["status"] in {"approved", "executing", "parsing"}
        failed_again = await wait_for(
            lambda: _detail(
                client,
                live_env.editor.token,
                space_id,
                int(pending["change_request_id"]),
            ),
            lambda value: (
                isinstance(value, dict) and value.get("status") in {"parse_failed", "execute_failed", "published"}
            ),
            description="retried configured parser failure",
            timeout=180.0,
        )
        assert failed_again["status"] in {"parse_failed", "execute_failed"}, failed_again
        await _cleanup_upload_request(
            client,
            live_env.editor.token,
            space_id,
            int(pending["change_request_id"]),
        )

    async def test_ac22_to_ac24_ac47_delete_cutover_all_read_paths_and_preview(
        self,
        client,
        live_env: F046TenantEnvironment,
    ):
        """AC-22~24/47: delete is visible before cutover and absent everywhere after execution."""
        require_async_workers()
        await put_policy(client, live_env.admin_token, enabled=True, scope="all_spaces")
        space = await create_space(client, live_env, "delete-cutover")
        space_id = int(space["id"])
        file_name = f"{RUN_PREFIX}delete-me.txt"
        stage = await stage_upload(
            client,
            live_env.admin_token,
            space_id,
            file_name,
            b"F046 file remains available until delete cutover",
        )
        direct = await register_upload(
            client,
            live_env.admin_token,
            space_id,
            stage["upload_id"],
        )
        assert direct["decision"] == "direct"
        file_id = int(direct["resource"]["id"])

        await wait_for(
            lambda: list_children(client, live_env.admin_token, space_id),
            lambda value: (
                isinstance(value, list)
                and any(int(item.get("id", 0)) == file_id and int(item.get("status", 0)) == 2 for item in value)
            ),
            description="direct upload to finish parsing",
            timeout=180.0,
        )
        pending = assert_success(
            await client.delete(
                f"{API_BASE}/knowledge/space/{space_id}/files/{file_id}",
                headers=auth_headers(live_env.editor.token),
            )
        )
        assert pending["decision"] == "pending"
        assert any(
            int(item.get("id", 0)) == file_id for item in await list_children(client, live_env.editor.token, space_id)
        )
        assert file_name in await _search_names(
            client,
            live_env.editor.token,
            space_id,
            "delete-me",
        )
        assert file_name in await _v2_names(client, space_id, "delete-me")
        assert_success(
            await client.get(
                f"{API_BASE}/knowledge/space/{space_id}/files/{file_id}/preview",
                headers=auth_headers(live_env.editor.token),
            )
        )

        await _batch_approve(
            client,
            live_env.manager.token,
            space_id,
            int(pending["approval_instance_id"]),
        )
        final = await wait_for(
            lambda: _detail(
                client,
                live_env.editor.token,
                space_id,
                int(pending["change_request_id"]),
            ),
            lambda value: isinstance(value, dict) and value.get("status") in {"executed", "execute_failed"},
            description="delete visibility cutover",
            timeout=180.0,
        )
        assert final["status"] == "executed", final
        assert all(
            int(item.get("id", 0)) != file_id for item in await list_children(client, live_env.editor.token, space_id)
        )
        assert file_name not in await _search_names(
            client,
            live_env.editor.token,
            space_id,
            "delete-me",
        )
        assert file_name not in await _v2_names(client, space_id, "delete-me")
        preview = await client.get(
            f"{API_BASE}/knowledge/space/{space_id}/files/{file_id}/preview",
            headers=auth_headers(live_env.editor.token),
        )
        assert_error(preview, 18020)
