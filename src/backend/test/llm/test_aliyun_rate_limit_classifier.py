from types import SimpleNamespace

import pytest

from bisheng.llm.domain.services.aliyun_rate_limit_classifier import AliyunRateLimitClassifier
from bisheng.llm.domain.utils import wrapper_bisheng_model_limit_check


class ProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 429,
        code: str | None = None,
        body: dict | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.body = body
        self.request_id = request_id


def model(model_id: int = 17, name: str = "Qwen Plus") -> SimpleNamespace:
    return SimpleNamespace(id=model_id, name=name, model_name="qwen-plus")


def server(
    server_type: str = "qwen",
    *,
    endpoint: str | None = None,
) -> SimpleNamespace:
    config = {"openai_api_base": endpoint} if endpoint else {}
    return SimpleNamespace(id=9, type=server_type, config=config, limit_flag=False)


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("Throttling.RateQuota", "Requests rate limit exceeded"),
        ("Throttling.AllocationQuota", "Allocated quota exceeded"),
        ("Throttling.BurstRate", "Request rate increased too quickly"),
        ("LimitRequests", "Too many requests"),
        ("limit_requests", "Requests rate limit exceeded"),
        ("limit_burst_rate", "Request rate increased too quickly"),
        ("ResourceExhausted", "Token rate limit reached"),
        ("insufficient_quota", "You exceeded your current quota"),
    ],
)
def test_qwen_transient_rate_limit_whitelist(code: str, message: str) -> None:
    observation = AliyunRateLimitClassifier.classify(
        model=model(),
        server=server(),
        exc=ProviderError(message, code=code, request_id="req-123"),
    )

    assert observation is not None
    assert observation.model_id == 17
    assert observation.provider_code == code
    assert observation.request_id == "req-123"


def test_trusted_dashscope_openai_compatible_endpoint_is_aliyun() -> None:
    observation = AliyunRateLimitClassifier.classify(
        model=model(),
        server=server(
            "openai",
            endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        exc=ProviderError(
            "throttled",
            body={"error": {"code": "Throttling.RateQuota", "message": "rate limit"}},
        ),
    )

    assert observation is not None
    assert observation.provider_code == "Throttling.RateQuota"


def test_model_name_does_not_make_an_untrusted_provider_aliyun() -> None:
    observation = AliyunRateLimitClassifier.classify(
        model=model(name="qwen-compatible"),
        server=server("openai", endpoint="https://third-party.example/v1"),
        exc=ProviderError("rate limit", code="Throttling.RateQuota"),
    )

    assert observation is None


@pytest.mark.parametrize(
    ("code", "message", "status_code"),
    [
        ("PrepaidBillOverdue", "prepaid bill overdue", 429),
        ("PostpaidBillOverdue", "postpaid bill overdue", 429),
        ("CommodityNotPurchased", "commodity not purchased", 429),
        ("Arrearage", "account is in arrears", 429),
        ("InvalidApiKey", "authentication failed", 401),
        ("AccessDenied", "permission denied", 403),
        ("DataInspectionFailed", "content safety policy rejected", 429),
    ],
)
def test_permanent_or_safety_errors_never_enter_busy_state(
    code: str,
    message: str,
    status_code: int,
) -> None:
    observation = AliyunRateLimitClassifier.classify(
        model=model(),
        server=server(),
        exc=ProviderError(message, status_code=status_code, code=code),
    )

    assert observation is None


def test_whitelisted_code_requires_http_429() -> None:
    observation = AliyunRateLimitClassifier.classify(
        model=model(),
        server=server(),
        exc=ProviderError(
            "provider service error",
            status_code=503,
            code="Throttling.RateQuota",
        ),
    )

    assert observation is None


def test_diagnostic_detail_is_bounded_and_secret_masked() -> None:
    secret = "sk-test-secret-value"
    observation = AliyunRateLimitClassifier.classify(
        model=model(),
        server=server(),
        exc=ProviderError(
            f"rate limit api_key={secret} Authorization: Bearer bearer-secret "
            "prompt='private input words' tool_args='private tool parameters' " + "x" * 1000,
            code="Throttling.RateQuota",
            body={"request_id": "req-body", "api_key": secret},
        ),
    )

    assert observation is not None
    assert observation.request_id == "req-body"
    assert secret not in observation.masked_detail
    assert "bearer-secret" not in observation.masked_detail
    assert "private input words" not in observation.masked_detail
    assert "private tool parameters" not in observation.masked_detail
    assert len(observation.masked_detail) <= 512


def test_structured_body_is_masked_before_stringification() -> None:
    secret_message = "private prompt in structured body"
    secret_key = "sk-structured-secret"
    observation = AliyunRateLimitClassifier.classify(
        model=model(),
        server=server(),
        exc=ProviderError(
            "rate limit",
            code="Throttling.RateQuota",
            body={
                "messages": [{"role": "user", "content": secret_message}],
                "api_key": secret_key,
                "request_id": "req-safe",
            },
        ),
    )

    assert observation is not None
    assert secret_message not in observation.masked_detail
    assert secret_key not in observation.masked_detail
    assert "req-safe" in observation.masked_detail


def test_confirmed_aliyun_throttle_preserves_existing_model_error_semantics(monkeypatch) -> None:
    updates: list[tuple[int, str]] = []
    fake_self = SimpleNamespace(
        model_info=SimpleNamespace(id=17, model_type="embedding"),
        server_info=server(),
        sync_update_model_status=lambda status, remark: updates.append((status, remark)),
    )
    monkeypatch.setattr("bisheng.llm.domain.utils.upload_telemetry_log", lambda *args, **kwargs: None)

    @wrapper_bisheng_model_limit_check
    def invoke(_self):
        raise ProviderError("rate limit", code="Throttling.RateQuota")

    with pytest.raises(ProviderError):
        invoke(fake_self)

    assert updates == [(1, "rate limit")]


def test_permanent_aliyun_error_still_persists_model_error(monkeypatch) -> None:
    updates: list[tuple[int, str]] = []
    fake_self = SimpleNamespace(
        model_info=SimpleNamespace(id=17, model_type="embedding"),
        server_info=server(),
        sync_update_model_status=lambda status, remark: updates.append((status, remark)),
    )
    monkeypatch.setattr("bisheng.llm.domain.utils.upload_telemetry_log", lambda *args, **kwargs: None)

    @wrapper_bisheng_model_limit_check
    def invoke(_self):
        raise ProviderError("account balance insufficient", code="PrepaidBillOverdue")

    with pytest.raises(ProviderError):
        invoke(fake_self)

    assert updates == [(1, "account balance insufficient")]
