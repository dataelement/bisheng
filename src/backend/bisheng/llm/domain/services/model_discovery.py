"""Read-only provider catalog discovery and conservative capability matching."""

import asyncio
import ipaddress
import json
import re
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field

from bisheng.common.errcode.llm import ModelDiscoveryError


class ModelDiscoveryRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    config: dict[str, str | None] = Field(default_factory=dict)
    server_id: int | None = Field(default=None, gt=0)


DEFAULT_BASES = {
    "openai": "https://api.openai.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "silicon": "https://api.siliconflow.cn/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "qianfan": "https://qianfan.baidubce.com/v2",
    "anthropic": "https://api.anthropic.com/v1",
}
COMPATIBLE = {
    "openai",
    "qwen",
    "deepseek",
    "silicon",
    "moonshot",
    "zhipu",
    "qianfan",
    "vllm",
    "xinference",
    "llamacpp",
    "MindIE",
}
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
    "asr": "asr",
    "audio_transcription": "asr",
    "speech-to-text": "asr",
    "transcription": "asr",
    "tts": "tts",
    "audio_speech": "tts",
    "text-to-speech": "tts",
    "speech": "tts",
}


def identify_type(item: dict) -> tuple[str | None, str]:
    """Explicit capabilities win; aliases stay unclassified for human review."""
    info = item.get("model_info") or {}
    info = info if isinstance(info, dict) else {}
    for value in (item.get("model_type"), item.get("type"), item.get("task"), item.get("mode"), info.get("mode")):
        if isinstance(value, str) and value.lower() in TYPE_ALIASES:
            return TYPE_ALIASES[value.lower()], "metadata"
        if value in ("image", "image_generation", "video", "video_generation", "text-to-image"):
            return None, "unsupported"
    name = str(item.get("id") or item.get("name") or "").lower().split("/")[-1]
    if re.match(
        r"^(?:gpt-image|dall-e|flux|stable-diffusion|sora|doubao-seedream|doubao-seedance|gemini[^/]*-image)", name
    ):
        return None, "unsupported"
    registry = (
        ("rerank", r"^(?:bge-reranker|qwen3-reranker|rerank|jina-reranker)"),
        (
            "embedding",
            r"^(?:text-embedding|embedding|doubao-embedding|gemini-embedding|bge-(?:m3|large|base|small)|qwen3-embedding|nomic-embed|mxbai-embed|jina-embeddings|all-minilm)",
        ),
        ("asr", r"^(?:whisper|paraformer|sensevoice|fun-asr|qwen[^/]*-asr|gpt-4o(?:-mini)?-transcribe)"),
        ("tts", r"^(?:tts-1|cosyvoice|gpt-4o-mini-tts|qwen[^/]*-tts|gemini[^/]*-tts)"),
        (
            "llm",
            r"^(?:gpt-|chatgpt-|o[134](?:-|$)|claude-|deepseek-(?:chat|reasoner|flash|pro|coder|r\d|v\d)|qwen(?:[0-9.]+)?-(?:turbo|plus|max|chat|\d+(?:\.\d+)?b|coder|vl|omni|next|instruct|flash|thinking)|doubao-(?:\d+(?:[-.]\d+)*-)?(?:seed(?:[-.]|$)|pro|lite|vision|thinking|ui-tars)|gemini-[\d.]|llama[\d.-]*|gemma[\d.-]*|mistral|mixtral|moonshot-|kimi-|glm-)",
        ),
    )
    for kind, pattern in registry:
        if re.match(pattern, name):
            return kind, "registry"
    return None, "unknown"


def connection(provider: str, config: dict) -> tuple[str, dict]:
    if provider not in COMPATIBLE | {"ollama", "anthropic"}:
        raise ModelDiscoveryError(msg="This provider requires manual model configuration.", reason="unsupported")
    base = (
        (
            config.get("openai_api_base")
            or config.get("base_url")
            or config.get("host_base_url")
            or DEFAULT_BASES.get(provider)
            or ""
        )
        .strip()
        .rstrip("/")
    )
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ModelDiscoveryError(msg="Enter a valid HTTP or HTTPS API base URL.", reason="address")
    if parsed.hostname == "metadata.google.internal":
        raise ModelDiscoveryError(msg="Enter a model service API base URL.", reason="address")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address and (address.is_link_local or str(address) == "100.100.100.200"):
        raise ModelDiscoveryError(msg="Enter a model service API base URL.", reason="address")
    key = (
        config.get("openai_api_key")
        or config.get("api_key")
        or config.get("siliconflow_api_key")
        or config.get("anthropic_api_key")
        or ""
    ).strip()
    if key and set(key) == {"*"}:
        raise ModelDiscoveryError(msg="Enter the API key for this connection.", reason="auth")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    if provider == "anthropic":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    if provider == "ollama":
        path = parsed.path.rstrip("/")
        path = path[:-3] if path.endswith("/v1") else path
        path = path[:-4] if path.endswith("/api") else path
        url = urlunsplit((parsed.scheme, parsed.netloc, path + "/api/tags", "", ""))
    else:
        url = base if base.endswith("/models") else base + "/models"
    return url, headers


