import { act, renderHook, waitFor } from "@testing-library/react";
import {
    FileStatus,
    FileType,
    addFilesApi,
    createFolderApi,
    getSimilarCandidatesApi,
    listKnowledgeFolders,
    retryDuplicateFilesApi,
    uploadFileToServerApi,
} from "~/api/knowledge";
import { usePortalUploadDialog } from "./usePortalUploadDialog";

jest.mock("~/api/knowledge", () => ({
    FileStatus: {
        SUCCESS: "success",
        FAILED: "failed",
        WAITING: "waiting",
    },
    FileType: {
        MD: "md",
        PDF: "pdf",
    },
    addFilesApi: jest.fn(),
    createFolderApi: jest.fn(),
    getSimilarCandidatesApi: jest.fn(),
    linkAsNewVersionApi: jest.fn(),
    listKnowledgeFolders: jest.fn(),
    retryDuplicateFilesApi: jest.fn(),
    uploadFileToServerApi: jest.fn(),
}));

const activeSpace = {
    id: "space-1",
    name: "个人知识库",
};

const makeFile = (overrides: Record<string, any> = {}) => ({
    id: "file-1",
    name: "文档.pdf",
    type: FileType.PDF,
    status: FileStatus.WAITING,
    tags: [],
    path: "文档.pdf",
    parentId: undefined,
    spaceId: "space-1",
    createdAt: "2026-05-31T00:00:00Z",
    updatedAt: "2026-05-31T00:00:00Z",
    ...overrides,
});

function renderUploadDialogHook(overrides: Record<string, any> = {}) {
    const params = {
        activeSpace: activeSpace as any,
        setActiveSpace: jest.fn(),
        uploadTargetSpace: activeSpace as any,
        canUploadInPortal: true,
        currentFolderId: undefined,
        currentFolderNode: null,
        currentPath: [],
        statusFilterNumbers: [],
        reloadFiles: jest.fn().mockResolvedValue(undefined),
        showToast: jest.fn(),
        ...overrides,
    };
    const hook = renderHook(() => usePortalUploadDialog(params));
    return { hook, params };
}

