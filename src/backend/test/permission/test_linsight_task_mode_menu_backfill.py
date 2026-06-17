"""F035 — unit tests for the linsight task-mode menu backfill (pure transform).

Mirrors the F034 ``relation_model_backfill`` test style: only the pure
``compute_missing_task_mode_grants`` set-difference is exercised; the DB
read/write wrapper is idempotent and benign, covered by startup self-heal.
"""

from bisheng.permission.domain.linsight_task_mode_menu_backfill import (
    compute_missing_task_mode_grants,
)


def test_only_roles_without_task_mode_returned():
    home = [(1, 10), (2, 10), (3, 20)]
    existing = {(2, 10)}  # role 2 already has linsight_task_mode
    assert compute_missing_task_mode_grants(home, existing) == [(1, 10), (3, 20)]


def test_dedup_repeated_home_keys():
    home = [(1, 10), (1, 10), (2, 10)]
    assert compute_missing_task_mode_grants(home, set()) == [(1, 10), (2, 10)]


def test_tenant_isolation_same_role_id_different_tenant():
    # Same role_id in two tenants are distinct keys; granting one must not cover the other.
    home = [(5, 10), (5, 20)]
    existing = {(5, 10)}
    assert compute_missing_task_mode_grants(home, existing) == [(5, 20)]


def test_noop_when_all_present():
    home = [(1, 10), (2, 10)]
    existing = {(1, 10), (2, 10)}
    assert compute_missing_task_mode_grants(home, existing) == []


def test_order_preserved():
    home = [(3, 10), (1, 10), (2, 10)]
    assert compute_missing_task_mode_grants(home, set()) == [(3, 10), (1, 10), (2, 10)]
