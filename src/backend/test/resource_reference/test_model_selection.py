"""AC-12: reference-free saves keep actual model sharing and tenant boundaries."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import update

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.database.models.tenant import Tenant
from bisheng.llm.application import model_selection
from bisheng.resource_reference.application.contracts import ReferenceSpec, TargetKey
from test.knowledge_unification import test_kn_model_bindings as fixtures

business, store, tenant = fixtures.business, fixtures.store, fixtures.tenant


async def test_root_model_needs_actual_sharing_and_direct_child_membership(business):
    ref = ReferenceSpec("model", TargetKey("model", "22"))
    business.sharing.allowed = frozenset()
    async with business.sessions() as session:
        assert set(await model_selection.read_models(session, (11, 22, 999))) == {TargetKey("model", "11")}
        with pytest.raises(ResourceReferenceInvalidError):
            await model_selection.require_new_models(session, (ref,))
    business.sharing.allowed = frozenset({2})
    async with business.sessions() as session:
        await model_selection.require_new_models(session, (ref,))
    async with business.sessions() as session, session.begin():
        await session.execute(update(Tenant).where(Tenant.id == 101).values(parent_tenant_id=None))
    async with business.sessions() as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await model_selection.require_new_models(session, (ref,))


async def test_sharing_transport_failure_is_a_real_permission_failure(business, monkeypatch):
    monkeypatch.setattr(
        model_selection, "get_permission_relation_api", AsyncMock(side_effect=OSError("sharing unavailable"))
    )
    async with business.sessions() as session:
        with pytest.raises(OSError, match="sharing unavailable"):
            await model_selection.read_models(session, (22,))
