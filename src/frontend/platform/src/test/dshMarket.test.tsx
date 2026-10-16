import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ContextType } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { userContext } from "@/contexts/userContext";
import { PluginMarketPage } from "@/pages/BuildPage/dsh/PluginMarketPage";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { toast } from "@/components/bs-ui/toast/use-toast";
import { previewMarketBundle, deleteMarketPlugin, getMarketContext, getMarketInstallPolicy, getMarketPlugin, importMarketBundle, listMarketImports, listMarketPlugins, setMarketInstallPolicy } from "@/controllers/API/dshMarket";
import type { MarketPlugin } from "@/controllers/API/dshMarket";
import { getMarketWorkbench, importWorkbenchBundle, listMarketWorkbenches, listWorkbenchImports, previewWorkbenchBundle } from "@/controllers/API/dshWorkbenches";

vi.mock("@/controllers/API/dshMarket", () => ({ previewMarketBundle: vi.fn(), deleteMarketPlugin: vi.fn(), getMarketContext: vi.fn(), getMarketInstallPolicy: vi.fn(), getMarketPlugin: vi.fn(), importMarketBundle: vi.fn(), listMarketImports: vi.fn(), listMarketPlugins: vi.fn(), resumeMarketImport: vi.fn(), setMarketInstallPolicy: vi.fn() }));
vi.mock("@/controllers/API/dshWorkbenches", () => ({ getMarketWorkbench: vi.fn(), importWorkbenchBundle: vi.fn(), listMarketWorkbenches: vi.fn(), listWorkbenchImports: vi.fn(), previewWorkbenchBundle: vi.fn(), resumeWorkbenchImport: vi.fn() }));
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
    vi.mocked(getMarketInstallPolicy).mockResolvedValue({ tenant_id: 2, allow_third_party_plugins: false, allow_third_party_workbenches: false });
    vi.mocked(setMarketInstallPolicy).mockResolvedValue({ tenant_id: 2, allow_third_party_plugins: true, allow_third_party_workbenches: false });
    vi.mocked(listMarketPlugins).mockResolvedValue({ data: [plugin], total: 1 });
    vi.mocked(listMarketImports).mockResolvedValue([]);
    vi.mocked(getMarketPlugin).mockResolvedValue(plugin);
    vi.mocked(deleteMarketPlugin).mockResolvedValue({ id: plugin.id, deleted: true });
    vi.mocked(importMarketBundle).mockResolvedValue({ id: "job", status: "completed", error: "", created_at: "2026-09-10T00:00:00" });
    vi.mocked(listMarketWorkbenches).mockResolvedValue({ data: [{
        id: "a".repeat(32), identity_kind: "repository", workbench_key: "example/workbench", legacy_id: null,
        package_name: "dsh-example-workbench", display_name: "Workbench Demo", description: "Example",
        current_version: { id: "b".repeat(32), version: "1.0.0" }, verification_level: "static",
        updated_at: "2026-10-15T00:00:00",
    }], total: 1 });
    vi.mocked(listWorkbenchImports).mockResolvedValue([]);
    vi.mocked(previewWorkbenchBundle).mockResolvedValue({
        package_name: "dsh-example-workbench", identity_kind: "repository", workbench_key: "example/workbench",
        legacy_id: null, incoming_version: "1.1.0", current_version: "1.0.0", suggested_display_name: "Workbench Demo",
        allowed: true, duplicate: false, reason: "", warnings: ["runtime_not_verified"],
    });
    vi.mocked(importWorkbenchBundle).mockResolvedValue({
        id: "task", status: "completed", error_code: "", error: "", version_id: "b".repeat(32),
        created_at: "2026-10-15T00:00:00",
    });
    vi.mocked(getMarketWorkbench).mockResolvedValue({
        id: "a".repeat(32), identity_kind: "repository", workbench_key: "example/workbench", legacy_id: null,
        package_name: "dsh-example-workbench", display_name: "Workbench Demo", description: "Example",
        current_version: { id: "b".repeat(32), version: "1.0.0", sha256: "c".repeat(64), size_bytes: 1024, artifact_url: "/artifact" },
        verification_level: "static", updated_at: "2026-10-15T00:00:00",
        package_metadata: { repository_url: "https://github.com/example/workbench", patch_entry_id: "example", server_entry: "desktop.js",
            client_entry: "client.js", bundle_patch: "cordis.patch.yml", license: "MIT", node_engine: ">=22", dependencies: [], legacy_manifest: false },
    });
});

describe("DSH market administration", () => {
    it("saves each installation setting for the current tenant", async () => {
        render(view());
        const plugins = await screen.findByRole("switch", { name: "allow_third_party_plugins" });
        const workbenches = screen.getByRole("switch", { name: "allow_third_party_workbenches" });
        expect(plugins).not.toBeChecked();
        expect(workbenches).not.toBeChecked();
        fireEvent.click(plugins);
        await waitFor(() => expect(setMarketInstallPolicy).toHaveBeenCalledWith(2, "allow_third_party_plugins", true));
        await waitFor(() => expect(plugins).toBeChecked());
        expect(workbenches).not.toBeChecked();
    });
    it("keeps the saved setting when an update fails", async () => {
        vi.mocked(setMarketInstallPolicy).mockRejectedValueOnce(new Error("offline"));
        render(view());
        const plugins = await screen.findByRole("switch", { name: "allow_third_party_plugins" });
        fireEvent.click(plugins);
        await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.objectContaining({ variant: "error" })));
        expect(plugins).not.toBeChecked();
        await waitFor(() => expect(getMarketInstallPolicy).toHaveBeenCalledTimes(2));
    });
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
    it.each(["plugin.zip", "plugin.tgz", "plugin.tar.gz"])("uploads %s bound to the login tenant", async (filename) => {
        render(view()); await screen.findByText("Company Demo"); fireEvent.click(screen.getByRole("button", { name: "import" }));
        const file = new File(["bundle"], filename, { type: filename.endsWith(".zip") ? "application/zip" : "application/gzip" });
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
    it("previews and imports a workbench archive in its own section", async () => {
        render(view());
        await userEvent.setup().click(screen.getByRole("tab", { name: "workbenchSection" }));
        await screen.findByText("Workbench Demo");
        fireEvent.click(screen.getByRole("button", { name: "workbenchImport" }));
        const file = new File(["archive"], "workbench.tgz", { type: "application/gzip" });
        fireEvent.change(screen.getByLabelText("workbenchImport", { selector: "input" }), { target: { files: [file] } });
        await screen.findByText("1.0.0 → 1.1.0");
        fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "workbenchImport" }));
        await waitFor(() => expect(importWorkbenchBundle).toHaveBeenCalledWith(file, 2, "", expect.any(AbortSignal), expect.any(Function)));
    });
});
