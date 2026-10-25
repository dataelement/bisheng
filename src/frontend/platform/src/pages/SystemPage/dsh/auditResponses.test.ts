import { describe, expect, it } from "vitest";
import { AuditMessageAssembler, type AuditMessage } from "./auditMessages";

function add(
  assembler: AuditMessageAssembler,
  index: number,
  value: unknown,
  channel: "input" | "output" = "output",
) {
  const raw = JSON.stringify(value);
  for (let start = 0; start < raw.length; start += 7)
    assembler.accept({
      type: "part",
      seq: 0,
      channel,
      unit_index: index,
      fragment: raw.slice(start, start + 7),
    });
}
const messages = (assembler: AuditMessageAssembler) =>
  assembler.entries.filter(
    (entry): entry is AuditMessage => entry.type === "message",
  );
const body = (message: AuditMessage) =>
  message.content
    .filter((part) => part.kind === "text")
    .map((part) => part.text.parts.join(""))
    .join("");
const reply = {
  type: "message",
  id: "msg-1",
  role: "assistant",
  status: "completed",
  content: [{ type: "output_text", text: "hello", annotations: [] }],
};
const thought = {
  type: "reasoning",
  id: "rs-1",
  summary: [{ type: "summary_text", text: "thinking" }],
  encrypted_content: "opaque-history",
};
const call = {
  type: "function_call",
  id: "fc-1",
  call_id: "call-1",
  name: "lookup",
  arguments: '{"query":"test"}',
};

