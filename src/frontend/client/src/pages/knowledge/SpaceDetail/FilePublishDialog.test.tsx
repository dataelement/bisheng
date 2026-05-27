import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { FilePublishDialog } from "./FilePublishDialog";

const mockGetTargetSpaces = jest.fn();
const mockGetSimilarCandidates = jest.fn();
const mockSearchDocuments = jest.fn();
const mockSubmitApproval = jest.fn();
const mockShowToast = jest.fn();

jest.mock("~/api/approval", () => ({
    getShougangFilePublishTargetSpacesApi: (...args: any[]) => mockGetTargetSpaces(...args),
    getShougangFilePublishSimilarCandidatesApi: (...args: any[]) => mockGetSimilarCandidates(...args),
    searchShougangFilePublishDocumentsApi: (...args: any[]) => mockSearchDocuments(...args),
    submitShougangFilePublishApprovalApi: (...args: any[]) => mockSubmitApproval(...args),
}));

jest.mock("~/Providers", () => ({
    useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock("~/components/ui", () => ({
    Button: ({ children, ...props }: any) => <button {...props}>{children}</button>,
    Dialog: ({ open, children }: any) => open ? <div>{children}</div> : null,
    DialogContent: ({ children }: any) => <div>{children}</div>,
    DialogFooter: ({ children }: any) => <div>{children}</div>,
    DialogHeader: ({ children }: any) => <div>{children}</div>,
    DialogTitle: ({ children }: any) => <h2>{children}</h2>,
}));

function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((res, rej) => {
        resolve = res;
        reject = rej;
    });
    return { promise, resolve, reject };
}

const activeSpace = { id: 10, name: "团队空间" } as any;
const file = { id: 100, name: "制度.pdf" } as any;

describe("FilePublishDialog", () => {
    beforeEach(() => {
        jest.clearAllMocks();
        mockGetTargetSpaces.mockResolvedValue({
            data: [
                { id: 20, name: "公共空间" },
                { id: 21, name: "部门空间" },
            ],
        });
        mockSearchDocuments.mockResolvedValue({ data: [] });
        mockSubmitApproval.mockResolvedValue({});
    });

    test("推荐文件返回前展示加载态", async () => {
        const similar = deferred<{ data: any[] }>();
        mockGetSimilarCandidates.mockReturnValue(similar.promise);

        render(
            <FilePublishDialog
                open
                activeSpace={activeSpace}
                file={file}
                onOpenChange={jest.fn()}
                versionManagementEnabled
            />,
        );

        await waitFor(() => expect(mockGetSimilarCandidates).toHaveBeenCalledWith(100, "20"));

        expect(screen.getByRole("option", { name: "推荐加载中..." })).toBeInTheDocument();

        similar.resolve({ data: [] });
        await waitFor(() => {
            expect(screen.queryByRole("option", { name: "推荐加载中..." })).not.toBeInTheDocument();
        });
    });

    test("切换目标空间时立即清空旧推荐和已选版本", async () => {
        const secondSimilar = deferred<{ data: any[] }>();
        mockGetSimilarCandidates
            .mockResolvedValueOnce({
                data: [{ target_document_id: 301, title: "旧空间文件" }],
            })
            .mockReturnValueOnce(secondSimilar.promise);

        render(
            <FilePublishDialog
                open
                activeSpace={activeSpace}
                file={file}
                onOpenChange={jest.fn()}
                versionManagementEnabled
            />,
        );

        await screen.findByRole("option", { name: "推荐：旧空间文件" });
        fireEvent.change(screen.getByLabelText("发布目标知识库"), { target: { value: "21" } });

        expect(screen.queryByRole("option", { name: "推荐：旧空间文件" })).not.toBeInTheDocument();
        expect((screen.getByLabelText("版本管理") as HTMLSelectElement).value).toBe("");

        secondSimilar.resolve({ data: [] });
        await waitFor(() => {
            expect(screen.queryByRole("option", { name: "推荐加载中..." })).not.toBeInTheDocument();
        });
    });

    test("版本管理关闭时禁用版本关联选择", async () => {
        mockGetSimilarCandidates.mockResolvedValue({ data: [{ target_document_id: 301, title: "推荐文件" }] });

        render(
            <FilePublishDialog
                open
                activeSpace={activeSpace}
                file={file}
                onOpenChange={jest.fn()}
                versionManagementEnabled={false}
            />,
        );

        await screen.findByRole("option", { name: "不关联新版本" });

        expect(screen.getByLabelText("版本管理")).toBeDisabled();
        expect(screen.queryByRole("option", { name: "推荐：推荐文件" })).not.toBeInTheDocument();
    });

    test("搜索时展示加载态并在结果弹窗选择 target_file_id", async () => {
        mockGetSimilarCandidates.mockResolvedValue({ data: [] });
        const search = deferred<{ data: any[] }>();
        mockSearchDocuments.mockReturnValue(search.promise);

        render(
            <FilePublishDialog
                open
                activeSpace={activeSpace}
                file={file}
                onOpenChange={jest.fn()}
                versionManagementEnabled
            />,
        );

        await waitFor(() => expect(mockGetSimilarCandidates).toHaveBeenCalledWith(100, "20"));
        fireEvent.change(screen.getByPlaceholderText("搜索目标空间文档..."), { target: { value: "桃" } });
        fireEvent.click(screen.getByRole("button", { name: "搜索" }));

        expect(screen.getByRole("button", { name: "搜索中..." })).toBeDisabled();

        search.resolve({
            data: [{ target_file_id: 300, title: "桃新品种经济效益分析.pdf", doc_code: "SGGF-STD-PP-20260500000004" }],
        });

        await screen.findByRole("heading", { name: "选择版本管理目标" });
        const result = await screen.findByRole("button", { name: /搜索 桃新品种经济效益分析\.pdf/ });
        expect(screen.getByText("SGGF-STD-PP-20260500000004")).toBeInTheDocument();
        fireEvent.click(result);
        await waitFor(() => {
            expect(screen.queryByRole("heading", { name: "选择版本管理目标" })).not.toBeInTheDocument();
        });
        expect(screen.getByText("已选择：桃新品种经济效益分析.pdf")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "提交申请" }));

        await waitFor(() => {
            expect(mockSubmitApproval).toHaveBeenCalledWith({
                source_space_id: 10,
                source_file_id: 100,
                target_space_id: "20",
                target_document_id: null,
                target_file_id: 300,
                reason: undefined,
            });
        });
    });
});
