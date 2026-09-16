"""异常层次与脱敏（AC-04 / AC-07 / AC-15 / AC-19 / AC-25）。"""

from __future__ import annotations

import inspect

import pytest

from bisheng_sdk import errors
from tests.helpers.platform_mock import FAKE_APP_TOKEN, FAKE_DEV_HANDLE, FAKE_OBO

ALL_ERROR_CLASSES = [
    value
    for _name, value in vars(errors).items()
    if inspect.isclass(value) and issubclass(value, errors.BishengSdkError) and value is not errors.BishengSdkError
]


def _instance(cls: type[errors.BishengSdkError]) -> errors.BishengSdkError:
    if cls is errors.SdkIncompatibleError:
        return cls(sdk_version="0.1.0", min_compatible="0.3.0", platform_version="3.0.0")
    return cls()


def test_every_error_carries_message_and_next_step():
    assert ALL_ERROR_CLASSES, "异常类应当被 vars() 枚举到，层次改名了就该来改这个测试"
    for cls in ALL_ERROR_CLASSES:
        error = _instance(cls)
        assert error.message, f"{cls.__name__} 没有 message"
        assert error.next_step, f"{cls.__name__} 没有 next_step"
        assert "下一步" in str(error)


def test_single_base_and_auth_vs_retrieve_are_not_subclasses():
    for cls in ALL_ERROR_CLASSES:
        assert issubclass(cls, errors.BishengSdkError)
    # auth 缺身份与 retrieve 缺访问者凭据是两件事：前者说"这条路径不该调 auth"，
    # 后者说"这次调用没有访问者"。谁是谁的子类，应用的 except 就会吃掉另一个。
    assert not issubclass(errors.PlatformIdentityMissingError, errors.VisitorCredentialMissingError)
    assert not issubclass(errors.VisitorCredentialMissingError, errors.PlatformIdentityMissingError)


@pytest.mark.parametrize(
    "secret",
    [FAKE_APP_TOKEN, "bs-pat-" + "y" * 24, f"Bearer {FAKE_OBO}", FAKE_OBO, FAKE_DEV_HANDLE],
)
def test_redact_masks_every_credential_shape(secret: str):
    error = errors.PlatformRefusedError(
        f"平台拒绝：{secret}",
        code=12345,
        details={"echo": secret, "nested": {"again": [secret]}},
    )
    rendered = f"{error}{error!r}{error.details}"
    assert secret not in rendered
    assert errors.redact(secret) != secret


def test_platform_refused_keeps_code_and_details_verbatim():
    error = errors.PlatformRefusedError("未登记的业务码", code=26399, details={"hint": "去看文档", "n": 3})
    assert error.code == 26399
    assert error.details == {"hint": "去看文档", "n": 3}
    assert "未登记的业务码" in str(error)


def test_structured_attributes_survive():
    assert errors.ScopeMissingError(required="knowledge:read").required == "knowledge:read"
    assert errors.TargetUnreachableError(ids=[1, 2]).ids == [1, 2]
    revoked = errors.CapabilityRevokedError(capability="财务档案", reason="revoked")
    assert (revoked.capability, revoked.reason) == ("财务档案", "revoked")
    assert errors.AttachmentTooLargeError(path="a.bin", limit_bytes=20 * 1024 * 1024).limit_bytes == 20 * 1024 * 1024
    incompatible = errors.SdkIncompatibleError(sdk_version="0.1.0", min_compatible="0.3.0", platform_version="3.0.0")
    assert "0.3.0" in str(incompatible) and "0.1.0" in str(incompatible)


def test_storage_errors_are_six_distinguishable_classes():
    classes = (
        errors.StorageHandleMissingError,
        errors.StorageHandleRejectedError,
        errors.StorageUnavailableError,
        errors.AttachmentNotFoundError,
        errors.AttachmentTooLargeError,
        errors.InvalidAttachmentPathError,
    )
    for cls in classes:
        for other in classes:
            if cls is not other:
                assert not issubclass(cls, other), f"{cls.__name__} 不该是 {other.__name__} 的子类"
    messages = {str(_instance(cls)) for cls in classes}
    assert len(messages) == len(classes), "六类 storage 错误的文案必须互不相同"
