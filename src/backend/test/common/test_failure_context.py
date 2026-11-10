"""Failure provenance must survive wrapping without exposing provider secrets."""

from datetime import datetime

import pytest

from bisheng.common.services.failure_context import FailureContextAdapter


def sdk_error(module, name, message="password=secret https://internal.invalid/api", **attrs):
    error = type(name, (Exception,), {"__module__": module})(message)
    for key, value in attrs.items():
        setattr(error, key, value)
    return error


@pytest.mark.parametrize(
    "module,name,category,service",
    [
        ("sqlalchemy.exc", "OperationalError", "database", "database"),
        ("redis.exceptions", "ConnectionError", "database", "redis"),
        ("pymilvus.exceptions", "MilvusException", "database", "milvus"),
        ("elastic_transport", "ConnectionTimeout", "database", "elasticsearch"),
        ("minio.error", "S3Error", "object_storage", "minio"),
        ("openai", "AuthenticationError", "model_service", "llm"),
    ],
)
def test_reliable_sdk_object_defines_category(module, name, category, service):
    error = sdk_error(module, name)
    result = FailureContextAdapter.from_error(error)
    assert result["category"] == category
    assert result["service"] == service
    assert "secret" not in str(result)
    assert datetime.fromisoformat(result["occurred_at"]).tzinfo
    assert FailureContextAdapter.from_error(error) == result


def test_explicit_boundary_and_wrapping_keep_original_identity():
    root = TimeoutError("Authorization: Bearer top-secret")
    original = FailureContextAdapter.capture(root, category="model_service", service="embedding", operation="search")
    wrapper = RuntimeError("tool failed")
    wrapper.__cause__ = root
    assert FailureContextAdapter.from_error(wrapper) == original
    assert FailureContextAdapter.capture(wrapper, category="database") == original
    assert "top-secret" not in FailureContextAdapter.safe_detail(wrapper)
    assert root.args == ("Authorization: Bearer top-secret",)


@pytest.mark.parametrize(
    "error", [ConnectionError("Connection error"), ValueError("bad JSON"), PermissionError("denied")]
)
def test_unknown_transport_protocol_and_business_are_not_guessed(error):
    assert FailureContextAdapter.from_error(error) is None


def test_normal_object_absence_is_not_storage_outage():
    assert FailureContextAdapter.from_error(sdk_error("minio.error", "S3Error", code="NoSuchKey")) is None


def test_only_safe_schema_survives_payload_roundtrip():
    info = FailureContextAdapter.capture(TimeoutError(), category="database", service="redis")
    assert FailureContextAdapter.from_payload({"data": {"failure_info": info}}) == info
    assert FailureContextAdapter.from_payload('[{"failure_info": ' + __import__("json").dumps(info) + "}]") == info
    poisoned = {**info, "service_name": "https://internal.invalid?token=secret", "exception": "password=secret"}
    result = FailureContextAdapter.validate(poisoned)
    assert "service_name" not in result and "exception" not in result
    assert FailureContextAdapter.validate({**info, "version": 2}) is None
    assert FailureContextAdapter.validate({**info, "category": "internal"}) is None
    assert FailureContextAdapter.from_payload("Connection error") is None


def test_same_payload_does_not_regenerate_failure_identifier():
    info = FailureContextAdapter.capture(RuntimeError(), category="sso", service="sso", operation="authenticate")
    assert FailureContextAdapter.validate(info) == info
    network = FailureContextAdapter.capture(TimeoutError(), category="network", service="gateway")
    assert network["category"] == "network"


def test_cycles_and_untrusted_display_fields_are_bounded():
    error = RuntimeError("api_key=secret")
    error.__cause__ = error
    assert FailureContextAdapter.from_error(error) is None
    info = FailureContextAdapter.capture(error, category="model_service", service_name="API key=secret")
    assert "service_name" not in info
    assert "secret" not in FailureContextAdapter.safe_detail(error)


