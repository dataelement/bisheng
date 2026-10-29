import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { getFilePreviewApi } from "~/api/knowledge";
import type { FilePreviewProps } from "./index";
import FilePreviewPage from "./FilePreviewPage";

jest.mock("~/api/knowledge", () => ({
    getFilePreviewApi: jest.fn(),
    getFileDownloadApi: jest.fn(),
}));
jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
jest.mock("~/pages/Subscription/AiChat/FileAiDock", () => ({ FileAiDock: () => null }));
jest.mock("./RichKnowledgePreview", () => ({ RichKnowledgePreview: () => null }));
jest.mock("./index", () => {
    const { TextViewer } = jest.requireActual("./viewers/TextViewer");
    return {
        __esModule: true,
        default: ({ fileUrl, fileType }: FilePreviewProps) => (
            <section data-testid="preview" data-type={fileType}>
                <TextViewer fileUrl={fileUrl} zoomLevel={100} />
            </section>
        ),
    };
});

const objectPath = "/bisheng/original/6.txt";
const signature = "?X-Amz-Credential=test%2Fdate%2Fs3&X-Amz-Signature=abc%2B123";
// eslint-disable-next-line no-restricted-syntax -- Multilingual file-content fixture, rendered verbatim rather than localized UI copy.
const body = "TXT preview acceptance\n中文正文与第二行\n<html>literal markup in a text file</html>";
const appHtml = '<!doctype html><html><body><div id="root"></div></body></html>';
const originalFetch = global.fetch;
const fetchMock = jest.fn();

describe("TXT preview content loaded from a search-result route", () => {
    beforeEach(() => {
        __APP_ENV__.BASE_URL = "/workspace";
        window.matchMedia = jest.fn().mockReturnValue({
            matches: false, addEventListener: jest.fn(), removeEventListener: jest.fn(),
        });
        // Model the deployed proxy: the bucket serves the file, the SPA fallback
        // serves index.html with HTTP 200 for the legacy application-prefixed URL.
        fetchMock.mockImplementation(async (url: string) => ({
            ok: true,
            status: 200,
            text: async () => url === objectPath + signature ? body : appHtml,
        }));
        global.fetch = fetchMock;
    });

    afterEach(() => {
        global.fetch = originalFetch;
    });

    it.each([
        [objectPath, ""],
        [`/workspace${objectPath}`, ""],
        [`/workspace/workspace${objectPath}`, ""],
        [`http://storage.internal:9000${objectPath}`, ""],
        ["/bisheng/original/source.txt", objectPath],
    ])("renders the TXT body for original=%s and preview=%s", async (original, preview) => {
        jest.mocked(getFilePreviewApi).mockResolvedValue({
            original_url: original + signature,
            preview_url: preview ? preview + signature : "",
            file_source: "space_upload",
            source_url: "", final_url: "", web_title: "", media_kind: "", html_preview_url: "",
        });
        const { container } = render(
            <MemoryRouter initialEntries={["/knowledge/file/6?spaceId=11&name=acceptance.txt&type=txt"]}>
                <Routes><Route path="/knowledge/file/:fileId" element={<FilePreviewPage />} /></Routes>
            </MemoryRouter>,
        );

        await screen.findByText(/TXT preview acceptance/);
        expect(screen.getByTestId("preview")).toHaveAttribute("data-type", "txt");
        expect(container.querySelector("pre")?.textContent).toBe(body);
        expect(fetchMock).toHaveBeenCalledWith(objectPath + signature);
        expect(getFilePreviewApi).toHaveBeenCalledWith("11", "6");
    });
});
