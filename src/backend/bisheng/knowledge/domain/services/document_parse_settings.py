"""Read, save and probe the document-parse (OCR / ETL) settings.

The endpoints are thin wrappers: everything that decides *what* to write, *how*
tokens are stored, and *which* provider to probe lives here, so it can be tested
without HTTP and cannot drift between the three routes.
"""

from __future__ import annotations

import os
from typing import Any

import yaml
from loguru import logger

from bisheng.common.errcode.server import SystemConfigEmptyError, SystemConfigInvalidError
from bisheng.common.models.config import ConfigDao, ConfigKeyEnum
from bisheng.common.services.config_service import ConfigService
from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.config.settings import KnowledgeConf, PaddleOcrConf, decrypt_token, encrypt_token
from bisheng.knowledge.domain.schemas.document_parse_schema import DocumentParseConfig
from bisheng.knowledge.rag.pipeline.loader.paddle_ocr_client import probe_connection
from bisheng.knowledge.rag.pipeline.loader.provider_probe import probe_endpoint, probe_mineru_v4

_MISSING = object()


def _env_is_set(name: str) -> bool:
    return bool(name and os.getenv(name))


def _lookup(section: Any, dotted: str) -> Any:
    """Value at ``a.b.c`` inside ``section``, or ``_MISSING``."""
    current = section
    for part in dotted.split("."):
        if not isinstance(current, dict):
            return _MISSING
        current = current.get(part, _MISSING)
        if current is _MISSING:
            return _MISSING
    return current


def _needs_write(section: Any, desired: dict) -> bool:
    """True when any desired value differs from what is stored (dotted keys allowed)."""
    if not isinstance(section, dict):
        return True
    return any(_lookup(section, key) != value for key, value in desired.items())


def _encrypt(value: str) -> str:
    encrypted = encrypt_token(value)
    return encrypted.decode() if isinstance(encrypted, bytes) else encrypted


def _resolve_secret(typed: str | None, clear: bool, stored: str) -> str:
    """Write-only field semantics: clear wins, then a new value, else keep stored."""
    if clear:
        return ""
    if typed:
        return _encrypt(typed)
    return stored or ""


