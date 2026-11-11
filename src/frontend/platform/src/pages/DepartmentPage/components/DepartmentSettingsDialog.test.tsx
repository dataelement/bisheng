import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DepartmentSettingsDialog } from "./DepartmentSettingsDialog";

const mocks = vi.hoisted(() => ({
  update: vi.fn(),
  move: vi.fn(),
  saveTraffic: vi.fn(),
  error: vi.fn(),
  confirm: vi.fn(),
  notify: vi.fn(),
}));
const department = {
  id: 2,
  dept_id: "product",
  name: "Product",
  parent_id: 1,
  path: "/1/2/",
  sort_order: 0,
  source: "local",
  status: "active",
  is_tenant_root: false,
  mounted_tenant_id: null,
  children: [],
};
vi.mock("@/controllers/API/department", () => ({
  getDepartmentAdminsApi: vi.fn(async () => []),
  getDepartmentApi: vi.fn(async () => ({
    ...department,
    default_role_ids: [],
  })),
  getDepartmentAssignableRolesApi: vi.fn(async () => []),
  getDepartmentChildrenApi: vi.fn(async () => [{ id: 1 }]),
  getDepartmentPathTreeApi: vi.fn(async () => ({ roots: [] })),
  updateDepartmentApi: mocks.update,
  moveDepartmentApi: mocks.move,
  deleteDepartmentApi: vi.fn(),
  purgeDepartmentApi: vi.fn(),
  restoreDepartmentApi: vi.fn(),
  unmountTenantApi: vi.fn(),
}));
vi.mock("@/controllers/API/pro", () => ({
  getDepartmentLimitDetailApi: vi.fn(async () => ({ dept_limit: 0 })),
  saveDepartmentLimitApi: mocks.saveTraffic,
}));
vi.mock("@/controllers/request", () => ({
  showApiError: mocks.error,
  handleUiRequest: (fn: () => void) => fn,
}));
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: mocks.confirm,
}));
vi.mock("@/components/bs-comp/selectComponent/DepartmentUsersSelect", () => ({
  default: () => null,
}));
vi.mock("@/components/bs-comp/department/TreeDepartmentSelect", () => ({
  TreeDepartmentSelect: ({ onChange }: { onChange: (id: number) => void }) => (
    <button type="button" onClick={() => onChange(3)}>
      move-parent
    </button>
  ),
}));
vi.mock("@/components/Pro/FlowControl", () => ({ FlowControl: () => null }));
vi.mock("@bisheng/ui", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@bisheng/ui")>()),
  notification: { open: mocks.notify },
}));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.update.mockResolvedValue({});
  mocks.saveTraffic.mockResolvedValue({});
});
afterEach(cleanup);

it("does not move the department twice when another basic setting fails after the move", async () => {
  mocks.update.mockRejectedValueOnce(new Error("Name update rejected"));
  mocks.move.mockResolvedValue({});
  const onClose = vi.fn();
  render(
    <DepartmentSettingsDialog
      dept={department}
      showTrafficControl={false}
      onChanged={vi.fn()}
      onClose={onClose}
    />
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "save" })).not.toBeDisabled()
  );
  fireEvent.change(screen.getByDisplayValue("Product"), {
    target: { value: "Product renamed" },
  });
  fireEvent.click(screen.getByRole("button", { name: "move-parent" }));
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await screen.findByText("bs:organization.partialBasicSave");
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  expect(mocks.move).toHaveBeenCalledTimes(1);
  expect(mocks.update).toHaveBeenCalledTimes(2);
});

async function editBoth() {
  const onChanged = vi.fn();
  const onClose = vi.fn();
  render(
    <DepartmentSettingsDialog
      dept={department}
      showTrafficControl
      onChanged={onChanged}
      onClose={onClose}
    />
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "save" })).not.toBeDisabled()
  );
  fireEvent.change(screen.getByDisplayValue("Product"), {
    target: { value: "Product renamed" },
  });
  fireEvent.mouseDown(
    screen.getByRole("tab", { name: "bs:department.trafficControl" }),
    { button: 0, ctrlKey: false }
  );
  fireEvent.click(screen.getByRole("radio", { name: "system.limit" }));
  fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "12" } });
  fireEvent.mouseDown(
    screen.getByRole("tab", { name: "bs:department.sectionBasic" }),
    { button: 0, ctrlKey: false }
  );
  expect(screen.getByDisplayValue("Product renamed")).toBeVisible();
  return { onChanged, onClose };
}

it("retains edits across tabs and saves basic settings and traffic together", async () => {
  const callbacks = await editBoth();
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(callbacks.onClose).toHaveBeenCalledOnce());
  expect(mocks.update).toHaveBeenCalledWith("product", {
    name: "Product renamed",
  });
  expect(mocks.saveTraffic).toHaveBeenCalledWith(
    expect.objectContaining({ departmentId: 2, deptLimit: 12 })
  );
  expect(callbacks.onChanged).toHaveBeenCalledOnce();
});

it("keeps failed traffic edits, reports partial success, and retries without resubmitting basic changes", async () => {
  const failure = new Error("Traffic update rejected");
  mocks.saveTraffic.mockRejectedValueOnce(failure);
  const callbacks = await editBoth();
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await screen.findByText("bs:organization.partialSave");
  expect(callbacks.onClose).not.toHaveBeenCalled();
  expect(screen.getByRole("spinbutton")).toHaveValue(12);
  expect(mocks.error).toHaveBeenCalledWith(failure);
  expect(mocks.notify).not.toHaveBeenCalledWith(
    expect.objectContaining({ type: "success" })
  );
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(callbacks.onClose).toHaveBeenCalledOnce());
  expect(mocks.update).toHaveBeenCalledTimes(1);
  expect(mocks.saveTraffic).toHaveBeenCalledTimes(2);
});

it("protects unsaved changes when closing the dialog", async () => {
  const callbacks = await editBoth();
  fireEvent.click(screen.getByRole("button", { name: "cancel" }));
  expect(mocks.confirm).toHaveBeenCalledWith(
    expect.objectContaining({ desc: "bs:organization.discardChanges" })
  );
  expect(callbacks.onClose).not.toHaveBeenCalled();
});

it("locks the form while saving so edits cannot be lost on successful close", async () => {
  let finish: (value: object) => void = () => {};
  mocks.update.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  const callbacks = await editBoth();
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  expect(screen.getByDisplayValue("Product renamed")).toBeDisabled();
  await act(async () => finish({}));
  await waitFor(() => expect(callbacks.onClose).toHaveBeenCalledOnce());
});
