"""Read a model's context window from its provider's model-info API (F087).

Each probe uses only the base URL and API key the chat client already resolved
(``BishengLLM._get_llm_params``), so it needs no extra credentials. The endpoints
and field paths come from the provider survey in
``features/v3.0.0/087-context-window-budget/plan.md`` §3.1.

A probe returns ``None`` whenever it cannot find a trustworthy number: missing
field, unknown model, HTTP error or timeout. It never guesses.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote

import httpx
from loguru import logger

from bisheng.llm.domain.const import LLMServerType

if TYPE_CHECKING:
    from bisheng.llm.domain.services.context_window import ModelSnapshot

PROBE_TIMEOUT_SECONDS = 3.0

# "total": the window covers input and output. "input": the number is already
# an input-only limit (Anthropic's max_input_tokens) and must not be reduced again.
WindowKind = Literal["total", "input"]
# "deployed": what the serving engine actually enforces. "published": the
# model's or platform's advertised limit, which a deployment may have lowered.
ProbeSource = Literal["deployed", "published"]

_OFFICIAL_OPENAI_HOSTS = ("api.openai.com",)


@dataclass(frozen=True)
class ProbeResult:
    window: int
    kind: WindowKind
    source: ProbeSource


ProbeFn = Callable[["ModelSnapshot", httpx.AsyncClient], Awaitable[ProbeResult | None]]


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _base_url(params: dict) -> str:
    url = params.get("base_url") or params.get("openai_api_base") or params.get("api_base") or ""
    return str(url).rstrip("/")


def _bearer(params: dict) -> dict:
    key = params.get("api_key") or params.get("openai_api_key")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _strip_v1(url: str) -> str:
    return url[: -len("/v1")] if url.endswith("/v1") else url


async def _get_json(client: httpx.AsyncClient, url: str, headers: dict | None = None) -> Any:
    response = await client.get(url, headers=headers or {})
    response.raise_for_status()
    return response.json()


def _model_entries(payload: Any) -> list[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [entry for entry in payload["data"] if isinstance(entry, dict)]
    return []


def _find_entry(entries: list[dict], model_name: str) -> dict | None:
    for entry in entries:
        if entry.get("id") == model_name:
            return entry
    return None


async def _probe_openai_models(snapshot: ModelSnapshot, client: httpx.AsyncClient) -> ProbeResult | None:
    """``GET <base>/models`` on an OpenAI-compatible server.

    vLLM and SGLang add ``max_model_len`` (the deployed limit); Moonshot, Xinference
    and OpenRouter add ``context_length`` (the advertised limit). A vLLM LoRA
    adapter entry carries ``max_model_len: null`` and points at its base model
    through ``parent``.
    """
    base = _base_url(snapshot.client_params)
    if not base:
        return None
    entries = _model_entries(await _get_json(client, f"{base}/models", _bearer(snapshot.client_params)))
    entry = _find_entry(entries, snapshot.model_name)
    if entry is None:
        return None
    window = _positive_int(entry.get("max_model_len"))
    if window is None and entry.get("parent"):
        parent = _find_entry(entries, entry["parent"])
        window = _positive_int(parent.get("max_model_len")) if parent else None
    if window is not None:
        return ProbeResult(window=window, kind="total", source="deployed")
    window = _positive_int(entry.get("context_length"))
    if window is not None:
        return ProbeResult(window=window, kind="total", source="published")
    return None


async def _probe_openai_type(snapshot: ModelSnapshot, client: httpx.AsyncClient) -> ProbeResult | None:
    """The ``openai`` server type: only worth probing when it points at a self-hosted
    or third-party OpenAI-compatible server. OpenAI's own API has no such field."""
    base = _base_url(snapshot.client_params)
    if not base or any(host in base for host in _OFFICIAL_OPENAI_HOSTS):
        return None
    return await _probe_openai_models(snapshot, client)


async def _probe_llamacpp(snapshot: ModelSnapshot, client: httpx.AsyncClient) -> ProbeResult | None:
    """llama.cpp server: ``GET /props`` gives the per-slot ``n_ctx`` actually in force."""
    base = _base_url(snapshot.client_params)
    if not base:
        return None
    root = _strip_v1(base)
    try:
        props = await _get_json(client, f"{root}/props", _bearer(snapshot.client_params))
        settings = props.get("default_generation_settings") if isinstance(props, dict) else None
        window = _positive_int(settings.get("n_ctx")) if isinstance(settings, dict) else None
        if window is not None:
            return ProbeResult(window=window, kind="total", source="deployed")
    except (httpx.HTTPError, ValueError):
        logger.opt(exception=True).debug("llama.cpp /props unavailable, trying /v1/models")
    entries = _model_entries(await _get_json(client, f"{root}/v1/models", _bearer(snapshot.client_params)))
    entry = _find_entry(entries, snapshot.model_name) or (entries[0] if len(entries) == 1 else None)
    meta = entry.get("meta") if entry else None
    window = _positive_int(meta.get("n_ctx")) if isinstance(meta, dict) else None
    return ProbeResult(window=window, kind="total", source="deployed") if window else None


async def _probe_xinference(snapshot: ModelSnapshot, client: httpx.AsyncClient) -> ProbeResult | None:
    """Xinference lists the model family's registered ``context_length`` — the
    advertised limit, not any context length the model was launched with."""
    base = _base_url(snapshot.client_params)
    if not base:
        return None
    entries = _model_entries(await _get_json(client, f"{base}/models", _bearer(snapshot.client_params)))
    entry = _find_entry(entries, snapshot.model_name)
    window = _positive_int(entry.get("context_length")) if entry else None
    return ProbeResult(window=window, kind="total", source="published") if window else None


