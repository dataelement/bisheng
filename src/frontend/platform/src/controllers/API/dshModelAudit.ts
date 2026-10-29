import request from "@/controllers/request";
import { contentSafetyStates } from "@/types/dshContentSafety";
import { createDshOperationId } from "@/util/dshOperationId";
import { requestStream } from "@/controllers/requestStream";
import type {
  AuditBodyFrame,
  AuditMode,
  AuditModeSnapshot,
  ModelAuditPage,
  ModelAuditQuery,
  MissingModelAudit,
  ModelAuditRecord,
  AuditUserPage,
  AuditModelOption,
  AuditGroupPage,
  AuditQueryReadiness,
  AuditTreePage,
} from "@/types/dshModelAudit";

const base = "/api/v1/dsh/admin/model-audit";
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const nonnegative = (value: unknown) =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= 0;

function validSafetySummary(value: unknown): boolean {
  if (!object(value)) return false;
  return (
    ["has_sensitive_hit", "safety_ready"].every(
      (key) => value[key] === undefined || typeof value[key] === "boolean",
    ) &&
    ["sensitive_hit_count", "matching_sensitive_hit_count"].every(
      (key) =>
        value[key] === undefined ||
        value[key] === null ||
        nonnegative(value[key]),
    )
  );
}

function validSafetyMetadata(value: unknown): boolean {
  if (!object(value) || !validSafetySummary(value)) return false;
  // Older backends omit these fields. Absence stays unknown, never PASSED or false.
  if (
    value.content_safety_state !== undefined &&
    !contentSafetyStates.some((state) => state === value.content_safety_state)
  )
    return false;
  if (
    value.details_status !== undefined &&
    !["AVAILABLE", "PENDING", "PURGED", "UNREPORTED"].some(
      (state) => state === value.details_status,
    )
  )
    return false;
  if (
    value.record_origin !== undefined &&
    value.record_origin !== "MODEL" &&
    value.record_origin !== "EXTERNAL_SAFETY"
  )
    return false;
  if (
    ["input_sensitive_hit", "output_sensitive_hit"].some(
      (key) => value[key] !== undefined && typeof value[key] !== "boolean",
    )
  )
    return false;
  if (
    value.model_entered !== undefined &&
    value.model_entered !== null &&
    typeof value.model_entered !== "boolean"
  )
    return false;
  if (
    value.policy_version !== undefined &&
    value.policy_version !== null &&
    !nonnegative(value.policy_version)
  )
    return false;
  if (
    [
      "source_id",
      "gateway_request_id",
      "session_id",
      "model_started_at",
      "builtin_digest",
      "safety_observed_at",
    ].some(
      (key) =>
        value[key] !== undefined &&
        value[key] !== null &&
        typeof value[key] !== "string",
    )
  )
    return false;
  const states = value.stage_results,
    versions = value.stage_versions;
  if (
    states !== undefined &&
    (!object(states) ||
      !["input", "output"].every((stage) =>
        contentSafetyStates.some((state) => state === states[stage]),
      ))
  )
    return false;
  if (
    versions !== undefined &&
    (!object(versions) ||
      !["input", "output"].every((stage) => nonnegative(versions[stage])))
  )
    return false;
  return (
    !object(states) ||
    !object(versions) ||
    ["input", "output"].every(
      (stage) => (states[stage] === "UNREPORTED") === (versions[stage] === 0),
    )
  );
}

function validSafetyProgress(value: unknown): boolean {
  return (
    object(value) &&
    (value.safety_ready === undefined ||
      typeof value.safety_ready === "boolean") &&
    (value.safety_summary_version === undefined ||
      nonnegative(value.safety_summary_version)) &&
    (value.safety_summary_as_of === undefined ||
      value.safety_summary_as_of === null ||
      typeof value.safety_summary_as_of === "string")
  );
}

function validTreeSafety(node: AuditTreePage["items"][number]): boolean {
  return (
    validSafetySummary(node) &&
    validSafetySummary(node.own_summary) &&
    validSafetySummary(node.branch_summary)
  );
}
export async function getAuditTree(
  query: ModelAuditQuery,
  signal?: AbortSignal,
  parentKey?: string,
  generation?: string,
): Promise<AuditTreePage> {
  const url =
    base +
    "/conversation-tree" +
    (parentKey ? "/" + encodeURIComponent(parentKey) + "/children" : "");
  const result: AuditTreePage = await request.get(url, {
    params: { ...groupQuery(query), generation },
    signal,
  });
  if (
    !result ||
    !Array.isArray(result.items) ||
    result.items.length > query.limit ||
    !result.items.every(validSafetySummary) ||
    !validSafetyProgress(result.progress) ||
    (result.next_cursor !== null &&
      (typeof result.next_cursor !== "string" ||
        result.next_cursor.length > 2048)) ||
    result.items.some(
      (node) =>
        !node ||
        !/^[a-f0-9]{64}$/.test(node.conversation_key) ||
        !/^[a-f0-9-]{36}$/.test(node.generation) ||
        !node.own_summary ||
        !node.branch_summary ||
        !validTreeSafety(node) ||
        !["SELF", "DESCENDANT", "BOTH"].includes(node.match_scope),
    )
  ) {
    throw new Error("Invalid audit tree page");
  }
  return result;
}

