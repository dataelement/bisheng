"""Single-model OpenFGA lifecycle, discovery validation, and readiness."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from bisheng.common.errcode.permission import AuthorizationModelMismatchError
from bisheng.core.config.openfga import OpenFGAConf
from bisheng.core.context.base import BaseContextManager
from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
    build_authorization_model_f048,
)
from bisheng.core.openfga.client import FGAClient
from bisheng.core.openfga.discovery import discover_openfga_runtime
from bisheng.core.openfga.runtime_heartbeat import (
    RedisRuntimeHeartbeatStore,
    RuntimeHeartbeatStorePort,
)

logger = logging.getLogger(__name__)


class FGAManager(BaseContextManager[FGAClient]):
    """Discover and manage one concrete OpenFGA Store/model runtime."""

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
        self._heartbeat_store = heartbeat_store or RedisRuntimeHeartbeatStore()
        self._instance_id = uuid4().hex
        self._started_at = datetime.now(UTC)
        self._last_heartbeat_at: datetime | None = None
        self._ready = False
        self._readiness_error: str | None = "not_initialized"
        self._runtime_store_id: str | None = None
        self._runtime_model_id: str | None = None
        self._runtime_model_checksum: str | None = None
        self._expected_model_checksum: str | None = None
        self._migration_required = False
        self._migration_reason: str | None = None
        self._runtime_catalog_release_id: int | None = None
        self._runtime_catalog_checksum: str | None = None
        self._catalog_resolver: Callable[[], Awaitable[Any]] | None = None

    async def _async_initialize(self) -> FGAClient:
        config = self._config
        if config.dual_model_mode or config.legacy_model_id:
            raise ValueError("OpenFGA runtime does not support legacy or dual-model clients")

        expected_model = build_authorization_model_f048()
        expected_model_checksum = authorization_model_checksum(expected_model)
        production = self._is_production()
        if production:
            config.validate_production_runtime()
        if not production and config.force_write_model:
            pin = await discover_openfga_runtime(
                config,
                expected_model=expected_model,
                allow_bootstrap=True,
            )
        else:
            try:
                pin = await discover_openfga_runtime(
                    config,
                    expected_model=None,
                    allow_bootstrap=False,
                )
            except AuthorizationModelMismatchError:
                if production:
                    raise
                pin = await discover_openfga_runtime(
                    config,
                    expected_model=expected_model,
                    allow_bootstrap=True,
                )

        client = FGAClient(
            api_url=config.api_url,
            store_id=pin.store_id,
            model_id=pin.model_id,
            timeout=config.timeout,
        )
        self._runtime_store_id = pin.store_id
        self._runtime_model_id = pin.model_id
        self._runtime_model_checksum = pin.model_checksum
        self._expected_model_checksum = expected_model_checksum
        self._migration_required = pin.model_checksum != expected_model_checksum
        self._migration_reason = "authorization_model_migration_required" if self._migration_required else None
        self._ready = not self._migration_required
        self._readiness_error = self._migration_reason
        if self._migration_required:
            logger.warning(
                "OpenFGA predecessor model discovered; API/worker may start for "
                "operator migration but permission runtime remains unavailable: "
                "store=%s source_model=%s role=%s",
                pin.store_id,
                pin.model_id,
                self._instance_role,
            )
            return client
        logger.info(
            "FGAClient initialized from discovered runtime: store=%s model=%s role=%s",
            pin.store_id,
            pin.model_id,
            self._instance_role,
        )
        return client

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
                (environment[key] for key in ("name", "environment", "env", "mode") if environment.get(key)),
                "dev",
            )
        normalized = str(environment).strip().casefold()
        return normalized in {"prod", "production"} or normalized.startswith("production-")

    def readiness(self) -> dict[str, Any]:
        """Return process-local pin and heartbeat evidence."""

        return {
            "ready": self._ready,
            "error": self._readiness_error,
            "store_id": self._runtime_store_id,
            "model_id": self._runtime_model_id,
            "model_checksum": self._runtime_model_checksum,
            "expected_model_checksum": self._expected_model_checksum,
            "migration_required": self._migration_required,
            "catalog_release_id": self._runtime_catalog_release_id,
            "catalog_checksum": self._runtime_catalog_checksum,
            "consistency_window_seconds": (self._config.recent_consistency_window_seconds),
            "instance_id": self._instance_id,
            "instance_role": self._instance_role,
            "started_at": self._started_at.isoformat(),
            "last_heartbeat_at": (self._last_heartbeat_at.isoformat() if self._last_heartbeat_at else None),
        }

    async def mark_migration_required(
        self,
        *,
        reason: str = "permission_data_migration_required",
    ) -> None:
        """Keep the process alive but unavailable for an explicit data migration."""

        self._migration_required = True
        self._migration_reason = reason
        self._ready = False
        self._readiness_error = reason
        self._catalog_resolver = None
        self._runtime_catalog_release_id = None
        self._runtime_catalog_checksum = None
        await self._remove_heartbeat()

    async def bind_catalog_runtime(
        self,
        resolver: Callable[[], Awaitable[Any]],
    ) -> None:
        """Bind the SQL CURRENT Catalog used by this process.

        Startup performs a one-time comparison with the deployment pin. Later
        heartbeats refresh the CURRENT release dynamically so an online Catalog
        publish is reflected by every process without constructing a second
        OpenFGA client.
        """

        if self._migration_required:
            raise AuthorizationModelMismatchError(
                msg="F048 data migration must complete before binding the CURRENT Catalog"
            )
        self._catalog_resolver = resolver
        try:
            await self._refresh_catalog_runtime()
        except Exception:
            self._catalog_resolver = None
            raise

    async def _refresh_catalog_runtime(self) -> None:
        resolver = self._catalog_resolver
        if resolver is None:
            return
        catalog = await resolver()
        release_id = getattr(catalog, "release_id", None)
        checksum = getattr(catalog, "checksum", None)
        store_id = getattr(catalog, "store_id", None)
        model_id = getattr(catalog, "model_id", None)
        model_checksum = getattr(catalog, "model_checksum", None)
        if not isinstance(release_id, int) or release_id <= 0 or not isinstance(checksum, str) or not checksum:
            raise AuthorizationModelMismatchError(msg="CURRENT Catalog runtime pin is incomplete")
        if (
            store_id != self._runtime_store_id
            or model_id != self._runtime_model_id
            or model_checksum != self._runtime_model_checksum
        ):
            raise AuthorizationModelMismatchError(msg="CURRENT Catalog does not match the OpenFGA runtime pin")
        self._runtime_catalog_release_id = release_id
        self._runtime_catalog_checksum = checksum

    async def heartbeat(self) -> bool:
        instance = self._instance
        if instance is None:
            self._ready = False
            self._readiness_error = "client_not_initialized"
            return False
        if self._migration_required:
            self._ready = False
            self._readiness_error = self._migration_reason or "authorization_model_migration_required"
            await self._remove_heartbeat()
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
        self._expected_model_checksum = None
        self._migration_required = False
        self._migration_reason = None
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
    """Return the client only after the permission runtime is READY.

    Synchronous callers never initialize OpenFGA independently. Async callers
    must use :func:`aget_fga_client` to trigger the lazy permission runtime.
    """

    global _fga_client
    try:
        from bisheng.core.context.manager import app_context

        permission_context = app_context.get_context("permission_runtime")
        if not permission_context.is_ready():
            return None
        if _fga_client is not None:
            return _fga_client
        context = app_context.get_context("openfga")
        _fga_client = context.sync_get_instance()
        return _fga_client
    except Exception:
        return None


async def aget_fga_client() -> FGAClient | None:
    """Initialize the permission runtime and return its OpenFGA client."""

    global _fga_client
    try:
        from bisheng.core.context.manager import app_context
        from bisheng.permission.application.process_runtime import get_f048_process_runtime

        await get_f048_process_runtime()
        if _fga_client is not None:
            return _fga_client
        _fga_client = await app_context.async_get_instance("openfga")
        return _fga_client
    except Exception:
        return None
