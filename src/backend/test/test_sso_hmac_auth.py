"""Tests for F014 HMAC dependency (``verify_hmac``).

Covers:
- Canonical signing string (METHOD + PATH + raw body).
- Header mismatch / missing / empty-secret → 19301.
- Body replay: downstream Pydantic parsers can still read the request body
  after the dependency has consumed it for signature verification.
"""

import pytest
from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel
from starlette.testclient import TestClient

# The hmac fixtures in this module's ``conftest`` cascade into this file.
pytest_plugins = ['test.fixtures.sso_sync']


# ---------------------------------------------------------------------------
# Mini test app — declares a POST route guarded by verify_hmac
# ---------------------------------------------------------------------------

class _Echo(BaseModel):
    msg: str


def _build_app() -> FastAPI:
    from bisheng.sso_sync.domain.services.hmac_auth import verify_hmac

    app = FastAPI()

    @app.post('/api/v1/internal/sso/login-sync')
    async def login_sync(
        payload: _Echo,
        request: Request,
        _: None = Depends(verify_hmac),
    ):
        # Reading body a second time verifies _receive replay worked.
        second_read = await request.body()
        return {
            'ok': True,
            'msg': payload.msg,
            'body_len': len(second_read),
        }

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHmacDependency:

    def test_valid_signature_passes(self, configure_sso_secret, hmac_signer):
        app = _build_app()
        body = b'{"msg":"hello"}'
        sig = hmac_signer('POST', '/api/v1/internal/sso/login-sync', body)
        with TestClient(app) as client:
            resp = client.post(
                '/api/v1/internal/sso/login-sync',
                content=body,
                headers={
                    'X-Signature': sig,
                    'Content-Type': 'application/json',
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data == {'ok': True, 'msg': 'hello', 'body_len': len(body)}

    def test_missing_header_rejected(self, configure_sso_secret):
        app = _build_app()
        with TestClient(app) as client:
            resp = client.post(
                '/api/v1/internal/sso/login-sync',
                json={'msg': 'hi'},
            )
        # BaseErrorCode.http_exception uses Code (19301) as HTTPException
        # status_code — project convention; the body still semantically means
        # "unauthenticated". Assert the code is present so later tests can
        # rely on it without caring about the specific HTTP number.
        assert resp.status_code == 19301

    def test_empty_signature_rejected(
        self, configure_sso_secret, hmac_signer,
    ):
        app = _build_app()
        with TestClient(app) as client:
            resp = client.post(
                '/api/v1/internal/sso/login-sync',
                json={'msg': 'hi'},
                headers={'X-Signature': '   '},  # whitespace-only
            )
        assert resp.status_code == 19301

    def test_invalid_signature_rejected(
        self, configure_sso_secret, hmac_signer,
    ):
        app = _build_app()
        # sign over a different body than we actually send
        bad_sig = hmac_signer(
            'POST', '/api/v1/internal/sso/login-sync', b'{"msg":"other"}',
        )
        with TestClient(app) as client:
            resp = client.post(
                '/api/v1/internal/sso/login-sync',
                content=b'{"msg":"hi"}',
                headers={
                    'X-Signature': bad_sig,
                    'Content-Type': 'application/json',
                },
            )
        assert resp.status_code == 19301

    def test_empty_secret_fails_closed(
        self, disable_sso_secret, hmac_signer,
    ):
        """With secret='' every request — even one 'signed' with the empty
        secret — must be rejected. Silent acceptance would defeat the point
        of HMAC during misconfigured rollouts."""
        import hashlib
        import hmac as _h
        app = _build_app()
        body = b'{"msg":"hi"}'
        # craft a valid-looking signature against the empty secret
        empty_sig = _h.new(
            b'', f'POST\n/api/v1/internal/sso/login-sync\n'.encode() + body,
            hashlib.sha256,
        ).hexdigest()
        with TestClient(app) as client:
            resp = client.post(
                '/api/v1/internal/sso/login-sync',
                content=body,
                headers={
                    'X-Signature': empty_sig,
                    'Content-Type': 'application/json',
                },
            )
        assert resp.status_code == 19301
