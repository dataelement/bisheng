import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ContextType } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { userContext } from "@/contexts/userContext";
import { PluginMarketPage } from "@/pages/BuildPage/dsh/PluginMarketPage";
import { DshPage } from "@/pages/DshPage";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { notification } from "@bisheng/ui";
import { previewMarketBundle, deleteMarketPlugin, getMarketContext, getMarketInstallPolicy, getMarketPlugin, importMarketBundle, listMarketImports, listMarketPlugins, setMarketInstallPolicy } from "@/controllers/API/dshMarket";
import type { MarketPlugin } from "@/controllers/API/dshMarket";
import { deleteMarketWorkbench, getMarketWorkbench, importWorkbenchBundle, listMarketWorkbenches, listWorkbenchImports, previewWorkbenchBundle } from "@/controllers/API/dshWorkbenches";

vi.mock("@/controllers/API/dshMarket", () => ({ previewMarketBundle: vi.fn(), deleteMarketPlugin: vi.fn(), getMarketContext: vi.fn(), getMarketInstallPolicy: vi.fn(), getMarketPlugin: vi.fn(), importMarketBundle: vi.fn(), listMarketImports: vi.fn(), listMarketPlugins: vi.fn(), resumeMarketImport: vi.fn(), setMarketInstallPolicy: vi.fn() }));
vi.mock("@/controllers/API/dshWorkbenches", () => ({ deleteMarketWorkbench: vi.fn(), getMarketWorkbench: vi.fn(), importWorkbenchBundle: vi.fn(), listMarketWorkbenches: vi.fn(), listWorkbenchImports: vi.fn(), previewWorkbenchBundle: vi.fn(), resumeWorkbenchImport: vi.fn() }));
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({ bsConfirm: vi.fn() }));
vi.mock("@/hooks/useDshBrowserConfig", () => ({
    useDshBrowserConfig: () => ({ config: { enabled: true, management_enabled: true } }),
}));
vi.mock("@/pages/SystemPage/dsh", () => ({ DshManagement: () => <div data-testid="dsh-management" /> }));
vi.mock('@bisheng/ui', async () => {
const actual = await vi.importActual<typeof import('@bisheng/ui')>('@bisheng/ui');
const previous = await (() => ({ toast: vi.fn() }))();
const hooks = Reflect.get(previous, 'useToast')?.() ?? {};
return { ...actual, notification: { ...actual.notification, open: Reflect.get(previous, 'toast') ?? Reflect.get(hooks, 'toast') ?? actual.notification.open }, toast: { ...actual.toast, show: Reflect.get(previous, 'message') ?? Reflect.get(hooks, 'message') ?? actual.toast.show } };
});

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
        id: "a".repeat(32), revision: 4, identity_kind: "repository", workbench_key: "example/workbench", legacy_id: null,
        package_name: "dsh-example-workbench", display_name: "Workbench Demo", description: "Example",
        current_version: { id: "b".repeat(32), version: "1.0.0" }, verification_level: "static",
        updated_at: "2026-10-15T00:00:00",
    }], total: 1 });
    vi.mocked(deleteMarketWorkbench).mockResolvedValue({ id: "a".repeat(32), deleted: true });
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
        id: "a".repeat(32), revision: 4, identity_kind: "repository", workbench_key: "example/workbench", legacy_id: null,
        package_name: "dsh-example-workbench", display_name: "Workbench Demo", description: "Example",
        current_version: { id: "b".repeat(32), version: "1.0.0", sha256: "c".repeat(64), size_bytes: 1024, artifact_url: "/artifact" },
        verification_level: "static", updated_at: "2026-10-15T00:00:00",
        package_metadata: { repository_url: "https://github.com/example/workbench", patch_entry_id: "example", server_entry: "desktop.js",
            client_entry: "client.js", bundle_patch: "cordis.patch.yml", license: "MIT", node_engine: ">=22", dependencies: [], legacy_manifest: false },
    });
});

