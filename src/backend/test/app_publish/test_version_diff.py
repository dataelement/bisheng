"""T063 — server-side diff of two version snapshots (AC-41 / design D15).

``GET /api/v1/apps/{app_id}/versions/{base}/diff/{target}``. The sentence
under test is the design's: **the diff is computed on the server and neither
tar is sent to the browser**. So the response is asserted to carry a change
list and bounded patch text and nothing archive-shaped; binary files degrade
to "not comparable"; secrets are masked inside hunks; and the three caps each
leave a ``truncated`` mark rather than a silently shorter answer.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from .conftest import OWNER_USER_ID, ROOT_TENANT_ID
from .test_snapshot_api import _payload, _seed_task, _store

pytestmark = pytest.mark.asyncio

APPROVER_USER_ID = OWNER_USER_ID + 600

_MANIFEST = "name: F055 app\nruntime: python3.11\nport: 8080\n"
_MAIN_V1 = "import os\n\n\ndef main():\n    print('v1')\n\n\nmain()\n"
_MAIN_V2 = "import os\nimport sys\n\n\ndef main():\n    print('v2')\n\n\nmain()\n"


def _body(response):
    assert response.status_code == 200, response.text
    return response.json()


async def _second_version(publish_db, app):
    """A version-2 row for ``app`` (the app factory only seeds version 1)."""
    from bisheng.database.models.app_version import VERSION_KIND_ITERATION, AppVersion, AppVersionDao

    async with publish_db() as session:
        row = AppVersion(
            app_id=app.id,
            version_no=2,
            kind=VERSION_KIND_ITERATION,
            terminal_state=None,
            code_object_key="",
            manifest={"name": app.name, "runtime": "python3.11", "port": 8080},
            capabilities={},
            injections={},
            tier_id="light",
            runtime="python3.11",
            submitted_at=datetime.now(),
        )
        await AppVersionDao.ainsert(session, row)
        await session.commit()
    return row


@pytest.fixture()
async def two_versions(publish_db, app_factory, fake_minio, tarball_factory):
    """``await two_versions(v1_files, v2_files)`` → ``(app, v1, v2)`` with both snapshots stored.

    ``v1_files`` / ``v2_files`` replace the whole package content (the
    manifest is added when absent), so a test states exactly what differs.
    """

    async def _make(v1_files: dict, v2_files: dict):
        app, v1 = await app_factory(with_version=True)
        v2 = await _second_version(publish_db, app)
        for version, files in ((v1, v1_files), (v2, v2_files)):
            package = tarball_factory(manifest=_MANIFEST, extra_files=files)
            await _store(publish_db, app, version, package.read_bytes())
        return app, v1, v2

    return _make


# ---------------------------------------------------------------------------
# shape and classification
# ---------------------------------------------------------------------------


async def test_diff_endpoint_shape_and_change_kinds(publish_db, api_app, two_versions, owner_user):
    app, v1, v2 = await two_versions(
        {"main.py": _MAIN_V1, "old.txt": "fastapi\n", "same.txt": "unchanged\n"},
        {"main.py": _MAIN_V2, "README.md": "# hello\n", "same.txt": "unchanged\n"},
    )

    async with api_app(payload=owner_user.payload) as client:
        data = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{v1.id}/diff/{v2.id}"))["data"]

    assert set(data) == {"base", "target", "role", "summary", "files", "patches"}
    assert data["base"]["version_id"] == v1.id and data["base"]["version_no"] == 1
    assert data["target"]["version_id"] == v2.id and data["target"]["version_no"] == 2
    assert data["role"] == "owner"

    files = {item["path"]: item for item in data["files"]}
    assert set(files) == {"main.py", "old.txt", "README.md"}  # same.txt and the fixture files are omitted
    assert files["main.py"] == {
        "path": "main.py",
        "change": "modified",
        "additions": 2,
        "deletions": 1,
        "comparable": True,
        "reason": None,
    }
    assert files["old.txt"]["change"] == "removed" and files["old.txt"]["deletions"] == 1
    assert files["README.md"]["change"] == "added" and files["README.md"]["additions"] == 1
    assert data["summary"] == {"files_changed": 3, "additions": 3, "deletions": 2, "truncated": False}

    patches = {item["path"]: item for item in data["patches"]}
    assert set(patches) == set(files)
    main_patch = patches["main.py"]["patch"]
    assert main_patch.startswith("--- a/main.py\n+++ b/main.py\n@@")
    assert "+import sys\n" in main_patch and "-    print('v1')\n" in main_patch and "+    print('v2')\n" in main_patch
    assert patches["README.md"]["patch"].startswith("--- /dev/null\n+++ b/README.md\n")
    assert patches["old.txt"]["patch"].startswith("--- a/old.txt\n+++ /dev/null\n")
    assert all(item["truncated"] is False for item in data["patches"])


async def test_no_archive_is_ever_sent(publish_db, api_app, two_versions, owner_user):
    """Design D15: the two tars stay on the server. The response is text about the change, not the code itself."""
    app, v1, v2 = await two_versions({"main.py": _MAIN_V1}, {"main.py": _MAIN_V2})

    async with api_app(payload=owner_user.payload) as client:
        response = await client.get(f"/api/v1/apps/{app.id}/versions/{v1.id}/diff/{v2.id}")

    body = response.text
    assert "code_object_key" not in body and "tar.gz" not in body and "H4sI" not in body  # base64 gzip magic
    data = response.json()["data"]
    assert not any(key in data for key in ("archive", "snapshot", "package", "download_url"))


async def test_binary_files_are_listed_but_not_compared(publish_db, api_app, two_versions, owner_user):
    app, v1, v2 = await two_versions(
        {"logo.bin": b"\x89PNG\x00\x00one", "keep.bin": b"\x00same"},
        {"logo.bin": b"\x89PNG\x00\x00two", "keep.bin": b"\x00same"},
    )

    async with api_app(payload=owner_user.payload) as client:
        data = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{v1.id}/diff/{v2.id}"))["data"]

    assert data["files"] == [
        {
            "path": "logo.bin",
            "change": "modified",
            "additions": 0,
            "deletions": 0,
            "comparable": False,
            "reason": "binary",
        }
    ]
    assert data["patches"] == []
    assert data["summary"]["files_changed"] == 1


async def test_oversized_text_file_is_not_compared(publish_db, api_app, two_versions, owner_user):
    from bisheng.app_publish.domain.services.secret_scanner import MAX_SCAN_FILE_BYTES

    app, v1, v2 = await two_versions(
        {"big.txt": "a" * (MAX_SCAN_FILE_BYTES + 1)},
        {"big.txt": "b" * (MAX_SCAN_FILE_BYTES + 1)},
    )

    async with api_app(payload=owner_user.payload) as client:
        data = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{v1.id}/diff/{v2.id}"))["data"]

    assert data["files"][0]["comparable"] is False and data["files"][0]["reason"] == "too_large"
    assert data["patches"] == []


async def test_identical_versions_yield_empty_diff(publish_db, api_app, two_versions, owner_user):
    app, v1, v2 = await two_versions({"main.py": _MAIN_V1}, {"main.py": _MAIN_V1})

    async with api_app(payload=owner_user.payload) as client:
        data = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{v1.id}/diff/{v2.id}"))["data"]

    assert data["files"] == [] and data["patches"] == []
    assert data["summary"] == {"files_changed": 0, "additions": 0, "deletions": 0, "truncated": False}


async def test_secrets_are_masked_inside_hunks(publish_db, api_app, two_versions, owner_user):
    """Masked *before* diffing: the value appears on neither side of any hunk."""
    app, v1, v2 = await two_versions(
        {"conf.py": 'password = "Zk8vQ2mN4pR7tW1yB5xC9eH3jL6sD0fG"\nx = 1\n'},
        {"conf.py": 'password = "Zk8vQ2mN4pR7tW1yB5xC9eH3jL6sD0fG"\nx = 2\nkey = "AKIAIOSFODNN7EXAMPLE"\n'},
    )

    async with api_app(payload=owner_user.payload) as client:
        response = await client.get(f"/api/v1/apps/{app.id}/versions/{v1.id}/diff/{v2.id}")

    assert "Zk8vQ2mN4pR7tW1yB5xC9eH3jL6sD0fG" not in response.text
    assert "AKIAIOSFODNN7EXAMPLE" not in response.text
    patch = response.json()["data"]["patches"][0]
    assert patch["masked_secrets"] == 3  # the password on both sides + the key on the new side
    assert '+key = "***"' in patch["patch"]


# ---------------------------------------------------------------------------
# size guards
# ---------------------------------------------------------------------------


async def test_per_file_patch_cap_marks_truncated(publish_db, api_app, two_versions, owner_user, monkeypatch):
    from bisheng.app_publish.domain.services import version_diff_service

    monkeypatch.setattr(version_diff_service, "MAX_PATCH_LINES_PER_FILE", 5)
    app, v1, v2 = await two_versions(
        {"gen.txt": "".join(f"old {i}\n" for i in range(50))},
        {"gen.txt": "".join(f"new {i}\n" for i in range(50))},
    )

    async with api_app(payload=owner_user.payload) as client:
        data = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{v1.id}/diff/{v2.id}"))["data"]

    patch = data["patches"][0]
    assert patch["truncated"] is True
    assert patch["patch"].count("\n") == 5
    # The counts are still the true counts — truncation rations text, not numbers.
    assert data["files"][0]["additions"] == 50 and data["files"][0]["deletions"] == 50


async def test_total_patch_budget_drops_later_patches_not_files(
    publish_db, api_app, two_versions, owner_user, monkeypatch
):
    from bisheng.app_publish.domain.services import version_diff_service

    monkeypatch.setattr(version_diff_service, "MAX_TOTAL_PATCH_BYTES", 1)
    app, v1, v2 = await two_versions(
        {"a.txt": "1\n", "b.txt": "1\n"},
        {"a.txt": "2\n", "b.txt": "2\n"},
    )

    async with api_app(payload=owner_user.payload) as client:
        data = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{v1.id}/diff/{v2.id}"))["data"]

    assert [item["path"] for item in data["files"]] == ["a.txt", "b.txt"]
    assert data["patches"][0]["patch"]  # the first one fits (the budget is checked before spending)
    assert data["patches"][1] == {
        "path": "b.txt",
        "change": "modified",
        "patch": None,
        "truncated": True,
        "masked_secrets": 0,
    }
    assert data["summary"]["truncated"] is True
    assert data["summary"]["files_changed"] == 2


async def test_file_list_cap_marks_summary_truncated(publish_db, api_app, two_versions, owner_user, monkeypatch):
    from bisheng.app_publish.domain.services import version_diff_service

    monkeypatch.setattr(version_diff_service, "MAX_DIFF_FILES", 2)
    app, v1, v2 = await two_versions({}, {f"f{i}.txt": "x\n" for i in range(5)})

    async with api_app(payload=owner_user.payload) as client:
        data = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{v1.id}/diff/{v2.id}"))["data"]

    assert len(data["files"]) == 2
    assert data["summary"]["truncated"] is True


# ---------------------------------------------------------------------------
# access and failure envelopes (K11 ②)
# ---------------------------------------------------------------------------


async def test_approver_of_the_target_version_may_diff_against_the_published_one(publish_db, api_app, two_versions):
    """AC-41's diff is "pending against last published"; the published side has no request to hold a task on."""
    app, v1, v2 = await two_versions({"main.py": _MAIN_V1}, {"main.py": _MAIN_V2})
    await _seed_task(publish_db, app=app, version_id=v2.id, approver_user_id=APPROVER_USER_ID)

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        data = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{v1.id}/diff/{v2.id}"))["data"]

    assert data["role"] == "approver"
    assert data["summary"]["files_changed"] == 1


