"""Regression tests for the department short-name backfill script."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department
from scripts import backfill_department_short_names as script


async def _create_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite://", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Department.__table__.create)
    return engine


async def _add_department(
    session: AsyncSession,
    *,
    dept_id: str,
    name: str,
    tenant_id: int,
    parent_id: int | None = None,
    short_name: str | None = None,
    source: str = "local",
    status: str = "active",
) -> Department:
    department = Department(
        dept_id=dept_id,
        name=name,
        short_name=short_name,
        tenant_id=tenant_id,
        parent_id=parent_id,
        path="",
        source=source,
        status=status,
    )
    session.add(department)
    await session.commit()
    await session.refresh(department)
    return department


def test_cli_defaults_to_read_only_bounded_batches() -> None:
    args = script.parse_args([])

    assert args.apply is False
    assert args.batch_size == 200
    assert args.sample_limit == 20


@pytest.mark.parametrize(
    "argv",
    [
        ["--batch-size", "0"],
        ["--batch-size", "1001"],
        ["--sample-limit", "-1"],
        ["--sample-limit", "1001"],
    ],
)
def test_cli_rejects_unsafe_bounds(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        script.parse_args(argv)


def test_exact_direct_parent_prefix_derivation() -> None:
    assert script.derive_short_name(
        "北京首钢股份有限公司炼铁作业部",
        "北京首钢股份有限公司",
    ) == script.Derivation(short_name="炼铁作业部", reason=None)
    assert script.derive_short_name("父部门  子部门  ", "父部门") == script.Derivation(
        short_name="子部门",
        reason=None,
    )
    assert script.derive_short_name("前缀父部门后缀", "父部门") == script.Derivation(
        short_name=None,
        reason="parent_name_not_prefix",
    )
    assert script.derive_short_name("研发中心", "研发中心") == script.Derivation(
        short_name=None,
        reason="derived_short_name_empty",
    )
    assert script.derive_short_name("PX" + "长" * 64, "P") == script.Derivation(
        short_name=None,
        reason="derived_short_name_too_long",
    )


async def test_dry_run_apply_protection_and_idempotency() -> None:
    engine = await _create_engine()
    with bypass_tenant_filter():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            parent_one = await _add_department(
                session,
                dept_id="LOCAL@parent-1",
                name="北京首钢股份有限公司",
                tenant_id=1,
            )
            valid_one = await _add_department(
                session,
                dept_id="LOCAL@valid-1",
                name="北京首钢股份有限公司炼铁作业部",
                tenant_id=1,
                parent_id=parent_one.id,
            )
            blank_value = await _add_department(
                session,
                dept_id="LOCAL@blank",
                name="北京首钢股份有限公司能源部",
                tenant_id=1,
                parent_id=parent_one.id,
                short_name="   ",
            )
            existing = await _add_department(
                session,
                dept_id="LOCAL@existing",
                name="北京首钢股份有限公司已有部门",
                tenant_id=1,
                parent_id=parent_one.id,
                short_name="人工简称",
            )
            archived = await _add_department(
                session,
                dept_id="LOCAL@archived",
                name="北京首钢股份有限公司归档部门",
                tenant_id=1,
                parent_id=parent_one.id,
                status="archived",
            )
            root = await _add_department(
                session,
                dept_id="LOCAL@root",
                name="独立根部门",
                tenant_id=1,
            )
            missing_parent = await _add_department(
                session,
                dept_id="LOCAL@missing-parent",
                name="缺失父部门子部门",
                tenant_id=1,
                parent_id=999_999,
            )
            not_prefix = await _add_department(
                session,
                dept_id="LOCAL@not-prefix",
                name="炼铁作业部北京首钢股份有限公司",
                tenant_id=1,
                parent_id=parent_one.id,
            )
            same_name = await _add_department(
                session,
                dept_id="LOCAL@same-name",
                name="北京首钢股份有限公司",
                tenant_id=1,
                parent_id=parent_one.id,
            )
            too_long = await _add_department(
                session,
                dept_id="LOCAL@too-long",
                name="北京首钢股份有限公司" + "长" * 65,
                tenant_id=1,
                parent_id=parent_one.id,
            )

            parent_two = await _add_department(
                session,
                dept_id="SG@parent-2",
                name="首钢集团",
                tenant_id=2,
                source="sg",
            )
            valid_two = await _add_department(
                session,
                dept_id="SG@valid-2",
                name="首钢集团技术研究院",
                tenant_id=2,
                parent_id=parent_two.id,
                source="sg",
            )
            cross_tenant_parent = await _add_department(
                session,
                dept_id="SG@cross-tenant",
                name="北京首钢股份有限公司跨租户部门",
                tenant_id=2,
                parent_id=parent_one.id,
                source="sg",
            )

            dry_run = await script.backfill_department_short_names(
                session,
                apply=False,
                batch_size=2,
                sample_limit=50,
            )
            rows_after_dry_run = {int(row.id): row.short_name for row in (await session.exec(select(Department))).all()}

            assert dry_run.would_update == 3
            assert dry_run.updated == 0
            assert rows_after_dry_run[int(valid_one.id)] is None
            assert rows_after_dry_run[int(valid_two.id)] is None
            assert rows_after_dry_run[int(blank_value.id)] == "   "
            assert {
                "not_active",
                "short_name_present",
                "root_department",
                "parent_missing",
                "parent_tenant_mismatch",
                "parent_name_not_prefix",
                "derived_short_name_empty",
                "derived_short_name_too_long",
            }.issubset(dry_run.reason_counts)

            applied = await script.backfill_department_short_names(
                session,
                apply=True,
                batch_size=2,
                sample_limit=50,
            )
            session.expire_all()
            rows_after_apply = {int(row.id): row.short_name for row in (await session.exec(select(Department))).all()}

            assert applied.updated == 3
            assert rows_after_apply[int(valid_one.id)] == "炼铁作业部"
            assert rows_after_apply[int(valid_two.id)] == "技术研究院"
            assert rows_after_apply[int(blank_value.id)] == "能源部"
            assert rows_after_apply[int(existing.id)] == "人工简称"
            assert rows_after_apply[int(archived.id)] is None
            assert rows_after_apply[int(root.id)] is None
            assert rows_after_apply[int(missing_parent.id)] is None
            assert rows_after_apply[int(not_prefix.id)] is None
            assert rows_after_apply[int(same_name.id)] is None
            assert rows_after_apply[int(too_long.id)] is None
            assert rows_after_apply[int(cross_tenant_parent.id)] is None

            rerun = await script.backfill_department_short_names(
                session,
                apply=False,
                batch_size=3,
                sample_limit=10,
            )
            assert rerun.would_update == 0

    await engine.dispose()


async def test_apply_rechecks_current_state_before_write() -> None:
    engine = await _create_engine()
    with bypass_tenant_filter():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            parent = await _add_department(
                session,
                dept_id="LOCAL@drift-parent",
                name="父部门",
                tenant_id=1,
            )
            child = await _add_department(
                session,
                dept_id="LOCAL@drift-child",
                name="父部门子部门",
                tenant_id=1,
                parent_id=parent.id,
            )
            candidate = script.BackfillCandidate(
                department_id=int(child.id),
                tenant_id=1,
                source="local",
                department_name="父部门子部门",
                parent_id=int(parent.id),
                parent_name="父部门",
                short_name="子部门",
            )

            child.short_name = "人工简称"
            session.add(child)
            await session.commit()

            outcome = await script.apply_candidate(session, candidate)
            await session.commit()
            await session.refresh(child)

    assert outcome == script.ApplyOutcome(updated=False, reason="changed_before_update")
    assert child.short_name == "人工简称"
    await engine.dispose()


async def test_apply_failure_rolls_back_current_batch_and_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine = await _create_engine()
    with bypass_tenant_filter():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            parent = await _add_department(
                session,
                dept_id="LOCAL@failure-parent",
                name="父部门",
                tenant_id=1,
            )
            first = await _add_department(
                session,
                dept_id="LOCAL@failure-first",
                name="父部门第一部门",
                tenant_id=1,
                parent_id=parent.id,
            )
            second = await _add_department(
                session,
                dept_id="LOCAL@failure-second",
                name="父部门第二部门",
                tenant_id=1,
                parent_id=parent.id,
            )

    @asynccontextmanager
    async def _session_factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    original_apply_candidate = script.apply_candidate
    call_count = 0

    async def _fail_second_candidate(
        session: AsyncSession,
        candidate: script.BackfillCandidate,
    ) -> script.ApplyOutcome:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("sensitive database details")
        return await original_apply_candidate(session, candidate)

    async def _no_close() -> None:
        return None

    monkeypatch.setattr(script, "get_async_db_session", _session_factory)
    monkeypatch.setattr(script, "apply_candidate", _fail_second_candidate)
    monkeypatch.setattr(script, "close_app_context", _no_close)

    result = await script._run(script.parse_args(["--apply", "--batch-size", "10"]))

    with bypass_tenant_filter():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            rows = {int(row.id): row.short_name for row in (await session.exec(select(Department))).all()}

    stderr = capsys.readouterr().err
    assert result == script.EXIT_EXECUTION
    assert rows[int(first.id)] is None
    assert rows[int(second.id)] is None
    assert '"error_type": "RuntimeError"' in stderr
    assert "sensitive database details" not in stderr
    await engine.dispose()
