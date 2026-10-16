import request from "@/controllers/request";
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
} from "@/types/dshModelAudit";

const base = "/api/v1/dsh/admin/model-audit";
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
  return await request.get(
    base + "/requests/" + encodeURIComponent(requestId),
    { params: { tenant_id: tenantId }, signal },
  );
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
