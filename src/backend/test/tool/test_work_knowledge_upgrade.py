"""Exercise the complete upgrade with real catalog SQL and the F048 reconciler."""

import os
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.api.services import f048_system_resource_bootstrap as inventory_module
from bisheng.permission.application import system_resource_reconcile as permission_module
from bisheng.permission.application.system_resource_reconcile import SystemOwnedResourceState
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType
from scripts import register_work_knowledge_tool as upgrade


@pytest.fixture
async def environment(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'catalog.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(GptsToolsType.__table__.create)
        await connection.run_sync(GptsTools.__table__.create)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    state = SimpleNamespace(projections={}, fail=False, sessions=sessions)

    async def inspect(resources):
        return tuple(
            SystemOwnedResourceState(
                resource=item,
                state=state.projections.get(item.resource_id, "MISSING"),
            )
            for item in resources
        )

    async def authorize(**kwargs):
        if state.fail:
            raise RuntimeError("Synthetic permission service outage")
        state.projections[kwargs["target"].resource_id] = "CURRENT"

    state.facade = SimpleNamespace(authorize_system_owned=AsyncMock(side_effect=authorize))
    state.marker = SimpleNamespace(wait_until_ready=AsyncMock())
    state.close = AsyncMock()
    monkeypatch.setattr(upgrade, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(upgrade, "close_app_context", state.close)
    monkeypatch.setattr(
        upgrade, "settings", SimpleNamespace(openfga=SimpleNamespace(recent_consistency_window_seconds=1))
    )
    client = SimpleNamespace(store_id="fixture-store", model_id="fixture-model")
    manager = SimpleNamespace(async_get_instance=AsyncMock(return_value=client))
    monkeypatch.setattr(upgrade, "app_context", SimpleNamespace(get_context=lambda name: manager))
    monkeypatch.setattr(upgrade, "build_f048_permission_runtime", AsyncMock(return_value=state))
    monkeypatch.setattr(upgrade, "get_async_db_session", sessions)
    monkeypatch.setattr(inventory_module, "get_async_db_session", sessions)
    monkeypatch.setattr(permission_module, "inspect_system_owned_resources", inspect)
    yield state
    await engine.dispose()


async def catalog_rows(environment):
    with upgrade.bypass_tenant_filter():
        async with environment.sessions() as session:
            return (await session.exec(select(GptsTools))).all(), (await session.exec(select(GptsToolsType))).all()


async def apply_upgrade():
    return await upgrade.run(apply=True, confirm_store_id="fixture-store", operator_id=27)


async def test_preview_reports_missing_catalog_without_writes(environment):
    result = await upgrade.run(apply=False)
    assert result["store_id"] == "fixture-store"
    assert result["ready"] is False
    assert result["catalog"]["create_tool"] is True
    assert await catalog_rows(environment) == ([], [])
    environment.facade.authorize_system_owned.assert_not_awaited()
    environment.close.assert_awaited_once()


async def test_apply_registers_and_projects_once_across_repeated_upgrades(environment):
    result = await apply_upgrade()
    assert result["ready"] is True
    assert result["permission"]["after"][0]["state"] == "CURRENT"
    again = await apply_upgrade()
    assert again["ready"] is True
    assert again["catalog"]["status"] == "current"
    tools, categories = await catalog_rows(environment)
    assert len(tools) == len(categories) == 1
    assert tools[0].tool_key == upgrade.TOOL_KEY
    assert tools[0].type == categories[0].id
    call = environment.facade.authorize_system_owned.call_args.kwargs
    assert call["actor"].user_id == 27
    assert call["target"].resource_id == str(categories[0].id)
    assert "use" in call["action_codes"]
    environment.facade.authorize_system_owned.assert_awaited_once()


async def test_permission_outage_preserves_catalog_and_retry_completes(environment):
    environment.fail = True
    with pytest.raises(RuntimeError, match="outage"):
        await apply_upgrade()
    tools, categories = await catalog_rows(environment)
    assert len(tools) == len(categories) == 1
    preview = await upgrade.run(apply=False)
    assert preview["ready"] is False
    assert preview["permission"]["before"][0]["state"] == "MISSING"
    environment.fail = False
    result = await apply_upgrade()
    assert result["ready"] is True
    assert result["catalog"]["tool_id"] == tools[0].id
    assert len((await catalog_rows(environment))[0]) == 1
    assert environment.close.await_count == 3


@pytest.mark.parametrize("failure", ["store", "marker"])
async def test_preflight_failure_preserves_empty_catalog(environment, failure):
    if failure == "marker":
        environment.marker.wait_until_ready.side_effect = RuntimeError("Synthetic marker failure")
    with pytest.raises((ValueError, RuntimeError)):
        await upgrade.run(apply=True, confirm_store_id="other-store" if failure == "store" else "fixture-store")
    assert await catalog_rows(environment) == ([], [])
    environment.facade.authorize_system_owned.assert_not_awaited()
    environment.close.assert_awaited_once()


async def test_existing_category_configuration_and_other_tool_permissions_are_preserved(environment):
    category_seed, _ = upgrade.seed_records()
    with upgrade.bypass_tenant_filter():
        async with environment.sessions() as session:
            session.add(
                GptsToolsType(
                    **{k: v for k, v in category_seed.items() if k not in {"id", "extra"}},
                    id=81,
                    extra='{"custom":"keep"}',
                    tenant_id=1,
                )
            )
            session.add(GptsToolsType(id=82, name="Unrelated preset", is_preset=1, tenant_id=1))
            await session.commit()
    environment.projections["81"] = "CURRENT"
    result = await apply_upgrade()
    assert result["ready"] is True
    assert result["catalog"]["category_id"] == 81
    _, categories = await catalog_rows(environment)
    assert next(row for row in categories if row.id == 81).extra == '{"custom":"keep"}'
    assert "82" not in environment.projections
    environment.facade.authorize_system_owned.assert_not_awaited()


async def test_pending_existing_projection_blocks_tool_insert(environment):
    category_seed, _ = upgrade.seed_records()
    with upgrade.bypass_tenant_filter():
        async with environment.sessions() as session:
            session.add(GptsToolsType(**{k: v for k, v in category_seed.items() if k != "id"}, id=81, tenant_id=1))
            await session.commit()
    environment.projections["81"] = "NON_CURRENT"
    from bisheng.common.errcode.permission import PermissionPublishNotReadyError

    with pytest.raises(PermissionPublishNotReadyError):
        await apply_upgrade()
    assert (await catalog_rows(environment))[0] == []
    environment.facade.authorize_system_owned.assert_not_awaited()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--apply"],
        ["--apply", "--confirm-store-id", "fixture-store"],
        ["--apply", "--operator-id", "27"],
        ["--operator-id", "0"],
        ["--operator-id", "-1"],
    ],
)
def test_apply_requires_explicit_target_and_audit_operator(arguments):
    with pytest.raises(SystemExit) as failure:
        upgrade.parse_args(arguments)
    assert failure.value.code == 2


@pytest.mark.parametrize("entrypoint", ["src/backend/entrypoint.sh", "docker/bisheng/entrypoint.sh"])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_container_upgrade_dispatch_forwards_arguments_and_exit_status(tmp_path, entrypoint, exit_code):
    root = Path(__file__).resolve().parents[4]
    interpreter = tmp_path / "python"
    interpreter.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@"\nexit {exit_code}\n')
    interpreter.chmod(0o755)
    result = subprocess.run(
        [
            "sh",
            str(root / entrypoint),
            "upgrade-work-knowledge",
            "--apply",
            "--confirm-store-id",
            "fixture-store",
            "--operator-id",
            "27",
        ],
        cwd=root / "src/backend",
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == exit_code
    assert result.stdout.splitlines() == [
        "scripts/register_work_knowledge_tool.py",
        "--apply",
        "--confirm-store-id",
        "fixture-store",
        "--operator-id",
        "27",
    ]
