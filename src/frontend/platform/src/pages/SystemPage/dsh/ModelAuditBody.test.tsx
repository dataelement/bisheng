import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditBodyFrame } from "@/types/dshModelAudit";

const api = vi.hoisted(() => ({ stream: vi.fn() }));
vi.mock("@/controllers/request", () => ({
  default: { get: vi.fn(), put: vi.fn() },
}));
vi.mock("@/controllers/requestStream", () => ({ requestStream: api.stream }));
import { ModelAuditBody } from "./ModelAuditBody";

function frames(
  units: { channel: "input" | "output"; value: unknown }[],
  requestId = "request",
) {
  const result: AuditBodyFrame[] = [
    {
      type: "meta",
      request_id: requestId,
      encoding_version: 1,
      content_state: "COMPLETE",
    },
  ];
  const indices = { input: 0, output: 0 };
  let seq = -1;
  for (const unit of units) {
    const index = indices[unit.channel]++;
    const raw = JSON.stringify(unit.value);
    for (let offset = 0; offset < raw.length; offset += 31)
      result.push({
        type: "part",
        seq: ++seq,
        channel: unit.channel,
        unit_index: index,
        fragment: raw.slice(offset, offset + 31),
      });
  }
  result.push({
    type: "end",
    last_seq: seq,
    content_state: "COMPLETE",
    transfer_status: "COMPLETED",
  });
  return result;
}
function source(value: AuditBodyFrame[]) {
  const bytes = new TextEncoder().encode(
    value.map((frame) => JSON.stringify(frame) + "\n").join(""),
  );
  api.stream.mockResolvedValueOnce(
    new ReadableStream({
      start(controller) {
        for (let offset = 0; offset < bytes.length; offset += 97)
          controller.enqueue(bytes.slice(offset, offset + 97));
        controller.close();
      },
    }),
  );
}
beforeEach(() => vi.clearAllMocks());

it("shows role and producer independently without calling partial sources a body gap", async () => {
  const result = frames([
    { channel: "input", value: { parameters: {} } },
    { channel: "input", value: { role: "user", content: "Synthetic context" } },
  ]);
  result.splice(1, 0, {
    type: "annotations",
    message_sources_status: "PARTIAL",
    items: [
      {
        message_index: 0,
        sources: [{ kind: "runtime-context", form: "snapshot" }],
      },
    ],
  });
  source(result);
  render(<ModelAuditBody requestId="request" />);
  expect(
    await screen.findByText("dsh.modelAuditView.sources.kinds.runtime-context"),
  ).toBeVisible();
  expect(
    screen.getByText("dsh.modelAuditView.sources.status.PARTIAL"),
  ).toBeVisible();
  expect(screen.queryByText("dsh.modelAuditView.gap")).toBeNull();
  const region = screen.getByRole("region", {
    name: "dsh.modelAuditView.message_content",
  });
  expect(region).toHaveAttribute("tabindex", "0");
  expect(region).toHaveClass("h-96", "overflow-y-auto");
  const metadata = screen
    .getByText("dsh.modelAuditView.sources.kinds.runtime-context")
    .closest("header")!;
  expect(metadata).toHaveClass("border-b", "bg-muted/50", "text-xs");
  expect(within(metadata).queryByText(/snapshot/)).toBeNull();
  expect(metadata.querySelector("[title]")).toBeNull();
  expect(metadata.closest("article")!.querySelector("details")).toBeNull();
  expect(metadata).not.toContainElement(screen.getByText("Synthetic context"));
});

it("uses readable source labels, deduplicates forms, and never exposes unknown technical kinds", async () => {
  const result = frames([
    { channel: "input", value: { parameters: {} } },
    {
      channel: "input",
      value: { role: "user", content: "Synthetic source test" },
    },
  ]);
  result.splice(1, 0, {
    type: "annotations",
    message_sources_status: "AVAILABLE",
    items: [
      {
        message_index: 0,
        sources: [
          { kind: "runtime-context", form: "snapshot" },
          { kind: "runtime-context", form: "private-technical-form" },
          { kind: "private-unknown-kind", form: "private-form" },
        ],
      },
    ],
  });
  source(result);
  render(<ModelAuditBody requestId="request" />);
  expect(
    await screen.findByText("dsh.modelAuditView.sources.kinds.runtime-context"),
  ).toBeVisible();
  expect(
    screen.getAllByText("dsh.modelAuditView.sources.kinds.runtime-context"),
  ).toHaveLength(1);
  expect(screen.getByText("dsh.modelAuditView.sources.unknown")).toBeVisible();
  expect(screen.queryByText(/private-|snapshot/)).toBeNull();
});

