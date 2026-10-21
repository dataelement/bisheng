"""Provider request plans. Catalog-only credentials are isolated from inference configuration."""

import hashlib
import hmac
import ipaddress
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit, urlunsplit

from bisheng.common.errcode.llm import ModelDiscoveryError

from .model_discovery_presets import PRESETS, preset_catalog

DEFAULT_BASES = {
    "openai": "https://api.openai.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "silicon": "https://api.siliconflow.cn/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "qianfan": "https://qianfan.baidubce.com/v2",
    "anthropic": "https://api.anthropic.com/v1",
    "volcengine": "https://ark.cn-beijing.volces.com/api/v3",
    "tencent": "https://api.hunyuan.cloud.tencent.com/v1",
    "spark": "https://spark-api-open.xf-yun.com/v1",
    "minimax": "https://api.minimax.cn/v1",
}
PROVIDERS = set(DEFAULT_BASES) | {"azure_openai", "ollama", "xinference", "vllm", "llamacpp", "MindIE"}


def validate_url(url: str):
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise ModelDiscoveryError(reason="address") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (port is not None and port < 1)
    ):
        raise ModelDiscoveryError(reason="address")
    if parsed.hostname == "metadata.google.internal":
        raise ModelDiscoveryError(reason="address")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address and (address.is_link_local or str(address) == "100.100.100.200"):
        raise ModelDiscoveryError(reason="address")
    return parsed


