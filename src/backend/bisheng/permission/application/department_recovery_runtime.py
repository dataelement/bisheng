"""Same-environment composition for explicit F048 department operations."""

from __future__ import annotations

import argparse
import asyncio
import time
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.engine import make_url

from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import (
    get_current_tenant_id,
)
from bisheng.core.database import get_async_db_session
from bisheng.core.openfga.authorization_model_f048 import build_authorization_model_f048
from bisheng.core.openfga.client import FGAClient
from bisheng.core.openfga.discovery import discover_openfga_runtime
from bisheng.permission.application.department_recovery_fga import DepartmentRecoveryFGA, RecoveryRequestLimiter
from bisheng.permission.domain.models import PermissionProjectionOperation
from bisheng.permission.domain.repositories.catalog_repository import CatalogRepository
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.services.department_recovery_plan import (
    RecoveryBlockedError,
    RecoveryRuntimeError,
    checksum,
)


@contextmanager
def tenant_scope(identity):
    from bisheng.core.context.tenant import exact_tenant_filter

    with exact_tenant_filter(identity):
        yield


def database_fingerprint():
    url = make_url(settings.database_url)
    return checksum(
        {
            "driver": url.drivername,
            "host": url.host,
            "port": url.port,
            "database": url.database,
            "schema": url.query.get("schema"),
        }
    )


class DepartmentRecoveryRuntime:
    def __init__(self, environment_id, qps=2):
        self.environment_id = environment_id
        self.limiter = RecoveryRequestLimiter(qps)
        self.client = FGAClient(
            settings.openfga.api_url, "discovery", "discovery", timeout=min(settings.openfga.timeout, 5)
        )
        self.client._http.event_hooks["request"].append(self.limiter.on_request)
        self.pin = None
        self.catalog = CatalogRepository()
        self.projections = ProjectionRepository()
        self.fga = DepartmentRecoveryFGA(self.client, marker_window=settings.openfga.recent_consistency_window_seconds)
        self._session_context = ContextVar(f"department_recovery_session_{id(self)}", default=None)

    @property
    def session(self):
        return self._session_context.get()

    @session.setter
    def session(self, value):
        self._session_context.set(value)

    @asynccontextmanager
    async def execution_scope(self, payload):
        from bisheng.core.cache.redis_manager import get_redis_client
        from bisheng.core.lock.token_safe_redis_lock import TokenSafeRedisLock

        if not hasattr(self, "_lease_context"):
            self._lease_context = ContextVar(f"department_manual_lease_{id(self)}", default=None)
        if self._lease_context.get() is not None:
            if (
                self._lease_context.get().key
                != f"f048:department-projection:{payload['tenant_id']}:{payload['department_id']}"
            ):
                raise RecoveryRuntimeError("DEPARTMENT_EXECUTION_SCOPE_MISMATCH")
            await self.verify_execution()
            yield
            return
        redis = await get_redis_client()
        async with TokenSafeRedisLock(
            redis,
            f"f048:department-projection:{payload['tenant_id']}:{payload['department_id']}",
            ttl_seconds=60,
            renewal_interval_seconds=15,
        ) as lease:
            token = self._lease_context.set(lease)
            try:
                yield
            finally:
                self._lease_context.reset(token)

    async def verify_execution(self):
        context = getattr(self, "_lease_context", None)
        if context is None or context.get() is None:
            raise RecoveryRuntimeError("DEPARTMENT_EXECUTION_LEASE_REQUIRED")
        await context.get().verify_owned()

    async def discover(self):
        async with asyncio.timeout(5):
            return await discover_openfga_runtime(
                settings.openfga,
                expected_model=build_authorization_model_f048(),
                allow_bootstrap=False,
                http_client=self.client._http,
            )

    async def wait_for_request_slot(self):
        delay = self.limiter.last + self.limiter.interval - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)

    async def initialize(self):
        self.pin = await self.discover()
        self.client._store_id, self.client._model_id = self.pin.store_id, self.pin.model_id

    async def environment(self, *, lock=False, refresh=False):
        try:
            release = await self.catalog.aget_recovery_environment(lock=lock)
            pin = await self.discover() if refresh else self.pin
        except Exception as exc:
            raise RecoveryRuntimeError("RUNTIME_RELEASE_UNAVAILABLE") from exc
        if (self.client.store_id, self.client.model_id) != (pin.store_id, pin.model_id):
            raise RecoveryRuntimeError("RUNTIME_MODEL_PIN_CHANGED")
        if any(release[key] != asdict(pin)[key] for key in ("store_id", "model_id", "model_checksum")):
            raise RecoveryRuntimeError("RUNTIME_MODEL_PIN_CHANGED")
        return release | {
            "environment_id": self.environment_id,
            "database_fingerprint": database_fingerprint(),
            "fga_endpoint_checksum": checksum(settings.openfga.api_url),
        }

    async def load(self, identity, *, lock=False):
        department = await self.departments.get(identity, session=self.session, lock=lock)
        if department and department["tenant_id"] != get_current_tenant_id():
            raise RecoveryBlockedError("DEPARTMENT_OUTSIDE_SELECTED_TENANT")
        if not department or not department["operation_id"]:
            return department, None, []
        operation = await (
            self.projections.alock_recovery_operation(department["operation_id"])
            if lock
            else self.projections.aget_operation(department["operation_id"])
        )
        # Four rows are the only supported MOVE shape; a fifth proves invalidity.
        return department, operation, []

    async def database_time(self):
        return await self.projections.arecovery_database_time()

    async def topology(self, plan):
        return await self.fga.topology(plan)

    async def write(self, deltas):
        await self.fga.write(deltas)

    async def arm(self, plan):
        await self.fga.arm(plan)

    @asynccontextmanager
    async def transaction(self):
        if self.session is not None:
            raise RecoveryRuntimeError("RECOVERY_TRANSACTION_ALREADY_ACTIVE")
        async with get_async_db_session() as session:
            # SQLite omits row locks; never treat its unit tests as production locking proof.
            dialect = session.get_bind().dialect
            statement = select(PermissionProjectionOperation.id).with_for_update(nowait=True)
            if "NOWAIT" not in str(statement.compile(dialect=dialect)).upper():
                raise RecoveryRuntimeError("DIALECT_NOWAIT_UNSUPPORTED")
            async with session.begin():
                async with AsyncExitStack() as stack:
                    await stack.enter_async_context(self.catalog.bind_session(session))
                    await stack.enter_async_context(self.projections.bind_session(session))
                    self.session = session
                    try:
                        yield
                    finally:
                        self.session = None


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def abnormal_department(row, metadata):
    if row["state"] != "CURRENT":
        return True
    if row["operation_id"] is None:
        return row["version"] != 0
    operation = metadata.get(row["operation_id"])
    return not operation or (
        operation["scope_type"] != "department"
        or operation["scope_key"] != str(row["id"])
        or operation["tenant_id"] != row["tenant_id"]
        or operation["status"] != "FINALIZED"
        or operation["target_version"] != row["version"]
    )
