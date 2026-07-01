import { fireEvent, render, screen } from "@testing-library/react";
import { FileStatus, FileType, SpaceRole, SortDirection, SortType, type KnowledgeFile } from "~/api/knowledge";
import { FileCard } from "./FileCard";
import { FileTable } from "./FileTable";

const mockOnPublishFile = jest.fn();

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => {
        const dict: Record<string, string> = {
            "com_knowledge.download": "下载",
            "com_knowledge.edit_tags": "编辑标签",
            "com_knowledge.rename": "重命名",
            "com_knowledge.retry": "重试",
            "com_knowledge.delete": "删除",
            "com_knowledge.file_name": "文件名",
            "com_knowledge.type": "类型",
            "com_knowledge.file_size": "文件大小",
            "com_knowledge.tag": "标签",
            "com_knowledge.file_encoding": "文件编码",
            "com_knowledge.update_time": "更新时间",
            "com_knowledge.status": "状态",
            "com_knowledge.success": "成功",
            "com_knowledge.parsing_status": "解析中",
            "com_permission.manage_permission": "权限管理",
            "com_knowledge.version.menu_version_management": "版本管理",
            "com_knowledge.version.menu_version_history": "版本历史",
            "com_knowledge.version.pill_similar": "相似",
        };
        return dict[key] || key;
    },
    useScrollRevealRef: () => jest.fn(),
    useMediaQuery: () => false,
}));

jest.mock("~/hooks/queries/endpoints/queries", () => ({
    useGetBsConfig: () => ({ data: { shougang: { enabled: false } } }),
}));

