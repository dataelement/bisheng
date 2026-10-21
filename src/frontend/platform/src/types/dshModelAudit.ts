export const modelResults = [
  "RUNNING",
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
  "UNKNOWN",
] as const;
export const responseResults = [
  "RUNNING",
  "COMPLETED",
  "ERROR",
  "INTERRUPTED",
  "UNKNOWN",
] as const;
export const settlements = [
  "PENDING",
  "SETTLED",
  "USAGE_UNKNOWN",
  "UNCERTAIN",
] as const;
export const contentStates = [
  "PENDING",
  "COMPLETE",
  "PARTIAL",
  "NOT_CAPTURED",
] as const;
export type AuditMode = "OFF" | "METADATA" | "CONTENT";
export type AuditModeSnapshot = {
  mode: AuditMode;
  version: number;
  content_available?: boolean;
};
export type AuditUserOption = { user_id: number; user_name: string };
export type AuditModelOption = { id: number; name: string };
export type AuditUserPage = { data: AuditUserOption[]; total: number };
export type ModelAuditRecord = {
  user_name?: string | null;
  audit_status?: "NORMAL" | "ABNORMAL" | null;
  status_reasons?: string[];
  status_pending?: boolean;
  request_id: string;
  user_id: number;
  model_id: number;
  model_name: string;
  provider_name: string;
  conversation_id: string | null;
  request_kind: string | null;
  session_origin?: "main" | "subagent" | null;
  parent_conversation_id?: string | null;
  context_invalid: boolean;
  association_status: "ASSOCIATED" | "UNASSOCIATED";
  effective_mode: AuditMode;
  started_at: string;
  last_write_at: string | null;
  input_units: number;
  input_bytes: number;
  output_bytes: number;
  model_result: (typeof modelResults)[number];
  response_result: (typeof responseResults)[number];
  model_error_code?: string | null;
  response_error_code?: string | null;
  usage_settlement: (typeof settlements)[number];
  content_status: (typeof contentStates)[number];
  usage: {
    input_tokens: number | null;
    output_tokens: number | null;
    total_tokens: number | null;
    status: string;
    latency_ms?: number | null;
  } | null;
};
export type ModelAuditQuery = {
  audit_status?: "NORMAL" | "ABNORMAL";
  tenant_id?: number;
  user_id?: number;
  user_keyword?: string;
  request_id?: string;
  conversation_id?: string;
  model_id?: number;
  model_name?: string;
  provider_name?: string;
  start_at?: string;
  end_at?: string;
  model_result?: (typeof modelResults)[number];
  response_result?: (typeof responseResults)[number];
  usage_settlement?: (typeof settlements)[number];
  content_status?: (typeof contentStates)[number];
  association_status?: "ASSOCIATED" | "UNASSOCIATED";
  cursor?: string;
  limit: number;
};
export type AuditQueryReadiness = {
  status_ready: boolean;
  name_ready: boolean;
  indexing_pending: boolean | null;
  hierarchy_available?: boolean;
  hierarchy_ready?: boolean;
  generation?: string | null;
  phase?: "PREPARING" | "READY" | "UPDATING" | "FAILED";
  summary_ready?: boolean;
  refresh_required?: boolean;
};
export type AuditConversation = {
  conversation_title?: string | null;
  title_event_seq?: number | null;
  user_name?: string | null;
  conversation_key: string;
  user_id: number;
  conversation_id: string;
  listed_at: string;
  last_request_at: string;
  updated_at: string;
  request_count: number;
  abnormal_count: number;
};
export type AuditGroupPage = {
  items: AuditConversation[];
  next_cursor: string | null;
  scan_limited: boolean;
  progress: AuditQueryReadiness;
};
export type AuditTreeSummary = {
  ready: boolean;
  request_count: number | null;
  abnormal_count: number | null;
  known_abnormal: boolean;
};
export type AuditTreeNode = AuditConversation & {
  generation: string;
  parent_key: string;
  root_key: string;
  relation_state:
    | "MAIN"
    | "UNKNOWN"
    | "LINKED"
    | "MISSING_PARENT"
    | "PARENT_UNAVAILABLE"
    | "SELF_REFERENCE"
    | "CYCLE"
    | "CONFLICT"
    | "DEPTH_LIMIT";
  has_children: boolean;
  match_scope: "SELF" | "DESCENDANT" | "BOTH";
  own_summary: AuditTreeSummary;
  branch_summary: AuditTreeSummary;
  summary_as_of: string | null;
};
export type AuditTreePage = Omit<AuditGroupPage, "items"> & {
  items: AuditTreeNode[];
};
export type ModelAuditPage = {
  items: ModelAuditRecord[];
  next_cursor: string | null;
  progress: {
    last_write_at: string | null;
    coverage: string;
    limitations: string[];
    pending_events?: number | null;
  };
};
export type MissingModelAudit = {
  request_id: string;
  audit_record_missing: true;
  gap: "AWAITING" | "CONFIRMED" | "DEGRADED_OFF" | "MODE_UNKNOWN" | "UNKNOWN";
};
export type AuditMessageSource = { kind: string; form?: string };
export type AuditSourceItem = {
  message_index: number;
  sources: AuditMessageSource[];
};
export type AuditBodyFrame =
  | {
      type: "annotations";
      message_sources_status: string;
      items: AuditSourceItem[];
    }
  | {
      type: "meta";
      request_id: string;
      encoding_version: number;
      content_state: string;
    }
  | {
      type: "part";
      seq: number;
      channel: "input" | "output";
      unit_index: number;
      fragment: string;
    }
  | {
      type: "gap";
      channel: "input" | "output";
      unit_index: number;
      stored_sequence: number;
    }
  | {
      type: "end";
      last_seq: number;
      content_state: string;
      transfer_status: string;
    }
  | { type: "error"; code: string };
