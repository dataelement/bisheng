"""Capture trusted dependency provenance before an exception becomes text.

This adapter never retries, changes exception types, or decides authorization.
Public metadata is a strict allowlist; provider messages remain in server logs.
"""

from __future__ import annotations

import inspect
import json
import re
import sys
from datetime import UTC, datetime
from functools import wraps
from typing import Any
from uuid import uuid4

from loguru import logger

from bisheng.common.schemas.failure import FailureCategory, FailureContext, FailureInfo, FailureReason

_CONTEXT = "_bisheng_failure_context"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SERVICE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_PRIVATE = re.compile(
    r"https?://|[\r\n]|(?:password|secret|api[_ -]?key|access[_ -]?token|authorization|cookie|bearer)\s*[:= ]", re.I
)
_OPERATIONS = frozenset(
    {
        "search",
        "invoke_model",
        "read_file",
        "write_file",
        "parse_file",
        "transcribe",
        "synthesize",
        "authenticate",
        "enqueue",
        "upload",
        "download",
        "rerank",
        "embed",
        "tool_call",
    }
)


def failure_boundary(category: str, service: str, operation: str):
    """Annotate the actual dependency call without changing its control flow."""

    def decorate(function):
        def record(exc, args):
            if category == "object_storage" and (
                isinstance(exc, ValueError) or getattr(exc, "code", None) in ("NoSuchKey", "NoSuchObject")
            ):
                return
            owner = args[0] if args else None
            model = getattr(owner, "model_info", None) if category == "model_service" else None
            name = getattr(model, "name", None)
            FailureContextAdapter.capture(
                exc, category=category, service=service, service_name=name, operation=operation
            )

        if inspect.isasyncgenfunction(function):

            @wraps(function)
            async def async_stream(*args, **kwargs):
                try:
                    async for item in function(*args, **kwargs):
                        yield item
                except Exception as exc:
                    record(exc, args)
                    raise

            return async_stream
        if inspect.isgeneratorfunction(function):

            @wraps(function)
            def stream(*args, **kwargs):
                try:
                    yield from function(*args, **kwargs)
                except Exception as exc:
                    record(exc, args)
                    raise

            return stream
        if inspect.iscoroutinefunction(function):

            @wraps(function)
            async def asynchronous(*args, **kwargs):
                try:
                    return await function(*args, **kwargs)
                except Exception as exc:
                    record(exc, args)
                    raise

            return asynchronous

        @wraps(function)
        def synchronous(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except Exception as exc:
                record(exc, args)
                raise

        return synchronous

    return decorate


def _chain(error: BaseException):
    pending, seen = [error], set()
    while pending and len(seen) < 64:
        current = pending.pop(0)
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        for key in ("__cause__", "__context__", "exception", "original_error", "orig"):
            nested = getattr(current, key, None)
            if isinstance(nested, BaseException):
                pending.append(nested)
        nested_errors = getattr(current, "exceptions", ())
        if isinstance(nested_errors, (tuple, list)):
            pending.extend(x for x in nested_errors if isinstance(x, BaseException))


def _label(value: Any, limit=256) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or _PRIVATE.search(value):
        return None
    return value.strip()


def _infer(error: BaseException) -> tuple[str, str] | None:
    module = type(error).__module__.lower()
    name = type(error).__name__
    if module == "bisheng.common.errcode.server":
        config_errors = {
            "llm": {
                "NoLlmModelConfigError",
                "LlmModelConfigDeletedError",
                "LlmProviderDeletedError",
                "LlmModelTypeError",
                "LlmModelOfflineError",
                "InitLlmError",
            },
            "embedding": {
                "NoEmbeddingModelError",
                "EmbeddingModelNotExistError",
                "EmbeddingModelTypeError",
                "EmbeddingModelStatusError",
            },
            "asr": {
                "NoAsrModelConfigError",
                "AsrModelConfigDeletedError",
                "AsrProviderDeletedError",
                "AsrModelTypeError",
                "AsrModelOfflineError",
                "InitAsrError",
            },
            "tts": {
                "NoTtsModelConfigError",
                "TtsModelConfigDeletedError",
                "TtsProviderDeletedError",
                "TtsModelTypeError",
                "TtsModelOfflineError",
                "InitTtsError",
            },
        }
        for service, errors in config_errors.items():
            if name in errors:
                return "model_service", service
    if module.startswith(("httpx", "requests.exceptions")) and name in {
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "ReadError",
        "WriteError",
        "ConnectionError",
        "Timeout",
    }:
        return "network", "transport"
    if module.startswith("openai") and name.endswith("Error"):
        return "model_service", "llm"
    if module.startswith("redis") and name not in {"DataError", "InvalidResponse"}:
        return "database", "redis"
    if module.startswith(("pymilvus", "milvus")) and name not in {"ParamError", "DataNotMatchException"}:
        return "database", "milvus"
    if any(
        base.__module__.startswith(("elasticsearch", "elastic_transport"))
        and base.__name__ in {"ConnectionError", "ConnectionTimeout", "TransportError", "ApiError"}
        for base in type(error).__mro__
    ):
        return "database", "elasticsearch"
    storage_type = any(
        base.__module__.startswith(("minio", "botocore"))
        and base.__name__
        in {"S3Error", "ClientError", "EndpointConnectionError", "ConnectTimeoutError", "ReadTimeoutError"}
        for base in type(error).__mro__
    )
    if storage_type:
        if getattr(error, "code", None) in ("NoSuchKey", "NoSuchObject"):
            return None
        return "object_storage", "minio"
    if module.startswith("sqlalchemy") and name in {
        "OperationalError",
        "InterfaceError",
        "InternalError",
        "DatabaseError",
        "TimeoutError",
        "DisconnectionError",
    }:
        driver = type(getattr(error, "orig", None)).__module__.lower()
        return "database", "dm8" if driver.startswith(("dmpython", "dmasync")) else "mysql" if driver.startswith(
            ("pymysql", "mysqldb")
        ) else "database"
    if module.startswith(("dmpython", "dmasync", "pymysql", "mysqldb")) and name in {
        "OperationalError",
        "InterfaceError",
        "InternalError",
        "DatabaseError",
    }:
        return "database", "dm8" if module.startswith(("dmpython", "dmasync")) else "mysql"
    return None


def _reason(error: BaseException) -> FailureReason:
    name = type(error).__name__.lower()
    code = getattr(error, "code", None)
    status = getattr(error, "status_code", None)
    reasons = {
        "arrearage": FailureReason.BALANCE_EXHAUSTED,
        "insufficient_balance": FailureReason.BALANCE_EXHAUSTED,
        "context_length_exceeded": FailureReason.CONTEXT_LIMIT,
        "max_tokens_exceeded": FailureReason.CONTEXT_LIMIT,
        "content_filter": FailureReason.CONTENT_REJECTED,
        "content_policy_violation": FailureReason.CONTENT_REJECTED,
        "data_inspection_failed": FailureReason.CONTENT_REJECTED,
        "model_not_found": FailureReason.MODEL_UNAVAILABLE,
        "unsupported_response_format": FailureReason.CAPABILITY_MISMATCH,
        "unsupported_parameter": FailureReason.CAPABILITY_MISMATCH,
        "invalidapikey": FailureReason.AUTHENTICATION_FAILED,
        "invalidaccesskeyid": FailureReason.AUTHENTICATION_FAILED,
        "signaturedoesnotmatch": FailureReason.AUTHENTICATION_FAILED,
        "expiredtoken": FailureReason.AUTHENTICATION_FAILED,
        "accessdenied": FailureReason.ACCESS_DENIED,
    }
    if isinstance(code, str) and code.lower() in reasons:
        return reasons[code.lower()]
    if "timeout" in name:
        return FailureReason.TIMEOUT
    if "authentication" in name or status == 401:
        return FailureReason.AUTHENTICATION_FAILED
    if "permission" in name or status == 403:
        return FailureReason.ACCESS_DENIED
    if "ratelimit" in name or status == 429:
        return FailureReason.RATE_LIMIT
    if isinstance(code, str) and code in {"context_length_exceeded", "max_tokens_exceeded"}:
        return FailureReason.CONTEXT_LIMIT
    if isinstance(code, str) and code in {"content_filter", "content_policy_violation"}:
        return FailureReason.CONTENT_REJECTED
    if "connection" in name or "connect" in name:
        return FailureReason.CONNECTION_FAILED
    if isinstance(status, int) and status >= 500:
        return FailureReason.SERVICE_UNAVAILABLE
    if "jsondecode" in name or "validation" in name:
        return FailureReason.INVALID_RESPONSE
    return FailureReason.UNKNOWN


class FailureContextAdapter:
    @classmethod
    def public_tool_result(cls, value: Any, *, failed: bool = False, _depth: int = 0):
        if _depth > 8:
            return None
        if isinstance(value, list):
            return [cls.public_tool_result(item, failed=failed, _depth=_depth + 1) for item in value]
        if isinstance(value, dict):
            is_error = (
                bool(value.get("error"))
                or "错误信息" in value
                or value.get("状态") == "失败"
                or "failure_info" in value
            )
            if value.get("状态") == "无结果" and value.get("错误信息") in (
                "没有找到相关的知识内容",
                "knowledge_id 不是有效的知识库/知识空间 id",
            ):
                is_error = False
            return cls.public_payload(value) if is_error else dict(value)
        if isinstance(value, str):
            if "<retrieval_error>" in value:
                return re.sub(
                    r"<retrieval_error>[\s\S]*?</retrieval_error>",
                    "<retrieval_error>Knowledge retrieval failed.</retrieval_error>",
                    value,
                )
            if len(value) <= 1048576:
                try:
                    parsed = json.loads(value)
                except (ValueError, TypeError):
                    parsed = None
                if isinstance(parsed, (dict, list)):
                    return json.dumps(
                        cls.public_tool_result(parsed, failed=failed, _depth=_depth + 1), ensure_ascii=False
                    )
            if value.startswith("Error:"):
                return "Tool execution failed."
            if failed and "<knowledge_base_id>" not in value:
                return "Tool execution failed."
        return value

    @classmethod
    def public_step_metadata(cls, value: Any, *, include_knowledge_name: bool = False) -> dict:
        clean = dict(value) if isinstance(value, dict) else {}
        clean.pop("failure_info", None)
        if info := cls.validate(value.get("failure_info") if isinstance(value, dict) else None):
            clean["failure_info"] = info
        target = clean.pop("knowledge_target", None)
        if isinstance(target, dict) and type(target.get("version")) is int and target["version"] == 1:
            if isinstance(target.get("knowledge_id"), str) and target.get("kind") in (
                "space",
                "knowledge_base",
                "personal",
            ):
                public_target = {key: target[key] for key in ("version", "knowledge_id", "kind")}
                name = target.get("name")
                if (
                    include_knowledge_name
                    and target["kind"] != "personal"
                    and isinstance(name, str)
                    and 0 < len(name) <= 512
                ):
                    public_target["name"] = name
                clean["knowledge_target"] = public_target
        return clean

    @classmethod
    def public_payload(cls, payload: Any, *, exc: BaseException | None = None) -> dict:
        """Preserve recovery/answer fields while excluding raw diagnostic text."""
        clean = dict(payload) if isinstance(payload, dict) else {}
        info = cls.from_error(exc) if exc is not None else cls.validate(clean.get("failure_info"))
        if exc is not None:
            for cause in reversed(list(_chain(exc))):
                code = getattr(cause, "code", None)
                if (
                    type(cause).__module__.startswith("bisheng.common.errcode.")
                    and type(code) is int
                    and 10000 <= code <= 99999
                ):
                    clean["error_code"] = code
                    break
        clean.pop("failure_info", None)
        for key in ("exception", "detail"):
            clean.pop(key, None)
        for key in ("files", "file_list"):
            if isinstance(clean.get(key), list):
                clean[key] = [cls.public_payload(item) if isinstance(item, dict) else item for item in clean[key]]
        for key in ("error", "error_message", "error_msg", "错误信息"):
            if key in clean and isinstance(clean[key], str):
                clean[key] = cls.safe_detail(exc) if exc is not None else "Request failed."
        if info:
            clean["failure_info"] = info
        return clean

    @staticmethod
    def validate(info: Any) -> dict | None:
        if not isinstance(info, dict) or type(info.get("version")) is not int or info["version"] != 1:
            return None
        if not isinstance(info.get("failure_id"), str) or not _IDENTIFIER.fullmatch(info["failure_id"]):
            return None
        if not isinstance(info.get("category"), str) or info["category"] not in {x.value for x in FailureCategory}:
            return None
        occurred = info.get("occurred_at")
        if not isinstance(occurred, str) or len(occurred) > 48:
            return None
        try:
            if datetime.fromisoformat(occurred.replace("Z", "+00:00")).tzinfo is None:
                return None
        except ValueError:
            return None
        clean = {key: info[key] for key in ("version", "failure_id", "category", "occurred_at")}
        if isinstance(info.get("service"), str) and _SERVICE.fullmatch(info["service"]):
            clean["service"] = info["service"]
        if label := _label(info.get("service_name")):
            clean["service_name"] = label
        if isinstance(info.get("operation"), str) and info["operation"] in _OPERATIONS:
            clean["operation"] = info["operation"]
        if isinstance(info.get("trace_id"), str) and _IDENTIFIER.fullmatch(info["trace_id"]):
            clean["trace_id"] = info["trace_id"]
        return FailureInfo.model_validate(clean).model_dump(mode="json", exclude_none=True)

    @classmethod
    def capture(
        cls, exc: BaseException, *, category=None, service=None, service_name=None, operation=None, reason=None
    ) -> dict | None:
        if not isinstance(exc, BaseException):
            return None
        chain = list(_chain(exc))
        for error in chain:
            context = getattr(error, _CONTEXT, None)
            if isinstance(context, FailureContext) and context.info:
                info = cls.validate(context.info)
                if info:
                    return info
        inferred = next((pair for error in chain if (pair := _infer(error))), None)
        category = category.value if isinstance(category, FailureCategory) else category
        if category is None and inferred:
            category, inferred_service = inferred
            service = service or inferred_service
        if not isinstance(category, str) or category not in {x.value for x in FailureCategory}:
            return None
        info = cls.validate(
            {
                "version": 1,
                "failure_id": uuid4().hex,
                "category": category,
                "service": service,
                "service_name": service_name,
                "operation": operation,
                "occurred_at": datetime.now(UTC).isoformat(),
            }
        )
        logger_module = sys.modules.get("bisheng.core.logger")
        trace_var = getattr(logger_module, "trace_id_var", None)
        trace_id = trace_var.get() if trace_var is not None else None
        if isinstance(trace_id, str) and _IDENTIFIER.fullmatch(trace_id):
            info["trace_id"] = trace_id
        try:
            reason = FailureReason(reason) if reason is not None else _reason(exc)
        except ValueError:
            reason = FailureReason.UNKNOWN
        context = FailureContext(info=info, reason=reason, exception_type=type(exc).__name__)
        try:
            vars(exc)[_CONTEXT] = context
        except (AttributeError, TypeError):
            # Some third-party exceptions are immutable; the existing cause is untouched.
            pass
        logger.warning(
            "Dependency failure category={} service={} failure_id={} exception_type={} reason={}",
            category,
            info.get("service"),
            info["failure_id"],
            type(exc).__name__,
            reason.value,
        )
        return info

    @classmethod
    def from_error(cls, exc: BaseException) -> dict | None:
        return cls.capture(exc)

    @classmethod
    def from_payload(cls, payload: Any) -> dict | None:
        pending, seen = [(payload, 0)], set()
        while pending and len(seen) < 100:
            item, depth = pending.pop(0)
            if depth > 6 or id(item) in seen:
                continue
            seen.add(id(item))
            if isinstance(item, str):
                if len(item) > 1048576:
                    continue
                try:
                    if item.startswith("Error: {"):
                        item = item[7:]
                    item = json.loads(item)
                except (ValueError, TypeError):
                    continue
            if isinstance(item, dict):
                if info := cls.validate(item.get("failure_info")):
                    return info
                for key in ("data", "message", "extra_info", "output_result", "error", "results"):
                    if key in item:
                        pending.append((item[key], depth + 1))
            elif isinstance(item, (list, tuple)):
                pending.extend((value, depth + 1) for value in reversed(item[-100:]))
        return None

    @classmethod
    def safe_detail(cls, exc: BaseException) -> str:
        info = cls.from_error(exc)
        if info:
            return f"Service request failed ({info['category']}); reference {info['failure_id']}."
        return "Request failed. Please provide the diagnostic reference to support."