def _ollama_names_match(name: str, model_name: str) -> bool:
    # Ollama reports "qwen3:latest" for a model configured as "qwen3".
    return name == model_name or name == f"{model_name}:latest"


def _num_ctx_from_parameters(parameters: Any) -> int | None:
    if not isinstance(parameters, str):
        return None
    for line in parameters.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "num_ctx" and parts[1].isdigit():
            return _positive_int(int(parts[1]))
    return None


async def _probe_ollama(snapshot: ModelSnapshot, client: httpx.AsyncClient) -> ProbeResult | None:
    """Ollama's served window is ``num_ctx``, which only ``/api/ps`` reports, and only
    while the model is loaded. Otherwise fall back to a ``num_ctx`` set in the
    Modelfile, then to the GGUF's trained context length (advertised value)."""
    base = _strip_v1(_base_url(snapshot.client_params))
    if not base:
        return None
    running = await _get_json(client, f"{base}/api/ps")
    for entry in running.get("models", []) if isinstance(running, dict) else []:
        if isinstance(entry, dict) and _ollama_names_match(
            str(entry.get("name") or entry.get("model")), snapshot.model_name
        ):
            window = _positive_int(entry.get("context_length"))
            if window is not None:
                return ProbeResult(window=window, kind="total", source="deployed")
    response = await client.post(f"{base}/api/show", json={"model": snapshot.model_name})
    response.raise_for_status()
    shown = response.json()
    if not isinstance(shown, dict):
        return None
    window = _num_ctx_from_parameters(shown.get("parameters"))
    if window is not None:
        return ProbeResult(window=window, kind="total", source="deployed")
    model_info = shown.get("model_info")
    if isinstance(model_info, dict):
        for key, value in model_info.items():
            if key.endswith(".context_length") and _positive_int(value):
                return ProbeResult(window=value, kind="total", source="published")
    return None


async def _probe_anthropic(snapshot: ModelSnapshot, client: httpx.AsyncClient) -> ProbeResult | None:
    """Anthropic's model API returns ``max_input_tokens``: already an input-only limit."""
    params = snapshot.client_params
    base = str(params.get("anthropic_api_url") or params.get("base_url") or "https://api.anthropic.com").rstrip("/")
    key = params.get("anthropic_api_key") or params.get("api_key")
    if not key:
        return None
    headers = {"x-api-key": str(key), "anthropic-version": "2023-06-01"}
    model = quote(snapshot.model_name, safe="")
    payload = await _get_json(client, f"{_strip_v1(base)}/v1/models/{model}", headers)
    window = _positive_int(payload.get("max_input_tokens")) if isinstance(payload, dict) else None
    return ProbeResult(window=window, kind="input", source="published") if window else None


async def _probe_deepseek(snapshot: ModelSnapshot, client: httpx.AsyncClient) -> ProbeResult | None:
    """DeepSeek's ``/models`` reports ``context_window`` (input plus output)."""
    base = _base_url(snapshot.client_params)
    if not base:
        return None
    entries = _model_entries(await _get_json(client, f"{base}/models", _bearer(snapshot.client_params)))
    entry = _find_entry(entries, snapshot.model_name)
    window = _positive_int(entry.get("context_window")) if entry else None
    return ProbeResult(window=window, kind="total", source="published") if window else None


async def _probe_moonshot(snapshot: ModelSnapshot, client: httpx.AsyncClient) -> ProbeResult | None:
    """Moonshot (Kimi) adds ``context_length`` to its OpenAI-style model list."""
    base = _base_url(snapshot.client_params)
    if not base:
        return None
    entries = _model_entries(await _get_json(client, f"{base}/models", _bearer(snapshot.client_params)))
    entry = _find_entry(entries, snapshot.model_name)
    window = _positive_int(entry.get("context_length")) if entry else None
    return ProbeResult(window=window, kind="total", source="published") if window else None


PROBES: dict[str, ProbeFn] = {
    LLMServerType.VLLM.value: _probe_openai_models,
    LLMServerType.OPENAI.value: _probe_openai_type,
    LLMServerType.LLAMACPP.value: _probe_llamacpp,
    LLMServerType.OLLAMA.value: _probe_ollama,
    LLMServerType.XINFERENCE.value: _probe_xinference,
    LLMServerType.ANTHROPIC.value: _probe_anthropic,
    LLMServerType.DEEPSEEK.value: _probe_deepseek,
    LLMServerType.MOONSHOT.value: _probe_moonshot,
}


def _proxy(params: dict) -> str | None:
    proxy = params.get("openai_proxy")
    return str(proxy) if proxy else None


async def probe_context_window(snapshot: ModelSnapshot, client: httpx.AsyncClient | None = None) -> ProbeResult | None:
    """Ask the provider for the model's context window; ``None`` when it cannot say."""
    probe = PROBES.get(snapshot.server_type)
    if probe is None:
        return None
    try:
        if client is not None:
            return await probe(snapshot, client)
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS, proxy=_proxy(snapshot.client_params)) as owned:
            return await probe(snapshot, owned)
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, TypeError, KeyError, AttributeError) as exc:
        # Unreachable endpoint, timeout, non-2xx, non-JSON or unexpectedly shaped
        # body (e.g. Ollama's `{"models": null}`): no reliable number.
        logger.warning(
            "[linsight-context-window] probe failed model_id={} server_type={}: {}: {}",
            snapshot.model_id,
            snapshot.server_type,
            type(exc).__name__,
            exc,
        )
        return None
    except Exception as exc:
        # Anything else is a probe bug, not a provider answer. Log the type only:
        # a traceback's local variables would include the Authorization header.
        logger.warning(
            "[linsight-context-window] probe crashed model_id={} server_type={}: {}",
            snapshot.model_id,
            snapshot.server_type,
            type(exc).__name__,
        )
        return None
