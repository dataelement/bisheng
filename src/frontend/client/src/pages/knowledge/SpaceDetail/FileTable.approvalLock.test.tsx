import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FileStatus, FileType, SpaceRole, SortDirection, SortType, type KnowledgeFile } from "~/api/knowledge";
import { FileTable } from "./FileTable";

const mockShowToast = jest.fn();

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => ({
        "com_knowledge.download": "下载",
        "com_knowledge.edit_tags": "编辑标签",
    }[key] || key),
    useScrollRevealRef: () => jest.fn(),
}));
jest.mock("~/hooks/queries/endpoints/queries", () => ({
    useGetBsConfig: () => ({ data: { shougang: { enabled: true } } }),
}));
jest.mock("~/Providers", () => ({
    useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("~/components", () => {
    const PassThrough = ({ children }: any) => <>{children}</>;
    return {
        Checkbox: ({ checked, onCheckedChange, ...props }: any) => (
            <input type="checkbox" checked={checked === true}
                onChange={(event) => onCheckedChange?.(event.currentTarget.checked)} {...props} />
        ),
        DropdownMenu: PassThrough,
        DropdownMenuContent: PassThrough,
        DropdownMenuItem: ({ children, onClick }: any) => <button onClick={onClick}>{children}</button>,
        DropdownMenuSeparator: () => <hr />,
        DropdownMenuTrigger: PassThrough,
    };
});
jest.mock("./FileIcon", () => ({ __esModule: true, default: () => null }));
jest.mock("./EditEncodingModal", () => ({ EditEncodingModal: () => null }));

const file = {
    id: "approval-file", name: "审批测试.txt", type: FileType.TXT,
    status: FileStatus.SUCCESS, size: 1024, tags: [], spaceId: "50",
    updatedAt: "2026-09-07T08:00:00Z", fileEncoding: "",
    hasPendingPublishApproval: true,
} as KnowledgeFile;

function setup(locked = true) {
    const onDownload = jest.fn();
    const onEditTags = jest.fn();
    const view = render(
        <FileTable
            files={[{ ...file, hasPendingPublishApproval: locked }]}
            selectedFiles={new Set()} handleSelectAll={jest.fn()} handleSelectFile={jest.fn()}
            isAdmin currentUserRole={SpaceRole.ADMIN}
            onDownload={onDownload} onEditTags={onEditTags} onRename={jest.fn()}
            onDelete={jest.fn()} onNavigateFolder={jest.fn()} onPreview={jest.fn()}
            sortBy={SortType.UPDATE_TIME} sortDirection={SortDirection.DESC} onSort={jest.fn()}
            downloadEntryIds={new Set([file.id])} enableEncodingClassification
            businessDomainOptions={[{ code: "PM", name: "设备" }]}
        />,
    );
    fireEvent.mouseEnter(screen.getByTestId(`file-tree-row-${file.id}`));
    return { ...view, onDownload, onEditTags };
}

beforeAll(() => {
    window.ResizeObserver = class {
        observe() {}
        unobserve() {}
        disconnect() {}
    };
});

test("审批中操作禁用，悬浮显示局部提示并在移开后消失，下载仍可用", async () => {
    const user = userEvent.setup();
    const { onDownload, onEditTags } = setup();
    const category = screen.getByRole("button", { name: /修改审批测试.txt文件分类/ });
    const domain = screen.getByRole("combobox");
    const tags = screen.getByTitle("编辑标签");
    const more = screen.getByTestId(`file-tree-row-${file.id}`).querySelector("button:has(svg.lucide-ellipsis-vertical)");
    expect(category).toBeDisabled();
    expect(domain).toBeDisabled();
    expect(tags).toBeDisabled();
    expect(more).toBeDisabled();
    for (const control of [category, domain, tags]) {
        // Hover the containing element because disabled controls do not receive pointer events.
        const trigger = control.closest('[data-slot="tooltip-trigger"]') || control.parentElement!;
        await user.hover(trigger);
        expect(mockShowToast).not.toHaveBeenCalled();
        expect(await screen.findByRole("tooltip")).toHaveTextContent("该文件正在审批中，无法操作");
        await user.unhover(trigger);
        await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
    }
    await user.click(category);
    await user.click(tags);
    expect(screen.queryByRole("tree")).not.toBeInTheDocument();
    expect(onEditTags).not.toHaveBeenCalled();
    fireEvent.mouseEnter(screen.getByTestId(`file-tree-row-${file.id}`));
    const download = screen.getByTitle("下载");
    expect(download).toBeEnabled();
    fireEvent.click(download);
    expect(onDownload).toHaveBeenCalledWith(file.id);
    expect(mockShowToast).not.toHaveBeenCalled();
});

test("非审批中文件分类和标签可以操作", async () => {
    const user = userEvent.setup();
    const { onEditTags } = setup(false);
    const category = screen.getByRole("button", { name: /修改审批测试.txt文件分类/ });
    expect(category).toBeEnabled();
    expect(screen.getByRole("combobox")).toBeEnabled();
    await user.click(category);
    expect(screen.getByRole("tree")).toBeInTheDocument();
    await user.click(screen.getByTitle("编辑标签"));
    expect(onEditTags).toHaveBeenCalledWith(file.id);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
});
