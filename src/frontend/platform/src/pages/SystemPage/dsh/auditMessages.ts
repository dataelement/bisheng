import type { AuditBodyFrame } from "@/types/dshModelAudit";

export type AuditText = { parts: string[]; length: number };
export type AuditToolCall = {
  index: number;
  id: string;
  name: AuditText;
  arguments: AuditText;
};
export type AuditMessage = {
  type: "message";
  key: number;
  channel: "input" | "output";
  role: string;
  name?: string;
  toolCallId?: string;
  content: { kind: "text" | "image" | "data"; text: AuditText }[];
  reasoning: AuditText;
  tools: AuditToolCall[];
  incomplete: boolean;
  unparsed: boolean;
};
export type AuditMessageEntry = AuditMessage | { type: "gap"; key: number };
type ObjectValue = Record<string, unknown>;
type PartFrame = Extract<AuditBodyFrame, { type: "part" }>;

const object = (value: unknown): value is ObjectValue =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const text = (): AuditText => ({ parts: [], length: 0 });
function append(target: AuditText, value: unknown) {
  if (typeof value !== "string" || !value) return;
  target.parts.push(value);
  target.length += value.length;
}

// Slice only the displayed page, without repeatedly joining the whole response.
export function auditTextPage(
  value: AuditText,
  start: number,
  length: number,
): string {
  const pieces: string[] = [];
  let offset = 0;
  for (const part of value.parts) {
    if (offset + part.length > start)
      pieces.push(
        part.slice(Math.max(0, start - offset), start + length - offset),
      );
    offset += part.length;
    if (offset >= start + length) break;
  }
  return pieces.join("");
}

export class AuditMessageAssembler {
  readonly entries: AuditMessageEntry[] = [];
  partial = false;
  private size = 0;
  private pending?: {
    channel: PartFrame["channel"];
    index: number;
    parts: string[];
    broken: boolean;
  };
  private reply?: AuditMessage;
  private key = 0;

  accept(frame: AuditBodyFrame) {
    if (frame.type === "meta" || frame.type === "end") {
      this.partial ||= frame.content_state === "PARTIAL";
      if (frame.type === "end") this.finish();
    } else if (frame.type === "part") {
      this.size += frame.fragment.length;
      if (this.size > 20 * 1024 * 1024)
        throw new Error("Display budget exceeded");
      if (
        this.pending &&
        (this.pending.channel !== frame.channel ||
          this.pending.index !== frame.unit_index)
      )
        this.flush();
      this.pending ??= {
        channel: frame.channel,
        index: frame.unit_index,
        parts: [],
        broken: false,
      };
      this.pending.parts.push(frame.fragment);
    } else if (frame.type === "gap") {
      this.partial = true;
      if (
        this.pending?.channel === frame.channel &&
        this.pending.index === frame.unit_index
      )
        this.pending.broken = true;
      else {
        this.flush();
        this.pending = {
          channel: frame.channel,
          index: frame.unit_index,
          parts: [],
          broken: true,
        };
      }
      if (this.reply) this.reply.incomplete = true;
      this.reply = undefined;
      this.entries.push({ type: "gap", key: this.key++ });
    }
  }

  finish(interrupted = false) {
    this.flush(interrupted);
    if (interrupted) {
      if (this.reply) this.reply.incomplete = true;
    }
  }

  private message(channel: PartFrame["channel"], role: string): AuditMessage {
    const message: AuditMessage = {
      type: "message",
      key: this.key++,
      channel,
      role,
      content: [],
      reasoning: text(),
      tools: [],
      incomplete: false,
      unparsed: false,
    };
    this.entries.push(message);
    return message;
  }

  private content(message: AuditMessage, value: unknown) {
    if (typeof value === "string") {
      let block = message.content.at(-1);
      if (block?.kind !== "text") {
        block = { kind: "text", text: text() };
        message.content.push(block);
      }
      append(block.text, value);
    } else if (Array.isArray(value)) {
      for (const part of value) {
        if (
          object(part) &&
          part.type === "text" &&
          typeof part.text === "string"
        )
          this.content(message, part.text);
        else {
          const block = {
            kind:
              object(part) && part.type === "image_url"
                ? ("image" as const)
                : ("data" as const),
            text: text(),
          };
          append(block.text, JSON.stringify(part, null, 2));
          message.content.push(block);
        }
      }
    } else if (value !== null && value !== undefined) {
      const block = { kind: "data" as const, text: text() };
      append(block.text, JSON.stringify(value, null, 2));
      message.content.push(block);
    }
  }

  private tools(message: AuditMessage, value: unknown, streaming: boolean) {
    if (!Array.isArray(value)) return;
    value.forEach((call: unknown, position) => {
      if (!object(call)) return;
      const index =
        streaming && Number.isSafeInteger(call.index)
          ? Number(call.index)
          : position;
      let tool = message.tools.find((item) => item.index === index);
      if (!tool) {
        tool = { index, id: "", name: text(), arguments: text() };
        message.tools.push(tool);
      }
      if (typeof call.id === "string") tool.id = call.id;
      if (object(call.function)) {
        append(tool.name, call.function.name);
        append(tool.arguments, call.function.arguments);
      }
    });
    message.tools.sort((a, b) => a.index - b.index);
  }

  private flush(interrupted = false) {
    const unit = this.pending;
    if (!unit) return;
    this.pending = undefined;
    const raw = unit.parts.join("");
    let value: unknown;
    try {
      value = JSON.parse(raw);
    } catch {
      value = undefined;
    }
    if (unit.broken || !object(value)) {
      this.reply = undefined;
      const message = this.message(unit.channel, "unknown");
      message.unparsed = true;
      message.incomplete = unit.broken || interrupted;
      message.content.push({
        kind: "data",
        text: { parts: unit.parts, length: raw.length },
      });
      return;
    }
    // Unit zero contains invocation settings, not a chat message. Keep it in storage only.
    if (
      unit.channel === "input" &&
      unit.index === 0 &&
      object(value.parameters) &&
      !value.role
    )
      return;
    if (unit.channel === "output" && object(value.delta)) {
      const message = (this.reply ??= this.message("output", "assistant"));
      this.content(message, value.delta.content);
      append(message.reasoning, value.delta.reasoning_content);
      this.tools(message, value.delta.tool_calls, true);
      message.incomplete ||= interrupted;
    } else if (
      unit.channel === "output" &&
      "finish_reason" in value &&
      !value.role
    ) {
      this.reply = undefined;
    } else if (typeof value.role === "string") {
      const message = this.message(unit.channel, value.role);
      message.name = typeof value.name === "string" ? value.name : undefined;
      message.toolCallId =
        typeof value.tool_call_id === "string" ? value.tool_call_id : undefined;
      this.content(message, value.content);
      append(message.reasoning, value.reasoning_content);
      this.tools(message, value.tool_calls, false);
      message.incomplete = interrupted;
      this.reply = undefined;
    } else {
      const message = this.message(unit.channel, "unknown");
      message.unparsed = true;
      this.content(message, raw);
      this.reply = undefined;
    }
  }
}
