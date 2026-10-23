import { useContext, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within, fireEvent } from "@/test/test-utils";
import userEvent from "@testing-library/user-event";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import TenantPage from "./index";
import { CreateTenantDialog } from "./components/CreateTenantDialog";
import { TenantQuotaDialog } from "./components/TenantQuotaDialog";
import { TenantUserDialog } from "./components/TenantUserDialog";
import type { Tenant } from "@/types/api/tenant";
import * as api from "@/controllers/API/tenant";

vi.mock("@/contexts/userContext", async () => ({ userContext: (await import("react")).createContext({ user: {} }) }));
vi.mock("@/contexts/locationContext", async () => ({
  locationContext: (await import("react")).createContext({ appConfig: {} }),
}));
vi.mock("@/controllers/request", () => ({ captureAndAlertRequestErrorHoc: (promise: Promise<unknown>) => promise }));
vi.mock('@bisheng/ui', async () => {
const actual = await vi.importActual<typeof import('@bisheng/ui')>('@bisheng/ui');
const previous = await (() => ({ toast: vi.fn() }))();
const hooks = Reflect.get(previous, 'useToast')?.() ?? {};
return { ...actual, notification: { ...actual.notification, open: Reflect.get(previous, 'toast') ?? Reflect.get(hooks, 'toast') ?? actual.notification.open }, toast: { ...actual.toast, show: Reflect.get(previous, 'message') ?? Reflect.get(hooks, 'message') ?? actual.toast.show } };
});
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: (options: { onOk: (next: () => void) => void }) => options.onOk(() => {}),
}));
vi.mock("@/controllers/API/user", () => ({ getUsersApi: vi.fn(async () => ({ data: [], total: 0 })) }));
vi.mock("@/controllers/API/tenant", () => ({
  getTenantsApi: vi.fn(),
  getTenantApi: vi.fn(),
  updateTenantApi: vi.fn(),
  createTenantApi: vi.fn(),
  updateTenantStatusApi: vi.fn(),
  deleteTenantApi: vi.fn(),
  getTenantQuotaApi: vi.fn(),
  setTenantQuotaApi: vi.fn(),
  getTenantUsersApi: vi.fn(),
  listTenantAdminsApi: vi.fn(),
  grantTenantAdminApi: vi.fn(),
  revokeTenantAdminApi: vi.fn(),
}));

const tenant: Tenant = {
  id: 2,
  tenant_code: "team",
  tenant_name: "Team",
  status: "active",
  logo: null,
  user_count: 2,
  storage_used_gb: 1,
  storage_quota_gb: 5,
  create_time: "2026-10-20T12:00:00",
};
interface FixtureProps {
  children: ReactNode;
  user?: Record<string, unknown>;
  enabled?: boolean;
}
function Fixture({ children, user = { role: "admin" }, enabled = true }: FixtureProps) {
  const location = useContext(locationContext),
    currentUser = useContext(userContext);
  return (
    <locationContext.Provider value={{ ...location, appConfig: { multiTenantEnabled: enabled } }}>
      <userContext.Provider value={{ ...currentUser, user }}>{children}</userContext.Provider>
    </locationContext.Provider>
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getTenantsApi).mockResolvedValue({
    data: [
      tenant,
      { ...tenant, id: 1, tenant_name: "Root" },
      { ...tenant, id: 3, tenant_name: "Archived", tenant_code: "archived", status: "archived" },
      { ...tenant, id: 4, tenant_name: "Disabled", status: "disabled" },
    ],
    total: 4,
  });
  vi.mocked(api.getTenantApi).mockResolvedValue({
    ...tenant,
    root_dept_id: 1,
    contact_name: "Contact",
    contact_phone: "123",
    contact_email: "test@example.com",
    quota_config: {},
    storage_config: {},
    admin_users: [],
  });
  vi.mocked(api.getTenantQuotaApi).mockResolvedValue({ quota_config: { storage_gb: 5 }, usage: { storage_gb: 1 } });
  vi.mocked(api.getTenantUsersApi).mockResolvedValue({
    data: [
      { user_id: 7, user_name: "Admin", external_id: "admin-7" },
      { user_id: 8, user_name: "Member" },
    ],
    total: 2,
  });
  vi.mocked(api.listTenantAdminsApi).mockResolvedValue({ user_ids: [7] });
  for (const fn of [
    api.updateTenantApi,
    api.updateTenantStatusApi,
    api.deleteTenantApi,
    api.setTenantQuotaApi,
    api.grantTenantAdminApi,
    api.revokeTenantAdminApi,
  ])
    vi.mocked(fn).mockResolvedValue({});
});

