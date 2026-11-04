"""T078/T079 测试入口自身的离线安全契约。不是存储或 E2E 通过证据。"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from test.e2e.helpers.kunlian import Journey, OperatorBridge, envelope, live_journey, private_json, validate_manifest
from test.integration.kunlian_fixtures import storage_settings


def manifest():
    return {
        "origin": "https://e2e-kunlian.invalid",
        "connection_id": "e2e-kunlian-test",
        "external_tenant_id": "e2e-kunlian-tenant",
        "local_tenant_id": 2,
        "foreign_local_tenant_id": 3,
        "expected_member_count": 3,
        "return_to": "/workspace",
        "actors": {
            "a": {"user_id": 101, "name": "e2e-kunlian-a"},
            "b": {"user_id": 102, "name": "e2e-kunlian-b"},
            "c": {"name": "e2e-kunlian-c"},
            "missing": {"name": "e2e-kunlian-new-probe"},
        },
    }


@pytest.mark.parametrize(
    "database,redis",
    [
        ("sqlite+aiosqlite://", "redis://localhost/9"),
        ("mysql+asyncmy://tester@localhost/production", "redis://localhost/9"),
        ("mysql+asyncmy://tester@localhost/e2e_kunlian_test", "redis://localhost/0"),
        ("dm+dmAsync://tester@localhost/e2e_kunlian_test", "redis://localhost/9"),
    ],
)
def test_storage_rejects_unsafe_targets_without_connecting(database, redis):
    with pytest.raises(ValueError):
        storage_settings({"F118_TEST_DATABASE_URL": database, "F118_TEST_REDIS_URL": redis})


def test_missing_or_malformed_settings_fail_without_secret_output():
    with pytest.raises(ValueError):
        storage_settings({})
    with pytest.raises(ValueError) as failure:
        storage_settings({"F118_TEST_DATABASE_URL": "secret-marker", "F118_TEST_REDIS_URL": "redis://localhost/9"})
    assert "secret-marker" not in str(failure.value)
    value = manifest()
    value["origin"] = "https://other.invalid/redirect"
    with pytest.raises(ValueError):
        validate_manifest(value)
    value = manifest()
    value["actors"]["b"]["user_id"] = value["actors"]["a"]["user_id"]
    with pytest.raises(ValueError):
        validate_manifest(value)


def test_valid_test_targets_and_manifest_are_accepted_without_io():
    for database in (
        "mysql+asyncmy://tester@localhost/e2e_kunlian_test",
        "dm+dmAsync://tester@localhost?schema=e2e_kunlian_test",
    ):
        result, _ = storage_settings({"F118_TEST_DATABASE_URL": database, "F118_TEST_REDIS_URL": "redis://localhost/9"})
        assert result.drivername in {"mysql+asyncmy", "dm+dmAsync"}
    assert validate_manifest(manifest())["return_to"] == "/workspace"


def test_private_exchange_file_refuses_public_permissions_and_links(tmp_path):
    path = tmp_path / "value.json"
    path.write_text("{}")
    path.chmod(0o644)
    with pytest.raises(ValueError):
        private_json(path)
    path.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        private_json(link)
    assert private_json(path) == {}


@pytest.mark.parametrize("valid", [True, False], ids=["current-checkpoint", "stale-checkpoint"])
async def test_checkpoint_nonce_is_required_and_private_files_are_removed(tmp_path, valid):
    bridge = OperatorBridge(tmp_path, timeout=5)

    async def operator():
        while not list(tmp_path.glob("*.request.json")):
            await asyncio.sleep(0)
        request = next(tmp_path.glob("*.request.json"))
        assert request.stat().st_mode & 0o077 == 0
        reply = request.with_name(request.name.replace(".request.", ".reply."))
        payload = private_json(request)
        reply.write_text(json.dumps({"nonce": payload["nonce"] if valid else "stale-nonce", "ok": True}))
        reply.chmod(0o600)

    if valid:
        answer, _ = await asyncio.gather(bridge.checkpoint("unit-only"), operator())
        assert answer["ok"] is True
    else:
        with pytest.raises(AssertionError, match="checkpoint"):
            await asyncio.gather(bridge.checkpoint("unit-only"), operator())
    assert not list(tmp_path.glob("*.json"))


async def test_explicit_live_mode_requires_complete_configuration_before_client_creation():
    with pytest.raises(ValueError, match="F118_E2E=1"):
        async with live_journey({}):
            pytest.fail("缺少配置时不能建立真实连接")


async def test_browser_write_uses_cookie_origin_and_actual_csrf_header(tmp_path):
    seen = []

    def endpoint(request):
        seen.append(request)
        if request.url.path.endswith("/session/csrf"):
            return httpx.Response(
                200, json={"status_code": 200, "status_message": "SUCCESS", "data": {"csrf_token": "unit-csrf"}}
            )
        assert request.headers["x-csrf-token"] == "unit-csrf"
        assert request.headers["origin"] == manifest()["origin"]
        assert request.headers["cookie"] == "access_token_cookie=unit-cookie"
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"status_code": 200, "status_message": "SUCCESS", "data": {"allowed": False}})

    async with httpx.AsyncClient(
        base_url=manifest()["origin"],
        transport=httpx.MockTransport(endpoint),
        cookies={"access_token_cookie": "unit-cookie"},
    ) as client:
        journey = Journey(manifest(), OperatorBridge(tmp_path, 5), "unit-admin", client, None)
        assert not await journey.check_action(client, "unit-workflow", "use")
    assert [request.method for request in seen] == ["GET", "POST"]


async def test_accepted_http_request_cannot_replace_real_worker_success(tmp_path):
    sent = []
    task = SimpleNamespace(ready=lambda: True, successful=lambda: False)

    def send_task(*args, **kwargs):
        sent.append((args, kwargs))
        return task

    def endpoint(request):
        data = (
            {"connection_id": "e2e-kunlian-test", "sync_completed_version": 1}
            if request.method == "GET"
            else {"requested_version": 2}
        )
        return httpx.Response(
            200 if request.method == "GET" else 202,
            json={"status_code": 200, "status_message": "SUCCESS", "data": data},
        )

    async with httpx.AsyncClient(base_url=manifest()["origin"], transport=httpx.MockTransport(endpoint)) as client:
        journey = Journey(
            manifest(), OperatorBridge(tmp_path, 5), "unit-admin", client, SimpleNamespace(send_task=send_task)
        )
        with pytest.raises(AssertionError, match="Worker"):
            await journey.sync()
    assert sent == [
        (
            ("bisheng.worker.sso_sync.tasks.sync_directory",),
            {"args": ["e2e-kunlian-test"], "headers": {"tenant_id": 1}, "queue": "celery", "retry": False},
        )
    ]


async def test_worker_budget_includes_slow_broker_submission(tmp_path):
    import time

    def send_task(*_args, **_kwargs):
        time.sleep(0.06)
        return SimpleNamespace(
            ready=lambda: True, successful=lambda: True, get=lambda **_: {"directory_status": "PUBLISHED"}
        )

    reads = 0

    def endpoint(request):
        nonlocal reads
        if request.method == "POST":
            return httpx.Response(
                202, json={"status_code": 200, "status_message": "SUCCESS", "data": {"requested_version": 2}}
            )
        reads += 1
        data = {
            "connection_id": "e2e-kunlian-test",
            "sync_completed_version": 1 if reads == 1 else 2,
            "active_batch_id": "old" if reads == 1 else "new",
            "directory_status": "PUBLISHED",
            "projection_pending": 0,
            "projection_failed": 0,
            "member_count": 3,
        }
        return httpx.Response(200, json={"status_code": 200, "status_message": "SUCCESS", "data": data})

    async with httpx.AsyncClient(base_url=manifest()["origin"], transport=httpx.MockTransport(endpoint)) as client:
        journey = Journey(
            manifest(), OperatorBridge(tmp_path, 0.01), "unit-admin", client, SimpleNamespace(send_task=send_task)
        )
        with pytest.raises(AssertionError, match="预算"):
            await journey.sync()


async def test_cleanup_stops_before_deleting_a_foreign_workflow(tmp_path):
    methods = []

    def endpoint(request):
        methods.append(request.method)
        return httpx.Response(
            200,
            json={
                "status_code": 200,
                "status_message": "SUCCESS",
                "data": {
                    "name": "another-owner",
                    "user_id": 999,
                    "tenant_id": 2,
                },
            },
        )

    async with httpx.AsyncClient(base_url=manifest()["origin"], transport=httpx.MockTransport(endpoint)) as client:
        journey = Journey(
            manifest(),
            OperatorBridge(tmp_path, 5),
            "unit-admin",
            client,
            None,
            workflows={"test-id": {"name": "e2e-kunlian-owned", "user_id": 101, "tenant_id": 2}},
        )
        with pytest.raises(AssertionError, match="停止清理"):
            await journey.cleanup()
    assert methods == ["GET"]


def test_failure_does_not_echo_response_secrets():
    response = httpx.Response(503, text="synthetic-secret-do-not-echo")
    with pytest.raises(AssertionError) as failure:
        envelope(response)
    assert "synthetic-secret" not in str(failure.value)
