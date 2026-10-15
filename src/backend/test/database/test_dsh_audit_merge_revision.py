"""Offline guards for joining both published DSH migration histories."""

import pytest

from test.database.test_alembic_single_head import _script_directory

_MERGE = "f065_merge_dsh_audit_heads"
_PARENTS = ("merge_dsh_heads", "f065_dsh_install_policy_default_off")


def test_merge_preserves_both_published_parents():
    revision = _script_directory().get_revision(_MERGE)
    assert set(revision.down_revision) == set(_PARENTS)


@pytest.mark.parametrize("current", _PARENTS)
def test_upgrade_graph_reaches_head_from_either_published_parent(current):
    revisions = list(_script_directory().iterate_revisions("head", current))
    assert _MERGE in {revision.revision for revision in revisions}
    assert current not in {revision.revision for revision in revisions}


def test_merge_body_has_no_schema_or_data_operations():
    module = _script_directory().get_revision(_MERGE).module
    assert module.upgrade() is None
    assert module.downgrade() is None
