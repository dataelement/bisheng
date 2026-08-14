import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { ReactNode } from "react";

import {
    getFileChangeDetailApi,
    FileType,
    listPendingUploadFileChangesApi,
    retryFileChangeIngestApi,
    type FileChangeDetail,
    type KnowledgeFile,
    type PendingUploadFileChange,
} from "~/api/knowledge";
import type { BatchFileChangeApprovalResult } from "~/api/approval";
import { FILE_CHANGE_APPROVAL_REFRESH_EVENT } from "~/events/fileChangeApprovalEvents";

import {
    buildFileChangeActionRows,
    getFileChangeLockState,
    mergeFileChangeApprovalEnrichment,
    projectPendingUploadAsKnowledgeFile,
    selectApprovablePendingUploads,
    summarizeBatchApprovalResult,
    useFileChangeApproval,
} from "../hooks/useFileChangeApproval";
import { canCleanup, FileChangeApprovalDetail } from "./FileChangeApprovalDetail";

jest.mock("~/api/knowledge", () => ({
    ...jest.requireActual("~/api/knowledge"),
    getFileChangeDetailApi: jest.fn(),
    listPendingUploadFileChangesApi: jest.fn(),
    retryFileChangeIngestApi: jest.fn(),
}));

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => key,
}));

jest.mock("@bisheng/ui", () => ({
    Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
        <button {...props}>{children}</button>
    ),
}));

jest.mock("~/components/ui/Sheet", () => ({
    Sheet: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    SheetContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    SheetFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    SheetHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    SheetTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
}));

const mockedListPending = listPendingUploadFileChangesApi as jest.MockedFunction<
    typeof listPendingUploadFileChangesApi
>;
const mockedGetDetail = getFileChangeDetailApi as jest.MockedFunction<typeof getFileChangeDetailApi>;
const mockedRetry = retryFileChangeIngestApi as jest.MockedFunction<typeof retryFileChangeIngestApi>;

const BUSINESS_STATES = [
    "queued",
    "applying",
    "applied",
    "failed",
    "compensating",
    "closed",
] as const;

type BusinessState = (typeof BUSINESS_STATES)[number];

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

function businessDetail(
    status: BusinessState,
    overrides: Record<string, unknown> = {},
): FileChangeDetail & { approvalStatus: string } {
    return {
        requestId: 41,
        spaceId: 101,
        action: "upload",
        resourceType: "staged_upload",
        uploadId: "upload-41",
        resourceName: "budget.xlsx",
        fileSize: 123,
        applicantUserId: 2,
        applicantUserName: "applicant",
        approvalInstanceId: 301,
        status,
        approvalStatus: "approved",
        actionDetail: { relativePath: "budget.xlsx" },
        canApprove: false,
        failureReason: status === "failed" ? "storage temporarily unavailable" : undefined,
        ...overrides,
    } as FileChangeDetail & { approvalStatus: string };
}

function pendingBusinessItem(
    status: BusinessState,
    requestId: number,
): PendingUploadFileChange & { approvalStatus: string } {
    return {
        requestId,
        approvalInstanceId: 300 + requestId,
        uploadId: `upload-${requestId}`,
        fileName: `file-${requestId}.pdf`,
        fileSize: 1,
        applicantUserId: 2,
        status,
        approvalStatus: "approved",
        canApprove: false,
    } as PendingUploadFileChange & { approvalStatus: string };
}

function queryWrapper(queryClient: QueryClient) {
    return function Wrapper({ children }: { children: ReactNode }) {
        return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    };
}

