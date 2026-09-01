"""Tests for ``scripts/clean_user_group_admin_resource_grants.py``."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, call

import pytest

import scripts.clean_user_group_admin_resource_grants as mod


def test_normalize_grants_selects_only_admin_manager_resource_tuples():
    tuples = [
        {"user": "user_group:10#admin", "relation": "manager", "object": "knowledge_library:24"},
        {"user": "user_group:10#admin", "relation": "manager", "object": "knowledge_library:24"},
        {"user": "user_group:10#member", "relation": "manager", "object": "knowledge_library:24"},
        {"user": "user_group:10#admin", "relation": "viewer", "object": "knowledge_library:24"},
        {"user": "user:301", "relation": "manager", "object": "knowledge_library:24"},
        {"user": "user_group:10#admin", "relation": "manager", "object": "user_group:10"},
    ]

    assert mod._normalize_grants(tuples) == [
        mod.AdminResourceGrant(
            user="user_group:10#admin",
            relation="manager",
            object="knowledge_library:24",
        )
    ]


def test_admin_resource_grant_exposes_group_and_object_type():
    grant = mod.AdminResourceGrant(
        user="user_group:42#admin",
        relation="manager",
        object="workflow:abc",
    )

    assert grant.group_id == 42
    assert grant.object_type == "workflow"


async def test_load_fga_targets_queries_each_user_group_by_admin_subject(
    monkeypatch: pytest.MonkeyPatch,
):
    fga = AsyncMock()
    results = {
        ("user_group:7#admin", "workflow:"): [
            {
                "user": "user_group:7#admin",
                "relation": "manager",
                "object": "workflow:abc",
            }
        ],
        ("user_group:10#admin", "knowledge_library:"): [
            {
                "user": "user_group:10#admin",
                "relation": "viewer",
                "object": "knowledge_library:24",
            },
            {
                "user": "user_group:10#admin",
                "relation": "manager",
                "object": "knowledge_library:24",
            },
        ],
    }

    async def read_tuples(*, user: str, relation: str, object: str):
        assert relation == "manager"
        return results.get((user, object), [])

    fga.read_tuples.side_effect = read_tuples
    monkeypatch.setattr(
        "bisheng.core.openfga.manager.aget_fga_client",
        AsyncMock(return_value=fga),
    )
    monkeypatch.setattr(
        mod,
        "_target_object_types",
        lambda: ("knowledge_library", "workflow"),
    )

    assert await mod._load_fga_targets([10, 7, 10]) == [
        mod.AdminResourceGrant(
            user="user_group:10#admin",
            relation="manager",
            object="knowledge_library:24",
        ),
        mod.AdminResourceGrant(
            user="user_group:7#admin",
            relation="manager",
            object="workflow:abc",
        ),
    ]
    assert fga.read_tuples.await_args_list == [
        call(user="user_group:7#admin", relation="manager", object="knowledge_library:"),
        call(user="user_group:7#admin", relation="manager", object="workflow:"),
        call(user="user_group:10#admin", relation="manager", object="knowledge_library:"),
        call(user="user_group:10#admin", relation="manager", object="workflow:"),
    ]


def test_target_object_types_follow_f006_group_resource_mapping():
    assert mod._target_object_types() == (
        "assistant",
        "dashboard",
        "knowledge_library",
        "knowledge_space",
        "tool",
        "workflow",
    )


async def test_dry_run_never_mutates(monkeypatch: pytest.MonkeyPatch):
    grants = [
        mod.AdminResourceGrant(
            user="user_group:10#admin",
            relation="manager",
            object="knowledge_library:24",
        )
    ]
    pending = [
        mod.PendingAdminWrite(
            id=7,
            user="user_group:10#admin",
            relation="manager",
            object="knowledge_library:24",
        )
    ]

    monkeypatch.setattr(mod, "_load_group_ids", lambda: _async_value([10]))
    monkeypatch.setattr(mod, "_load_fga_targets", lambda _group_ids: _async_value(grants))
    monkeypatch.setattr(mod, "_load_pending_admin_writes", lambda: _async_value(pending))

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("dry-run must not mutate state")

    monkeypatch.setattr(mod, "_mark_pending_admin_writes_dead", unexpected)
    monkeypatch.setattr(mod, "_delete_grants", unexpected)
    monkeypatch.setattr(mod, "_invalidate_permission_cache", unexpected)

    assert await mod.run(apply=False, sample_limit=10) == 0


async def test_apply_blocks_replay_deletes_and_verifies(monkeypatch: pytest.MonkeyPatch):
    grant = mod.AdminResourceGrant(
        user="user_group:10#admin",
        relation="manager",
        object="knowledge_library:24",
    )
    pending = mod.PendingAdminWrite(
        id=7,
        user=grant.user,
        relation=grant.relation,
        object=grant.object,
    )
    calls: list[object] = []
    grant_snapshots = iter([[grant], []])
    pending_snapshots = iter([[pending], []])

    @asynccontextmanager
    async def fake_lock():
        calls.append("lock-enter")
        yield
        calls.append("lock-exit")

    async def load_grants(_group_ids: list[int]):
        return next(grant_snapshots)

    async def load_pending():
        return next(pending_snapshots)

    async def mark_dead(ids: list[int]) -> int:
        calls.append(("mark-dead", ids))
        return len(ids)

    async def delete_grants(grants: list[mod.AdminResourceGrant]) -> None:
        calls.append(("delete", grants))

    async def invalidate() -> None:
        calls.append("invalidate")

    monkeypatch.setattr(mod, "_hold_retry_lock", fake_lock)
    monkeypatch.setattr(mod, "_load_group_ids", lambda: _async_value([10]))
    monkeypatch.setattr(mod, "_load_fga_targets", load_grants)
    monkeypatch.setattr(mod, "_load_pending_admin_writes", load_pending)
    monkeypatch.setattr(mod, "_mark_pending_admin_writes_dead", mark_dead)
    monkeypatch.setattr(mod, "_delete_grants", delete_grants)
    monkeypatch.setattr(mod, "_invalidate_permission_cache", invalidate)

    assert await mod.run(apply=True, sample_limit=10) == 0
    assert calls == [
        "lock-enter",
        ("mark-dead", [7]),
        ("delete", [grant]),
        "invalidate",
        "lock-exit",
    ]


async def _async_value(value):
    return value