export async function getAuditTreeLocation(
  key: string,
  tenantId?: number,
  signal?: AbortSignal,
  generation?: string,
): Promise<Pick<AuditTreePage, "items" | "progress">> {
  const result: Pick<AuditTreePage, "items" | "progress"> = await request.get(
    base + "/conversation-tree/" + encodeURIComponent(key) + "/location",
    {
      params: { tenant_id: tenantId, generation },
      signal,
    },
  );
  if (
    !result ||
    !Array.isArray(result.items) ||
    result.items.length > 33 ||
    !validSafetyProgress(result.progress) ||
    !result.items.every(validTreeSafety)
  )
    throw new Error("Invalid audit tree location");
  return result;
}
export async function getAuditReadiness(
  tenantId?: number,
  signal?: AbortSignal,
): Promise<AuditQueryReadiness> {
  const result: AuditQueryReadiness = await request.get(
    base + "/query-readiness",
    {
      params: { tenant_id: tenantId },
      signal,
    },
  );
  if (!validSafetyProgress(result))
    throw new Error("Invalid audit query readiness");
  return result;
}
function groupQuery(query: ModelAuditQuery) {
  const {
    tenant_id,
    user_id,
    request_id,
    conversation_id,
    model_name,
    audit_status,
    has_sensitive_hit,
    sensitive_direction,
    content_safety_state,
    start_at,
    end_at,
    cursor,
    limit,
  } = query;
  return {
    tenant_id,
    user_id,
    request_id,
    conversation_id,
    model_name,
    audit_status,
    has_sensitive_hit,
    sensitive_direction,
    content_safety_state,
    start_at,
    end_at,
    cursor,
    limit,
  };
}
export async function getAuditGroups(
  query: ModelAuditQuery,
  signal?: AbortSignal,
): Promise<AuditGroupPage> {
  const result: AuditGroupPage = await request.get(
    base + "/conversation-groups",
    { params: groupQuery(query), signal },
  );
  if (
    !result ||
    !Array.isArray(result.items) ||
    result.items.length > query.limit ||
    !result.items.every(validSafetySummary) ||
    !validSafetyProgress(result.progress) ||
    (result.next_cursor !== null && typeof result.next_cursor !== "string")
  )
    throw new Error("Invalid audit group page");
  return result;
}
export async function getAuditGroupRequests(
  key: string,
  query: ModelAuditQuery,
  signal?: AbortSignal,
): Promise<ModelAuditPage> {
  const result: ModelAuditPage = await request.get(
    base + "/conversation-groups/" + encodeURIComponent(key) + "/requests",
    { params: groupQuery(query), signal },
  );
  if (
    !result ||
    !Array.isArray(result.items) ||
    result.items.length > query.limit ||
    !result.items.every(validSafetyMetadata) ||
    (result.next_cursor !== null && typeof result.next_cursor !== "string")
  )
    throw new Error("Invalid audit group requests");
  return result;
}
export async function getAuditParent(
  requestId: string,
  tenantId?: number,
  signal?: AbortSignal,
): Promise<
  | { status: "AVAILABLE"; user_id: number; conversation_id: string }
  | { status: "NOT_PROVIDED" | "UNAVAILABLE" }
> {
  return await request.get(
    base +
      "/requests/" +
      encodeURIComponent(requestId) +
      "/parent-conversation",
    {
      params: { tenant_id: tenantId },
      signal,
    },
  );
}
export async function getAuditModels(
  query: {
    tenant_id?: number;
    page: number;
    page_size: number;
    keyword?: string;
  },
  signal?: AbortSignal,
): Promise<{ data: AuditModelOption[]; total: number }> {
  return await request.get(base + "/models", { params: query, signal });
}

export async function getAuditUsers(
  query: {
    tenant_id?: number;
    page: number;
    page_size: number;
    keyword?: string;
  },
  signal?: AbortSignal,
): Promise<AuditUserPage> {
  return await request.get(base + "/users", { params: query, signal });
}

