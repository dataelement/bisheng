"""Unit tests for the destructive department-subtree maintenance script."""

from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from scripts import purge_department_subtree as script


def test_parser_requires_exactly_one_department_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["purge_department_subtree.py", "--transfer-to-user-id", "1"])
    with pytest.raises(SystemExit):
        script.parse_args()

    monkeypatch.setattr(
        "sys.argv",
        [
            "purge_department_subtree.py",
            "--dept-id",
            "BS@target",
            "--department-id",
            "10",
            "--transfer-to-user-id",
            "1",
        ],
    )
    with pytest.raises(SystemExit):
        script.parse_args()


def _department(pk: int, parent_id: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=pk, parent_id=parent_id)


def test_build_subtree_returns_stable_breadth_first_order():
    root = _department(1)
    result = script._build_subtree(
        root,
        [_department(3, 1), root, _department(2, 1), _department(4, 2)],
    )

    assert [item.id for item in result] == [1, 2, 3, 4]
    assert [item.id for item in script._delete_order(result)] == [4, 3, 2, 1]


def test_chunks_respects_resource_transfer_limit():
    values = list(range(script.MAX_BATCH + 1))

    chunks = list(script._chunks(values))

    assert [len(chunk) for chunk in chunks] == [script.MAX_BATCH, 1]


@pytest.mark.asyncio
async def test_dry_run_never_calls_apply(capsys):
    plan = script.PurgePlan(
        departments_root_to_leaf=[],
        users=[],
        user_department_pairs=[],
        admin_pairs=[],
    )
    args = Namespace(dept_id="BS@test", department_id=None, transfer_to_user_id=1, apply=False)

    with (
        patch.object(script, "build_plan", AsyncMock(return_value=plan)),
        patch.object(
            script,
            "apply_plan",
            AsyncMock(),
        ) as apply_plan,
    ):
        assert await script.run(args) == 0

    assert not apply_plan.called
    assert "Dry-run only" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_apply_calls_execution_after_plan_is_built():
    plan = script.PurgePlan(
        departments_root_to_leaf=[],
        users=[],
        user_department_pairs=[],
        admin_pairs=[],
    )
    args = Namespace(dept_id="BS@test", department_id=None, transfer_to_user_id=1, apply=True)

    with (
        patch.object(script, "build_plan", AsyncMock(return_value=plan)),
        patch.object(
            script,
            "apply_plan",
            AsyncMock(return_value={"deleted_users": 1}),
        ) as apply_plan,
    ):
        assert await script.run(args) == 0

    apply_plan.assert_awaited_once_with(plan, 1)


@pytest.mark.asyncio
async def test_asset_preflight_uses_read_only_resource_resolution():
    resource = SimpleNamespace(id="resource-1")
    with (
        patch.object(
            script.ResourceOwnershipService,
            "_check_receiver_visible",
            AsyncMock(),
        ),
        patch.object(
            script.ResourceOwnershipService,
            "_resolve_resources",
            AsyncMock(return_value=[resource]),
        ) as resolve_resources,
    ):
        batches = await script._collect_asset_batches({10: set()}, receiver_id=1)

    assert len(batches) == len(script.SUPPORTED_TYPES)
    assert all(call.kwargs["resource_ids"] is None for call in resolve_resources.await_args_list)
