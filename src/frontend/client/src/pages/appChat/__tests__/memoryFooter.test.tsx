import { messagesForPresentation } from "@bisheng/chat/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ClientMessageFooter } from "../components/ClientMessageFooter";
import {
  appMemoryEnabled,
  attachMemoryFlags,
  readMemoryFrame,
  queueMemoryFlags,
  takeQueuedMemoryFlags,
} from "../appMemory";

const mockApi = { getMemoryTurnApi: jest.fn(), getMemoryFlagsApi: jest.fn() };

jest.mock("~/api/memory", () => ({
  ...jest.requireActual("~/api/memory"),
  getMemoryTurnApi: (...args: unknown[]) => mockApi.getMemoryTurnApi(...args),
  getMemoryFlagsApi: (...args: unknown[]) => mockApi.getMemoryFlagsApi(...args),
}));
jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
// The package entry pulls the markdown stack (ESM); only the copy action is used here.
jest.mock("@bisheng/chat", () => ({ CopyMessageAction: () => null }));
jest.mock("~/components/Chat/Messages/Content/CitationReferencesDrawer", () => ({ __esModule: true, default: () => null }));
jest.mock("~/components/Chat/MessageSelection", () => ({ ExportSelectionButton: () => null }));
jest.mock("~/components/Voice/TextToSpeechButton", () => ({ TextToSpeechButton: () => null }));
jest.mock("../components/MessageButtons", () => ({
  __esModule: true,
  default: () => <div data-testid="message-buttons" />,
}));

const QUESTION = { id: 10, category: "question", is_bot: false, message: "Remember my flight", chat_id: "c1" };
const ANSWER = { id: 11, category: "answer", is_bot: true, message: "Noted.", chat_id: "c1", end: true };

const MEMORY_FRAME = {
  category: "memory",
  type: "memory",
  message: { turn_id: "turn-1", has_write: true, has_attribution: true },
  chat_id: "c1",
};

function renderFooter(rows: unknown[], mode: "assistant" | "workflow", memoryEnabled: boolean) {
  const messages = messagesForPresentation(rows, { mode, sessionKey: "c1" });
  const answer = messages[messages.length - 1];
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/app/c1/f1/5"]}>
        <Routes>
          <Route
            path="/app/:conversationId/:fid/:type"
            element={
              <ClientMessageFooter
                message={answer}
                contentRef={createRef<HTMLDivElement>()}
                readOnly={false}
                memoryEnabled={memoryEnabled}
              />
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockApi.getMemoryTurnApi.mockResolvedValue({ turn_id: "turn-1", writes: [], retrieved: [], resident: [] });
  mockApi.getMemoryFlagsApi.mockResolvedValue({});
});

it("reads a memory WebSocket message and pins it on the round's answer (AC-21)", () => {
  const parsed = readMemoryFrame(MEMORY_FRAME);
  expect(parsed).toEqual({ flags: { turn_id: "turn-1", has_write: true, has_attribution: true }, messageId: undefined });
  expect(readMemoryFrame({ category: "stream_msg", type: "end", message: "hi" })).toBeNull();

  const { rows, attached } = attachMemoryFlags([QUESTION, ANSWER], parsed!.flags);
  expect(attached).toBe(true);
  expect((rows[1] as { memory?: unknown }).memory).toEqual(parsed!.flags);
  expect(rows[0]).toBe(QUESTION);

  const byId = attachMemoryFlags([QUESTION, ANSWER, { ...ANSWER, id: 12 }], parsed!.flags, "11");
  expect((byId.rows[1] as { memory?: unknown }).memory).toEqual(parsed!.flags);
  expect((byId.rows[2] as { memory?: unknown }).memory).toBeUndefined();

  const early = attachMemoryFlags([ANSWER, QUESTION], parsed!.flags);
  expect(early.attached).toBe(false);
  queueMemoryFlags("c1", parsed!.flags);
  expect(takeQueuedMemoryFlags("c1")).toEqual(parsed!.flags);
  expect(takeQueuedMemoryFlags("c1")).toBeUndefined();
});

it("shows the notice and the attribution entry under an assistant answer (AC-21, AC-87)", async () => {
  const { rows } = attachMemoryFlags([QUESTION, ANSWER], readMemoryFrame(MEMORY_FRAME)!.flags);
  renderFooter(rows, "assistant", appMemoryEnabled(5, false, false));
  expect(await screen.findByRole("button", { name: /memory\.notice/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /memory\.attribution\.entry/ })).toBeInTheDocument();
  await waitFor(() => expect(mockApi.getMemoryTurnApi).toHaveBeenCalledWith({ turnId: "turn-1", messageId: "11" }));
  expect(screen.getByTestId("message-buttons")).toBeInTheDocument();
});

it("shows history flags fetched by chat id after a reload (AC-21, AC-87)", async () => {
  mockApi.getMemoryFlagsApi.mockResolvedValue({ "11": { turn_id: "turn-0", has_write: false, has_attribution: true } });
  renderFooter([QUESTION, ANSWER], "assistant", true);
  expect(await screen.findByRole("button", { name: /memory\.attribution\.entry/ })).toBeInTheDocument();
  expect(mockApi.getMemoryFlagsApi).toHaveBeenCalledWith("c1");
});

it("never shows attribution under a workflow answer (AC-87)", async () => {
  expect(appMemoryEnabled(10, false, false)).toBe(false);
  expect(appMemoryEnabled(5, true, false)).toBe(false);
  expect(appMemoryEnabled(5, false, true)).toBe(false);

  const workflowAnswer = { ...ANSWER, category: "output_msg" };
  const { rows } = attachMemoryFlags([QUESTION, workflowAnswer], readMemoryFrame(MEMORY_FRAME)!.flags);
  renderFooter(rows, "workflow", appMemoryEnabled(10, false, false));
  await waitFor(() => expect(screen.getByTestId("message-buttons")).toBeInTheDocument());
  expect(screen.queryByRole("button", { name: /memory\.attribution\.entry/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /memory\.notice/ })).toBeNull();
  expect(mockApi.getMemoryFlagsApi).not.toHaveBeenCalled();
  expect(mockApi.getMemoryTurnApi).not.toHaveBeenCalled();
});