export async function getModelAuditDetail(
  requestId: string,
  tenantId?: number,
  signal?: AbortSignal,
): Promise<ModelAuditRecord | MissingModelAudit> {
  const result: ModelAuditRecord | MissingModelAudit = await request.get(
    base + "/requests/" + encodeURIComponent(requestId),
    { params: { tenant_id: tenantId }, signal },
  );
  if (
    !object(result) ||
    (!("audit_record_missing" in result) && !validSafetyMetadata(result))
  )
    throw new Error("Invalid audit request detail");
  return result;
}
export async function getModelAudit(
  query: ModelAuditQuery,
  signal?: AbortSignal,
): Promise<ModelAuditPage> {
  const page: ModelAuditPage = await request.get(base + "/requests", {
    params: query,
    signal,
  });
  if (
    !page ||
    !Array.isArray(page.items) ||
    page.items.length > query.limit ||
    !page.items.every(validSafetyMetadata) ||
    (page.next_cursor !== null && typeof page.next_cursor !== "string")
  )
    throw new Error("Invalid audit page");
  return page;
}
export async function getAuditMode(
  tenantId?: number,
  signal?: AbortSignal,
): Promise<AuditModeSnapshot> {
  return await request.get(base + "/settings", {
    params: { tenant_id: tenantId },
    signal,
  });
}
export async function saveAuditMode(
  tenantId: number,
  snapshot: AuditModeSnapshot,
  mode: AuditMode,
): Promise<AuditModeSnapshot> {
  return await request.put(base + "/settings/" + tenantId, {
    operation_id: createDshOperationId(),
    expected_version: snapshot.version,
    mode,
  });
}

export async function* readAuditBody(
  requestId: string,
  tenantId?: number,
  signal?: AbortSignal,
): AsyncGenerator<AuditBodyFrame> {
  const query =
    "?include_message_sources=true" +
    (tenantId ? "&tenant_id=" + tenantId : "");
  const body = await requestStream(
    base +
      "/requests/" +
      encodeURIComponent(requestId) +
      "/body-access" +
      query,
    signal,
  );
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let buffer = "";
  let seq = -1;
  let meta = false;
  let ended = false;
  let errored = false;
  let annotations = false;
  function parse(line: string): AuditBodyFrame {
    const frame = JSON.parse(line) as AuditBodyFrame;
    if (!frame || typeof frame !== "object" || ended || errored)
      throw new Error("Invalid audit frame");
    if (frame.type === "meta") {
      if (
        meta ||
        frame.request_id !== requestId ||
        frame.encoding_version !== 1
      )
        throw new Error("Invalid audit identity");
      meta = true;
    } else if (!meta) throw new Error("Missing audit metadata");
    else if (frame.type === "annotations") {
      const indexSet = new Set<number>();
      const validIdentifier = (value: unknown, max: number) =>
        typeof value === "string" &&
        value.length <= max &&
        /^[A-Za-z0-9]/.test(value) &&
        !/[^A-Za-z0-9._:/-]/.test(value);
      const valid =
        !annotations &&
        seq === -1 &&
        line.length <= 16384 &&
        [
          "NOT_CAPTURED",
          "NOT_PROVIDED",
          "PENDING",
          "AVAILABLE",
          "PARTIAL",
          "INVALID",
          "UNAVAILABLE",
        ].includes(frame.message_sources_status) &&
        Array.isArray(frame.items) &&
        frame.items.length <= 128 &&
        frame.items.every((item) => {
          if (
            !item ||
            !Number.isSafeInteger(item.message_index) ||
            item.message_index < 0 ||
            indexSet.has(item.message_index)
          )
            return false;
          indexSet.add(item.message_index);
          return (
            Array.isArray(item.sources) &&
            item.sources.length > 0 &&
            item.sources.length <= 4 &&
            item.sources.every(
              (source) =>
                source &&
                validIdentifier(source.kind, 64) &&
                (source.form === undefined || validIdentifier(source.form, 32)),
            )
          );
        });
      annotations = true;
      if (!valid)
        return {
          type: "annotations",
          message_sources_status: "UNAVAILABLE",
          items: [],
        };
    } else if (frame.type === "part") {
      if (
        frame.seq !== seq + 1 ||
        !["input", "output"].includes(frame.channel) ||
        !Number.isSafeInteger(frame.unit_index) ||
        frame.unit_index < 0 ||
        typeof frame.fragment !== "string"
      )
        throw new Error("Invalid audit sequence");
      seq = frame.seq;
    } else if (frame.type === "end") {
      if (frame.last_seq !== seq || frame.transfer_status !== "COMPLETED")
        throw new Error("Incomplete audit transfer");
      ended = true;
    } else if (frame.type === "error") errored = true;
    else if (frame.type !== "gap") throw new Error("Unknown audit frame");
    return frame;
  }
  try {
    while (true) {
      const next = await reader.read();
      buffer += next.done
        ? decoder.decode()
        : decoder.decode(next.value, { stream: true });
      let end = buffer.indexOf("\n");
      while (end >= 0) {
        if (end > 262144) throw new Error("Audit frame exceeds limit");
        const line = buffer.slice(0, end);
        buffer = buffer.slice(end + 1);
        if (line) yield parse(line);
        end = buffer.indexOf("\n");
      }
      if (buffer.length > 262144) throw new Error("Audit frame exceeds limit");
      if (next.done) break;
    }
    if (buffer || !ended || errored)
      throw new Error("Audit transfer interrupted");
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
}