def credential(value: str | None) -> str:
    value = (value or "").strip()
    if value and (set(value) == {"*"} or not value.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ModelDiscoveryError(reason="auth")
    return value


def base_url(provider: str, config: dict) -> str:
    if provider not in PROVIDERS:
        raise ModelDiscoveryError(reason="unsupported")
    # Each provider consumes the same address field as its inference adapter.
    specific = {"azure_openai": "azure_endpoint", "anthropic": "anthropic_api_url"}.get(provider)
    base = (
        (config.get(specific) if specific else None)
        or config.get("openai_api_base")
        or config.get("base_url")
        or DEFAULT_BASES.get(provider)
        or ""
    )
    base = base.strip().rstrip("/")
    validate_url(base)
    return base


def connection(provider: str, config: dict) -> tuple[str, dict]:
    base = base_url(provider, config)
    parsed = urlsplit(base)
    key = credential(
        config.get("openai_api_key")
        or config.get("api_key")
        or config.get("siliconflow_api_key")
        or config.get("anthropic_api_key")
    )
    if provider == "spark" and config.get("api_secret"):
        key += ":" + credential(config["api_secret"])
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    if provider == "anthropic":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        if parsed.path in {"", "/"}:
            base += "/v1"
    if provider == "azure_openai":
        headers = {"api-key": key}
        path = parsed.path.rstrip("/")
        if path.endswith("/openai/v1"):
            base += "/models"
        elif path.endswith("/openai"):
            base += "/v1/models"
        else:
            base += "/openai/v1/models"
        return base, headers
    if provider == "ollama":
        path = parsed.path.rstrip("/")
        path = path[:-3] if path.endswith("/v1") else path
        path = path[:-4] if path.endswith("/api") else path
        return urlunsplit((parsed.scheme, parsed.netloc, path + "/api/tags", "", "")), headers
    if provider in {"xinference", "vllm", "llamacpp", "MindIE"} and parsed.path in {"", "/"}:
        base += "/v1"
    return base if base.endswith("/models") else base + "/models", headers


def sign_ark(url: str, body: str, options: dict, now: datetime | None = None) -> dict:
    """Volcengine v4: hash the exact bytes passed to the HTTP transport."""
    ak = credential(options.get("access_key_id"))
    sk = credential(options.get("secret_access_key"))
    if not ak or not sk:
        raise ModelDiscoveryError(reason="credentials")
    region = options.get("region") or "cn-beijing"
    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(body.encode()).hexdigest()
    parsed = urlsplit(url)
    headers = {
        "content-type": "application/json",
        "host": parsed.netloc,
        "x-content-sha256": digest,
        "x-date": timestamp,
    }
    if options.get("session_token"):
        headers["x-security-token"] = credential(options["session_token"])
    signed = ";".join(sorted(headers))
    canonical = "\n".join(
        ["POST", "/", parsed.query, "".join(f"{key}:{headers[key]}\n" for key in sorted(headers)), signed, digest]
    )
    scope = f"{timestamp[:8]}/{region}/ark/request"
    string_to_sign = "\n".join(["HMAC-SHA256", timestamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    signing_key = sk.encode()
    for component in (timestamp[:8], region, "ark", "request"):
        signing_key = hmac.new(signing_key, component.encode(), hashlib.sha256).digest()
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers["Authorization"] = f"HMAC-SHA256 Credential={ak}/{scope}, SignedHeaders={signed}, Signature={signature}"
    return headers


@dataclass
class CatalogPlan:
    url: str
    headers: dict
    protocol: str = "compatible"
    scope: str = "catalog"
    params: dict = field(default_factory=dict)
    page: int = 1
    seen: int = 0
    next_url: str | None = None

    def request(self, options: dict) -> tuple[str, str, dict]:
        if self.protocol == "ark":
            body = {"PageNumber": self.page, "PageSize": 100, "Filter": {"Statuses": ["Running"]}}
            if options.get("project_name"):
                body["ProjectName"] = options["project_name"].strip()
            content = json.dumps(body, separators=(",", ":"), ensure_ascii=True)
            return "POST", self.url, {"headers": sign_ark(self.url, content, options), "content": content}
        if self.protocol == "bailian":
            self.params = {"page_no": self.page, "page_size": 100}
        return "GET", self.next_url or self.url, {"headers": self.headers, "params": self.params or None}


def build_plan(provider: str, config: dict, source: str, options: dict) -> CatalogPlan:
    base = base_url(provider, config)
    host = urlsplit(base).hostname
    if source == "preset" or (source == "auto" and provider in PRESETS and host in PRESETS[provider]["hosts"]):
        preset_catalog(provider)
        return CatalogPlan(base, {}, "preset")
    url, headers = connection(provider, config)
    plan = CatalogPlan(url, headers)
    if provider == "anthropic":
        plan.params = {"limit": 1000}
    if provider in {"ollama", "xinference", "llamacpp", "vllm", "MindIE"}:
        plan.scope = "local"
    if provider == "qwen" and source == "auto":
        native = options.get("catalog_url", "").strip().rstrip("/")
        if not native and host == "dashscope.aliyuncs.com":
            workspace = options.get("workspace_id", "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]+", workspace):
                raise ModelDiscoveryError(reason="workspace")
            native = f"https://{workspace}.cn-beijing.maas.aliyuncs.com/api/v1/models"
        elif not native and host in {"dashscope-intl.aliyuncs.com", "cn-hongkong.dashscope.aliyuncs.com"}:
            native = f"https://{host}/api/v1/models"
        elif not native and host.endswith(".maas.aliyuncs.com"):
            native = f"https://{host}/api/v1/models"
        if native:
            validate_url(native)
            plan = CatalogPlan(native, headers, "bailian")
    if provider == "volcengine" and source == "auto" and host == "ark.cn-beijing.volces.com":
        region = options.get("region") or "cn-beijing"
        if region != "cn-beijing":
            raise ModelDiscoveryError(reason="region")
        url = "https://ark.cn-beijing.volcengineapi.com/?" + urlencode(
            {"Action": "ListEndpoints", "Version": "2024-01-01"}
        )
        plan = CatalogPlan(url, {}, "ark", "deployments")
    if provider == "azure_openai":
        plan.scope = "azure_models"
        if options.get("resource_id") or options.get("management_token"):
            resource = options.get("resource_id", "").strip().rstrip("/")
            if not re.fullmatch(
                r"/subscriptions/[A-Za-z0-9-]+/resourceGroups/[A-Za-z0-9_.()-]+/providers/Microsoft.CognitiveServices/accounts/[A-Za-z0-9_.-]+",
                resource,
            ):
                raise ModelDiscoveryError(reason="resource")
            token = credential(options.get("management_token"))
            if not token:
                raise ModelDiscoveryError(reason="credentials")
            url = f"https://management.azure.com{resource}/deployments"
            plan = CatalogPlan(
                url,
                {"Authorization": f"Bearer {token}"},
                "azure_deployments",
                "deployments",
                {"api-version": "2024-10-01"},
            )
    return plan


def paged(plan: CatalogPlan, rows: list, total) -> bool:
    if type(total) is not int or total < 0:
        raise ModelDiscoveryError(reason="format")
    plan.seen += len(rows)
    more = plan.seen < total
    if more and not rows:
        raise ModelDiscoveryError(reason="format")
    plan.page += 1
    return more


def next_page(plan: CatalogPlan, payload: dict) -> tuple[dict, bool]:
    if plan.protocol == "bailian":
        output = payload.get("output")
        if not isinstance(output, dict) or not isinstance(output.get("models"), list):
            raise ModelDiscoveryError(reason="format")
        rows = output["models"]
        normalized = [
            {**row, "id": row.get("model"), "display_name": row.get("name")} for row in rows if isinstance(row, dict)
        ]
        return {"data": normalized}, paged(plan, rows, output.get("total"))
    if plan.protocol == "ark":
        result = payload.get("Result")
        if not isinstance(result, dict) or not isinstance(result.get("Items"), list):
            raise ModelDiscoveryError(reason="format")
        rows = result["Items"]
        normalized = []
        for row in rows:
            if not isinstance(row, dict) or row.get("Status") != "Running":
                continue
            ref = row.get("ModelReference") or {}
            if not isinstance(ref, dict):
                raise ModelDiscoveryError(reason="format")
            foundation = ref.get("FoundationModel") or {}
            if not isinstance(foundation, dict):
                raise ModelDiscoveryError(reason="format")
            normalized.append(
                {
                    "id": row.get("Id"),
                    "display_name": row.get("Name"),
                    "classification_name": foundation.get("Name"),
                    "model_type": "image_generation" if row.get("ContentGeneration") else None,
                }
            )
        return {"data": normalized}, paged(plan, rows, result.get("TotalCount"))
    if plan.protocol == "azure_deployments":
        rows = payload.get("value")
        if not isinstance(rows, list):
            raise ModelDiscoveryError(reason="format")
        normalized = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            properties = row.get("properties") or {}
            if not isinstance(properties, dict):
                raise ModelDiscoveryError(reason="format")
            if properties.get("provisioningState") != "Succeeded":
                continue
            model = properties.get("model") or {}
            if not isinstance(model, dict):
                raise ModelDiscoveryError(reason="format")
            normalized.append(
                {
                    "id": row.get("name"),
                    "classification_name": model.get("name"),
                    "capabilities": properties.get("capabilities"),
                    "display_name": model.get("name"),
                }
            )
        next_url = payload.get("nextLink")
        if next_url:
            # Follow only pagination for the same ARM account, with fixed credentials.
            if not isinstance(next_url, str):
                raise ModelDiscoveryError(reason="format")
            target, origin = urlsplit(next_url), urlsplit(plan.url)
            if (
                (target.scheme, target.netloc, target.path) != (origin.scheme, origin.netloc, origin.path)
                or target.fragment
                or next_url == plan.next_url
            ):
                raise ModelDiscoveryError(reason="format")
            plan.next_url, plan.params = next_url, {}
        return {"data": normalized}, bool(next_url)
    more = payload.get("has_more", False)
    if more:
        cursor = payload.get("last_id")
        if not isinstance(cursor, str) or not cursor or cursor == plan.params.get("after_id"):
            raise ModelDiscoveryError(reason="format")
        plan.params["after_id"] = cursor
    return payload, bool(more)
