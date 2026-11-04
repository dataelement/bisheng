"""Entry routing uses backend v2 projections without a legacy manager fallback."""

import pytest

from app_proxy.clients import ManagerRouteClient
from app_proxy.config import Config


@pytest.fixture(autouse=True)
def wired():
    yield


def test_entry_default_and_explicit_old_protocol():
    assert Config().protocol_version == 2
    for value in (1, 0, 3):
        with pytest.raises(ValueError, match="v2"):
            Config(protocol_version=value)
        with pytest.raises(ValueError, match="v2"):
            ManagerRouteClient("http://backend", "", protocol_version=value)