async def test_stranger_and_unrelated_approver_get_16257(publish_db, api_app, two_versions):
    app, v1, v2 = await two_versions({"main.py": _MAIN_V1}, {"main.py": _MAIN_V2})
    await _seed_task(publish_db, app=app, version_id="unrelated-version", approver_user_id=APPROVER_USER_ID + 1)

    for user_id in (OWNER_USER_ID + 4242, APPROVER_USER_ID + 1):
        async with api_app(payload=_payload(user_id)) as client:
            response = await client.get(f"/api/v1/apps/{app.id}/versions/{v1.id}/diff/{v2.id}")
        assert response.status_code == 200
        assert response.json()["status_code"] == 16257
        assert "patches" not in response.json()["data"]


async def test_unknown_version_is_16253_and_swept_snapshot_16256(publish_db, api_app, two_versions, owner_user):
    from bisheng.app_publish.domain.services.package_service import APPS_BUCKET, snapshot_key
    from bisheng.core.storage.minio.minio_manager import get_minio_storage

    app, v1, v2 = await two_versions({"main.py": _MAIN_V1}, {"main.py": _MAIN_V2})
    storage = await get_minio_storage()
    await storage.remove_object(bucket_name=APPS_BUCKET, object_name=snapshot_key(app.id, v1.id))

    async with api_app(payload=owner_user.payload) as client:
        unknown = await client.get(f"/api/v1/apps/{app.id}/versions/{v1.id}/diff/no-such-version")
        swept = await client.get(f"/api/v1/apps/{app.id}/versions/{v1.id}/diff/{v2.id}")

    assert unknown.status_code == 200 and unknown.json()["status_code"] == 16253
    assert swept.status_code == 200 and swept.json()["status_code"] == 16256


