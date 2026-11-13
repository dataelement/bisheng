"""F016 model price storage inside ``llm_model.config["pricing"]``."""

from collections.abc import Callable

from sqlmodel import Session, select, update

from bisheng.common.errcode.llm import ModelPricingInvalidError
from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.llm.domain.const import LLMModelType
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer

# (provider type, model name, stored price) -> price to store; raises on a stale revision.
PriceResolver = Callable[[str, str, dict | None], dict]


class ModelPricingRepository:
    def __init__(self, session: Session):
        self.session = session

    def read(self, model_id: int) -> dict | None:
        """Current price config of a model the caller has ALREADY authorized.

        Reads the row directly, never the 60s in-process LLM_CACHE, so a price saved in
        another process applies to the next call (design decision 15). Tenant filtering
        is bypassed only to read Root-shared models; it never authorizes access.
        """
        with bypass_tenant_filter():
            config = self.session.exec(select(LLMModel.config).where(LLMModel.id == model_id)).first()
        pricing = config.get("pricing") if isinstance(config, dict) else None
        return pricing if isinstance(pricing, dict) else None


async def asave_model_pricing(model_id: int, resolve: PriceResolver) -> dict:
    """Store one LLM model's price under the provider lock every model writer takes (F118).

    ``resolve`` runs after the lock, so the revision it compares is the one being replaced
    and two administrators saving at once cannot both win (design decision 17).
    """
    from bisheng.llm.domain.repositories.model_provider_write_guard import alock_idle_model, check_idle_model_write

    async with get_async_db_session() as session:
        await session.begin()
        tenant, server_id, transaction = await alock_idle_model(session, model_id)
        owned = (LLMModel.id == model_id, LLMModel.tenant_id == tenant, LLMModel.server_id == server_id)
        row = (
            await session.exec(select(LLMModel.model_name, LLMModel.model_type, LLMModel.config).where(*owned))
        ).first()
        if row is None:
            raise LLMModelNotAccessibleError()
        model_name, model_type, config = row
        if model_type != LLMModelType.LLM.value:
            raise ModelPricingInvalidError()
        server_type = (await session.exec(select(LLMServer.type).where(LLMServer.id == server_id))).one()
        config = dict(config or {})
        pricing = resolve(server_type, model_name, config.get("pricing"))
        if pricing != config.get("pricing"):
            await session.exec(update(LLMModel).where(*owned).values(config={**config, "pricing": pricing}))
        check_idle_model_write(session, tenant, transaction)
        await session.commit()
        return pricing
