import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ContextType } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { userContext } from "@/contexts/userContext";
import { PluginMarketPage } from "@/pages/BuildPage/dsh/PluginMarketPage";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { previewMarketBundle, deleteMarketPlugin, getMarketContext, getMarketPlugin, importMarketBundle, listMarketImports, listMarketPlugins } from "@/controllers/API/dshMarket";
import type { MarketPlugin } from "@/controllers/API/dshMarket";

vi.mock("@/controllers/API/dshMarket", () => ({ previewMarketBundle: vi.fn(), deleteMarketPlugin: vi.fn(), getMarketContext: vi.fn(), getMarketPlugin: vi.fn(), importMarketBundle: vi.fn(), listMarketImports: vi.fn(), listMarketPlugins: vi.fn(), resumeMarketImport: vi.fn() }));
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({ bsConfirm: vi.fn() }));
vi.mock("@/components/bs-ui/toast/use-toast", () => ({ toast: vi.fn() }));

const plugin: MarketPlugin = {
    id: "a".repeat(32), tenant_id: 2, name: "company-demo", display_name: "Company Demo", description: "Internal reporting",
    current_version_id: "b".repeat(32), revision: 2, disabled: false, updated_at: "2026-09-10T00:00:00",
    versions: [{ id: "b".repeat(32), version: "1.0.0", digest: "c".repeat(64),
        manifest: { plugin: { name: "company-demo", display_name: "Company Demo", description: "Internal reporting", publisher: "Company", license: "MIT", desktop_min: "0.1.1", permissions: [], services: [] }, targets: { "darwin-arm64": {} } } }],
};
function view(admin = true, tenant = 2) {
    return <userContext.Provider value={{ user: { user_id: 20, tenant_id: tenant, role: "user", is_child_admin: admin } } as ContextType<typeof userContext>}><PluginMarketPage /></userContext.Provider>;
}
beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(previewMarketBundle).mockResolvedValue({ name: "company-demo", display_name: "Company Demo", current_version: "1.0.0", incoming_version: "1.1.0", allowed: true, reason: "", duplicate: false });
    vi.mocked(getMarketContext).mockResolvedValue({ tenant_id: 2 });
    vi.mocked(listMarketPlugins).mockResolvedValue({ data: [plugin], total: 1 });
    vi.mocked(listMarketImports).mockResolvedValue([]);
    vi.mocked(getMarketPlugin).mockResolvedValue(plugin);
    vi.mocked(deleteMarketPlugin).mockResolvedValue({ id: plugin.id, deleted: true });
    vi.mocked(importMarketBundle).mockResolvedValue({ id: "job", status: "completed", error: "", created_at: "2026-09-10T00:00:00" });
});