@pytest.mark.parametrize("key,value", [("category", {}), ("operation", []), ("category", ["database"])])
def test_malformed_optional_and_enum_values_cannot_break_error_rendering(key, value):
    info = FailureContextAdapter.capture(TimeoutError(), category="database")
    result = FailureContextAdapter.validate({**info, key: value})
    if key == "category":
        assert result is None
    else:
        assert key not in result


def test_public_projection_keeps_answer_and_recovery_but_never_raw_diagnostics():
    error = sdk_error("redis.exceptions", "ConnectionError")
    payload = FailureContextAdapter.public_payload(
        {
            "answer": "partial",
            "attempt_id": "a",
            "detail": "password=secret",
            "exception": "https://internal",
            "error": "secret",
        },
        exc=error,
    )
    assert payload["answer"] == "partial" and payload["attempt_id"] == "a"
    assert payload["failure_info"] == FailureContextAdapter.from_error(error)
    assert "secret" not in str(payload) and "https://internal" not in str(payload)


def test_frozen_errors_keep_identity_and_existing_diagnostics():
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class FrozenError(Exception):
        message: str

    error = FrozenError("secret")
    info = FailureContextAdapter.capture(error, category="object_storage", service="minio")
    assert FailureContextAdapter.from_error(error) == info
    assert error.message == "secret"


@pytest.mark.parametrize(
    "module,name,service",
    [
        ("bisheng.common.errcode.server", "LlmModelOfflineError", "llm"),
        ("bisheng.common.errcode.server", "EmbeddingModelNotExistError", "embedding"),
        ("httpx", "ConnectError", "transport"),
    ],
)
def test_explicit_model_config_and_transport_types_are_recognized(module, name, service):
    info = FailureContextAdapter.from_error(sdk_error(module, name))
    assert info["service"] == service


def test_model_sdk_precedes_its_transport_or_internal_service_text():
    provider = sdk_error("openai", "InternalServerError", message="Redis connection error", status_code=500)
    provider.__cause__ = sdk_error("httpx", "ConnectError")
    assert FailureContextAdapter.from_error(provider)["category"] == "model_service"


def test_platform_quota_and_permission_are_not_model_provider_failures():
    for name in ("LLMTenantQuotaExceededError", "LLMModelPermissionDeniedError"):
        assert FailureContextAdapter.from_error(sdk_error("bisheng.common.errcode.llm_tenant", name)) is None


def test_long_partial_results_do_not_hide_the_failure_envelope():
    import json

    info = FailureContextAdapter.capture(TimeoutError(), category="model_service", service="embedding")
    payload = json.dumps(["useful result" * 4000, {"error": "failed", "failure_info": info}])
    assert FailureContextAdapter.from_payload(payload) == info


def test_real_provider_database_and_storage_exceptions_are_safe():
    import httpx
    import openai
    from minio.error import S3Error
    from sqlalchemy.exc import OperationalError

    provider = openai.AuthenticationError(
        "password=secret", response=httpx.Response(401, request=httpx.Request("GET", "https://internal")), body={}
    )
    assert FailureContextAdapter.from_error(provider)["category"] == "model_service"
    database = OperationalError("SELECT secret", {}, RuntimeError("secret"))
    assert FailureContextAdapter.from_error(database)["category"] == "database"
    storage = S3Error(
        response=None,
        code="AccessDenied",
        message="secret",
        resource="internal",
        request_id="r",
        host_id="h",
        bucket_name="b",
        object_name="o",
    )
    info = FailureContextAdapter.from_error(storage)
    assert info["category"] == "object_storage"
    assert FailureContextAdapter.from_error(storage) == info
    assert "secret" not in str(info)


def test_step_projection_preserves_failure_and_other_metadata():
    original = {
        "namespace": "n",
        "failure_info": FailureContextAdapter.capture(TimeoutError(), category="database"),
    }
    public = FailureContextAdapter.public_step_metadata(original)
    assert public == original


