#!/usr/bin/env python3
"""Formal install command. Reuses actual schema/model/catalog state, no total marker.

Run from src/backend. Production model writes are confined to this operational
entry point, never enabled in the API/worker runtime.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def permission_ready():
    from sqlmodel import select

    from bisheng.common.services.config_service import settings
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.core.openfga.authorization_model_f048 import get_authorization_model_f048
    from bisheng.core.openfga.discovery import discover_openfga_runtime
    from bisheng.permission.domain.models import AuthorizationModelRelease, PermissionCatalogRelease

    pin = await discover_openfga_runtime(
        settings.openfga, expected_model=get_authorization_model_f048(), allow_bootstrap=False
    )
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            rows = list(
                (
                    await session.exec(
                        select(PermissionCatalogRelease).where(PermissionCatalogRelease.status == "CURRENT")
                    )
                ).all()
            )
            if len(rows) != 1:
                return False
            model = await session.get(AuthorizationModelRelease, rows[0].required_authorization_model_release_id)
            return bool(
                model
                and model.status == "ACTIVE"
                and (model.store_id, model.model_id, model.model_checksum)
                == (pin.store_id, pin.model_id, pin.model_checksum)
            )


async def schema_ready():
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory

    from bisheng.core.database import get_database_connection

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "bisheng/core/database/alembic"))
    expected = set(ScriptDirectory.from_config(cfg).get_heads())
    manager = await get_database_connection()
    async with manager.async_engine.connect() as connection:
        actual = await connection.run_sync(lambda conn: set(MigrationContext.configure(conn).get_current_heads()))
    return bool(expected and actual == expected)


async def initialize_permissions(*, allow_create):
    import httpx
    from sqlmodel import select

    from bisheng.common.services.config_service import settings
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.core.openfga.authorization_model_f048 import get_authorization_model_f048
    from bisheng.core.openfga.client import FGAClient
    from bisheng.core.openfga.discovery import discover_openfga_runtime
    from bisheng.permission.application.catalog_bootstrap import seed_initial_permission_catalog
    from bisheng.permission.domain.models import PermissionCatalogRelease

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            current = list(
                (
                    await session.exec(
                        select(PermissionCatalogRelease).where(PermissionCatalogRelease.status == "CURRENT")
                    )
                ).all()
            )
    if current:
        if not await permission_ready():
            raise RuntimeError("Existing authorization state needs the explicit permission upgrade tool")
        return
    # Reuse discovery for unique Store resolution. Before any write, refuse an
    # unclaimed Store containing tuples; it is not a fresh platform install.
    async with httpx.AsyncClient(
        base_url=settings.openfga.api_url, timeout=settings.openfga.timeout, follow_redirects=False, trust_env=False
    ) as client:
        response = await client.get("/stores", params={"name": settings.openfga.store_name, "page_size": 2})
        response.raise_for_status()
        stores = [row for row in response.json().get("stores", []) if row.get("name") == settings.openfga.store_name]
        if len(stores) > 1:
            raise RuntimeError("OpenFGA Store name is ambiguous")
        if stores:
            response = await client.post(f"/stores/{stores[0]['id']}/read", json={"page_size": 1})
            response.raise_for_status()
            if response.json().get("tuples"):
                raise RuntimeError("Nonempty OpenFGA Store has no matching SQL ownership")
    config = settings.openfga.model_copy(update={"force_write_model": False})
    pin = await discover_openfga_runtime(
        config, expected_model=get_authorization_model_f048(), allow_bootstrap=allow_create
    )
    client = FGAClient(api_url=config.api_url, store_id=pin.store_id, model_id=pin.model_id, timeout=config.timeout)
    await seed_initial_permission_catalog(
        client,
        store_id=pin.store_id,
        model_id=pin.model_id,
        model_checksum=pin.model_checksum,
        environment=settings.environment,
    )
    if not await permission_ready():
        raise RuntimeError("Permission initialization did not produce a matching CURRENT Catalog")


async def ready(*, runtime, catalog):
    if not await schema_ready() or not await permission_ready():
        return False
    if runtime:
        from bisheng.app_runtime.domain.services.system_profile_service import official_catalog_ready

        return await official_catalog_ready(catalog)
    return True


async def wait_ready(*, runtime, catalog, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if await ready(runtime=runtime, catalog=catalog):
                return
        except Exception as error:
            # Connection/SQL content may contain credentials; the operator has
            # the initializer logs, this waiter only reports its finite timeout.
            logger.warning("Initialization readiness pending ({})", type(error).__name__)
        await asyncio.sleep(min(2, max(0, deadline - time.monotonic())))
    raise RuntimeError("Timed out waiting for actual database/authorization/catalog initialization")


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--catalog", default="/run/official-runtime-catalog")
    parser.add_argument("--allow-openfga-bootstrap", action="store_true")
    parser.add_argument("--timeout", type=int, default=600)
    return parser.parse_args()


def main():
    import subprocess

    args = arguments()

    async def initialize():
        import httpx

        from bisheng.common.services.config_service import settings
        from bisheng.core.database import get_database_connection

        if not 1 <= args.timeout <= 3600:
            raise ValueError("Initialization timeout must be between 1 and 3600 seconds")
        deadline = time.monotonic() + args.timeout
        manager = await get_database_connection()
        while True:
            try:
                async with manager.async_engine.connect():
                    pass
                break
            except Exception as error:
                logger.warning("Platform database readiness pending ({})", type(error).__name__)
                if time.monotonic() >= deadline:
                    raise RuntimeError("Configured platform database did not become available") from None
                await asyncio.sleep(2)
        await asyncio.to_thread(
            subprocess.run, [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True
        )
        async with httpx.AsyncClient(
            base_url=settings.openfga.api_url, timeout=3, follow_redirects=False, trust_env=False
        ) as client:
            while True:
                try:
                    response = await client.get("/stores", params={"page_size": 1})
                    response.raise_for_status()
                    break
                except httpx.HTTPError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Configured OpenFGA service did not become available") from None
                    await asyncio.sleep(2)
        await initialize_permissions(allow_create=args.allow_openfga_bootstrap)
        if args.runtime:
            from bisheng.app_runtime.domain.services.system_profile_service import seed_official_catalog

            await seed_official_catalog(args.catalog)

    asyncio.run(initialize())
    print("Platform schema and enabled initialization completed")


if __name__ == "__main__":
    main()
