import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { MemoryItem, MemoryTurn } from "~/api/memory";
import { ResultPanel } from "../ResultPanel";

const mockGetTurn = jest.fn();

jest.mock("~/api/memory", () => ({
  ...jest.requireActual("~/api/memory"),
  getMemoryTurnApi: (...args: unknown[]) => mockGetTurn(...args),
}));
jest.mock("~/api/apps", () => ({ likeChatApi: jest.fn(), disLikeCommentApi: jest.fn() }));
jest.mock("~/components/Chat/MessageFeedbackButtons", () => ({
  MessageFeedbackButtons: () => <div data-testid="feedback" />,
}));
jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string, options?: Record<string, unknown>) =>
    options && Object.keys(options).length ? `${key}|${Object.values(options).join("|")}` : key,
}));

const item = (id: string, content: string): MemoryItem => ({
  id,
  content,
  type: "fact",
  status: "active",
  recorded_at: "2026-11-10 08:00",
  event_time: null,
  source: { scene: "linsight", app_id: null, app_name: null, chat_id: "c1", origin: "explicit" },
  pinned: false,
  has_detail: false,
});

const TURNS: Record<string, MemoryTurn> = {
  "201": {
    turn_id: "round-1",
    writes: [{ record_id: 1, op: "remember", item_id: "a", related_item_id: null, undone: false, item: item("a", "Round one fact"), related_item: null }],
    retrieved: [],
    resident: [],
  },
  "202": {
    turn_id: "round-2",
    writes: [],
    retrieved: [item("b", "Round two lookup")],
    resident: [],
  },
};

function renderRounds(allowFeedback = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <div data-testid="round-1">
        <ResultPanel messageId="201" allowFeedback={allowFeedback}>
          <p>first result</p>
        </ResultPanel>
      </div>
      <div data-testid="round-2">
        <ResultPanel messageId="202" allowFeedback={allowFeedback}>
          <p>second result</p>
        </ResultPanel>
      </div>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockGetTurn.mockImplementation(async ({ messageId }: { messageId: string }) => TURNS[messageId]);
});

it("shows each round's own notice and attribution by its task message id (AC-21, AC-87)", async () => {
  renderRounds();
  const first = screen.getByTestId("round-1");
  const second = screen.getByTestId("round-2");

  const notice = await within(first).findByRole("button", { name: /memory\.notice\.remember\|1/ });
  expect(within(first).queryByRole("button", { name: /memory\.attribution\.entry/ })).toBeNull();
  const attribution = await within(second).findByRole("button", { name: /memory\.attribution\.entry/ });
  expect(within(second).queryByRole("button", { name: /memory\.notice/ })).toBeNull();

  expect(mockGetTurn).toHaveBeenCalledWith({ turnId: undefined, messageId: "201" });
  expect(mockGetTurn).toHaveBeenCalledWith({ turnId: undefined, messageId: "202" });

  fireEvent.click(notice);
  expect(await within(first).findByText("Round one fact")).toBeInTheDocument();
  expect(within(second).queryByText("Round one fact")).toBeNull();

  fireEvent.click(attribution);
  expect(await within(second).findByText("Round two lookup")).toBeInTheDocument();
  expect(within(first).queryByText("Round two lookup")).toBeNull();

  // The notice sits with the feedback buttons of the same round.
  expect(within(first).getByTestId("feedback")).toBeInTheDocument();
});

it("asks nothing on a read-only or shared result (AC-87)", async () => {
  renderRounds(false);
  await waitFor(() => expect(screen.getByText("second result")).toBeInTheDocument());
  expect(mockGetTurn).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: /memory\./ })).toBeNull();
});
