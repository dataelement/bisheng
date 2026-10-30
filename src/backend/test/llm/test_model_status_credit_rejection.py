"""A per-user platform credit rejection must not mark the shared model as broken.

The client module (DSH) rejects a call before it reaches the provider when this
one user is out of credits. Flipping the model to "abnormal" would show every
user a broken model that the next probe immediately flips back.
"""

import pytest

from bisheng.common.errcode.dsh import DshModelNotAllowedError, DshMonthlyTokenLimitExceededError
from test.llm.test_bisheng_llm_context_overflow import MESSAGES, _wrapper
from test.llm.test_bisheng_llm_context_overflow import status_writes as status_writes

REJECTIONS = [DshMonthlyTokenLimitExceededError, DshModelNotAllowedError]


@pytest.mark.parametrize("error", REJECTIONS)
@pytest.mark.parametrize("streaming", [True, False])
def test_generate_keeps_model_status(status_writes, streaming, error):
    inst = _wrapper(error(), streaming, status_writes)
    with pytest.raises(error):
        inst._generate(MESSAGES)
    assert status_writes == []


@pytest.mark.parametrize("error", REJECTIONS)
async def test_agenerate_keeps_model_status(status_writes, error):
    inst = _wrapper(error(), False, status_writes)
    with pytest.raises(error):
        await inst._agenerate(MESSAGES)
    assert status_writes == []


@pytest.mark.parametrize("error", REJECTIONS)
def test_stream_keeps_model_status(status_writes, error):
    inst = _wrapper(error(), True, status_writes)
    with pytest.raises(error):
        list(inst._stream(MESSAGES))
    assert status_writes == []


@pytest.mark.parametrize("error", REJECTIONS)
async def test_astream_keeps_model_status(status_writes, error):
    inst = _wrapper(error(), True, status_writes)
    with pytest.raises(error):
        async for _ in inst._astream(MESSAGES):
            pass
    assert status_writes == []
