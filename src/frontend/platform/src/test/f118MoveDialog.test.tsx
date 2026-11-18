import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { toast } from "@bisheng/ui";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { MoveDialog } from "@/pages/KnowledgePage/components/MoveDialog";
import * as api from "@/controllers/API/knowledgeMove";

vi.mock("@/controllers/request", () => ({
  default: {},
  showApiError: vi.fn(),
}));
vi.mock("@/controllers/API", () => ({ getKnowledgeDetailApi: vi.fn() }));
vi.mock("@/controllers/API/knowledgeMove", () => ({
  precheckMove: vi.fn(),
  confirmMove: vi.fn(),
}));
vi.mock("@/controllers/managementScope", () => ({
  managementRequestScope: () => 101,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, args?: { fields?: string; destination?: string }) =>
      args?.fields || args?.destination
        ? `${key}: ${args.fields ?? args.destination}`
        : key,
    i18n: { resolvedLanguage: "en", exists: () => true },
  }),
}));
vi.mock("@bisheng/knowledge", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@bisheng/knowledge")>();
  const { useState } = await import("react");
  return {
    ...actual,
    MoveToDialog: ({
      onOpenChange,
      onConfirm,
    }: {
      onOpenChange: (open: boolean) => void;
      onConfirm: (
        spaceId: string,
        folderId: null,
        crossSpace: boolean,
        name: string,
      ) => void;
    }) => {
      const [target, setTarget] = useState("40");
      return (
        <>
          <button onClick={() => setTarget("42")}>destination</button>
          <button onClick={() => setTarget("43")}>destination two</button>
          <button onClick={() => onOpenChange(false)}>close</button>
          <button
            onClick={() => {
              onOpenChange(false);
              onConfirm(
                target,
                null,
                target !== "40",
                target === "43" ? "Target two" : "Target root",
              );
            }}
          >
            move here
          </button>
        </>
      );
    },
  };
});
vi.mock("@/pages/KnowledgePage/components/SpaceProcessingProgress", () => ({
  SpaceProcessingProgress: ({
    kind,
    spaceId,
    onCompleted,
  }: {
    kind: string;
    spaceId: number;
    onCompleted?: () => void;
  }) => (
    <>
      <p>
        {kind}:{spaceId}
      </p>
      <button onClick={onCompleted}>complete job</button>
    </>
  ),
}));
const clients: QueryClient[] = [];
vi.spyOn(toast, "show").mockReturnValue("move-toast");
afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.clearAllMocks();
});
const plan = {
  confirmation_id: "real-review",
  plan_digest: "a".repeat(64),
  expires_at: "2030-01-01",
  check_complete: true,
  can_execute: true,
  valid_items: [{ id: 31, type: "file" as const }],
  invalid_items: [
    { id: 32, type: "file" as const, name: "blocked.txt", reason: "no_permission" as const },
  ],
  impact: {
    cross_space: true,
    removed_fields: ["confidentiality"],
    retained_fields: ["date"],
  },
  requires_skip_confirmation: true,
};
function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  const onClose = vi.fn();
  const view = render(
    <QueryClientProvider client={client}>
      <MoveDialog
        scope={{
          identityKey: "u7",
          tenantId: 101,
          managementTenantId: 101,
          view: "ordinary",
        }}
        spaceId={40}
        parentId={null}
        items={[
          { id: 31, type: "file" },
          { id: 32, type: "file" },
        ]}
        onClose={onClose}
      />
    </QueryClientProvider>,
  );
  return { onClose, ...view };
}
it("cancel leaves both API commands untouched", () => {
  const { onClose: close } = setup();
  fireEvent.click(screen.getByText("close"));
  expect(close).toHaveBeenCalledOnce();
  expect(api.precheckMove).not.toHaveBeenCalled();
  expect(api.confirmMove).not.toHaveBeenCalled();
});
it("confirms mixed selection with the shared dialog and retries an unknown ACK with the same command", async () => {
  vi.stubGlobal("crypto", {
    getRandomValues: globalThis.crypto.getRandomValues.bind(globalThis.crypto),
  });
  vi.mocked(api.precheckMove).mockResolvedValue(plan);
  vi.mocked(api.confirmMove)
    .mockRejectedValueOnce(new Error("unknown ACK"))
    .mockResolvedValueOnce({
      job_id: "move-job",
      accepted: true,
      state: "accepted",
      reused: true,
    });
  const { onClose } = setup();
  fireEvent.click(screen.getByText("destination"));
  fireEvent.click(screen.getByText("move here"));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "move_here" })).toBeEnabled(),
  );
  expect(screen.getByRole("alertdialog")).toHaveTextContent("confidentiality");
  const unavailable = screen.getByRole("table", { name: "batch.invalid" });
  expect(within(unavailable).getByRole("rowheader", { name: "blocked.txt" })).toBeVisible();
  expect(within(unavailable).getByRole("cell", { name: "batch.reason_no_permission" })).toBeVisible();
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(api.precheckMove).toHaveBeenCalledWith(
    40,
    [
      { id: 31, type: "file" },
      { id: 32, type: "file" },
    ],
    { spaceId: 42, folderId: null },
    101,
  );
  fireEvent.click(screen.getByRole("button", { name: "move_here" }));
  await screen.findByText(/move.unknown_ack/);
  expect(screen.queryByRole("button", { name: "cancel_all" })).toBeNull();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  expect(await screen.findByText("move_index:40")).toBeVisible();
  expect(api.confirmMove).toHaveBeenCalledTimes(2);
  expect(vi.mocked(api.confirmMove).mock.calls[0]).toEqual(
    vi.mocked(api.confirmMove).mock.calls[1],
  );
  expect(
    Object.keys(vi.mocked(api.confirmMove).mock.calls[0][1]).sort(),
  ).toEqual(["confirmation_id", "idempotency_key", "plan_digest"]);
  expect(api.precheckMove).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "complete job" }));
  expect(onClose).toHaveBeenCalledOnce();
  expect(toast.show).toHaveBeenCalledWith({
    type: "success",
    message: "success",
  });
});

