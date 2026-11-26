import { fireEvent, render, screen, waitFor, within } from "@/test/test-utils";
import type {
  KunlianApiKeyIssued,
  KunlianApiKeyItem,
  KunlianDirectoryTenantItem,
} from "@/types/api/kunlianApiKey";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { KunlianApiKey } from "./index";

const {
  mockListAll,
  mockIssue,
  mockUpdate,
  mockRotate,
  mockRevoke,
  mockStatusSilent,
  mockTenantsSilent,
  mockCopyText,
  mockConfirm,
} = vi.hoisted(() => ({
  mockListAll: vi.fn(),
  mockIssue: vi.fn(),
  mockUpdate: vi.fn(),
  mockRotate: vi.fn(),
  mockRevoke: vi.fn(),
  mockStatusSilent: vi.fn(),
  mockTenantsSilent: vi.fn(),
  mockCopyText: vi.fn(),
  mockConfirm: vi.fn(),
}));

vi.mock("@/controllers/API/kunlianApiKeys", () => ({
  listAllKunlianApiKeysApi: mockListAll,
  issueKunlianApiKeyApi: mockIssue,
  updateKunlianApiKeyApi: mockUpdate,
  rotateKunlianApiKeyApi: mockRotate,
  revokeKunlianApiKeyApi: mockRevoke,
  getKunlianIntegrationStatusSilentApi: mockStatusSilent,
  getKunlianTenantsSilentApi: mockTenantsSilent,
}));

vi.mock("@/utils", () => ({ copyText: mockCopyText }));

vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: mockConfirm,
}));

const directoryTenants: KunlianDirectoryTenantItem[] = [
  {
    external_tenant_id: "kl-tenant-a",
    name: "Tenant Alpha",
    code: "alpha",
    status: "ACTIVE",
    local_tenant_id: 2,
    binding_enabled: true,
    materialized: true,
  },
  {
    external_tenant_id: "kl-tenant-b",
    name: "Tenant Beta",
    code: "beta",
    status: "ACTIVE",
    local_tenant_id: 3,
    binding_enabled: true,
    materialized: true,
  },
  {
    external_tenant_id: "kl-tenant-s",
    name: "Tenant Suspended",
    code: "suspended",
    status: "SUSPENDED",
    local_tenant_id: null,
    binding_enabled: false,
    materialized: false,
  },
];

const activeKey: KunlianApiKeyItem = {
  id: 1,
  integration_id: "kunlian",
  connection_id: "kunlian-workflow-test",
  policy_revision: 2,
  expires_at: "2099-01-01T00:00:00",
  revoked_at: null,
  created_by: 1,
  create_time: "2026-11-25T10:40:00",
  rotated_from_id: null,
  tenant_ids: ["kl-tenant-a", "kl-tenant-b"],
  capabilities: ["read", "invoke"],
  key_mask: "bs-kl-****AbCd",
};

const expiredKey: KunlianApiKeyItem = {
  ...activeKey,
  id: 2,
  key_mask: "bs-kl-****EfGh",
  expires_at: "2020-01-01T00:00:00",
  tenant_ids: ["kl-tenant-c"],
  capabilities: ["read"],
};

const wildcardRevokedKey: KunlianApiKeyItem = {
  ...activeKey,
  id: 3,
  key_mask: "bs-kl-****IjKl",
  revoked_at: "2026-11-26T01:00:00",
  rotated_from_id: 1,
  tenant_ids: ["*"],
  capabilities: ["read", "write"],
};

