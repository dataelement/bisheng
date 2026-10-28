import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { getFileDownloadApi, getFilePreviewApi } from "~/api/knowledge";
import { triggerUrlDownload } from "../knowledgeUtils";
import type { FilePreviewProps } from "./index";
import FilePreviewPage from "./FilePreviewPage";

jest.mock("~/api/knowledge", () => ({
    ...jest.requireActual("~/api/knowledge"),
    getFilePreviewApi: jest.fn(),
    getFileDownloadApi: jest.fn(),
}));
jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
jest.mock("~/pages/Subscription/AiChat/FileAiDock", () => ({ FileAiDock: () => null }));
jest.mock("./RichKnowledgePreview", () => ({ RichKnowledgePreview: () => null }));
jest.mock("./index", () => ({
    __esModule: true,
    default: ({ fileUrl, fileType, onDownloadFile, conversionFailed }: FilePreviewProps) => (
        <div>
            <output data-testid="viewer" data-type={fileType} data-conversion-failed={conversionFailed}>{fileUrl}</output>
            <button onClick={onDownloadFile}>Download</button>
        </div>
    ),
}));

const previewApi = jest.mocked(getFilePreviewApi);
const downloadApi = jest.mocked(getFileDownloadApi);
const metadata = { file_source: "space_upload", source_url: "", final_url: "", web_title: "", media_kind: "", html_preview_url: "" };

describe("knowledge preview resource contract", () => {
    beforeEach(() => {
        __APP_ENV__.BASE_URL = "/workspace";
        window.matchMedia = jest.fn().mockReturnValue({
            matches: false, addEventListener: jest.fn(), removeEventListener: jest.fn(),
        });
    });

    function openPreview(name: string) {
        return render(<MemoryRouter initialEntries={[`/knowledge/file/4?spaceId=6&name=${name}`]}>
            <Routes><Route path="/knowledge/file/:fileId" element={<FilePreviewPage />} /></Routes>
        </MemoryRouter>);
    }

    it.each([
        ["file.pdf", "", "pdf", "/bisheng/original/file.pdf"],
        ["file.pptx", "/bisheng/preview/file.pdf", "pdf", "/bisheng/preview/file.pdf"],
        ["file.docx", "", "docx", "/bisheng/original/file.docx"],
        ["file.xlsx", "", "xlsx", "/bisheng/original/file.xlsx"],
        ["file.md", "", "md", "/bisheng/original/file.md"],
        ["file.txt", "", "txt", "/bisheng/original/file.txt"],
    ])("opens %s using its actual object URL", async (name, preview, type, expected) => {
        previewApi.mockResolvedValue({ ...metadata, original_url: `/bisheng/original/${name}`, preview_url: preview });
        openPreview(name);
        await waitFor(() => expect(screen.getByTestId("viewer")).toHaveTextContent(expected));
        expect(screen.getByTestId("viewer")).toHaveAttribute("data-type", type);
        expect(previewApi).toHaveBeenCalledWith("6", "4");
    });

    it("shows conversion failure when PPTX has no derived preview", async () => {
        previewApi.mockResolvedValue({ ...metadata, original_url: "/bisheng/original/file.pptx", preview_url: "" });
        openPreview("file.pptx");
        await waitFor(() => expect(screen.getByTestId("viewer")).toHaveAttribute("data-conversion-failed", "true"));
    });

    it("downloads the original PPTX through the protected download endpoint", async () => {
        previewApi.mockResolvedValue({ ...metadata, original_url: "/bisheng/original/file.pptx", preview_url: "/bisheng/preview/file.pdf" });
        downloadApi.mockResolvedValue({ original_url: "/workspace/bisheng/original/file.pptx?signature=download", preview_url: "" });
        const clicks: string[] = [];
        jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
            clicks.push(this.getAttribute("href") || "");
        });
        openPreview("file.pptx");
        fireEvent.click(await screen.findByRole("button", { name: "Download" }));
        await waitFor(() => expect(clicks).toEqual(["/bisheng/original/file.pptx?signature=download"]));
        expect(downloadApi).toHaveBeenCalledWith("6", "4");
        triggerUrlDownload("/bisheng/original/file.pdf?signature=list", "file.pdf");
        expect(clicks[1]).toBe("/bisheng/original/file.pdf?signature=list");
    });
});
