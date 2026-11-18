import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpaceCopyDialog } from "@/pages/KnowledgePage/components/SpaceCopyDialog";
import { ApiError } from "@bisheng/api-client";
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
  const closed = vi.fn();
  return {
    ...render(
      <SpaceCopyDialog
        scope={scope}
        source={{ id: 7, name: "Source" }}
        onClose={closed}
        onCreated={created}
      />,
    ),
    created,
    closed,
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
it("prechecks and confirms once, then closes so the copy continues in the background", async () => {
  const view = mount();
  fireEvent.click(screen.getByRole("button", { name: "space_copy_ui.create" }));
  await waitFor(() => expect(view.closed).toHaveBeenCalledTimes(1));
  expect(view.created).toHaveBeenCalledTimes(1);
  expect(mocks.precheck).toHaveBeenCalledWith(7, "SourcecopySuffix");
  expect(mocks.confirm).toHaveBeenCalledWith(
    7,
    expect.objectContaining({ confirmation_id: "plan", plan_digest: "digest" }),
  );
});
it("closes after an accepted copy job without waiting for the job to finish", async () => {
  mocks.confirm.mockResolvedValue({
    knowledge: { id: 8, name: "Copy" },
    processing_job: { job_id: "job", state: "accepted" },
    completed: false,
  });
  const view = mount();
  fireEvent.click(screen.getByRole("button", { name: "space_copy_ui.create" }));
  await waitFor(() => expect(view.closed).toHaveBeenCalledTimes(1));
  expect(view.created).toHaveBeenCalledTimes(1);
});
it("reuses the same confirmation and idempotency key after a lost acknowledgement", async () => {
  mocks.confirm.mockRejectedValueOnce(new Error("Lost ACK"));
  mount();
  fireEvent.click(screen.getByRole("button", { name: "space_copy_ui.create" }));
  await waitFor(() => expect(mocks.error).toHaveBeenCalled());
  expect(screen.getByText("space_copy_ui.retry_notice")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await waitFor(() => expect(mocks.confirm).toHaveBeenCalledTimes(2));
  expect(mocks.precheck).toHaveBeenCalledTimes(1);
  expect(mocks.confirm.mock.calls[0]).toEqual(mocks.confirm.mock.calls[1]);
});

it.each([25002, 25008, 25009])("keeps the accepted copy identity after recoverable business error %s", async (code) => {
  mocks.confirm.mockRejectedValueOnce(new ApiError({ status_code: code }, { message: "Copy interrupted" }));
  mount();
  fireEvent.click(screen.getByRole("button", { name: "space_copy_ui.create" }));
  await waitFor(() => expect(mocks.error).toHaveBeenCalled());
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await waitFor(() => expect(mocks.confirm).toHaveBeenCalledTimes(2));
  expect(mocks.precheck).toHaveBeenCalledTimes(1);
  expect(mocks.confirm.mock.calls[0]).toEqual(mocks.confirm.mock.calls[1]);
});

it.each([18087, 18088])("reviews a new plan only after explicit stale-plan error %s", async (code) => {
  mocks.confirm.mockRejectedValueOnce(new ApiError({ status_code: code }, { message: "Plan expired" }));
  mount();
  fireEvent.click(screen.getByRole("button", { name: "space_copy_ui.create" }));
  await waitFor(() => expect(mocks.error).toHaveBeenCalled());
  fireEvent.click(screen.getByRole("button", { name: "space_copy_ui.create" }));
  await waitFor(() => expect(mocks.confirm).toHaveBeenCalledTimes(2));
  expect(mocks.precheck).toHaveBeenCalledTimes(2);
  expect(mocks.confirm.mock.calls[0][1].idempotency_key).not.toEqual(mocks.confirm.mock.calls[1][1].idempotency_key);
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
