import { createDebugEventDecoder, getRobotDebugStatus } from "@/controllers/API/eplusDebug";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/controllers/request", () => ({ default: mocks }));
afterEach(() => { vi.unstubAllEnvs(); vi.clearAllMocks(); });

describe("robot debug transport", () => {
  it("does not probe when disabled", async () => {
    vi.stubEnv("VITE_EPLUS_DEBUG_ENABLED", "false");
    expect(await getRobotDebugStatus()).toBe(false);
    expect(mocks.get).not.toHaveBeenCalled();
  });
  it("hides the optional entry for rejected authorization or absent service", async () => {
    vi.stubEnv("VITE_EPLUS_DEBUG_ENABLED", "true");
    mocks.get.mockRejectedValue(new Error("unavailable"));
    expect(await getRobotDebugStatus()).toBe(false);
  });
  it("handles arbitrary fragments, unicode, CRLF and multiple data lines", () => {
    const received: unknown[] = [];
    const parser = createDebugEventDecoder(event => received.push(event));
    const wire = 'data: {"run_id":"r","seq":1,"type":"answer_delta",\r\ndata: "data":{"text":"知识"}}\r\n\r\ndata: {"run_id":"r","seq":2,"type":"completed","data":{"tool_call_count":0}}\n\n';
    for (const char of wire) parser.push(char);
    parser.finish();
    expect(received).toHaveLength(2);
    expect(received[0]).toMatchObject({ data: { text: "知识" } });
  });
  it("rejects missing terminal, changed run ID and replayed sequence", () => {
    const frame = 'data: {"run_id":"r","seq":1,"type":"context","data":{}}\n\n';
    const parser = createDebugEventDecoder(() => undefined);
    parser.push(frame);
    expect(() => parser.finish()).toThrow();
    expect(() => parser.push(frame)).toThrow();
    const changed = createDebugEventDecoder(() => undefined);
    changed.push(frame);
    expect(() => changed.push('data: {"run_id":"other","seq":2,"type":"context","data":{}}\n\n')).toThrow();
  });
});
