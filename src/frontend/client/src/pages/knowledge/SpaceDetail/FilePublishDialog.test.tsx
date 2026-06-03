import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { FilePublishDialog } from "./FilePublishDialog";

const mockGetTargetSpaces = jest.fn();
const mockGetSimilarCandidates = jest.fn();
const mockSearchDocuments = jest.fn();
const mockSubmitApproval = jest.fn();
const mockShowToast = jest.fn();
const mockListKnowledgeFolders = jest.fn();

jest.mock("~/api/approval", () => ({
    getShougangFilePublishTargetSpacesApi: (...args: any[]) => mockGetTargetSpaces(...args),
    getShougangFilePublishSimilarCandidatesApi: (...args: any[]) => mockGetSimilarCandidates(...args),
    searchShougangFilePublishDocumentsApi: (...args: any[]) => mockSearchDocuments(...args),
    submitShougangFilePublishApprovalApi: (...args: any[]) => mockSubmitApproval(...args),
}));

jest.mock("~/Providers", () => ({
    useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock("~/api/knowledge", () => ({
    listKnowledgeFolders: (...args: any[]) => mockListKnowledgeFolders(...args),
}));

jest.mock("~/components/ui", () => ({
    Button: ({ children, ...props }: any) => <button {...props}>{children}</button>,
    Dialog: ({ open, children }: any) => open ? <div>{children}</div> : null,
    DialogContent: ({ children, onPointerDownOutside: _onPointerDownOutside, ...props }: any) => (
        <div {...props}>{children}</div>
    ),
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

const activeSpace = { id: 10, name: "团队空间", spaceLevel: "team" } as any;
const file = { id: 100, name: "制度.pdf" } as any;

describe("FilePublishDialog", () => {
    beforeEach(() => {
        jest.clearAllMocks();
        mockGetTargetSpaces.mockResolvedValue({
            data: [
                { id: 20, name: "公共空间", space_level: "public" },
                { id: 21, name: "部门空间", space_level: "department" },
            ],
        });
        mockListKnowledgeFolders.mockResolvedValue({ items: [], total: 0 });
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

        await waitFor(() => expect(mockGetTargetSpaces).toHaveBeenCalledWith(10));
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
        fireEvent.click(screen.getByRole("button", { name: "选择部门空间根目录" }));

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
                target_folder_id: null,
                target_document_id: null,
                target_file_id: 300,
                reason: undefined,
            });
        });
    });

    test("按类型展示目标空间目录树并提交所选目录", async () => {
        mockGetTargetSpaces.mockResolvedValue({
            data: [
                { id: 20, name: "公共空间", space_level: "public" },
                { id: 30, name: "团队空间", space_level: "team" },
            ],
        });
        mockGetSimilarCandidates.mockResolvedValue({ data: [] });
        mockListKnowledgeFolders.mockResolvedValueOnce({
            items: [{ id: 301, file_name: "制度目录", file_type: 0, file_size: null }],
            total: 1,
        });

        render(
            <FilePublishDialog
                open
                activeSpace={{ id: 10, name: "个人空间", spaceLevel: "personal" } as any}
                file={file}
                onOpenChange={jest.fn()}
                versionManagementEnabled
            />,
        );

        await screen.findByText("公共知识库");
        expect(screen.getByText("团队知识库")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "选择公共空间根目录" })).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: "展开团队空间目录" }));
        await waitFor(() => {
            expect(mockListKnowledgeFolders).toHaveBeenCalledWith({ space_id: 30, parent_id: null });
        });
        fireEvent.click(await screen.findByRole("button", { name: "选择目录制度目录" }));
        fireEvent.click(screen.getByRole("button", { name: "提交申请" }));

        await waitFor(() => {
            expect(mockSubmitApproval).toHaveBeenCalledWith(expect.objectContaining({
                source_space_id: 10,
                source_file_id: 100,
                target_space_id: "30",
                target_folder_id: 301,
            }));
        });
    });

    test("知识空间节点不使用文件夹图标", async () => {
        mockGetTargetSpaces.mockResolvedValue({
            data: [{ id: 20, name: "公共空间", space_level: "public" }],
        });
        mockGetSimilarCandidates.mockResolvedValue({ data: [] });
        mockListKnowledgeFolders.mockResolvedValueOnce({
            items: [{ id: 301, file_name: "制度目录", file_type: 0, file_size: null }],
            total: 1,
        });

        render(
            <FilePublishDialog
                open
                activeSpace={activeSpace}
                file={file}
                onOpenChange={jest.fn()}
                versionManagementEnabled
            />,
        );

        const rootButton = await screen.findByRole("button", { name: "选择公共空间根目录" });
        expect(rootButton.querySelector(".lucide-folder, .lucide-folder-open")).toBeNull();

        fireEvent.click(screen.getByRole("button", { name: "展开公共空间目录" }));
        const folderButton = await screen.findByRole("button", { name: "选择目录制度目录" });
        expect(folderButton.querySelector(".lucide-folder, .lucide-folder-open")).not.toBeNull();
    });

    test("发布弹窗限制在视口内并让内容区滚动", async () => {
        mockGetSimilarCandidates.mockResolvedValue({ data: [] });

        render(
            <FilePublishDialog
                open
                activeSpace={activeSpace}
                file={file}
                onOpenChange={jest.fn()}
                versionManagementEnabled
            />,
        );

        const dialogContent = await screen.findByTestId("file-publish-dialog");
        expect(dialogContent).toHaveClass("!flex", "max-h-[calc(100dvh-48px)]", "overflow-hidden");
        expect(screen.getByTestId("file-publish-dialog-body")).toHaveClass("min-h-0", "overflow-y-auto");
    });

    test("审批配置异常时不关闭弹窗且不提示成功", async () => {
        mockGetSimilarCandidates.mockResolvedValue({ data: [] });
        const onOpenChange = jest.fn();
        mockSubmitApproval.mockResolvedValue({
            decision: "exception",
            exception_type: "route_missing",
            instance_id: 135,
        });

        render(
            <FilePublishDialog
                open
                activeSpace={activeSpace}
                file={file}
                onOpenChange={onOpenChange}
                versionManagementEnabled
            />,
        );

        await waitFor(() => expect(screen.getByRole("button", { name: "提交申请" })).toBeEnabled());
        fireEvent.click(screen.getByRole("button", { name: "提交申请" }));

        await waitFor(() => {
            expect(mockShowToast).toHaveBeenCalledWith({
                message: "审批配置未匹配，请联系管理员处理后重试",
                severity: "error",
            });
        });
        expect(mockShowToast).not.toHaveBeenCalledWith({
            message: "已提交发布申请",
            severity: "success",
        });
        expect(onOpenChange).not.toHaveBeenCalledWith(false);
    });
});