@pytest.mark.parametrize("kind", ["sync", "async", "stream", "astream"])
async def test_dependency_boundary_preserves_exception_and_partial_stream(kind):
    from bisheng.common.services.failure_context import failure_boundary

    error = RuntimeError("password=secret")

    def sync():
        raise error

    async def asynchronous():
        raise error

    def stream():
        yield "partial"
        raise error

    async def astream():
        yield "partial"
        raise error

    functions = {"sync": sync, "async": asynchronous, "stream": stream, "astream": astream}
    wrapped = failure_boundary("model_service", "embedding", "embed")(functions[kind])
    with pytest.raises(RuntimeError) as caught:
        if kind == "sync":
            wrapped()
        elif kind == "async":
            await wrapped()
        elif kind == "stream":
            iterator = wrapped()
            assert next(iterator) == "partial"
            next(iterator)
        else:
            iterator = wrapped()
            assert await anext(iterator) == "partial"
            await anext(iterator)
    assert caught.value is error
    assert FailureContextAdapter.from_error(error)["service"] == "embedding"


def test_legacy_tool_errors_and_attachment_errors_do_not_leak_diagnostics():
    import json

    secret = "password=secret https://internal"
    data = {"answer": "useful partial", "files": [{"name": "ok.pdf", "error_message": secret}]}
    public = FailureContextAdapter.public_payload(data)
    assert public["answer"] == "useful partial"
    assert "secret" not in str(public)
    old_result = json.dumps({"状态": "无结果", "错误信息": secret}, ensure_ascii=False)
    assert "secret" not in FailureContextAdapter.public_tool_result(old_result)
    assert "secret" not in FailureContextAdapter.public_tool_result("Error: " + secret)


def test_partial_knowledge_history_keeps_good_chunks_and_sanitizes_bad_source():
    good = "<knowledge_base_id>7</knowledge_base_id><knowledge_base_name>Public</knowledge_base_name>useful answer"
    bad = "<knowledge_base_id>8</knowledge_base_id><retrieval_error>password=secret</retrieval_error>"
    result = FailureContextAdapter.public_tool_result([good, bad], failed=True)
    assert result[0] == good
    assert "secret" not in result[1]


def test_wrapped_business_rejection_keeps_its_numeric_code():
    from bisheng.common.errcode.workstation import DepartmentDailyChatConcurrentLimitError

    error = RuntimeError("wrapped business failure")
    error.__cause__ = DepartmentDailyChatConcurrentLimitError()
    public = FailureContextAdapter.public_payload({"error_code": 11090}, exc=error)
    assert public["error_code"] == 12045
    assert "failure_info" not in public


@pytest.mark.parametrize(
    "status,message",
    [
        ("无权限", "该知识库不在当前任务可用的知识库列表中"),
        ("失败", "检索关键词不能为空"),
    ],
)
def test_safe_business_tool_results_keep_existing_copy(status, message):
    result = FailureContextAdapter.public_tool_result(
        {"状态": status, "错误信息": message, "detail": "password=secret"}
    )
    assert result["错误信息"] == message
    assert "secret" not in str(result)


def test_safe_retrieval_business_result_survives_history():
    value = "<retrieval_error>No permission to use this knowledge base</retrieval_error>"
    assert FailureContextAdapter.public_tool_result(value) == value


def test_public_sse_sanitizes_typed_diagnostic_message_and_keeps_source():
    import json

    from bisheng.common.errcode.server import InitLlmError

    error = InitLlmError(exception=RuntimeError("password=secret https://internal.example"))
    payload = json.loads(FailureContextAdapter.public_sse_event(error)["data"])
    assert "secret" not in str(payload)
    assert "https://internal.example" not in str(payload)
    assert payload["status_code"] == error.code
    assert payload["data"]["failure_info"]["category"] == "model_service"


def test_public_sse_preserves_registered_business_message():
    import json

    from bisheng.common.errcode.workstation import DepartmentDailyChatConcurrentLimitError

    error = DepartmentDailyChatConcurrentLimitError()
    payload = json.loads(FailureContextAdapter.public_sse_event(error)["data"])
    assert payload["status_message"] == error.message
    assert "failure_info" not in payload["data"]
