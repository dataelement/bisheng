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
import { readAuditBody } from "./dshModelAudit";
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
describe("bounded audit NDJSON parser", () => {
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