describe("KunlianApiKey management page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListAll.mockResolvedValue([activeKey, expiredKey, wildcardRevokedKey]);
    mockStatusSilent.mockResolvedValue({
      connection_id: "kunlian-workflow-test",
    });
    mockTenantsSilent.mockResolvedValue({
      connection_id: "kunlian-workflow-test",
      items: directoryTenants,
    });
  });

  it("renders resolved tenant names, wildcard scope badge, and filters by tenant name", async () => {
    render(<KunlianApiKey />);

    expect(await screen.findByText("bs-kl-****AbCd")).toBeInTheDocument();
    expect(screen.getByText("Tenant Alpha")).toBeInTheDocument();
    expect(screen.getByText("Tenant Beta")).toBeInTheDocument();
    expect(
      screen.getByText("kunlianApiKey.scope.allTenantsTag"),
    ).toBeInTheDocument();

    expect(screen.getByText("kunlianApiKey.status.active")).toBeInTheDocument();
    expect(screen.getByText("kunlianApiKey.status.expired")).toBeInTheDocument();
    expect(screen.getByText("kunlianApiKey.status.revoked")).toBeInTheDocument();

    const searchInput = screen.getByPlaceholderText(
      "kunlianApiKey.filters.searchPlaceholder",
    );
    fireEvent.change(searchInput, { target: { value: "Tenant Alpha" } });

    expect(screen.getByText("bs-kl-****AbCd")).toBeInTheDocument();
    expect(screen.queryByText("bs-kl-****EfGh")).not.toBeInTheDocument();
    expect(screen.queryByText("bs-kl-****IjKl")).not.toBeInTheDocument();
  });

  it("supports selecting active/all directory tenants plus manual paste fallback when issuing", async () => {
    const issuedResponse: KunlianApiKeyIssued = {
      ...activeKey,
      id: 10,
      key_mask: "bs-kl-****ZzYy",
      api_key: "bs-kl-secret-plaintext-token-value-1234567890",
    };
    mockIssue.mockResolvedValue(issuedResponse);

    render(<KunlianApiKey />);
    await screen.findByText("bs-kl-****AbCd");

    fireEvent.click(
      screen.getByRole("button", { name: "kunlianApiKey.actions.issue" }),
    );

    const connectionInput = (await screen.findByLabelText(
      /kunlianApiKey.fields.connectionId/,
    )) as HTMLInputElement;
    await waitFor(() => {
      expect(connectionInput.value).toBe("kunlian-workflow-test");
    });

    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByText("Tenant Alpha")).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "kunlianApiKey.actions.selectActiveTenants",
      }),
    );

    const tenantInput = within(dialog).getByPlaceholderText(
      "kunlianApiKey.form.tenantPlaceholder",
    );
    fireEvent.paste(tenantInput, {
      clipboardData: {
        getData: () => "t-001, kl-tenant-a\nt-001",
      },
    });
    expect(within(dialog).getByText("t-001")).toBeInTheDocument();

    const submitButtons = within(dialog).getAllByRole("button", {
      name: "kunlianApiKey.actions.issue",
    });
    fireEvent.click(submitButtons[submitButtons.length - 1]);

    await waitFor(() => {
      expect(mockIssue).toHaveBeenCalledWith({
        connection_id: "kunlian-workflow-test",
        integration_id: "kunlian",
        tenant_ids: ["kl-tenant-a", "kl-tenant-b", "t-001"],
        capabilities: ["read", "invoke"],
        expires_at: null,
      });
    });

    expect(
      await screen.findByText("bs-kl-secret-plaintext-token-value-1234567890"),
    ).toBeInTheDocument();

    const confirmBtn = screen.getByRole("button", { name: "confirmButton" });
    expect(confirmBtn).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(confirmBtn).toBeEnabled();
    fireEvent.click(confirmBtn);
  });

  it("supports issuing an unrestricted all-tenants key with wildcard [*] and select-all tenants", async () => {
    const issuedAll: KunlianApiKeyIssued = {
      ...activeKey,
      id: 11,
      tenant_ids: ["*"],
      key_mask: "bs-kl-****All1",
      api_key: "bs-kl-all-tenants-secret-token",
    };
    mockIssue.mockResolvedValue(issuedAll);

    render(<KunlianApiKey />);
    await screen.findByText("bs-kl-****AbCd");

    fireEvent.click(
      screen.getByRole("button", { name: "kunlianApiKey.actions.issue" }),
    );
    await screen.findByText("Tenant Suspended");

    // Verify Select all picks active + suspended tenants first
    fireEvent.click(
      screen.getByRole("button", {
        name: "kunlianApiKey.actions.selectAllTenants",
      }),
    );
    expect(
      screen.getByText("kunlianApiKey.form.tenantCount"),
    ).toBeInTheDocument();

    // Switch to all-tenants wildcard mode
    fireEvent.click(screen.getByText("kunlianApiKey.scope.allModeLabel"));
    expect(
      screen.getByText("kunlianApiKey.scope.allAlertTitle"),
    ).toBeInTheDocument();

    const submitButtons = screen.getAllByRole("button", {
      name: "kunlianApiKey.actions.issue",
    });
    fireEvent.click(submitButtons[submitButtons.length - 1]);

    await waitFor(() => {
      expect(mockIssue).toHaveBeenCalledWith({
        connection_id: "kunlian-workflow-test",
        integration_id: "kunlian",
        tenant_ids: ["*"],
        capabilities: ["read", "invoke"],
        expires_at: null,
      });
    });
  });

  it("sends minimal PATCH payload when updating an existing key to wildcard scope", async () => {
    mockUpdate.mockResolvedValue({
      ...activeKey,
      tenant_ids: ["*"],
      capabilities: ["read", "invoke", "publish"],
      policy_revision: 3,
    });

    render(<KunlianApiKey />);
    await screen.findByText("bs-kl-****AbCd");

    const editButtons = screen.getAllByRole("button", { name: "edit" });
    expect(editButtons[2]).toBeDisabled();
    fireEvent.click(editButtons[0]);

    const connectionInput = await screen.findByLabelText(
      /kunlianApiKey.fields.connectionId/,
    );
    expect(connectionInput).toBeDisabled();

    fireEvent.click(screen.getByText("kunlianApiKey.scope.allModeLabel"));
    fireEvent.click(
      screen.getByText("kunlianApiKey.capabilities.publish.label"),
    );
    fireEvent.click(screen.getByRole("button", { name: "save" }));

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledWith(1, {
        tenant_ids: ["*"],
        capabilities: ["read", "invoke", "publish"],
      });
    });
  });

  it("confirms and executes rotate and revoke actions", async () => {
    const rotatedResult: KunlianApiKeyIssued = {
      ...activeKey,
      id: 9,
      rotated_from_id: 1,
      key_mask: "bs-kl-****Rot9",
      api_key: "bs-kl-rotated-secret-value",
    };
    mockRotate.mockResolvedValue(rotatedResult);
    mockRevoke.mockResolvedValue({
      ...activeKey,
      revoked_at: "2026-11-26T05:00:00",
    });
    mockConfirm.mockImplementation(({ onOk }) => onOk(() => {}));

    render(<KunlianApiKey />);
    await screen.findByText("bs-kl-****AbCd");

    const rotateButtons = screen.getAllByRole("button", {
      name: "kunlianApiKey.actions.rotate",
    });
    expect(rotateButtons[2]).toBeDisabled();
    fireEvent.click(rotateButtons[0]);

    await waitFor(() => {
      expect(mockRotate).toHaveBeenCalledWith(1);
    });
    expect(
      await screen.findByText("bs-kl-rotated-secret-value"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "confirmButton" }));

    const revokeButtons = screen.getAllByRole("button", {
      name: "kunlianApiKey.actions.revoke",
    });
    expect(revokeButtons[2]).toBeDisabled();
    fireEvent.click(revokeButtons[0]);

    await waitFor(() => {
      expect(mockRevoke).toHaveBeenCalledWith(1);
    });
  });
});
