"""F016: provider saves resolve prices inside their locked write, against the rows as stored then.

The provider form omits prices it did not change. Both write paths (a plain save and a save that
removes models) must keep the stored price, and must not write back a price that another
administrator changed after the form was loaded.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.llm import ModelPricingConflictError
from bisheng.llm.domain.models.llm_server import LLMDao, LLMModel, LLMServer
from bisheng.llm.domain.repositories import model_pricing_repository as repository
from bisheng.llm.domain.repositories.model_mutation_repository import ModelMutationRepository
from bisheng.llm.domain.schemas import LLMModelCreateReq, LLMServerCreateReq
from test.llm.test_model_pricing_edit import QWEN_MAX, STORED, TENANT, _config, _resolve
from test.llm.test_model_pricing_edit import store as store

NO_DSH = SimpleNamespace(dsh=SimpleNamespace(enabled=False))


@pytest.fixture
def provider(store):
    with (
        patch("bisheng.llm.domain.models.llm_server.get_async_db_session", store.sessions),
        patch("bisheng.llm.domain.models.llm_server.settings", NO_DSH),
        patch("bisheng.llm.domain.repositories.model_mutation_repository.settings", NO_DSH),
    ):
        yield store


async def _another_admin_raises_the_output_price():
    """Administrator B edits the price in the table after A loaded the provider form."""
    saved = await repository.asave_model_pricing(7, _resolve({**QWEN_MAX, "output": "40", "revision": 3}))
    assert (saved["output"], saved["revision"]) == ("40", 4)
    return saved


def _form_models(pricing=None):
    """Administrator A's provider form: the price is omitted unless A changed it."""
    config = {"max_tokens": 2000, **({"pricing": pricing} if pricing else {})}
    return [
        LLMModel(id=7, tenant_id=TENANT, server_id=2, name="m", model_name="qwen-max", model_type="llm", config=config),
        LLMModel(
            id=8, tenant_id=TENANT, server_id=2, name="e", model_name="text-embedding", model_type="embedding", config={}
        ),
    ]


async def test_a_plain_save_keeps_a_price_changed_after_the_form_loaded(provider):
    edited = await _another_admin_raises_the_output_price()
    server = LLMServer(id=2, tenant_id=TENANT, name="qwen", type="qwen", config={})
    await LLMDao.update_server_with_models(server, _form_models())
    config = await _config(provider, 7)
    assert config["pricing"] == edited
    assert config["max_tokens"] == 2000


async def test_a_plain_save_with_a_stale_price_is_refused_and_writes_nothing(provider):
    edited = await _another_admin_raises_the_output_price()
    server = LLMServer(id=2, tenant_id=TENANT, name="qwen", type="qwen", config={})
    with pytest.raises(ModelPricingConflictError):
        await LLMDao.update_server_with_models(server, _form_models({**QWEN_MAX, "revision": 3}))
    config = await _config(provider, 7)
    assert config["pricing"] == edited
    assert config["max_tokens"] == 1000


async def test_removing_a_model_keeps_the_retained_models_prices(provider):
    async with provider.sessions() as session, session.begin():
        session.add(
            LLMModel(
                id=9, tenant_id=TENANT, server_id=2, name="old", model_name="qwen-plus", model_type="llm", config={}
            )
        )
    edited = await _another_admin_raises_the_output_price()
    form = LLMServerCreateReq(
        id=2,
        name="qwen",
        type="qwen",
        config={},
        models=[
            LLMModelCreateReq(id=7, name="m", model_name="qwen-max", model_type="llm", config={"max_tokens": 2000}),
            LLMModelCreateReq(id=8, name="e", model_name="text-embedding", model_type="embedding", config={}),
        ],
    )
    async with provider.sessions() as session:
        async with session.begin():
            await ModelMutationRepository().aupdate_server(
                session, server=form, merged_config={}, removed_model_ids=(9,), actor_user_id=1
            )
    config = await _config(provider, 7)
    assert config["pricing"] == edited
    assert config["max_tokens"] == 2000
    # The confirmed command is left as submitted; only the written rows carry the price.
    assert "pricing" not in form.models[0].config
    async with provider.sessions() as session:
        remaining = (await session.exec(sa.select(LLMModel.id).order_by(LLMModel.id))).all()
    assert [row[0] for row in remaining] == [7, 8]
