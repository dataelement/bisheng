"""JWT signing secret resolution (NVDB security fix, F068).

Historically ``Settings.jwt_secret`` shipped a hard-coded default that lived in
the open-source tree, so any deployment that never overrode it signed its login
cookies with a publicly known key — a forged ``user_id=1`` token was a super
admin. The default is gone; the secret now comes from one of two places:

1. ``config.yaml`` ``jwt_secret`` — explicit operator choice, used as-is.
2. Otherwise a random secret generated once at first boot and persisted in the
   ``config`` table under ``ConfigKeyEnum.JWT_SECRET`` so every api / worker
   process of the deployment signs and verifies with the same key.

The two leaked historical defaults are treated as "not configured": an upgraded
deployment whose YAML happens to carry the old default falls through to the
generated secret rather than keeping the known key alive.

Only the generated secret is cached (per process); the YAML value is read live
so a test that swaps ``settings`` sees its own key. Rotate by changing the YAML
value or deleting the DB row, then restart.
"""

from __future__ import annotations

import secrets
import threading

from loguru import logger

# Values that ever shipped as the code default. Both are public, so neither may
# be used as a signing key even when an operator copied it into config.yaml.
LEGACY_JWT_SECRETS: frozenset[str] = frozenset(
    {
        "secret",
        "secret_cF2kD4lW9wY4zL7eX1zX9vS1fA7eW4lQ",
    }
)

_SECRET_BYTES = 48

_lock = threading.Lock()
_generated: str | None = None


def _settings_object():
    """Current ``config_service.settings`` (looked up on every call, never bound at import)."""
    from bisheng.common.services import config_service

    return config_service.settings


def configured_jwt_secret() -> str | None:
    """Return the YAML-configured secret, or ``None`` when absent / legacy."""
    value = getattr(_settings_object(), "jwt_secret", None)
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    if value in LEGACY_JWT_SECRETS:
        logger.warning(
            "config.yaml jwt_secret is a publicly known legacy default; ignoring it and using the generated secret"
        )
        return None
    return value


def _load_or_create_db_secret() -> str:
    # Deferred: the config DAO drags in the database package, which must not be
    # imported by modules that are loaded before the app context exists.
    from sqlalchemy.exc import IntegrityError

    from bisheng.common.models.config import Config, ConfigDao, ConfigKeyEnum
    from bisheng.core.database import get_sync_db_session

    row = ConfigDao.get_config(ConfigKeyEnum.JWT_SECRET)
    if row and row.value:
        return row.value
    candidate = secrets.token_urlsafe(_SECRET_BYTES)
    try:
        with get_sync_db_session() as session:
            session.add(Config(key=ConfigKeyEnum.JWT_SECRET.value, value=candidate))
            session.commit()
        logger.info("generated a new JWT signing secret and stored it in the config table")
        return candidate
    except IntegrityError:
        # Another process won the first-boot race; its value is the one to use.
        row = ConfigDao.get_config(ConfigKeyEnum.JWT_SECRET)
        if row and row.value:
            return row.value
        raise


def resolve_jwt_secret() -> str:
    """Return the signing secret for this deployment."""
    global _generated
    configured = configured_jwt_secret()
    if configured:
        return configured
    if _generated:
        return _generated
    with _lock:
        if not _generated:
            _generated = _load_or_create_db_secret()
        return _generated


def reset_cache() -> None:
    """Test hook: forget the cached generated secret."""
    global _generated
    with _lock:
        _generated = None
