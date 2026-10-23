export const contentSafetyStates = [
  "PASSED",
  "BLOCKED",
  "ERROR",
  "DISABLED",
  "NOT_APPLICABLE",
  "UNREPORTED",
] as const;

export type ContentSafetyState = (typeof contentSafetyStates)[number];
export type SensitiveDirection = "INPUT" | "OUTPUT" | "BOTH";
export type SafetyDetailsStatus = "AVAILABLE" | "PENDING" | "PURGED" | "UNREPORTED";
export type SafetyStageResults = Record<"input" | "output", ContentSafetyState>;
export type SafetyStageVersions = Record<"input" | "output", number>;
export type SafetyDrainStatus =
  | "NOT_REQUIRED"
  | "RUNNING"
  | "FINISHED"
  | "TIMED_OUT"
  | "LIMITED"
  | "DISCONNECTED";

export type DshSafetyLimits = {
  custom_words_max_bytes: number;
  effective_words_max_count: number;
  effective_words_max_bytes: number;
  word_max_codepoints: number;
  request_max_bytes: number;
  response_max_bytes: number;
  event_max_bytes: number;
  rule_refs_max_count: number;
};

export type DshSensitivePolicy = {
  version: number;
  enabled: boolean;
  input_enabled: boolean;
  output_enabled: boolean;
  words_types: string[];
  custom_words: string;
  auto_reply: string;
  builtin_digest: string;
  effective_word_count: number;
  limits: DshSafetyLimits;
};

export type DshSensitivePolicyCommand = Pick<
  DshSensitivePolicy,
  | "enabled"
  | "input_enabled"
  | "output_enabled"
  | "words_types"
  | "custom_words"
  | "auto_reply"
> & { expected_version: number };

export type DshSensitivePolicySaved = DshSensitivePolicy & {
  effective_within_seconds: number;
};

export type DshSafetyCapabilities = {
  available: boolean;
  enabled: boolean;
  configuration_ready: boolean;
  builtin_digest: string | null;
  limits: DshSafetyLimits;
};

export type SafetyConversation = {
  conversation_id?: string | null;
  request_kind?: "chat" | "compaction" | "session-title" | null;
  session_origin?: "main" | "subagent" | null;
  parent_conversation_id?: string | null;
};

// Identity IDs are decimal strings to preserve int64 precision across runtimes.
export type ContentSafetyEvent = {
  schema_version: 1;
  source_id: string;
  event_id: string;
  gateway_request_id: string;
  backend_request_id: string | null;
  tenant_id: string;
  user_id: string;
  model_id: string;
  session_id: string | null;
  protocol: "CHAT" | "RESPONSES";
  event_kind: "DECISION" | "FINAL" | "DRAIN";
  event_version: number;
  request_started_at: string;
  occurred_at: string;
  stage_results: SafetyStageResults;
  stage_versions: SafetyStageVersions;
  policy_version: number;
  builtin_digest: string;
  hit_count: number;
  hit_count_truncated: boolean;
  rule_refs: string[];
  forwarded: boolean;
  drain_status: SafetyDrainStatus;
  conversation: SafetyConversation | null;
};

// Query metadata excludes the transport identity envelope and raw model content.
export type ContentSafetyEventMetadata = Omit<ContentSafetyEvent, "tenant_id"> & {
  association_status: "ASSOCIATED" | "UNASSOCIATED";
  audit_request_id: string | null;
  received_at: string;
};

export type ContentSafetyEventPage = {
  items: ContentSafetyEventMetadata[];
  next_cursor: string | null;
  details_status: SafetyDetailsStatus;
};

export type ContentSafetyEventQuery = {
  tenant_id?: number;
  user_id?: number;
  model_id?: number;
  start_at?: string;
  end_at?: string;
  association_status?: "UNASSOCIATED";
  gateway_request_id?: string;
  backend_request_id?: string;
  cursor?: string;
  limit: number;
};
