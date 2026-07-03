import { act, renderHook, waitFor } from "@testing-library/react";
import {
    FileStatus,
    FileType,
    addFilesApi,
    createFolderApi,
    getSimilarCandidatesApi,
    getSpaceTagsApi,
    listKnowledgeFolders,
    recommendUploadFoldersApi,
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
    getSpaceTagsApi: jest.fn(),
    linkAsNewVersionApi: jest.fn(),
    listKnowledgeFolders: jest.fn(),
    recommendUploadFoldersApi: jest.fn(),
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
        jest.mocked(getSpaceTagsApi).mockResolvedValue([] as any);
        jest.mocked(listKnowledgeFolders).mockResolvedValue({ items: [], total: 0 } as any);
        jest.mocked(createFolderApi).mockResolvedValue({ id: 1, name: "研发资料" } as any);
        jest.mocked(recommendUploadFoldersApi).mockResolvedValue({ items: [] } as any);
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
        const reloadFiles = jest.fn().mockResolvedValue(undefined);
        const onUploaded = jest.fn();

        const { hook, params } = renderUploadDialogHook({ reloadFiles, onUploaded });

        act(() => {
            hook.result.current.handleOpenUploadDialog();
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
        expect(hook.result.current.uploadStep).toBe("select");
        expect(hook.result.current.uploadReviewRows).toEqual([]);
        expect(reloadFiles).toHaveBeenCalledTimes(1);
        expect(onUploaded).not.toHaveBeenCalled();
        expect(params.showToast).not.toHaveBeenCalledWith(expect.objectContaining({
            message: "上传成功",
        }));
        expect(getSimilarCandidatesApi).not.toHaveBeenCalled();
    });

    test("uses AI folder recommendation when upload target is unselected", async () => {
        const energyFile = makeFile({ id: "201", name: "能源管理标准.pdf", parentId: "37" });
        const rootFile = makeFile({ id: "202", name: "其他资料.pdf" });
        jest.mocked(uploadFileToServerApi)
            .mockResolvedValueOnce({ file_path: "/tmp/能源管理标准.pdf" } as any)
            .mockResolvedValueOnce({ file_path: "/tmp/其他资料.pdf" } as any);
        jest.mocked(recommendUploadFoldersApi).mockImplementation(async (_spaceId, payload) => ({
            items: payload.files.map((file) => file.file_name.includes("能源")
                ? {
                    clientFileId: file.client_file_id,
                    fileName: file.file_name,
                    recommendedFolderId: "37",
                    recommendedFolderName: "能源管理",
                    recommendedFolderPath: "技术文档/能源管理",
                    reason: "命中能源",
                }
                : {
                    clientFileId: file.client_file_id,
                    fileName: file.file_name,
                    recommendedFolderId: null,
                    recommendedFolderName: "根目录",
                    recommendedFolderPath: "根目录",
                    reason: "无匹配",
                }),
        } as any));
        jest.mocked(addFilesApi)
            .mockResolvedValueOnce([energyFile] as any)
            .mockResolvedValueOnce([rootFile] as any);
        const reloadFiles = jest.fn().mockResolvedValue(undefined);
        const onUploaded = jest.fn();
        const { hook } = renderUploadDialogHook({ reloadFiles, onUploaded });

        act(() => {
            hook.result.current.handleOpenUploadDialog();
            hook.result.current.handleAddUploadFiles([
                new File(["energy"], "能源管理标准.pdf", { type: "application/pdf" }),
                new File(["other"], "其他资料.pdf", { type: "application/pdf" }),
            ]);
        });

        await act(async () => {
            await hook.result.current.handleUploadNext();
        });

        expect(recommendUploadFoldersApi).toHaveBeenCalledWith("space-1", {
            files: [
                { client_file_id: expect.any(String), file_name: "能源管理标准.pdf" },
                { client_file_id: expect.any(String), file_name: "其他资料.pdf" },
            ],
        });
        expect(addFilesApi).toHaveBeenNthCalledWith(1, "space-1", {
            file_path: ["/tmp/能源管理标准.pdf"],
            parent_id: 37,
        });
        expect(addFilesApi).toHaveBeenNthCalledWith(2, "space-1", {
            file_path: ["/tmp/其他资料.pdf"],
            parent_id: null,
        });
        expect(reloadFiles).toHaveBeenCalledTimes(1);
        expect(onUploaded).toHaveBeenCalledTimes(1);
        expect(hook.result.current.uploadDialogOpen).toBe(false);
        expect(hook.result.current.uploadReviewRows).toEqual([]);
    });

    test("registers uploaded files to explicit root without AI recommendation", async () => {
        jest.mocked(addFilesApi).mockResolvedValue([makeFile()] as any);
        const { hook } = renderUploadDialogHook();

        act(() => {
            hook.result.current.handleSelectUploadFolder(null, "根目录");
            hook.result.current.handleAddUploadFiles([
                new File(["report"], "报告.pdf", { type: "application/pdf" }),
            ]);
        });

        await act(async () => {
            await hook.result.current.handleUploadNext();
        });

        expect(uploadFileToServerApi).toHaveBeenCalledTimes(1);
        expect(recommendUploadFoldersApi).not.toHaveBeenCalled();
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

    test("accepts audio and video files in portal upload selections", () => {
        const { hook, params } = renderUploadDialogHook();
        const audioFile = new File(["audio"], "访谈.mp3", { type: "audio/mpeg" });
        const unsupportedFile = new File(["bin"], "安装包.exe", { type: "application/octet-stream" });

        act(() => {
            hook.result.current.handleAddUploadFiles([audioFile, unsupportedFile]);
        });

        expect(hook.result.current.uploadFiles).toHaveLength(1);
        expect(hook.result.current.uploadFiles[0].file.name).toBe("访谈.mp3");
        expect(params.showToast).toHaveBeenCalledWith(expect.objectContaining({
            message: expect.stringContaining("安装包.exe"),
        }));

        const { hook: folderHook } = renderUploadDialogHook();
        const videoFile = new File(["video"], "培训.mp4", { type: "video/mp4" });
        Object.defineProperty(videoFile, "webkitRelativePath", { value: "培训资料/培训.mp4" });

        act(() => {
            folderHook.result.current.handleAddUploadFolder([videoFile]);
        });

        expect(folderHook.result.current.uploadFiles).toHaveLength(1);
        expect(folderHook.result.current.uploadFiles[0].file.name).toBe("培训.mp4");
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

    test("passes selected business domain and tags when registering uploaded files", async () => {
        jest.mocked(addFilesApi).mockResolvedValue([makeFile()] as any);
        const { hook } = renderUploadDialogHook();

        act(() => {
            (hook.result.current as any).handleSelectBusinessDomain?.("PP");
            (hook.result.current as any).handleToggleUploadTag?.("id:1");
            (hook.result.current as any).handleToggleUploadTag?.("name:制度");
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
            business_domain_code: "PP",
            manual_tag_ids: [1],
            manual_tag_names: ["制度"],
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
        expect(hook.result.current.uploadStep).toBe("select");
        expect(hook.result.current.uploadReviewRows).toEqual([]);
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
        ], { file_category_code: "RPT" });
        expect(reloadFiles).toHaveBeenCalledTimes(1);
        expect(hook.result.current.duplicateFiles).toEqual([]);
        expect(hook.result.current.uploadDialogOpen).toBe(false);
        expect(hook.result.current.uploadReviewRows).toEqual([]);
    });

    test("preserves selected upload metadata when overwriting duplicate files", async () => {
        const duplicateFile = makeFile({
            id: "101",
            name: "重复.pdf",
            status: FileStatus.FAILED,
            oldFileLevelPath: "/制度库",
        }) as any;
        duplicateFile._raw = { id: "101", file_name: "重复.pdf" };
        jest.mocked(addFilesApi).mockResolvedValue([duplicateFile] as any);
        jest.mocked(retryDuplicateFilesApi).mockResolvedValue(undefined as any);
        const { hook } = renderUploadDialogHook();

        act(() => {
            (hook.result.current as any).handleSelectBusinessDomain?.("PP");
            (hook.result.current as any).handleToggleUploadTag?.("id:1");
            (hook.result.current as any).handleToggleUploadTag?.("name:制度");
            hook.result.current.handleAddUploadFiles([
                new File(["duplicate"], "重复.pdf", { type: "application/pdf" }),
            ]);
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
        ], {
            business_domain_code: "PP",
            manual_tag_ids: [1],
            manual_tag_names: ["制度"],
        });
    });

    test("loads deduplicated tag options from space tags", async () => {
        jest.mocked(getSpaceTagsApi).mockResolvedValue([
            { id: 1, name: "已有标签", business_type: "tag_library" },
            { id: 2, name: "制度", business_type: "tag_library" },
            { id: 3, name: "技术文档", business_type: "tag_library" },
        ] as any);

        const { hook } = renderUploadDialogHook();

        act(() => {
            hook.result.current.handleOpenUploadDialog();
        });

        await waitFor(() => {
            expect(getSpaceTagsApi).toHaveBeenCalledWith("space-1");
            expect(hook.result.current.uploadTagOptions).toEqual([
                { label: "已有标签", value: "id:1" },
                { label: "制度", value: "id:2" },
                { label: "技术文档", value: "id:3" },
            ]);
        });
    });
});