describe("DSH market administration", () => {
    it("guards direct navigation before reading administrative data", () => {
        render(view(false)); expect(screen.getByText("forbidden")).toBeInTheDocument();
        expect(getMarketContext).not.toHaveBeenCalled(); expect(listMarketPlugins).not.toHaveBeenCalled();
    });
    it("shows import, details and delete with a simple table", async () => {
        render(view()); await screen.findByText("Company Demo");
        expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
        expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
        expect(screen.getAllByRole("button").map(button => button.textContent)).toEqual(["import", "details", "delete"]);
        expect(screen.getAllByRole("columnheader").map(cell => cell.textContent)).toEqual(["name", "version", "platform", "updated", "actions"]);
    });
    it("resets the page and tenant-bound data when the login tenant changes", async () => {
        const page = render(view()); await screen.findByText("Company Demo");
        expect(listMarketPlugins).toHaveBeenLastCalledWith({ page: 1 }, 2, expect.any(AbortSignal));
        vi.mocked(getMarketContext).mockResolvedValue({ tenant_id: 3 });
        vi.mocked(listMarketPlugins).mockResolvedValue({ data: [], total: 0 });
        page.rerender(view(true, 3));
        await waitFor(() => expect(listMarketPlugins).toHaveBeenLastCalledWith({ page: 1 }, 3, expect.any(AbortSignal)));
        expect(screen.queryByText("Company Demo")).not.toBeInTheDocument();
    });
    it("uploads the selected bundle bound to the login tenant", async () => {
        render(view()); await screen.findByText("Company Demo"); fireEvent.click(screen.getByRole("button", { name: "import" }));
        const file = new File(["bundle"], "plugin.zip", { type: "application/zip" });
        fireEvent.change(screen.getByLabelText("import", { selector: "input" }), { target: { files: [file] } });
        await screen.findByText("1.0.0 → 1.1.0");
        fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "import" }));
        await waitFor(() => expect(importMarketBundle).toHaveBeenCalledWith(file, 2, expect.any(AbortSignal), expect.any(Function)));
    });
    it("blocks confirmation for an older version", async () => {
        vi.mocked(previewMarketBundle).mockResolvedValue({ name: "company-demo", display_name: "Company Demo", current_version: "1.1.0", incoming_version: "1.0.0", allowed: false, reason: "lower_version", duplicate: false });
        render(view()); await screen.findByText("Company Demo");
        fireEvent.click(screen.getByRole("button", { name: "import" }));
        fireEvent.change(screen.getByLabelText("import", { selector: "input" }), { target: { files: [new File(["bundle"], "plugin.zip")] } });
        await screen.findByText("lowerVersion");
        expect(within(screen.getByRole("dialog")).getByRole("button", { name: "import" })).toBeDisabled();
        expect(importMarketBundle).not.toHaveBeenCalled();
    });
    it("waits for preview and rejects oversized bundles before uploading", async () => {
        render(view()); await screen.findByText("Company Demo");
        fireEvent.click(screen.getByRole("button", { name: "import" }));
        const file = new File(["bundle"], "plugin.zip");
        Object.defineProperty(file, "size", { value: 512 * 1024 * 1024 + 1 });
        fireEvent.change(screen.getByLabelText("import", { selector: "input" }), { target: { files: [file] } });
        await screen.findByText("previewFailed");
        expect(previewMarketBundle).not.toHaveBeenCalled();
        expect(within(screen.getByRole("dialog")).getByRole("button", { name: "import" })).toBeDisabled();
    });
    it("deletes after confirmation using the displayed revision and refreshes the list", async () => {
        render(view()); await screen.findByText("Company Demo");
        fireEvent.click(screen.getByRole("button", { name: "delete" }));
        expect(deleteMarketPlugin).not.toHaveBeenCalled();
        vi.mocked(listMarketPlugins).mockResolvedValue({ data: [], total: 0 });
        const confirmation = vi.mocked(bsConfirm).mock.calls[0][0];
        await act(async () => { await confirmation.onOk?.(vi.fn()); });
        expect(deleteMarketPlugin).toHaveBeenCalledWith(plugin);
        await screen.findByText("empty");
        expect(screen.queryByText("Company Demo")).not.toBeInTheDocument();
    });
    it("returns to the preceding page when the last row is deleted", async () => {
        vi.mocked(listMarketPlugins).mockResolvedValue({ data: [plugin], total: 21 });
        render(view()); await screen.findByText("Company Demo");
        fireEvent.click(screen.getByRole("button", { name: "next" }));
        await waitFor(() => expect(listMarketPlugins).toHaveBeenLastCalledWith({ page: 2 }, 2, expect.any(AbortSignal)));
        await screen.findByText("Company Demo");
        fireEvent.click(screen.getByRole("button", { name: "delete" }));
        vi.mocked(listMarketPlugins).mockImplementation(async ({ page }) => ({ data: page === 1 ? [plugin] : [], total: 20 }));
        await act(async () => { await vi.mocked(bsConfirm).mock.calls[0][0].onOk?.(vi.fn()); });
        await waitFor(() => expect(listMarketPlugins).toHaveBeenLastCalledWith({ page: 1 }, 2, expect.any(AbortSignal)));
        expect(screen.queryByRole("button", { name: "next" })).not.toBeInTheDocument();
    });
    it("keeps version details as a read-only view", async () => {
        render(view()); await screen.findByText("Company Demo");
        fireEvent.click(screen.getByRole("button", { name: "details" }));
        const dialog = await screen.findByRole("dialog");
        expect(within(dialog).getByText("versions")).toBeInTheDocument();
        expect(within(dialog).queryByRole("button", { name: "publish" })).not.toBeInTheDocument();
        expect(within(dialog).queryByText("audit")).not.toBeInTheDocument();
    });
});
