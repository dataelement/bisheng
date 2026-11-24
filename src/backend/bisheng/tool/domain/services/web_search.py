"""Custom web search management: credentials, schema import, settings and previews."""

import asyncio
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator
from sqlmodel import select

from bisheng.common.errcode import BaseErrorCode
from bisheng.core.config.settings import decrypt_token, encrypt_token
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.tool.domain.const import ToolPresetType
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType, WebSearchSecret
from bisheng.tool.domain.services.tool import ToolServices
from bisheng.utils.mask_data import JsonFieldMasker
from bisheng_langchain.gpts.tools.web_search.custom import (
    CustomSearchError,
    build_request,
    execute_request,
    map_response,
    validate_mapping,
)
from bisheng_langchain.gpts.tools.web_search.tool import SearchTool


class SecretUnavailable(RuntimeError):
    """The credential or its encryption key is unavailable or invalid."""


class WebSearchCipher:
    _domain = "bisheng-custom-web-search-secret-v1"
    _key_id = "platform"

    @classmethod
    def configured(cls):
        return cls()

    def encrypt(self, value: str, *, tenant_id: int, category_id: int) -> tuple[str, str]:
        try:
            if not isinstance(value, str) or not value or "\0" in value or len(value.encode("utf-8")) > 16384:
                raise ValueError
        except (ValueError, UnicodeError):
            raise SecretUnavailable("Invalid custom search secret") from None
        payload = {
            "domain": self._domain,
            "version": 1,
            "tenant_id": tenant_id,
            "category_id": category_id,
            "value": value,
        }
        token = encrypt_token(json.dumps(payload, ensure_ascii=False)).decode("ascii")
        return self._key_id, token

    def decrypt(self, key_id: str, ciphertext: str, *, tenant_id: int, category_id: int) -> str:
        try:
            if not isinstance(ciphertext, str) or len(ciphertext) > 65536:
                raise ValueError
            if key_id != self._key_id:
                raise ValueError
            data = json.loads(decrypt_token(ciphertext.encode("ascii")))
            if (data["domain"], data["version"], data["tenant_id"], data["category_id"]) != (
                self._domain,
                1,
                tenant_id,
                category_id,
            ):
                raise ValueError
            value = data["value"]
            if not isinstance(value, str) or not value or "\0" in value or len(value.encode("utf-8")) > 16384:
                raise ValueError
            return value
        except (KeyError, InvalidToken, ValueError, TypeError, UnicodeError):
            raise SecretUnavailable("Custom search secret unavailable") from None


class SecretChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["keep", "replace", "clear"]
    value: SecretStr | None = None

    @model_validator(mode="after")
    def check_action(self):
        if self.action == "replace":
            if self.value is None or not self.value.get_secret_value():
                raise ValueError("replace requires a nonempty value")
        elif "value" in self.model_fields_set:
            raise ValueError("value is permitted only for replace")
        return self


class SettingsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: str = Field(min_length=1, max_length=128)
    enabled: bool
    type: str = Field(min_length=1, max_length=128)
    prompt: str = Field(max_length=16384)
    providers: dict[str, Any]
    custom_secret: SecretChange


def _revision(category, children, secret):
    state = [
        category.extra,
        [(c.id, c.is_delete, c.is_preset, c.tool_key, c.extra) for c in children],
        [secret.key_id, secret.ciphertext, secret.version] if secret else None,
    ]
    return hashlib.sha256(json.dumps(state, ensure_ascii=True, sort_keys=True, default=str).encode()).hexdigest()


