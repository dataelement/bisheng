import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "fs";
import path from "path";
import PortalKnowledgeWorkbench from "./PortalKnowledgeWorkbench";
import {
    FileStatus,
    FileType,
    SpaceLevel,
    SpaceRole,
    SpaceSortType,
    VisibilityType,
    batchDeleteApi,
    batchDownloadApi,
    batchRetryApi,
    createSpaceApi,
    deleteSpaceApi,
    getCreateSpaceOptionsApi,
    getDepartmentSpacesApi,
    getFileDownloadApi,
    getFilePreviewApi,
    getGroupedSpacesApi,
    getJoinedSpacesApi,
    getMineSpacesApi,
    getSpaceChildrenApi,
    getSpaceInfoApi,
    pinSpaceApi,
    searchSpaceChildrenApi,
    unsubscribeSpaceApi,
} from "~/api/knowledge";

const mockShowToast = jest.fn();
const mockConfirm = jest.fn();
const mockUseKnowledgeSpaceActionPermissions = jest.fn();
const mockCheckPermission = jest.fn();
const mockClipboardWriteText = jest.fn();

jest.mock("~/Providers", () => ({
    useToastContext: () => ({
        showToast: mockShowToast,
    }),
    useConfirm: () => mockConfirm,
}));

jest.mock("~/components/ui", () => ({
    Button: ({ children, ...props }: any) => <button {...props}>{children}</button>,
    Dialog: ({ open, children }: any) => (open ? <div>{children}</div> : null),
    DialogContent: ({ children }: any) => <div>{children}</div>,
    DialogFooter: ({ children }: any) => <div>{children}</div>,
    DialogHeader: ({ children }: any) => <div>{children}</div>,
    DialogTitle: ({ children }: any) => <div>{children}</div>,
}));

jest.mock("~/components/ui/DropdownMenu", () => ({
    DropdownMenu: ({ children }: any) => <div>{children}</div>,
    DropdownMenuTrigger: ({ children }: any) => <div>{children}</div>,
    DropdownMenuContent: ({ children }: any) => <div>{children}</div>,
    DropdownMenuItem: ({ children, onClick }: any) => (
        <button type="button" onClick={onClick}>
            {children}
        </button>
    ),
    DropdownMenuCheckboxItem: ({ children, checked, onCheckedChange, onSelect }: any) => (
        <button
            type="button"
            aria-pressed={Boolean(checked)}
            onClick={(event) => {
                onSelect?.(event);
                onCheckedChange?.(!checked);
            }}
        >
            {children}
        </button>
    ),
}));

jest.mock("../FilePreview", () => ({
    __esModule: true,
    default: () => <div data-testid="file-preview" />,
}));

jest.mock("../SpaceDetail/EditTagsModal", () => ({
    EditTagsModal: ({ isOpen }: any) => (
        isOpen ? <div data-testid="edit-tags-modal">编辑标签弹窗</div> : null
    ),
}));

jest.mock("../SpaceDetail/AiChat/KnowledgeAiPanel", () => ({
    KnowledgeAiPanel: () => <div data-testid="knowledge-ai-panel" />,
}));

jest.mock("../SpaceDetail/KnowledgeSpaceShareDialog", () => ({
    KnowledgeSpaceShareDialog: ({ open, resourceName }: any) => (
        open ? <div data-testid="space-share-dialog">成员管理:{resourceName}</div> : null
    ),
}));

jest.mock("~/components/ui/icon/File", () => ({
    __esModule: true,
    default: ({ type, className }: any) => (
        <span data-testid={`legacy-file-icon-${type}`} className={className} />
    ),
}));

jest.mock("../CreateKnowledgeSpaceDrawer", () => ({
    CreateKnowledgeSpaceDrawer: ({ open, initialSpaceLevel, mode = "create", editingSpace, onConfirm }: any) => {
        if (!open) return null;
        return (
            <div data-testid="create-space-drawer">
                mode:{mode}
                initial:{initialSpaceLevel}
                editing:{editingSpace?.name || ""}
                <button
                    type="button"
                    onClick={() => onConfirm?.({
                        name: "新空间",
                        description: "说明",
                        joinPolicy: "review",
                        publishToSquare: "yes",
                        spaceLevel: initialSpaceLevel,
                        autoTagEnabled: false,
                        autoTagLibraryId: null,
                    })}
                >
                    提交创建
                </button>
            </div>
        );
    },
}));

jest.mock("../hooks/useKnowledgeSpacePermissions", () => ({
    useKnowledgeSpaceActionPermissions: (...args: any[]) => mockUseKnowledgeSpaceActionPermissions(...args),
    hasKnowledgeSpacePermission: (
        permissions: Record<string, string[]>,
        spaceId: string | number,
        permissionId: string,
    ) => permissions[String(spaceId)]?.includes(permissionId) ?? false,
}));

jest.mock("../hooks/useFileManager", () => ({
    useFileManager: () => ({
        files: [],
        setFiles: jest.fn(),
        total: 0,
        setTotal: jest.fn(),
        pageSize: 20,
        currentPage: 1,
        currentFolderId: undefined,
        currentPath: [],
        loading: false,
        loadFiles: jest.fn(),
        handleSearch: jest.fn(),
        handleNavigateFolder: jest.fn(),
        handlePageChange: jest.fn(),
    }),
}));

