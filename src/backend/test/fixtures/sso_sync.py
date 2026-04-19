"""Shared fixtures for F014 SSO sync tests.

Provides:
- ``hmac_secret`` + ``hmac_signer`` — canonical HMAC-SHA256 signer matching
  the Gateway signing string (``METHOD + "\\n" + PATH + "\\n" + raw_body``).
- ``configure_sso_secret`` — monkeypatch the ``settings.sso_sync`` proxy on
  the hmac_auth module so the dependency picks up a real
  :class:`SSOSyncConf` during the test lifetime. The global config_service
  is itself pre-mocked (see ``test/conftest.py``), so we patch in a real
  conf instance right on the ``hmac_auth.settings`` symbol to make the
  tests deterministic without touching the upstream singleton.
"""

import hashlib
import hmac as _hmac
from types import SimpleNamespace

import pytest

from bisheng.core.config.sso_sync import SSOSyncConf


_DEFAULT_TEST_SECRET = 'test-hmac-secret-ABC123'


@pytest.fixture
def hmac_secret() -> str:
    return _DEFAULT_TEST_SECRET


@pytest.fixture
def hmac_signer(hmac_secret):
    """Return a ``sign(method, path, body)`` callable producing hex digests.

    Mirrors :func:`compute_signature` in the hmac_auth module verbatim so a
    drift there will surface here immediately.
    """
    def _sign(method: str, path: str, body: bytes | str) -> str:
        if isinstance(body, str):
            body = body.encode('utf-8')
        msg = f'{method.upper()}\n{path}\n'.encode() + (body or b'')
        return _hmac.new(
            hmac_secret.encode('utf-8'), msg, hashlib.sha256,
        ).hexdigest()
    return _sign


@pytest.fixture
def configure_sso_secret(monkeypatch, hmac_secret):
    """Install a real SSOSyncConf into the hmac_auth module's ``settings``
    proxy so the dependency passes / fails on controlled inputs rather than
    on the MagicMock auto-attribute maze installed by ``premock_import_chain``.
    """
    import bisheng.sso_sync.domain.services.hmac_auth as mod

    conf = SSOSyncConf(
        gateway_hmac_secret=hmac_secret,
        signature_header='X-Signature',
        user_lock_ttl_seconds=30,
        orphan_config_id=9999,
    )

    fake_settings = SimpleNamespace(sso_sync=conf)
    monkeypatch.setattr(mod, 'settings', fake_settings)
    return conf


@pytest.fixture
def disable_sso_secret(monkeypatch):
    """Force ``gateway_hmac_secret=''`` to exercise the fail-closed branch."""
    import bisheng.sso_sync.domain.services.hmac_auth as mod

    conf = SSOSyncConf(
        gateway_hmac_secret='',
        signature_header='X-Signature',
    )
    monkeypatch.setattr(mod, 'settings', SimpleNamespace(sso_sync=conf))
    return conf
