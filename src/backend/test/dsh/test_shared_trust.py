"""Native signing is independent of Gateway secrets. 覆盖 AC: AC-01, AC-03."""

import pytest

from bisheng.common.errcode.dsh import DshInvalidAccessTokenError
from bisheng.dsh.infrastructure.token_keys import KEY_ID, LocalTokenKeys


async def test_native_key_is_stable_and_purpose_separated():
    master = "synthetic-platform-master-for-native-tests"
    first = await LocalTokenKeys(lambda: master).resolve(KEY_ID)
    assert first == await LocalTokenKeys(lambda: master).resolve(KEY_ID)
    assert first != master.encode() and len(first) == 32
    assert first != await LocalTokenKeys(lambda: master + "rotated").resolve(KEY_ID)
    with pytest.raises(DshInvalidAccessTokenError):
        await LocalTokenKeys(lambda: master).resolve("dsh-access-v1")
