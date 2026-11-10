import type { AuditMessage, AuditText } from "./auditMessages";

type JsonObject = Record<string, unknown>;
type Channel = "input" | "output";
type ItemState = {
  message: AuditMessage;
  text: Map<number, AuditText>;
  reasoning: Map<string, AuditText>;
};
interface ResponsesAuditHooks {
  message: (channel: Channel, role: string, index?: number) => AuditMessage;
  content: (message: AuditMessage, value: unknown) => void;
}
const object = (value: unknown): value is JsonObject =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const text = (): AuditText => ({ parts: [], length: 0 });
function append(target: AuditText, value: unknown, replace = false) {
  if (typeof value !== "string") return;
  if (replace) {
    target.parts = [];
    target.length = 0;
  }
  if (value) {
    target.parts.push(value);
    target.length += value.length;
  }
}
const itemTypes = new Set([
  "message",
  "reasoning",
  "function_call",
  "function_call_output",
]);
const controls = new Set([
  "response.created",
  "response.in_progress",
  "response.output_text.annotation.added",
]);

/** Project native items and events without replaying final snapshots as new messages. */
export class ResponsesAuditAssembler {
  private readonly items = new Map<number, ItemState>();
  constructor(private readonly hooks: ResponsesAuditHooks) {}

  finish() {
    for (const state of this.items.values()) state.message.incomplete = true;
  }

  reset() {
    this.finish();
    this.items.clear();
  }

  private state(
    index: number,
    channel: Channel,
    role = "assistant",
    unitIndex?: number,
  ): ItemState {
    const existing = channel === "output" ? this.items.get(index) : undefined;
    if (existing) return existing;
    const state = {
      message: this.hooks.message(channel, role, unitIndex),
      text: new Map<number, AuditText>(),
      reasoning: new Map<string, AuditText>(),
    };
    if (channel === "output") this.items.set(index, state);
    return state;
  }

  private content(
    state: ItemState,
    index: number,
    value: unknown,
    replace = false,
  ) {
    let block = state.text.get(index);
    if (!block) {
      block = text();
      state.text.set(index, block);
      state.message.content.push({ kind: "text", text: block });
    }
    append(block, value, replace);
  }

  private reasoning(
    state: ItemState,
    key: string,
    value: unknown,
    replace = false,
  ) {
    let block = state.reasoning.get(key);
    if (!block) {
      block = text();
      state.reasoning.set(key, block);
    }
    append(block, value, replace);
    if (replace) {
      state.message.reasoning = {
        parts: [...state.reasoning.values()].flatMap((part) => part.parts),
        length: [...state.reasoning.values()].reduce(
          (sum, part) => sum + part.length,
          0,
        ),
      };
    } else append(state.message.reasoning, value);
  }

  private item(value: JsonObject, state: ItemState, interrupted: boolean) {
    const message = state.message;
    message.content = [];
    message.tools = [];
    message.reasoning = text();
    state.text.clear();
    state.reasoning.clear();
    message.incomplete ||= interrupted || value.status === "incomplete";
    if (value.type === "message") {
      message.role = typeof value.role === "string" ? value.role : "assistant";
      if (Array.isArray(value.content))
        value.content.forEach((part, index) => {
          if (
            object(part) &&
            ["input_text", "output_text", "refusal"].includes(String(part.type))
          )
            this.content(
              state,
              index,
              part.type === "refusal" ? part.refusal : part.text,
              true,
            );
          else this.hooks.content(message, [part]);
        });
      else this.hooks.content(message, value.content);
    } else if (value.type === "function_call") {
      const call = {
        index: 0,
        id: typeof value.call_id === "string" ? value.call_id : "",
        name: text(),
        arguments: text(),
      };
      append(call.name, value.name);
      append(call.arguments, value.arguments);
      message.tools.push(call);
    } else if (value.type === "function_call_output") {
      message.role = "tool";
      message.toolCallId =
        typeof value.call_id === "string" ? value.call_id : undefined;
      this.hooks.content(message, value.output);
    } else if (value.type === "reasoning") {
      for (const field of ["summary", "content"]) {
        const parts = value[field];
        if (Array.isArray(parts))
          parts.forEach((part, index) => {
            if (object(part))
              this.reasoning(state, `${field}:${index}`, part.text);
          });
      }
      // Opaque replay state remains inspectable as data, never as assistant prose.
      if (
        typeof value.encrypted_content === "string" &&
        value.encrypted_content
      )
        this.hooks.content(message, {
          type: "reasoning",
          encrypted_content: value.encrypted_content,
        });
    }
  }

