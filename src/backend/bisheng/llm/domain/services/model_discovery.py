"""Read-only provider discovery with explicit source and bounded pagination."""

import asyncio
import json
import re
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from bisheng.common.errcode.llm import ModelDiscoveryError

from .model_discovery_providers import (
    build_plan,
    next_page,
    prefer_connection_catalog,
    preset_catalog,
    validate_url,
)


class ModelDiscoveryRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    config: dict[str, str | None] = Field(default_factory=dict)
    server_id: int | None = Field(default=None, gt=0)
    source: Literal["auto", "live", "preset"] = "auto"
    # Request-scoped discovery credentials never enter saved inference settings.
    options: dict[str, str] = Field(default_factory=dict, repr=False)


TYPE_ALIASES = {
    "llm": "llm",
    "chat": "llm",
    "completion": "llm",
    "text-generation": "llm",
    "embedding": "embedding",
    "embeddings": "embedding",
    "text-embedding": "embedding",
    "rerank": "rerank",
    "reranking": "rerank",
    "reranker": "rerank",
    "tg": "llm",
    "tr": "embedding",
    "me": "embedding",
    "asr": "asr",
    "realtime-asr": "asr",
    "audio_transcription": "asr",
    "speech-to-text": "asr",
    "transcription": "asr",
    "tts": "tts",
    "audio_speech": "tts",
    "text-to-speech": "tts",
    "speech": "tts",
}


# File clients live in ``_asr_client_type``. Realtime clients live in
# ``_streaming_client_type``, plus Qwen, whose realtime client is constructed
# beside that map. These sets decide asr versus asr_rt; model names do not.
_FILE_ASR_PROVIDERS = frozenset({"openai", "azure_openai", "qwen"})
_REALTIME_ASR_PROVIDERS = frozenset({"volcengine", "qianfan", "tencent", "qwen"})
_REALTIME_TRANSPORTS = frozenset({"websocket", "realtime", "streaming"})
_FILE_TRANSPORTS = frozenset({"file", "batch"})
# These names also match the LLM registry (``glm-`` and ``gpt-``). Keeping them
# unknown is not an asr-versus-asr_rt decision.
_LLM_SHADOWED_SPEECH_NAMES = re.compile(r"^(?:glm-asr|gpt-4o(?:-mini)?-transcribe)")
# Compatible catalogs often have only an id. The task token marks speech; the
# transport token chooses asr_rt. This is not a fixed model-id list.
_SPEECH_NAME = re.compile(r"(?:^|[-_/])(?:asr|paraformer|whisper|sensevoice)(?:$|[-_/])")
_REALTIME_NAME = re.compile(r"(?:^|[-_/])(?:realtime|streaming|websocket)(?:$|[-_/])")


def _raw_capabilities(item: dict) -> list:
    capabilities = item.get("capabilities") or []
    if isinstance(capabilities, dict):
        capabilities = [
            key
            for key, value in capabilities.items()
            if value is True or (isinstance(value, dict) and value.get("supported"))
        ]
    return capabilities if isinstance(capabilities, list) else []


def _metadata_values(item: dict) -> list:
    info = item.get("model_info") or {}
    info = info if isinstance(info, dict) else {}
    return [
        item.get("model_type"),
        item.get("sub_type"),
        item.get("type"),
        item.get("task"),
        item.get("mode"),
        info.get("mode"),
        *_raw_capabilities(item),
    ]


def _capability_tokens(item: dict) -> list[str]:
    return [value.lower() for value in _raw_capabilities(item) if isinstance(value, str)]


