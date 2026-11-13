import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpaceCopyDialog } from "@/pages/KnowledgePage/components/SpaceCopyDialog";
const mocks = vi.hoisted(() => ({
  precheck: vi.fn(),
  confirm: vi.fn(),
  error: vi.fn(),
}));
vi.mock("@/controllers/API/knowledgeProcessing", () => ({
  precheckSpaceCopy: mocks.precheck,
  confirmSpaceCopy: mocks.confirm,
}));
vi.mock("@/controllers/request", () => ({ showApiError: mocks.error }));
vi.mock("@/pages/KnowledgePage/components/SpaceProcessingProgress", () => ({
  SpaceProcessingProgress: ({
    spaceId,
    kind,
  }: {
    spaceId: number;
    kind: string;
  }) => (
    <p>
      {kind}:{spaceId}
    </p>
  ),
}));
const scope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary" as const,
};
const plan = {
  confirmation_id: "plan",
  plan_digest: "digest",
  can_execute: true,
  check_complete: true,
  invalid_items: [],
  requires_skip_confirmation: false,
};
function mount() {
  const created = vi.fn();
  return {
    ...render(
      <SpaceCopyDialog
        scope={scope}
        source={{ id: 7, name: "Source" }}
        onClose={vi.fn()}
        onCreated={created}
      />,
    ),
    created,
  };
}
beforeEach(() => {
  vi.resetAllMocks();
  mocks.precheck.mockResolvedValue(plan);
  mocks.confirm.mockResolvedValue({
    knowledge: { id: 8, name: "Copy" },
    processing_job: null,
    completed: true,
  });
});
afterEach(cleanup);
it("explains the complete copy and permission scope before any API call", () => {
  mount();
  for (const text of [
    "space_copy_ui.scope",
    "space_copy_ui.permissions",
    "space_copy_ui.independent",
  ])
    expect(screen.getByText(text)).toBeVisible();
  expect(mocks.precheck).not.toHaveBeenCalled();
  expect(mocks.confirm).not.toHaveBeenCalled();
});
it("prechecks and confirms once and reports the independent target", async () => {
  const view = mount();
  fireEvent.click(screen.getByRole("button", { name: "space_copy_ui.create" }));
  await waitFor(() => expect(view.created).toHaveBeenCalledTimes(1));
  expect(mocks.precheck).toHaveBeenCalledWith(7, "SourcecopySuffix");
  expect(mocks.confirm).toHaveBeenCalledWith(
    7,
    expect.objectContaining({ confirmation_id: "plan", plan_digest: "digest" }),
  );
  expect(screen.getByText("space_copy_ui.created")).toBeVisible();
});
it("uses the target space and copy-kind progress rather than the source space", async () => {
  mocks.confirm.mockResolvedValue({
    knowledge: { id: 8, name: "Copy" },
    processing_job: { job_id: "job", state: "accepted" },
    completed: false,
  });
  mount();
  fireEvent.click(screen.getByRole("button", { name: "space_copy_ui.create" }));
  expect(await screen.findByText("space_copy:8")).toBeVisible();
});
it("reuses the same confirmation and idempotency key after a lost acknowledgement", async () => {
  mocks.confirm.mockRejectedValueOnce(new Error("Lost ACK"));
  mount();
  fireEvent.click(screen.getByRole("button", { name: "space_copy_ui.create" }));
  await waitFor(() => expect(mocks.error).toHaveBeenCalled());
  fireEvent.click(screen.getByRole("button", { name: "space_copy_ui.create" }));
  await screen.findByText("space_copy_ui.created");
  expect(mocks.precheck).toHaveBeenCalledTimes(1);
  expect(mocks.confirm.mock.calls[0]).toEqual(mocks.confirm.mock.calls[1]);
});
it("rejects incomplete plans and does not confirm a retired precheck", async () => {
  mocks.precheck.mockResolvedValueOnce({ ...plan, check_complete: false });
  const view = mount();
  fireEvent.click(screen.getByRole("button", { name: "space_copy_ui.create" }));
  await waitFor(() => expect(mocks.error).toHaveBeenCalled());
  expect(mocks.confirm).not.toHaveBeenCalled();
  let resolve!: (value: typeof plan) => void;
  mocks.precheck.mockReturnValue(
    new Promise((yes) => {
      resolve = yes;
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "space_copy_ui.create" }));
  await waitFor(() => expect(mocks.precheck).toHaveBeenCalledTimes(2));
  view.unmount();
  resolve(plan);
  await new Promise((yes) => setTimeout(yes, 0));
  expect(mocks.confirm).not.toHaveBeenCalled();
});
