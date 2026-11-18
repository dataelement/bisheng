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