describe("F046 file change approval projection", () => {
    beforeEach(() => {
        mockedListPending.mockReset();
        mockedGetDetail.mockReset();
        mockedRetry.mockReset();
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

    it("keeps the public Knowledge API vocabulary separate from approval status", () => {
        const apiSource = readFileSync(resolve(__dirname, "../../../api/knowledge.ts"), "utf8");
        const statusType = apiSource.slice(
            apiSource.indexOf("export type FileChangeApprovalStatus ="),
            apiSource.indexOf("export interface FileMutationItemResult"),
        );

        for (const status of BUSINESS_STATES) {
            expect(statusType).toContain(`"${status}"`);
        }
        for (const legacyExecutionStatus of [
            "executing",
            "executed",
            "execute_failed",
            "parsing",
            "parse_failed",
            "published",
        ]) {
            expect(statusType).not.toContain(`"${legacyExecutionStatus}"`);
        }
        expect(apiSource).toContain("approvalStatus: raw.approval_status");
    });

    it.each(BUSINESS_STATES)(
        "renders Knowledge business state %s independently from approval state",
        (status) => {
            render(
                <FileChangeApprovalDetail
                    open
                    onOpenChange={jest.fn()}
                    detail={businessDetail(status)}
                />,
            );

            expect(screen.getByText("com_knowledge.file_change_business_status")).toBeTruthy();
            expect(screen.getByText(`com_knowledge.file_change_status_${status}`)).toBeTruthy();
            expect(screen.getByText("com_approval_status_label")).toBeTruthy();
            expect(screen.getByText("com_approval_status_approved")).toBeTruthy();
        },
    );

    it("renders queued requests with pending or approved approval status without conflating them", () => {
        const { rerender } = render(
            <FileChangeApprovalDetail
                open
                onOpenChange={jest.fn()}
                detail={businessDetail("queued", { approvalStatus: "pending" })}
            />,
        );
        expect(screen.getByText("com_knowledge.file_change_status_queued")).toBeTruthy();
        expect(screen.getByText("com_approval_status_pending")).toBeTruthy();

        rerender(
            <FileChangeApprovalDetail
                open
                onOpenChange={jest.fn()}
                detail={businessDetail("queued", { approvalStatus: "approved" })}
            />,
        );
        expect(screen.getByText("com_knowledge.file_change_status_queued")).toBeTruthy();
        expect(screen.getByText("com_approval_status_approved")).toBeTruthy();
        expect(screen.queryByText("com_approval_status_pending")).toBeNull();
    });

    it.each(BUSINESS_STATES)("offers original-request retry only for failed, not %s", (status) => {
        const retry = jest.fn();
        render(
            <FileChangeApprovalDetail
                open
                onOpenChange={jest.fn()}
                detail={businessDetail(status)}
                onRetry={retry}
                onCleanup={jest.fn()}
            />,
        );

        const retryButton = screen.queryByText("com_knowledge.retry");
        if (status === "failed") {
            expect(retryButton).not.toBeNull();
            fireEvent.click(retryButton!);
            expect(retry).toHaveBeenCalledWith(41);
        } else {
            expect(retryButton).toBeNull();
        }
        if (status === "closed") {
            expect(screen.queryByText("com_knowledge.file_change_cleanup")).toBeNull();
        }
    });

    it("does not turn approval approved into business applied or business failed into approval exception", () => {
        const { rerender } = render(
            <FileChangeApprovalDetail
                open
                onOpenChange={jest.fn()}
                detail={businessDetail("queued")}
            />,
        );
        expect(screen.getByText("com_knowledge.file_change_status_queued")).toBeTruthy();
        expect(screen.getByText("com_approval_status_approved")).toBeTruthy();
        expect(screen.queryByText("com_knowledge.file_change_status_applied")).toBeNull();

        rerender(
            <FileChangeApprovalDetail
                open
                onOpenChange={jest.fn()}
                detail={businessDetail("failed")}
            />,
        );
        expect(screen.getByText("com_knowledge.file_change_status_failed")).toBeTruthy();
        expect(screen.getByText("com_approval_status_approved")).toBeTruthy();
        expect(screen.queryByText("com_approval_status_exception")).toBeNull();
    });

    it("keeps business states and approval status from list through detail", async () => {
        const items = BUSINESS_STATES.map((status, index) => pendingBusinessItem(status, index + 1));
        mockedListPending.mockResolvedValue({ data: items, pageSize: 100, hasMore: false });
        mockedGetDetail.mockResolvedValue(businessDetail("applying"));
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const { result } = renderHook(
            () => useFileChangeApproval({ spaceId: "101", parentId: "55" }),
            { wrapper: queryWrapper(queryClient) },
        );

        await waitFor(() => expect(result.current.pendingItems).toEqual(items));
        act(() => result.current.openDetail(41));
        await waitFor(() => expect(result.current.detail).toEqual(businessDetail("applying")));
        expect((result.current.detail as FileChangeDetail & { approvalStatus: string }).approvalStatus).toBe("approved");
    });

    it("retries the same Knowledge request through the business API and refreshes list/detail", async () => {
        mockedListPending.mockResolvedValue({
            data: [pendingBusinessItem("failed", 41)],
            pageSize: 100,
            hasMore: false,
        });
        mockedGetDetail.mockResolvedValue(businessDetail("failed"));
        mockedRetry.mockResolvedValue(businessDetail("queued"));
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const { result } = renderHook(
            () => useFileChangeApproval({ spaceId: "101" }),
            { wrapper: queryWrapper(queryClient) },
        );

        act(() => result.current.openDetail(41));
        await waitFor(() => expect(result.current.detail).toEqual(businessDetail("failed")));
        await act(async () => {
            await result.current.retryIngest(41);
        });

        expect(mockedRetry).toHaveBeenCalledWith("101", 41);
        await waitFor(() => expect(mockedListPending.mock.calls.length).toBeGreaterThan(1));
        await waitFor(() => expect(mockedGetDetail.mock.calls.length).toBeGreaterThan(1));
    });

    it("refreshes Knowledge list, open detail and formal files after an F046 decision event", async () => {
        mockedListPending.mockResolvedValue({
            data: [pendingBusinessItem("queued", 41)],
            pageSize: 100,
            hasMore: false,
        });
        mockedGetDetail.mockResolvedValue(businessDetail("queued"));
        const refreshFormalFiles = jest.fn();
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const { result } = renderHook(
            () => useFileChangeApproval({
                spaceId: "101",
                onFormalFilesRefresh: refreshFormalFiles,
            }),
            { wrapper: queryWrapper(queryClient) },
        );
        act(() => result.current.openDetail(41));
        await waitFor(() => expect(result.current.detail).toEqual(businessDetail("queued")));
        mockedListPending.mockClear();
        mockedGetDetail.mockClear();

        act(() => {
            window.dispatchEvent(new CustomEvent(FILE_CHANGE_APPROVAL_REFRESH_EVENT, {
                detail: { spaceId: 101 },
            }));
        });

        await waitFor(() => expect(mockedListPending).toHaveBeenCalled());
        await waitFor(() => expect(mockedGetDetail).toHaveBeenCalledWith("101", 41));
        await waitFor(() => expect(refreshFormalFiles).toHaveBeenCalled());
    });

    it("does not consume Approval projection, outbox, token or exception execution state", () => {
        const sources = [
            resolve(__dirname, "../../../api/knowledge.ts"),
            resolve(__dirname, "../hooks/useFileChangeApproval.ts"),
            resolve(__dirname, "./FileChangeApprovalDetail.tsx"),
        ].map((path) => readFileSync(path, "utf8"));
        const forbidden = [
            "business_status_projection",
            "ApprovalException",
            "retry_execute_failed",
            "execution_token",
            "outbox_status",
            "outbox_id",
        ];

        for (const source of sources) {
            for (const fragment of forbidden) {
                expect(source).not.toContain(fragment);
            }
        }
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
            { requestId: 1, approvalInstanceId: 11, uploadId: "u1", fileName: "a.pdf", fileSize: 1, applicantUserId: 2, status: "queued", approvalStatus: "pending", canApprove: true },
            { requestId: 2, approvalInstanceId: 12, uploadId: "u2", fileName: "b.pdf", fileSize: 1, applicantUserId: 2, status: "queued", approvalStatus: "pending", canApprove: false },
            { requestId: 3, approvalInstanceId: 13, uploadId: "u3", fileName: "c.pdf", fileSize: 1, applicantUserId: 2, status: "applying", approvalStatus: "approved", canApprove: true },
        ];
        expect(selectApprovablePendingUploads(uploads).map((item) => item.requestId)).toEqual([1]);
    });

    it("shows cleanup only when the backend grants it to the uploader", () => {
        const detail = {
            requestId: 1,
            spaceId: 10,
            action: "upload",
            resourceType: "file",
            resourceName: "a.pdf",
            applicantUserId: 2,
            status: "queued",
            approvalStatus: "pending",
            actionDetail: {},
            canApprove: false,
            canCleanup: true,
        } satisfies FileChangeDetail;

        expect(canCleanup(detail)).toBe(true);
        expect(canCleanup({ ...detail, canCleanup: false })).toBe(false);
    });

    it("projects a staged upload into its directory without creating a formal file identity", () => {
        const pending: PendingUploadFileChange = {
            requestId: 41,
            approvalInstanceId: 31,
            uploadId: "upload-41",
            fileName: "budget.xlsx",
            fileSize: 123,
            parentId: 55,
            applicantUserId: 2,
            status: "queued",
            approvalStatus: "pending",
            canApprove: true,
            createTime: "2026-08-12T09:00:00",
        };

        expect(projectPendingUploadAsKnowledgeFile(pending, "101")).toMatchObject({
            id: "pending-upload:41",
            name: "budget.xlsx",
            type: FileType.XLSX,
            parentId: "55",
            spaceId: "101",
            pendingUploadApproval: pending,
        });
    });

    it("keeps cursor pages in one infinite pending-upload list", async () => {
        const first: PendingUploadFileChange = {
            requestId: 1,
            approvalInstanceId: 11,
            uploadId: "u1",
            fileName: "a.pdf",
            fileSize: 1,
            applicantUserId: 2,
            status: "queued",
            approvalStatus: "pending",
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
            () => useFileChangeApproval({ spaceId: "101", parentId: "55" }),
            { wrapper },
        );

        await waitFor(() => expect(result.current.pendingItems).toEqual([first]));
        expect(mockedListPending).toHaveBeenNthCalledWith(1, "101", {
            parentId: "55",
            cursor: undefined,
            pageSize: 100,
        });
        await act(async () => { await result.current.fetchPendingNextPage(); });
        await waitFor(() => expect(result.current.pendingItems).toEqual([first, second]));
        expect(mockedListPending).toHaveBeenNthCalledWith(2, "101", {
            parentId: "55",
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
            status: "queued",
            approvalStatus: "pending",
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
