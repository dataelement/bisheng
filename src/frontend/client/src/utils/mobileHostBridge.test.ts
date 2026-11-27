import {
  prepareMobileHostSend,
  publishMobileHost,
  runMobileHostSend,
} from "./mobileHostBridge";

if (typeof window === "undefined") {
  (globalThis as { window?: object }).window = globalThis;
}

test("prepareMobileHostSend keeps the draft fields the page closes over", () => {
  const prepared = prepareMobileHostSend({
    text: "  hello ",
    modelId: "9",
    taskMode: true,
    searchEnabled: true,
    orgIds: [3, ""],
    spaceIds: ["8"],
    skillNames: ["brief"],
    skillIds: [6],
    tools: [{ id: "4", tool_key: "search", name: "Search" }, { id: "nope" }],
    files: [{ filepath: "a", name: "a.txt" }, "bad"],
  });

  expect(prepared.text).toBe("hello");
  expect(prepared.model).toEqual({ id: 9, name: "" });
  expect(prepared.taskMode).toBe(true);
  expect(prepared.searchEnabled).toBe(true);
  expect(prepared.knowledge).toEqual([
    { id: "3", name: "", type: "org" },
    { id: "8", name: "", type: "space" },
  ]);
  expect(prepared.skills).toEqual([{ name: "brief", display_name: "brief", id: 6 }]);
  expect(prepared.tools).toEqual([{
    id: 0,
    name: "",
    children: [{ id: 4, tool_key: "search", name: "Search" }],
  }]);
  expect(prepared.files).toEqual([{ filepath: "a", name: "a.txt" }]);
});

test("prepareMobileHostSend drops a draft that is not an object", () => {
  expect(prepareMobileHostSend(null)).toMatchObject({
    text: "",
    tools: [],
    knowledge: [],
    skills: [],
  });
  expect(prepareMobileHostSend("hello").model).toBeUndefined();
});

test("runMobileHostSend applies the draft before the existing send and then reports the turn", async () => {
  const notices: Array<Record<string, unknown>> = [];
  const applied: unknown[] = [];
  const sent: unknown[] = [];
  await runMobileHostSend({ text: "hello", modelId: 9 }, {
    conversationId: "new",
    apply: (prepared) => applied.push(prepared),
    sendMessage: async (text, files, opts) => {
      sent.push({ text, files, model: opts.hostDraft.model });
      opts.onTurnCreated("chat-1");
      return true;
    },
    post: (message) => notices.push(message),
  });

  expect(applied[0]).toMatchObject({ text: "hello", model: { id: 9, name: "" } });
  expect(sent).toEqual([{ text: "hello", files: [], model: { id: 9, name: "" } }]);
  expect(notices).toEqual([
    { type: "turn-started", conversationId: "chat-1" },
    { type: "turn-started" },
  ]);
});

test("runMobileHostSend does not report a turn when the existing send refuses", async () => {
  const notices: Array<Record<string, unknown>> = [];
  await runMobileHostSend({ text: "hello" }, {
    conversationId: "new",
    apply: () => undefined,
    sendMessage: async () => false,
    post: (message) => notices.push(message),
  });
  expect(notices).toEqual([{ type: "send-failed", handedOff: false }]);
});

test("a normal browser does not keep the mobile host entry", () => {
  publishMobileHost(false, { send: async () => undefined, resetBlank: () => undefined });
  expect((window as Window & { __bsMobileHost?: unknown }).__bsMobileHost).toBeUndefined();
  const api = { send: async () => undefined, resetBlank: () => undefined };
  publishMobileHost(true, api);
  expect((window as Window & { __bsMobileHost?: unknown }).__bsMobileHost).toBe(api);
  publishMobileHost(false, api);
  expect((window as Window & { __bsMobileHost?: unknown }).__bsMobileHost).toBeUndefined();
});
