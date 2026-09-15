"""T052 (backend half) — read-only snapshot browsing for the review view (AC-25 / AC-30).

``GET /api/v1/apps/{app_id}/versions/{version_id}/snapshot/tree`` and
``…/snapshot/file?path=``. What is asserted most carefully:

* **Who gets in.** Owner, tenant admin, super admin — and an approver, but
  only one who holds a task on the request of *that* version. Everybody else
  gets a business code in a 200 envelope, never a 403/404 (design K11 ②).
* **What never leaves.** Binary and over-sized files are reported, not
  served; secrets in text files are masked before the text goes out; the
  archive itself is never downloadable.
* **The tree the approver sees is the tree the runtime built** — a package
  wrapped in a single top-level directory is unwrapped the way the extractor
  unwraps it.
"""

from __future__ import annotations

import pytest

from .conftest import DEPT_ADMIN_USER_ID, OWNER_USER_ID, ROOT_TENANT_ID, _file_member, _tar_bytes_from_members

pytestmark = pytest.mark.asyncio

APPROVER_USER_ID = OWNER_USER_ID + 500
OTHER_APPROVER_USER_ID = OWNER_USER_ID + 501


def _body(response):
    assert response.status_code == 200, response.text
    return response.json()


def _payload(user_id: int, *, is_global_super: bool = False):
    from bisheng.common.dependencies.user_deps import UserPayload

    return UserPayload(
        user_id=user_id,
        user_name=f"u{user_id}",
        user_role=[],
        tenant_id=ROOT_TENANT_ID,
        is_global_super=is_global_super,
    )


async def _store(publish_db, app, version, package_bytes: bytes) -> None:
    """Put ``package_bytes`` where the version row points (through the real key layout)."""
    from bisheng.app_publish.domain.services.package_service import APPS_BUCKET, snapshot_key
    from bisheng.core.storage.minio.minio_manager import get_minio_storage
    from bisheng.database.models.app_version import AppVersion

    key = snapshot_key(app.id, version.id)
    storage = await get_minio_storage()
    await storage.put_object(bucket_name=APPS_BUCKET, object_name=key, file=package_bytes)
    async with publish_db() as session:
        row = await session.get(AppVersion, version.id)
        row.code_object_key = key
        session.add(row)
        await session.commit()


@pytest.fixture()
async def stored_app(publish_db, app_factory, fake_minio, tarball_factory):
    """``await stored_app(extra_files=...)`` → ``(app, version)`` with a real snapshot behind it."""

    async def _make(**tarball_kwargs):
        app, version = await app_factory(with_version=True)
        package = tarball_factory(**tarball_kwargs)
        await _store(publish_db, app, version, package.read_bytes())
        return app, version

    return _make


async def _seed_task(publish_db, *, app, version_id: str, approver_user_id: int) -> int:
    """An ``app_publish_request`` instance about ``version_id`` with one task for ``approver_user_id``."""
    from bisheng.app_publish.domain.services.app_publish_scenario_handler import SCENARIO_CODE
    from bisheng.approval.domain.models.approval_instance import ApprovalInstance, ApprovalTask

    async with publish_db() as session:
        instance = ApprovalInstance(
            tenant_id=ROOT_TENANT_ID,
            scenario_code=SCENARIO_CODE,
            scenario_name="应用发布",
            handler_key="app_publish",
            business_key=f"dep-{version_id}",
            business_resource_type="app",
            business_resource_id=str(app.id),
            business_name=app.name,
            applicant_user_id=int(app.owner_user_id),
            applicant_user_name="owner",
            status="pending",
            payload_snapshot={"app_id": app.id, "version_id": version_id},
            detail_snapshot={},
        )
        session.add(instance)
        await session.flush()
        session.add(
            ApprovalTask(
                tenant_id=ROOT_TENANT_ID,
                instance_id=instance.id,
                flow_version_id=1,
                node_code="n1",
                node_name="审批",
                node_order=1,
                approver_user_id=approver_user_id,
                approver_source_type="tenant_admin",
                node_mode="or",
                status="pending",
            )
        )
        await session.commit()
        return instance.id


# ---------------------------------------------------------------------------
# tree
# ---------------------------------------------------------------------------


