import { act, renderHook, waitFor } from "@testing-library/react";
import {
    FileStatus,
    FileType,
    addFilesApi,
    uploadFileToServerApi,
} from "~/api/knowledge";
import { useFileUpload } from "./useFileUpload";

jest.mock("~/api/knowledge", () => {
    const actual = jest.requireActual("~/api/knowledge");
    return {
        ...actual,
        addFilesApi: jest.fn(),
        uploadFileToServerApi: jest.fn(),
    };
});

jest.mock("~/Providers", () => ({
    useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => key,
}));

describe("useFileUpload dragged duplicate flow", () => {
    beforeEach(() => {
        jest.clearAllMocks();
    });

    test("exposes a duplicate entry so the confirmation dialog opens", async () => {
        const rawDuplicate = {
            id: 17,
            file_name: "dragged-duplicate.pdf",
            status: 3,
            remark: JSON.stringify({
                new_name: "dragged-duplicate.pdf",
                old_name: "dragged-duplicate.pdf",
            }),
        };
        const duplicateFile = {
            id: "17",
            name: "dragged-duplicate.pdf",
            type: FileType.PDF,
            status: FileStatus.FAILED,
            tags: [],
            path: "dragged-duplicate.pdf",
            spaceId: "space-1",
            createdAt: "",
            updatedAt: "",
            _raw: rawDuplicate,
        };

        jest.mocked(uploadFileToServerApi).mockResolvedValue({
            file_path: "/tmp/dragged-duplicate.pdf",
        } as any);
        jest.mocked(addFilesApi).mockResolvedValue([duplicateFile] as any);

        const hook = renderHook(() => useFileUpload({
            activeSpace: { id: "space-1", name: "Space" } as any,
            currentFolderId: undefined,
            currentPath: [],
            files: [],
            setFiles: jest.fn(),
            setTotal: jest.fn(),
            loadFiles: jest.fn().mockResolvedValue(undefined),
            currentPage: 1,
            markPendingDeletion: jest.fn(),
            clearPendingDeletion: jest.fn(),
        }));

        await act(async () => {
            await hook.result.current.handleUploadFile([
                new File(["duplicate"], "dragged-duplicate.pdf", { type: "application/pdf" }),
            ]);
        });

        await waitFor(() => {
            expect(hook.result.current.duplicateFiles).toEqual([
                {
                    fileId: "17",
                    fileName: "dragged-duplicate.pdf",
                    oldFileLevelPath: "",
                    rawObj: rawDuplicate,
                },
            ]);
        });
    });
});
