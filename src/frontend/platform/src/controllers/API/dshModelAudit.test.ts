import { describe, expect, it, vi } from "vitest";
const state = vi.hoisted(() => ({
  stream: null as ReadableStream<Uint8Array> | null,
}));
vi.mock("@/controllers/request", () => ({
  default: { get: vi.fn(), put: vi.fn() },
}));
vi.mock("@/controllers/requestStream", () => ({
  requestStream: () => Promise.resolve(state.stream),
}));
import { getAuditModels, getAuditUsers, readAuditBody } from "./dshModelAudit";
import request from "@/controllers/request";
import type { AuditBodyFrame } from "@/types/dshModelAudit";

function source(text: string) {
  const bytes = new TextEncoder().encode(text);
  state.stream = new ReadableStream({
    start(controller) {
      for (let index = 0; index < bytes.length; index += 3)
        controller.enqueue(bytes.slice(index, index + 3));
      controller.close();
    },
  });
}
const meta = {
  type: "meta",
  request_id: "request",
  encoding_version: 1,
  content_state: "COMPLETE",
};
const part = {
  type: "part",
  seq: 0,
  channel: "input",
  unit_index: 0,
  fragment: "<script>untrusted</script>" + String.fromCodePoint(0x4f60, 0x597d),
};
const end = {
  type: "end",
  last_seq: 0,
  transfer_status: "COMPLETED",
  content_state: "COMPLETE",
};
async function collect() {
  const frames: AuditBodyFrame[] = [];
  for await (const frame of readAuditBody("request")) frames.push(frame);
  return frames;
}
it("loads audit-scoped user options with tenant, pagination, search and cancellation", async () => {
  const page = { data: [{ user_id: 20, user_name: "Alice" }], total: 1 };
  vi.mocked(request.get).mockResolvedValueOnce(page);
  const signal = new AbortController().signal;
  const query = { tenant_id: 2, page: 1, page_size: 20, keyword: "ali" };
  expect(await getAuditUsers(query, signal)).toEqual(page);
  expect(request.get).toHaveBeenCalledWith(
    "/api/v1/dsh/admin/model-audit/users",
    { params: query, signal },
  );
});
describe("bounded audit NDJSON parser", () => {
  it("loads available model IDs and names within the requested tenant scope", async () => {
    const page = { data: [{ id: 42, name: "Available model" }], total: 1 };
    vi.mocked(request.get).mockResolvedValueOnce(page);
    const signal = new AbortController().signal;
    const query = { tenant_id: 2, page: 1, page_size: 20, keyword: "Deleted" };
    expect(await getAuditModels(query, signal)).toEqual(page);
    expect(request.get).toHaveBeenLastCalledWith(
      "/api/v1/dsh/admin/model-audit/models",
      { params: query, signal },
    );
  });
  it("decodes fragmented UTF8 and validates identity, order and terminal transfer", async () => {
    source(
      [meta, part, end].map((item) => JSON.stringify(item) + "\n").join(""),
    );
    expect(await collect()).toEqual([meta, part, end]);
  });
  it.each([
    [meta, { ...part, seq: 1 }, end],
    [{ ...meta, request_id: "other" }, part, end],
    [meta, part],
    [meta, { type: "error", code: "original_unavailable" }],
  ])(
    "does not report malformed or interrupted transport as complete",
    async (...frames) => {
      source(frames.map((item) => JSON.stringify(item) + "\n").join(""));
      await expect(collect()).rejects.toThrow();
    },
  );
});