it("confirms a cross-space move once and closes with a success toast", async () => {
  vi.mocked(api.precheckMove).mockResolvedValue({
    ...plan,
    invalid_items: [],
    requires_skip_confirmation: false,
  });
  vi.mocked(api.confirmMove).mockResolvedValue({
    moved: [{ id: 31, type: "file" }],
    invalid: [],
  });
  const { onClose } = setup();
  fireEvent.click(screen.getByText("destination"));
  fireEvent.click(screen.getByText("move here"));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "move_here" })).toBeEnabled(),
  );
  expect(api.confirmMove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "move_here" }));
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  expect(toast.show).toHaveBeenCalledWith({
    type: "success",
    message: "success",
  });
  expect(api.confirmMove).toHaveBeenCalledOnce();
});

it("only prechecks after the picker commits its latest destination", async () => {
  vi.mocked(api.precheckMove).mockResolvedValue({
    ...plan,
    confirmation_id: "current-plan",
    invalid_items: [],
    requires_skip_confirmation: false,
  });
  vi.mocked(api.confirmMove).mockResolvedValue({ moved: [], invalid: [] });
  setup();
  fireEvent.click(screen.getByText("destination"));
  fireEvent.click(screen.getByText("destination two"));
  expect(api.precheckMove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("move here"));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "move_here" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "move_here" }));
  await waitFor(() =>
    expect(api.confirmMove).toHaveBeenCalledWith(
      40,
      expect.objectContaining({ confirmation_id: "current-plan" }),
      101,
    ),
  );
  expect(api.precheckMove).toHaveBeenCalledOnce();
  expect(api.precheckMove).toHaveBeenCalledWith(
    40,
    expect.any(Array),
    { spaceId: 43, folderId: null },
    101,
  );
});

it("moves a valid same-space selection without a second confirmation", async () => {
  vi.mocked(api.precheckMove).mockResolvedValue({
    ...plan,
    invalid_items: [],
    impact: { cross_space: false },
    requires_skip_confirmation: false,
  });
  vi.mocked(api.confirmMove).mockResolvedValue({ moved: [], invalid: [] });
  const { onClose } = setup();
  fireEvent.click(screen.getByText("move here"));
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  expect(toast.show).toHaveBeenCalledWith({
    type: "success",
    message: "success",
  });
  expect(api.confirmMove).toHaveBeenCalledOnce();
});

it("does not execute a retired same-space precheck after unmount", async () => {
  let resolve!: (value: typeof plan) => void;
  vi.mocked(api.precheckMove).mockReturnValueOnce(
    new Promise((yes) => {
      resolve = yes;
    }),
  );
  const { unmount } = setup();
  fireEvent.click(screen.getByText("move here"));
  await waitFor(() => expect(api.precheckMove).toHaveBeenCalledOnce());
  unmount();
  resolve({
    ...plan,
    invalid_items: [],
    impact: { ...plan.impact, cross_space: false },
    requires_skip_confirmation: false,
  });
  await new Promise((yes) => setTimeout(yes, 0));
  expect(api.confirmMove).not.toHaveBeenCalled();
});

it("renews an expired plan and asks for a fresh confirmation of the valid subset", async () => {
  vi.mocked(api.precheckMove)
    .mockResolvedValueOnce(plan)
    .mockResolvedValueOnce({ ...plan, confirmation_id: "renewed-plan" });
  vi.mocked(api.confirmMove)
    .mockRejectedValueOnce({ status_code: 18087 })
    .mockResolvedValueOnce({ moved: [], invalid: [] });
  setup();
  fireEvent.click(screen.getByText("destination"));
  fireEvent.click(screen.getByText("move here"));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "move_here" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "move_here" }));
  await waitFor(() => expect(api.precheckMove).toHaveBeenCalledTimes(2));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "move_here" })).toBeEnabled(),
  );
  expect(api.confirmMove).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "move_here" }));
  await waitFor(() =>
    expect(api.confirmMove).toHaveBeenLastCalledWith(
      40,
      expect.objectContaining({ confirmation_id: "renewed-plan" }),
      101,
    ),
  );
});

it("never executes a visible navigation destination denied by the server precheck", async () => {
  vi.mocked(api.precheckMove).mockResolvedValue({
    ...plan,
    can_execute: false,
  });
  setup();
  fireEvent.click(screen.getByText("destination"));
  fireEvent.click(screen.getByText("move here"));
  await screen.findByText(/review_impact/);
  expect(screen.getByRole("button", { name: "move_here" })).toBeDisabled();
  expect(api.confirmMove).not.toHaveBeenCalled();
});
