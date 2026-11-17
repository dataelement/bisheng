"""Legacy variable writes prove their canonical workflow and never trust body ownership."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from bisheng.common.errcode.http_error import NotFoundError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.variable_value import Variable, VariableCreate
from bisheng.workflow.application import variables
from bisheng.workflow.domain.repositories import variable_repository
from test.fixtures.managed_tenant import managed_db as managed_db


@pytest.fixture
async def variable_db(managed_db, monkeypatch):
    await managed_db.create(Flow, FlowVersion, Variable)
    monkeypatch.setattr(variable_repository, "get_async_db_session", managed_db.sessions)
    with bypass_tenant_filter():
        async with managed_db.sessions() as session:
            session.add_all(
                [
                    Flow(id="mine", name="Mine", flow_type=10, tenant_id=60),
                    Flow(id="other", name="Other", flow_type=10, tenant_id=65),
                    FlowVersion(id=601, flow_id="mine", name="v0", is_current=1, tenant_id=60),
                    FlowVersion(id=651, flow_id="other", name="v0", is_current=1, tenant_id=65),
                    Variable(
                        id=1,
                        flow_id="other",
                        version_id=651,
                        node_id="n",
                        variable_name="foreign",
                        value_type=1,
                        value="v",
                        tenant_id=65,
                    ),
                ]
            )
            await session.commit()
    gate = AsyncMock()
    monkeypatch.setattr(variables, "require_business_action", gate)
    return managed_db, gate


def value(**overrides):
    return Variable(
        flow_id="mine",
        version_id=601,
        node_id="n",
        variable_name="field",
        value_type=1,
        value="v",
        tenant_id=65,
        **overrides,
    )


async def test_write_uses_parent_owner_and_preserves_foreign_row(variable_db):
    db, gate = variable_db
    with tenant_execution_scope(60):
        saved = await variables.save_variable(SimpleNamespace(user_id=191), value())
        assert saved.tenant_id == 60
        with pytest.raises(NotFoundError):
            await variables.delete_variable(SimpleNamespace(user_id=191), 1)
    gate.assert_awaited_once_with(
        SimpleNamespace(user_id=191), resource_type="workflow", resource_id="mine", action="edit"
    )
    with bypass_tenant_filter():
        async with db.sessions() as session:
            assert (await session.get(Variable, 1)).value == "v"


async def test_mixed_batch_and_foreign_version_leave_existing_data(variable_db):
    db, _ = variable_db
    with tenant_execution_scope(60):
        await variables.save_variable(SimpleNamespace(), value())
        foreign = VariableCreate(
            flow_id="other", version_id=651, node_id="n", variable_name="field", value_type=1, value="v"
        )
        with pytest.raises(NotFoundError):
            await variables.replace_variables(SimpleNamespace(), [VariableCreate.model_validate(value()), foreign])
        wrong = value()
        wrong.version_id = 651
        with pytest.raises(NotFoundError):
            await variables.save_variable(SimpleNamespace(), wrong)
        async with db.sessions() as session:
            assert len((await session.exec(select(Variable))).all()) == 1


async def test_replacement_ignores_body_owner_and_empty_payload_cannot_delete(variable_db):
    db, _ = variable_db
    with tenant_execution_scope(60):
        await variables.save_variable(SimpleNamespace(), value())
        replacement = VariableCreate.model_validate(value())
        replacement.variable_name = "replacement"
        await variables.replace_variables(SimpleNamespace(), [replacement])
        await variables.replace_variables(SimpleNamespace(), [])
        async with db.sessions() as session:
            own = (await session.exec(select(Variable))).all()
            assert [(v.variable_name, v.tenant_id) for v in own] == [("replacement", 60)]
    with bypass_tenant_filter():
        async with db.sessions() as session:
            assert (await session.get(Variable, 1)).tenant_id == 65


async def test_denied_edit_never_mutates_variables(variable_db, monkeypatch):
    db, _ = variable_db
    from bisheng.common.errcode.http_error import UnAuthorizedError

    monkeypatch.setattr(variables, "require_business_action", AsyncMock(side_effect=UnAuthorizedError()))
    with tenant_execution_scope(60), pytest.raises(UnAuthorizedError):
        await variables.save_variable(SimpleNamespace(), value())
    with bypass_tenant_filter():
        async with db.sessions() as session:
            assert len((await session.exec(select(Variable))).all()) == 1
