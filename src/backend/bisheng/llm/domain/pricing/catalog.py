"""F016 built-in model price catalog, bundled with each release (never fetched online).

Matching is exact on the provider type plus the normalized model name; dated
snapshot names are listed explicitly instead of being stripped, because a
snapshot can be priced differently from its base model. Platforms that resell
other vendors' models (``MULTI_VENDOR_PROVIDER_TYPES``) also match those models by
name, and a gateway's vendor prefix ("openai/gpt-5.5") is dropped when the full
name has no entry; such matches carry the vendor's list price and ask the admin to
verify. ``catalog.json`` is validated on first load, and the test suite keeps the
bundled file valid.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bisheng.llm.domain.const import LLMServerType
from bisheng.llm.domain.pricing.schemas import Currency, ModelPricing, Price

CATALOG_PATH = Path(__file__).with_name("catalog.json")
_PROVIDER_TYPES = {item.value for item in LLMServerType}
# 百炼, 方舟, 千帆, TokenHub, 硅基流动 and gateways sell other vendors' models too: every catalog
# model is offered there. Single-vendor APIs (DeepSeek, Kimi, ...) and self-hosted types are not.
MULTI_VENDOR_PROVIDER_TYPES = frozenset(
    item.value
    for item in (
        LLMServerType.OPENAI_COMPATIBLE,
        LLMServerType.QWEN,
        LLMServerType.VOLCENGINE,
        LLMServerType.QIAN_FAN,
        LLMServerType.TENCENT,
        LLMServerType.SILICON,
    )
)


def normalize_model_name(name: str) -> str:
    return name.strip().lower()


class CatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9-]+/[a-z0-9.-]+$", max_length=128)
    vendor: str = Field(min_length=1)
    label: str = Field(min_length=1)
    provider_types: list[str] = Field(min_length=1)
    aliases: list[str] = Field(min_length=1)
    currency: Currency
    input: Price
    cache_read: Price
    cache_write: Price | None = None
    output: Price
    source_url: str = Field(pattern=r"^https://")
    verified_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("provider_types")
    @classmethod
    def known_provider_types(cls, value: list[str]) -> list[str]:
        unknown = set(value) - _PROVIDER_TYPES
        if unknown:
            raise ValueError(f"Unknown provider types: {sorted(unknown)}")
        return value

    @field_validator("aliases")
    @classmethod
    def normalized_aliases(cls, value: list[str]) -> list[str]:
        if any(alias != normalize_model_name(alias) or not alias for alias in value):
            raise ValueError("Aliases must be stored trimmed and lower-case")
        return value


class PriceCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=32)
    entries: list[CatalogEntry]

    @model_validator(mode="after")
    def unique_keys_and_names(self):
        keys, names = set(), set()
        for entry in self.entries:
            if entry.key in keys:
                raise ValueError(f"Duplicate catalog key {entry.key}")
            keys.add(entry.key)
            for provider_type in entry.provider_types:
                for alias in entry.aliases:
                    if (provider_type, alias) in names:
                        raise ValueError(f"Ambiguous catalog name {provider_type}/{alias}")
                    names.add((provider_type, alias))
        return self


class CatalogMatch(NamedTuple):
    entry: CatalogEntry
    # Only the model name matched (OpenAI-compatible gateway): the admin should verify.
    via_name: bool


@lru_cache(maxsize=1)
def load_catalog() -> PriceCatalog:
    return PriceCatalog.model_validate(json.loads(CATALOG_PATH.read_text(encoding="utf-8")))


def _find(server_type: str, name: str) -> tuple[CatalogEntry, bool] | None:
    """The entry for a name, and whether the provider type lists it as its own model."""
    resold = None
    for entry in load_catalog().entries:
        if name in entry.aliases:
            if server_type in entry.provider_types:
                return entry, True
            resold = resold or entry
    if resold is not None and server_type in MULTI_VENDOR_PROVIDER_TYPES:
        return resold, False
    return None


def match(server_type: str, model_name: str) -> CatalogMatch | None:
    name = normalize_model_name(model_name or "")
    # Gateways often prefix the vendor: "openai/gpt-5.5", "deepseek-ai/deepseek-v4-pro".
    for candidate in dict.fromkeys((name, name.rsplit("/", 1)[-1].strip())):
        found = _find(server_type, candidate) if candidate else None
        if found is not None:
            entry, own = found
            gateway = server_type == LLMServerType.OPENAI_COMPATIBLE.value
            return CatalogMatch(entry, via_name=gateway or not own or candidate != name)
    return None


def catalog_pricing(entry: CatalogEntry) -> ModelPricing:
    """Catalog prices as a model price record (source CATALOG)."""
    return ModelPricing(
        currency=entry.currency,
        input=entry.input,
        cache_read=entry.cache_read,
        cache_write=entry.cache_write,
        output=entry.output,
        source="CATALOG",
        catalog_key=entry.key,
        catalog_version=load_catalog().version,
    )
