"""CLI-only CURRENT-pin recovery composition; no business runtime admission.

Does not publish a model, bootstrap storage, or expose permission checks. The
operation ledger and native scope guard remain the only recovery authority.
"""

from contextlib import AsyncExitStack
from types import SimpleNamespace

_owned = None
_client = None
_pin = None


async def initialize_maintenance_context(*, config):
    global _owned, _client, _pin
    from bisheng.core.cache.redis_manager import RedisManager
    from bisheng.core.context.manager import app_context
    from bisheng.core.database import get_async_db_session
    from bisheng.core.database.manager import DatabaseManager
    from bisheng.core.openfga.client import FGAClient
    from bisheng.core.openfga.discovery import discover_openfga_runtime
    from scripts.prepare_f118_history import blocked, global_session, read_pin, unfrozen

    if _owned is not None:
        blocked("maintenance_context_already_owned")
    stack = AsyncExitStack()
    try:
        if (
            not config.openfga.enabled
            or config.openfga.force_write_model
            or config.openfga.dual_model_mode
            or config.openfga.legacy_model_id
        ):
            blocked("read_pinned_fga_configuration_required")
        database = DatabaseManager(
            database_url=config.database_url, engine_config=config.database_pool.as_engine_kwargs()
        )
        app_context.register_context(database)
        stack.push_async_callback(database.async_close)
        await app_context.async_get_instance(DatabaseManager.name)
        async with global_session(get_async_db_session) as session:
            await unfrozen(session)
            pin = await read_pin(session)
        actual = await discover_openfga_runtime(
            config.openfga,
            expected_model=None,
            allow_bootstrap=False,
            required_store_id=pin["store_id"],
            required_model_id=pin["model_id"],
        )
        if actual.model_checksum != pin["model_checksum"]:
            blocked("physical_pin_changed")
        client = FGAClient(
            api_url=config.openfga.api_url,
            store_id=pin["store_id"],
            model_id=pin["model_id"],
            timeout=config.openfga.timeout,
        )
        stack.push_async_callback(client.close)
        redis = RedisManager(redis_url=config.redis_url)
        app_context.register_context(redis)
        stack.push_async_callback(redis.async_close)
        await app_context.async_get_instance(RedisManager.name)
        _owned, _client, _pin = stack, client, pin
    except BaseException:
        await stack.aclose()
        raise


async def close_maintenance_context():
    global _owned, _client, _pin
    stack, _owned = _owned, None
    _client, _pin = None, None
    if stack is not None:
        await stack.aclose()


async def maintenance_client():
    from bisheng.core.database import get_async_db_session
    from scripts.prepare_f118_history import blocked, global_session, read_pin, unfrozen

    if _client is None:
        blocked("maintenance_context_missing")
    async with global_session(get_async_db_session) as session:
        await unfrozen(session)
        if await read_pin(session) != _pin:
            blocked("catalog_pin_changed")
    return _client


class _PinnedPort:
    def __init__(self, port):
        self.port = port

    def __getattr__(self, name):
        async def call(*args, **kwargs):
            await maintenance_client()
            return await getattr(self.port, name)(*args, **kwargs)

        return call


async def build_maintenance_projection(client, *, external_scopes=None):
    from bisheng.permission.application.sql_runtime import build_sql_projection_runtime
    from bisheng.permission.domain.services.projection_service import ProjectionService

    if client is not await maintenance_client():
        raise RuntimeError("Maintenance client pin changed")
    ports = await build_sql_projection_runtime(client, external_scopes=external_scopes)
    return SimpleNamespace(
        projection=ProjectionService(
            repository=ports.repository,
            marker=ports.marker,
            fga=_PinnedPort(ports.fga),
            scope_guard=_PinnedPort(ports.scope_guard),
            finalizer=_PinnedPort(ports.finalizer),
        )
    )
