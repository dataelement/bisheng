import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { Sheet, SheetContent, SheetTitle } from "~/components/ui/Sheet";
import { KnowledgeFilePreviewOverlay, useKnowledgeFilePreview } from "./KnowledgeFilePreviewOverlay";

let mockChannel: "desktop" | "web";
let mockHasHostChatHeader: boolean;
jest.mock("~/utils/clientEnvironment", () => ({
    getClientEnvironment: () => ({
        channel: mockChannel,
        capabilities: { hasHostChatHeader: mockHasHostChatHeader },
    }),
}));
jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
jest.mock("./FilePreviewPage", () => ({
    KnowledgeFileReader: ({ fileId, spaceId, embedded }: { fileId: string; spaceId: string; embedded: string }) =>
        <output>{[spaceId, fileId, embedded].join(":")}</output>,
}));

function FileList({ aboveDialog = false }: { aboveDialog?: boolean }) {
    const { filePreview, openFilePreview, closeFilePreview } = useKnowledgeFilePreview("6");
    return (
        <section aria-label="Knowledge list">
            <input aria-label="Filter" defaultValue="" />
            <button onClick={() => openFilePreview("4", "My report.TXT", aboveDialog)}>Open document</button>
            {filePreview && <KnowledgeFilePreviewOverlay preview={filePreview} onClose={closeFilePreview} />}
        </section>
    );
}

describe("open a knowledge file within the embedded client", () => {
    beforeEach(() => {
        mockChannel = "desktop";
        mockHasHostChatHeader = false;
        __APP_ENV__.BASE_URL = "/workspace";
        jest.spyOn(window, "open").mockImplementation(() => null);
    });

    it.each([
        ["desktop", false, "desktop"],
        ["web", true, "mobile-app"],
    ] as const)("keeps the %s (host header=%s) source list and reader in one document", async (channel, hostHeader, reader) => {
        mockChannel = channel;
        mockHasHostChatHeader = hostHeader;
        render(<FileList />);
        const input = screen.getByRole("textbox", { name: "Filter" });
        fireEvent.change(input, { target: { value: "report" } });
        const open = screen.getByRole("button", { name: "Open document" });
        open.focus();
        fireEvent.click(open);

        const dialog = await screen.findByRole("dialog", { name: /My report.TXT/ });
        expect(dialog.parentElement?.closest("section")).toContainElement(open);
        expect(await within(dialog).findByText(`6:4:${reader}`)).toBeVisible();
        expect(window.open).not.toHaveBeenCalled();

        const back = within(dialog).getByRole("button", { name: "com_ui_go_back" });
        if (reader === "desktop") {
            expect(back).not.toHaveTextContent("com_ui_go_back");
        } else {
            expect(back).toHaveTextContent("com_ui_go_back");
        }
        fireEvent.click(back);
        expect(screen.queryByRole("dialog", { name: /My report.TXT/ })).not.toBeInTheDocument();
        expect(screen.getByRole("textbox", { name: "Filter" })).toBe(input);
        expect(input).toHaveValue("report");
        await waitFor(() => expect(open).toHaveFocus());
    });

    it.each([false, true])("closes only the file on Escape with an outer sheet (body portal=%s)", async (aboveDialog) => {
        function SourceSheet() {
            const [open, setOpen] = useState(true);
            return (
                <Sheet open={open} onOpenChange={setOpen}>
                    <SheetContent aria-describedby={undefined}>
                        <SheetTitle>Source sheet</SheetTitle>
                        <FileList aboveDialog={aboveDialog} />
                    </SheetContent>
                </Sheet>
            );
        }
        render(<SourceSheet />);
        const open = await screen.findByRole("button", { name: "Open document" });
        open.focus();
        fireEvent.click(open);
        const reader = await screen.findByRole("dialog", { name: /My report.TXT/ });
        fireEvent.keyDown(reader, { key: "Escape" });
        expect(screen.queryByRole("dialog", { name: /My report.TXT/ })).not.toBeInTheDocument();
        expect(screen.getByRole("dialog", { name: "Source sheet" })).toBeVisible();
        await waitFor(() => expect(open).toHaveFocus());
    });

    it("preserves the standalone URL and new-tab target for an ordinary browser", () => {
        mockChannel = "web";
        render(<FileList />);
        fireEvent.click(screen.getByRole("button", { name: "Open document" }));
        expect(window.open).toHaveBeenCalledWith(
            "/workspace/knowledge/file/4?name=My%20report.TXT&type=txt&spaceId=6", "_blank",
        );
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
});
