// Explicit protocol allowlist. Unknown server diagnostics are never shown to users.
export const referenceReasonGroups: Record<string, readonly string[]> = {
    app_preview: [
        'app_preview_pending_task_required', 'app_preview_qualification_invalid', 'app_preview_route_ambiguous',
        'app_source_execution_required',
    ],
    app_version: [
        'app_management_source_version', 'app_source_version_required', 'app_version_parent',
    ],
    channel_configuration: [
        'channel_delivery_configuration_invalid', 'channel_delivery_configuration_not_effective', 'channel_delivery_rule_missing',
        'channel_selection_invalid', 'channel_source_configuration_invalid',
    ],
    channel_folder: [
        'channel_legacy_folder_rebind_required',
    ],
    channel_time: [
        'channel_delivery_time_invalid',
    ],
    configuration_changed: [
        'app_name_binding_changed', 'checkpoint_scope_changed', 'knowledge_cleanup_index_changed',
        'knowledge_cleanup_job_changed', 'knowledge_cleanup_manifest_target_changed', 'knowledge_clear_tombstone_conflict',
        'knowledge_rebuild_file_scope_changed', 'metadata_completion_business_result_changed', 'metadata_completion_pending_schema_change',
        'metadata_plan_changed', 'model_deletion_execution_changed', 'model_deletion_execution_targets_changed',
        'new_source_already_indexed', 'processing_cutover_business_result_changed', 'processing_file_source_changed',
        'rebuild_cleanup_origin_changed', 'reference_batch_order_changed', 'reference_file_owner_context_changed',
        'reference_file_owner_pending_changes', 'reference_file_owner_write_conflict', 'reference_owner_result_targets_changed',
        'reference_read_target_plan_changed', 'reference_receipt_expired', 'root_revision_conflict',
        'source_digest_mismatch', 'source_revision_conflict', 'target_owner_scope_expired',
    ],
    configuration_guard: [
        'knowledge_model_write_requires_configuration_cas',
    ],
    delete_force: [
        'knowledge_delete_force_not_supported',
    ],
    delete_selection: [
        'knowledge_delete_no_valid_items', 'knowledge_delete_selection_invalid', 'knowledge_delete_selection_required',
        'knowledge_reference_selection_invalid',
    ],
    deletion_evidence: [
        'knowledge_reference_tombstone_facts_invalid', 'knowledge_reference_tombstone_result_invalid', 'legacy_evidence_mismatch',
        'legacy_evidence_original_mismatch', 'legacy_target_reappeared', 'model_deletion_execution_untrusted',
        'model_reference_tombstone_result_invalid', 'new_invalid_reference', 'processing_cutover_original_evidence_required',
        'processing_reset_original_evidence_required', 'reference_ancestor_evidence_mismatch', 'reference_deleted_target_reappeared',
        'reference_deletion_evidence_mismatch', 'reference_legacy_evidence_mismatch', 'reference_legacy_target_reappeared',
        'reference_original_target_mismatch', 'reference_target_deletion_invalid', 'reference_target_deletion_runtime_mismatch',
    ],
    execution_context: [
        'app_management_execution_context_required', 'app_source_transaction_scope', 'assistant_read_transaction_required',
        'async_guard_required', 'channel_delivery_transaction_required', 'knowledge_model_finalization_background_changed',
        'knowledge_model_finalization_background_required', 'knowledge_model_identity_transaction', 'knowledge_model_plan_transaction',
        'knowledge_model_read_context', 'knowledge_rebuild_background_required', 'knowledge_removal_plan_transaction',
        'metadata_completion_native_transaction_required', 'metadata_execution_native_tenant_transaction_required', 'model_default_context_required',
        'processing_actual_worker_required', 'processing_attempt_background_required', 'processing_cutover_background_required',
        'processing_cutover_business_session_required', 'processing_cutover_job_session_required', 'processing_cutover_lease_changed',
        'processing_cutover_original_lease_required', 'rebuild_cleanup_background_required', 'source_read_transaction_required',
    ],
    identity_changed: [
        'knowledge_delete_actor_changed', 'knowledge_model_identity_context_changed', 'knowledge_model_identity_source_changed',
        'knowledge_reference_identity_changed', 'legacy_evidence_source_tenant_mismatch', 'metadata_owner_actor_changed',
        'model_reference_identity_changed', 'processing_actor_scope_changed', 'reference_original_evidence_conflict',
        'reference_read_identity_context_mixed', 'reference_target_owner_changed', 'source_tenant_mismatch',
        'space_upload_identity_changed_or_unbound', 'target_owner_changed',
    ],
    identity_context: [
        'actor_required', 'app_identity_ambiguous', 'app_management_identity_invalid',
        'app_management_source_credential', 'app_reference_identity_invalid', 'app_reference_principal_root',
        'app_runtime_principal_required', 'assistant_original_identity_required', 'distinct_same_tenant_spaces_required',
        'duplicate_reference_identity', 'knowledge_model_identity_invalid', 'knowledge_model_identity_not_issued',
        'knowledge_model_original_identity_required', 'knowledge_model_tenant_required', 'knowledge_rag_resource_identity',
        'metadata_completion_concrete_tenant_required', 'metadata_concrete_tenant_required', 'model_default_read_identity_required',
        'model_default_tenant_required', 'move_concrete_tenant_required', 'processing_fence_tenant_required',
        'processing_original_identity_required', 'reference_read_actor_required', 'reference_read_identity_context_invalid',
        'reference_read_identity_required', 'reference_read_tenant_required', 'reference_target_tenant_required',
        'reference_verification_tenant_bypassed', 'reference_verification_tenant_missing', 'source_tenant_context_missing',
        'source_tenant_filter_bypassed', 'workflow_original_identity_required',
    ],
    inactive: [
        'reference_source_inactive',
    ],
    invalid_selection: [
        'app_knowledge_plan_invalid', 'app_knowledge_reference_invalid', 'app_model_plan_incomplete',
        'app_reference_declaration_invalid', 'app_reference_resolution', 'assistant_model_id_required',
        'assistant_source_configuration', 'knowledge_model_source_configuration', 'knowledge_space_creator_parent_invalid',
        'migration_name_catalog_invalid', 'processing_model_admission_invalid', 'reference_selection_invalid',
        'reference_target_keys_required',
    ],
    knowledge_unavailable: [
        'app_knowledge_selection_unavailable', 'knowledge_reference_parent_unavailable', 'knowledge_reference_target_unavailable',
        'preview_knowledge_unavailable',
    ],
    missing: [
        'reference_target_unexplained_missing',
    ],
    model_default: [
        'model_default_configuration_invalid', 'model_default_key_invalid', 'model_default_not_configured',
        'model_default_owner_missing', 'model_default_root_cannot_inherit', 'model_default_slot_invalid',
    ],
    model_identity: [
        'app_model_binding_unresolved', 'assistant_legacy_model_name_unresolved', 'model_name_frozen_identity_unavailable',
        'model_name_provider_owner_mismatch', 'model_name_tenant_mismatch', 'model_provider_owner_mismatch',
        'model_retained_identity_invalid',
    ],
    model_slot: [
        'knowledge_model_business_slot_missing', 'knowledge_model_business_slot_required', 'knowledge_reference_target_type_invalid',
        'model_reference_target_type_invalid', 'reference_read_slot_plan_invalid',
    ],
    model_unavailable: [
        'knowledge_new_model_invalid', 'knowledge_pending_model_invalid', 'model_default_models_unavailable',
        'model_reference_target_unavailable', 'model_selection_unavailable',
    ],
    processing_plan: [
        'checkpoint_counts_invalid', 'checkpoint_digest_invalid', 'durable_checkpoint_required',
        'generation_invalid', 'knowledge_chunk_index_required', 'knowledge_cleanup_index_required',
        'knowledge_cleanup_persisted_job_required', 'knowledge_cleanup_resource_not_owned', 'knowledge_cleanup_resource_required',
        'knowledge_clear_execution_inconsistent', 'knowledge_rebuild_space_required', 'metadata_index_guard_required',
        'metadata_index_owner_scope_required', 'metadata_index_snapshot_invalid', 'move_checkpoint_closed_shape_required',
        'move_checkpoint_typed_required', 'move_index_policy_invalid', 'move_index_typed_result_required',
        'processing_cutover_business_result_required', 'rebuild_cleanup_collection_invalid',
    ],
    processing_unavailable: [
        'processing_configuration_unavailable',
    ],
    published_only: [
        'public_workflow_preview_forbidden',
    ],
    reference_page: [
        'knowledge_reference_cursor_invalid', 'knowledge_reference_page_size_invalid', 'model_reference_cursor_context_invalid',
        'model_reference_cursor_invalid', 'model_reference_page_size_invalid',
    ],
    reference_target_invalid: [
        'reference_target_invalid',
    ],
    sharing_result: [
        'model_reference_share_result_invalid',
    ],
    source_context: [
        'app_management_source_context', 'app_source_snapshot_invalid', 'assistant_authorized_links_required',
        'assistant_source_request', 'assistant_source_snapshot', 'channel_source_request_invalid',
        'channel_source_snapshot_invalid', 'ineffective_source_has_references', 'knowledge_disclosure_unflushed_source_changes',
        'knowledge_model_internal_source_not_owned', 'knowledge_model_resource_invalid', 'knowledge_model_source_request_invalid',
        'metadata_owner_plan_invalid', 'model_default_source_request', 'model_removal_requires_owner_application',
        'processing_original_file_evidence_required', 'reference_batch_root_mismatch', 'reference_batch_sources_required',
        'reference_file_owner_inbound_invalid', 'reference_file_owner_invalid', 'reference_mixed_source_duplicate',
        'reference_mixed_source_scope_invalid', 'reference_mixed_sources_required', 'reference_owner_query_empty',
        'reference_read_purpose_mismatch', 'reference_row_source_mismatch', 'reference_source_mismatch',
        'scope_required', 'target_owner_scope_invalid', 'workflow_connection_root_mismatch',
        'workflow_source_request_invalid',
    ],
    space_required: [
        'metadata_completion_space_required', 'processing_space_required', 'space_required',
    ],
    verification_context: [
        'app_source_authority_already_installed', 'app_source_authority_invalid', 'extractor_version_invalid',
        'knowledge_disclosure_invalid_batch', 'knowledge_model_finalization_plan_required', 'knowledge_model_plan_not_issued',
        'knowledge_removal_plan_not_issued', 'metadata_completion_receipt_invalid', 'metadata_plan_not_issued',
        'model_name_plan_invalid', 'ports_required', 'processing_cutover_receipt_invalid',
        'reference_batch_manifest_required', 'reference_batch_required', 'reference_owner_result_incomplete',
        'reference_owner_result_invalid', 'reference_prelock_must_not_issue_receipts', 'reference_read_target_owner_result_invalid',
        'reference_read_target_plan_required', 'reference_receipt_invalid', 'reference_receipt_not_issued',
        'reference_receipt_scope_mismatch', 'reference_receipt_set_incomplete', 'reference_source_owner_result_invalid',
        'reference_target_observation_invalid', 'reference_target_owner_unregistered', 'reference_target_verifier_mismatch',
        'reference_target_verifier_missing', 'verified_reference_set_required',
    ],
    workflow_changed: [
        'workflow_override_changes_references', 'workflow_override_invalid', 'workflow_preview_snapshot_mismatch',
        'workflow_saved_graph_mismatch', 'workflow_source_snapshot_mismatch',
    ],
    workflow_graph: [
        'workflow_execution_graph_invalid', 'workflow_node_input_invalid', 'workflow_node_invalid',
        'workflow_preview_payload_invalid', 'workflow_reference_invalid',
    ],
    workflow_mode: [
        'workflow_execution_mode_invalid',
    ],
    workflow_version: [
        'public_workflow_current_version_required', 'workflow_version_invalid',
    ],
};

export const referenceReasonKeys = new Map(
    Object.entries(referenceReasonGroups).flatMap(([group, reasons]) => reasons.map(reason => [reason, group])),
);
