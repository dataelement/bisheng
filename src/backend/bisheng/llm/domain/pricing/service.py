"""F016 price decisions when LLM models are saved (the single price write path, decision 17).

Every LLM model ends up with ``config["pricing"]``: a submitted price is validated
and its source judged by the server; an omitted price keeps the stored one (the
provider form replaces the whole config, so omission must never wipe it); a model
with no price yet takes the catalog price, or zeros (free) when nothing matches.
"""

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bisheng.common.errcode.llm import ModelPricingConflictError, ModelPricingInvalidError
from bisheng.llm.domain.const import LLMModelType
from bisheng.llm.domain.pricing.catalog import catalog_pricing, match
from bisheng.llm.domain.pricing.schemas import Currency, ModelPricing, Price, price_to_micro


class ModelPricingInput(BaseModel):
    # Server-owned fields (source, catalog_key, ...) may be echoed back by the editor; ignore them.
    model_config = ConfigDict(extra="ignore")

    currency: Currency
    input: Price
    cache_read: Price
    cache_write: Price | None = None
    output: Price
    ref_key: str | None = Field(default=None, max_length=128)
    revision: int | None = Field(default=None, ge=1, strict=True)


def _parse_stored(value) -> ModelPricing | None:
    try:
        return ModelPricing.model_validate(value) if value is not None else None
    except ValidationError:
        return None  # a corrupt stored price is re-derived like a missing one


def _price_key(pricing) -> tuple:
    return (
        pricing.currency,
        price_to_micro(pricing.input),
        price_to_micro(pricing.cache_read),
        price_to_micro(pricing.cache_write if pricing.cache_write is not None else pricing.input),
        price_to_micro(pricing.output),
    )


def default_pricing(server_type: str, model_name: str) -> ModelPricing:
    found = match(server_type, model_name)
    if found is not None:
        return catalog_pricing(found.entry)
    return ModelPricing(currency="CNY", input="0", cache_read="0", output="0", source="DEFAULT")


def resolve_model_pricing(server_type: str, model_name: str, *, incoming, existing) -> dict:
    """The price record to store for one LLM model being saved."""
    current = _parse_stored(existing)
    if incoming is None:
        return (current or default_pricing(server_type, model_name)).model_dump()
    try:
        value = ModelPricingInput.model_validate(incoming)
    except ValidationError as error:
        raise ModelPricingInvalidError() from error
    if current is not None and value.revision != current.revision:
        raise ModelPricingConflictError()
    found = match(server_type, model_name)
    if found is not None:
        catalog = catalog_pricing(found.entry)
        source = "CATALOG" if _price_key(value) == _price_key(catalog) else "MANUAL"
        catalog_key, catalog_version = catalog.catalog_key, catalog.catalog_version
    else:
        source = "MANUAL" if any(_price_key(value)[1:]) else "DEFAULT"
        catalog_key = catalog_version = None
    candidate = ModelPricing(
        currency=value.currency,
        input=value.input,
        cache_read=value.cache_read,
        cache_write=value.cache_write,
        output=value.output,
        source=source,
        catalog_key=catalog_key,
        catalog_version=catalog_version,
        ref_key=value.ref_key,
        revision=1 if current is None else current.revision,
    )
    if current is not None:
        if candidate.model_dump() == current.model_dump():
            return current.model_dump()  # resubmitting the same price is not a change
        candidate.revision = current.revision + 1
    return candidate.model_dump()


def apply_pricing_on_save(server_type: str, models, old_models: dict) -> None:
    """Fill ``config["pricing"]`` on every LLM model of a provider save, in place."""
    for model in models:
        if model.model_type != LLMModelType.LLM.value:
            continue
        config = dict(model.config or {})
        old = old_models.get(model.id) if model.id else None
        existing = (old.config or {}).get("pricing") if old is not None else None
        config["pricing"] = resolve_model_pricing(
            server_type, model.model_name, incoming=config.get("pricing"), existing=existing
        )
        model.config = config


async def save_model_pricing(operator, model_id: int, incoming) -> dict:
    """Edit one model's price from the user-selectable model table (T04); returns the stored price."""
    from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError, LLMModelSharedReadonlyError
    from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id
    from bisheng.database.models.tenant import ROOT_TENANT_ID
    from bisheng.llm.domain.models.llm_server import LLMDao
    from bisheng.llm.domain.repositories.model_pricing_repository import asave_model_pricing
    from bisheng.llm.domain.utils import invalidate_llm_info_cache

    if incoming is None:
        raise ModelPricingInvalidError()
    # Read past the tenant filter only to tell a Root-shared model (read-only here) from a missing one.
    with bypass_tenant_filter():
        model = await LLMDao.aget_model_by_id(model_id)
        server = await LLMDao.aget_server_by_id(model.server_id) if model else None
    if server is None:
        raise LLMModelNotAccessibleError()
    if server.tenant_id == ROOT_TENANT_ID and get_current_tenant_id() != ROOT_TENANT_ID:
        raise LLMModelSharedReadonlyError()
    pricing = await asave_model_pricing(
        model_id,
        lambda server_type, model_name, stored: resolve_model_pricing(
            server_type, model_name, incoming=incoming, existing=stored
        ),
    )
    invalidate_llm_info_cache(model_id=model_id)
    return pricing


def catalog_view() -> dict:
    """The built-in price catalog for the admin "pick a reference price" list."""
    from bisheng.llm.domain.pricing.catalog import load_catalog

    catalog = load_catalog()
    return {"version": catalog.version, "entries": [entry.model_dump() for entry in catalog.entries]}


def match_view(server_type: str, model_name: str) -> dict:
    """Catalog match for the add-model form prefill; ``via_name`` asks the admin to verify."""
    from bisheng.llm.domain.pricing.catalog import load_catalog

    found = match(server_type, model_name)
    return {
        "matched": found is not None,
        "via_name": bool(found and found.via_name),
        "catalog_version": load_catalog().version,
        "entry": found.entry.model_dump() if found else None,
    }