def _speech_transports(item: dict) -> set[str]:
    """Transport tokens are not speech-task aliases and are not ``TYPE_ALIASES``.

    Bailian publishes two speech capabilities: ``ASR`` is file recognition and
    ``Realtime-ASR`` is the websocket model. A bare ``model_type`` of ``ASR``
    stays a task alias and does not imply a transport.
    """
    transports = {
        value.lower()
        for value in _metadata_values(item)
        if isinstance(value, str) and value.lower() in _REALTIME_TRANSPORTS | _FILE_TRANSPORTS
    }
    for token in _capability_tokens(item):
        if token == "realtime-asr":
            transports.add("realtime")
        elif token == "asr":
            transports.add("file")
    return transports


def identify_type(item: dict) -> tuple[str | None, str]:
    """Explicit capabilities win; aliases stay unclassified for human review."""
    values = _metadata_values(item)
    kinds = {
        TYPE_ALIASES[value.lower()] for value in values if isinstance(value, str) and value.lower() in TYPE_ALIASES
    }
    if len(kinds) == 1:
        return kinds.pop(), "metadata"
    if len(kinds) > 1:
        return None, "unknown"
    for value in values:
        if isinstance(value, str) and value.lower() in TYPE_ALIASES:
            return TYPE_ALIASES[value.lower()], "metadata"
        if isinstance(value, str) and value.lower() in (
            "image",
            "image_generation",
            "video",
            "video_generation",
            "text-to-image",
            "image-to-image",
            "text-to-video",
            "ig",
            "vg",
            "3d-generation",
        ):
            return None, "unsupported"
    metadata = item.get("inference_metadata") or {}
    metadata = metadata if isinstance(metadata, dict) else {}
    outputs = item.get("output_modalities") or metadata.get("response_modality") or []
    if isinstance(outputs, list) and any(str(value).lower() in {"image", "video"} for value in outputs):
        return None, "unsupported"
    name = str(item.get("id") or item.get("name") or "").lower().split("/")[-1]
    if re.match(
        r"^(?:gpt-image|dall-e|flux|stable-diffusion|sora|glm-image|cogview|cogvideox|doubao-seedream|doubao-seedance|gemini[^/]*-image)",
        name,
    ):
        return None, "unsupported"
    if _LLM_SHADOWED_SPEECH_NAMES.match(name):
        return None, "unknown"
    registry = (
        ("rerank", r"^(?:bge-reranker|qwen3-reranker|rerank|jina-reranker)"),
        (
            "embedding",
            r"^(?:text-embedding|embedding|hunyuan-embedding|doubao-embedding|gemini-embedding|bge-(?:m3|large|base|small)|qwen3-embedding|nomic-embed|mxbai-embed|jina-embeddings|all-minilm)",
        ),
        ("tts", r"^(?:glm-tts|tts-1|cosyvoice|gpt-4o-mini-tts|qwen[^/]*-tts|gemini[^/]*-tts)"),
        (
            "llm",
            r"^(?:gpt-|chatgpt-|o[134](?:-|$)|claude-|deepseek-(?:chat|reasoner|flash|pro|coder|r\d|v\d)|qwen(?:[0-9.]+)?-(?:turbo|plus|max|chat|\d+(?:\.\d+)?b|coder|vl|omni|next|instruct|flash|thinking)|doubao-(?:\d+(?:[-.]\d+)*-)?(?:seed(?:[-.]|$)|pro|lite|vision|thinking|ui-tars)|gemini-[\d.]|llama[\d.-]*|gemma[\d.-]*|mistral|mixtral|moonshot-|kimi-|glm-|minimax-m|hunyuan-)",
        ),
    )
    for kind, pattern in registry:
        if re.match(pattern, name):
            return kind, "registry"
    return None, "unknown"