async def test_tree_lists_files_and_derived_directories(publish_db, api_app, stored_app, owner_user):
    app, version = await stored_app(extra_files={"src/app/util.py": "def f():\n    return 1\n"})

    async with api_app(payload=owner_user.payload) as client:
        data = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/tree"))["data"]

    assert set(data) == {"version", "role", "entries", "total_files", "truncated"}
    assert data["version"]["version_id"] == version.id
    assert data["role"] == "owner"
    assert data["truncated"] is False
    by_path = {entry["path"]: entry for entry in data["entries"]}
    assert by_path["bisheng-app.yaml"]["type"] == "file"
    assert by_path["src"]["type"] == "dir" and by_path["src/app"]["type"] == "dir"
    assert by_path["src/app/util.py"] == {
        "path": "src/app/util.py",
        "name": "util.py",
        "type": "file",
        "size": len("def f():\n    return 1\n"),
        "previewable": True,
        "reason": None,
    }
    assert data["total_files"] == sum(1 for e in data["entries"] if e["type"] == "file")
    assert [e["path"] for e in data["entries"]] == sorted(e["path"] for e in data["entries"])


async def test_tree_flags_binary_and_oversized_as_not_previewable(publish_db, api_app, stored_app, owner_user):
    from bisheng.app_publish.domain.services.secret_scanner import MAX_SCAN_FILE_BYTES

    app, version = await stored_app(
        extra_files={"logo.bin": b"\x89PNG\x00\x00binary", "big.txt": "x" * (MAX_SCAN_FILE_BYTES + 1)}
    )

    async with api_app(payload=owner_user.payload) as client:
        data = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/tree"))["data"]

    by_path = {entry["path"]: entry for entry in data["entries"]}
    assert by_path["logo.bin"]["previewable"] is False and by_path["logo.bin"]["reason"] == "binary"
    assert by_path["big.txt"]["previewable"] is False and by_path["big.txt"]["reason"] == "too_large"
    assert by_path["main.py"]["previewable"] is True


async def test_tree_marks_truncated_when_entries_exceed_the_deploy_limit(
    publish_db, api_app, stored_app, owner_user, monkeypatch
):
    """The walk stops at ``max_package_entries`` and says so, rather than listing a partial tree as complete."""
    from bisheng.app_publish.domain.services import package_service

    limits = dict(package_service.deploy_limits())
    limits["max_package_entries"] = 2
    monkeypatch.setattr(package_service, "deploy_limits", lambda: limits)
    app, version = await stored_app(extra_files={"a.py": "a = 1\n", "b.py": "b = 1\n", "c.py": "c = 1\n"})

    async with api_app(payload=owner_user.payload) as client:
        data = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/tree"))["data"]

    assert data["truncated"] is True
    assert data["total_files"] == 2


async def test_tree_unwraps_single_top_level_directory(publish_db, api_app, app_factory, fake_minio, owner_user):
    """``tar czf pkg.tar.gz myapp/`` — the tree the approver sees has no ``myapp/`` prefix, like the runtime's."""
    app, version = await app_factory(with_version=True)
    package = _tar_bytes_from_members(
        [
            _file_member("myapp/bisheng-app.yaml", b"name: x\nruntime: python3.11\nport: 8080\n"),
            _file_member("myapp/main.py", b"print('hi')\n"),
            _file_member("myapp/lib/a.py", b"A = 1\n"),
        ]
    )
    await _store(publish_db, app, version, package)

    async with api_app(payload=owner_user.payload) as client:
        tree = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/tree"))["data"]
        file = _body(
            await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/file", params={"path": "lib/a.py"})
        )["data"]

    assert {e["path"] for e in tree["entries"]} == {"bisheng-app.yaml", "main.py", "lib", "lib/a.py"}
    assert file["content"] == "A = 1\n"


# ---------------------------------------------------------------------------
# file
# ---------------------------------------------------------------------------


async def test_file_returns_text_with_secrets_masked(publish_db, api_app, stored_app, owner_user):
    """A credential in a stored snapshot is masked on the way out — the value never reaches a browser."""
    app, version = await stored_app(
        extra_files={
            "settings.py": 'DEBUG = True\npassword = "Zk8vQ2mN4pR7tW1yB5xC9eH3jL6sD0fG"\nAWS = "AKIAIOSFODNN7EXAMPLE"\n'
        }
    )

    async with api_app(payload=owner_user.payload) as client:
        data = _body(
            await client.get(
                f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/file", params={"path": "settings.py"}
            )
        )["data"]

    assert set(data) == {
        "version",
        "role",
        "path",
        "size",
        "previewable",
        "reason",
        "content",
        "masked_secrets",
        "line_count",
    }
    assert data["previewable"] is True
    assert data["masked_secrets"] == 2
    assert data["line_count"] == 3
    assert "Zk8vQ2mN4pR7tW1yB5xC9eH3jL6sD0fG" not in data["content"]
    assert "AKIAIOSFODNN7EXAMPLE" not in data["content"]
    assert 'password = "***"' in data["content"]
    assert "DEBUG = True" in data["content"]


