"""Safe task diagnostics. Raw provider errors and frozen payloads stay private."""

REASONS = frozenset(
    {
        "file_changed",
        "schema_changed",
        "model_changed",
        "model_unavailable",
        "copy_permissions_changed",
        "permission_projection_not_ready",
        "index_not_ready",
        "file_unavailable",
        "resource_deleted",
        "all_files_failed",
        "copy_input_failed",
        "copy_index_failed",
        "copy_initialization_failed",
    }
)
ALIASES = {
    "metadata_execution_source_or_values_changed": "file_changed",
    "metadata_execution_physical_scope_changed": "file_changed",
    "metadata_execution_physical_chain_changed": "file_changed",
    "metadata_execution_snapshot_invalid": "schema_changed",
    "metadata_schema_changed": "schema_changed",
    "metadata_schema_revision_changed": "schema_changed",
    "metadata_schema_digest_changed": "schema_changed",
    "model_config_revision_changed": "model_changed",
    "index_generation_changed": "model_changed",
    "knowledge_model_configuration_changed": "model_changed",
    "knowledge_new_model_invalid": "model_unavailable",
    "knowledge_embedding_unavailable": "model_unavailable",
    "copy_source_file_changed": "file_changed",
    "copy_target_changed": "file_changed",
    "copy_permission_sources_changed": "copy_permissions_changed",
    "copy_projection_unavailable": "permission_projection_not_ready",
    "copy_vector_collection_not_ready": "index_not_ready",
    "processing_file_source_changed": "file_changed",
    "owning_space_missing": "resource_deleted",
    "resource_deleted": "resource_deleted",
}


def safe_failure_reason(value):
    return (
        value if isinstance(value, str) and value in REASONS else ALIASES.get(value) if isinstance(value, str) else None
    )


def failure_reason_from_error(error):
    reason = safe_failure_reason(getattr(error, "kwargs", {}).get("reason"))
    if reason:
        return reason
    return {10903: "model_unavailable", 25008: "permission_projection_not_ready"}.get(getattr(error, "Code", None))


def space_processing_conflict(reason, *, state=None, has_transition=False):
    """Describe only an observed lifecycle blocker, without disclosing jobs."""
    from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError

    operation = (
        "embedding_rebuild"
        if has_transition or state == 3
        else "space_copy"
        if state == 2
        else "space_unpublished"
        if state == 0
        else "space_failed"
        if state == 4
        else None
    )
    return KnowledgeProcessingConflictError(reason=reason, **({"blocking_operation": operation} if operation else {}))


def file_processing_conflict(reason, status):
    from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError

    operation = {1: "file_parse", 4: "embedding_rebuild", 5: "file_waiting"}.get(status)
    return KnowledgeProcessingConflictError(reason=reason, **({"blocking_operation": operation} if operation else {}))
