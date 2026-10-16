"""BaseErrorCode fills the placeholders of its class message template."""

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import (
    KnowledgeMetadataFieldConflictError,
    KnowledgeMetadataFieldNotExistError,
    KnowledgeMetadataValueTypeConvertError,
)
from bisheng.common.errcode.linsight import SkillGitHubUrlInvalidError
from bisheng.common.errcode.server import AsrTranscriptionFailedError, NoAsrModelConfigError


def test_kwargs_fill_the_template():
    err = KnowledgeMetadataFieldNotExistError(field_name="author")
    assert err.message == "Meta data fields author Does not exist"
    # The frontend interpolates copy from data, so the raw field must stay there.
    assert err.to_dict()["data"]["field_name"] == "author"


def test_two_kwargs_fill_the_template():
    err = KnowledgeMetadataValueTypeConvertError(field_name="age", error_msg="not a number")
    assert err.message == "Meta data fields age Value type conversion error: not a number"
    assert "{" not in KnowledgeMetadataFieldConflictError(field_name="id").message


def test_exception_fills_the_exception_placeholder():
    err = AsrTranscriptionFailedError(exception=RuntimeError("provider timeout"))
    assert err.message == "Speech recognition failed, please try again later. Reason: provider timeout"
    assert err.to_dict()["data"]["exception"] == "provider timeout"


def test_missing_values_keep_their_placeholders():
    # No kwarg for a placeholder: keep the literal text instead of raising.
    assert SkillGitHubUrlInvalidError().message == SkillGitHubUrlInvalidError.Msg
    assert AsrTranscriptionFailedError().message.endswith("Reason: {exception}")


def test_explicit_msg_is_not_formatted():
    err = KnowledgeMetadataFieldNotExistError(msg="custom {field_name}", field_name="x")
    assert err.message == "custom {field_name}"


def test_template_without_placeholders_is_unchanged():
    assert NoAsrModelConfigError().message == NoAsrModelConfigError.Msg


def test_malformed_template_falls_back_to_raw_text():
    class _Odd(BaseErrorCode):
        Code = 1
        Msg = "bad {0} and {x!z}"

    assert _Odd(x=1).message == "bad {0} and {x!z}"