def normalize_catalog(payload: dict, provider: str) -> list[dict]:
    raw = payload.get("models") if provider == "ollama" else payload.get("data")
    if provider == "xinference" and "data" not in payload:
        raw = payload
    if not isinstance(raw, (list, dict)):
        raise ModelDiscoveryError(reason="format")
    if isinstance(raw, dict):
        raw = [{**value, "id": key} for key, value in raw.items() if isinstance(value, dict)]
    models = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id") or item.get("name") or item.get("model_uid")
        if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 100:
            continue
        if item.get("lifecycle") == "retired":
            continue
        model_id = model_id.strip()
        classified = {**item, "id": item.get("classification_name") or model_id}
        kind, source = identify_type(classified)
        row = {
            "model_name": model_id,
            "display_name": str(item.get("display_name") or model_id)[:200],
            "model_type": kind,
            "type_source": source,
        }
        transports = _speech_transports(classified)
        if transports:
            row["_transports"] = transports
        models[model_id] = row
    return sorted(models.values(), key=lambda model: model["model_name"].lower())


def _compatible_speech_transports(model_name: str) -> set[str] | None:
    """Speech task plus transport words in an id-only compatible catalog row."""
    name = model_name.lower().split("/")[-1]
    if not _SPEECH_NAME.search(name):
        return None
    if _REALTIME_NAME.search(name):
        return {"realtime"}
    return {"file"}


def assign_speech_type(model: dict, provider: str) -> None:
    """Rewrite the internal speech marker using the real provider, not catalog names."""
    transports = set(model.pop("_transports", ()))
    named = None
    if (
        model.get("model_type") is None
        and model.get("type_source") == "unknown"
        and provider in _FILE_ASR_PROVIDERS & _REALTIME_ASR_PROVIDERS
    ):
        named = _compatible_speech_transports(str(model.get("model_name") or ""))
        if named is not None:
            model["model_type"] = "asr"
            model["type_source"] = "metadata"
            transports |= named
    if model.get("model_type") != "asr" or model.get("type_source") != "metadata":
        return
    realtime = bool(set(transports) & _REALTIME_TRANSPORTS)
    file_transport = bool(set(transports) & _FILE_TRANSPORTS)
    has_realtime = provider in _REALTIME_ASR_PROVIDERS
    has_file = provider in _FILE_ASR_PROVIDERS
    if realtime and file_transport:
        if has_realtime and has_file:
            model["model_type"] = None
            model["type_source"] = "speech"
        elif has_realtime:
            model["model_type"] = "asr_rt"
        elif has_file:
            model["model_type"] = "asr"
        else:
            model["model_type"] = None
            model["type_source"] = "unsupported"
        return
    if realtime and has_realtime:
        model["model_type"] = "asr_rt"
        return
    if file_transport and has_file:
        model["model_type"] = "asr"
        return
    if has_file and has_realtime:
        model["model_type"] = None
        model["type_source"] = "speech"
    elif has_file:
        model["model_type"] = "asr"
    elif has_realtime:
        model["model_type"] = "asr_rt"
    else:
        model["model_type"] = None
        model["type_source"] = "unsupported"


def _publish_speech_types(models, provider: str) -> None:
    for model in models:
        assign_speech_type(model, provider)


