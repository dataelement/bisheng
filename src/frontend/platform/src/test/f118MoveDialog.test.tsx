import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
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
vi.mock("@/pages/KnowledgePage/components/MoveDestinationPicker", () => ({
  MoveDestinationPicker: ({
    onChange,
  }: {
    onChange: (
      value: { spaceId: number; folderId: null },
      label: string,
    ) => void;
  }) => (<>
    <button
      onClick={() => onChange({ spaceId: 42, folderId: null }, "Target root")}
    >
      destination
    </button>
    <button onClick={() => onChange({ spaceId: 43, folderId: null }, "Target two")}>destination two</button>
  </>),
}));
vi.mock("@/pages/KnowledgePage/components/SpaceProcessingProgress", () => ({
  SpaceProcessingProgress: ({
    kind,
    spaceId,
  }: {
    kind: string;
    spaceId: number;
  }) => (
    <p>
      {kind}:{spaceId}
    </p>
  ),
}));
const clients: QueryClient[] = [];
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
    { id: 32, type: "file" as const, reason: "no_permission" as const },
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
  render(
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
  return onClose;
}
it("cancel leaves both API commands untouched", () => {
  const close = setup();
  fireEvent.click(screen.getByText("close"));
  expect(close).toHaveBeenCalledOnce();
  expect(api.precheckMove).not.toHaveBeenCalled();
  expect(api.confirmMove).not.toHaveBeenCalled();
});
it("reviews full mixed selection and field losses, then retries the same immutable confirmation after unknown ACK", async () => {
  // HTTP deployments have getRandomValues but no secure-context randomUUID.
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
  setup();
  fireEvent.click(screen.getByText("destination"));
  expect(screen.queryByText("f118.processing_review_action")).toBeNull();
  await screen.findByText("move.removed_fields: confidentiality");
  expect(screen.getByText("move.destination: Target root")).toBeTruthy();
  expect(screen.getByText("move.retained_fields: date")).toBeTruthy();
  expect(api.precheckMove).toHaveBeenCalledWith(
    40,
    [
      { id: 31, type: "file" },
      { id: 32, type: "file" },
    ],
    { spaceId: 42, folderId: null },
    101,
  );
  expect((screen.getByText("confirm") as HTMLButtonElement).disabled).toBe(
    true,
  );
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByText("confirm"));
  await screen.findByText("move.unknown_ack");
  expect((screen.getByText("close") as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByText("retry"));
  await waitFor(() => expect(screen.getByText("move_index:40")).toBeTruthy());
  expect(api.confirmMove).toHaveBeenCalledTimes(2);
  expect(vi.mocked(api.confirmMove).mock.calls[0]).toEqual(
    vi.mocked(api.confirmMove).mock.calls[1],
  );
  expect(
    Object.keys(vi.mocked(api.confirmMove).mock.calls[0][1]).sort(),
  ).toEqual(["confirmation_id", "idempotency_key", "plan_digest"]);
  expect(api.precheckMove).toHaveBeenCalledOnce();
});

it("checks the selected destination automatically and moves after one confirmation", async () => {
  vi.mocked(api.precheckMove).mockResolvedValue({ ...plan, invalid_items: [], requires_skip_confirmation: false });
  vi.mocked(api.confirmMove).mockResolvedValue({ moved: [{ id: 31, type: "file" }], invalid: [] });
  setup();
  expect(screen.queryByText("f118.processing_review_action")).toBeNull();
  fireEvent.click(screen.getByText("destination"));
  await waitFor(() => expect(screen.getByRole("button", { name: "confirm" })).toBeEnabled());
  expect(api.confirmMove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  expect(await screen.findByText("move.completed")).toBeVisible();
  expect(api.confirmMove).toHaveBeenCalledOnce();
});

it("ignores a retired destination check and only confirms the current plan", async () => {
  let resolve!: (value: typeof plan) => void;
  vi.mocked(api.precheckMove)
    .mockReturnValueOnce(new Promise((yes) => { resolve = yes; }))
    .mockResolvedValueOnce({ ...plan, confirmation_id: "current-plan", invalid_items: [], requires_skip_confirmation: false });
  vi.mocked(api.confirmMove).mockResolvedValue({ moved: [], invalid: [] });
  setup();
  fireEvent.click(screen.getByText("destination"));
  await waitFor(() => expect(api.precheckMove).toHaveBeenCalledOnce());
  fireEvent.click(screen.getByText("destination two"));
  await screen.findByText("move.destination: Target two");
  resolve(plan);
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(api.confirmMove).toHaveBeenCalledWith(40, expect.objectContaining({ confirmation_id: "current-plan" }), 101));
});

it("automatically renews an expired plan and requires fresh skip consent", async () => {
  vi.mocked(api.precheckMove).mockResolvedValueOnce(plan).mockResolvedValueOnce({ ...plan, confirmation_id: "renewed-plan" });
  vi.mocked(api.confirmMove).mockRejectedValueOnce({ status_code: 18087 }).mockResolvedValueOnce({ moved: [], invalid: [] });
  setup();
  fireEvent.click(screen.getByText("destination"));
  fireEvent.click(await screen.findByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(api.precheckMove).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.getByRole("checkbox")).not.toBeChecked());
  expect(screen.getByRole("button", { name: "confirm" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(api.confirmMove).toHaveBeenLastCalledWith(40, expect.objectContaining({ confirmation_id: "renewed-plan" }), 101));
});
