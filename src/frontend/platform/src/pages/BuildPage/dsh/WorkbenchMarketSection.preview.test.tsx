import React, { type ComponentProps, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import request from "@/controllers/request";
import en from "../../../../public/locales/en-US/dshMarket.json";
import errors from "../../../../../packages/locales/src/api_errors/en.json";
import { WorkbenchMarketSection } from "./WorkbenchMarketSection";
import userEvent from "@testing-library/user-event";

vi.unmock("react-i18next");
vi.mock("@bisheng/ui", () => ({
    buttonVariants: () => "",
    Button: ({ children, disabled, onClick }: ComponentProps<"button">) => <button disabled={disabled} onClick={onClick}>{children}</button>,
    Input: (props: ComponentProps<"input">) => <input {...props} />,
    Pagination: () => null,
    notification: { open: vi.fn() },
}));
vi.mock("@/hooks/usePaginationLocale", () => ({ usePaginationLocale: () => ({}) }));
vi.mock("@/components/bs-ui/dialog", () => ({
    Dialog: ({ open, children }: { open: boolean; children: ReactNode }) => open ? <div>{children}</div> : null,
    DialogContent: ({ children }: { children: ReactNode }) => <div role="dialog">{children}</div>,
    DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
    DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
}));
const originalAdapter = request.defaults.adapter;
let diagnostic: { code: string; rule: string; field: string; message: string };
let previewCalls: number;
beforeEach(() => {
    previewCalls = 0;
    diagnostic = { code: "WORKBENCH_CONFIG_INVALID", rule: "WB09", field: "config.model", message: "Expected an object" };
    request.defaults.adapter = async config => {
        const url = config.url || "";
        if (url.endsWith("/preview")) {
            previewCalls++;
            return { config, status: 200, statusText: "OK", headers: {}, data: { status_code: 26205, status_message: "Validation failed", data: diagnostic } };
        }
        const data = url.endsWith("/context") ? { tenant_id: 7 } : url.endsWith("/imports") ? [] : { data: [], total: 0 };
        return { config, status: 200, statusText: "OK", headers: {}, data: { status_code: 200, data } };
    };
});
afterEach(() => { request.defaults.adapter = originalAdapter; });

async function openSection() {
    const i18n = createInstance();
    await i18n.init({ lng: "en-US", defaultNS: "dshMarket", resources: { "en-US": { dshMarket: en, api_errors: errors } }, interpolation: { escapeValue: false } });
    render(<I18nextProvider i18n={i18n}><WorkbenchMarketSection /></I18nextProvider>);
}

async function openUpload() {
    await openSection();
    const openButton = screen.getByRole("button", { name: en.workbenchImport });
    await waitFor(() => expect(openButton).toBeEnabled());
    fireEvent.click(openButton);
    return screen.getByLabelText(en.workbenchImport);
}

describe("workbench upload preview feedback", () => {
    it("reopens workbench deletion after real Escape without sending DELETE", async () => {
        const requests: string[] = [];
        request.defaults.adapter = async config => {
            requests.push(config.method || "");
            const url = config.url || "";
            const data = url.endsWith("/context") ? { tenant_id: 7 } : url.endsWith("/imports") ? [] : {
                data: [{ id: "workbench", revision: 3, identity_kind: "repository", workbench_key: "org/workbench",
                    legacy_id: null, package_name: "workbench", display_name: "Escape workbench", description: "",
                    current_version: { id: "version", version: "1.0.0" }, verification_level: "static", updated_at: "2026-10-15T00:00:00Z" }], total: 1,
            };
            return { config, status: 200, statusText: "OK", headers: {}, data: { status_code: 200, data } };
        };
        await openSection();
        await screen.findByText("Escape workbench");
        await act(async () => { fireEvent.click(screen.getByRole("button", { name: en.delete })); });
        expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
        await userEvent.setup().keyboard("{Escape}");
        await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
        await act(async () => { fireEvent.click(screen.getByRole("button", { name: en.delete })); });
        expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
        await userEvent.setup().keyboard("{Escape}");
        await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
        expect(requests).not.toContain("delete");
    });
    it.each([
        ["WORKBENCH_ARCHIVE_LIMIT", "WB02", errors.WORKBENCH_ARCHIVE_LIMIT],
        ["WORKBENCH_ARCHIVE_INVALID", "WB01", errors.WORKBENCH_ARCHIVE_INVALID],
        ["WORKBENCH_CONFIG_INVALID", "WB09", errors.WORKBENCH_VALIDATION_FAILED],
    ])("renders %s diagnostics in the alert and blocks import", async (code, rule, heading) => {
        diagnostic = { code, rule, field: "config.model", message: "Precise rejection reason" };
        const input = await openUpload();
        fireEvent.change(input, { target: { files: [new File(["archive"], "workbench.tgz")] } });
        const alert = await screen.findByRole("alert");
        expect(alert).toHaveTextContent(heading);
        expect(alert).toHaveTextContent("Precise rejection reason");
        expect(alert).toHaveTextContent("Field: config.model");
        expect(alert).toHaveTextContent("Rule: " + rule);
        expect(screen.getAllByRole("button", { name: en.workbenchImport })[1]).toBeDisabled();
        expect(screen.queryByText(en.previewing)).not.toBeInTheDocument();
        expect(previewCalls).toBe(1);
    });

    it("clears the previous diagnostic when another file is selected", async () => {
        const input = await openUpload();
        fireEvent.change(input, { target: { files: [new File(["archive"], "workbench.tgz")] } });
        expect(await screen.findByRole("alert")).toHaveTextContent("Expected an object");
        fireEvent.change(input, { target: { files: [new File(["zip"], "workbench.zip")] } });
        await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(en.workbenchPreview.fileType));
        expect(screen.getByRole("alert")).not.toHaveTextContent("Expected an object");
        expect(previewCalls).toBe(1);
    });

    it("rejects oversize local files before requesting a preview", async () => {
        const input = await openUpload();
        const file = new File(["archive"], "workbench.tgz");
        Object.defineProperty(file, "size", { value: 100 * 1024 * 1024 + 1 });
        fireEvent.change(input, { target: { files: [file] } });
        expect(await screen.findByRole("alert")).toHaveTextContent(en.workbenchPreview.fileSize);
        expect(previewCalls).toBe(0);
    });
});
