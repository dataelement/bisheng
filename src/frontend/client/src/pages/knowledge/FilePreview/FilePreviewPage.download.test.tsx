import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import FilePreviewPage from "./FilePreviewPage";
import {
    downloadWatermarkedKnowledgeFileApi,
    getFilePreviewApi,
    getSpaceInfoApi,
} from "~/api/knowledge";

const mockShowToast = jest.fn();

jest.mock("react-router-dom", () => ({
    useParams: () => ({ fileId: "201" }),
    useSearchParams: () => [new URLSearchParams("spaceId=team-1&name=%E5%90%8E%E7%AB%AF%E5%BC%80%E5%8F%91.md")],
}));

jest.mock("~/api/knowledge", () => ({
    downloadWatermarkedKnowledgeFileApi: jest.fn(),
    getFilePreviewApi: jest.fn(),
    getSpaceInfoApi: jest.fn(),
}));

jest.mock("~/api/permission", () => ({
    checkPermission: jest.fn().mockResolvedValue({ allowed: true }),
    canOpenPermissionDialog: jest.fn().mockResolvedValue(false),
}));

jest.mock("~/Providers", () => ({
    useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => key,
}));

jest.mock("~/pages/Subscription/hooks/useResizablePanel", () => ({
    useResizablePanel: () => ({
        leftWidth: 800,
        isResizing: false,
        startResizing: jest.fn(),
    }),
}));

jest.mock("~/components/permission", () => ({
    PermissionDialog: () => null,
}));

jest.mock("~/pages/Subscription/AiChat/AiAssistantPanel", () => ({
    AiAssistantPanel: () => null,
}));

jest.mock("./index", () => ({
    __esModule: true,
    default: ({ onDownloadFile, downloadPending }: {
        onDownloadFile?: () => void;
        downloadPending?: boolean;
    }) => (
        <button
            type="button"
            aria-label="下载"
            aria-busy={downloadPending}
            disabled={downloadPending}
            onClick={onDownloadFile}
        >
            下载
        </button>
    ),
}));

jest.mock("./RichKnowledgePreview", () => ({
    RichKnowledgePreview: () => null,
}));

describe("FilePreviewPage watermarked download", () => {
    beforeEach(() => {
        jest.clearAllMocks();
        Object.defineProperty(window, "matchMedia", {
            configurable: true,
            value: jest.fn().mockReturnValue({
                matches: false,
                addEventListener: jest.fn(),
                removeEventListener: jest.fn(),
            }),
        });
        jest.mocked(getFilePreviewApi).mockResolvedValue({
            preview_url: "https://example.test/preview.pdf",
            original_url: "https://example.test/original.md",
            pdf_preview_url: "https://example.test/preview.pdf",
        } as any);
        jest.mocked(getSpaceInfoApi).mockResolvedValue({ spaceLevel: "team" } as any);
    });

    test("uses the preview entry point, blocks duplicate clicks, and restores after an error", async () => {
        let resolveDownload!: () => void;
        jest.mocked(downloadWatermarkedKnowledgeFileApi).mockImplementationOnce(() => new Promise<void>((resolve) => {
            resolveDownload = resolve;
        }));

        render(<FilePreviewPage />);

        const downloadButton = await screen.findByRole("button", { name: "下载" });
        await waitFor(() => expect(downloadButton).toBeEnabled());
        fireEvent.click(downloadButton);
        fireEvent.click(downloadButton);

        await waitFor(() => {
            expect(downloadWatermarkedKnowledgeFileApi).toHaveBeenCalledTimes(1);
            expect(downloadWatermarkedKnowledgeFileApi).toHaveBeenCalledWith({
                spaceId: "team-1",
                fileId: "201",
                entryPoint: "bisheng_preview",
                fallbackFileName: "后端开发.md",
            });
            expect(downloadButton).toBeDisabled();
            expect(downloadButton).toHaveAttribute("aria-busy", "true");
        });

        await act(async () => resolveDownload());
        await waitFor(() => expect(downloadButton).toBeEnabled());

        jest.mocked(downloadWatermarkedKnowledgeFileApi).mockRejectedValueOnce(new Error("水印服务繁忙"));
        fireEvent.click(downloadButton);

        await waitFor(() => {
            expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({
                message: "水印服务繁忙",
            }));
            expect(downloadButton).toBeEnabled();
        });
    });
});