describe("model audit protocol compatibility", () => {
  it("renders the actual nonstream Chat envelope rather than dropping its finish_reason", () => {
    const assembler = new AuditMessageAssembler();
    add(assembler, 0, {
      message: {
        role: "assistant",
        content: "hello",
        reasoning_content: "thinking",
        tool_calls: [
          {
            id: "call-1",
            type: "function",
            function: { name: "lookup", arguments: "{}" },
          },
        ],
      },
      finish_reason: "tool_calls",
    });
    assembler.finish();
    const [message] = messages(assembler);
    expect(messages(assembler)).toHaveLength(1);
    expect(message.role).toBe("assistant");
    expect(body(message)).toBe("hello");
    expect(message.reasoning.parts.join("")).toBe("thinking");
    expect(message.tools[0].id).toBe("call-1");
  });

  it("renders native nonstream messages, reasoning and function calls with their original identities", () => {
    const assembler = new AuditMessageAssembler();
    add(assembler, 0, {
      object: "response",
      status: "completed",
      output: [thought, call, reply],
    });
    assembler.finish();
    const result = messages(assembler);
    expect(result.map((message) => message.role)).toEqual([
      "assistant",
      "assistant",
      "assistant",
    ]);
    expect(result.every((message) => !message.unparsed)).toBe(true);
    expect(result[0].reasoning.parts.join("")).toBe("thinking");
    expect(result[0].content[0].kind).toBe("data");
    expect(result[0].content[0].text.parts.join("")).toContain(
      "opaque-history",
    );
    expect(body(result[0])).not.toContain("opaque-history");
    expect(result[1].tools[0].id).toBe("call-1");
    expect(result[1].tools[0].name.parts.join("")).toBe("lookup");
    expect(result[1].tools[0].arguments.parts.join("")).toBe(call.arguments);
    expect(body(result[2])).toBe("hello");
  });

  it("keeps typed native input provenance, tool results and image ordering", () => {
    const assembler = new AuditMessageAssembler();
    assembler.accept({
      type: "annotations",
      message_sources_status: "AVAILABLE",
      items: [{ message_index: 2, sources: [{ kind: "tool" }] }],
    });
    add(assembler, 0, { parameters: { model: "private-config" } }, "input");
    add(assembler, 1, thought, "input");
    add(assembler, 2, call, "input");
    add(
      assembler,
      3,
      { type: "function_call_output", call_id: "call-1", output: "tool reply" },
      "input",
    );
    add(
      assembler,
      4,
      {
        type: "message",
        role: "user",
        content: [
          { type: "input_text", text: "before" },
          { type: "input_image", image_url: "https://untrusted.invalid/image" },
          { type: "input_text", text: "after" },
        ],
      },
      "input",
    );
    assembler.finish();
    const result = messages(assembler);
    expect(result).toHaveLength(4);
    expect(result[2].role).toBe("tool");
    expect(result[2].toolCallId).toBe("call-1");
    expect(result[2].sources).toEqual([{ kind: "tool" }]);
    expect(body(result[2])).toBe("tool reply");
    expect(result[3].content.map((part) => part.kind)).toEqual([
      "text",
      "image",
      "text",
    ]);
    expect(body(result[3])).toBe("beforeafter");
    expect(JSON.stringify(result)).not.toContain("private-config");
  });

  it("does not duplicate deltas when done events and the terminal response repeat final snapshots", () => {
    const assembler = new AuditMessageAssembler();
    const events = [
      {
        type: "response.created",
        response: { output: [], status: "in_progress" },
      },
      {
        type: "response.output_item.added",
        output_index: 0,
        item: { ...thought, summary: [], encrypted_content: null },
      },
      {
        type: "response.reasoning_summary_text.delta",
        output_index: 0,
        summary_index: 0,
        delta: "think",
      },
      {
        type: "response.reasoning_summary_text.delta",
        output_index: 0,
        summary_index: 0,
        delta: "ing",
      },
      {
        type: "response.reasoning_summary_text.done",
        output_index: 0,
        summary_index: 0,
        text: "thinking",
      },
      { type: "response.output_item.done", output_index: 0, item: thought },
      {
        type: "response.output_item.added",
        output_index: 1,
        item: { ...call, arguments: "" },
      },
      {
        type: "response.function_call_arguments.delta",
        output_index: 1,
        delta: '{"query":',
      },
      {
        type: "response.function_call_arguments.delta",
        output_index: 1,
        delta: '"test"}',
      },
      {
        type: "response.function_call_arguments.done",
        output_index: 1,
        arguments: call.arguments,
      },
      { type: "response.output_item.done", output_index: 1, item: call },
      {
        type: "response.output_item.added",
        output_index: 2,
        item: { ...reply, content: [], status: "in_progress" },
      },
      {
        type: "response.output_text.delta",
        output_index: 2,
        content_index: 0,
        delta: "hel",
      },
      {
        type: "response.output_text.delta",
        output_index: 2,
        content_index: 0,
        delta: "lo",
      },
      {
        type: "response.output_text.done",
        output_index: 2,
        content_index: 0,
        text: "hello",
      },
      {
        type: "response.content_part.done",
        output_index: 2,
        content_index: 0,
        part: reply.content[0],
      },
      { type: "response.output_item.done", output_index: 2, item: reply },
      {
        type: "response.completed",
        response: { status: "completed", output: [thought, call, reply] },
      },
    ];
    events.forEach((event, index) => add(assembler, index, event));
    assembler.finish();
    const result = messages(assembler);
    expect(result).toHaveLength(3);
    expect(result.every((message) => !message.unparsed)).toBe(true);
    expect(result[0].reasoning.parts.join("")).toBe("thinking");
    expect(result[1].tools[0].arguments.parts.join("")).toBe(call.arguments);
    expect(body(result[2])).toBe("hello");
  });

  it("retains thousands of native deltas and marks interrupted output without a final snapshot", () => {
    const assembler = new AuditMessageAssembler();
    for (let index = 0; index < 2000; index++)
      add(assembler, index, {
        type: "response.output_text.delta",
        output_index: 0,
        content_index: 0,
        delta: "a",
      });
    assembler.finish(true);
    const [message] = messages(assembler);
    expect(messages(assembler)).toHaveLength(1);
    expect(body(message)).toBe("a".repeat(2000));
    expect(message.content[0].text.parts).toHaveLength(2000);
    expect(message.incomplete).toBe(true);
    expect(assembler.partial).toBe(false);
  });

  it("keeps parallel function calls separate and uses done-only snapshots to recover full arguments", () => {
    const assembler = new AuditMessageAssembler();
    add(assembler, 0, {
      type: "response.output_item.added",
      output_index: 0,
      item: { ...call, arguments: "" },
    });
    add(assembler, 1, {
      type: "response.output_item.added",
      output_index: 1,
      item: { ...call, call_id: "call-2", name: "other", arguments: "" },
    });
    add(assembler, 2, {
      type: "response.function_call_arguments.delta",
      output_index: 1,
      delta: "{",
    });
    add(assembler, 3, {
      type: "response.function_call_arguments.done",
      output_index: 0,
      arguments: call.arguments,
    });
    add(assembler, 4, {
      type: "response.function_call_arguments.done",
      output_index: 1,
      arguments: "{}",
    });
    assembler.finish();
    expect(
      messages(assembler).map((message) => [
        message.tools[0].id,
        message.tools[0].arguments.parts.join(""),
      ]),
    ).toEqual([
      ["call-1", call.arguments],
      ["call-2", "{}"],
    ]);
  });

  it("reconciles distinct text and reasoning parts without concatenating their done snapshots twice", () => {
    const assembler = new AuditMessageAssembler();
    [
      {
        type: "response.reasoning_text.delta",
        output_index: 0,
        content_index: 0,
        delta: "thought",
      },
      {
        type: "response.reasoning_text.done",
        output_index: 0,
        content_index: 0,
        text: "thought",
      },
      {
        type: "response.reasoning_summary_part.done",
        output_index: 0,
        summary_index: 0,
        part: { type: "summary_text", text: "summary" },
      },
      {
        type: "response.output_text.delta",
        output_index: 1,
        content_index: 0,
        delta: "first",
      },
      {
        type: "response.output_text.delta",
        output_index: 1,
        content_index: 1,
        delta: "second",
      },
      {
        type: "response.output_text.done",
        output_index: 1,
        content_index: 0,
        text: "first",
      },
      {
        type: "response.refusal.done",
        output_index: 2,
        content_index: 0,
        refusal: "cannot comply",
      },
    ].forEach((event, index) => add(assembler, index, event));
    assembler.finish();
    const result = messages(assembler);
    expect(result[0].reasoning.parts.join("")).toBe("thoughtsummary");
    expect(body(result[1])).toBe("firstsecond");
    expect(body(result[2])).toBe("cannot comply");
  });

  it.each(["failed", "incomplete"])(
    "marks a native %s snapshot as incomplete content",
    (status) => {
      const assembler = new AuditMessageAssembler();
      add(assembler, 0, {
        type: `response.${status}`,
        response: { status, output: [reply] },
      });
      assembler.finish();
      expect(messages(assembler)[0].incomplete).toBe(true);
      expect(body(messages(assembler)[0])).toBe("hello");
    },
  );

  it("does not merge native replies across an explicit audit gap", () => {
    const assembler = new AuditMessageAssembler();
    add(assembler, 0, {
      type: "response.output_text.delta",
      output_index: 0,
      delta: "before",
    });
    assembler.accept({
      type: "gap",
      channel: "output",
      unit_index: 2,
      stored_sequence: 3,
    });
    add(assembler, 3, {
      type: "response.output_text.delta",
      output_index: 0,
      delta: "after",
    });
    assembler.finish();
    expect(assembler.partial).toBe(true);
    expect(
      messages(assembler)
        .filter((message) => !message.unparsed)
        .map(body),
    ).toEqual(["before", "after"]);
    expect(messages(assembler).some((message) => message.unparsed)).toBe(true);
    expect(messages(assembler)[0].incomplete).toBe(true);
  });

  it("preserves unsupported native output as visibly unparsed data", () => {
    const assembler = new AuditMessageAssembler();
    add(assembler, 0, {
      type: "response.future_event",
      output_index: 0,
      data: "kept",
    });
    assembler.finish();
    expect(messages(assembler)[0].unparsed).toBe(true);
    expect(body(messages(assembler)[0])).toContain("kept");
  });
});