describe("Tenant module", () => {
  it("keeps super-user and deployment guards ahead of requests", async () => {
    const first = render(
      <Fixture user={{ role: "user", is_child_admin: true }}>
        <TenantPage />
      </Fixture>,
    );
    expect(api.getTenantsApi).not.toHaveBeenCalled();
    first.unmount();
    render(
      <Fixture enabled={false}>
        <TenantPage />
      </Fixture>,
    );
    expect(api.getTenantsApi).not.toHaveBeenCalled();
  });
  it("keeps Root protected, archived rows terminal, and child actions available", async () => {
    render(
      <Fixture>
        <TenantPage />
      </Fixture>,
    );
    const root = within((await screen.findByText("Root")).closest("tr")!);
    expect(root.queryByRole("button", { name: "tenant.disable" })).not.toBeInTheDocument();
    const archived = within(screen.getByText("Archived").closest("tr")!);
    expect(archived.queryByRole("button", { name: "edit" })).not.toBeInTheDocument();
    expect(archived.queryByRole("button", { name: "tenant.enable" })).not.toBeInTheDocument();
    expect(archived.getByRole("button", { name: "delete" })).toBeEnabled();
    await userEvent.click(
      within(screen.getByText("Team").closest("tr")!).getByRole("button", { name: "tenant.disable" }),
    );
    await waitFor(() => expect(api.updateTenantStatusApi).toHaveBeenCalledWith(2, "disabled"));
  });
  it("requires an exact tenant code before deleting an archived tenant", async () => {
    render(
      <Fixture>
        <TenantPage />
      </Fixture>,
    );
    await userEvent.click(
      within((await screen.findByText("Archived")).closest("tr")!).getByRole("button", { name: "delete" }),
    );
    const input = screen.getByPlaceholderText("tenant.enterCodeToConfirm");
    const confirm = screen.getAllByRole("button", { name: "delete" }).at(-1)!;
    expect(confirm).toBeDisabled();
    await userEvent.type(input, "wrong");
    expect(confirm).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, "archived");
    await userEvent.click(confirm);
    await waitFor(() => expect(api.deleteTenantApi).toHaveBeenCalledWith(3));
  });
  it("edits a tenant without sending an immutable code or admin assignments", async () => {
    const onSuccess = vi.fn();
    render(<CreateTenantDialog tenant={tenant} onClose={vi.fn()} onSuccess={onSuccess} />);
    await waitFor(() => expect(screen.getAllByRole("textbox")[0]).toHaveValue("Team"));
    const [name, code] = screen.getAllByRole("textbox");
    expect(code).toBeDisabled();
    await userEvent.clear(name);
    await userEvent.type(name, "Renamed");
    await userEvent.click(screen.getByRole("button", { name: "confirm" }));
    await waitFor(() =>
      expect(api.updateTenantApi).toHaveBeenCalledWith(2, {
        tenant_name: "Renamed",
        logo: "",
        contact_name: "Contact",
        contact_phone: "123",
        contact_email: "test@example.com",
      }),
    );
    expect(onSuccess).toHaveBeenCalledOnce();
    expect(api.createTenantApi).not.toHaveBeenCalled();
  });
  it.each([
    ["0", "tenant.quotaTooSmall"],
    ["100000", "tenant.quotaTooLarge"],
    ["1.23", "tenant.quotaPrecision"],
  ])("keeps invalid quota %s visible and rejects saving", async (value, error) => {
    render(<TenantQuotaDialog tenant={tenant} onClose={vi.fn()} onSuccess={vi.fn()} />);
    const input = await screen.findByRole("spinbutton");
    fireEvent.change(input, { target: { value } });
    expect(input).toHaveValue(Number(value));
    expect(screen.getByText(error)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "confirm" })).toBeDisabled();
    expect(api.setTenantQuotaApi).not.toHaveBeenCalled();
  });
  it("preserves decimal quota payloads and blank unlimited values", async () => {
    render(<TenantQuotaDialog tenant={tenant} onClose={vi.fn()} onSuccess={vi.fn()} />);
    const input = await screen.findByRole("spinbutton");
    fireEvent.change(input, { target: { value: "1.1" } });
    await userEvent.click(screen.getByRole("button", { name: "confirm" }));
    await waitFor(() => expect(api.setTenantQuotaApi).toHaveBeenCalledWith(2, { storage_gb: 1.1 }));
    fireEvent.change(input, { target: { value: "" } });
    await userEvent.click(screen.getByRole("button", { name: "confirm" }));
    await waitFor(() => expect(api.setTenantQuotaApi).toHaveBeenLastCalledWith(2, {}));
  });
  it("grants and revokes child admins while Root has no admin actions", async () => {
    const first = render(<TenantUserDialog tenant={tenant} onClose={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "tenant.promoteAdmin" }));
    await waitFor(() => expect(api.grantTenantAdminApi).toHaveBeenCalledWith(2, 8));
    await userEvent.click(screen.getByRole("button", { name: "tenant.revokeAdmin" }));
    await waitFor(() => expect(api.revokeTenantAdminApi).toHaveBeenCalledWith(2, 7));
    first.unmount();
    render(<TenantUserDialog tenant={{ ...tenant, id: 1 }} onClose={vi.fn()} />);
    await screen.findByText("Member");
    expect(screen.queryByRole("button", { name: "tenant.promoteAdmin" })).not.toBeInTheDocument();
  });

  it("exposes edit and quota field labels to assistive technology", async () => {
    const edit = render(<CreateTenantDialog tenant={tenant} onClose={vi.fn()} onSuccess={vi.fn()} />);
    expect(await screen.findByRole("textbox", { name: "tenant.name" })).toBeInTheDocument();
    edit.unmount();
    render(<TenantQuotaDialog tenant={tenant} onClose={vi.fn()} onSuccess={vi.fn()} />);
    expect(await screen.findByRole("spinbutton", { name: "tenant.knowledgeStorageUsage (GB)" })).toBeInTheDocument();
  });

  it('keeps the deprecated create path inactive', async () => {
    render(<CreateTenantDialog tenant={null} onClose={vi.fn()} onSuccess={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'confirm' })).toBeDisabled();
    expect(api.createTenantApi).not.toHaveBeenCalled();
  });
  it.each(['0.1', '99999'])('accepts quota boundary %s', async (value) => {
    render(<TenantQuotaDialog tenant={tenant} onClose={vi.fn()} onSuccess={vi.fn()} />);
    fireEvent.change(await screen.findByRole('spinbutton'), { target: { value } });
    await userEvent.click(screen.getByRole('button', { name: 'confirm' }));
    await waitFor(() => expect(api.setTenantQuotaApi).toHaveBeenCalledWith(2, { storage_gb: Number(value) }));
  });
  it('renders unlimited quota as blank', async () => {
    vi.mocked(api.getTenantQuotaApi).mockResolvedValueOnce({ quota_config: { storage_gb: -1 }, usage: {} });
    render(<TenantQuotaDialog tenant={tenant} onClose={vi.fn()} onSuccess={vi.fn()} />);
    expect(await screen.findByRole('spinbutton')).toHaveValue(null);
  });
});
