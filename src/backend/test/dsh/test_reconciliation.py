"""T062: Coverage AC: AC-22, AC-23, AC-24, AC-28, AC-29, AC-30, AC-31, AC-34."""

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

import pytest
from sqlmodel import Session

from bisheng.common.errcode.dsh import DshOperationConflictError
from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
from bisheng.dsh.domain.repositories.reconciliation import DshReconciliationRepository
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.services.projection import DshProjectionService
from bisheng.dsh.domain.services.reconciliation import DshReconciliationService, ReconciliationInput
from bisheng.dsh.domain.services.usage import DshUsageService
from test.dsh.test_quota_admission import quota as quota
from test.dsh.test_quota_admission import running
from test.dsh.test_usage_repository import usage_db as usage_db


async def test_reconcile_one_unknown_preserves_others_and_waits_for_projection(quota, usage_db):
    DshAdminOperation.__table__.create(usage_db, checkfirst=True)

    @contextmanager
    def repository():
        with Session(usage_db) as session, session.begin():
            yield DshReconciliationRepository(session)

    @contextmanager
    def usage_repository():
        with Session(usage_db) as session, session.begin():
            yield DshUsageRepository(session)

    projector = DshProjectionService(quota, usage_repository, consumer="repair")
    a, b = running(), running()
    for e in [a, b]:
        await quota.check_and_start(e)
    for e in [a, b]:
        await quota.record_usage(e.model_copy(update={"status": "USAGE_UNKNOWN", "event_version": 2}), 1)
    await projector.project_batch(2, 20)
    evidence = json.dumps(
        {
            "request_id": a.request_id,
            "provider_request_id": None,
            "model_id": a.model_id,
            "started_at": a.started_at.isoformat(),
            "input_tokens": 10,
            "output_tokens": 20,
            "total_tokens": 30,
        }
    ).encode()

    class Evidence:
        async def read(self, reference, tenant_id):
            return evidence

    async def authorize(actor, user):
        return actor == 7 and user == 20

    service = DshReconciliationService(
        repository_scope=repository,
        usage=DshUsageService(quota),
        evidence=Evidence(),
        authorize=authorize,
        now=lambda: datetime(2026, 9, 9, 1),
    )
    request = ReconciliationInput(
        request_id=a.request_id,
        operation_id=str(uuid4()),
        expected_event_version=2,
        evidence_object="dsh/reconciliation/2/evidence@v1",
        evidence_sha256=hashlib.sha256(evidence).hexdigest(),
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        reason="provider case",
    )
    result = await service.submit(request, actor_user_id=7)
    assert result["status"] == "PROCESSING"
    assert await quota.redis.smembers(quota.keys(a)[0].removesuffix(":gate") + ":unknown_usage") == {b.request_id}
    assert await quota.redis.hget(quota.keys(a)[1], "used") == "930"
    await projector.project_batch(2, 20)
    assert (await service.resume(request.operation_id))["status"] == "SUCCEEDED"
    assert (await service.submit(request, actor_user_id=7))["status"] == "SUCCEEDED"
    assert await quota.redis.hget(quota.keys(a)[1], "used") == "930"
    with pytest.raises(DshOperationConflictError):
        await service.submit(request.model_copy(update={"operation_id": str(uuid4())}), actor_user_id=7)
    DshAdminOperation.__table__.drop(usage_db)


@pytest.mark.parametrize("denial", ["hash", "permission"])
async def test_bad_evidence_or_revoked_actor_never_settles(quota, usage_db, denial):
    from bisheng.common.errcode.dsh import DshOperationConflictError

    DshAdminOperation.__table__.create(usage_db, checkfirst=True)

    @contextmanager
    def repository():
        with Session(usage_db) as session, session.begin():
            yield DshReconciliationRepository(session)

    @contextmanager
    def usage_repository():
        with Session(usage_db) as session, session.begin():
            yield DshUsageRepository(session)

    a = running()
    await quota.check_and_start(a)
    await quota.record_usage(a.model_copy(update={"status": "USAGE_UNKNOWN", "event_version": 2}), 1)
    await DshProjectionService(quota, usage_repository, consumer="repair").project_batch(2, 20)
    data = json.dumps(
        {
            "request_id": a.request_id,
            "provider_request_id": None,
            "model_id": a.model_id,
            "started_at": a.started_at.isoformat(),
            "input_tokens": 1,
            "output_tokens": 0,
            "total_tokens": 1,
        }
    ).encode()

    class Evidence:
        async def read(self, reference, tenant_id):
            return data

    async def authorize(actor, user):
        return denial != "permission"

    service = DshReconciliationService(
        repository_scope=repository,
        usage=DshUsageService(quota),
        evidence=Evidence(),
        authorize=authorize,
        now=lambda: datetime(2026, 9, 9, 1),
    )
    request = ReconciliationInput(
        request_id=a.request_id,
        operation_id=str(uuid4()),
        expected_event_version=2,
        evidence_object="dsh/reconciliation/2/evidence@v1",
        evidence_sha256="b" * 64 if denial == "hash" else hashlib.sha256(data).hexdigest(),
        input_tokens=1,
        output_tokens=0,
        total_tokens=1,
        reason="provider case",
    )
    with pytest.raises(ValueError if denial == "hash" else DshOperationConflictError):
        await service.submit(request, actor_user_id=7)
    assert await quota.redis.hget(quota.keys(a)[1], "used") == "900"
    assert (await quota.get_request(a)).status == "USAGE_UNKNOWN"
    DshAdminOperation.__table__.drop(usage_db)


async def test_reconciliation_worker_uses_trusted_header_and_resets_context():
    import importlib.util
    from pathlib import Path

    from bisheng.core.context.tenant import current_tenant_id

    spec = importlib.util.spec_from_file_location(
        "dsh_reconcile_task", Path(__file__).resolve().parents[2] / "bisheng/worker/dsh/reconciliation.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Service:
        async def resume(self, operation_id):
            assert current_tenant_id.get() == 2
            raise RuntimeError("injected failure")

    before = current_tenant_id.get()
    with pytest.raises(RuntimeError, match="injected"):
        await module.resume_operation({"tenant_id": 2}, 2, "op", Service())
    assert current_tenant_id.get() == before
    with pytest.raises(ValueError):
        await module.resume_operation({"tenant_id": 3}, 2, "op", Service())
