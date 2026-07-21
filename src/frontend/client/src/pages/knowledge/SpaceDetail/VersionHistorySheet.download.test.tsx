import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
    deleteFileVersionApi,
    getFileVersionsApi,
    setPrimaryVersionApi,
} from "~/api/knowledge";
import { VersionHistorySheet } from "./VersionHistorySheet";

jest.mock("~/api/knowledge", () => ({
    ...jest.requireActual("~/api/knowledge"),
    getFileVersionsApi: jest.fn(),
    setPrimaryVersionApi: jest.fn(),
    deleteFileVersionApi: jest.fn(),
}));

jest.mock("~/Providers", () => ({
    useToastContext: () => ({ showToast: jest.fn() }),
    useConfirm: () => jest.fn().mockResolvedValue(true),
}));

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => key,
}));

describe("VersionHistorySheet watermarked download", () => {
    beforeEach(() => {
        jest.clearAllMocks();
        jest.mocked(getFileVersionsApi).mockResolvedValue({
            document_id: 10,
            knowledge_id: 20,
            title: "设备检修方案",
            current_primary_version_no: 2,
            versions: [{
                version_id: 11,
                version_no: 1,
                is_primary: false,
                knowledge_file_id: 777,
                original_file_name: "设备检修方案-v1.docx",
                status: 2,
            }],
        });
        jest.mocked(setPrimaryVersionApi).mockResolvedValue(undefined as any);
        jest.mocked(deleteFileVersionApi).mockResolvedValue(undefined as any);
    });

    test("passes the historical knowledge file id and blocks a duplicate click", async () => {
        let resolveDownload!: () => void;
        const onDownload = jest.fn(() => new Promise<void>((resolve) => {
            resolveDownload = resolve;
        }));
        const queryClient = new QueryClient({
            defaultOptions: { queries: { retry: false } },
        });

        render(
            <QueryClientProvider client={queryClient}>
                <VersionHistorySheet
                    open
                    onOpenChange={jest.fn()}
                    fileId={201}
                    canManage={false}
                    onDownload={onDownload}
                />
            </QueryClientProvider>,
        );

        const downloadButton = await screen.findByRole("button", {
            name: "com_knowledge.version.history_action_download",
        });
        fireEvent.click(downloadButton);
        fireEvent.click(downloadButton);

        await waitFor(() => {
            expect(onDownload).toHaveBeenCalledTimes(1);
            expect(onDownload).toHaveBeenCalledWith(777, "设备检修方案-v1.docx");
            expect(downloadButton).toBeDisabled();
        });

        await act(async () => resolveDownload());
        await waitFor(() => expect(downloadButton).toBeEnabled());
    });
});