async def test_file_binary_and_oversized_degrade_without_bytes(publish_db, api_app, stored_app, owner_user):
    from bisheng.app_publish.domain.services.secret_scanner import MAX_SCAN_FILE_BYTES

    app, version = await stored_app(
        extra_files={"logo.bin": b"\x89PNG\x00\x00binary", "big.txt": "x" * (MAX_SCAN_FILE_BYTES + 1)}
    )

    async with api_app(payload=owner_user.payload) as client:
        binary = _body(
            await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/file", params={"path": "logo.bin"})
        )["data"]
        big = _body(
            await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/file", params={"path": "big.txt"})
        )["data"]

    assert binary["previewable"] is False and binary["reason"] == "binary" and binary["content"] is None
    assert big["previewable"] is False and big["reason"] == "too_large" and big["content"] is None
    assert big["size"] == MAX_SCAN_FILE_BYTES + 1


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("../etc/passwd", "illegal_path"),
        ("/etc/passwd", "illegal_path"),
        ("nope.py", "not_found"),
        ("src", "not_found"),  # a directory is not a file
    ],
)
async def test_file_refuses_missing_and_illegal_paths_16258(publish_db, api_app, stored_app, owner_user, path, reason):
    app, version = await stored_app(extra_files={"src/x.py": "x = 1\n"})

    async with api_app(payload=owner_user.payload) as client:
        response = await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/file", params={"path": path})

    assert response.status_code == 200
    body = response.json()
    assert body["status_code"] == 16258
    assert body["data"]["details"]["reason"] == reason


# ---------------------------------------------------------------------------
# access — owner / approver / stranger
# ---------------------------------------------------------------------------


async def test_approver_holding_a_task_on_this_version_is_admitted(publish_db, api_app, stored_app):
    app, version = await stored_app()
    await _seed_task(publish_db, app=app, version_id=version.id, approver_user_id=APPROVER_USER_ID)

    async with api_app(payload=_payload(APPROVER_USER_ID)) as client:
        tree = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/tree"))
        file = _body(
            await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/file", params={"path": "main.py"})
        )

    assert tree["status_code"] == 200 and tree["data"]["role"] == "approver"
    assert file["status_code"] == 200 and file["data"]["content"]


async def test_approver_resolved_by_the_real_publish_request_is_admitted(
    publish_db,
    api_app,
    app_factory,
    deployment_factory,
    fake_minio,
    tarball_factory,
    approval_env,
    audit_sink,
    approval_notifications,
    dept_admin_user,
):
    """The access rule reads what ``publish_approval_service.submit`` actually writes.

    ``_seed_task`` above hand-builds an instance; this one goes through the
    real gate so a renamed ``payload_snapshot.version_id`` or a changed
    ``business_resource_type`` breaks here instead of silently locking every
    approver out of the review view in production.
    """
    from bisheng.app_publish.domain.models.app_deployment import STAGE_PRECHECK_PROBE, STATUS_RUNNING
    from bisheng.app_publish.domain.services import publish_approval_service
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
    from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision

    app, version = await app_factory(with_version=True)
    await _store(publish_db, app, version, tarball_factory().read_bytes())
    deployment = await deployment_factory(
        app_id=app.id,
        stage=STAGE_PRECHECK_PROBE,
        status=STATUS_RUNNING,
        version_id=version.id,
        tier_code="light",
        manifest={"name": app.name, "runtime": "python3.11", "port": 8080, "tier": "light"},
    )

    result = await publish_approval_service.submit(deployment)
    assert result.decision == ApprovalGateDecision.PENDING
    tasks = await ApprovalInstanceRepository.list_tasks(result.instance_id)
    assert DEPT_ADMIN_USER_ID in {int(task.approver_user_id) for task in tasks}

    async with api_app(payload=_payload(DEPT_ADMIN_USER_ID)) as client:
        tree = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/tree"))
    async with api_app(payload=_payload(OWNER_USER_ID + 4242)) as client:
        stranger = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/tree"))

    assert tree["status_code"] == 200 and tree["data"]["role"] == "approver"
    assert stranger["status_code"] == 16257


