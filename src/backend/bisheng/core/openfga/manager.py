"""Single-model OpenFGA lifecycle, pin validation, and readiness."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx

from bisheng.common.errcode.permission import AuthorizationModelMismatchError
from bisheng.core.config.openfga import OpenFGAConf
from bisheng.core.context.base import BaseContextManager
from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
    build_authorization_model_f048,
)
from bisheng.core.openfga.client import FGAClient
from bisheng.core.openfga.runtime_heartbeat import (
    RedisRuntimeHeartbeatStore,
    RuntimeHeartbeatStorePort,
)

logger = logging.getLogger(__name__)


class FGAManager(BaseContextManager[FGAClient]):
    """Manage one explicitly pinned OpenFGA Store/model runtime."""

    name = "openfga"

    def __init__(
        self,
        openfga_config: OpenFGAConf,
        *,
        environment: str | dict[str, Any] | None = None,
        instance_role: str = "api",
        heartbeat_store: RuntimeHeartbeatStorePort | None = None,
    ) -> None:
        super().__init__()
        self._config = openfga_config
        self._environment = environment
        self._instance_role = instance_role
        self._heartbeat_store = (
            heartbeat_store or RedisRuntimeHeartbeatStore()
        )
        self._instance_id = uuid4().hex
        self._started_at = datetime.now(UTC)
        self._last_heartbeat_at: datetime | None = None
        self._ready = False
        self._readiness_error: str | None = "not_initialized"
        self._runtime_store_id: str | None = None
        self._runtime_model_id: str | None = None
        self._runtime_model_checksum: str | None = None
        self._runtime_catalog_release_id: int | None = None
        self._runtime_catalog_checksum: str | None = None
        self._catalog_resolver: Callable[[], Awaitable[Any]] | None = None

    async def _async_initialize(self) -> FGAClient:
        config = self._config
        if config.dual_model_mode or config.legacy_model_id:
            raise ValueError("OpenFGA runtime does not support legacy or dual-model clients")

        expected_model = build_authorization_model_f048()
        expected_checksum = authorization_model_checksum(expected_model)
        production = self._is_production()
        if production:
            config.validate_production_runtime_pin()
            if config.model_checksum != expected_checksum:
                raise AuthorizationModelMismatchError(
                    msg="Configured model checksum does not match the F048 runtime model"
                )
            remote_model = await self._fetch_authorization_model(
                config.store_id,
                config.model_id,
            )
            remote_checksum = authorization_model_checksum(remote_model)
            if remote_checksum != config.model_checksum:
                raise AuthorizationModelMismatchError(
                    msg="Pinned OpenFGA model checksum does not match the release"
                )
            store_id = config.store_id
            model_id = config.model_id
            runtime_checksum = remote_checksum
        else:
            store_id, model_id, runtime_checksum = await self._resolve_development_pins(
                expected_model,
                expected_checksum,
            )

        client = FGAClient(
            api_url=config.api_url,
            store_id=store_id,
            model_id=model_id,
            timeout=config.timeout,
        )
        self._runtime_store_id = store_id
        self._runtime_model_id = model_id
        self._runtime_model_checksum = runtime_checksum
        self._ready = True
        self._readiness_error = None
        logger.info(
            "FGAClient initialized with explicit runtime pin: store=%s model=%s role=%s",
            store_id,
            model_id,
            self._instance_role,
        )
        return client

    async def _fetch_authorization_model(
        self,
        store_id: str,
        model_id: str,
    ) -> dict:
        config = self._config
        try:
            async with httpx.AsyncClient(
                base_url=config.api_url,
                timeout=httpx.Timeout(config.timeout),
            ) as client:
                response = await client.get(
                    f"/stores/{store_id}/authorization-models/{model_id}"
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise AuthorizationModelMismatchError(
                exception=exc,
                msg="Unable to load the pinned OpenFGA authorization model",
            ) from exc
        return self._normalize_remote_model(payload)

    @staticmethod
    def _normalize_remote_model(payload: dict) -> dict:
        raw_model = payload.get("authorization_model", payload)
        model = {
            "schema_version": raw_model.get("schema_version"),
            "type_definitions": raw_model.get("type_definitions"),
        }
        if raw_model.get("conditions"):
            model["conditions"] = raw_model["conditions"]
        if not model["schema_version"] or not isinstance(
            model["type_definitions"],
            list,
        ):
            raise AuthorizationModelMismatchError(
                msg="Pinned OpenFGA authorization model payload is incomplete"
            )
        return model

    async def _resolve_development_pins(
        self,
        expected_model: dict,
        expected_checksum: str,
    ) -> tuple[str, str, str]:
        """Bootstrap an isolated development runtime without selecting latest."""

        config = self._config
        store_id = config.store_id
        model_id = config.model_id
        async with httpx.AsyncClient(
            base_url=config.api_url,
            timeout=httpx.Timeout(config.timeout),
        ) as client:
            if not store_id:
                response = await client.post(
                    "/stores",
                    json={"name": config.store_name},
                )
                response.raise_for_status()
                store_id = response.json().get("id", "")
                if not store_id:
                    raise AuthorizationModelMismatchError(
                        msg="Development OpenFGA store creation returned no ID"
                    )
            if not model_id or config.force_write_model:
                response = await client.post(
                    f"/stores/{store_id}/authorization-models",
                    json=expected_model,
                )
                response.raise_for_status()
                model_id = response.json().get("authorization_model_id", "")
                if not model_id:
                    raise AuthorizationModelMismatchError(
                        msg="Development OpenFGA model creation returned no ID"
                    )
            elif config.model_checksum and config.model_checksum != expected_checksum:
                raise AuthorizationModelMismatchError(
                    msg="Configured development model checksum does not match F048"
                )
        return store_id, model_id, expected_checksum

    def _is_production(self) -> bool:
        environment = self._environment
        if environment is None:
            try:
                from bisheng.common.services.config_service import settings

                environment = settings.environment
            except Exception:
                environment = "dev"
        if isinstance(environment, dict):
            environment = next(
                (
                    environment[key]
                    for key in ("name", "environment", "env", "mode")
                    if environment.get(key)
                ),
                "dev",
            )
        normalized = str(environment).strip().casefold()
        return normalized in {"prod", "production"} or normalized.startswith(
            "production-"
        )

    def readiness(self) -> dict[str, Any]:
        """Return process-local pin and heartbeat evidence."""

        config = self._config
        return {
            "ready": self._ready,
            "error": self._readiness_error,
            "store_id": self._runtime_store_id or config.store_id,
            "model_id": self._runtime_model_id or config.model_id,
            "model_checksum": self._runtime_model_checksum
            or config.model_checksum,
            "catalog_release_id": self._runtime_catalog_release_id
            or config.current_catalog_release_id,
            "catalog_checksum": self._runtime_catalog_checksum
            or config.current_catalog_checksum,
            "consistency_window_seconds": (
                config.recent_consistency_window_seconds
            ),
            "instance_id": self._instance_id,
            "instance_role": self._instance_role,
            "started_at": self._started_at.isoformat(),
            "last_heartbeat_at": (
                self._last_heartbeat_at.isoformat()
                if self._last_heartbeat_at
                else None
            ),
        }

    async def bind_catalog_runtime(
        self,
        resolver: Callable[[], Awaitable[Any]],
        *,
        require_config_match: bool = False,
    ) -> None:
        """Bind the SQL CURRENT Catalog used by this process.

        Startup performs a one-time comparison with the deployment pin. Later
        heartbeats refresh the CURRENT release dynamically so an online Catalog
        publish is reflected by every process without constructing a second
        OpenFGA client.
        """

        self._catalog_resolver = resolver
        try:
            await self._refresh_catalog_runtime(
                require_config_match=require_config_match,
            )
        except Exception:
            self._catalog_resolver = None
            raise

    async def _refresh_catalog_runtime(
        self,
        *,
        require_config_match: bool = False,
    ) -> None:
        resolver = self._catalog_resolver
        if resolver is None:
            return
        catalog = await resolver()
        release_id = getattr(catalog, "release_id", None)
        checksum = getattr(catalog, "checksum", None)
        store_id = getattr(catalog, "store_id", None)
        model_id = getattr(catalog, "model_id", None)
        model_checksum = getattr(catalog, "model_checksum", None)
        if (
            not isinstance(release_id, int)
            or release_id <= 0
            or not isinstance(checksum, str)
            or not checksum
        ):
            raise AuthorizationModelMismatchError(
                msg="CURRENT Catalog runtime pin is incomplete"
            )
        if (
            store_id != self._runtime_store_id
            or model_id != self._runtime_model_id
            or model_checksum != self._runtime_model_checksum
        ):
            raise AuthorizationModelMismatchError(
                msg="CURRENT Catalog does not match the OpenFGA runtime pin"
            )
        if require_config_match and (
            release_id != self._config.current_catalog_release_id
            or checksum != self._config.current_catalog_checksum
        ):
            raise AuthorizationModelMismatchError(
                msg="CURRENT Catalog does not match the startup configuration"
            )
        self._runtime_catalog_release_id = release_id
        self._runtime_catalog_checksum = checksum

    async def heartbeat(self) -> bool:
        instance = self._instance
        if instance is None:
            self._ready = False
            self._readiness_error = "client_not_initialized"
            return False
        try:
            await self._refresh_catalog_runtime()
        except Exception as exc:
            self._ready = False
            self._readiness_error = "catalog_pin_mismatch"
            logger.error("F048 Catalog heartbeat refresh failed: %s", exc)
            await self._remove_heartbeat()
            return False
        try:
            healthy = await instance.health()
        except Exception as exc:
            logger.warning("OpenFGA heartbeat failed: %s", exc)
            healthy = False
        self._last_heartbeat_at = datetime.now(UTC)
        self._ready = healthy
        self._readiness_error = None if healthy else "openfga_unhealthy"
        if not healthy:
            await self._remove_heartbeat()
            return False
        try:
            await self._heartbeat_store.publish(
                role=self._instance_role,
                instance_id=self._instance_id,
                payload=self._heartbeat_payload(),
            )
        except Exception as exc:
            self._ready = False
            self._readiness_error = "heartbeat_store_unavailable"
            logger.error(
                "F048 runtime heartbeat publish failed: role=%s error=%s",
                self._instance_role,
                exc,
            )
            return False
        return True

    def _heartbeat_payload(self) -> dict[str, Any]:
        readiness = self.readiness()
        return {
            "ready": readiness["ready"],
            "store_id": readiness["store_id"],
            "model_id": readiness["model_id"],
            "model_checksum": readiness["model_checksum"],
            "catalog_release_id": readiness["catalog_release_id"],
            "catalog_checksum": readiness["catalog_checksum"],
            "dual_model_mode": self._config.dual_model_mode,
            "legacy_model_id": self._config.legacy_model_id,
        }

    async def _remove_heartbeat(self) -> None:
        try:
            await self._heartbeat_store.remove(
                role=self._instance_role,
                instance_id=self._instance_id,
            )
        except Exception as exc:
            logger.warning(
                "F048 runtime heartbeat cleanup failed: role=%s error=%s",
                self._instance_role,
                exc,
            )

    def _sync_initialize(self) -> FGAClient:
        raise TypeError("FGAManager only supports async initialization")

    async def _async_cleanup(self) -> None:
        global _fga_client
        instance = self._instance
        if instance:
            await instance.close()
        await self._remove_heartbeat()
        _fga_client = None
        self._runtime_store_id = None
        self._runtime_model_id = None
        self._runtime_model_checksum = None
        self._runtime_catalog_release_id = None
        self._runtime_catalog_checksum = None
        self._catalog_resolver = None
        self._ready = False
        self._readiness_error = "closed"
        logger.info("FGAClient closed")

    def _sync_cleanup(self) -> None:
        return None

    async def health_check(self) -> bool:
        return await self.heartbeat()


_fga_client: FGAClient | None = None


def get_fga_client() -> FGAClient | None:
    """Get the initialized process-local FGA client."""

    global _fga_client
    if _fga_client is not None:
        return _fga_client
    try:
        from bisheng.core.context.manager import app_context

        context = app_context.get_context("openfga")
        _fga_client = context.sync_get_instance()
        return _fga_client
    except Exception:
        return None


async def aget_fga_client() -> FGAClient | None:
    """Async version of :func:`get_fga_client`."""

    global _fga_client
    if _fga_client is not None:
        return _fga_client
    try:
        from bisheng.core.context.manager import app_context

        _fga_client = await app_context.async_get_instance("openfga")
        return _fga_client
    except Exception:
        return None
