"""F016 model price storage inside ``llm_model.config["pricing"]``."""

from sqlmodel import Session, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.llm.domain.models.llm_server import LLMModel


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