async def test_approver_of_another_version_is_refused_16257(publish_db, api_app, stored_app):
    """Holding a task on version N does not open version M; being an approver somewhere opens nothing."""
    app, version = await stored_app()
    await _seed_task(publish_db, app=app, version_id="some-other-version", approver_user_id=OTHER_APPROVER_USER_ID)

    async with api_app(payload=_payload(OTHER_APPROVER_USER_ID)) as client:
        response = await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/tree")

    assert response.status_code == 200
    assert response.json()["status_code"] == 16257
    assert response.json()["data"]["details"]["reason"] == "not_reviewer"


async def test_stranger_gets_business_code_not_403_404(publish_db, api_app, stored_app):
    app, version = await stored_app()

    async with api_app(payload=_payload(OWNER_USER_ID + 4242)) as client:
        tree = await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/tree")
        file = await client.get(
            f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/file", params={"path": "main.py"}
        )

    for response in (tree, file):
        assert response.status_code == 200
        assert response.json()["status_code"] == 16257
        assert response.json().get("data", {}).get("content") is None


async def test_super_admin_and_tenant_admin_are_admitted(publish_db, api_app, stored_app, monkeypatch):
    from bisheng.app_publish.domain.services import snapshot_browse_service

    app, version = await stored_app()

    async def _is_admin(user_id: int, tenant_id: int) -> bool:
        return user_id == OWNER_USER_ID + 7 and tenant_id == ROOT_TENANT_ID

    monkeypatch.setattr(snapshot_browse_service, "check_tenant_admin", _is_admin)

    async with api_app(payload=_payload(OWNER_USER_ID + 9, is_global_super=True)) as client:
        as_super = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/tree"))
    async with api_app(payload=_payload(OWNER_USER_ID + 7)) as client:
        as_tenant_admin = _body(await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/tree"))

    assert as_super["data"]["role"] == "super_admin"
    assert as_tenant_admin["data"]["role"] == "tenant_admin"


async def test_missing_app_and_missing_version_are_200_envelopes(publish_db, api_app, stored_app, owner_user):
    app, _version = await stored_app()

    async with api_app(payload=owner_user.payload) as client:
        no_app = await client.get("/api/v1/apps/no-such-app/versions/v/snapshot/tree")
        no_version = await client.get(f"/api/v1/apps/{app.id}/versions/no-such-version/snapshot/tree")

    assert no_app.status_code == 200 and no_app.json()["status_code"] == 16257
    assert no_version.status_code == 200 and no_version.json()["status_code"] == 16253


async def test_swept_snapshot_is_16256(publish_db, api_app, app_factory, fake_minio, owner_user):
    """The version row survives (AC-40) but its object is gone: a distinct code from 'no such version'."""
    app, version = await app_factory(with_version=True)  # code_object_key points at nothing in fake_minio

    async with api_app(payload=owner_user.payload) as client:
        response = await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/tree")

    assert response.status_code == 200
    assert response.json()["status_code"] == 16256
    assert response.json()["data"]["details"]["reason"] == "missing"


async def test_corrupt_snapshot_is_16256_not_500(publish_db, api_app, app_factory, fake_minio, owner_user):
    app, version = await app_factory(with_version=True)
    await _store(publish_db, app, version, b"this is not a gzip archive")

    async with api_app(payload=owner_user.payload) as client:
        response = await client.get(f"/api/v1/apps/{app.id}/versions/{version.id}/snapshot/tree")

    assert response.status_code == 200
    assert response.json()["status_code"] == 16256
    assert response.json()["data"]["details"]["reason"] == "unreadable_archive"


# ---------------------------------------------------------------------------
# what is pinned about the surface
# ---------------------------------------------------------------------------


async def test_no_archive_download_route_exists(publish_db):
    """The snapshot is browsed one file at a time; there is no way to pull the whole archive (design D15)."""
    from bisheng.app_publish.api.router import v1_router

    paths = {route.path for route in v1_router.routes}
    assert "/apps/{app_id}/versions/{version_id}/snapshot/tree" in paths
    assert "/apps/{app_id}/versions/{version_id}/snapshot/file" in paths
    assert not any(path.endswith(("/download", "/archive", "/snapshot")) for path in paths)


async def test_mask_secrets_keeps_placeholders_and_counts():
    """Documentation-shaped values stay readable; real ones become ``***`` and are counted."""
    from bisheng.app_publish.domain.services.secret_scanner import SECRET_MASK, mask_secrets

    text = 'token = "your_token_goes_here_replace_me_now"\nsecret = "Zk8vQ2mN4pR7tW1yB5xC9eH3jL6sD0fG"\n'
    masked, count = mask_secrets(text)
    assert count == 1
    assert 'token = "your_token_goes_here_replace_me_now"' in masked
    assert f'secret = "{SECRET_MASK}"' in masked