describe("usePortalUploadDialog", () => {
    beforeEach(() => {
        jest.clearAllMocks();
        jest.mocked(uploadFileToServerApi).mockResolvedValue({ file_path: "/tmp/uploaded.pdf" } as any);
        jest.mocked(getSimilarCandidatesApi).mockResolvedValue([] as any);
        jest.mocked(listKnowledgeFolders).mockResolvedValue({ items: [], total: 0 } as any);
        jest.mocked(createFolderApi).mockResolvedValue({ id: 1, name: "研发资料" } as any);
    });

    test("separates duplicate files from review rows when upload contains mixed results", async () => {
        const duplicateFile = makeFile({
            id: "101",
            name: "重复.pdf",
            status: FileStatus.FAILED,
            oldFileLevelPath: "/制度库",
        }) as any;
        duplicateFile._raw = { id: "101", file_name: "重复.pdf" };
        const waitingFile = makeFile({
            id: "102",
            name: "新增.pdf",
            status: FileStatus.WAITING,
        });
        jest.mocked(addFilesApi).mockResolvedValue([duplicateFile, waitingFile] as any);

        const { hook } = renderUploadDialogHook();

        act(() => {
            (hook.result.current as any).handleSelectFileCategory?.("RPT");
            hook.result.current.handleAddUploadFiles([
                new File(["duplicate"], "重复.pdf", { type: "application/pdf" }),
                new File(["new"], "新增.pdf", { type: "application/pdf" }),
            ]);
        });

        await act(async () => {
            await hook.result.current.handleUploadNext();
        });

        await waitFor(() => {
            expect(hook.result.current.duplicateFiles).toEqual([
                {
                    fileId: "101",
                    fileName: "重复.pdf",
                    oldFileLevelPath: "/制度库",
                    rawObj: { id: "101", file_name: "重复.pdf" },
                },
            ]);
        });
        expect(hook.result.current.uploadStep).toBe("review");
        expect(hook.result.current.uploadReviewRows).toHaveLength(1);
        expect(hook.result.current.uploadReviewRows[0].file.id).toBe("102");
        expect(getSimilarCandidatesApi).toHaveBeenCalledWith(102);
        expect(hook.result.current.uploadReviewRows.some((row) => row.file.id === "101")).toBe(false);
    });

    test("registers uploaded files without file category when none is selected", async () => {
        jest.mocked(addFilesApi).mockResolvedValue([makeFile()] as any);
        const { hook } = renderUploadDialogHook();

        act(() => {
            hook.result.current.handleAddUploadFiles([
                new File(["report"], "报告.pdf", { type: "application/pdf" }),
            ]);
        });

        await act(async () => {
            await hook.result.current.handleUploadNext();
        });

        expect(uploadFileToServerApi).toHaveBeenCalledTimes(1);
        expect(addFilesApi).toHaveBeenCalledWith("space-1", {
            file_path: ["/tmp/uploaded.pdf"],
            parent_id: null,
        });
    });

    test("registers uploaded folder files without file category when none is selected", async () => {
        jest.mocked(addFilesApi).mockResolvedValue([makeFile()] as any);
        const { hook } = renderUploadDialogHook();
        const rootFile = new File(["report"], "报告.pdf", { type: "application/pdf" });
        Object.defineProperty(rootFile, "webkitRelativePath", { value: "研发资料/报告.pdf" });

        act(() => {
            hook.result.current.handleAddUploadFolder([rootFile]);
        });

        await act(async () => {
            await hook.result.current.handleUploadNext();
        });

        expect(createFolderApi).toHaveBeenCalledWith("space-1", {
            name: "研发资料",
            parent_id: null,
        });
        expect(uploadFileToServerApi).toHaveBeenCalledWith("space-1", rootFile, "报告.pdf");
        expect(addFilesApi).toHaveBeenCalledWith("space-1", {
            file_path: ["/tmp/uploaded.pdf"],
            parent_id: 1,
        });
    });

    test("passes selected file category when registering uploaded files", async () => {
        jest.mocked(addFilesApi).mockResolvedValue([makeFile()] as any);
        const { hook } = renderUploadDialogHook();

        act(() => {
            (hook.result.current as any).handleSelectFileCategory?.("RPT");
            hook.result.current.handleAddUploadFiles([
                new File(["report"], "报告.pdf", { type: "application/pdf" }),
            ]);
        });

        await act(async () => {
            await hook.result.current.handleUploadNext();
        });

        expect(addFilesApi).toHaveBeenCalledWith("space-1", {
            file_path: ["/tmp/uploaded.pdf"],
            parent_id: null,
            file_category_code: "RPT",
        });
    });

    test("keeps non-duplicate review rows when user skips duplicate files", async () => {
        const duplicateFile = makeFile({
            id: "101",
            name: "重复.pdf",
            status: FileStatus.FAILED,
            oldFileLevelPath: "/制度库",
        }) as any;
        duplicateFile._raw = { id: "101", file_name: "重复.pdf" };
        const waitingFile = makeFile({
            id: "102",
            name: "新增.pdf",
            status: FileStatus.WAITING,
        });
        jest.mocked(addFilesApi).mockResolvedValue([duplicateFile, waitingFile] as any);

        const { hook } = renderUploadDialogHook();

        act(() => {
            (hook.result.current as any).handleSelectFileCategory?.("RPT");
            hook.result.current.handleAddUploadFiles([
                new File(["duplicate"], "重复.pdf", { type: "application/pdf" }),
                new File(["new"], "新增.pdf", { type: "application/pdf" }),
            ]);
        });
        await act(async () => {
            await hook.result.current.handleUploadNext();
        });

        await waitFor(() => {
            expect(hook.result.current.duplicateFiles).toHaveLength(1);
        });
        act(() => {
            hook.result.current.handleDuplicateSkip();
        });

        expect(hook.result.current.duplicateFiles).toEqual([]);
        expect(hook.result.current.uploadStep).toBe("review");
        expect(hook.result.current.uploadReviewRows.map((row) => row.file.id)).toEqual(["102"]);
    });

    test("overwrites duplicate files then refreshes and closes the upload flow", async () => {
        const duplicateFile = makeFile({
            id: "101",
            name: "重复.pdf",
            status: FileStatus.FAILED,
            oldFileLevelPath: "/制度库",
        }) as any;
        duplicateFile._raw = { id: "101", file_name: "重复.pdf" };
        jest.mocked(addFilesApi).mockResolvedValue([duplicateFile] as any);
        jest.mocked(retryDuplicateFilesApi).mockResolvedValue(undefined as any);
        const reloadFiles = jest.fn().mockResolvedValue(undefined);

        const { hook } = renderUploadDialogHook({ reloadFiles });

        act(() => {
            hook.result.current.handleOpenUploadDialog();
            (hook.result.current as any).handleSelectFileCategory?.("RPT");
            hook.result.current.handleAddUploadFiles([
                new File(["duplicate"], "重复.pdf", { type: "application/pdf" }),
            ]);
        });
        await waitFor(() => {
            expect(hook.result.current.uploadDialogOpen).toBe(true);
        });
        await act(async () => {
            await hook.result.current.handleUploadNext();
        });
        await waitFor(() => {
            expect(hook.result.current.duplicateFiles).toHaveLength(1);
        });

        await act(async () => {
            await hook.result.current.handleDuplicateOverwrite();
        });

        expect(retryDuplicateFilesApi).toHaveBeenCalledWith("space-1", [
            { id: "101", file_name: "重复.pdf" },
        ], "RPT");
        expect(reloadFiles).toHaveBeenCalledTimes(1);
        expect(hook.result.current.duplicateFiles).toEqual([]);
        expect(hook.result.current.uploadDialogOpen).toBe(false);
        expect(hook.result.current.uploadReviewRows).toEqual([]);
    });
});
