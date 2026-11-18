import type { ProcessingKind } from "@/controllers/API/knowledgeSpace";

const REASONS = new Set([
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
]);
const OBSOLETE_REASONS: Record<string, string> = {
  model_config_revision_changed: "model_changed",
  index_generation_changed: "model_changed",
  metadata_schema_revision_changed: "schema_changed",
  metadata_schema_digest_changed: "schema_changed",
  resource_deleted: "resource_deleted",
  owning_space_missing: "resource_deleted",
};

export function processingFailureKey(
  value: {
    failure_reason?: string | null;
    obsolete_reason?: string | null;
    error_code?: number | null;
  },
  kind?: ProcessingKind,
): string | undefined {
  const reason =
    value.failure_reason && REASONS.has(value.failure_reason)
      ? value.failure_reason
      : OBSOLETE_REASONS[value.obsolete_reason ?? ""];
  if (reason) return `f118.failure_${reason}`;
  // Old tasks retained only error codes. Never invent an exact cause for them.
  if (kind === "space_copy" && [10996, 25008].includes(value.error_code ?? 0))
    return "f118.failure_copy_details_missing";
  if (kind === "metadata_schema_change" && value.error_code === 10998)
    return "f118.failure_metadata_details_missing";
  return value.error_code ? `api_errors:${value.error_code}` : undefined;
}
