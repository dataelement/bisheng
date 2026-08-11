"""API E2E contract for F046 knowledge-space file-change approval.

Prerequisites:
- A live backend with MySQL, Redis, MinIO and OpenFGA.
- ``E2E_F046_ENABLED=1`` (explicit opt-in for prefix-scoped writes).
- ``E2E_F046_ASYNC_ENABLED=1`` for assertions that wait for Celery execution.
- Tenant-B credentials for the dual-tenant test (see that test's skip reason).

The module performs strict cleanup for its process-unique
``e2e-f046-<run-id>-`` prefix before and after the suite.  It never deletes a
resource whose name lacks that exact run prefix.
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
    authorize_space,
    create_folder,
    create_space,
    get_policy,
    list_children,
    optional_tenant_b_token,
    provision_default_tenant,
    put_policy,
    register_upload,
    require_async_workers,
    restore_and_cleanup,
    rows,
    stage_upload,
    tenant_id_from_token,
    wait_for,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(timeout=60.0) as value:
        yield value


@pytest.fixture(scope="module")
async def live_env(client):
    env = await provision_default_tenant(client)
    try:
        yield env
    finally:
        await restore_and_cleanup(client, env)


async def _put_setting(
    client: httpx.AsyncClient,
    token: str,
    space_id: int,
    required: bool,
) -> dict:
    return assert_success(
        await client.put(
            f"{API_BASE}/knowledge/space/admin/file-change-settings/{space_id}",
            json={"approval_required": required},
            headers=auth_headers(token),
        )
    )


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


async def _withdraw(
    client: httpx.AsyncClient,
    token: str,
    instance_id: int,
) -> dict:
    return assert_success(
        await client.post(
            f"{API_BASE}/approval/instances/{instance_id}/withdraw",
            json={"reason": "F046 E2E prefix-scoped teardown"},
            headers=auth_headers(token),
        )
    )


async def _cleanup_upload_request(
    client: httpx.AsyncClient,
    token: str,
    space_id: int,
    request_id: int,
) -> dict:
    return assert_success(
        await client.delete(
            f"{API_BASE}/knowledge/space/{space_id}/file-changes/{request_id}",
            headers=auth_headers(token),
        )
    )


async def _task_id_for_instance(
    client: httpx.AsyncClient,
    token: str,
    instance_id: int,
) -> int:
    data = assert_success(
        await client.get(
            f"{API_BASE}/approval/my-tasks",
            headers=auth_headers(token),
        )
    )
    task = next(
        (
            item
            for item in rows(data)
            if int(item.get("instance_id", 0)) == instance_id and item.get("status") == "pending"
        ),
        None,
    )
    assert task is not None, {"instance_id": instance_id, "tasks": data}
    return int(task["task_id"])


async def _reject(
    client: httpx.AsyncClient,
    token: str,
    instance_id: int,
) -> None:
    task_id = await _task_id_for_instance(client, token, instance_id)
    assert_success(
        await client.post(
            f"{API_BASE}/approval/tasks/{task_id}/decision",
            json={"action": "reject", "comment": "F046 E2E rejection"},
            headers=auth_headers(token),
        )
    )


class TestE2EF046FileChangeApproval:
    """F046 main path: policy, roles, four actions, conflicts and decisions."""

    async def test_ac01_to_ac07_policy_save_restore_and_per_space_default(
        self,
        client,
        live_env: F046TenantEnvironment,
    ):
        """AC-01~07: current-tenant policy, save failure, retained setting and default."""
        space = await create_space(client, live_env, "policy")
        space_id = int(space["id"])

        default_policy = await put_policy(
            client,
            live_env.admin_token,
            enabled=True,
            scope="per_space",
        )
        assert default_policy == {"enabled": True, "scope": "per_space"}
        settings = assert_success(
            await client.get(
                f"{API_BASE}/knowledge/space/admin/file-change-settings",
                params={"keyword": RUN_PREFIX, "page": 1, "page_size": 20},
                headers=auth_headers(live_env.admin_token),
            )
        )
        row = next(item for item in settings["data"] if int(item["space_id"]) == space_id)
        assert row["approval_required"] is True
        assert row["effective_required"] is True

        saved = await _put_setting(client, live_env.admin_token, space_id, False)
        assert saved["approval_required"] is False
        assert saved["effective_required"] is False
        no_review_folder = await create_folder(
            client,
            live_env.admin_token,
            space_id,
            f"{RUN_PREFIX}no-review-old",
        )
        direct_editor_change = assert_success(
            await client.put(
                f"{API_BASE}/knowledge/space/{space_id}/folders/{no_review_folder['id']}",
                json={"name": f"{RUN_PREFIX}no-review-new"},
                headers=auth_headers(live_env.editor.token),
            )
        )
        assert direct_editor_change["decision"] == "direct"
        assert direct_editor_change["approval_instance_id"] is None

        # Pydantic rejects this request before the service is entered. FastAPI's
        # framework 422 is the only non-UnifiedResponseModel response in this
        # suite; the GET proves the effective policy was not mutated (AC-04).
        rejected = await client.put(
            f"{API_BASE}/knowledge/space/admin/file-change-policy",
            json={"enabled": False, "scope": "not-a-scope"},
            headers=auth_headers(live_env.admin_token),
        )
        assert rejected.status_code == 422, rejected.text
        assert await get_policy(client, live_env.admin_token) == default_policy

        await put_policy(client, live_env.admin_token, enabled=False, scope="all_spaces")
        await put_policy(client, live_env.admin_token, enabled=True, scope="per_space")
        retained = assert_success(
            await client.get(
                f"{API_BASE}/knowledge/space/admin/file-change-settings",
                params={"keyword": RUN_PREFIX, "page": 1, "page_size": 20},
                headers=auth_headers(live_env.admin_token),
            )
        )
        retained_row = next(item for item in retained["data"] if int(item["space_id"]) == space_id)
        assert retained_row["approval_required"] is False
        assert retained_row["effective_required"] is False

    async def test_ac08_to_ac14_direct_pending_allow_deny_and_upload_cleanup(
        self,
        client,
        live_env: F046TenantEnvironment,
    ):
        """AC-08~14/20/21/27/28/40: owner-manager direct; editor pending; viewer denied."""
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
            "upload-gate",
            extra_grants=[viewer_grant],
        )
        space_id = int(space["id"])

        owner_stage = await stage_upload(
            client,
            live_env.admin_token,
            space_id,
            f"{RUN_PREFIX}owner.txt",
            b"owner direct F046 E2E",
        )
        owner_result = await register_upload(
            client,
            live_env.admin_token,
            space_id,
            owner_stage["upload_id"],
        )
        assert owner_result["decision"] == "direct"
        assert owner_result["resource"] is not None

        manager_stage = await stage_upload(
            client,
            live_env.manager.token,
            space_id,
            f"{RUN_PREFIX}manager.txt",
            b"manager direct F046 E2E",
        )
        manager_result = await register_upload(
            client,
            live_env.manager.token,
            space_id,
            manager_stage["upload_id"],
        )
        assert manager_result["decision"] == "direct"

        denied = await client.post(
            f"{API_BASE}/knowledge/upload/{space_id}",
            files={"file": (f"{RUN_PREFIX}denied.txt", b"denied", "text/plain")},
            headers=auth_headers(live_env.viewer.token),
        )
        assert_error(denied, 18040)

        editor_stage = await stage_upload(
            client,
            live_env.editor.token,
            space_id,
            f"{RUN_PREFIX}pending.txt",
            b"editor pending F046 E2E",
        )
        editor_result = await register_upload(
            client,
            live_env.editor.token,
            space_id,
            editor_stage["upload_id"],
        )
        assert editor_result["decision"] == "pending"
        assert editor_result["resource"] is None
        assert editor_result["approval_instance_id"]
        assert editor_result["change_request_id"]

        applicant_uploads = assert_success(
            await client.get(
                f"{API_BASE}/knowledge/space/{space_id}/file-changes/uploads",
                params={"status": "pending", "page_size": 20},
                headers=auth_headers(live_env.editor.token),
            )
        )
        pending = next(
            item
            for item in applicant_uploads["data"]
            if int(item["request_id"]) == int(editor_result["change_request_id"])
        )
        assert pending["file_name"] == f"{RUN_PREFIX}pending.txt"
        assert "object_name" not in pending

        owner_uploads = assert_success(
            await client.get(
                f"{API_BASE}/knowledge/space/{space_id}/file-changes/uploads",
                params={"status": "pending", "page_size": 20},
                headers=auth_headers(live_env.admin_token),
            )
        )
        owner_view = next(
            item for item in owner_uploads["data"] if int(item["request_id"]) == int(editor_result["change_request_id"])
        )
        assert owner_view["can_approve"] is True

        # Policy changes only affect later mutations; the existing instance is
        # neither auto-approved nor cancelled (AC-07).
        await put_policy(client, live_env.admin_token, enabled=False, scope="all_spaces")
        existing = await _detail(
            client,
            live_env.editor.token,
            space_id,
            int(editor_result["change_request_id"]),
        )
        assert existing["status"] == "pending"

        viewer_uploads = assert_success(
            await client.get(
                f"{API_BASE}/knowledge/space/{space_id}/file-changes/uploads",
                params={"page_size": 20},
                headers=auth_headers(live_env.viewer.token),
            )
        )
        assert all(
            int(item["request_id"]) != int(editor_result["change_request_id"]) for item in viewer_uploads["data"]
        )

        cleaned = assert_success(
            await client.delete(
                f"{API_BASE}/knowledge/space/{space_id}/file-changes/{editor_result['change_request_id']}",
                headers=auth_headers(live_env.editor.token),
            )
        )
        assert cleaned["status"] in {"withdrawn", "cancelled"}
        names = {item.get("file_name") for item in await list_children(client, live_env.admin_token, space_id)}
        assert f"{RUN_PREFIX}pending.txt" not in names

        await put_policy(client, live_env.admin_token, enabled=True, scope="all_spaces")
        folder_stage = await stage_upload(
            client,
            live_env.editor.token,
            space_id,
            f"{RUN_PREFIX}folder-upload.txt",
            b"folder upload is staged per file",
        )
        folder_upload = assert_success(
            await client.post(
                f"{API_BASE}/knowledge/space/{space_id}/folders/upload",
                json={
                    "parent_id": None,
                    "items": [
                        {
                            "upload_id": folder_stage["upload_id"],
                            "relative_path": f"{RUN_PREFIX}tree/sub/folder-upload.txt",
                        }
                    ],
                },
                headers=auth_headers(live_env.editor.token),
            )
        )
        assert len(folder_upload) == 1
        assert folder_upload[0]["decision"] == "pending"
        folder_detail = await _detail(
            client,
            live_env.editor.token,
            space_id,
            int(folder_upload[0]["change_request_id"]),
        )
        assert folder_detail["action_detail"]["relative_path"].endswith("sub/folder-upload.txt")
        assert all(
            item.get("file_name") != f"{RUN_PREFIX}tree"
            for item in await list_children(client, live_env.editor.token, space_id)
        )
        await _cleanup_upload_request(
            client,
            live_env.editor.token,
            space_id,
            int(folder_upload[0]["change_request_id"]),
        )

        rejected_stage = await stage_upload(
            client,
            live_env.editor.token,
            space_id,
            f"{RUN_PREFIX}rejected-upload.txt",
            b"rejected staged upload must not become a formal file",
        )
        rejected_upload = await register_upload(
            client,
            live_env.editor.token,
            space_id,
            rejected_stage["upload_id"],
        )
        await _reject(
            client,
            live_env.manager.token,
            int(rejected_upload["approval_instance_id"]),
        )
        rejected_detail = await _detail(
            client,
            live_env.editor.token,
            space_id,
            int(rejected_upload["change_request_id"]),
        )
        assert rejected_detail["status"] == "rejected"
        await _cleanup_upload_request(
            client,
            live_env.editor.token,
            space_id,
            int(rejected_upload["change_request_id"]),
        )

    async def test_ac22_to_ac32_ac43_to_ac52_four_actions_and_subtree_conflict(
        self,
        client,
        live_env: F046TenantEnvironment,
    ):
        """AC-22~32/43~52: old state persists; root lock; four-action item results."""
        await put_policy(client, live_env.admin_token, enabled=True, scope="all_spaces")
        space = await create_space(client, live_env, "mutations")
        space_id = int(space["id"])
        root = await create_folder(
            client,
            live_env.admin_token,
            space_id,
            f"{RUN_PREFIX}root-old",
        )
        child = await create_folder(
            client,
            live_env.admin_token,
            space_id,
            f"{RUN_PREFIX}child",
            parent_id=int(root["id"]),
        )
        target = await create_folder(
            client,
            live_env.admin_token,
            space_id,
            f"{RUN_PREFIX}target",
        )

        rename = assert_success(
            await client.put(
                f"{API_BASE}/knowledge/space/{space_id}/folders/{root['id']}",
                json={"name": f"{RUN_PREFIX}root-new"},
                headers=auth_headers(live_env.editor.token),
            )
        )
        assert rename["decision"] == "pending"
        assert any(
            item.get("file_name") == f"{RUN_PREFIX}root-old"
            for item in await list_children(client, live_env.editor.token, space_id)
        )
        detail = await _detail(
            client,
            live_env.editor.token,
            space_id,
            int(rename["change_request_id"]),
        )
        assert detail["action"] == "rename"
        assert detail["action_detail"]["old_name"] == f"{RUN_PREFIX}root-old"
        assert detail["action_detail"]["new_name"] == f"{RUN_PREFIX}root-new"

        conflict = await client.delete(
            f"{API_BASE}/knowledge/space/{space_id}/folders/{child['id']}",
            headers=auth_headers(live_env.editor.token),
        )
        assert_error(conflict, 18072)
        await _withdraw(client, live_env.editor.token, int(rename["approval_instance_id"]))

        move = assert_success(
            await client.post(
                f"{API_BASE}/knowledge/space/{space_id}/files/move",
                json={
                    "items": [{"id": root["id"], "type": "folder"}],
                    "target_space_id": space_id,
                    "target_folder_id": target["id"],
                },
                headers=auth_headers(live_env.editor.token),
            )
        )
        assert move["moved"] == []
        assert len(move["pending"]) == 1
        assert any(
            int(item["id"]) == int(root["id"]) for item in await list_children(client, live_env.editor.token, space_id)
        )
        await _withdraw(
            client,
            live_env.editor.token,
            int(move["pending"][0]["approval_instance_id"]),
        )

        delete = assert_success(
            await client.delete(
                f"{API_BASE}/knowledge/space/{space_id}/folders/{root['id']}",
                headers=auth_headers(live_env.editor.token),
            )
        )
        assert delete["decision"] == "pending"
        assert any(
            int(item["id"]) == int(root["id"]) for item in await list_children(client, live_env.editor.token, space_id)
        )
        await _reject(
            client,
            live_env.manager.token,
            int(delete["approval_instance_id"]),
        )
        rejected = await _detail(
            client,
            live_env.editor.token,
            space_id,
            int(delete["change_request_id"]),
        )
        assert rejected["status"] == "rejected"
        assert any(
            int(item["id"]) == int(root["id"]) for item in await list_children(client, live_env.editor.token, space_id)
        )

        first = await create_folder(
            client,
            live_env.admin_token,
            space_id,
            f"{RUN_PREFIX}batch-first",
        )
        second = await create_folder(
            client,
            live_env.admin_token,
            space_id,
            f"{RUN_PREFIX}batch-second",
        )
        lock_first = assert_success(
            await client.put(
                f"{API_BASE}/knowledge/space/{space_id}/folders/{first['id']}",
                json={"name": f"{RUN_PREFIX}batch-first-new"},
                headers=auth_headers(live_env.editor.token),
            )
        )
        batch_delete = assert_success(
            await client.post(
                f"{API_BASE}/knowledge/space/{space_id}/files/batch-delete",
                json={"file_ids": [], "folder_ids": [first["id"], second["id"]]},
                headers=auth_headers(live_env.editor.token),
            )
        )
        assert [int(item["id"]) for item in batch_delete["invalid"]] == [int(first["id"])]
        assert batch_delete["invalid"][0]["error_code"] == 18072
        assert [int(item["id"]) for item in batch_delete["pending"]] == [int(second["id"])]
        await _withdraw(client, live_env.editor.token, int(lock_first["approval_instance_id"]))
        await _withdraw(
            client,
            live_env.editor.token,
            int(batch_delete["pending"][0]["approval_instance_id"]),
        )

        rename_targets = [
            await create_folder(
                client,
                live_env.admin_token,
                space_id,
                f"{RUN_PREFIX}batch-rename-{index}",
            )
            for index in range(2)
        ]
        batch_rename = assert_success(
            await client.post(
                f"{API_BASE}/knowledge/space/{space_id}/files/batch-rename",
                json={
                    "items": [
                        {
                            "id": item["id"],
                            "type": "folder",
                            "name": f"{RUN_PREFIX}batch-renamed-{index}",
                        }
                        for index, item in enumerate(rename_targets)
                    ]
                },
                headers=auth_headers(live_env.editor.token),
            )
        )
        assert len(batch_rename["pending"]) == 2
        assert batch_rename["renamed"] == []
        for item in batch_rename["pending"]:
            await _withdraw(
                client,
                live_env.editor.token,
                int(item["approval_instance_id"]),
            )

        move_targets = [
            await create_folder(
                client,
                live_env.admin_token,
                space_id,
                f"{RUN_PREFIX}batch-move-{index}",
            )
            for index in range(2)
        ]
        batch_move = assert_success(
            await client.post(
                f"{API_BASE}/knowledge/space/{space_id}/files/move",
                json={
                    "items": [{"id": item["id"], "type": "folder"} for item in move_targets],
                    "target_space_id": space_id,
                    "target_folder_id": target["id"],
                },
                headers=auth_headers(live_env.editor.token),
            )
        )
        assert len(batch_move["pending"]) == 2
        assert batch_move["moved"] == []
        for item in batch_move["pending"]:
            await _withdraw(
                client,
                live_env.editor.token,
                int(item["approval_instance_id"]),
            )

    async def test_ac29_ac34_ac36_ac37_batch_approve_partial_latest_status(
        self,
        client,
        live_env: F046TenantEnvironment,
    ):
        """AC-29/34/36/37: instance batch decision preserves successes and reports stale items."""
        require_async_workers()
        await put_policy(client, live_env.admin_token, enabled=True, scope="all_spaces")
        space = await create_space(client, live_env, "batch-approve")
        space_id = int(space["id"])
        folders = [
            await create_folder(
                client,
                live_env.admin_token,
                space_id,
                f"{RUN_PREFIX}approve-{index}",
            )
            for index in range(2)
        ]
        pending: list[dict] = []
        for index, folder in enumerate(folders):
            pending.append(
                assert_success(
                    await client.put(
                        f"{API_BASE}/knowledge/space/{space_id}/folders/{folder['id']}",
                        json={"name": f"{RUN_PREFIX}approved-{index}"},
                        headers=auth_headers(live_env.editor.token),
                    )
                )
            )

        await _reject(
            client,
            live_env.manager.token,
            int(pending[1]["approval_instance_id"]),
        )
        batch = assert_success(
            await client.post(
                f"{API_BASE}/knowledge/space/{space_id}/file-changes/batch-approve",
                json={
                    "approval_instance_ids": [
                        pending[0]["approval_instance_id"],
                        pending[1]["approval_instance_id"],
                    ]
                },
                headers=auth_headers(live_env.admin_token),
            )
        )
        assert batch["successCount"] == 1, batch
        assert batch["failureCount"] == 1, batch
        assert len(batch["items"]) == 2
        assert {item["result"] for item in batch["items"]} == {"approved", "invalid"}
        failed = next(item for item in batch["items"] if item["result"] != "approved")
        assert failed["latestStatus"] == "rejected"
        assert failed["retryable"] is False
        completed = await wait_for(
            lambda: _detail(
                client,
                live_env.editor.token,
                space_id,
                int(pending[0]["change_request_id"]),
            ),
            lambda value: isinstance(value, dict) and value.get("status") in {"executed", "execute_failed"},
            description="successful batch item to finish independently",
        )
        assert completed["status"] == "executed", completed

    async def test_ac28_to_ac30_dynamic_manager_reconciliation_and_former_deny(
        self,
        client,
        live_env: F046TenantEnvironment,
    ):
        """AC-28~30/34/36: new manager can approve; former manager loses detail/decision."""
        require_async_workers()
        await put_policy(client, live_env.admin_token, enabled=True, scope="all_spaces")
        replacement_viewer_grant = {
            "subject_type": "user",
            "subject_id": live_env.replacement_manager.user_id,
            "relation": "viewer",
            "include_children": False,
        }
        space = await create_space(
            client,
            live_env,
            "manager-change",
            extra_grants=[replacement_viewer_grant],
        )
        space_id = int(space["id"])
        folder = await create_folder(
            client,
            live_env.admin_token,
            space_id,
            f"{RUN_PREFIX}manager-folder",
        )
        pending = assert_success(
            await client.put(
                f"{API_BASE}/knowledge/space/{space_id}/folders/{folder['id']}",
                json={"name": f"{RUN_PREFIX}manager-folder-new"},
                headers=auth_headers(live_env.editor.token),
            )
        )
        old_grant = {
            "subject_type": "user",
            "subject_id": live_env.manager.user_id,
            "relation": "manager",
            "include_children": False,
        }
        new_grant = {
            "subject_type": "user",
            "subject_id": live_env.replacement_manager.user_id,
            "relation": "manager",
            "include_children": False,
        }
        authorization = await authorize_space(
            client,
            live_env.admin_token,
            space_id,
            grants=[new_grant],
            revokes=[old_grant, replacement_viewer_grant],
        )
        assert authorization["failed_count"] == 0, authorization
        assert authorization["invite_created_count"] == 0, authorization
        assert authorization["direct_applied_count"] == 3, authorization

        new_detail = await _detail(
            client,
            live_env.replacement_manager.token,
            space_id,
            int(pending["change_request_id"]),
        )
        assert new_detail["can_approve"] is True
        former = await client.get(
            f"{API_BASE}/knowledge/space/{space_id}/file-changes/{pending['change_request_id']}",
            headers=auth_headers(live_env.manager.token),
        )
        assert_error(former, 18073)

        approved = assert_success(
            await client.post(
                f"{API_BASE}/knowledge/space/{space_id}/file-changes/batch-approve",
                json={"change_request_ids": [pending["change_request_id"]]},
                headers=auth_headers(live_env.replacement_manager.token),
            )
        )
        assert approved["successCount"] == 1
        assert approved["failureCount"] == 0
        completed = await wait_for(
            lambda: _detail(
                client,
                live_env.editor.token,
                space_id,
                int(pending["change_request_id"]),
            ),
            lambda value: isinstance(value, dict) and value.get("status") in {"executed", "execute_failed"},
            description="new manager approved mutation to finish",
        )
        assert completed["status"] == "executed", completed

    async def test_ac32_ac44_ac46_ac48_async_execution_reaches_authoritative_state(
        self,
        client,
        live_env: F046TenantEnvironment,
    ):
        """AC-32/44/46/48: approved rename stays executing until worker applies it."""
        require_async_workers()
        await put_policy(client, live_env.admin_token, enabled=True, scope="all_spaces")
        space = await create_space(client, live_env, "async-execution")
        space_id = int(space["id"])
        folder = await create_folder(
            client,
            live_env.admin_token,
            space_id,
            f"{RUN_PREFIX}async-old",
        )
        pending = assert_success(
            await client.put(
                f"{API_BASE}/knowledge/space/{space_id}/folders/{folder['id']}",
                json={"name": f"{RUN_PREFIX}async-new"},
                headers=auth_headers(live_env.editor.token),
            )
        )
        approved = assert_success(
            await client.post(
                f"{API_BASE}/knowledge/space/{space_id}/file-changes/batch-approve",
                json={"approval_instance_ids": [pending["approval_instance_id"]]},
                headers=auth_headers(live_env.manager.token),
            )
        )
        assert approved["successCount"] == 1

        final = await wait_for(
            lambda: _detail(
                client,
                live_env.editor.token,
                space_id,
                int(pending["change_request_id"]),
            ),
            lambda value: isinstance(value, dict) and value.get("status") in {"executed", "execute_failed"},
            description="approved rename to become executed or execute_failed",
        )
        assert final["status"] == "executed", final
        assert any(
            int(item["id"]) == int(folder["id"]) and item.get("file_name") == f"{RUN_PREFIX}async-new"
            for item in await list_children(client, live_env.editor.token, space_id)
        )

    async def test_ac39_ac40_ac42_private_and_channel_boundaries(
        self,
        client,
        live_env: F046TenantEnvironment,
    ):
        """AC-39/40/42: private-space owner is direct and channel APIs remain unaffected."""
        await put_policy(client, live_env.admin_token, enabled=True, scope="all_spaces")
        private_space = await create_space(
            client,
            live_env,
            "private",
            auth_type="private",
            include_editor=False,
            include_manager=False,
        )
        folder = await create_folder(
            client,
            live_env.admin_token,
            int(private_space["id"]),
            f"{RUN_PREFIX}private-folder",
        )
        direct = assert_success(
            await client.put(
                f"{API_BASE}/knowledge/space/{private_space['id']}/folders/{folder['id']}",
                json={"name": f"{RUN_PREFIX}private-renamed"},
                headers=auth_headers(live_env.admin_token),
            )
        )
        assert direct["decision"] == "direct"

        channels = assert_success(
            await client.get(
                f"{API_BASE}/channel/manager/my_channels",
                params={"query_type": "created", "sort_by": "latest_update"},
                headers=auth_headers(live_env.admin_token),
            )
        )
        assert isinstance(rows(channels), list)

    async def test_ac41_department_space_private_is_rejected(
        self,
        client,
        live_env: F046TenantEnvironment,
    ):
        """AC-41: an explicit private department-space request returns exact error 18075."""
        department_id = os.environ.get("E2E_F046_DEPARTMENT_ID")
        if not department_id:
            pytest.skip("set E2E_F046_DEPARTMENT_ID to exercise department-space private rejection")
        response = await client.post(
            f"{API_BASE}/knowledge/space/department/batch-create",
            json={
                "items": [
                    {
                        "department_id": int(department_id),
                        "name": f"{RUN_PREFIX}department-private",
                        "auth_type": "private",
                    }
                ]
            },
            headers=auth_headers(live_env.admin_token),
        )
        assert_error(response, 18075)

    async def test_ac53_dual_tenant_policy_and_request_isolation(
        self,
        client,
        live_env: F046TenantEnvironment,
    ):
        """AC-53: tenant A/B policies are independent and tenant B cannot read A request."""
        tenant_b_token = await optional_tenant_b_token(client)
        tenant_b_id = tenant_id_from_token(tenant_b_token)
        assert tenant_b_id != live_env.tenant_id, "tenant-B credentials resolve to tenant A"
        original_b = await get_policy(client, tenant_b_token)
        try:
            await put_policy(client, live_env.admin_token, enabled=True, scope="per_space")
            await put_policy(client, tenant_b_token, enabled=False, scope="all_spaces")
            assert await get_policy(client, live_env.admin_token) == {
                "enabled": True,
                "scope": "per_space",
            }
            assert await get_policy(client, tenant_b_token) == {
                "enabled": False,
                "scope": "all_spaces",
            }

            space = await create_space(client, live_env, "tenant-isolation")
            folder = await create_folder(
                client,
                live_env.admin_token,
                int(space["id"]),
                f"{RUN_PREFIX}tenant-folder",
            )
            request = assert_success(
                await client.put(
                    f"{API_BASE}/knowledge/space/{space['id']}/folders/{folder['id']}",
                    json={"name": f"{RUN_PREFIX}tenant-folder-new"},
                    headers=auth_headers(live_env.editor.token),
                )
            )
            cross_tenant = await client.get(
                f"{API_BASE}/knowledge/space/{space['id']}/file-changes/{request['change_request_id']}",
                headers=auth_headers(tenant_b_token),
            )
            assert_error(cross_tenant, 18073)
            await _withdraw(
                client,
                live_env.editor.token,
                int(request["approval_instance_id"]),
            )
        finally:
            await put_policy(
                client,
                tenant_b_token,
                enabled=bool(original_b["enabled"]),
                scope=str(original_b["scope"]),
            )
