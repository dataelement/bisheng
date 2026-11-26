/**
 * A provider (WeKnora) space previews through a controlled content handle that
 * lives under `/api/v1`. Those URLs pass the browser-facing admission layer, and a
 * super admin's session is admitted only when the request names its management
 * tenant — a header the app's HTTP client adds and a viewer's bare `fetch(url)`
 * cannot. The page therefore reads the excerpt through the client and hands the
 * viewer a `blob:` URL. These tests pin that contract.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { getFilePreviewApi } from "~/api/knowledge";
import request from "~/api/request";
import type { FilePreviewProps } from "./index";
import FilePreviewPage from "./FilePreviewPage";

jest.mock("~/api/knowledge", () => ({
    getFilePreviewApi: jest.fn(),
    getFileDownloadApi: jest.fn(),
}));
jest.mock("~/api/request", () => ({ __esModule: true, default: { get: jest.fn() } }));
jest.mock("~/api/permission", () => ({ getMyResourcePermissions: jest.fn().mockResolvedValue({ actions: [] }) }));
jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => key,
    useAuthContext: () => ({ user: { id: "7", role: "super_admin", tenant_id: 60 } }),
}));
jest.mock("~/pages/Subscription/AiChat/FileAiDock", () => ({ FileAiDock: () => null }));
jest.mock("./RichKnowledgePreview", () => ({ RichKnowledgePreview: () => null }));
jest.mock("./index", () => ({
    __esModule: true,
    default: ({ fileUrl, fileType }: FilePreviewProps) => (
        <section data-testid="preview" data-type={fileType} data-url={fileUrl} />
    ),
}));

const handle = "/api/v1/knowledge/space/18/files/57/content/preview?version_id=45&generation=1&epoch=1";
const excerpt = "解析文本节选（非原文件）";
const originalFetch = global.fetch;

describe("provider text excerpt preview", () => {
    beforeEach(() => {
        __APP_ENV__.BASE_URL = "/workspace";
        window.matchMedia = jest.fn().mockReturnValue({
            matches: false, addEventListener: jest.fn(), removeEventListener: jest.fn(),
        });
        (URL as unknown as { createObjectURL: jest.Mock }).createObjectURL = jest.fn(() => "blob:excerpt");
        (URL as unknown as { revokeObjectURL: jest.Mock }).revokeObjectURL = jest.fn();
        jest.mocked(request.get).mockResolvedValue(new Blob([excerpt], { type: "text/plain" }) as never);
    });

    afterEach(() => {
        global.fetch = originalFetch;
        jest.clearAllMocks();
    });

    it("reads the handle through the app client and renders a blob URL", async () => {
        jest.mocked(getFilePreviewApi).mockResolvedValue({
            original_url: "",
            preview_url: handle,
            file_source: "space_upload",
            source_url: "", final_url: "", web_title: "", media_kind: "text_excerpt", html_preview_url: "",
        });
        render(
            <MemoryRouter initialEntries={["/knowledge/file/57?spaceId=18&name=emoji-cookbook.md"]}>
                <Routes><Route path="/knowledge/file/:fileId" element={<FilePreviewPage />} /></Routes>
            </MemoryRouter>,
        );

        await waitFor(() => expect(request.get).toHaveBeenCalledWith(handle, { responseType: "blob" }));
        await waitFor(() => expect(screen.getByTestId("preview")).toHaveAttribute("data-url", "blob:excerpt"));
        expect(screen.getByTestId("preview")).toHaveAttribute("data-type", "txt");
    });

    it("does not fall back to a raw cross-context fetch when the client read fails", async () => {
        jest.mocked(request.get).mockRejectedValue(new Error("400"));
        jest.mocked(getFilePreviewApi).mockResolvedValue({
            original_url: "",
            preview_url: handle,
            file_source: "space_upload",
            source_url: "", final_url: "", web_title: "", media_kind: "text_excerpt", html_preview_url: "",
        });
        global.fetch = jest.fn();

        render(
            <MemoryRouter initialEntries={["/knowledge/file/57?spaceId=18&name=emoji-cookbook.md"]}>
                <Routes><Route path="/knowledge/file/:fileId" element={<FilePreviewPage />} /></Routes>
            </MemoryRouter>,
        );

        await waitFor(() => expect(request.get).toHaveBeenCalled());
        // The handle is never handed to the viewer: that is what produced the 400.
        expect(global.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/content/preview"), expect.anything());
    });

    it("ignores a preview_url that is not this file's handle", async () => {
        jest.mocked(getFilePreviewApi).mockResolvedValue({
            original_url: "",
            preview_url: "/api/v1/knowledge/space/18/files/58/content/preview?version_id=45&generation=1&epoch=1",
            file_source: "space_upload",
            source_url: "", final_url: "", web_title: "", media_kind: "text_excerpt", html_preview_url: "",
        });
        render(
            <MemoryRouter initialEntries={["/knowledge/file/57?spaceId=18&name=emoji-cookbook.md"]}>
                <Routes><Route path="/knowledge/file/:fileId" element={<FilePreviewPage />} /></Routes>
            </MemoryRouter>,
        );

        await waitFor(() => expect(getFilePreviewApi).toHaveBeenCalledWith("18", "57"));
        expect(request.get).not.toHaveBeenCalled();
    });
});
