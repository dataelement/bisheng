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
    return {
        ...jest.requireActual("~/components/ui/DropdownMenu"),
        Checkbox: ({ checked, onCheckedChange, ...props }: any) => (
            <input type="checkbox" checked={checked === true}
                onChange={(event) => onCheckedChange?.(event.currentTarget.checked)} {...props} />
        ),
    };
});
jest.mock("./FileIcon", () => ({ __esModule: true, default: () => null }));
jest.mock("./EditEncodingModal", () => ({ EditEncodingModal: () => null }));

const file = {
    id: "approval-file", name: "审批测试.txt", type: FileType.TXT,
    status: FileStatus.SUCCESS, size: 1024, tags: [], spaceId: "50",
    updatedAt: "2026-09-07T08:00:00Z", fileEncoding: "",
    hasPendingPublishApproval: true,
    is_multi_version: true,
} as KnowledgeFile;

function setup(locked = true) {
    const onDownload = jest.fn();
    const onEditTags = jest.fn();
    const onAction = jest.fn();
    const allowedIds = new Set([file.id]);
    const view = render(
        <FileTable
            files={[{ ...file, hasPendingPublishApproval: locked }]}
            selectedFiles={new Set()} handleSelectAll={jest.fn()} handleSelectFile={jest.fn()}
            isAdmin currentUserRole={SpaceRole.ADMIN}
            onDownload={onDownload} onEditTags={onEditTags} onRename={onAction}
            onDelete={onAction} onNavigateFolder={jest.fn()} onPreview={jest.fn()}
            onPublishFile={onAction} onShareFile={onAction} onMove={onAction}
            onRetry={onAction} canRetryFile={() => true} onManagePermission={onAction}
            onOpenVersionManagement={onAction} onOpenVersionHistory={onAction} versionManagementEnabled
            publishEntryIds={allowedIds} shareEntryIds={allowedIds} moveEntryIds={allowedIds}
            renameEntryIds={allowedIds} deleteEntryIds={allowedIds} permissionEntryIds={allowedIds}
            sortBy={SortType.UPDATE_TIME} sortDirection={SortDirection.DESC} onSort={jest.fn()}
            downloadEntryIds={new Set([file.id])} enableEncodingClassification
            businessDomainOptions={[{ code: "PM", name: "设备" }]}
        />,
    );
    fireEvent.mouseEnter(screen.getByTestId(`file-tree-row-${file.id}`));
    return { ...view, onDownload, onEditTags, onAction };
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
    expect(more).toBeEnabled();
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

test.each([true, false])("审批锁定=%s：更多按钮可打开菜单，具体操作遵循审批状态", async (locked) => {
    const user = userEvent.setup();
    const { onAction, onEditTags } = setup(locked);
    const more = screen.getByTestId(`file-tree-row-${file.id}`).querySelector("button:has(svg.lucide-ellipsis-vertical)")!;
    expect(more).toBeEnabled();
    await user.click(more);
    await screen.findByRole("menu");
    const items = screen.getAllByRole("menuitem");
    expect(items).toHaveLength(10);
    if (locked) {
        for (const item of items) {
            expect(item).toHaveAttribute("aria-disabled", "true");
            const trigger = item.closest('[data-slot="tooltip-trigger"]')!;
            await user.hover(trigger);
            expect(await screen.findByRole("tooltip")).toHaveTextContent("该文件正在审批中，无法操作");
            fireEvent.click(item);
            fireEvent.keyDown(item, { key: "Enter" });
            await user.hover(screen.getByRole("menu"));
            await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
        }
        expect(onAction).not.toHaveBeenCalled();
        expect(onEditTags).not.toHaveBeenCalled();
        expect(screen.getByRole("menu")).toBeInTheDocument();
        expect(mockShowToast).not.toHaveBeenCalled();
    } else {
        for (const item of items) expect(item).not.toHaveAttribute("aria-disabled", "true");
        await user.click(screen.getByRole("menuitem", { name: "发布" }));
        expect(onAction).toHaveBeenCalledTimes(1);
    }
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
