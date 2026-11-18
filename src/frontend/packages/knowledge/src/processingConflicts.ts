// Shared safe conflict variants. Host applications own translated copy.
const KNOWLEDGE_PROCESSING_CONFLICT_REASONS: Record<string, string> = {
    space_rebuilding: 'rebuild',
    space_copying: 'copy',
    metadata_value_writer_unconfigured: 'task_state',
    processing_space_not_ready: 'space_busy',
    metadata_space_processing: 'space_busy',
    move_space_processing: 'space_busy',
    copy_source_processing: 'space_busy',
    processing_file_state_not_ready: 'file_state',
    file_parse_in_progress: 'file_parsing',
    processing_file_state_changed: 'file_busy',
    metadata_file_processing: 'file_busy',
    chunk_file_processing: 'file_busy',
    move_file_processing: 'file_busy',
    copy_source_file_processing: 'file_busy',
    legacy_retry_file_busy: 'file_busy',
    processing_target_job_active: 'job_active',
    metadata_processing_conflict: 'job_active',
    move_processing_conflict: 'job_active',
    processing_file_retry_conflict: 'job_active',
    processing_retry_fence_conflict: 'job_active',
    model_provider_operation_active: 'model_busy',
    reference_target_deleting: 'deleting',
    source_space_move_input_required: 'source_input',
    space_transfer_input_required: 'transfer_input',
    move_source_input_required: 'move_input',
    move_pending_source_input: 'move_input',
    move_pending_processing_conflict: 'move_input',
    copy_permission_not_ready: 'initializing',
    copy_retry_unavailable: 'copy_retry',
    copy_vector_collection_not_ready: 'initializing',
    legacy_retry_pending_dispatch: 'file_queue',
    processing_scope_not_empty: 'scope_not_empty',
    processing_scope_incomplete: 'scope_incomplete',
    copy_complete_scope_required: 'scope_incomplete',
    metadata_space_required: 'space_required',
    processing_kind_unavailable: 'unsupported',
    processing_owner_missing: 'task_state',
    processing_reset_owner_missing: 'task_state',
    processing_reset_evidence_missing: 'task_state',
    processing_reset_anchor_changed: 'file_state',
    source_space_move_context_changed: 'scope_changed',
}

const KNOWLEDGE_PROCESSING_OPERATIONS: Record<string, string> = {
    embedding_rebuild: 'rebuild',
    space_copy: 'copy',
    space_initialization: 'initializing',
    space_unpublished: 'space_unpublished',
    space_failed: 'space_failed',
    metadata_schema_change: 'metadata',
    move_index: 'move',
    file_reprocess: 'reprocess',
    file_resplit: 'resplit',
    file_parse: 'file_parsing',
    file_waiting: 'file_queue',
}

export function knowledgeProcessingConflictVariant(envelope: unknown): string {
    if (!envelope || typeof envelope !== 'object' || (envelope as {status_code?: unknown}).status_code !== 10999) return '';
    const data = (envelope as {data?: unknown}).data;
    if (!data || typeof data !== 'object') return '';
    const raw = (data as {reason?: unknown}).reason;
    if (typeof raw !== 'string') return '';
    const reason = raw.split(':')[0];
    const operation = (data as {blocking_operation?: unknown}).blocking_operation;
    const observed = typeof operation === 'string' && Object.hasOwn(KNOWLEDGE_PROCESSING_OPERATIONS, operation)
        ? KNOWLEDGE_PROCESSING_OPERATIONS[operation] : '';
    return observed || (Object.hasOwn(KNOWLEDGE_PROCESSING_CONFLICT_REASONS, reason)
        ? KNOWLEDGE_PROCESSING_CONFLICT_REASONS[reason] : '');
}