describe("DSH market administration", () => {
    it("keeps the market selector beside the page tabs and removes it when leaving the market", async () => {
        const { container } = render(
            <MemoryRouter initialEntries={["/dsh?tab=plugins"]}>
                <userContext.Provider value={{ user: { user_id: 20, tenant_id: 2, role: "admin" } } as ContextType<typeof userContext>}>
                    <DshPage />
                </userContext.Provider>
            </MemoryRouter>,
        );
        await screen.findByText("Company Demo");
        const header = container.querySelector("[data-dsh-header]");
        const selector = screen.getByRole("radiogroup", { name: "marketSections" });
        expect(header).toContainElement(selector);
        expect(header).toContainElement(screen.getByRole("tab", { name: "dsh.enterprisePlugins" }));
        expect(screen.getAllByRole("radiogroup", { name: "marketSections" })).toHaveLength(1);

        await userEvent.setup().click(screen.getByRole("radio", { name: "workbenchSection" }));
        await screen.findByText("Workbench Demo");
        expect(header).toContainElement(selector);
        expect(screen.queryByText("Company Demo")).not.toBeInTheDocument();

        await userEvent.setup().click(screen.getByRole("tab", { name: "dsh.unified.usage" }));
        expect(screen.getByTestId("dsh-management")).toBeInTheDocument();
        expect(screen.queryByRole("radiogroup", { name: "marketSections" })).not.toBeInTheDocument();
    });
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
        await waitFor(() => expect(notification.open).toHaveBeenCalledWith(expect.objectContaining({ type: "error" })));
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
        expect(screen.getByRole("button", { name: /^import$/ })).toBeInTheDocument();
        expect(within(screen.getByRole("table")).getAllByRole("button").map(button => button.textContent)).toEqual(["details", "delete"]);
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
    it.each(["plugin.zip", "plugin.tgz", "plugin.tar.gz"])("uploads %s bound to the login tenant", async (name) => {
        render(view()); await screen.findByText("Company Demo"); fireEvent.click(screen.getByRole("button", { name: "import" }));
        const file = new File(["bundle"], name, { type: name.endsWith(".zip") ? "application/zip" : "application/gzip" });
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
        fireEvent.click(screen.getByRole("button", { name: "pagination.next" }));
        await waitFor(() => expect(listMarketPlugins).toHaveBeenLastCalledWith({ page: 2 }, 2, expect.any(AbortSignal)));
        await screen.findByText("Company Demo");
        fireEvent.click(screen.getByRole("button", { name: "delete" }));
        vi.mocked(listMarketPlugins).mockImplementation(async ({ page }) => ({ data: page === 1 ? [plugin] : [], total: 20 }));
        await act(async () => { await vi.mocked(bsConfirm).mock.calls[0][0].onOk?.(vi.fn()); });
        await waitFor(() => expect(listMarketPlugins).toHaveBeenLastCalledWith({ page: 1 }, 2, expect.any(AbortSignal)));
        expect(screen.getByRole("button", { name: "pagination.next" })).toBeDisabled();
    });
    it("keeps version details as a read-only view", async () => {
        render(view()); await screen.findByText("Company Demo");
        fireEvent.click(screen.getByRole("button", { name: "details" }));
        const dialog = await screen.findByRole("dialog");
        expect(within(dialog).getByText("versions")).toBeInTheDocument();
        expect(within(dialog).queryByRole("button", { name: "publish" })).not.toBeInTheDocument();
        expect(within(dialog).queryByText("audit")).not.toBeInTheDocument();
    });
    it("shows the plugin overwrite notice from the preview flag", async () => {
        vi.mocked(previewMarketBundle).mockResolvedValue({ name: "company-demo", display_name: "Company Demo", current_version: "1.0.0", incoming_version: "1.0.0", allowed: true, reason: "", duplicate: false, overwrite: true });
        render(view()); await screen.findByText("Company Demo");
        fireEvent.click(screen.getByRole("button", { name: "import" }));
        fireEvent.change(screen.getByLabelText("import", { selector: "input" }), { target: { files: [new File(["bundle"], "plugin.zip")] } });
        await screen.findByText("overwriteVersion");
        expect(within(screen.getByRole("dialog")).getByRole("button", { name: "import" })).toBeEnabled();
    });
    it("confirms workbench deletion with revision, clears detail and reloads", async () => {
        render(view());
        await userEvent.setup().click(screen.getByRole("radio", { name: "workbenchSection" }));
        await screen.findByText("Workbench Demo");
        fireEvent.click(screen.getByRole("button", { name: "delete" }));
        fireEvent.click(screen.getByRole("button", { name: "details" }));
        await screen.findByRole("dialog");
        expect(deleteMarketWorkbench).not.toHaveBeenCalled();
        const confirmation = vi.mocked(bsConfirm).mock.calls[0][0];
        expect(confirmation.desc).toBe("workbenchDeleteConfirm");
        vi.mocked(listMarketWorkbenches).mockResolvedValue({ data: [], total: 0 });
        const close = vi.fn(() => confirmation.onClose?.());
        await act(async () => { await confirmation.onOk?.(close); });
        expect(deleteMarketWorkbench).toHaveBeenCalledWith("a".repeat(32), 4, 2, expect.any(AbortSignal));
        await screen.findByText("workbenchEmpty");
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
        expect(close).toHaveBeenCalledOnce();
        expect(notification.open).toHaveBeenCalledWith(expect.objectContaining({ title: "workbenchDeleted" }));
    });
    it("cancels workbench deletion without a request and locks duplicate confirmation", async () => {
        render(view());
        await userEvent.setup().click(screen.getByRole("radio", { name: "workbenchSection" }));
        await screen.findByText("Workbench Demo");
        const button = screen.getByRole("button", { name: "delete" });
        act(() => { fireEvent.click(button); fireEvent.click(button); });
        expect(bsConfirm).toHaveBeenCalledOnce();
        const confirmation = vi.mocked(bsConfirm).mock.calls[0][0];
        act(() => { confirmation.onCancel?.(); confirmation.onClose?.(); });
        await act(async () => { await confirmation.onOk?.(vi.fn()); });
        expect(deleteMarketWorkbench).not.toHaveBeenCalled();
        expect(screen.getByText("Workbench Demo")).toBeInTheDocument();
        fireEvent.click(button);
        expect(bsConfirm).toHaveBeenCalledTimes(2);
    });
    it("reports failed workbench deletion and retains the row", async () => {
        vi.mocked(deleteMarketWorkbench).mockRejectedValue(new Error("offline"));
        render(view());
        await userEvent.setup().click(screen.getByRole("radio", { name: "workbenchSection" }));
        await screen.findByText("Workbench Demo");
        fireEvent.click(screen.getByRole("button", { name: "delete" }));
        const close = vi.fn();
        await act(async () => { await vi.mocked(bsConfirm).mock.calls[0][0].onOk?.(close); });
        expect(screen.getByText("Workbench Demo")).toBeInTheDocument();
        expect(listMarketWorkbenches).toHaveBeenCalledOnce();
        expect(close).not.toHaveBeenCalled();
        expect(notification.open).toHaveBeenCalledWith(expect.objectContaining({ type: "error" }));
        expect(screen.getByRole("button", { name: "delete" })).toBeEnabled();
        vi.mocked(deleteMarketWorkbench).mockResolvedValue({ id: "a".repeat(32), deleted: true });
        await act(async () => { await vi.mocked(bsConfirm).mock.calls[0][0].onOk?.(close); });
        expect(deleteMarketWorkbench).toHaveBeenCalledTimes(2);
        expect(close).toHaveBeenCalledOnce();
    });
    it("returns from an empty last workbench page after deletion", async () => {
        vi.mocked(listMarketWorkbenches).mockResolvedValue({ data: [await getMarketWorkbench("fixture")], total: 21 });
        render(view());
        await userEvent.setup().click(screen.getByRole("radio", { name: "workbenchSection" }));
        await screen.findByText("Workbench Demo");
        fireEvent.click(screen.getByRole("button", { name: "pagination.next" }));
        await waitFor(() => expect(listMarketWorkbenches).toHaveBeenLastCalledWith(2, 2, expect.any(AbortSignal)));
        await screen.findByText("Workbench Demo");
        fireEvent.click(screen.getByRole("button", { name: "delete" }));
        vi.mocked(listMarketWorkbenches).mockResolvedValue({ data: [], total: 20 });
        await act(async () => { await vi.mocked(bsConfirm).mock.calls[0][0].onOk?.(vi.fn()); });
        await waitFor(() => expect(listMarketWorkbenches).toHaveBeenLastCalledWith(2, 1, expect.any(AbortSignal)));
    });
    it.each(["tenant", "unmount"])("invalidates a pending workbench confirmation on %s", async mode => {
        const page = render(view());
        await userEvent.setup().click(screen.getByRole("radio", { name: "workbenchSection" }));
        await screen.findByText("Workbench Demo");
        fireEvent.click(screen.getByRole("button", { name: "delete" }));
        const confirmation = vi.mocked(bsConfirm).mock.calls[0][0];
        if (mode === "tenant") page.rerender(view(true, 3)); else page.unmount();
        expect(confirmation.signal?.aborted).toBe(true);
        await act(async () => { await confirmation.onOk?.(vi.fn()); });
        expect(deleteMarketWorkbench).not.toHaveBeenCalled();
    });
    it.each(["tenant", "unmount"])("ignores a late workbench delete result after %s and prevents repeated requests", async mode => {
        let resolve: (value: { id: string; deleted: true }) => void = () => undefined;
        vi.mocked(deleteMarketWorkbench).mockReturnValue(new Promise(fulfill => { resolve = fulfill; }));
        const page = render(view());
        await userEvent.setup().click(screen.getByRole("radio", { name: "workbenchSection" }));
        await screen.findByText("Workbench Demo");
        fireEvent.click(screen.getByRole("button", { name: "delete" }));
        const confirmation = vi.mocked(bsConfirm).mock.calls[0][0];
        const close = vi.fn();
        let pending: unknown;
        act(() => { pending = confirmation.onOk?.(close); });
        await act(async () => { await confirmation.onOk?.(close); });
        expect(deleteMarketWorkbench).toHaveBeenCalledOnce();
        if (mode === "tenant") page.rerender(view(true, 3)); else page.unmount();
        await act(async () => { resolve({ id: "a".repeat(32), deleted: true }); await pending; });
        expect(close).not.toHaveBeenCalled();
        expect(notification.open).not.toHaveBeenCalledWith(expect.objectContaining({ title: "workbenchDeleted" }));
    });
    it("previews and imports a workbench archive in its own section", async () => {
        render(view());
        await userEvent.setup().click(screen.getByRole("radio", { name: "workbenchSection" }));
        await screen.findByText("Workbench Demo");
        fireEvent.click(screen.getByRole("button", { name: "workbenchImport" }));
        const file = new File(["archive"], "workbench.tgz", { type: "application/gzip" });
        fireEvent.change(screen.getByLabelText("workbenchImport", { selector: "input" }), { target: { files: [file] } });
        await screen.findByText("1.0.0 → 1.1.0");
        fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "workbenchImport" }));
        await waitFor(() => expect(importWorkbenchBundle).toHaveBeenCalledWith(file, 2, "", expect.any(AbortSignal), expect.any(Function)));
    });
});
