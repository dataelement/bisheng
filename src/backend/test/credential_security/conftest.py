"""Live tests are opt-in and require an explicitly disposable deployment.

Run with --confcutdir=test/credential_security to avoid unit-suite premocks.
Never point the live fixture at a customer installation.
"""

import os
from pathlib import Path

import pytest


@pytest.fixture
def live_settings(monkeypatch):
    if os.getenv("BISHENG_CREDENTIAL_LIVE_DISPOSABLE") != "true":
        pytest.skip("NOT EXECUTED: isolated disposable middleware environment not configured")
    bundle = os.getenv("BISHENG_CREDENTIAL_LIVE_BUNDLE")
    key = os.getenv("BISHENG_CREDENTIAL_LIVE_KEYS")
    if not bundle or not key:
        pytest.fail("Explicit live bundle and key file are required")
    from bisheng.core.config.credential_tool import check_bundle
    from bisheng.core.config.secret_crypto import get_keyring

    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(Path(key).absolute()))
    get_keyring.cache_clear()
    settings, _, pending = check_bundle(bundle, enforce=True)
    assert pending == [], "Live acceptance requires governed credentials"
    yield settings
    get_keyring.cache_clear()
