"""Opt-in isolated DSH fixtures, including fail-loud external test stores."""

import json
import os
from urllib.parse import urlsplit

import pytest
from sqlalchemy.engine import make_url

from test.dsh.fixtures import CONTRACT_DIRECTORY, DshTestClock, identity_scenarios


@pytest.fixture
def dsh_contracts():
    return {path.stem: json.loads(path.read_text()) for path in CONTRACT_DIRECTORY.glob("*.json")}


@pytest.fixture
def dsh_clock():
    return DshTestClock()


@pytest.fixture
def dsh_identities():
    return identity_scenarios()


@pytest.fixture
def dsh_database_url():
    value = os.environ.get("DSH_TEST_DATABASE_URL")
    if not value:
        raise pytest.UsageError("DSH_TEST_DATABASE_URL must explicitly name an isolated dsh_test database")
    url = make_url(value)
    if not url.database or not url.database.startswith("dsh_test_"):
        raise pytest.UsageError("DSH test database names must start with dsh_test_")
    return value


@pytest.fixture
def dsh_redis_url():
    value = os.environ.get("DSH_TEST_REDIS_URL")
    if not value or os.environ.get("DSH_TEST_REDIS_ISOLATED") != "1":
        raise pytest.UsageError("An isolated DSH_TEST_REDIS_URL and DSH_TEST_REDIS_ISOLATED=1 are required")
    url = urlsplit(value)
    if url.scheme not in {"redis", "rediss"} or not url.hostname:
        raise pytest.UsageError("DSH test Redis requires an explicit redis/rediss endpoint")
    return value
