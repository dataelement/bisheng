"""F015 built-in model price catalog, bundled with each release (never fetched online).

Matching is exact on the provider type plus the normalized model name; dated
snapshot names are listed explicitly instead of being stripped, because a
snapshot can be priced differently from its base model. ``catalog.json`` is
validated on first load, and the test suite keeps the bundled file valid.
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


def match(server_type: str, model_name: str) -> CatalogMatch | None:
    name = normalize_model_name(model_name or "")
    if not name:
        return None
    for entry in load_catalog().entries:
        if server_type in entry.provider_types and name in entry.aliases:
            return CatalogMatch(entry, via_name=server_type == LLMServerType.OPENAI_COMPATIBLE.value)
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
