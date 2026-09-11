"""Production assembly boundaries: current JWT authority and tenant lifecycle restoration."""

from types import SimpleNamespace

import pytest

from bisheng.core.context import tenant as context
from bisheng.dsh.operations_runtime import OperationsAuthentication


async def test_authentication_validates_fresh_version_global_admin_and_scope():
    calls = []

    class Records:
        async def actor(self, user_id):
            return {"user_id": user_id, "user_name": "admin", "active": True, "token_version": 4, "tenant_id": 1}

        async def active_tenant(self, tenant_id):
            return tenant_id == 2

    async def login(record):
        calls.append(record["token_version"])
        return SimpleNamespace(is_global_super=True)

    auth = OperationsAuthentication(
        records=Records(), decode=lambda token: {"user_id": 7, "tenant_id": 1, "token_version": 4}, login=login
    )
    previous = context.current_tenant_id.get()
    try:
        assert await auth.authenticate_admin("jwt", tenant_id=2) == 7
        assert context.get_current_tenant_id() == 2
        assert context.get_visible_tenant_ids() == frozenset({2})
        assert calls == [4]
    finally:
        auth.reset()
    assert context.current_tenant_id.get() == previous
    auth.decode = lambda token: {"user_id": 7, "tenant_id": 1, "token_version": 3}
    with pytest.raises(PermissionError):
        await auth.authenticate_admin("stale", tenant_id=2)
    assert context.current_tenant_id.get() == previous


async def test_non_global_or_inactive_scope_rejected_without_context_change():
    class Records:
        async def actor(self, user_id):
            return {"user_id": user_id, "user_name": "admin", "active": True, "token_version": 0, "tenant_id": 1}

        async def active_tenant(self, tenant_id):
            return True

    async def login(record):
        return SimpleNamespace(is_global_super=False)

    auth = OperationsAuthentication(
        records=Records(), decode=lambda token: {"user_id": 7, "tenant_id": 1, "token_version": 0}, login=login
    )
    previous = context.current_tenant_id.get()
    with pytest.raises(PermissionError):
        await auth.authenticate_admin("jwt", tenant_id=2)
    assert context.current_tenant_id.get() == previous


async def test_activation_failure_cannot_reuse_old_approval(monkeypatch):
    import asyncio

    from bisheng.dsh import operations_runtime
    from bisheng.dsh.infrastructure.quota_redis import QuotaRejected

    calls = []

    async def denied(*args, **kwargs):
        calls.append(kwargs["reference"])
        raise QuotaRejected("unapproved_primary")

    monkeypatch.setattr(operations_runtime, "activate_from_approval", denied)
    runtime = object.__new__(operations_runtime.OperationsRuntime)
    runtime.activation_lock = asyncio.Lock()
    runtime.activation_attempted = False
    runtime.quota = SimpleNamespace(topology=SimpleNamespace(ready=False))
    runtime.approvals = object()
    runtime.config = SimpleNamespace(quota_approval_object="immutable@v1", quota_approval_sha256="a" * 64)
    with pytest.raises(QuotaRejected, match="unapproved_primary"):
        await runtime.activate()
    with pytest.raises(QuotaRejected, match="controlled_approval_required"):
        await runtime.activate()
    assert calls == ["immutable@v1"]


def test_real_celery_registration_and_existing_jwt_decoder(tmp_path):
    import os
    import subprocess
    import sys

    configuration = tmp_path / "config.yaml"
    configuration.write_text(
        "database_url: sqlite:///" + str(tmp_path / "import.db") + "\n"
        "redis_url: redis://127.0.0.1:16362/15\n"
        "celery_redis_url: redis://127.0.0.1:16362/15\n"
        "dsh:\n  enabled: true\n"
        "  platform_public_url: https://bisheng.example\n"
        "  gateway_internal_url: https://gateway.example\n"
        "logger_conf:\n  log_level: ERROR\n"
    )
    script = """
import bisheng.worker
from bisheng.worker.main import bisheng_celery
from bisheng.worker.config import beat_schedule
from bisheng.user.domain.services.auth import AuthJwt
from bisheng.dsh.operations_runtime import _decode_admin_token
required = {'dsh.project_usage', 'dsh.reconcile_usage', 'dsh.scan_usage',
            'dsh.inspect_usage', 'dsh.scan_operations', 'dsh.resume_operation', 'dsh.scan_profiles'}
assert required <= set(bisheng_celery.tasks)
assert {beat_schedule[k]['task'] for k in beat_schedule if k.startswith('dsh-')} == {
    'dsh.scan_usage', 'dsh.scan_operations', 'dsh.scan_profiles'}
subject = {'user_id': 7, 'tenant_id': 1, 'token_version': 4}
auth = AuthJwt()
token = auth.create_access_token(subject)
assert _decode_admin_token(token) == subject
try:
    _decode_admin_token(token + 'invalid')
except Exception:
    pass
else:
    raise AssertionError('Invalid signature accepted')
print('DSH registration and existing JWT signature verification passed')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "config": str(configuration), "MPLCONFIGDIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr[-5000:]
    assert "DSH registration and existing JWT signature verification passed" in result.stdout