class DocumentParseSettingsService:
    """Document-parse settings for the admin form."""

    @staticmethod
    def read() -> dict:
        """Current effective settings. Tokens are reported as presence only."""
        conf = bisheng_settings.get_knowledge()
        paddle, mineru, mv4 = conf.paddle_ocr, conf.mineru, conf.mineru_v4
        view = DocumentParseConfig(
            loader_provider=conf.loader_provider,
            etl4lm_url=conf.etl4lm.url,
            etl4lm_timeout=conf.etl4lm.timeout,
            etl4lm_ocr_sdk_url=conf.etl4lm.ocr_sdk_url,
            mineru_url=mineru.url,
            mineru_timeout=mineru.timeout,
            mineru_api_key_header=mineru.api_key_header,
            mineru_backend=str((mineru.request_kwargs or {}).get("backend", "")),
            mineru_v4_api_url=mv4.api_url,
            mineru_v4_api_key_env=mv4.api_key_env,
            mineru_v4_tier=mv4.tier,
            mineru_v4_model_version=mv4.cloud_model_version,
            mineru_v4_ocr_mode=mv4.ocr_mode,
            mineru_v4_request_timeout_seconds=mv4.request_timeout_seconds,
            mineru_v4_job_timeout_seconds=mv4.job_timeout_seconds,
            mineru_v4_poll_interval_seconds=mv4.poll_interval_seconds,
            paddle_ocr_url=paddle.url,
            paddle_ocr_model=paddle.model,
            paddle_ocr_api_key_env=paddle.api_key_env,
            paddle_ocr_service_mode=paddle.service_mode,
            paddle_ocr_timeout=paddle.timeout,
            paddle_ocr_max_retries=paddle.max_retries,
            paddle_ocr_retry_backoff=paddle.retry_backoff,
            paddle_ocr_poll_interval_seconds=paddle.poll_interval_seconds,
            paddle_ocr_job_timeout_seconds=paddle.job_timeout_seconds,
        ).model_dump()
        return view | {
            "token_configured": _env_is_set(paddle.api_key_env) or bool(paddle.auth_token_enc),
            "mineru_token_configured": bool(mineru.api_key_enc),
            "mineru_v4_token_configured": _env_is_set(mv4.api_key_env) or bool(mv4.api_key_enc),
        }

    @staticmethod
    def save(data: DocumentParseConfig, user_name: str = "") -> None:
        """Persist the settings, writing only the sections that actually changed.

        Text-level writes preserve comments; only the selected provider's scalars
        are touched, and a section whose values already match is skipped so a
        stale form cannot overwrite another administrator's edit.
        """
        db_config = ConfigDao.get_config(ConfigKeyEnum.INIT_DB)
        if db_config is None or not db_config.value:
            raise SystemConfigEmptyError()
        stored = DocumentParseSettingsService._stored_knowledges(db_config.value)

        paddle = stored.get("paddle_ocr") or {}
        mineru = stored.get("mineru") or {}
        mv4 = stored.get("mineru_v4") or {}

        mineru_values = {
            "url": data.mineru_url,
            "timeout": data.mineru_timeout,
            "api_key_header": data.mineru_api_key_header,
            "api_key_enc": _resolve_secret(data.mineru_token, data.mineru_clear_token, mineru.get("api_key_enc", "")),
        }
        if data.mineru_backend:
            # Dotted key: updates one child, leaving the rest of the mapping (and
            # its comments) alone.
            mineru_values["request_kwargs.backend"] = data.mineru_backend

        sections = [
            (["knowledges"], {"loader_provider": data.loader_provider}),
            (
                ["knowledges", "etl4lm"],
                {"url": data.etl4lm_url, "timeout": data.etl4lm_timeout, "ocr_sdk_url": data.etl4lm_ocr_sdk_url},
            ),
            (["knowledges", "mineru"], mineru_values),
            (
                ["knowledges", "mineru_v4"],
                {
                    "api_url": data.mineru_v4_api_url,
                    "api_key_env": data.mineru_v4_api_key_env,
                    "api_key_enc": _resolve_secret(
                        data.mineru_v4_token, data.mineru_v4_clear_token, mv4.get("api_key_enc", "")
                    ),
                    "tier": data.mineru_v4_tier,
                    "cloud_model_version": data.mineru_v4_model_version,
                    "ocr_mode": data.mineru_v4_ocr_mode,
                    "request_timeout_seconds": data.mineru_v4_request_timeout_seconds,
                    "job_timeout_seconds": data.mineru_v4_job_timeout_seconds,
                    "poll_interval_seconds": data.mineru_v4_poll_interval_seconds,
                },
            ),
            (
                ["knowledges", "paddle_ocr"],
                {
                    "url": data.paddle_ocr_url,
                    "model": data.paddle_ocr_model,
                    "api_key_env": data.paddle_ocr_api_key_env,
                    "service_mode": data.paddle_ocr_service_mode,
                    "timeout": data.paddle_ocr_timeout,
                    "max_retries": data.paddle_ocr_max_retries,
                    "retry_backoff": data.paddle_ocr_retry_backoff,
                    "poll_interval_seconds": data.paddle_ocr_poll_interval_seconds,
                    "job_timeout_seconds": data.paddle_ocr_job_timeout_seconds,
                    "auth_token_enc": _resolve_secret(
                        data.paddle_ocr_token, data.paddle_ocr_clear_token, paddle.get("auth_token_enc", "")
                    ),
                },
            ),
        ]

        updated = db_config.value
        for path, desired in sections:
            section = stored if path == ["knowledges"] else _lookup(stored, ".".join(path[1:]))
            if _needs_write(section, desired):
                updated = ConfigService.update_section_scalars(updated, path, desired)

        if updated == db_config.value:
            logger.info("document-parse settings unchanged by user_name={}", user_name)
            return

        try:
            parsed = yaml.safe_load(updated)
            conf = KnowledgeConf(**parsed["knowledges"])
            # Only this service can see the stored ciphertext, so the "a token
            # exists" check belongs here rather than in the request schema.
            if conf.paddle_ocr.resolved_service_mode == "jobs" and not (
                conf.paddle_ocr.api_key_env or conf.paddle_ocr.auth_token_enc
            ):
                raise ValueError("Set a token, or name the environment variable that holds it")
        except Exception as exc:
            logger.exception("document-parse settings update rejected")
            raise SystemConfigInvalidError(exception=str(exc)) from exc

        db_config.value = updated
        ConfigDao.insert_config(db_config)
        get_redis_client_sync().delete("config:initdb_config")
        logger.info("document-parse settings updated by user_name={}", user_name)

    @staticmethod
    def test(data: DocumentParseConfig) -> dict:
        """Probe the selected provider without saving anything.

        PaddleOCR gets the precise check (an empty submission separates a rejected
        token from a dead service); the others get a reachability-and-credential
        check, since they have no harmless probe request.
        """
        row = ConfigDao.get_config(ConfigKeyEnum.INIT_DB)
        stored = DocumentParseSettingsService._stored_knowledges(row.value if row else "")

        if data.loader_provider == "paddle_ocr":
            conf = PaddleOcrConf(
                url=data.paddle_ocr_url,
                model=data.paddle_ocr_model,
                api_key_env=data.paddle_ocr_api_key_env,
                service_mode=data.paddle_ocr_service_mode,
                timeout=data.paddle_ocr_timeout,
                auth_token_enc=(stored.get("paddle_ocr") or {}).get("auth_token_enc", "") or "",
            )
            return probe_connection(conf, token=data.paddle_ocr_token or None)

        if data.loader_provider == "mineru_v4":
            token = DocumentParseSettingsService._stored_or_typed(
                data.mineru_v4_token, (stored.get("mineru_v4") or {}).get("api_key_enc", ""), data.mineru_v4_api_key_env
            )
            if token is None:
                return {"status": "token_invalid", "message": "The stored API key cannot be decrypted", "latency_ms": 0}
            return probe_mineru_v4(data.mineru_v4_api_url, token)

        if data.loader_provider == "mineru":
            token = DocumentParseSettingsService._stored_or_typed(
                data.mineru_token, (stored.get("mineru") or {}).get("api_key_enc", ""), ""
            )
            if token is None:
                return {"status": "token_invalid", "message": "The stored API key cannot be decrypted", "latency_ms": 0}
            return probe_endpoint(
                data.mineru_url,
                token,
                token_header=data.mineru_api_key_header or "x-api-key",
                token_prefix="",
            )

        return probe_endpoint(data.etl4lm_url)

    # -- helpers -----------------------------------------------------------------------

    @staticmethod
    def _stored_knowledges(raw: str) -> dict:
        if not raw:
            return {}
        try:
            return (yaml.safe_load(raw) or {}).get("knowledges", {}) or {}
        except Exception:
            logger.warning("stored configuration is not parseable; treating provider settings as absent")
            return {}

    @staticmethod
    def _stored_or_typed(typed: str | None, stored_enc: str, env_name: str) -> str | None:
        """Typed token, else the stored ciphertext, else the environment.

        Returns ``None`` only when a stored ciphertext cannot be decrypted, so the
        caller can answer with a precise error instead of a bare 401 later.
        """
        if typed:
            return typed
        if stored_enc:
            try:
                return decrypt_token(stored_enc)
            except Exception:
                logger.exception("stored provider key cannot be decrypted")
                return None
        return os.getenv(env_name, "") if env_name else ""
