import type { AuditBodyFrame } from "@/types/dshModelAudit";
import { describe, expect, it } from "vitest";
import {
  AuditMessageAssembler,
  auditTextPage,
  type AuditMessage,
} from "./auditMessages";

function add(
  assembler: AuditMessageAssembler,
  channel: "input" | "output",
  index: number,
  value: unknown,
  split = 9,
) {
  const raw = JSON.stringify(value);
  for (let offset = 0; offset < raw.length; offset += split)
    assembler.accept({
      type: "part",
      seq: 0,
      channel,
      unit_index: index,
      fragment: raw.slice(offset, offset + split),
    });
}
const messages = (assembler: AuditMessageAssembler) =>
  assembler.entries.filter(
    (entry): entry is AuditMessage => entry.type === "message",
  );

describe("request-scoped audit message assembly", () => {
  it("reassembles split JSON, hides only the parameters unit and preserves ordered message roles", () => {
    const assembler = new AuditMessageAssembler();
    add(assembler, "input", 0, {
      parameters: { model: "secret-model-config" },
      tools: [],
    });
    ["system", "developer", "user", "assistant", "tool"].forEach(
      (role, index) =>
        add(assembler, "input", index + 1, {
          role,
          content: "line one\nline two " + index,
          tool_call_id: role === "tool" ? "call-1" : undefined,
        }),
    );
    assembler.finish();
    expect(messages(assembler).map((message) => message.role)).toEqual([
      "system",
      "developer",
      "user",
      "assistant",
      "tool",
    ]);
    expect(messages(assembler)[0].content[0].text.parts.join("")).toBe(
      "line one\nline two 0",
    );
    expect(messages(assembler).at(-1)?.toolCallId).toBe("call-1");
    expect(JSON.stringify(assembler.entries)).not.toContain(
      "secret-model-config",
    );
  });

  it("merges thousands of deltas into one assistant message, keeping reasoning separate", () => {
    const assembler = new AuditMessageAssembler();
    add(assembler, "output", 0, { delta: { reasoning_content: "" } });
    add(assembler, "output", 1, { delta: { reasoning_content: "Think " } });
    add(assembler, "output", 2, { delta: { reasoning_content: "carefully." } });
    for (let index = 3; index < 2003; index++)
      add(assembler, "output", index, { delta: { content: "a" } });
    add(assembler, "output", 2003, { finish_reason: "stop" });
    assembler.finish();
    expect(messages(assembler)).toHaveLength(1);
    const [reply] = messages(assembler);
    expect(reply.reasoning.parts.join("")).toBe("Think carefully.");
    expect(reply.content[0].text.parts.join("")).toBe("a".repeat(2000));
    expect(reply.content[0].text.parts).toHaveLength(2000);
  });

  it("keeps historical assistant messages separate from this request's output and handles nonstream output", () => {
    const assembler = new AuditMessageAssembler();
    add(assembler, "input", 0, { role: "assistant", content: "old response" });
    add(assembler, "output", 0, {
      role: "assistant",
      content: "current response",
      reasoning_content: "one thought",
    });
    assembler.finish();
    expect(messages(assembler)).toHaveLength(2);
    expect(messages(assembler).map((message) => message.channel)).toEqual([
      "input",
      "output",
    ]);
    expect(messages(assembler)[1].reasoning.parts.join("")).toBe("one thought");
  });

  it("merges parallel tool call fragments by index rather than conflating them", () => {
    const assembler = new AuditMessageAssembler();
    add(assembler, "output", 0, {
      delta: {
        tool_calls: [
          {
            index: 1,
            id: "call-b",
            function: { name: "web_", arguments: '{"q":' },
          },
          {
            index: 0,
            id: "call-a",
            function: { name: "file", arguments: "{" },
          },
        ],
      },
    });
    add(assembler, "output", 1, {
      delta: {
        tool_calls: [
          { index: 1, function: { name: "search", arguments: '"query"}' } },
          { index: 0, function: { arguments: "}" } },
        ],
      },
    });
    assembler.finish();
    const [reply] = messages(assembler);
    expect(
      reply.tools.map((call) => [
        call.id,
        call.name.parts.join(""),
        call.arguments.parts.join(""),
      ]),
    ).toEqual([
      ["call-a", "file", "{}"],
      ["call-b", "web_search", '{"q":"query"}'],
    ]);
  });

  it("preserves multimodal ordering without dereferencing image URLs", () => {
    const assembler = new AuditMessageAssembler();
    add(assembler, "input", 1, {
      role: "user",
      content: [
        { type: "text", text: "Before" },
        { type: "image_url", image_url: { url: "https://untrusted/image" } },
        { type: "text", text: "After" },
      ],
    });
    assembler.finish();
    expect(messages(assembler)[0].content.map((block) => block.kind)).toEqual([
      "text",
      "image",
      "text",
    ]);
    expect(messages(assembler)[0].content[1].text.parts.join("")).toContain(
      "https://untrusted/image",
    );
  });

  it("does not silently join replies across missing units or treat broken JSON as a complete message", () => {
    const assembler = new AuditMessageAssembler();
    add(assembler, "output", 0, { delta: { content: "before" } });
    assembler.accept({
      type: "gap",
      channel: "output",
      unit_index: 2,
      stored_sequence: 3,
    });
    add(assembler, "output", 2, { delta: { content: "damaged" } });
    add(assembler, "output", 3, { delta: { content: "after" } });
    assembler.finish(true);
    expect(assembler.partial).toBe(true);
    expect(assembler.entries.some((entry) => entry.type === "gap")).toBe(true);
    expect(messages(assembler)).toHaveLength(3);
    expect(messages(assembler)[0].incomplete).toBe(true);
    expect(messages(assembler)[1].unparsed).toBe(true);
    expect(messages(assembler)[2].incomplete).toBe(true);
    expect(messages(assembler)[2].content[0].text.parts.join("")).toBe("after");
  });

  it("records partial storage separately from successful transmission", () => {
    const assembler = new AuditMessageAssembler();
    assembler.accept({
      type: "meta",
      request_id: "request",
      encoding_version: 1,
      content_state: "PARTIAL",
    });
    add(assembler, "input", 1, { role: "user", content: "saved" });
    assembler.accept({
      type: "end",
      last_seq: 0,
      content_state: "PARTIAL",
      transfer_status: "COMPLETED",
    });
    expect(assembler.partial).toBe(true);
    expect(messages(assembler)[0].content[0].text.parts.join("")).toBe("saved");
  });

  it("does not call metadata-only records or browser transfer interruptions missing storage", () => {
    const assembler = new AuditMessageAssembler();
    assembler.accept({
      type: "meta",
      request_id: "request",
      encoding_version: 1,
      content_state: "NOT_CAPTURED",
    });
    assembler.finish();
    expect(assembler.partial).toBe(false);
    expect(assembler.entries).toHaveLength(0);
    add(assembler, "output", 0, { delta: { content: "observed" } });
    assembler.finish(true);
    expect(assembler.partial).toBe(false);
    expect(messages(assembler)[0].incomplete).toBe(true);
  });

  it("retains malformed source fragments and enforces the display budget", () => {
    const assembler = new AuditMessageAssembler();
    const frame: AuditBodyFrame = {
      type: "part",
      seq: 0,
      channel: "input",
      unit_index: 1,
      fragment: '{"role":"user","content":"truncated',
    };
    assembler.accept(frame);
    assembler.finish(true);
    expect(messages(assembler)[0].unparsed).toBe(true);
    expect(messages(assembler)[0].content[0].text.parts.join("")).toBe(
      frame.fragment,
    );
    expect(() =>
      assembler.accept({ ...frame, fragment: "x".repeat(20 * 1024 * 1024) }),
    ).toThrow("Display budget exceeded");
  });

  it("pages long text without truncation, duplication or joining all fragments", () => {
    const parts = ["abc", "de", "fghij", "klm"];
    const value = { parts, length: 13 };
    expect(auditTextPage(value, 0, 4)).toBe("abcd");
    expect(auditTextPage(value, 4, 4)).toBe("efgh");
    expect(auditTextPage(value, 8, 4)).toBe("ijkl");
    expect(auditTextPage(value, 12, 4)).toBe("m");
  });
});
