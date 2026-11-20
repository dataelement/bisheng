"""Native SQL: the candidate roster and assignment enforce the same qualifications."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.app_publish.domain.models.app_deployment import AppDeployment
from bisheng.approval.domain.models.approval_instance import (
    ApprovalActionLog,
    ApprovalException,
    ApprovalInstance,
    ApprovalTask,
)
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.services.approval_exception_service import ApprovalExceptionService
from bisheng.approval.domain.services.approval_runtime_handler_factory import validate_scenario_candidates
from bisheng.common.errcode.approval import ApprovalRequestAlreadyProcessedError, ApprovalRequestPermissionDeniedError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion
from bisheng.database.models.tenant import UserTenant
from bisheng.user.domain.models.user import User
from test.fixtures.managed_tenant import managed_db as managed_db


@pytest.fixture
async def candidates_db(managed_db, monkeypatch):
    from bisheng.app_publish.domain.repositories import release_tenancy_repository
    from bisheng.approval.application import app_candidates
    from bisheng.approval.domain.repositories import (
        app_candidate_repository,
        approval_instance_repository,
        approver_candidate_repository,
    )

    await managed_db.create(
        User,
        UserTenant,
        App,
        AppVersion,
        AppDeployment,
        ApprovalInstance,
        ApprovalException,
        ApprovalTask,
        ApprovalActionLog,
    )
    for module in (
        release_tenancy_repository,
        app_candidate_repository,
        approval_instance_repository,
        approver_candidate_repository,
    ):
        monkeypatch.setattr(module, "get_async_db_session", managed_db.sessions)
    admins = {60: (849, 850), 1: (999,)}
    monkeypatch.setattr(
        app_candidates, "administrator_ids", AsyncMock(side_effect=lambda tenant: admins.get(tenant, ()))
    )
    payload = {
        "app_id": "app436",
        "deployment_id": "dep436",
        "version_id": "v436",
        "version_no": 4,
        "tenant_id": 60,
        "source": "cli",
        "owner_user_id": 868,
    }
    with bypass_tenant_filter():
        async with managed_db.sessions() as session:
            for uid, home, deleted in [
                (868, 60, 0),
                (895, 60, 0),
                (896, 1, 0),
                (897, 60, 1),
                (898, 60, 0),
                (849, 60, 0),
                (850, 60, 0),
                (999, 1, 0),
            ]:
                session.add(
                    User(
                        user_id=uid,
                        user_name=f"person-{uid}",
                        external_id=f"gzx{uid}",
                        password="fixture-only",
                        delete=deleted,
                    )
                )
                session.add(
                    UserTenant(user_id=uid, tenant_id=home, is_active=1, status="inactive" if uid == 898 else "active")
                )
            session.add(
                App(id="app436", tenant_id=60, owner_user_id=868, name="Legacy app", slug="legacy-436", state="draft")
            )
            session.add(
                AppVersion(
                    id="v436",
                    app_id="app436",
                    version_no=4,
                    kind="iteration",
                    code_object_key="fixture",
                    runtime="static",
                    tier_id=1,
                )
            )
            session.add(
                AppDeployment(
                    id="dep436",
                    tenant_id=60,
                    app_id="app436",
                    owner_user_id=868,
                    submitted_by_user_id=0,
                    version_id="v436",
                    approval_instance_id=436,
                    stage="approval_created",
                    status="waiting_approval",
                )
            )
            session.add(
                ApprovalInstance(
                    id=436,
                    tenant_id=60,
                    scenario_code="app_publish_request",
                    scenario_name="publish",
                    handler_key="app_publish_request",
                    business_key="dep436",
                    business_resource_type="app",
                    business_resource_id="app436",
                    business_name="Legacy app",
                    applicant_user_id=868,
                    applicant_user_name="owner",
                    status="exception",
                    payload_snapshot=payload,
                )
            )
            session.add(
                ApprovalException(id=79, tenant_id=60, instance_id=436, exception_type="approver_empty", status="open")
            )
            await session.commit()
    return SimpleNamespace(db=managed_db, admins=admins, payload=payload)


async def roster(**kwargs):
    return await ApprovalExceptionService.list_approver_candidates(
        exception_id=79, tenant_id=60, keyword="", page=1, limit=50, **kwargs
    )


async def test_legacy_roster_and_assignment_admit_same_tenant_person(candidates_db, monkeypatch):
    node = SimpleNamespace(node_code="n1", node_name="Review", node_order=1, node_mode="or")
    monkeypatch.setattr(ApprovalExceptionService, "_resolve_exception_node", AsyncMock(return_value=node))
    monkeypatch.setattr(ApprovalExceptionService, "_notify_created_tasks", AsyncMock())
    monkeypatch.setattr(ApprovalExceptionService, "_lookup_user_name", AsyncMock(return_value="admin"))
    with tenant_execution_scope(60):
        result = await roster()
        assert {row["user_id"] for row in result["data"]} == {895, 849, 850, 999}
        assert result["total"] == 4
        service = ApprovalExceptionService(instance_repository=ApprovalInstanceRepository, tenant_id=60)
        await service.assign_approvers(exception_id=79, approver_user_ids=[895], resolved_by_user_id=849)
        instance = await ApprovalInstanceRepository.get_instance(436)
        assert instance.status == "pending" and instance.payload_snapshot == candidates_db.payload
        tasks = await ApprovalInstanceRepository.list_tasks(436)
        assert [(task.tenant_id, task.approver_user_id) for task in tasks] == [(60, 895)]


async def test_pagination_and_search_only_count_eligible_people(candidates_db):
    with tenant_execution_scope(60):
        first = await ApprovalExceptionService.list_approver_candidates(
            exception_id=79, tenant_id=60, keyword="", page=1, limit=2
        )
        second = await ApprovalExceptionService.list_approver_candidates(
            exception_id=79, tenant_id=60, keyword="", page=2, limit=2
        )
        assert first["total"] == second["total"] == 4
        assert [row["user_id"] for row in first["data"] + second["data"]] == [999, 895, 850, 849]
        found = await ApprovalExceptionService.list_approver_candidates(
            exception_id=79, tenant_id=60, keyword="gzx895", page=1, limit=50
        )
        assert [row["user_id"] for row in found["data"]] == [895]


async def test_http_roster_requires_administrator_and_valid_pagination(candidates_db, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from bisheng.approval.api.endpoints.approval_admin import router
    from bisheng.common.dependencies.user_deps import UserPayload

    user = UserPayload(user_id=849, tenant_id=60, user_role=[])
    monkeypatch.setattr(
        "bisheng.permission.application.is_tenant_admin",
        AsyncMock(side_effect=lambda uid, tenant: uid == 849 and tenant == 60),
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    with tenant_execution_scope(60):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            path = "/api/v1/approval/admin/exceptions/79/approver-candidates"
            result = await client.get(path, params={"keyword": "gzx895", "page": 1, "limit": 50})
            assert result.json()["data"]["data"][0]["user_id"] == 895
            assert (await client.get(path, params={"limit": 100})).status_code == 422
            assert (await client.get(path, params={"page": 0})).status_code == 422
            user.user_id = 895
            assert (await client.get(path)).status_code == 403


async def test_modern_snapshot_retains_both_distinct_self_review_exclusions(candidates_db):
    with tenant_execution_scope(60):
        async with candidates_db.db.sessions() as session:
            instance = await session.get(ApprovalInstance, 436)
            instance.payload_snapshot = {
                **instance.payload_snapshot,
                "self_review_user_id": 849,
                "submission_actor": {"subject_type": "user", "subject_id": 849, "tenant_id": 60},
            }
            await session.commit()
        result = await roster()
        assert {row["user_id"] for row in result["data"]} == {895, 850, 999}
        instance = await ApprovalInstanceRepository.get_instance(436)
        assert await validate_scenario_candidates(instance, [895]) == [895]
        for uid in (849, 868):
            with pytest.raises(ApprovalRequestPermissionDeniedError):
                await validate_scenario_candidates(instance, [uid])


@pytest.mark.parametrize("candidate", [868, 896, 897, 898])
async def test_tampered_assignment_rejects_owner_foreign_disabled_and_inactive_home(candidates_db, candidate):
    with tenant_execution_scope(60):
        instance = await ApprovalInstanceRepository.get_instance(436)
        with pytest.raises(ApprovalRequestPermissionDeniedError):
            await validate_scenario_candidates(instance, [candidate])
        assert await ApprovalInstanceRepository.list_tasks(436) == []


async def test_current_policy_is_rechecked_after_roster(candidates_db):
    with tenant_execution_scope(60):
        assert 895 in {row["user_id"] for row in (await roster())["data"]}
        async with candidates_db.db.sessions() as session:
            (await session.get(User, 895)).delete = 1
            await session.commit()
        instance = await ApprovalInstanceRepository.get_instance(436)
        with pytest.raises(ApprovalRequestPermissionDeniedError):
            await validate_scenario_candidates(instance, [895])


async def test_verified_single_admin_exception_is_exclusive(candidates_db):
    candidates_db.admins[60] = (868,)
    with tenant_execution_scope(60):
        result = await roster()
        assert next(row for row in result["data"] if row["user_id"] == 868)["exclusive"] is True
        instance = await ApprovalInstanceRepository.get_instance(436)
        assert await validate_scenario_candidates(instance, [868]) == [868]
        with pytest.raises(ApprovalRequestPermissionDeniedError):
            await validate_scenario_candidates(instance, [868, 895])


async def test_newly_active_second_admin_blocks_cached_self_review_policy(candidates_db):
    from bisheng.approval.application.app_candidates import app_candidate_policy

    candidates_db.admins[60] = (868, 850)
    with tenant_execution_scope(60):
        async with candidates_db.db.sessions() as session:
            (await session.get(User, 850)).delete = 1
            await session.commit()
        policy = await app_candidate_policy(60, 868, 868)
        assert policy.exclusive_user_id == 868
        async with candidates_db.db.sessions() as session:
            (await session.get(User, 850)).delete = 0
            await session.commit()
        assert (await policy.qualify([868])).user_ids == ()


async def test_foreign_exception_is_rejected_even_with_root_visible(candidates_db):
    from bisheng.core.context.tenant import visible_tenant_ids

    with tenant_execution_scope(61):
        token = visible_tenant_ids.set(frozenset({60, 61}))
        try:
            with pytest.raises(ApprovalRequestPermissionDeniedError):
                await ApprovalExceptionService.list_approver_candidates(
                    exception_id=79, tenant_id=61, keyword="", page=1, limit=50
                )
        finally:
            visible_tenant_ids.reset(token)


async def test_resolved_exception_cannot_be_reopened_by_stale_selection(candidates_db):
    with tenant_execution_scope(60):
        exception = await ApprovalInstanceRepository.get_exception(79)
        exception.status = "resolved"
        await ApprovalInstanceRepository.update_exception(exception)
        with pytest.raises(ApprovalRequestAlreadyProcessedError):
            await roster()
        service = ApprovalExceptionService(instance_repository=ApprovalInstanceRepository, tenant_id=60)
        with pytest.raises(ApprovalRequestAlreadyProcessedError):
            await service.assign_approvers(exception_id=79, approver_user_ids=[895], resolved_by_user_id=849)


@pytest.mark.parametrize(
    "change",
    [
        "modern_missing",
        "wrong_deployment",
        "wrong_version",
        "wrong_tenant",
        "wrong_instance",
        "modern_origin",
        "different_submitter",
    ],
)
async def test_incomplete_or_mismatched_origin_never_guesses_owner(candidates_db, change):
    with tenant_execution_scope(60):
        async with candidates_db.db.sessions() as session:
            instance = await session.get(ApprovalInstance, 436)
            payload = deepcopy(instance.payload_snapshot)
            deployment = await session.get(AppDeployment, "dep436")
            if change == "modern_missing":
                payload["self_review_user_id"] = None
            elif change == "wrong_deployment":
                payload["deployment_id"] = "other"
            elif change == "wrong_version":
                payload["version_no"] = 5
            elif change == "wrong_tenant":
                payload["tenant_id"] = 61
            elif change == "wrong_instance":
                deployment.approval_instance_id = 437
            elif change == "modern_origin":
                deployment.authorization_context = {}
            elif change == "different_submitter":
                deployment.submitted_by_user_id = 895
            instance.payload_snapshot = payload
            await session.commit()
        assert (await roster())["data"] == []
        instance = await ApprovalInstanceRepository.get_instance(436)
        with pytest.raises(ApprovalRequestPermissionDeniedError):
            await validate_scenario_candidates(instance, [895])
