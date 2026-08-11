import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import {
    FileType,
    listPendingUploadFileChangesApi,
    type FileChangeDetail,
    type KnowledgeFile,
    type PendingUploadFileChange,
} from "~/api/knowledge";
import type { BatchFileChangeApprovalResult } from "~/api/approval";

import {
    buildFileChangeActionRows,
    getFileChangeLockState,
    mergeFileChangeApprovalEnrichment,
    selectApprovablePendingUploads,
    summarizeBatchApprovalResult,
    useFileChangeApproval,
} from "../hooks/useFileChangeApproval";

jest.mock("~/api/knowledge", () => ({
    ...jest.requireActual("~/api/knowledge"),
    listPendingUploadFileChangesApi: jest.fn(),
}));

const mockedListPending = listPendingUploadFileChangesApi as jest.MockedFunction<
    typeof listPendingUploadFileChangesApi
>;

function file(id: string, name = `${id}.pdf`): KnowledgeFile {
    return {
        id,
        name,
        type: FileType.PDF,
        tags: [],
        path: name,
        spaceId: "101",
        createdAt: "",
        updatedAt: "",
    };
}

const rootApproval = {
    status: "pending" as const,
    action: "rename" as const,
    instanceId: 8,
    requestId: 9,
    canApprove: false,
    inherited: false,
    rootResourceId: 1,
};

describe("F046 file change approval projection", () => {
    beforeEach(() => {
        mockedListPending.mockReset();
    });

    it("batch-merges enrichment and clears fields hidden from an ordinary viewer", () => {
        const initial = [file("1"), file("2")];
        const visible = mergeFileChangeApprovalEnrichment(initial, [
            { ...file("1"), fileChangeApproval: rootApproval },
            file("2"),
        ]);
        expect(visible[0].fileChangeApproval).toEqual(rootApproval);

        const hidden = mergeFileChangeApprovalEnrichment(visible, [file("1")]);
        expect(hidden[0].fileChangeApproval).toBeUndefined();
        expect(hidden[1]).toEqual(visible[1]);
    });

    it("uses the latest canApprove enrichment after owners/managers change", () => {
        const previous = [{ ...file("1"), fileChangeApproval: rootApproval }];
        const refreshed = mergeFileChangeApprovalEnrichment(previous, [{
            ...file("1"),
            fileChangeApproval: { ...rootApproval, canApprove: true },
        }]);
        expect(refreshed[0].fileChangeApproval?.canApprove).toBe(true);
    });

    it("distinguishes root badge from inherited subtree lock", () => {
        expect(getFileChangeLockState({ ...file("1"), fileChangeApproval: rootApproval })).toEqual({
            locked: true,
            showBadge: true,
            requestId: 9,
        });
        expect(getFileChangeLockState({
            ...file("2"),
            fileChangeApproval: { ...rootApproval, inherited: true, rootResourceId: 1 },
        })).toEqual({ locked: true, showBadge: false, requestId: 9 });
        expect(getFileChangeLockState(file("3"))).toEqual({ locked: false, showBadge: false });
    });

    it("selects only pending uploads currently approvable by the dynamic reviewer", () => {
        const uploads: PendingUploadFileChange[] = [
            { requestId: 1, approvalInstanceId: 11, uploadId: "u1", fileName: "a.pdf", fileSize: 1, applicantUserId: 2, status: "pending", canApprove: true },
            { requestId: 2, approvalInstanceId: 12, uploadId: "u2", fileName: "b.pdf", fileSize: 1, applicantUserId: 2, status: "pending", canApprove: false },
            { requestId: 3, approvalInstanceId: 13, uploadId: "u3", fileName: "c.pdf", fileSize: 1, applicantUserId: 2, status: "parsing", canApprove: true },
        ];
        expect(selectApprovablePendingUploads(uploads).map((item) => item.requestId)).toEqual([1]);
    });

    it("keeps cursor pages in one infinite pending-upload list", async () => {
        const first: PendingUploadFileChange = {
            requestId: 1,
            approvalInstanceId: 11,
            uploadId: "u1",
            fileName: "a.pdf",
            fileSize: 1,
            applicantUserId: 2,
            status: "pending",
            canApprove: true,
        };
        const second: PendingUploadFileChange = { ...first, requestId: 2, uploadId: "u2", fileName: "b.pdf" };
        mockedListPending
            .mockResolvedValueOnce({ data: [first], pageSize: 100, hasMore: true, nextCursor: "cursor-1" })
            .mockResolvedValueOnce({ data: [second], pageSize: 100, hasMore: false });
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const wrapper = ({ children }: { children: ReactNode }) => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        );

        const { result } = renderHook(
            () => useFileChangeApproval({ spaceId: "101" }),
            { wrapper },
        );

        await waitFor(() => expect(result.current.pendingItems).toEqual([first]));
        expect(mockedListPending).toHaveBeenNthCalledWith(1, "101", {
            statuses: [],
            cursor: undefined,
            pageSize: 100,
        });
        await act(async () => { await result.current.fetchPendingNextPage(); });
        await waitFor(() => expect(result.current.pendingItems).toEqual([first, second]));
        expect(mockedListPending).toHaveBeenNthCalledWith(2, "101", {
            statuses: [],
            cursor: "cursor-1",
            pageSize: 100,
        });
    });

    it("describes rename, move and delete causes with pending values", () => {
        const base: FileChangeDetail = {
            requestId: 1,
            spaceId: 101,
            action: "rename",
            resourceType: "file",
            resourceId: 3,
            resourceName: "old.pdf",
            applicantUserId: 2,
            status: "pending",
            actionDetail: { oldName: "old.pdf", newName: "new.pdf" },
            canApprove: false,
        };
        expect(buildFileChangeActionRows(base)).toEqual([
            { key: "oldName", value: "old.pdf" },
            { key: "newName", value: "new.pdf" },
        ]);
        expect(buildFileChangeActionRows({
            ...base,
            action: "move",
            actionDetail: { sourcePath: "/A/old.pdf", targetPath: "/B/old.pdf" },
        })).toEqual([
            { key: "sourcePath", value: "/A/old.pdf" },
            { key: "targetPath", value: "/B/old.pdf" },
        ]);
        expect(buildFileChangeActionRows({ ...base, action: "delete", failureReason: "execution failed" })).toEqual([
            { key: "resourceName", value: "old.pdf" },
            { key: "failureReason", value: "execution failed" },
        ]);
    });

    it("summarizes partial batch approval without losing latest status or retryability", () => {
        const result: BatchFileChangeApprovalResult = {
            successCount: 1,
            failureCount: 2,
            items: [
                { changeRequestId: 1, approvalInstanceId: 11, result: "approved", latestStatus: "approved", retryable: false },
                { changeRequestId: 2, approvalInstanceId: 12, result: "invalid", latestStatus: "rejected", retryable: false },
                { changeRequestId: 3, approvalInstanceId: 13, result: "failed", latestStatus: "pending", retryable: true, errorMessage: "temporarily unavailable" },
            ],
        };
        expect(summarizeBatchApprovalResult(result)).toEqual({
            successCount: 1,
            failureCount: 2,
            failures: [
                { requestId: 2, latestStatus: "rejected", retryable: false, message: undefined },
                { requestId: 3, latestStatus: "pending", retryable: true, message: "temporarily unavailable" },
            ],
        });
    });
});
