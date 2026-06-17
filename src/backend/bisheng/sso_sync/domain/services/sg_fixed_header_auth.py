"""Fixed-header auth for SG sync endpoints."""

import logging

from fastapi import Request

from bisheng.common.errcode.sso_sync import SsoHmacInvalidError
from bisheng.common.services.config_service import settings

logger = logging.getLogger(__name__)


async def verify_sg_fixed_header(request: Request) -> None:
    """Validate SG sync requests by exact header-value matching.

    Uses the configured signature header name and shared secret value:
    - header name: ``settings.sso_sync.signature_header`` (default: ``X-Signature``)
    - fixed value: ``settings.sso_sync.gateway_hmac_secret``
    """
    expected = settings.sso_sync.gateway_hmac_secret
    if not expected:
        logger.error(
            'SG fixed-header auth failed: sso_sync.gateway_hmac_secret is '
            'not configured; rejecting request.'
        )
        raise SsoHmacInvalidError.http_exception('sg fixed header secret not configured')

    header_name = settings.sso_sync.signature_header or 'X-Signature'
    provided = (request.headers.get(header_name, '') or '').strip()
    if not provided:
        logger.warning(
            'SG fixed-header auth failed: missing %s header from %s on %s',
            header_name,
            getattr(request.client, 'host', '?'),
            request.url.path,
        )
        raise SsoHmacInvalidError.http_exception('missing sg fixed header')

    if provided != expected:
        logger.warning(
            'SG fixed-header auth failed: header mismatch from %s on %s',
            getattr(request.client, 'host', '?'),
            request.url.path,
        )
        raise SsoHmacInvalidError.http_exception('invalid sg fixed header')