jest.mock("~/Providers", () => ({
    useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock("@/components/ui/Table", () => ({
    TableBody: ({ children }: any) => <tbody>{children}</tbody>,
    TableCell: ({ children, ...props }: any) => <td {...props}>{children}</td>,
    TableHead: ({ children, ...props }: any) => <th {...props}>{children}</th>,
    TableHeader: ({ children }: any) => <thead>{children}</thead>,
    TableRow: ({ children, ...props }: any) => <tr {...props}>{children}</tr>,
}), { virtual: true });

const Dropdown = ({ children }: any) => <>{children}</>;
const DropdownItem = ({ children, onClick, className }: any) => (
    <button type="button" className={className} onClick={onClick}>
        {children}
    </button>
);

jest.mock("~/components", () => ({
    Button: ({ children, ...props }: any) => <button {...props}>{children}</button>,
    Checkbox: ({ checked, onCheckedChange, ...props }: any) => (
        <input
            type="checkbox"
            checked={checked === true}
            onChange={(event) => onCheckedChange?.(event.currentTarget.checked)}
            {...props}
        />
    ),
    DropdownMenu: Dropdown,
    DropdownMenuContent: Dropdown,
    DropdownMenuItem: DropdownItem,
    DropdownMenuSeparator: () => <hr />,
    DropdownMenuTrigger: Dropdown,
}));

jest.mock("~/components/ui/DropdownMenu", () => ({
    DropdownMenu: Dropdown,
    DropdownMenuContent: Dropdown,
    DropdownMenuItem: DropdownItem,
    DropdownMenuTrigger: Dropdown,
}));

jest.mock("~/components/ui/Card", () => ({
    Card: ({ children, ...props }: any) => <div {...props}>{children}</div>,
    CardContent: ({ children, ...props }: any) => <div {...props}>{children}</div>,
}));

jest.mock("~/components/ui/Tooltip2", () => ({
    Tooltip: ({ children }: any) => <>{children}</>,
    TooltipTrigger: ({ children }: any) => <>{children}</>,
    TooltipContent: ({ children }: any) => <div>{children}</div>,
}));

jest.mock("~/components/ui/Badge", () => ({
    Badge: ({ children }: any) => <span>{children}</span>,
}));

jest.mock("./FileIcon", () => ({
    __esModule: true,
    default: () => <span data-testid="file-icon" />,
}));

jest.mock("./TagGroup", () => ({
    __esModule: true,
    default: () => <span data-testid="tag-group" />,
}));

jest.mock("./EditEncodingModal", () => ({
    EditEncodingModal: () => null,
}));

jest.mock("../hooks/useInlineRename", () => ({
    useInlineRename: ({ fileName }: any) => ({
        isRenaming: false,
        renameValue: fileName,
        setRenameValue: jest.fn(),
        inputRef: { current: null },
        handleRenameSubmit: jest.fn(),
        handleKeyDown: jest.fn(),
        startRenaming: jest.fn(),
    }),
}));

const baseFile: KnowledgeFile = {
    id: "101",
    name: "发布测试.pdf",
    type: FileType.PDF,
    status: FileStatus.SUCCESS,
    size: 1024,
    tags: [],
    updatedAt: "2026-05-24T08:00:00Z",
    createdAt: "2026-05-24T08:00:00Z",
    fileEncoding: "",
    spaceId: "space-1",
} as any;

beforeAll(() => {
    class ResizeObserverMock {
        observe() {}
        unobserve() {}
        disconnect() {}
    }
    Object.defineProperty(window, "ResizeObserver", {
        writable: true,
        value: ResizeObserverMock,
    });
});

describe("普通知识空间文件发布入口", () => {
    beforeEach(() => {
        mockOnPublishFile.mockClear();
    });

    test("表格行更多菜单展示发布并触发发布回调", () => {
        render(
            <FileTable
                files={[baseFile]}
                selectedFiles={new Set()}
                handleSelectAll={jest.fn()}
                handleSelectFile={jest.fn()}
                isAdmin={false}
                currentUserRole={SpaceRole.MEMBER}
                onDownload={jest.fn()}
                onEditTags={jest.fn()}
                onRename={jest.fn()}
                onDelete={jest.fn()}
                onRetry={jest.fn()}
                onNavigateFolder={jest.fn()}
                onPreview={jest.fn()}
                onValidateName={() => null}
                sortBy={SortType.UPDATE_TIME}
                sortDirection={SortDirection.DESC}
                onSort={jest.fn()}
                publishEntryIds={new Set([baseFile.id])}
                onPublishFile={mockOnPublishFile}
            />
        );

        fireEvent.mouseEnter(screen.getByText(baseFile.name).closest("tr")!);
        fireEvent.click(screen.getByRole("button", { name: "发布" }));

        expect(mockOnPublishFile).toHaveBeenCalledWith(baseFile);
    });

    test("卡片更多菜单展示发布并触发发布回调", () => {
        render(
            <FileCard
                file={baseFile}
                userRole={SpaceRole.MEMBER}
                isSelected={false}
                onSelect={jest.fn()}
                onDownload={jest.fn()}
                onRename={jest.fn()}
                onDelete={jest.fn()}
                onEditTags={jest.fn()}
                onRetry={jest.fn()}
                onNavigateFolder={jest.fn()}
                onPreview={jest.fn()}
                canPublish
                onPublishFile={mockOnPublishFile}
            />
        );

        fireEvent.click(screen.getByRole("button", { name: "发布" }));

        expect(mockOnPublishFile).toHaveBeenCalledWith(baseFile);
    });

    test("普通成员卡片展示文件解析状态", () => {
        render(
            <FileCard
                file={{ ...baseFile, status: FileStatus.PROCESSING }}
                userRole={SpaceRole.MEMBER}
                isSelected={false}
                onSelect={jest.fn()}
                onDownload={jest.fn()}
                onRename={jest.fn()}
                onDelete={jest.fn()}
                onEditTags={jest.fn()}
                onRetry={jest.fn()}
                onNavigateFolder={jest.fn()}
                onPreview={jest.fn()}
            />
        );

        expect(screen.getByText("解析中")).toBeInTheDocument();
    });

    test("移动端卡片菜单展示发布并触发发布回调", () => {
        render(
            <FileCard
                file={baseFile}
                userRole={SpaceRole.MEMBER}
                isSelected={false}
                onSelect={jest.fn()}
                onDownload={jest.fn()}
                onRename={jest.fn()}
                onDelete={jest.fn()}
                onEditTags={jest.fn()}
                onRetry={jest.fn()}
                onNavigateFolder={jest.fn()}
                onPreview={jest.fn()}
                mobileListMode
                canPublish
                onPublishFile={mockOnPublishFile}
            />
        );

        fireEvent.click(screen.getByRole("button", { name: "发布" }));

        expect(mockOnPublishFile).toHaveBeenCalledWith(baseFile);
    });

    test("不可发布文件不展示发布入口", () => {
        render(
            <FileCard
                file={{ ...baseFile, status: FileStatus.PROCESSING }}
                userRole={SpaceRole.MEMBER}
                isSelected={false}
                onSelect={jest.fn()}
                onDownload={jest.fn()}
                onRename={jest.fn()}
                onDelete={jest.fn()}
                onEditTags={jest.fn()}
                onRetry={jest.fn()}
                onNavigateFolder={jest.fn()}
                onPreview={jest.fn()}
                canPublish={false}
                onPublishFile={mockOnPublishFile}
            />
        );

        expect(screen.queryByRole("button", { name: "发布" })).not.toBeInTheDocument();
    });
});
