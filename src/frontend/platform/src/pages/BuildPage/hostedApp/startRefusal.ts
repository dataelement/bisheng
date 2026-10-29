const REASON_KEYS: Record<string, string> = {
  no_approved_version: "api_errors:appStartNoApprovedVersion",
  approval_pending: "api_errors:appStartApprovalPending",
  approval_rejected: "api_errors:appStartApprovalRejected",
  approval_withdrawn: "api_errors:appStartApprovalWithdrawn",
  approval_cancelled: "api_errors:appStartApprovalCancelled",
  approval_exception: "api_errors:appStartApprovalException",
  approval_executing: "api_errors:appStartApprovalExecuting",
  approval_execute_failed: "api_errors:appStartApprovalExecuteFailed",
  publish_failed: "api_errors:appStartPublishFailed",
  publish_preparing: "api_errors:appStartPublishPreparing",
}

export function startRefusalI18nKey(error: unknown): string | null {
  if (!error || typeof error !== "object" || !("data" in error)) return null
  const data = error.data
  if (!data || typeof data !== "object" || !("reason" in data)) return null
  return typeof data.reason === "string" ? REASON_KEYS[data.reason] ?? null : null
}
