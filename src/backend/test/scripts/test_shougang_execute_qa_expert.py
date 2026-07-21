"""Tests for the hardcoded QA expert import script."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import scripts.shougang_execute_qa_expert as script


def _row(user_id: int | None = 1, name: str = "专家甲") -> script.ExpertSeedRow:
    return script.ExpertSeedRow(
        user_id=user_id,
        name=name,
        unit="测试单位",
        position="测试岗位",
        title="测试职务",
        job_family="测试职位族",
        job_category="测试职位类",
    )


def test_hardcoded_rows_preserve_the_source_data_shape() -> None:
    assert len(script.EXPERT_ROWS) == 153

    populated_user_ids = [row.user_id for row in script.EXPERT_ROWS if row.user_id is not None]
    assert len(populated_user_ids) == 116
    assert len(set(populated_user_ids)) == 116
    assert all(isinstance(user_id, int) for user_id in populated_user_ids)
    assert sum(row.user_id is None for row in script.EXPERT_ROWS) == 37
    assert all(
        value and value == value.strip()
        for row in script.EXPERT_ROWS
        for value in (
            row.name,
            row.unit,
            row.position,
            row.title,
            row.job_family,
            row.job_category,
        )
    )


async def test_resolve_user_id_keeps_a_hardcoded_id() -> None:
    lookup_users = AsyncMock()

    user_id, reason = await script._resolve_user_id(_row(user_id=7), lookup_users)

    assert user_id == 7
    assert reason is None
    lookup_users.assert_not_awaited()


async def test_resolve_user_id_accepts_one_name_match() -> None:
    lookup_users = AsyncMock(return_value=[SimpleNamespace(user_id=9)])

    user_id, reason = await script._resolve_user_id(_row(user_id=None), lookup_users)

    assert user_id == 9
    assert reason is None
    lookup_users.assert_awaited_once_with("专家甲")


@pytest.mark.parametrize(
    ("matches", "expected_reason"),
    [
        ([], "not_found"),
        ([SimpleNamespace(user_id=1), SimpleNamespace(user_id=2)], "ambiguous"),
    ],
)
async def test_resolve_user_id_rejects_non_unique_name_matches(
    matches: list[SimpleNamespace], expected_reason: str
) -> None:
    user_id, reason = await script._resolve_user_id(_row(user_id=None), AsyncMock(return_value=matches))

    assert user_id is None
    assert reason == expected_reason


async def test_prepare_experts_skips_existing_user_ids() -> None:
    rows = (_row(user_id=1, name="已有专家"), _row(user_id=2, name="新增专家"))
    lookup_users = AsyncMock()
    list_departments = AsyncMock(return_value=[SimpleNamespace(id=12, name="测试单位")])
    get_existing_expert = AsyncMock(side_effect=[SimpleNamespace(id=100, user_id=1), None])
    expert_factory = Mock(side_effect=lambda **values: SimpleNamespace(**values))

    experts, stats = await script._prepare_experts(
        rows,
        lookup_users=lookup_users,
        list_departments=list_departments,
        get_existing_expert=get_existing_expert,
        expert_factory=expert_factory,
    )

    assert len(experts) == 1
    assert experts[0].user_id == 2
    assert experts[0].depart_ment == "12"
    assert stats.skipped_duplicate == 1
    list_departments.assert_awaited_once_with()
    assert get_existing_expert.await_count == 2
    lookup_users.assert_not_awaited()


async def test_persist_experts_dry_run_never_creates_rows() -> None:
    repository = SimpleNamespace(create=AsyncMock())
    experts = [SimpleNamespace(user_id=1), SimpleNamespace(user_id=2)]

    inserted = await script._persist_experts(experts, repository=repository, dry_run=True)

    assert inserted == 2
    repository.create.assert_not_awaited()


async def test_prepare_all_hardcoded_rows_with_unique_name_matches() -> None:
    missing_names = [row.name for row in script.EXPERT_ROWS if row.user_id is None]
    resolved_ids = {name: 50_000 + index for index, name in enumerate(missing_names)}
    lookup_users = AsyncMock(side_effect=lambda name: [SimpleNamespace(user_id=resolved_ids[name])])
    units = sorted({row.unit for row in script.EXPERT_ROWS})
    list_departments = AsyncMock(
        return_value=[SimpleNamespace(id=index, name=unit) for index, unit in enumerate(units, start=1)]
    )
    get_existing_expert = AsyncMock(return_value=None)
    expert_factory = Mock(side_effect=lambda **values: SimpleNamespace(**values))

    experts, stats = await script._prepare_experts(
        script.EXPERT_ROWS,
        lookup_users=lookup_users,
        list_departments=list_departments,
        get_existing_expert=get_existing_expert,
        expert_factory=expert_factory,
    )

    assert len(experts) == 153
    assert lookup_users.await_count == 37
    assert get_existing_expert.await_count == 153
    assert stats == script.ImportStats()


async def test_persist_experts_creates_each_prepared_row() -> None:
    repository = SimpleNamespace(create=AsyncMock())
    experts = [SimpleNamespace(user_id=1), SimpleNamespace(user_id=2)]

    inserted = await script._persist_experts(experts, repository=repository, dry_run=False)

    assert inserted == 2
    assert repository.create.await_count == 2
    repository.create.assert_any_await(experts[0])
    repository.create.assert_any_await(experts[1])