async def test_corrupt_snapshot_is_16256_not_a_deploy_code(publish_db, api_app, two_versions, owner_user):
    """``safe_extract`` speaks 16202 at deploy time; at review time the caller hears "snapshot unavailable"."""
    app, v1, v2 = await two_versions({"main.py": _MAIN_V1}, {"main.py": _MAIN_V2})
    await _store(publish_db, app, v2, b"definitely not a tarball")

    async with api_app(payload=owner_user.payload) as client:
        response = await client.get(f"/api/v1/apps/{app.id}/versions/{v1.id}/diff/{v2.id}")

    assert response.status_code == 200
    assert response.json()["status_code"] == 16256
    assert response.json()["data"]["details"]["reason"] == "unreadable_archive"


async def test_diff_route_is_session_only_and_registered(publish_db):
    from bisheng.app_publish.api.router import v1_router
    from bisheng.open_api.domain.scopes import get_open_api_scope_marker

    route = next(r for r in v1_router.routes if r.path.endswith("/diff/{target_version_id}"))
    assert route.path == "/apps/{app_id}/versions/{base_version_id}/diff/{target_version_id}"
    assert get_open_api_scope_marker(route.endpoint) is None


async def test_tenant_admin_check_is_asked_with_the_apps_tenant(publish_db, api_app, two_versions, monkeypatch):
    from bisheng.app_publish.domain.services import snapshot_browse_service

    asked: list[tuple[int, int]] = []

    async def _check(user_id: int, tenant_id: int) -> bool:
        asked.append((user_id, tenant_id))
        return False

    monkeypatch.setattr(snapshot_browse_service, "check_tenant_admin", _check)
    app, v1, v2 = await two_versions({"main.py": _MAIN_V1}, {"main.py": _MAIN_V2})

    async with api_app(payload=_payload(OWNER_USER_ID + 99)) as client:
        response = await client.get(f"/api/v1/apps/{app.id}/versions/{v1.id}/diff/{v2.id}")

    assert response.json()["status_code"] == 16257
    assert asked == [(OWNER_USER_ID + 99, ROOT_TENANT_ID)]
