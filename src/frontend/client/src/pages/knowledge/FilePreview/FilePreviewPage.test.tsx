import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { getFileDownloadApi, getFilePreviewApi } from "~/api/knowledge";
import { getMyResourcePermissions } from "~/api/permission";
import { triggerUrlDownload } from "../knowledgeUtils";
import type { FilePreviewProps } from "./index";
import FilePreviewPage from "./FilePreviewPage";

jest.mock("~/api/permission", () => ({ getMyResourcePermissions: jest.fn() }));
jest.mock("~/api/knowledge", () => ({
    getFilePreviewApi: jest.fn(),
    getFileDownloadApi: jest.fn(),
}));
jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key, useAuthContext: () => ({ user: { id: '7', role: 'member', tenant_id: 60 } }) }));
let mockHostBack = false;
jest.mock("~/hooks/useClientEnvironment", () => ({
    useClientEnvironment: () => ({ capabilities: { hasHostBackButton: mockHostBack } }),
}));
jest.mock("~/pages/Subscription/AiChat/FileAiDock", () => ({ FileAiDock: () => null }));
jest.mock("./RichKnowledgePreview", () => ({ RichKnowledgePreview: () => null }));
jest.mock("./index", () => ({
    __esModule: true,
    default: ({ fileUrl, fileType, onDownloadFile, conversionFailed, allowDownload }: FilePreviewProps) => (
        <div>
            <output data-testid="viewer" data-type={fileType} data-conversion-failed={conversionFailed}>{fileUrl}</output>
            {allowDownload && <button onClick={onDownloadFile}>Download</button>}
        </div>
    ),
}));

const previewApi = jest.mocked(getFilePreviewApi);
const downloadApi = jest.mocked(getFileDownloadApi);
const metadata = { file_source: "space_upload", source_url: "", final_url: "", web_title: "", media_kind: "", html_preview_url: "" };

