import inspect

from bisheng.common.errcode import knowledge_space
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge_space import (
    SpacePersonalPinForbiddenError,
    SpacePinLimitError,
)


def test_knowledge_space_pin_error_codes_are_unique_and_explicit():
    assert issubclass(SpacePersonalPinForbiddenError, BaseErrorCode)
    assert issubclass(SpacePinLimitError, BaseErrorCode)
    assert SpacePersonalPinForbiddenError.Code == 18078
    assert SpacePersonalPinForbiddenError.Msg == "个人知识库不支持置顶"
    assert SpacePinLimitError.Code == 18079
    assert SpacePinLimitError.Msg == "每类最多置顶 5 个知识库"

    codes = [
        value.Code
        for _, value in inspect.getmembers(knowledge_space, inspect.isclass)
        if issubclass(value, BaseErrorCode) and value is not BaseErrorCode
    ]
    assert len(codes) == len(set(codes))
