"""FGAManager — BaseContextManager for OpenFGA lifecycle.

Handles store creation, authorization model initialization, and FGAClient lifecycle.
Registered in ApplicationContextManager when openfga.enabled=True.
"""

from __future__ import annotations

import logging
from typing import Optional

from bisheng.core.config.openfga import OpenFGAConf
from bisheng.core.context.base import BaseContextManager
from bisheng.core.openfga.client import FGAClient

logger = logging.getLogger(__name__)


class FGAManager(BaseContextManager[FGAClient]):
    """Manages FGAClient lifecycle within the application context."""

    name = 'openfga'

    def __init__(self, openfga_config: OpenFGAConf):
        super().__init__()
        self._config = openfga_config

    async def _async_initialize(self) -> FGAClient:
        """Create FGAClient, auto-create store and write authorization model."""
        import httpx
        from bisheng.core.openfga.authorization_model import get_authorization_model

        config = self._config
        api_url = config.api_url

        # Temporary client without store_id for bootstrap
        temp_http = httpx.AsyncClient(base_url=api_url, timeout=httpx.Timeout(config.timeout))

        try:
            # 1. Resolve store_id
            store_id = config.store_id
            if not store_id:
                # Search for existing store by name
                resp = await temp_http.get('/stores')
                resp.raise_for_status()
                stores = resp.json().get('stores', [])
                for s in stores:
                    if s.get('name') == config.store_name:
                        store_id = s['id']
                        logger.info('Found existing OpenFGA store: %s (%s)', config.store_name, store_id)
                        break

                if not store_id:
                    # Create new store
                    resp = await temp_http.post('/stores', json={'name': config.store_name})
                    resp.raise_for_status()
                    store_id = resp.json()['id']
                    logger.info('Created OpenFGA store: %s (%s)', config.store_name, store_id)

            # 2. Resolve model_id
            model_id = config.model_id
            if not model_id:
                # Always write the latest model (idempotent — OpenFGA creates new version)
                model = get_authorization_model()
                resp = await temp_http.post(
                    f'/stores/{store_id}/authorization-models', json=model
                )
                resp.raise_for_status()
                model_id = resp.json().get('authorization_model_id', '')
                logger.info('Wrote OpenFGA authorization model: %s', model_id)

        finally:
            await temp_http.aclose()

        # 3. Build production client with resolved store_id and model_id
        client = FGAClient(
            api_url=api_url,
            store_id=store_id,
            model_id=model_id,
            timeout=config.timeout,
        )
        logger.info('FGAClient initialized: store=%s model=%s', store_id, model_id)
        return client

    def _sync_initialize(self) -> FGAClient:
        raise TypeError('FGAManager only supports async initialization')

    async def _async_cleanup(self) -> None:
        instance = self._instance
        if instance:
            await instance.close()
            logger.info('FGAClient closed')

    def _sync_cleanup(self) -> None:
        pass

    async def health_check(self) -> bool:
        try:
            instance = self._instance
            if instance:
                return await instance.health()
            return False
        except Exception:
            return False


# ── Convenience accessor ─────────────────────────────────────────

_fga_client: Optional[FGAClient] = None


def get_fga_client() -> Optional[FGAClient]:
    """Get the FGAClient instance from app context.

    Returns None if OpenFGA is not enabled or not initialized.
    """
    global _fga_client
    if _fga_client is not None:
        return _fga_client

    try:
        from bisheng.core.context.manager import app_context
        ctx = app_context.get_context('openfga')
        _fga_client = ctx.sync_get_instance()
        return _fga_client
    except (KeyError, Exception):
        return None


async def aget_fga_client() -> Optional[FGAClient]:
    """Async version of get_fga_client."""
    global _fga_client
    if _fga_client is not None:
        return _fga_client

    try:
        from bisheng.core.context.manager import app_context
        instance = await app_context.async_get_instance('openfga')
        _fga_client = instance
        return _fga_client
    except (KeyError, Exception):
        return None