jest.mock("../hooks/useFileUpload", () => ({
    useFileUpload: () => ({
        creatingFolder: null,
        uploadingFiles: [],
        duplicateFiles: [],
        handleCreateFolder: jest.fn(),
        handleUploadFile: jest.fn(),
        handleCancelCreateFolder: jest.fn(),
        handleRenameFile: jest.fn(),
        handleDuplicateSkip: jest.fn(),
        handleDuplicateOverwrite: jest.fn(),
    }),
}));

jest.mock("~/api/permission", () => ({
    checkPermission: (...args: any[]) => mockCheckPermission(...args),
    canOpenPermissionDialog: jest.fn(),
}));

jest.mock("~/api/knowledge", () => ({
    FileStatus: {
        SUCCESS: "success",
        VIOLATION: "violation",
        UPLOADING: "uploading",
        PROCESSING: "processing",
        WAITING: "waiting",
        REBUILDING: "rebuilding",
        FAILED: "failed",
        TIMEOUT: "timeout",
    },
    FileType: {
        FOLDER: "folder",
        FILE: "file",
        MD: "md",
        PDF: "pdf",
        DOC: "doc",
    },
    SpaceRole: {
        CREATOR: "creator",
        ADMIN: "admin",
        MEMBER: "member",
    },
    SpaceSortType: {
        UPDATE_TIME: "update_time",
    },
    SpaceLevel: {
        PUBLIC: "public",
        DEPARTMENT: "department",
        TEAM: "team",
        PERSONAL: "personal",
    },
    VisibilityType: {
        PUBLIC: "public",
        PRIVATE: "private",
        APPROVAL: "approval",
    },
    getGroupedSpacesApi: jest.fn(),
    getCreateSpaceOptionsApi: jest.fn(),
    createSpaceApi: jest.fn(),
    getMineSpacesApi: jest.fn(),
    getJoinedSpacesApi: jest.fn(),
    getDepartmentSpacesApi: jest.fn(),
    getSpaceInfoApi: jest.fn(),
    updateSpaceApi: jest.fn(),
    deleteSpaceApi: jest.fn(),
    unsubscribeSpaceApi: jest.fn(),
    pinSpaceApi: jest.fn(),
    getSpaceChildrenApi: jest.fn(),
    searchSpaceChildrenApi: jest.fn(),
    batchDownloadApi: jest.fn(),
    batchDeleteApi: jest.fn(),
    batchRetryApi: jest.fn(),
    getFileDownloadApi: jest.fn(),
    getFilePreviewApi: jest.fn(),
    fileStatusToNumber: jest.fn((status) => {
        const map: Record<string, number> = {
            processing: 1,
            success: 2,
            failed: 3,
            rebuilding: 4,
            waiting: 5,
            timeout: 6,
            violation: 7,
            uploading: 0,
        };
        return map[String(status)] ?? 0;
    }),
}));

const makeSpace = (id: string, name: string, overrides: Record<string, any> = {}) => ({
    id,
    name,
    description: "",
    icon: "",
    visibility: "public",
    creator: "tester",
    creatorId: "1",
    memberCount: 1,
    fileCount: 0,
    totalFileCount: 0,
    role: SpaceRole.MEMBER,
    isPinned: false,
    createdAt: "",
    updatedAt: "",
    tags: [],
    spaceLevel: SpaceLevel.PERSONAL,
    ...overrides,
});

const makeFile = (id: string, name: string, overrides: Record<string, any> = {}) => ({
    id,
    name,
    type: FileType.MD,
    size: 1024,
    status: FileStatus.SUCCESS,
    tags: [],
    path: name,
    parentId: undefined,
    spaceId: "personal-1",
    createdAt: "",
    updatedAt: "",
    ...overrides,
});

function renderWorkbench() {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: {
                retry: false,
            },
        },
    });

    return render(
        <QueryClientProvider client={queryClient}>
            <PortalKnowledgeWorkbench />
        </QueryClientProvider>,
    );
}