async def read_catalog(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> dict:
    try:
        async with client.stream(method, url, **kwargs) as response:
            if response.status_code in {401, 403}:
                raise ModelDiscoveryError(reason="auth")
            if response.status_code in {404, 405, 501}:
                raise ModelDiscoveryError(reason="unsupported")
            if response.status_code == 429:
                raise ModelDiscoveryError(reason="rate_limit")
            if response.status_code >= 300:
                raise ModelDiscoveryError()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 4 * 1024 * 1024:
                    raise ModelDiscoveryError(reason="limit")
            payload = json.loads(content)
    except httpx.TimeoutException:
        raise ModelDiscoveryError(reason="timeout") from None
    except httpx.HTTPError:
        raise ModelDiscoveryError(reason="connection") from None
    except (ValueError, TypeError, UnicodeError):
        raise ModelDiscoveryError(reason="format") from None
    if not isinstance(payload, dict):
        raise ModelDiscoveryError(reason="format")
    metadata = payload.get("ResponseMetadata") or {}
    if not isinstance(metadata, dict):
        raise ModelDiscoveryError(reason="format")
    if payload.get("error") or payload.get("success") is False or metadata.get("Error"):
        raise ModelDiscoveryError()
    return payload


async def enrich_silicon(client: httpx.AsyncClient, url: str, headers: dict, models: dict) -> None:
    """The official list exposes capability through filters, rather than row fields."""
    subtypes = ["chat", "embedding", "reranker", "speech-to-text", "text-to-image", "image-to-image", "text-to-video"]

    async def fetch(subtype):
        return await read_catalog(client, "GET", url, headers=headers, params={"sub_type": subtype})

    responses = await asyncio.gather(*(fetch(subtype) for subtype in subtypes))
    capabilities: dict[str, set[tuple[str | None, str]]] = {}
    for subtype, payload in zip(subtypes, responses, strict=True):
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ModelDiscoveryError(reason="format")
        for row in rows:
            if isinstance(row, dict) and row.get("id") in models:
                capabilities.setdefault(row["id"], set()).add(identify_type({"sub_type": subtype}))
    for name, kinds in capabilities.items():
        kind, source = next(iter(kinds)) if len(kinds) == 1 else (None, "unknown")
        models[name].update(model_type=kind, type_source=source)


class ModelDiscoveryService:
    @classmethod
    async def discover(cls, provider: str, config: dict, *, source="auto", options=None) -> dict:
        try:
            async with asyncio.timeout(55):
                return await cls._discover(provider, config, source, options or {})
        except TimeoutError:
            raise ModelDiscoveryError(reason="timeout") from None

    @classmethod
    async def _discover(cls, provider: str, config: dict, source: str, options: dict) -> dict:
        if source == "auto" and prefer_connection_catalog(provider, config, options):
            try:
                return await cls._fetch_catalog(provider, config, "live", options)
            except ModelDiscoveryError as error:
                if error.kwargs.get("reason") != "unsupported":
                    raise
                # An unsupported list route selects the provider's native discovery contract.
        return await cls._fetch_catalog(provider, config, source, options)

    @classmethod
    async def _fetch_catalog(cls, provider: str, config: dict, source: str, options: dict) -> dict:
        plan = build_plan(provider, config, source, options)
        if plan.protocol == "preset":
            payload, docs = preset_catalog(provider)
            models = normalize_catalog(payload, provider)
            _publish_speech_types(models, provider)
            return {
                "models": models,
                "source": "preset",
                "scope": "catalog",
                "catalog_date": "2026-10-21",
                "docs_url": docs,
            }
        proxy = config.get("openai_proxy") or None
        if proxy:
            validate_url(proxy)
        models = {}
        seen_pages = set()
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, proxy=proxy, trust_env=False) as client:
            for _ in range(50):
                method, url, kwargs = plan.request(options)
                payload = await read_catalog(client, method, url, **kwargs)
                normalized, more = next_page(plan, payload)
                page_models = normalize_catalog(
                    normalized,
                    "ollama" if provider == "ollama" else "xinference" if provider == "xinference" else "openai",
                )
                fingerprint = tuple(model["model_name"] for model in page_models)
                if fingerprint and fingerprint in seen_pages:
                    raise ModelDiscoveryError(reason="format")
                seen_pages.add(fingerprint)
                for model in page_models:
                    models[model["model_name"]] = model
                if len(models) > 5000:
                    raise ModelDiscoveryError(reason="limit")
                if not more:
                    if provider == "silicon" and urlsplit(plan.url).hostname in {
                        "api.siliconflow.cn",
                        "api.siliconflow.com",
                    }:
                        await enrich_silicon(client, plan.url, plan.headers, models)
                    _publish_speech_types(models.values(), provider)
                    return {
                        "models": sorted(models.values(), key=lambda model: model["model_name"].lower()),
                        "source": "live",
                        "scope": plan.scope,
                    }
        raise ModelDiscoveryError(reason="limit")
