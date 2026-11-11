"""Quota guidance uses capacity exit semantics and the safe resource summary."""

import pytest

from bisheng_cli.errors import EXIT_CAPACITY, EXIT_PRECHECK_FAILED, error_from_platform, render_human


@pytest.mark.parametrize("code", [16125, 16226])
def test_quota_has_capacity_exit_and_resource_summary(code):
    error = error_from_platform(
        code,
        "Insufficient runtime capacity",
        details={
            "reason": "k8s_quota_exceeded",
            "runtime_stage": "preparing",
            "operation_id": "operation-a",
            "quota": {"limits.cpu": {"requested": "2", "used": "3", "limit": "4"}},
        },
    )
    text = render_human(error)
    assert error.exit_code == EXIT_CAPACITY
    assert "资源配额不足" in text and "平台管理员" in text
    assert "limits.cpu" in text and "本次申请 2" in text and "当前占用 3" in text and "上限 4" in text
    assert "operation-a" in text and "依赖构建失败" not in text and "requirements.txt" not in text


def test_unknown_quota_fields_and_invalid_quantities_are_not_rendered():
    error = error_from_platform(
        16226,
        details={
            "reason": "k8s_quota_exceeded",
            "quota": {
                "private-resource": {"requested": "secret", "used": "1", "limit": "2"},
                "limits.cpu": {"requested": "secret", "used": "1", "limit": "2"},
            },
        },
    )
    assert "secret" not in render_human(error) and "private-resource" not in render_human(error)


def test_ordinary_build_failure_keeps_its_original_classification():
    error = error_from_platform(16227, details={"reason": "k8s_api_refused"})
    assert error.exit_code == EXIT_PRECHECK_FAILED
    assert "资源配额不足" not in render_human(error)
