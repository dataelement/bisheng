"""Signed external-user identity for WeKnora API-key requests.

A WeKnora workspace whose ``APIPrincipalConfig`` runs in ``signed_token`` mode
rejects API-key requests that do not also carry a short-lived HS256 token. The
token subject is the BiSheng user performing the operation; it is bound for the
duration of one operation with ``provider_external_identity`` and never taken
from request parameters, prompt content or the model.

The HMAC secret is sealed on the provider instance (``upload_credential_ref``).
Instances without it keep using plain API-key auth, so workspaces in ``tenant``
mode are unaffected.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta

import jwt

EXTERNAL_USER_TOKEN_HEADER = "X-External-User-Token"

_TOKEN_TTL = timedelta(minutes=5)

_current_external_user_id: ContextVar[int | None] = ContextVar("provider_external_user_id", default=None)


@contextmanager
def provider_external_identity(user_id):
    """Bind the acting BiSheng user for provider calls made inside this scope.

    Anything that is not a positive integer identity binds None; the request
    builder fails closed if the instance needs a subject and none is bound.
    """
    bound = user_id if type(user_id) is int and user_id > 0 else None
    token = _current_external_user_id.set(bound)
    try:
        yield
    finally:
        _current_external_user_id.reset(token)


def current_external_user_id() -> int | None:
    return _current_external_user_id.get()


def mint_external_user_token(*, secret: str, weknora_tenant_id: int, external_user_id: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": external_user_id,
            "tenant_id": weknora_tenant_id,
            "aud": "weknora",
            "iat": now,
            "nbf": now,
            "exp": now + _TOKEN_TTL,
        },
        secret,
        algorithm="HS256",
    )


def unseal_external_token_secret(ref: str | None) -> str | None:
    """Return the plain HMAC secret, or None when it cannot be used safely."""
    from bisheng.core.config.settings import decrypt_token

    if not isinstance(ref, str) or not ref.startswith("fernet:"):
        return None
    try:
        value = decrypt_token(ref.removeprefix("fernet:"))
    except Exception:
        return None
    if not value or not value.isascii() or not value.isprintable() or any(c.isspace() for c in value):
        return None
    return value
