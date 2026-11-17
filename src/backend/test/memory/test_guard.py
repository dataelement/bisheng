"""Content validation of memory items (AC-12, AC-14, AC-16)."""

import pytest

from bisheng.common.errcode.memory import (
    MemoryContentEmptyError,
    MemoryContentRelativeTimeError,
    MemoryContentSensitiveError,
    MemoryContentTooLongError,
    MemoryContentTypeInvalidError,
)
from bisheng.memory.domain.services.guard import SensitiveContentGuard, check_relative_time, validate_item


def test_ac12_length_limit_200():
    """AC-12: content over 200 characters is rejected, 200 is accepted."""
    validate_item("好" * 200, "fact")
    with pytest.raises(MemoryContentTooLongError):
        validate_item("好" * 201, "fact")


def test_ac12_empty_rejected():
    with pytest.raises(MemoryContentEmptyError):
        validate_item("   ", "fact")


@pytest.mark.parametrize("item_type", ["fact", "preference", "experience"])
def test_ac12_types_accepted(item_type):
    validate_item("用户在华东区负责售前方案", item_type)


@pytest.mark.parametrize("item_type", ["note", "", None, "FACT"])
def test_ac12_other_types_rejected(item_type):
    with pytest.raises(MemoryContentTypeInvalidError):
        validate_item("用户喜欢简洁的回答", item_type)


@pytest.mark.parametrize(
    "text",
    [
        "我的 OpenAI key 是 sk-proj-3fA9kLmN0pQrStUvWxYz12345678",
        "AWS 账号 AKIAIOSFODNN7EXAMPLE 用于测试",
        "github token ghp_16C7e42F292c6912E7710c838347Ae178B4a",
        "服务令牌 9fQ2xLk8Zr7TmW3vNp6Yb4Hs1Dc5Gj0K",
        "-----BEGIN RSA PRIVATE KEY----- abc",
    ],
)
def test_ac16_secret_keys_rejected(text):
    """AC-16: key prefixes and high-entropy strings are rejected."""
    with pytest.raises(MemoryContentSensitiveError):
        SensitiveContentGuard.check(text)


@pytest.mark.parametrize(
    "text",
    [
        "用户的项目代号是 Phoenix-2026，负责人是王经理",
        "用户偏好使用 https://docs.example.com/guide/getting-started 这类文档链接",
        "用户的工号是 A10086",
        "用户常用的模型是 deepseek-chat 与 qwen-max",
    ],
)
def test_ac16_ordinary_text_with_codes_accepted(text):
    SensitiveContentGuard.check(text)


@pytest.mark.parametrize("text", ["我的身份证号 11010519491231002X", "证件号码 440308199901010012"])
def test_ac16_id_card_with_valid_checksum_rejected(text):
    with pytest.raises(MemoryContentSensitiveError):
        SensitiveContentGuard.check(text)


@pytest.mark.parametrize("text", ["订单号 110105194912310021", "流水号 440308199901010015"])
def test_ac16_18_digits_with_wrong_checksum_accepted(text):
    SensitiveContentGuard.check(text)


@pytest.mark.parametrize("text", ["工资卡 4111 1111 1111 1111", "银行卡号 6222021001115550003"])
def test_ac16_bank_card_luhn_rejected(text):
    with pytest.raises(MemoryContentSensitiveError):
        SensitiveContentGuard.check(text)


@pytest.mark.parametrize("text", ["报销单号 4111111111111112", "用户手机号段 13800138000"])
def test_ac16_digits_failing_luhn_accepted(text):
    SensitiveContentGuard.check(text)


@pytest.mark.parametrize(
    "text",
    ["我的邮箱密码是 abc12345", "password: hunter2", "VPN 口令为 qwer!234", "数据库 passwd=Root@123"],
)
def test_ac16_password_assignment_rejected(text):
    with pytest.raises(MemoryContentSensitiveError):
        SensitiveContentGuard.check(text)


@pytest.mark.parametrize("text", ["用户经常忘记密码，希望提醒他用密码管理器", "用户在做密码学方向的研究"])
def test_ac16_password_mention_without_value_accepted(text):
    SensitiveContentGuard.check(text)


def test_ac16_guard_runs_inside_validate_item():
    with pytest.raises(MemoryContentSensitiveError):
        validate_item("密码是 abc12345", "fact")


@pytest.mark.parametrize(
    "text",
    [
        "用户今天下午要开会",
        "明天交周报",
        "用户下周二有个重要会议",
        "本月底前完成预算",
        "Meeting with the CFO tomorrow",
        "Release planned for next week",
        "三天后出差",
        "用户本周在北京出差",
        "下周三之前交周报",
        "这个月要完成评审",
    ],
)
def test_ac14_relative_time_rejected(text):
    """AC-14: relative time words must be converted to dates before writing."""
    with pytest.raises(MemoryContentRelativeTimeError):
        check_relative_time(text)
    with pytest.raises(MemoryContentRelativeTimeError):
        validate_item(text, "fact")


@pytest.mark.parametrize(
    "text",
    [
        "用户 2026-11-17（周二）有个重要会议",
        "用户每周二例会",
        "用户偏好在周报里列出下一步计划",
        "The weekly report is due on 2026-11-20",
        # Period words naming a report section are labels, not dates.
        "用户偏好周报采用本周结论、关键数据、风险与支持三段式结构",
        "用户写月报时先写本月总结，再写下月计划",
        "用户的周报里有上周回顾和下周重点",
    ],
)
def test_ac14_absolute_dates_accepted(text):
    check_relative_time(text)
    validate_item(text, "fact")


def test_reason_codes_are_distinct():
    codes = {
        MemoryContentTooLongError.Code,
        MemoryContentSensitiveError.Code,
        MemoryContentRelativeTimeError.Code,
        MemoryContentTypeInvalidError.Code,
        MemoryContentEmptyError.Code,
    }
    assert len(codes) == 5