def _custom(value):
    if not isinstance(value, dict) or set(value) not in ({"operation", "mapping"}, {"operation", "mapping", "proof"}):
        raise HTTPException(422, "Invalid custom search configuration")
    # Accept persisted settings and older clients, but discard their obsolete proof.
    value = {key: value[key] for key in ("operation", "mapping")}
    op, mapping = value["operation"], value["mapping"]
    if isinstance(op, dict) and op.get("version") == 2:
        if set(op) != {
            "version",
            "server",
            "method",
            "path",
            "declaration",
            "request",
            "media_type",
            "auth",
            "response_mode",
        }:
            raise HTTPException(422, "Invalid OpenAPI search operation")
        auth = op.get("auth")
        if (
            not isinstance(auth, dict)
            or set(auth) != {"location", "name"}
            or auth["location"] not in {"none", "header", "query", "cookie"}
            or not isinstance(auth["name"], str)
            or (auth["location"] != "none" and not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", auth["name"]))
        ):
            raise HTTPException(422, "Complete the OpenAPI authentication settings")
        declaration = op.get("declaration")
        if not isinstance(declaration, dict):
            raise HTTPException(422, "Invalid OpenAPI search declaration")
        required_auth = declaration.get("security")
        if required_auth is not None and (
            not isinstance(required_auth, dict)
            or auth["location"] == "none"
            or any(required_auth.get(key) and auth[key] != required_auth[key] for key in ("location", "name"))
        ):
            raise HTTPException(422, "Complete the OpenAPI authentication settings")
        if op["response_mode"] not in {"raw", "mapped"}:
            raise HTTPException(422, "Invalid OpenAPI response mode")
        try:
            build_request(op, "validation", "validation-key")
            if op["response_mode"] == "mapped":
                validate_mapping(mapping)
        except (CustomSearchError, TypeError, ValueError, KeyError) as exc:
            detail = str(exc) if isinstance(exc, CustomSearchError) else "Invalid OpenAPI request template"
            raise HTTPException(422, detail) from None
        return value
    if not isinstance(op, dict) or set(op) != {"server", "method", "path", "query_parameter", "fixed_params", "auth"}:
        raise HTTPException(422, "Invalid custom search operation")
    if not isinstance(op["query_parameter"], dict) or set(op["query_parameter"]) != {"location", "name"}:
        raise HTTPException(422, "Invalid custom search query parameter")
    if not isinstance(op["auth"], dict) or set(op["auth"]) != {"location", "name"}:
        raise HTTPException(422, "Invalid custom search authentication")
    if not isinstance(op["fixed_params"], list) or any(
        not isinstance(p, dict) or set(p) != {"location", "name", "value"} for p in op["fixed_params"]
    ):
        raise HTTPException(422, "Invalid custom search fixed parameters")
    if not isinstance(mapping, dict) or set(mapping) != {
        "results",
        "title",
        "url",
        "snippet",
        "source",
        "siteIcon",
        "datePublished",
    }:
        raise HTTPException(422, "Invalid custom search mapping")
    try:
        build_request(op, "validation", "validation-key")
        validate_mapping(mapping)
    except (CustomSearchError, TypeError, ValueError):
        raise HTTPException(422, "Invalid custom search configuration") from None
    return value


async def _target(session, category_id, *, lock=False):
    tenant = get_current_tenant_id()
    if tenant is None:
        raise HTTPException(404, "Search tool not found")
    stmt = select(GptsToolsType).where(
        GptsToolsType.id == category_id,
        GptsToolsType.tenant_id == tenant,
        GptsToolsType.is_preset == ToolPresetType.PRESET.value,
        GptsToolsType.is_delete == 0,
    )
    if lock:
        stmt = stmt.with_for_update()
    category = (await session.exec(stmt)).first()
    if category is None:
        raise HTTPException(404, "Search tool not found")
    children_stmt = (
        select(GptsTools).where(GptsTools.type == category_id, GptsTools.tenant_id == tenant).order_by(GptsTools.id)
    )
    if lock:
        children_stmt = children_stmt.with_for_update()
    children = (await session.exec(children_stmt)).all()
    search = [
        c
        for c in children
        if c.tool_key == "web_search" and c.is_preset == ToolPresetType.PRESET.value and not c.is_delete
    ]
    if len(search) != 1:
        raise HTTPException(404, "Search tool not found")
    secret_stmt = select(WebSearchSecret).where(
        WebSearchSecret.tenant_id == tenant,
        WebSearchSecret.category_id == category_id,
        WebSearchSecret.provider == "custom",
    )
    if lock:
        secret_stmt = secret_stmt.with_for_update()
    secret = (await session.exec(secret_stmt)).first()
    return category, children, secret


def _extra(category):
    try:
        extra = json.loads(category.extra or "{}")
        if not isinstance(extra, dict) or not isinstance(extra.get("config", {}), dict):
            raise ValueError
        return extra
    except (ValueError, TypeError):
        raise HTTPException(409, "Stored search settings are invalid") from None


_PROVIDER_FIELDS = {
    "bing": {"api_key", "base_url"},
    "bocha": {"api_key", "base_url"},
    "jina": {"api_key", "base_url"},
    "serp": {"api_key", "base_url", "engine"},
    "tavily": {"api_key", "base_url"},
    "cloudsway": {"api_key", "base_url", "endpoint"},
    "searXNG": {"server_url", "base_url"},
    "deepseek": {"api_key", "base_url"},
}


def _view(category, children, secret):
    extra = _extra(category)
    config = extra.get("config", {})
    visible = {
        name: {key: value for key, value in config[name].items() if key in fields and isinstance(value, str)}
        for name, fields in _PROVIDER_FIELDS.items()
        if isinstance(config.get(name), dict)
    }
    if "custom" in config:
        visible["custom"] = config["custom"]
    providers = JsonFieldMasker().mask_json(visible)
    # New custom templates contain no stored plaintext credentials. Preserve schema field names.
    if isinstance(visible.get("custom"), dict) and visible["custom"].get("operation", {}).get("version") == 2:
        providers["custom"] = visible["custom"]
    if "custom" in providers:
        try:
            providers["custom"] = _custom(providers["custom"])
        except HTTPException:
            # Do not expose legacy or malformed custom settings; re-import is required.
            providers.pop("custom")
    return {
        "revision": _revision(category, children, secret),
        "enabled": extra.get("enabled", True),
        "type": extra.get("type", "bing"),
        "prompt": extra.get("prompt", ""),
        "providers": providers,
        "custom_secret_configured": secret is not None,
    }


async def get_settings(category_id):
    async with get_async_db_session() as session:
        category, children, secret = await _target(session, category_id)
        return _view(category, children, secret)


async def put_settings(category_id, req: SettingsWrite, user_id: int):
    async with get_async_db_session() as session:
        category, children, secret = await _target(session, category_id, lock=True)
        if req.revision != _revision(category, children, secret):
            raise HTTPException(409, "Search settings changed; reload and retry")
        if any(c.extra for c in children if not c.is_delete):
            raise HTTPException(409, "Search tool has child overrides requiring migration")
        extra = _extra(category)
        existing = extra.get("config", {})
        incoming = dict(req.providers)
        custom = incoming.pop("custom", None)
        for name, value in list(incoming.items()):
            if name not in _PROVIDER_FIELDS:
                if name not in existing or value != existing[name]:
                    raise HTTPException(422, "Unsupported search provider settings")
                del incoming[name]
                continue
            if not isinstance(value, dict):
                raise HTTPException(422, "Invalid search provider settings")
            old_provider = existing.get(name, {})
            if not isinstance(old_provider, dict):
                raise HTTPException(409, "Stored search provider settings require migration")
            accepted = {}
            for key, item in value.items():
                if key not in _PROVIDER_FIELDS[name]:
                    if key not in old_provider or item != old_provider[key]:
                        raise HTTPException(422, "Unsupported search provider settings")
                elif not isinstance(item, str):
                    raise HTTPException(422, "Invalid search provider settings")
                else:
                    accepted[key] = item
            incoming[name] = accepted
        merged = JsonFieldMasker().update_json_with_masked(existing, incoming)
        if req.type == "custom":
            if not custom:
                raise HTTPException(422, "Custom search settings are required")
            merged["custom"] = _custom(custom)
        action = req.custom_secret.action
        credentials = []
        if action == "replace":
            credentials.append(req.custom_secret.value.get_secret_value())
        if secret is not None:
            try:
                credentials.append(
                    WebSearchCipher.configured().decrypt(
                        secret.key_id, secret.ciphertext, tenant_id=category.tenant_id, category_id=category.id
                    )
                )
            except SecretUnavailable:
                if req.type == "custom":
                    raise
                # Allow switching or clearing only without introducing unverified provider text.
                previous = {key: value for key, value in existing.items() if key != "custom"}
                current = {key: value for key, value in merged.items() if key != "custom"}
                if req.prompt != extra.get("prompt", "") or current != previous:
                    raise HTTPException(409, "Cannot change search text while credentials are unavailable") from None

        # Literal matching cannot identify unknown, encoded, or dictionary-key secrets.
        def contains_secret(value):
            if isinstance(value, str):
                return any(credential in value for credential in credentials)
            if isinstance(value, dict):
                return any(contains_secret(item) for item in value.values())
            if isinstance(value, list):
                return any(contains_secret(item) for item in value)
            return False

        free_text = [req.prompt] if req.prompt != extra.get("prompt", "") else []
        for name, values in incoming.items():
            previous_values = existing.get(name, {})
            for key in values:
                value = merged[name].get(key)
                if value != previous_values.get(key):
                    free_text.append(value)
        if req.type == "custom":
            old_custom = existing.get("custom")
            old_op = old_custom.get("operation", {}) if isinstance(old_custom, dict) else {}
            old_fixed = old_op.get("fixed_params", []) if isinstance(old_op, dict) else []
            for item in custom["operation"].get("fixed_params", []):
                if item not in old_fixed:
                    free_text.append(item["value"])
        if req.type == "custom":
            free_text.extend(_request_values(custom["operation"].get("request")))
        if contains_secret(free_text):
            raise HTTPException(422, "Credentials must not appear in search settings")
        if action == "replace":
            new_credential = req.custom_secret.value.get_secret_value()
            existing_text = [req.prompt]
            for name, fields in _PROVIDER_FIELDS.items():
                provider = merged.get(name)
                if isinstance(provider, dict):
                    existing_text.extend(provider.get(field) for field in fields)
            chosen_custom = merged.get("custom")
            if isinstance(chosen_custom, dict) and isinstance(chosen_custom.get("operation"), dict):
                params = chosen_custom["operation"].get("fixed_params", [])
                if isinstance(params, list):
                    existing_text.extend(item.get("value") for item in params if isinstance(item, dict))
                existing_text.extend(_request_values(chosen_custom["operation"].get("request")))
            if any(isinstance(value, str) and new_credential in value for value in existing_text):
                raise HTTPException(422, "Credentials must not appear in search settings")
        if action == "replace":
            key_id, ciphertext = WebSearchCipher.configured().encrypt(
                req.custom_secret.value.get_secret_value(), tenant_id=category.tenant_id, category_id=category.id
            )
            if secret is None:
                secret = WebSearchSecret(
                    tenant_id=category.tenant_id,
                    category_id=category.id,
                    provider="custom",
                    key_id=key_id,
                    ciphertext=ciphertext,
                    version=1,
                    updated_by=user_id,
                )
            else:
                secret.key_id, secret.ciphertext, secret.version, secret.updated_by = (
                    key_id,
                    ciphertext,
                    secret.version + 1,
                    user_id,
                )
                secret.updated_at = datetime.now(UTC).replace(tzinfo=None)
            session.add(secret)
        elif action == "clear" and secret is not None:
            await session.delete(secret)
            secret = None
        chosen = merged.get("custom")
        if req.type == "custom" and chosen["operation"]["auth"]["location"] != "none" and secret is None:
            raise HTTPException(422, "Custom search credentials are required")
        extra.update(
            {
                "enabled": req.enabled,
                "type": req.type,
                "prompt": req.prompt,
                "config": merged,
                "_web_search_revision": uuid.uuid4().hex,
            }
        )
        serialized = json.dumps(extra, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > 60 * 1024:
            raise HTTPException(422, "Search settings exceed size limit")
        category.extra = serialized
        session.add(category)
        await session.commit()
        return _view(category, children, secret)


async def _resolve(category_id, secret_input=None):
    async with get_async_db_session() as session:
        category, children, secret = await _target(session, category_id)
        if any(child.extra for child in children if not child.is_delete):
            raise HTTPException(409, "Search tool has child overrides requiring migration")
        if secret_input is None:
            return None
        try:
            change = SecretChange.model_validate(secret_input)
        except ValidationError:
            raise HTTPException(422, "Invalid search test") from None
        if change.action == "clear":
            raise HTTPException(422, "Invalid search test")
        if change.action == "replace":
            return change.value.get_secret_value()
        if secret is None:
            return None
        return WebSearchCipher.configured().decrypt(
            secret.key_id, secret.ciphertext, tenant_id=category.tenant_id, category_id=category.id
        )


def _request_values(value):
    if isinstance(value, dict):
        return [item for child in value.values() for item in _request_values(child)]
    if isinstance(value, list):
        return [item for child in value for item in _request_values(child)]
    return [value] if isinstance(value, str) else []


def _search_operations(schema):
    """Preserve declarations from shared OpenAPI discovery."""
    from bisheng_langchain.gpts.tools.web_search.openapi_request import describe_operations

    return describe_operations(schema)


async def schema_preview(category_id, data):
    await _resolve(category_id)
    if not isinstance(data, dict) or set(data) not in ({"content"}, {"url"}):
        raise HTTPException(422, "Invalid schema import")

    async def download(url):
        request = {"url": url, "method": "GET", "params": {}, "json": {}, "headers": {}}
        content = await asyncio.to_thread(execute_request, request, schema=True)
        return content.decode("utf-8")

    try:
        schema, _ = await ToolServices.load_openapi_schema(data.get("url"), data.get("content"), download=download)
        operations = _search_operations(schema)
        return {"operations": operations}
    except CustomSearchError as exc:
        raise HTTPException(422, str(exc)) from None
    except (BaseErrorCode, ValueError, TypeError, KeyError, AttributeError, IndexError, UnicodeError):
        raise HTTPException(422, "Unsupported or invalid OpenAPI schema") from None


async def search_preview(category_id, data):
    if not isinstance(data, dict) or set(data) != {"draft", "query", "secret"}:
        raise HTTPException(422, "Invalid search test")
    draft = _custom(data["draft"])
    query = data["query"]
    if not isinstance(query, str) or not query or len(query) > 8192:
        raise HTTPException(422, "Invalid search test")
    secret = await _resolve(category_id, data["secret"])
    try:
        request = build_request(draft["operation"], query, secret)
        raw = await asyncio.to_thread(execute_request, request)
        if draft["operation"].get("version") == 2:
            from bisheng_langchain.gpts.tools.web_search.openapi_request import read_openapi_response

            preview = read_openapi_response(raw, draft["operation"], secret)
            results = preview
            if draft["operation"]["response_mode"] == "mapped":
                _, results = map_response(
                    json.dumps(preview).encode(), draft["mapping"], SearchTool.normalize_result_item, secret
                )
        else:
            preview, results = map_response(raw, draft["mapping"], SearchTool.normalize_result_item, secret)
        return {"status": "success", "preview": preview, "results": results}
    except CustomSearchError as exc:
        raise HTTPException(422, str(exc)) from None
    except (ValueError, TypeError):
        raise HTTPException(422, "Search test failed") from None
