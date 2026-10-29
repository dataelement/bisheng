"""Precise start refusals and per-version approval projections."""

from types import SimpleNamespace as Row
from unittest.mock import AsyncMock

import pytest

from bisheng.app_publish.domain.services import version_review_service as service
from bisheng.common.errcode.app_factory import AppStateConflictError


def deployment(**kwargs):
    return Row(
        id="deploy",
        app_id="app",
        tenant_id=60,
        version_id="v1",
        approval_instance_id=42,
        status="waiting_approval",
        **kwargs,
    )


def approval(status="pending", **kwargs):
    values = {
        "id": 42,
        "tenant_id": 60,
        "scenario_code": "app_publish_request",
        "business_resource_type": "app",
        "business_resource_id": "app",
        "business_key": "deploy",
        "status": status,
    }
    values.update(kwargs)
    return Row(**values)


@pytest.mark.parametrize(
    "status,reason",
    [
        ("pending", "approval_pending"),
        ("rejected", "approval_rejected"),
        ("withdrawn", "approval_withdrawn"),
        ("exception", "approval_exception"),
        ("cancelled", "approval_cancelled"),
        ("execute_failed", "approval_execute_failed"),
    ],
)
async def test_missing_version_explains_approval(monkeypatch, status, reason):
    monkeypatch.setattr(service.VersionReviewRepository, "latest", AsyncMock(return_value=deployment()))
    monkeypatch.setattr(service, "get_business_approvals", AsyncMock(return_value={42: approval(status)}))
    with pytest.raises(AppStateConflictError) as caught:
        await service.refuse_unapproved_start("app")
    assert caught.value.kwargs["reason"] == reason


async def test_never_substitutes_another_tenants_approval(monkeypatch):
    monkeypatch.setattr(service.VersionReviewRepository, "deployments", AsyncMock(return_value=[deployment()]))
    monkeypatch.setattr(service, "get_business_approvals", AsyncMock(return_value={42: approval(tenant_id=1)}))
    assert await service.version_approval_states("app", 60, ["v1"]) == {}


@pytest.mark.parametrize("status", ["pending", "rejected", "withdrawn", "approved", "execute_failed", "exception"])
async def test_version_approval_status_survives_unlatched_runtime_outcome(monkeypatch, status):
    monkeypatch.setattr(service.VersionReviewRepository, "deployments", AsyncMock(return_value=[deployment()]))
    monkeypatch.setattr(service, "get_business_approvals", AsyncMock(return_value={42: approval(status)}))
    assert await service.version_approval_states("app", 60, ["v1"]) == {"v1": status}


async def test_no_deployment_gives_actionable_refusal(monkeypatch):
    monkeypatch.setattr(service.VersionReviewRepository, "latest", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "get_business_approvals", AsyncMock(return_value={}))
    with pytest.raises(AppStateConflictError) as caught:
        await service.refuse_unapproved_start("app")
    assert caught.value.kwargs["reason"] == "no_approved_version"