describe("knowledge preview resource contract", () => {
    beforeEach(() => {
        jest.mocked(getMyResourcePermissions).mockResolvedValue({
            actions: ["download"], sources: [], mode: "INHERIT", roster_complete: true,
        } as never);
        mockHostBack = false;
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

    function showMobileViewport() {
        window.matchMedia = jest.fn().mockReturnValue({
            matches: true, addEventListener: jest.fn(), removeEventListener: jest.fn(),
        });
    }

    it("returns from the mobile preview when the app owns the back stack", async () => {
        mockHostBack = true;
        showMobileViewport();
        const back = jest.spyOn(window.history, "back").mockImplementation(() => undefined);
        Object.defineProperty(window.history, "length", { configurable: true, value: 2 });
        previewApi.mockResolvedValue({ ...metadata, original_url: "/bisheng/original/file.pdf", preview_url: "" });
        openPreview("file.pdf");
        await screen.findByTestId("viewer");
        fireEvent.click(await screen.findByRole("button", { name: "com_ui_go_back" }));
        expect(back).toHaveBeenCalledTimes(1);
    });

    it("leaves the mobile preview without a back button when the app did not request one", async () => {
        showMobileViewport();
        previewApi.mockResolvedValue({ ...metadata, original_url: "/bisheng/original/file.pdf", preview_url: "" });
        openPreview("file.pdf");
        await screen.findByTestId("viewer");
        expect(screen.queryByRole("button", { name: "com_ui_go_back" })).toBeNull();
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
        expect(getMyResourcePermissions).toHaveBeenCalledWith("knowledge_file", "4", expect.objectContaining({ signal: expect.anything() }));
        triggerUrlDownload("/bisheng/original/file.pdf?signature=list", "file.pdf");
        expect(clicks[1]).toBe("/bisheng/original/file.pdf?signature=list");
    });

    it.each([false, true])("hides download for manage-permission-only users (mobile=%s)", async (mobile) => {
        window.matchMedia = jest.fn().mockReturnValue({
            matches: mobile, addEventListener: jest.fn(), removeEventListener: jest.fn(),
        });
        jest.mocked(getMyResourcePermissions).mockResolvedValue({
            actions: ["manage_permission"], sources: [], mode: "CUSTOM", roster_complete: true,
        } as never);
        previewApi.mockResolvedValue({ ...metadata, original_url: "/bisheng/original/file.docx", preview_url: "" });
        openPreview("file.docx");
        await waitFor(() => expect(screen.getByTestId("viewer")).toHaveTextContent("/bisheng/original/file.docx"));
        expect(screen.queryByRole("button", { name: "Download" })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "com_knowledge.download_file" })).not.toBeInTheDocument();
    });

    it('retires a revoked download grant when returning to the preview window', async () => {
        previewApi.mockResolvedValue({ ...metadata, original_url: '/bisheng/original/file.docx', preview_url: '' });
        openPreview('file.docx');
        await screen.findByRole('button', { name: 'Download' });
        let resolve!: (value: Awaited<ReturnType<typeof getMyResourcePermissions>>) => void;
        jest.mocked(getMyResourcePermissions).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
        act(() => window.dispatchEvent(new Event('focus')));
        expect(screen.queryByRole('button', { name: 'Download' })).not.toBeInTheDocument();
        await act(async () => resolve({ actions: ['manage_permission'] } as never));
        expect(screen.queryByRole('button', { name: 'Download' })).not.toBeInTheDocument();
    });

    it('does not start a late signed download after leaving the preview page', async () => {
        previewApi.mockResolvedValue({ ...metadata, original_url: '/bisheng/original/file.docx', preview_url: '' });
        let resolve!: (value: Awaited<ReturnType<typeof getFileDownloadApi>>) => void;
        downloadApi.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
        const click = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
        const view = openPreview('file.docx');
        fireEvent.click(await screen.findByRole('button', { name: 'Download' }));
        view.unmount();
        await act(async () => resolve({ original_url: '/bisheng/original/file.docx', preview_url: '' }));
        expect(click).not.toHaveBeenCalled();
    });

    it('does not replace the current preview with a late response for the previous file', async () => {
        function Navigate() {
            const navigate = useNavigate();
            return <button onClick={() => navigate('/knowledge/file/5?spaceId=6&name=next.docx')}>Next</button>;
        }
        let resolve!: (value: Awaited<ReturnType<typeof getFilePreviewApi>>) => void;
        previewApi.mockImplementationOnce(() => new Promise(done => { resolve = done; }))
            .mockResolvedValueOnce({ ...metadata, original_url: '/bisheng/original/next.docx', preview_url: '' });
        render(<MemoryRouter initialEntries={['/knowledge/file/4?spaceId=6&name=file.docx']}>
            <Navigate /><Routes><Route path='/knowledge/file/:fileId' element={<FilePreviewPage />} /></Routes>
        </MemoryRouter>);
        fireEvent.click(screen.getByRole('button', { name: 'Next' }));
        await waitFor(() => expect(screen.getByTestId('viewer')).toHaveTextContent('/bisheng/original/next.docx'));
        await act(async () => resolve({ ...metadata, original_url: '/bisheng/original/old.docx', preview_url: '' }));
        expect(screen.getByTestId('viewer')).toHaveTextContent('/bisheng/original/next.docx');
    });

    it('does not reuse the last file download grant during navigation or after a late response', async () => {
        function Navigate() {
            const navigate = useNavigate();
            return <button onClick={() => navigate('/knowledge/file/5?spaceId=6&name=next.docx')}>Next</button>;
        }
        previewApi.mockResolvedValue({ ...metadata, original_url: '/bisheng/original/file.docx', preview_url: '' });
        let resolve!: (value: Awaited<ReturnType<typeof getMyResourcePermissions>>) => void;
        jest.mocked(getMyResourcePermissions).mockResolvedValueOnce({ actions: ['download'] } as never)
            .mockImplementationOnce(() => new Promise(done => { resolve = done; }));
        render(<MemoryRouter initialEntries={['/knowledge/file/4?spaceId=6&name=file.docx']}>
            <Navigate /><Routes><Route path='/knowledge/file/:fileId' element={<FilePreviewPage />} /></Routes>
        </MemoryRouter>);
        await screen.findByRole('button', { name: 'Download' });
        fireEvent.click(screen.getByRole('button', { name: 'Next' }));
        await waitFor(() => expect(jest.mocked(getMyResourcePermissions).mock.calls.some(([kind, id]) => kind === 'knowledge_file' && id === '5')).toBe(true));
        expect(screen.queryByRole('button', { name: 'Download' })).not.toBeInTheDocument();
        await act(async () => resolve({ actions: ['manage_permission'] } as never));
        expect(screen.queryByRole('button', { name: 'Download' })).not.toBeInTheDocument();
    });
});
