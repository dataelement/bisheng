"""Deployed audit revisions must remain valid upgrade starting points."""

from test.database.test_alembic_single_head import _script_directory


def test_deployed_audit_head_upgrades_without_replaying_legacy_migrations():
    """Keep the 13001 audit lineage while applying native session changes."""
    scripts = _script_directory()
    revisions = {step.revision.revision for step in scripts._upgrade_revs("head", "f062_dsh_audit_tree")}
    assert revisions == {
        "f062_work110_audit_lookup",
        "f062_work110_audit_sources",
        "f062_work110_audit_groups",
        "f062_work110_audit_tree",
        "work110_dsh_local_sessions",
        "work110_merge_legacy_audit",
    }


def test_native_session_head_can_join_the_deployed_audit_lineage():
    """Previously built native-access images also retain a forward path."""
    scripts = _script_directory()
    revisions = {step.revision.revision for step in scripts._upgrade_revs("head", "work110_dsh_local_sessions")}
    assert revisions == {
        "merge_dsh_heads",
        "merge_beta1_beta2_heads",
        "f068_knowledge_chat_entry",
        "f065_merge_dsh_audit_heads",
        "dsh_audit_model_lookup",
        "dsh_audit_sources",
        "dsh_audit_groups",
        "f062_dsh_audit_tree",
        "work110_merge_legacy_audit",
    }
