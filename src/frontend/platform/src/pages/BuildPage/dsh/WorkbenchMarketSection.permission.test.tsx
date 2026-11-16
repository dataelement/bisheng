import { beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@/test/test-utils";
import userEvent from "@testing-library/user-event";
import * as market from "@/controllers/API/dshMarket";
import * as workbenches from "@/controllers/API/dshWorkbenches";
import { useResourceActions } from "@/components/bs-comp/permission/useResourceActions";
import { WorkbenchMarketSection } from "./WorkbenchMarketSection";

vi.mock("@/components/bs-comp/permission/PermissionDialog", () => ({
    PermissionDialog: (props: { resourceType: string; resourceId: string; resourceName: string; allowAllMembers?: boolean }) => (
        <div data-testid="permission-dialog">{`${props.resourceType}|${props.resourceId}|${props.resourceName}|${String(props.allowAllMembers)}`}</div>
    ),
}));
vi.mock("@/components/bs-comp/permission/useResourceActions", async (importOriginal) => ({
    ...(await importOriginal<typeof import("@/components/bs-comp/permission/useResourceActions")>()),
    useResourceActions: vi.fn(),
}));
vi.mock("@/controllers/API/dshMarket", () => ({ getMarketContext: vi.fn() }));
vi.mock("@/controllers/API/dshWorkbenches", () => ({
    deleteMarketWorkbench: vi.fn(), getMarketWorkbench: vi.fn(), listMarketWorkbenches: vi.fn(),
    listWorkbenchImports: vi.fn(), resumeWorkbenchImport: vi.fn(),
}));

const row = {
    id: "w".repeat(32), revision: 2, identity_kind: "legacy" as const, workbench_key: null, legacy_id: "mind",
    package_name: "mind-workbench", display_name: "Mind map", description: "", verification_level: "static" as const,
    current_version: { id: "v".repeat(32), version: "1.0.0" }, updated_at: "2026-11-16T00:00:00",
};

beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(market.getMarketContext).mockResolvedValue({ tenant_id: 2 });
    vi.mocked(workbenches.listMarketWorkbenches).mockResolvedValue({ data: [row], total: 1 });
    vi.mocked(workbenches.listWorkbenchImports).mockResolvedValue([]);
    vi.mocked(useResourceActions).mockReturnValue({ actions: {}, loading: false });
});

it("opens the all-member permission dialog for a workbench the admin may manage", async () => {
    vi.mocked(useResourceActions).mockReturnValue({ actions: { [row.id]: ["manage_permission"] }, loading: false });
    const user = userEvent.setup();
    render(<WorkbenchMarketSection />);
    await user.click(await screen.findByRole("button", { name: "permission:dialog.tabGrant" }));
    expect(screen.getByTestId("permission-dialog")).toHaveTextContent(`dsh_market_workbench|${row.id}|Mind map|true`);
    expect(useResourceActions).toHaveBeenLastCalledWith("dsh_market_workbench", [row.id], ["manage_permission"]);
});

it("hides the permission entry without permission management rights", async () => {
    render(<WorkbenchMarketSection />);
    expect(await screen.findByText("Mind map")).toBeVisible();
    expect(screen.queryByRole("button", { name: "permission:dialog.tabGrant" })).toBeNull();
});
