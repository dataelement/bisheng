import { act, renderHook } from "@testing-library/react";
import type { MobileHostApi } from "~/utils/mobileHostBridge";
import { useMobileHostBridge } from "./useMobileHostBridge";

let mockEmbedded = true;
jest.mock("~/hooks/useClientEnvironment", () => ({
  useClientEnvironment: () => ({ capabilities: { hasHostChatHeader: mockEmbedded } }),
}));

type BridgeInput = Parameters<typeof useMobileHostBridge>[0];
const host = window as Window & {
  __bsMobileHost?: MobileHostApi;
  BishengMobile?: { postMessage: (message: string) => void };
};
let notices: Record<string, unknown>[];

function input(overrides: Partial<BridgeInput> = {}): BridgeInput {
  return {
    userLoaded: true,
    configReady: true,
    isLoading: false,
    conversationId: "new",
    messageCount: 0,
    navigate: jest.fn(),
    sendMessage: jest.fn().mockResolvedValue(true),
    apply: jest.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  mockEmbedded = true;
  notices = [];
  host.BishengMobile = { postMessage: message => notices.push(JSON.parse(message)) };
});
afterEach(() => {
  delete host.BishengMobile;
  delete host.__bsMobileHost;
});

test.each(["accepted", "refused", "thrown"])(
  "blocks another host call during the lease/request and unlocks after %s",
  async outcome => {
    let resolve!: (accepted: boolean) => void;
    let reject!: (error: Error) => void;
    const pending = new Promise<boolean>((done, fail) => { resolve = done; reject = fail; });
    const sendMessage = jest.fn().mockReturnValueOnce(pending).mockResolvedValue(true);
    const props = input({ sendMessage });
    const view = renderHook(useMobileHostBridge, { initialProps: props });
    const api = host.__bsMobileHost!;
    let first!: Promise<void>;
    act(() => { first = api.send({ text: "Question", modelId: 1 }); });
    view.rerender({ ...props });
    const beforeDuplicate = notices.length;
    await act(async () => { await api.send({ text: "Question", modelId: 1 }); });
    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(props.apply).toHaveBeenCalledTimes(1);
    expect(notices).toHaveLength(beforeDuplicate);
    await act(async () => {
      if (outcome === "thrown") reject(new Error("Request failed"));
      else resolve(outcome === "accepted");
      await first;
    });
    await act(async () => { await api.send({ text: "Retry", modelId: 1 }); });
    expect(sendMessage).toHaveBeenCalledTimes(2);
  },
);

test.each(["configReady", "isLoading"] as const)("waits for %s and checks the current state on send", async field => {
  const props = input({ [field]: field === "isLoading" });
  const view = renderHook(useMobileHostBridge, { initialProps: props });
  const api = host.__bsMobileHost!;
  expect(notices).toEqual([]);
  await act(async () => { await api.send({ text: "Question", modelId: 1 }); });
  expect(props.sendMessage).not.toHaveBeenCalled();
  expect(props.apply).not.toHaveBeenCalled();
  expect(notices).toEqual([{ type: "send-failed", handedOff: false }]);

  view.rerender({ ...props, configReady: true, isLoading: false });
  expect(notices.slice(1)).toEqual([{ type: "shell-ready" }, { type: "blank-ready" }]);
  await act(async () => { await api.send({ text: "Question", modelId: 1 }); });
  expect(props.sendMessage).toHaveBeenCalledTimes(1);

  view.rerender(props);
  await act(async () => { await api.send({ text: "Question", modelId: 1 }); });
  expect(props.sendMessage).toHaveBeenCalledTimes(1);
});

test.each(["browser", "logged-out"])("does not publish the API for %s", state => {
  mockEmbedded = state !== "browser";
  renderHook(useMobileHostBridge, { initialProps: input({ userLoaded: state !== "logged-out" }) });
  expect(host.__bsMobileHost).toBeUndefined();
  expect(notices).toEqual([]);
});

test("reset and cleanup keep the existing host lifecycle", () => {
  const props = input({ conversationId: "chat-1", messageCount: 2 });
  const view = renderHook(useMobileHostBridge, { initialProps: props });
  expect(notices).toEqual([{ type: "shell-ready" }]);
  host.__bsMobileHost!.resetBlank();
  expect(props.navigate).toHaveBeenCalledWith("/c/new", { replace: true });
  view.unmount();
  expect(host.__bsMobileHost).toBeUndefined();
});