describe("PortalKnowledgeWorkbench", () => {
    beforeEach(() => {
        jest.clearAllMocks();
        Object.defineProperty(navigator, "clipboard", {
            configurable: true,
            value: {
                writeText: mockClipboardWriteText,
            },
        });
        mockClipboardWriteText.mockResolvedValue(undefined);
        mockConfirm.mockResolvedValue(true);
        mockUseKnowledgeSpaceActionPermissions.mockReturnValue({
            permissions: {},
            loading: false,
        });
        jest.mocked(getCreateSpaceOptionsApi).mockResolvedValue({
            canCreatePublic: true,
            canCreateDepartment: true,
            canCreateTeam: true,
            canCreatePersonal: true,
            departments: [],
            userGroups: [],
            defaultSpaceLevel: SpaceLevel.PERSONAL,
        } as any);
        jest.mocked(getSpaceChildrenApi).mockImplementation(() => new Promise(() => undefined) as any);
        jest.mocked(searchSpaceChildrenApi).mockResolvedValue({ data: [], total: 0 } as any);
        jest.mocked(getFilePreviewApi).mockResolvedValue({
            preview_url: "/preview.md",
            original_url: "/origin.md",
        } as any);
        jest.mocked(getFileDownloadApi).mockResolvedValue({
            preview_url: "/preview.md",
            original_url: "/origin.md",
        } as any);
        jest.mocked(batchDownloadApi).mockResolvedValue("/download.zip");
        jest.mocked(batchDeleteApi).mockResolvedValue(undefined as any);
        jest.mocked(batchRetryApi).mockResolvedValue(undefined as any);
        mockCheckPermission.mockResolvedValue({ allowed: true });
    });

    test("renders knowledge space groups from grouped API without recomputing joined spaces", async () => {
        const publicSpace = makeSpace("public-1", "公共空间01");
        const teamSpace = makeSpace("team-1", "团队空间01");

        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [publicSpace],
            departmentSpaces: [],
            teamSpaces: [teamSpace],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        await waitFor(() => {
            expect(getGroupedSpacesApi).toHaveBeenCalledWith({ order_by: SpaceSortType.UPDATE_TIME });
        });

        expect(getMineSpacesApi).not.toHaveBeenCalled();
        expect(getJoinedSpacesApi).not.toHaveBeenCalled();
        expect(getDepartmentSpacesApi).not.toHaveBeenCalled();

        const publicGroup = screen.getByTestId("space-group-public");
        const teamGroup = screen.getByTestId("space-group-team");

        expect(within(publicGroup).getByText("公共空间01")).toBeInTheDocument();
        expect(within(teamGroup).getByText("团队空间01")).toBeInTheDocument();
        expect(within(teamGroup).queryByText("公共空间01")).not.toBeInTheDocument();

        expect(screen.getByTestId("space-group-icon-public")).toHaveAttribute(
            "src",
            "/assets/knowledge-portal/space-public.png",
        );
        expect(screen.getByTestId("space-group-icon-department")).toHaveAttribute(
            "src",
            "/assets/knowledge-portal/space-department.png",
        );
        expect(screen.getByTestId("space-group-icon-team")).toHaveAttribute(
            "src",
            "/assets/knowledge-portal/space-team.png",
        );
        expect(screen.getByTestId("space-group-icon-personal")).toHaveAttribute(
            "src",
            "/assets/knowledge-portal/space-personal.png",
        );
    });

    test("keeps empty state when grouped API returns no spaces", async () => {
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        await waitFor(() => {
            expect(screen.getByText("暂无可用知识库")).toBeInTheDocument();
        });

        expect(screen.getAllByText("暂无知识库").length).toBeGreaterThan(0);
    });

    test("selects the clicked collapsed group first space when restoring the sidebar", async () => {
        const publicSpace = makeSpace("public-1", "公共空间01");
        const teamSpace = makeSpace("team-1", "团队空间01");

        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [publicSpace],
            departmentSpaces: [],
            teamSpaces: [teamSpace],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        await waitFor(() => {
            expect(screen.getByTestId("active-space-title")).toHaveTextContent("公共空间01");
        });

        fireEvent.click(screen.getByRole("button", { name: "收起知识库侧栏" }));

        expect(screen.queryByText("公共知识库")).not.toBeInTheDocument();
        expect(screen.getByRole("button", { name: "打开公共知识库分组" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "打开团队知识库分组" })).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: "打开团队知识库分组" }));

        const teamGroup = screen.getByTestId("space-group-team");

        expect(within(teamGroup).getByText("团队空间01")).toBeInTheDocument();
        expect(screen.getByTestId("active-space-title")).toHaveTextContent("团队空间01");
    });

    test("keeps current space when restoring an empty collapsed group", async () => {
        const publicSpace = makeSpace("public-1", "公共空间01");

        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [publicSpace],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        await waitFor(() => {
            expect(screen.getByTestId("active-space-title")).toHaveTextContent("公共空间01");
        });

        fireEvent.click(screen.getByRole("button", { name: "收起知识库侧栏" }));
        fireEvent.click(screen.getByRole("button", { name: "打开团队知识库分组" }));

        const teamGroup = screen.getByTestId("space-group-team");

        expect(within(teamGroup).getByText("暂无知识库")).toBeInTheDocument();
        expect(screen.getByTestId("active-space-title")).toHaveTextContent("公共空间01");
    });

    test("opens create drawer with the clicked group level and does not toggle the group", async () => {
        const publicSpace = makeSpace("public-1", "公共空间01");

        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [publicSpace],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        await waitFor(() => {
            expect(screen.getByRole("button", { name: "新增公共知识库知识空间" })).toBeEnabled();
        });

        const publicGroup = screen.getByTestId("space-group-public");
        expect(within(publicGroup).getByText("公共空间01")).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: "新增公共知识库知识空间" }));

        expect(screen.getByTestId("create-space-drawer")).toHaveTextContent(`initial:${SpaceLevel.PUBLIC}`);
        expect(within(publicGroup).getByText("公共空间01")).toBeInTheDocument();
    });

    test("opens create drawer with team level from team group create action", async () => {
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        const teamCreateButton = await screen.findByRole("button", { name: "新增团队知识库知识空间" });
        expect(teamCreateButton).toBeEnabled();

        fireEvent.click(teamCreateButton);

        expect(screen.getByTestId("create-space-drawer")).toHaveTextContent(`initial:${SpaceLevel.TEAM}`);
    });

    test("creates a knowledge space with the selected group level", async () => {
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [],
        } as any);
        jest.mocked(createSpaceApi).mockResolvedValue(makeSpace("new-team", "新空间") as any);

        renderWorkbench();

        fireEvent.click(await screen.findByRole("button", { name: "新增团队知识库知识空间" }));
        fireEvent.click(screen.getByRole("button", { name: "提交创建" }));

        await waitFor(() => {
            expect(createSpaceApi).toHaveBeenCalledWith({
                name: "新空间",
                description: "说明",
                auth_type: VisibilityType.APPROVAL,
                is_released: true,
                space_level: SpaceLevel.TEAM,
                department_id: undefined,
                user_group_id: undefined,
                auto_tag_enabled: false,
                auto_tag_library_id: null,
            });
        });
    });

    test("shows create row under a permitted group and opens drawer with that group level", async () => {
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        const personalGroup = screen.getByTestId("space-group-personal");
        const createRow = await within(personalGroup).findByRole("button", { name: "新建知识库" });

        expect(createRow).toBeEnabled();

        fireEvent.click(createRow);

        expect(screen.getByTestId("create-space-drawer")).toHaveTextContent(`initial:${SpaceLevel.PERSONAL}`);
    });

    test("hides create row under a group without create permission", async () => {
        jest.mocked(getCreateSpaceOptionsApi).mockResolvedValue({
            canCreatePublic: true,
            canCreateDepartment: true,
            canCreateTeam: false,
            canCreatePersonal: true,
            departments: [],
            userGroups: [],
            defaultSpaceLevel: SpaceLevel.PERSONAL,
        } as any);
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        const teamGroup = screen.getByTestId("space-group-team");

        await waitFor(() => {
            expect(within(teamGroup).queryByRole("button", { name: "新建知识库" })).not.toBeInTheDocument();
        });
        expect(screen.getByRole("button", { name: "新增团队知识库知识空间" })).toBeDisabled();
    });

    test("disables create action for groups without create permission", async () => {
        jest.mocked(getCreateSpaceOptionsApi).mockResolvedValue({
            canCreatePublic: true,
            canCreateDepartment: false,
            canCreateTeam: false,
            canCreatePersonal: true,
            departments: [],
            userGroups: [],
            defaultSpaceLevel: SpaceLevel.PERSONAL,
        } as any);
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        const teamCreateButton = await screen.findByRole("button", { name: "新增团队知识库知识空间" });
        expect(teamCreateButton).toBeDisabled();

        fireEvent.click(teamCreateButton);

        expect(screen.queryByTestId("create-space-drawer")).not.toBeInTheDocument();
    });

    test("shows permitted space menu actions without selecting the menu target", async () => {
        const publicSpace = makeSpace("public-1", "公共空间01", {
            spaceLevel: SpaceLevel.PUBLIC,
        });
        const teamSpace = makeSpace("team-1", "团队空间01", {
            spaceLevel: SpaceLevel.TEAM,
        });
        mockUseKnowledgeSpaceActionPermissions.mockReturnValue({
            permissions: {
                "team-1": ["edit_space", "manage_space_relation", "delete_space"],
            },
            loading: false,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [publicSpace],
            departmentSpaces: [],
            teamSpaces: [teamSpace],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        await waitFor(() => {
            expect(screen.getByTestId("active-space-title")).toHaveTextContent("公共空间01");
        });

        const teamRow = screen.getByTestId("space-row-team-1");
        fireEvent.click(within(teamRow).getByRole("button", { name: "更多团队空间01操作" }));

        expect(screen.getByTestId("active-space-title")).toHaveTextContent("公共空间01");
        expect(within(teamRow).getByRole("button", { name: "空间设置" })).toBeInTheDocument();
        expect(within(teamRow).getByRole("button", { name: "成员管理" })).toBeInTheDocument();
        expect(within(teamRow).getByRole("button", { name: "置顶空间" })).toBeInTheDocument();
        expect(within(teamRow).getByRole("button", { name: "删除空间" })).toBeInTheDocument();
        expect(within(teamRow).queryByRole("button", { name: "退出空间" })).not.toBeInTheDocument();
    });

    test("opens space settings drawer with fetched space detail", async () => {
        const teamSpace = makeSpace("team-1", "团队空间01", {
            spaceLevel: SpaceLevel.TEAM,
        });
        mockUseKnowledgeSpaceActionPermissions.mockReturnValue({
            permissions: {
                "team-1": ["edit_space"],
            },
            loading: false,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [teamSpace],
            personalSpaces: [],
        } as any);
        jest.mocked(getSpaceInfoApi).mockResolvedValue(makeSpace("team-1", "团队空间详情", {
            spaceLevel: SpaceLevel.TEAM,
        }) as any);

        renderWorkbench();

        const teamRow = await screen.findByTestId("space-row-team-1");
        fireEvent.click(within(teamRow).getByRole("button", { name: "空间设置" }));

        await waitFor(() => {
            expect(getSpaceInfoApi).toHaveBeenCalledWith("team-1");
            expect(screen.getByTestId("create-space-drawer")).toHaveTextContent("mode:edit");
            expect(screen.getByTestId("create-space-drawer")).toHaveTextContent("editing:团队空间详情");
        });
    });

    test("shows leave action for unsubscribable spaces without delete permission", async () => {
        const teamSpace = makeSpace("team-1", "团队空间01", {
            canUnsubscribe: true,
            spaceLevel: SpaceLevel.TEAM,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [teamSpace],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        const teamRow = await screen.findByTestId("space-row-team-1");

        expect(within(teamRow).queryByRole("button", { name: "删除空间" })).not.toBeInTheDocument();

        fireEvent.click(within(teamRow).getByRole("button", { name: "退出空间" }));

        await waitFor(() => {
            expect(unsubscribeSpaceApi).toHaveBeenCalledWith("team-1");
        });
    });

    test("does not delete a space when delete confirmation is cancelled", async () => {
        const teamSpace = makeSpace("team-1", "团队空间01", {
            spaceLevel: SpaceLevel.TEAM,
        });
        mockConfirm.mockResolvedValue(false);
        mockUseKnowledgeSpaceActionPermissions.mockReturnValue({
            permissions: {
                "team-1": ["delete_space"],
            },
            loading: false,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [teamSpace],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        const teamRow = await screen.findByTestId("space-row-team-1");
        fireEvent.click(within(teamRow).getByRole("button", { name: "删除空间" }));

        await waitFor(() => {
            expect(mockConfirm).toHaveBeenCalled();
        });
        expect(deleteSpaceApi).not.toHaveBeenCalled();
    });

    test("blocks pinning when a group already has five pinned spaces", async () => {
        const pinnedSpaces = Array.from({ length: 5 }, (_, index) => makeSpace(
            `team-pinned-${index}`,
            `团队置顶${index}`,
            { isPinned: true, spaceLevel: SpaceLevel.TEAM },
        ));
        const teamSpace = makeSpace("team-1", "团队空间01", {
            spaceLevel: SpaceLevel.TEAM,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [...pinnedSpaces, teamSpace],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        const teamRow = await screen.findByTestId("space-row-team-1");
        fireEvent.click(within(teamRow).getByRole("button", { name: "置顶空间" }));

        expect(pinSpaceApi).not.toHaveBeenCalled();
        expect(mockShowToast).toHaveBeenCalled();
    });

    test("renders the root file tree with checkboxes, statuses, and folder counts", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
        });
        const folder = makeFile("101", "技术文档", {
            type: FileType.FOLDER,
            successFileNum: 1,
            fileNum: 7,
        });
        const file = makeFile("201", "后端开发.md", {
            status: FileStatus.SUCCESS,
        });
        const pendingFile = makeFile("202", "架构开发文档.pdf", {
            type: FileType.PDF,
            status: FileStatus.PROCESSING,
        });
        const noStatusFile = makeFile("203", "无状态文档.md", {
            status: undefined,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [folder, file, pendingFile, noStatusFile],
            total: 4,
        } as any);

        renderWorkbench();

        const folderRow = await screen.findByTestId("file-tree-row-101");
        const fileRow = screen.getByTestId("file-tree-row-201");
        const noStatusRow = screen.getByTestId("file-tree-row-203");

        expect(within(folderRow).getByRole("checkbox", { name: "选择技术文档" })).toBeInTheDocument();
        expect(within(folderRow).getByText("(1/7)")).toBeInTheDocument();
        expect(within(fileRow).getByRole("checkbox", { name: "选择后端开发.md" })).toBeInTheDocument();
        expect(within(fileRow).getByText("成功")).toBeInTheDocument();
        expect(screen.getAllByText("解析中").length).toBeGreaterThan(0);
        expect(within(noStatusRow).queryByText("成功")).not.toBeInTheDocument();
        expect(within(noStatusRow).queryByText("0/0")).not.toBeInTheDocument();
    });

    test("uses existing Bisheng file type icons in the portal file tree", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
        });
        const folder = makeFile("101", "技术文档", {
            type: FileType.FOLDER,
            successFileNum: 1,
            fileNum: 7,
        });
        const markdownFile = makeFile("201", "后端开发.md");
        const pdfFile = makeFile("202", "架构开发文档.pdf", {
            type: FileType.PDF,
        });
        const docFile = makeFile("203", "数据库优化方案.doc", {
            type: FileType.DOC,
        });
        const xlsxFile = makeFile("204", "经营指标.xlsx", {
            type: "xlsx",
        });
        const unknownFile = makeFile("205", "未知格式文件.unknown", {
            type: "unknown",
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [folder, markdownFile, pdfFile, docFile, xlsxFile, unknownFile],
            total: 6,
        } as any);

        renderWorkbench();

        const folderRow = await screen.findByTestId("file-tree-row-101");
        expect(within(folderRow).getByTestId("legacy-file-icon-dir")).toBeInTheDocument();
        expect(within(folderRow).getByText("(1/7)")).toBeInTheDocument();
        expect(within(screen.getByTestId("file-tree-row-201")).getByTestId("legacy-file-icon-md")).toBeInTheDocument();
        expect(within(screen.getByTestId("file-tree-row-202")).getByTestId("legacy-file-icon-pdf")).toBeInTheDocument();
        expect(within(screen.getByTestId("file-tree-row-203")).getByTestId("legacy-file-icon-doc")).toBeInTheDocument();
        expect(within(screen.getByTestId("file-tree-row-204")).getByTestId("legacy-file-icon-xlsx")).toBeInTheDocument();
        expect(within(screen.getByTestId("file-tree-row-205")).getByTestId("legacy-file-icon-txt")).toBeInTheDocument();
    });

    test("lazy-loads child files when expanding a folder", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
        });
        const folder = makeFile("101", "技术文档", {
            type: FileType.FOLDER,
            successFileNum: 1,
            fileNum: 7,
        });
        const childFile = makeFile("301", "前端开发.md", {
            parentId: "101",
            status: FileStatus.UPLOADING,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockImplementation(({ parent_id }: any) => Promise.resolve(
            parent_id === "101"
                ? { data: [childFile], total: 1 }
                : { data: [folder], total: 1 },
        ) as any);

        renderWorkbench();

        const folderRow = await screen.findByTestId("file-tree-row-101");
        fireEvent.click(within(folderRow).getByRole("button", { name: "展开技术文档" }));

        const childRow = await screen.findByTestId("file-tree-row-301");
        expect(getSpaceChildrenApi).toHaveBeenCalledWith(expect.objectContaining({
            space_id: "personal-1",
            parent_id: "101",
            page: 1,
            page_size: 100,
        }));
        expect(within(childRow).getByText("前端开发.md")).toBeInTheDocument();
        expect(within(childRow).getByText("上传中")).toBeInTheDocument();
    });

    test("checkbox selection does not preview while file row selection previews", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
        });
        const file = makeFile("201", "后端开发.md");
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [file],
            total: 1,
        } as any);

        renderWorkbench();

        const fileRow = await screen.findByTestId("file-tree-row-201");
        fireEvent.click(within(fileRow).getByRole("checkbox", { name: "选择后端开发.md" }));

        expect(getFilePreviewApi).not.toHaveBeenCalled();
        expect(screen.getByRole("button", { name: "批量操作" })).toBeEnabled();

        fireEvent.click(within(fileRow).getByRole("button", { name: "打开后端开发.md" }));

        await waitFor(() => {
            expect(getFilePreviewApi).toHaveBeenCalledWith("personal-1", "201");
        });
    });

    test("renders document preview actions in Lanhu order and opens the existing portals", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
        });
        const file = makeFile("201", "后端开发.md", {
            fileEncoding: "RPT-PP-00000001",
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [file],
            total: 1,
        } as any);

        renderWorkbench();

        const fileRow = await screen.findByTestId("file-tree-row-201");
        fireEvent.click(within(fileRow).getByRole("button", { name: "打开后端开发.md" }));

        const actions = await screen.findByTestId("portal-document-actions");
        expect(
            within(actions).getAllByRole("button").map((button) => button.getAttribute("aria-label")),
        ).toEqual([
            "AI 对话",
            "编辑标签",
            "分享",
            "下载",
            "权限管理",
            "复制",
        ]);

        fireEvent.click(within(actions).getByRole("button", { name: "AI 对话" }));
        expect(screen.getByTestId("knowledge-ai-panel")).toBeInTheDocument();

        fireEvent.click(within(actions).getByRole("button", { name: "编辑标签" }));
        expect(screen.getByTestId("edit-tags-modal")).toBeInTheDocument();

        fireEvent.click(within(actions).getByRole("button", { name: "分享" }));
        expect(screen.getByText("分享")).toBeInTheDocument();

        fireEvent.click(within(actions).getByRole("button", { name: "下载" }));
        await waitFor(() => {
            expect(getFileDownloadApi).toHaveBeenCalledWith("personal-1", "201");
        });

        fireEvent.click(within(actions).getByRole("button", { name: "权限管理" }));
        expect(screen.getByTestId("space-share-dialog")).toHaveTextContent("成员管理:后端开发.md");
    });

    test("shows the portal right rail only after selecting a file with the required preview entries", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
        });
        const file = makeFile("201", "后端开发.md");
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [file],
            total: 1,
        } as any);

        renderWorkbench();

        await screen.findByTestId("active-space-title");
        expect(screen.queryByTestId("portal-tool-rail")).not.toBeInTheDocument();

        const fileRow = await screen.findByTestId("file-tree-row-201");
        fireEvent.click(within(fileRow).getByRole("button", { name: "打开后端开发.md" }));

        const rail = await screen.findByTestId("portal-tool-rail");
        expect(within(rail).getAllByRole("button").map((button) => button.getAttribute("aria-label"))).toEqual([
            "侧边栏展开和关闭",
            "属性",
            "时间",
            "来源",
            "使用",
            "权限",
        ]);
        expect(within(rail).queryByRole("button", { name: "摘要" })).not.toBeInTheDocument();
        expect(within(rail).queryByRole("button", { name: "分享" })).not.toBeInTheDocument();
        expect(within(rail).queryByRole("button", { name: "AI 助手" })).not.toBeInTheDocument();
        expect(within(rail).queryByRole("button", { name: "标签" })).not.toBeInTheDocument();
        expect(within(rail).queryByRole("button", { name: "下载" })).not.toBeInTheDocument();
        expect(within(rail).queryByRole("button", { name: "更多能力" })).not.toBeInTheDocument();
        expect(within(rail).queryByRole("button", { name: "智能入库" })).not.toBeInTheDocument();
        expect(within(rail).queryByRole("button", { name: "复杂版本管理" })).not.toBeInTheDocument();
        expect(within(rail).queryByRole("button", { name: "外部链接" })).not.toBeInTheDocument();
    });

    test("opens the new right rail panels and keeps permission on the existing dialog", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
        });
        const file = makeFile("201", "后端开发.md", {
            size: 2048,
            updatedAt: "2026-05-20T12:30:00",
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [file],
            total: 1,
        } as any);

        renderWorkbench();

        const fileRow = await screen.findByTestId("file-tree-row-201");
        fireEvent.click(within(fileRow).getByRole("button", { name: "打开后端开发.md" }));

        const rail = await screen.findByTestId("portal-tool-rail");
        fireEvent.click(within(rail).getByRole("button", { name: "侧边栏展开和关闭" }));
        const drawer = await screen.findByTestId("portal-info-drawer");
        expect(within(drawer).getByText("属性")).toBeInTheDocument();
        expect(within(drawer).getByText("后端开发.md")).toBeInTheDocument();
        expect(within(drawer).getByText("2.0 KB")).toBeInTheDocument();

        fireEvent.click(within(rail).getByRole("button", { name: "侧边栏展开和关闭" }));
        expect(screen.queryByTestId("portal-info-drawer")).not.toBeInTheDocument();

        fireEvent.click(within(rail).getByRole("button", { name: "时间" }));
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("时间");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("暂未开放");

        fireEvent.click(within(rail).getByRole("button", { name: "来源" }));
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("来源");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("暂未开放");

        fireEvent.click(within(rail).getByRole("button", { name: "使用" }));
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("使用");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("暂未开放");

        fireEvent.click(within(rail).getByRole("button", { name: "权限" }));
        expect(screen.getByTestId("space-share-dialog")).toHaveTextContent("成员管理:后端开发.md");
    });

    test("copies the selected file encoding from the document header", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
        });
        const file = makeFile("201", "后端开发.md", {
            fileEncoding: "RPT-PP-00000001",
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [file],
            total: 1,
        } as any);

        renderWorkbench();

        const fileRow = await screen.findByTestId("file-tree-row-201");
        fireEvent.click(within(fileRow).getByRole("button", { name: "打开后端开发.md" }));

        const actions = await screen.findByTestId("portal-document-actions");
        fireEvent.click(within(actions).getByRole("button", { name: "复制" }));

        await waitFor(() => {
            expect(mockClipboardWriteText).toHaveBeenCalledWith("RPT-PP-00000001");
        });
        expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({
            message: "文件编码已复制",
        }));
    });

    test("does not copy an empty file encoding", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
        });
        const file = makeFile("201", "后端开发.md", {
            fileEncoding: null,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [file],
            total: 1,
        } as any);

        renderWorkbench();

        const fileRow = await screen.findByTestId("file-tree-row-201");
        fireEvent.click(within(fileRow).getByRole("button", { name: "打开后端开发.md" }));

        const actions = await screen.findByTestId("portal-document-actions");
        fireEvent.click(within(actions).getByRole("button", { name: "复制" }));

        expect(mockClipboardWriteText).not.toHaveBeenCalled();
        expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({
            message: "暂无文件编码",
        }));
    });

    test("expands summary details inline from the summary bar without rendering save action", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
        });
        const file = makeFile("201", "后端开发.md", {
            summary: "这是一段完整的文档摘要内容",
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [file],
            total: 1,
        } as any);

        renderWorkbench();

        const fileRow = await screen.findByTestId("file-tree-row-201");
        fireEvent.click(within(fileRow).getByRole("button", { name: "打开后端开发.md" }));

        expect(screen.queryByText("保存摘要")).not.toBeInTheDocument();

        const summaryButton = await screen.findByRole("button", { name: "查看文档摘要" });
        fireEvent.click(summaryButton);

        expect(summaryButton).toHaveAttribute("aria-expanded", "true");
        const summaryDetail = screen.getByTestId("portal-summary-detail");
        expect(summaryDetail).toHaveTextContent("这是一段完整的文档摘要内容");
        expect(screen.queryByText("摘要内容")).not.toBeInTheDocument();
    });

    test("keeps the active file row from changing tree indentation", () => {
        const css = readFileSync(path.join(__dirname, "PortalKnowledgeWorkbench.module.css"), "utf8");
        const activeRule = css.match(/\.treeRowActive\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";

        expect(activeRule).not.toMatch(/margin-left\s*:/);
        expect(activeRule).not.toMatch(/width\s*:\s*calc\(100%\s*-/);
    });

    test("scrolls the whole document preview instead of only the article area", () => {
        const css = readFileSync(path.join(__dirname, "PortalKnowledgeWorkbench.module.css"), "utf8");
        const documentShellRule = css.match(/\.documentShell\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";
        const previewHostRule = css.match(/\.previewHost\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";

        expect(documentShellRule).toMatch(/overflow-y\s*:\s*auto/);
        expect(previewHostRule).not.toMatch(/overflow\s*:\s*auto/);
        expect(previewHostRule).not.toMatch(/overflow-y\s*:\s*auto/);
    });

    test("renders Lanhu file action buttons in the required order", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [],
            total: 0,
        } as any);

        renderWorkbench();

        await screen.findByTestId("active-space-title");

        const actions = screen.getByTestId("portal-file-actions");
        expect(
            within(actions).getAllByRole("button").map((button) => button.getAttribute("aria-label")).filter(Boolean),
        ).toEqual([
            "上传",
            "网页链接",
            "在线创建文档",
            "新建文件夹",
            "筛选",
            "批量操作",
        ]);
    });

    test("shows unavailable toast for web link and online document placeholders", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [],
            total: 0,
        } as any);

        renderWorkbench();

        fireEvent.click(await screen.findByRole("button", { name: "网页链接" }));
        fireEvent.click(screen.getByRole("button", { name: "在线创建文档" }));

        expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({
            message: "暂未开放",
        }));
        expect(batchDownloadApi).not.toHaveBeenCalled();
        expect(batchDeleteApi).not.toHaveBeenCalled();
        expect(batchRetryApi).not.toHaveBeenCalled();
    });

    test("reloads the portal file tree with selected status filters", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [],
            total: 0,
        } as any);

        renderWorkbench();

        await waitFor(() => {
            expect(getSpaceChildrenApi).toHaveBeenCalledWith(expect.objectContaining({
                space_id: "personal-1",
                page: 1,
                page_size: 100,
            }));
        });

        fireEvent.click(screen.getByRole("button", { name: "筛选" }));
        fireEvent.click(screen.getByRole("button", { name: "成功" }));

        await waitFor(() => {
            expect(getSpaceChildrenApi).toHaveBeenCalledWith(expect.objectContaining({
                space_id: "personal-1",
                page: 1,
                page_size: 100,
                file_status: [2],
            }));
        });
    });

    test("search requests include selected status filters", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [],
            total: 0,
        } as any);
        jest.mocked(searchSpaceChildrenApi).mockResolvedValue({
            data: [],
            total: 0,
        } as any);

        renderWorkbench();

        fireEvent.click(await screen.findByRole("button", { name: "筛选" }));
        fireEvent.click(screen.getByRole("button", { name: "失败" }));

        const input = screen.getByPlaceholderText("搜索文件...");
        fireEvent.change(input, { target: { value: "后端" } });
        fireEvent.keyDown(input, { key: "Enter" });

        await waitFor(() => {
            expect(searchSpaceChildrenApi).toHaveBeenCalledWith(expect.objectContaining({
                space_id: "personal-1",
                keyword: "后端",
                page: 1,
                page_size: 100,
                file_status: [3],
            }));
        });
    });

    test("searches files as a flat result list and restores tree when keyword is cleared", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
        });
        const rootFile = makeFile("201", "后端开发.md");
        const matchedFile = makeFile("401", "搜索结果.md", {
            status: FileStatus.FAILED,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [rootFile],
            total: 1,
        } as any);
        jest.mocked(searchSpaceChildrenApi).mockResolvedValue({
            data: [matchedFile],
            total: 1,
        } as any);

        renderWorkbench();

        expect(await screen.findByText("后端开发.md")).toBeInTheDocument();

        const input = screen.getByPlaceholderText("搜索文件...");
        fireEvent.change(input, { target: { value: "搜索" } });
        fireEvent.keyDown(input, { key: "Enter" });

        expect(await screen.findByText("搜索结果")).toBeInTheDocument();
        expect(screen.getByText("搜索结果.md")).toBeInTheDocument();
        expect(screen.queryByText("后端开发.md")).not.toBeInTheDocument();

        fireEvent.change(input, { target: { value: "" } });

        expect(await screen.findByText("后端开发.md")).toBeInTheDocument();
        expect(screen.queryByText("搜索结果.md")).not.toBeInTheDocument();
    });

    test("runs real batch actions for selected files and folders", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
        });
        const folder = makeFile("101", "技术文档", {
            type: FileType.FOLDER,
            successFileNum: 0,
            fileNum: 1,
        });
        const failedFile = makeFile("201", "失败文档.md", {
            status: FileStatus.FAILED,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [folder, failedFile],
            total: 2,
        } as any);

        renderWorkbench();

        expect(await screen.findByRole("button", { name: "批量操作" })).toBeDisabled();

        const folderRow = await screen.findByTestId("file-tree-row-101");
        const fileRow = screen.getByTestId("file-tree-row-201");
        fireEvent.click(within(folderRow).getByRole("checkbox", { name: "选择技术文档" }));
        fireEvent.click(within(fileRow).getByRole("checkbox", { name: "选择失败文档.md" }));

        fireEvent.click(screen.getByRole("button", { name: "批量下载" }));
        await waitFor(() => {
            expect(batchDownloadApi).toHaveBeenCalledWith("personal-1", {
                file_ids: [201],
                folder_ids: [101],
            });
        });

        fireEvent.click(screen.getByRole("button", { name: "批量重试" }));
        await waitFor(() => {
            expect(batchRetryApi).toHaveBeenCalledWith("personal-1", [101, 201]);
        });

        fireEvent.click(within(folderRow).getByRole("checkbox", { name: "选择技术文档" }));
        fireEvent.click(within(fileRow).getByRole("checkbox", { name: "选择失败文档.md" }));
        fireEvent.click(screen.getByRole("button", { name: "批量删除" }));
        await waitFor(() => {
            expect(batchDeleteApi).toHaveBeenCalledWith("personal-1", {
                file_ids: [201],
                folder_ids: [101],
            });
        });
    });
});
