"""The original HTTP PUT/DELETE and new precheck/page entries use native SQL."""

from unittest.mock import AsyncMock

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.api.router import router
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.schemas import LLMModelCreateReq, LLMServerCreateReq
from bisheng.llm.domain.services import llm as service_module
from bisheng.llm.domain.services.llm import LLMService
from test.knowledge_unification import test_model_delete_plan_application as actual
from test.knowledge_unification import test_model_deletion_application as native_business
from test.knowledge_unification import test_model_deletion_put as native_put

business = native_business.business
impact = actual.impact
model_owner_tenant = actual.model_owner_tenant
ready = actual.ready
removal_session = actual.removal_session
install = native_put.install


def http_application(identity):
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    application.dependency_overrides[UserPayload.get_tenant_admin_user] = lambda: identity

    async def business_error(request, error):
        return JSONResponse(jsonable_encoder(error.return_resp_instance()))

    application.add_exception_handler(BaseErrorCode, business_error)
    return application


@pytest.mark.parametrize("force", [False, True])
async def test_public_precheck_exact_put_and_empty_provider_delete_share_the_real_confirmation(
    business, monkeypatch, force
):
    factory, _, _, _, _ = business
    await install(monkeypatch, business)
    body = actual.request().model_dump(mode="json")
    with actual.native.actor() as user:
        actual.web(user)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=http_application(user)), base_url="http://test"
        ) as client:
            precheck = (await client.post("/api/v1/llm/removal-plan", json=body)).json()
            assert precheck["status_code"] == 200 and not precheck["data"]["inspection"]["blocked"]
            control = precheck["data"]["confirmation"]
            response = (
                await client.put(
                    "/api/v1/llm",
                    json=body,
                    params={
                        "confirmation_id": control["confirmation_id"],
                        "plan_digest": control["plan_digest"],
                    },
                )
            ).json()
            assert response["status_code"] == 200 and len(response["data"]["models"]) == 3
            assert actual.SECRET not in str(response["data"]["config"])
            plan = (await client.post("/api/v1/llm/server-removal-plan", json={"server_id": 5})).json()
            assert plan["status_code"] == 200
            delete_control = plan["data"]["confirmation"]
            parameters = (
                {
                    "force": "true",
                    "confirmation_id": delete_control["confirmation_id"],
                    "plan_digest": delete_control["plan_digest"],
                }
                if force
                else {}
            )
            response = (await client.request("DELETE", "/api/v1/llm", json={"server_id": 5}, params=parameters)).json()
            assert response["status_code"] == 200
    async with factory() as session:
        assert await session.get(LLMServer, 5) is None


async def test_public_source_page_and_force_without_confirmation_fail_closed(business, monkeypatch):
    factory, _, references, _, _ = business
    await install(monkeypatch, business)
    with actual.native.actor() as user:
        actual.web(user)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=http_application(user)), base_url="http://test"
        ) as client:
            response = (
                await client.post("/api/v1/llm/removal-sources", json={"server_id": 1, "delete_server": True})
            ).json()
            assert response["status_code"] == 200 and "same" not in str(response["data"])
            response = (
                await client.request("DELETE", "/api/v1/llm", json={"server_id": 1}, params={"force": "true"})
            ).json()
            assert response["status_code"] != 200
            references.coverage_factory = None
            response = (await client.request("DELETE", "/api/v1/llm", json={"server_id": 5})).json()
            assert response["status_code"] == 10994
    async with factory() as session:
        assert await session.get(LLMServer, 1) is not None and await session.get(LLMServer, 5) is not None
        assert not (await session.execute(sa.select(KnowledgeOperationPlan))).scalars().all()


async def test_original_nonremoval_put_remains_usable_without_coverage(business, monkeypatch):
    factory, _, references, _, _ = business
    await install(monkeypatch, business)
    references.coverage_factory = None
    monkeypatch.setattr(service_module, "_write_llm_audit", AsyncMock())
    monkeypatch.setattr(LLMService, "probe_models_in_background", AsyncMock())
    monkeypatch.setattr(LLMService, "set_default_model", AsyncMock())
    async with factory() as session:
        provider = await session.get(LLMServer, 1)
        models = (await session.execute(sa.select(LLMModel).where(LLMModel.server_id == 1))).scalars().all()
        body = LLMServerCreateReq(
            **provider.model_dump(exclude={"user_id", "tenant_id", "create_time", "update_time"}),
            models=[LLMModelCreateReq.model_validate(row.model_dump()) for row in models],
        )
    body.description = "ordinary non-removal edit"
    body.models.extend(
        [
            LLMModelCreateReq(id=ident, name=f"added-{index}", model_name=f"added-{index}", model_type="asr_rt")
            for index, ident in enumerate((None, 0))
        ]
    )
    with actual.native.actor() as user:
        actual.web(user)
        result = await LLMService.update_llm_server(None, user, body)
    assert result.description == body.description and len(result.models) == 7
    assert all(type(model.id) is int and model.id > 0 for model in result.models)
    async with factory() as session:
        assert not (await session.execute(sa.select(KnowledgeOperationPlan))).scalars().all()