def normalize_catalog(payload: dict, provider: str) -> list[dict]:
    raw = payload.get("models") if provider == "ollama" else payload.get("data")
    if provider == "xinference" and "data" not in payload:
        raw = payload
    if not isinstance(raw, (list, dict)):
        raise ModelDiscoveryError(msg="The API returned an unsupported model list format.", reason="format")
    if isinstance(raw, dict):
        raw = [{**value, "id": key} for key, value in raw.items() if isinstance(value, dict)]
    models = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id") or item.get("name") or item.get("model_uid")
        if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 100:
            continue
        model_id = model_id.strip()
        kind, source = identify_type({**item, "id": model_id})
        models[model_id] = {
            "model_name": model_id,
            "display_name": str(item.get("display_name") or model_id)[:200],
            "model_type": kind,
            "type_source": source,
        }
    return sorted(models.values(), key=lambda model: model["model_name"].lower())


class ModelDiscoveryService:
    @classmethod
    async def discover(cls, provider: str, config: dict) -> dict:
        try:
            async with asyncio.timeout(55):
                return await cls._discover(provider, config)
        except TimeoutError:
            raise ModelDiscoveryError(
                msg="Fetching models timed out. Check the API address and retry.", reason="timeout"
            ) from None

    @classmethod
    async def _discover(cls, provider: str, config: dict) -> dict:
        url, headers = connection(provider, config)
        proxy = config.get("openai_proxy") or None
        if proxy:
            proxy_url = urlsplit(proxy)
            if (
                proxy_url.scheme not in {"http", "https"}
                or not proxy_url.hostname
                or proxy_url.query
                or proxy_url.fragment
            ):
                raise ModelDiscoveryError(msg="Enter a valid HTTP or HTTPS proxy API base URL.", reason="address")
        models = {}
        params = {"limit": 1000} if provider == "anthropic" else {}
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, proxy=proxy, trust_env=False) as client:
            for _ in range(50):
                try:
                    async with client.stream("GET", url, headers=headers, params=params) as response:
                        if response.status_code in {401, 403}:
                            raise ModelDiscoveryError(
                                msg="The model service rejected this API key or its permissions.", reason="auth"
                            )
                        if response.status_code == 404:
                            raise ModelDiscoveryError(
                                msg="This API address provides no model list. Use manual configuration.",
                                reason="unsupported",
                            )
                        if response.status_code >= 300:
                            raise ModelDiscoveryError(msg="The model service is temporarily unavailable. Retry later.")
                        content = bytearray()
                        async for chunk in response.aiter_bytes():
                            content.extend(chunk)
                            if len(content) > 4 * 1024 * 1024:
                                raise ModelDiscoveryError(
                                    msg="The model list exceeds the response size limit.", reason="limit"
                                )
                        payload = json.loads(content)
                except httpx.TimeoutException:
                    raise ModelDiscoveryError(
                        msg="Fetching models timed out. Check the API address and retry.", reason="timeout"
                    ) from None
                except httpx.HTTPError:
                    raise ModelDiscoveryError(
                        msg="Unable to connect to the model service. Check the address and retry.", reason="connection"
                    ) from None
                except (ValueError, TypeError):
                    raise ModelDiscoveryError(
                        msg="The API returned an unsupported model list format.", reason="format"
                    ) from None
                if not isinstance(payload, dict):
                    raise ModelDiscoveryError()
                for model in normalize_catalog(payload, provider):
                    models[model["model_name"]] = model
                if len(models) > 5000:
                    raise ModelDiscoveryError(msg="The model list exceeds the model count limit.", reason="limit")
                if not payload.get("has_more"):
                    return {"models": sorted(models.values(), key=lambda model: model["model_name"].lower())}
                cursor = payload.get("last_id")
                if not cursor or cursor == params.get("after_id"):
                    raise ModelDiscoveryError(
                        msg="The model service returned an invalid pagination cursor.", reason="format"
                    )
                params["after_id"] = cursor
        raise ModelDiscoveryError(msg="The model list exceeds the page count limit.", reason="limit")