  private snapshot(response: JsonObject, interrupted: boolean): boolean {
    if (!Array.isArray(response.output)) return false;
    if (
      !response.output.every(
        (item) => object(item) && itemTypes.has(String(item.type)),
      )
    )
      return false;
    response.output.forEach((item: JsonObject, index) =>
      this.item(item, this.state(index, "output"), interrupted),
    );
    if (
      interrupted ||
      ["failed", "incomplete"].includes(String(response.status))
    )
      this.finish();
    return true;
  }

  accept(
    value: JsonObject,
    channel: Channel,
    unitIndex: number,
    interrupted: boolean,
  ): boolean {
    const kind = String(value.type);
    if (channel === "input" && itemTypes.has(kind)) {
      this.item(
        value,
        this.state(unitIndex, channel, "assistant", unitIndex),
        interrupted,
      );
      return true;
    }
    if (channel !== "output") return false;
    if (value.object === "response") return this.snapshot(value, interrupted);
    if (
      ["response.completed", "response.failed", "response.incomplete"].includes(
        kind,
      )
    )
      return (
        object(value.response) && this.snapshot(value.response, interrupted)
      );
    if (controls.has(kind)) return true;
    if (
      !kind.startsWith("response.") ||
      !Number.isSafeInteger(value.output_index) ||
      Number(value.output_index) < 0
    )
      return false;
    const index = Number(value.output_index);
    if (
      ["response.output_item.added", "response.output_item.done"].includes(kind)
    ) {
      if (!object(value.item) || !itemTypes.has(String(value.item.type)))
        return false;
      this.item(value.item, this.state(index, channel), interrupted);
      return true;
    }
    const isContent = [
      "response.output_text.delta",
      "response.output_text.done",
      "response.refusal.delta",
      "response.refusal.done",
      "response.content_part.added",
      "response.content_part.done",
    ].includes(kind);
    const isReasoning = [
      "response.reasoning_summary_text.delta",
      "response.reasoning_summary_text.done",
      "response.reasoning_text.delta",
      "response.reasoning_text.done",
      "response.reasoning_summary_part.added",
      "response.reasoning_summary_part.done",
    ].includes(kind);
    const isArguments = [
      "response.function_call_arguments.delta",
      "response.function_call_arguments.done",
    ].includes(kind);
    if (!isContent && !isReasoning && !isArguments) return false;
    const state = this.state(index, channel);
    state.message.incomplete ||= interrupted;
    const done = kind.endsWith(".done");
    if (isContent) {
      const part = object(value.part) ? value.part : value;
      const contentIndex = Number.isSafeInteger(value.content_index)
        ? Number(value.content_index)
        : 0;
      this.content(
        state,
        contentIndex,
        kind.endsWith(".delta") ? value.delta : (part.text ?? part.refusal),
        done,
      );
    } else if (isReasoning) {
      const summary = kind.includes("summary");
      const partIndex =
        Number(summary ? value.summary_index : value.content_index) || 0;
      const part = object(value.part) ? value.part : value;
      this.reasoning(
        state,
        `${summary ? "summary" : "content"}:${partIndex}`,
        kind.endsWith(".delta") ? value.delta : part.text,
        done,
      );
    } else {
      const call = state.message.tools[0] ?? {
        index: 0,
        id: "",
        name: text(),
        arguments: text(),
      };
      if (!state.message.tools.length) state.message.tools.push(call);
      append(call.arguments, done ? value.arguments : value.delta, done);
    }
    return true;
  }
}
