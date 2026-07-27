import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { FileShareDialog } from "./FileShareDialog";

const mockGetTargets = jest.fn();
const mockListEntries = jest.fn();
const mockSubmit = jest.fn();
const mockRevoke = jest.fn();
const mockShowToast = jest.fn();

jest.mock("~/api/approval", () => ({
    getShougangFileShareTargetSpacesApi: (...args: any[]) => mockGetTargets(...args),
    listShougangFileShareEntriesApi: (...args: any[]) => mockListEntries(...args),
    submitShougangFileShareApprovalApi: (...args: any[]) => mockSubmit(...args),
    revokeShougangFileShareApi: (...args: any[]) => mockRevoke(...args),
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

const activeSpace = {
    id: "10",
    name: "设备部知识库",
    spaceLevel: "department",
} as any;
const managerFile = {
    id: "100",
    name: "检修制度.pdf",
    entryType: "manager",
} as any;

describe("FileShareDialog", () => {
    beforeEach(() => {
        jest.clearAllMocks();
        mockGetTargets.mockResolvedValue({
            data: [{ id: 20, name: "生产部知识库" }],
            total: 1,
        });
        mockListEntries.mockResolvedValue({ data: [], total: 0 });
        mockSubmit.mockResolvedValue({ decision: "pending" });
        mockRevoke.mockResolvedValue({});
    });

    test("提交同级部门分享原因和水印下载策略", async () => {
        const onOpenChange = jest.fn();
        render(
            <FileShareDialog
                open
                activeSpace={activeSpace}
                file={managerFile}
                onOpenChange={onOpenChange}
            />,
        );

        await screen.findByRole("option", { name: "生产部知识库" });
        fireEvent.change(screen.getByPlaceholderText("请输入分享原因"), {
            target: { value: "  联合检修使用  " },
        });
        fireEvent.click(
            screen.getByRole("checkbox", {
                name: "允许接收方下载带水印 PDF",
            }),
        );
        fireEvent.click(screen.getByRole("button", { name: "提交审批" }));

        await waitFor(() => {
            expect(mockSubmit).toHaveBeenCalledWith({
                source_space_id: "10",
                source_file_id: "100",
                target_space_id: "20",
                reason: "联合检修使用",
                allow_download: true,
            });
        });
        expect(onOpenChange).toHaveBeenCalledWith(false);
    });

    test("管理入口可以撤回已有分享", async () => {
        mockListEntries.mockResolvedValue({
            data: [
                {
                    entry_id: 301,
                    target_space_id: 20,
                    target_space_name: "生产部知识库",
                    allow_download: false,
                    entry_status: "active",
                },
            ],
            total: 1,
        });

        render(
            <FileShareDialog
                open
                activeSpace={activeSpace}
                file={managerFile}
                onOpenChange={jest.fn()}
            />,
        );

        await screen.findByText("仅查看");
        fireEvent.click(screen.getByRole("button", { name: "撤回" }));

        await waitFor(() => {
            expect(mockRevoke).toHaveBeenCalledWith({
                source_file_id: "100",
                share_entry_id: 301,
            });
        });
        await waitFor(() => {
            expect(screen.queryByText("仅查看")).not.toBeInTheDocument();
        });
    });
});