describe("audit body NDJSON-to-message UI", () => {
  it.each(["chat-json", "responses-json", "responses-stream"])(
    "renders %s replies through the original-access stream",
    async (protocol) => {
      const text = "Protocol reply shown once";
      const message = {
        type: "message",
        role: "assistant",
        content: [{ type: "output_text", text, annotations: [] }],
      };
      const response = {
        object: "response",
        status: "completed",
        output: [message],
      };
      const units: unknown[] =
        protocol === "chat-json"
          ? [
              {
                message: { role: "assistant", content: text },
                finish_reason: "stop",
              },
            ]
          : protocol === "responses-json"
            ? [response]
            : [
                {
                  type: "response.output_text.delta",
                  output_index: 0,
                  content_index: 0,
                  delta: text,
                },
                { type: "response.completed", response },
              ];
      source(
        frames(units.map((value) => ({ channel: "output" as const, value }))),
      );
      render(<ModelAuditBody requestId="request" />);
      await screen.findByText("dsh.modelAuditView.transfer.completed");
      expect(screen.getAllByText(text)).toHaveLength(1);
      expect(screen.getAllByRole("article")).toHaveLength(1);
      expect(
        screen.queryByText("dsh.modelAuditView.messages.unparsed"),
      ).toBeNull();
      expect(
        screen.queryByText(
          /finish_reason|response.output_text.delta|response.completed/,
        ),
      ).toBeNull();
    },
  );

  it("AC-10, AC-12: displays decoded roles and merged reply, hiding invocation settings and raw delta wrappers", async () => {
    source(
      frames([
        {
          channel: "input",
          value: {
            parameters: { model: "hidden-settings", stream: true },
            tools: [],
          },
        },
        {
          channel: "input",
          value: { role: "system", content: "System instruction\nSecond line" },
        },
        { channel: "input", value: { role: "user", content: "Hello" } },
        {
          channel: "output",
          value: { delta: { reasoning_content: "Think " } },
        },
        { channel: "output", value: { delta: { reasoning_content: "first" } } },
        { channel: "output", value: { delta: { content: "Hello " } } },
        { channel: "output", value: { delta: { content: "there!" } } },
        { channel: "output", value: { finish_reason: "stop" } },
      ]),
    );
    render(<ModelAuditBody requestId="request" tenantId={1} />);
    await screen.findByText("dsh.modelAuditView.transfer.completed");
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(
      screen.getByText("System instruction Second line"),
    ).toHaveTextContent("System instruction Second line");
    expect(screen.getByText("Hello there!")).toBeInTheDocument();
    const reasoning = screen.getByText("Think first").closest("details");
    expect(reasoning).not.toHaveAttribute("open");
    expect(
      screen.queryByText(
        /hidden-settings|reasoning_content|finish_reason|"delta"/,
      ),
    ).toBeNull();
    expect(api.stream).toHaveBeenCalledTimes(1);
    expect(api.stream).toHaveBeenCalledWith(
      "/api/v1/dsh/admin/model-audit/requests/request/body-access?include_message_sources=true&tenant_id=1",
      expect.any(AbortSignal),
    );
  });

  it("AC-10: merges indexed tool calls and retains tool-result associations without treating them as user messages", async () => {
    source(
      frames([
        {
          channel: "input",
          value: {
            role: "tool",
            tool_call_id: "call-old",
            content: "Saved tool result",
          },
        },
        {
          channel: "output",
          value: {
            delta: {
              tool_calls: [
                {
                  index: 0,
                  id: "call-new",
                  function: { name: "look", arguments: '{"q":' },
                },
              ],
            },
          },
        },
        {
          channel: "output",
          value: {
            delta: {
              tool_calls: [
                { index: 0, function: { name: "up", arguments: '"value"}' } },
              ],
            },
          },
        },
      ]),
    );
    render(<ModelAuditBody requestId="request" />);
    await screen.findByText("dsh.modelAuditView.transfer.completed");
    const [input, output] = screen.getAllByRole("article");
    expect(within(input).getByText(/roles.tool/)).toBeInTheDocument();
    expect(within(input).getByText(/call-old/)).toBeInTheDocument();
    expect(within(output).getByText("lookup")).toBeInTheDocument();
    expect(within(output).getByText('{"q":"value"}')).toBeInTheDocument();
    expect(within(output).getByText(/call-new/)).toBeInTheDocument();
  });

  it("AC-14, AC-19: renders untrusted text literally and never automatically loads image or HTML resources", async () => {
    source(
      frames([
        {
          channel: "input",
          value: {
            role: "user",
            content: [
              {
                type: "text",
                text: '<img src="https://invalid/tracker" onerror="alert(1)"><script>unsafe()</script>',
              },
              {
                type: "image_url",
                image_url: { url: "https://invalid/remote.png" },
              },
            ],
          },
        },
      ]),
    );
    const { container } = render(<ModelAuditBody requestId="request" />);
    await screen.findByText("dsh.modelAuditView.transfer.completed");
    expect(screen.getByText(/<script>unsafe/)).toBeInTheDocument();
    expect(container.querySelector("img,script,iframe,a")).toBeNull();
    expect(
      screen.getByText("dsh.modelAuditView.messages.image").closest("details"),
    ).not.toHaveAttribute("open");
  });

  it("AC-10, AC-12: pages long merged content without losing its tail or issuing another original access", async () => {
    source(
      frames([
        { channel: "output", value: { delta: { content: "x".repeat(16000) } } },
        { channel: "output", value: { delta: { content: "visible-tail" } } },
      ]),
    );
    render(<ModelAuditBody requestId="request" />);
    await screen.findByText("dsh.modelAuditView.transfer.completed");
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.queryByText("visible-tail")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "dsh.next" }));
    expect(screen.getByText("visible-tail")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "dsh.previous" }));
    expect(screen.getByText("x".repeat(16000))).toBeInTheDocument();
    expect(api.stream).toHaveBeenCalledTimes(1);
  });

  it("AC-09: exposes partial storage even when every transmitted frame arrived", async () => {
    const payload = frames([
      { channel: "input", value: { role: "user", content: "Saved text" } },
    ]);
    payload[0] = { ...payload[0], content_state: "PARTIAL" } as AuditBodyFrame;
    payload[payload.length - 1] = {
      ...payload.at(-1),
      content_state: "PARTIAL",
    } as AuditBodyFrame;
    source(payload);
    render(<ModelAuditBody requestId="request" />);
    await screen.findByText("dsh.modelAuditView.transfer.completed");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "dsh.modelAuditView.gap",
    );
    expect(screen.getByText("Saved text")).toBeInTheDocument();
  });

  it("AC-10, AC-19: marks interrupted reads and keeps safely decoded content without claiming completion", async () => {
    source(
      frames([
        { channel: "output", value: { delta: { content: "Partial reply" } } },
      ]).slice(0, -1),
    );
    render(<ModelAuditBody requestId="request" />);
    await screen.findByText("dsh.modelAuditView.transfer.interrupted");
    expect(screen.getByText("Partial reply")).toBeInTheDocument();
    expect(screen.queryByText("dsh.modelAuditView.gap")).toBeNull();
    expect(
      screen.queryByText("dsh.modelAuditView.transfer.completed"),
    ).toBeNull();
  });

  it("AC-10, AC-21: publishes merged content during a live transfer and aborts/clears it when the tenant changes", async () => {
    let streamController: ReadableStreamDefaultController<Uint8Array>;
    api.stream.mockImplementationOnce(
      (_url: string, signal: AbortSignal) =>
        new ReadableStream({
          start(controller) {
            streamController = controller;
            signal.addEventListener("abort", () =>
              controller.error(new Error("aborted")),
            );
          },
        }),
    );
    const payload = frames([
      { channel: "output", value: { delta: { content: "First live piece" } } },
      { channel: "output", value: { delta: { content: " second" } } },
    ]);
    const view = render(<ModelAuditBody requestId="request" tenantId={1} />);
    await act(async () => {
      for (const frame of payload.slice(0, -1))
        streamController.enqueue(
          new TextEncoder().encode(JSON.stringify(frame) + "\n"),
        );
    });
    await screen.findByText("First live piece");
    expect(
      screen.getByText("dsh.modelAuditView.transfer.loading"),
    ).toBeInTheDocument();
    const signal = api.stream.mock.calls[0][1] as AbortSignal;
    source(
      frames([
        { channel: "input", value: { role: "user", content: "Other tenant" } },
      ]),
    );
    view.rerender(<ModelAuditBody requestId="request" tenantId={2} />);
    await screen.findByText("Other tenant");
    expect(signal.aborted).toBe(true);
    expect(screen.queryByText(/First live piece/)).toBeNull();
  });
});
