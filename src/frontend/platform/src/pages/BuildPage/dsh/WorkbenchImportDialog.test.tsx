import React, { type ComponentProps, type ReactNode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import request from "@/controllers/request";
import { notification } from "@bisheng/ui";
import type { WorkbenchImport, WorkbenchPreview } from "@/controllers/API/dshWorkbenches";
import en from "../../../../public/locales/en-US/dshMarket.json";
import errors from "../../../../../packages/locales/src/api_errors/en.json";
import { WorkbenchImportDialog } from "./WorkbenchImportDialog";

vi.unmock("react-i18next");
vi.mock("@bisheng/ui", () => ({
    Button: ({ children, disabled, onClick }: ComponentProps<"button">) => <button disabled={disabled} onClick={onClick}>{children}</button>,
    Input: (props: ComponentProps<"input">) => <input {...props} />,
    notification: { open: vi.fn() },
}));
vi.mock("@/components/bs-ui/dialog", () => ({
    Dialog: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    DialogContent: ({ children }: { children: ReactNode }) => <div role="dialog">{children}</div>,
    DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
    DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
}));

const originalAdapter = request.defaults.adapter;
const preview = (name: string, extra: Partial<WorkbenchPreview> = {}): WorkbenchPreview => ({
    package_name: name, identity_kind: "repository", workbench_key: "org/" + name, legacy_id: null,
    incoming_version: "2.0.0", current_version: "1.0.0", suggested_display_name: "Name " + name,
    allowed: true, duplicate: false, reason: "", warnings: [], ...extra,
});
const task = (extra: Partial<WorkbenchImport> = {}): WorkbenchImport => ({
    id: "task", status: "completed", error_code: "", error: "", version_id: "version", created_at: "2026-10-15T00:00:00", ...extra,
});
type Call = { name: string; url: string; tenant: unknown; body: FormData; aborted: () => boolean };
let calls: Call[];
let onPreview: (name: string) => unknown | Promise<unknown>;
let onImport: (name: string) => unknown | Promise<unknown>;
const ok = (data: unknown) => ({ status_code: 200, data });
const invalid = { status_code: 26205, status_message: "Invalid workbench", data: {
    code: "WORKBENCH_CONFIG_INVALID", rule: "WB09", field: "config.model", message: "Expected an object",
} };

beforeEach(() => {
    vi.clearAllMocks();
    calls = [];
    onPreview = name => ok(preview(name));
    onImport = () => ok(task());
    request.defaults.adapter = async config => {
        const body = config.data as FormData;
        const name = (body.get("file") as File).name;
        const url = config.url || "";
        calls.push({ name, url, body, tenant: config.headers.get("x-dsh-market-tenant"), aborted: () => config.signal?.aborted === true });
        const isPreview = url.endsWith("/preview");
        if (!isPreview) config.onUploadProgress?.({ loaded: 5, total: 10, bytes: 5, lengthComputable: true, upload: true });
        const data = await (isPreview ? onPreview(name) : onImport(name));
        return { config, status: 200, statusText: "OK", headers: {}, data };
    };
});
afterEach(() => { request.defaults.adapter = originalAdapter; });

async function openDialog() {
    const i18n = createInstance();
    await i18n.init({ lng: "en-US", defaultNS: "dshMarket", resources: { "en-US": { dshMarket: en, api_errors: errors } }, interpolation: { escapeValue: false } });
    const onClose = vi.fn();
    const onImported = vi.fn();
    const view = (tenant: number) => <I18nextProvider i18n={i18n}><WorkbenchImportDialog tenant={tenant} onClose={onClose} onImported={onImported} /></I18nextProvider>;
    return { ...render(view(7)), view, onClose, onImported };
}
function select(...names: string[]) {
    fireEvent.change(screen.getByLabelText(en.workbenchImport), { target: { files: names.map(name => new File([name], name)) } });
}
async function confirm(count: number) {
    const button = await screen.findByRole("button", { name: "Import valid files (" + count + ")" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
}
function deferred() {
    let resolve: (value: unknown) => void = () => undefined;
    const promise = new Promise<unknown>(fulfill => { resolve = fulfill; });
    return { promise, resolve };
}

describe("sequential workbench imports through the request adapter", () => {
    it("imports a version upgrade and another good file while keeping a rejected TGZ visible", async () => {
        const { onImported, onClose } = await openDialog();
        onPreview = name => name === "bad.tgz" ? invalid : ok(preview(name));
        select("upgrade.tgz", "bad.tgz", "good.tgz");
        expect(screen.getByLabelText(en.workbenchImport)).toHaveAttribute("multiple");
        expect(screen.getByLabelText(en.workbenchImport)).toHaveAttribute("accept", ".tgz,application/gzip");
        expect(await screen.findByRole("alert")).toHaveTextContent("Expected an object");
        expect(screen.getByRole("alert")).toHaveTextContent("Field: config.model");
        expect(screen.getByRole("alert")).toHaveTextContent("Rule: WB09");
        await confirm(2);
        await waitFor(() => expect(onImported).toHaveBeenCalledOnce());
        expect(calls.map(call => call.name)).toEqual(["upgrade.tgz", "bad.tgz", "good.tgz", "upgrade.tgz", "good.tgz"]);
        expect(calls.every(call => call.tenant === "7")).toBe(true);
        expect(calls.every(call => !call.url.includes("batch"))).toBe(true);
        expect(screen.getByText("2 completed · 0 failed · 1 rejected")).toBeInTheDocument();
        expect(screen.getByText(/bad.tgz ·/)).toBeInTheDocument();
        expect(screen.getAllByText("1.0.0 → 2.0.0")).toHaveLength(2);
        expect(onClose).not.toHaveBeenCalled();
        expect(screen.getByRole("dialog")).toBeInTheDocument();
    });

    it("continues after failed task and API exception and reports their filenames and reasons", async () => {
        const { onImported } = await openDialog();
        onImport = name => name === "task-fail.tgz" ? ok(task({ status: "failed", error_code: "WORKBENCH_VERSION_CONFLICT", error: "Version changed during upload" }))
            : name === "api-fail.tgz" ? invalid : ok(task());
        select("task-fail.tgz", "api-fail.tgz", "good.tgz");
        await confirm(3);
        await waitFor(() => expect(onImported).toHaveBeenCalledOnce());
        expect(screen.getByText("1 completed · 2 failed · 0 rejected")).toBeInTheDocument();
        expect(screen.getByText(/Version changed during upload/)).toBeInTheDocument();
        expect(screen.getByText(/Version changed during upload/)).toHaveTextContent(en.workbenchVersionConflict);
        expect(screen.getByText(/task-fail.tgz ·/)).toBeInTheDocument();
        expect(screen.getByText(/api-fail.tgz ·/)).toBeInTheDocument();
        expect(screen.getAllByRole("alert").some(alert => alert.textContent?.includes("Expected an object"))).toBe(true);
        expect(calls.filter(call => !call.url.endsWith("/preview"))).toHaveLength(3);
        select("reselected.tgz");
        await screen.findByText("Name reselected.tgz");
        expect(screen.queryByText(/task-fail.tgz ·/)).not.toBeInTheDocument();
    });

    it("preserves single custom display name and idempotent duplicate imports", async () => {
        const { onClose } = await openDialog();
        onPreview = name => ok(preview(name, { duplicate: true }));
        select("single.tgz");
        await screen.findByText(en.workbenchDuplicate);
        fireEvent.change(screen.getByLabelText(en.workbenchDisplayName), { target: { value: "  My workbench  " } });
        fireEvent.click(screen.getByRole("button", { name: en.workbenchImport }));
        await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
        expect(calls[1].body.get("display_name")).toBe("My workbench");
        expect(calls[1].url).toBe("/api/v1/dsh/market/admin/workbenches/imports");
    });

    it("imports allowed duplicates in a multiple selection and blocks disallowed versions only", async () => {
        await openDialog();
        onPreview = name => ok(preview(name, name === "duplicate.tgz" ? { duplicate: true }
            : name === "old.tgz" ? { allowed: false, reason: "lower_version" } : {}));
        select("duplicate.tgz", "old.tgz", "good.tgz");
        await screen.findByText(en.workbenchLowerVersion);
        expect(screen.getByText(en.workbenchBatch.status.duplicate)).toBeInTheDocument();
        await confirm(2);
        await screen.findByText("2 completed · 0 failed · 1 rejected");
        expect(calls.filter(call => !call.url.endsWith("/preview")).map(call => call.name)).toEqual(["duplicate.tgz", "good.tgz"]);
    });

    it.each([
        ["lower_version", en.workbenchLowerVersion],
        ["version_conflict", en.workbenchVersionConflict],
        ["identity_conflict", en.workbenchIdentityConflict],
    ])("translates %s task failures while retaining raw details", async (code, message) => {
        await openDialog();
        onImport = () => ok(task({ status: "failed", error_code: code, error: code }));
        select("single.tgz");
        await screen.findByText("Name single.tgz");
        await waitFor(() => expect(screen.getByRole("button", { name: en.workbenchImport })).toBeEnabled());
        fireEvent.click(screen.getByRole("button", { name: en.workbenchImport }));
        const alert = await screen.findByRole("alert");
        expect(alert).toHaveTextContent(message);
        expect(alert).toHaveTextContent(code);
    });

    it("counts a historical duplicate rejected by the version policy as rejected", async () => {
        await openDialog();
        onPreview = name => ok(preview(name, name === "historical.tgz" ? { duplicate: true, allowed: false, reason: "lower_version" } : {}));
        select("historical.tgz", "good.tgz");
        await screen.findByText(en.workbenchLowerVersion);
        expect(screen.getByText("2 files · 1 ready to import · 1 rejected · 0 already imported")).toBeInTheDocument();
        expect(screen.queryByText(en.workbenchBatch.status.duplicate)).not.toBeInTheDocument();
        await confirm(1);
        await screen.findByText("1 completed · 0 failed · 1 rejected");
        expect(calls.filter(call => !call.url.endsWith("/preview")).map(call => call.name)).toEqual(["good.tgz"]);
    });

    it("keeps only one preview and one import in flight and handles synchronous progress", async () => {
        const heldPreview = deferred();
        const heldImport = deferred();
        onPreview = name => name === "one.tgz" ? heldPreview.promise : ok(preview(name));
        onImport = name => name === "one.tgz" ? heldImport.promise : ok(task());
        await openDialog();
        select("one.tgz", "two.tgz");
        await waitFor(() => expect(calls).toHaveLength(1));
        expect(screen.getByRole("button", { name: "Import valid files (0)" })).toBeDisabled();
        await act(async () => { heldPreview.resolve(ok(preview("one"))); });
        await confirm(2);
        await screen.findByText("50%");
        expect(calls.map(call => call.name)).toEqual(["one.tgz", "two.tgz", "one.tgz"]);
        await act(async () => { heldImport.resolve(ok(task())); });
        await screen.findByText("2 completed · 0 failed · 0 rejected");
    });

    it("aborts stale preview on reselection and ignores its late response", async () => {
        const stale = deferred();
        onPreview = name => name === "stale.tgz" ? stale.promise : ok(preview(name));
        await openDialog();
        select("stale.tgz", "never.tgz");
        await waitFor(() => expect(calls).toHaveLength(1));
        select("current.tgz");
        await screen.findByText("Name current.tgz");
        expect(calls[0].aborted()).toBe(true);
        await act(async () => { stale.resolve(invalid); });
        expect(screen.queryByRole("alert")).not.toBeInTheDocument();
        expect(screen.queryByText(/stale.tgz ·/)).not.toBeInTheDocument();
        expect(calls.map(call => call.name)).toEqual(["stale.tgz", "current.tgz"]);
    });

    it.each(["tenant", "close", "unmount"])("aborts an import on %s and ignores its late result", async mode => {
        const held = deferred();
        onImport = () => held.promise;
        const view = await openDialog();
        select("one.tgz", "two.tgz");
        await confirm(2);
        await waitFor(() => expect(calls).toHaveLength(3));
        if (mode === "tenant") view.rerender(view.view(8));
        else if (mode === "close") fireEvent.click(screen.getByRole("button", { name: en.cancel }));
        else view.unmount();
        expect(calls[2].aborted()).toBe(true);
        await act(async () => { held.resolve(ok(task())); });
        expect(view.onImported).not.toHaveBeenCalled();
        expect(calls.filter(call => !call.url.endsWith("/preview"))).toHaveLength(1);
        if (mode === "close") expect(view.onClose).toHaveBeenCalledOnce();
        if (mode === "tenant") expect(calls.slice(3).every(call => call.tenant === "8")).toBe(true);
    });

    it("imports all 50 files at the inclusive batch-count limit", async () => {
        await openDialog();
        select(...Array.from({ length: 50 }, (_, index) => index + ".tgz"));
        await confirm(50);
        await screen.findByText("50 completed · 0 failed · 0 rejected");
        expect(calls.filter(call => call.url.endsWith("/preview"))).toHaveLength(50);
        expect(calls.filter(call => !call.url.endsWith("/preview"))).toHaveLength(50);
    });

    it("blocks selections exceeding 50 files before requests", async () => {
        await openDialog();
        const files = Array.from({ length: 51 }, (_, index) => new File(["archive"], index + ".tgz"));
        fireEvent.change(screen.getByLabelText(en.workbenchImport), { target: { files } });
        expect(await screen.findByRole("alert")).toHaveTextContent(en.workbenchBatch.countLimit);
        expect(calls).toHaveLength(0);
        expect(screen.getByRole("button", { name: "Import valid files (0)" })).toBeDisabled();
    });

    it("accepts 100 MiB files and batches above the former 64 MiB limit", async () => {
        await openDialog();
        const files = ["boundary.tgz", "another.tgz"].map(name => {
            const file = new File(["archive"], name);
            Object.defineProperty(file, "size", { value: 100 * 1024 * 1024 });
            return file;
        });
        fireEvent.change(screen.getByLabelText(en.workbenchImport), { target: { files } });
        await confirm(2);
        await screen.findByText("2 completed · 0 failed · 0 rejected");
        expect(calls.map(call => call.name)).toEqual(["boundary.tgz", "another.tgz", "boundary.tgz", "another.tgz"]);
        expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("shows an overwrite notice only when preview marks same-version replacement", async () => {
        await openDialog();
        onPreview = name => ok(preview(name, { current_version: "2.0.0", overwrite: true }));
        select("replacement.tgz");
        expect(await screen.findByText(en.overwriteVersion)).toBeInTheDocument();
        expect(screen.getByRole("button", { name: en.workbenchImport })).toBeEnabled();
        expect(screen.queryByText(en.workbenchDuplicate)).not.toBeInTheDocument();
        onPreview = name => ok(preview(name, { current_version: "2.0.0" }));
        select("ordinary.tgz");
        await screen.findByText(en.workbenchReady);
        expect(screen.queryByText(en.overwriteVersion)).not.toBeInTheDocument();
    });

    it("disables confirmation when every preview is rejected", async () => {
        await openDialog();
        onPreview = () => invalid;
        select("one.tgz", "two.tgz");
        await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(2));
        expect(screen.getByRole("button", { name: "Import valid files (0)" })).toBeDisabled();
        expect(calls).toHaveLength(2);
        expect(calls.every(call => call.url.endsWith("/preview"))).toBe(true);
    });

    it("imports allowed upgrades with the same identity in selection order", async () => {
        const { onImported } = await openDialog();
        onPreview = name => ok(preview(name, { workbench_key: "org/shared", incoming_version: name === "first.tgz" ? "2.0.0" : "3.0.0" }));
        select("first.tgz", "second.tgz");
        await confirm(2);
        await waitFor(() => expect(onImported).toHaveBeenCalledOnce());
        expect(calls.filter(call => !call.url.endsWith("/preview")).map(call => call.name)).toEqual(["first.tgz", "second.tgz"]);
        expect(screen.getByText("2 completed · 0 failed · 0 rejected")).toBeInTheDocument();
    });

    it("refreshes committed results when closing during a later upload", async () => {
        const held = deferred();
        onImport = name => name === "first.tgz" ? ok(task()) : held.promise;
        const { onImported, onClose } = await openDialog();
        select("first.tgz", "second.tgz", "never.tgz");
        await confirm(3);
        await waitFor(() => expect(calls).toHaveLength(5));
        expect(onImported).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole("button", { name: en.cancel }));
        expect(onImported).toHaveBeenCalledOnce();
        expect(onClose).toHaveBeenCalledOnce();
        expect(calls[4].aborted()).toBe(true);
        await act(async () => { held.resolve(ok(task())); });
        expect(calls.filter(call => !call.url.endsWith("/preview")).map(call => call.name)).toEqual(["first.tgz", "second.tgz"]);
        expect(onImported).toHaveBeenCalledOnce();
    });

    it("shows unknown preview rejections without describing them as ready", async () => {
        await openDialog();
        onPreview = name => ok(preview(name, { allowed: false, reason: "New validation restriction" }));
        select("restricted.tgz");
        await screen.findByText("New validation restriction");
        expect(screen.getByText(en.workbenchBatch.status.rejected)).toBeInTheDocument();
        expect(screen.queryByText(en.workbenchReady)).not.toBeInTheDocument();
        expect(screen.getByRole("button", { name: en.workbenchImport })).toBeDisabled();
    });

    it("keeps a validating task pending without a success notification or auto close", async () => {
        const { onClose, onImported } = await openDialog();
        onImport = () => ok(task({ status: "validating" }));
        select("pending.tgz");
        await screen.findByText("Name pending.tgz");
        await waitFor(() => expect(screen.getByRole("button", { name: en.workbenchImport })).toBeEnabled());
        fireEvent.click(screen.getByRole("button", { name: en.workbenchImport }));
        await waitFor(() => expect(onImported).toHaveBeenCalledOnce());
        expect(screen.getByText(en.workbenchBatch.status.validating)).toBeInTheDocument();
        expect(notification.open).not.toHaveBeenCalled();
        expect(onClose).not.toHaveBeenCalled();
    });

    it("prevents same-turn repeated submits from starting a second import", async () => {
        const held = deferred();
        onImport = () => held.promise;
        await openDialog();
        select("single.tgz");
        await screen.findByText("Name single.tgz");
        const button = screen.getByRole("button", { name: en.workbenchImport });
        await waitFor(() => expect(button).toBeEnabled());
        act(() => { fireEvent.click(button); fireEvent.click(button); });
        await waitFor(() => expect(calls).toHaveLength(2));
        await act(async () => { held.resolve(ok(task())); });
        expect(calls.filter(call => !call.url.endsWith("/preview"))).toHaveLength(1);
    });

    it("rejects ZIP and oversize TGZ locally while allowing another valid TGZ", async () => {
        await openDialog();
        const oversized = new File(["archive"], "large.tgz");
        Object.defineProperty(oversized, "size", { value: 100 * 1024 * 1024 + 1 });
        fireEvent.change(screen.getByLabelText(en.workbenchImport), { target: { files: [new File(["zip"], "wrong.zip"), oversized, new File(["archive"], "good.tgz")] } });
        await confirm(1);
        await screen.findByText("1 completed · 0 failed · 2 rejected");
        expect(screen.getAllByRole("alert")[0]).toHaveTextContent(en.workbenchPreview.fileType);
        expect(screen.getAllByRole("alert")[1]).toHaveTextContent(en.workbenchPreview.fileSize);
        expect(calls.map(call => call.name)).toEqual(["good.tgz", "good.tgz"]);
    });
});
