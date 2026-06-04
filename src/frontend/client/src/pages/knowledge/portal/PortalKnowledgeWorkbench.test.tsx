import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "fs";
import path from "path";
import { RecoilRoot } from "recoil";
import PortalKnowledgeWorkbench from "./PortalKnowledgeWorkbench";
import {
    getShougangFilePublishSimilarCandidatesApi,
    getShougangFilePublishTargetSpacesApi,
    searchShougangFilePublishDocumentsApi,
    submitShougangFilePublishApprovalApi,
    submitShougangKnowledgeSpaceCreateApprovalApi,
} from "~/api/approval";
import {
    FileStatus,
    FileType,
    SpaceLevel,
    SpaceRole,
    SpaceSortType,
    VisibilityType,
    addFilesApi,
    batchDeleteApi,
    batchDownloadApi,
    batchRetryApi,
    createFolderApi,
    createSpaceApi,
    deleteSpaceApi,
    getCreateSpaceOptionsApi,
    getDepartmentSpacesApi,
    getFileDownloadApi,
    getFilePreviewApi,
    getGroupedSpacesApi,
    getJoinedSpacesApi,
    getSimilarCandidatesApi,
    getMineSpacesApi,
    getSpaceChildrenApi,
    getSpaceInfoApi,
    getSpaceTagsApi,
    linkAsNewVersionApi,
    listMyUploadedFilesApi,
    listKnowledgeFolders,
    moveUploadedFileFolderApi,
    pinSpaceApi,
    recommendUploadFoldersApi,
    searchSpaceChildrenApi,
    unsubscribeSpaceApi,
    updateFileEncoding,
    uploadFileToServerApi,
} from "~/api/knowledge";

function stripComments(source: string): string {
    return source
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/^\s*\/\/.*$/gm, "");
}

const mockShowToast = jest.fn();
const mockConfirm = jest.fn();
const mockUseKnowledgeSpaceActionPermissions = jest.fn();
const mockCheckPermission = jest.fn();
const mockClipboardWriteText = jest.fn();
const mockHandleUploadFile = jest.fn();
let mockCreateSpaceConfirmResult: any;

jest.mock("~/Providers", () => ({
    useToastContext: () => ({
        showToast: mockShowToast,
    }),
    useConfirm: () => mockConfirm,
}));

jest.mock("~/hooks/queries/endpoints/queries", () => ({
    useGetBsConfig: () => ({
        data: {
            shougang: {
                enabled: true,
                file_encoding: {
                    document_types: [
                        { code: "RPT", label: "报告" },
                        { code: "STD", label: "标准规范" },
                    ],
                },
            },
        },
    }),
}));

jest.mock("~/components/ui", () => ({
    Button: ({ children, ...props }: any) => <button {...props}>{children}</button>,
    Checkbox: ({ checked, onCheckedChange, ...props }: any) => (
        <input
            type="checkbox"
            checked={checked === true}
            aria-checked={checked === "indeterminate" ? "mixed" : Boolean(checked)}
            onChange={() => onCheckedChange?.(!(checked === true))}
            {...props}
        />
    ),
    Dialog: ({ open, children }: any) => (open ? <div>{children}</div> : null),
    DialogContent: ({ children }: any) => <div>{children}</div>,
    DialogFooter: ({ children }: any) => <div>{children}</div>,
    DialogHeader: ({ children }: any) => <div>{children}</div>,
    DialogTitle: ({ children }: any) => <div>{children}</div>,
    DropdownMenu: ({ children }: any) => <div>{children}</div>,
    DropdownMenuTrigger: ({ children }: any) => <div>{children}</div>,
    DropdownMenuContent: ({ children }: any) => <div>{children}</div>,
    DropdownMenuItem: ({ children, disabled, onClick }: any) => (
        <button type="button" disabled={disabled} onClick={onClick}>
            {children}
        </button>
    ),
    DropdownMenuSeparator: () => <hr />,
    Input: (props: any) => <input {...props} />,
}));

jest.mock("~/components/ui/DropdownMenu", () => ({
    DropdownMenu: ({ children }: any) => <div>{children}</div>,
    DropdownMenuTrigger: ({ children }: any) => <div>{children}</div>,
    DropdownMenuContent: ({ children }: any) => <div>{children}</div>,
    DropdownMenuItem: ({ children, disabled, onClick }: any) => (
        <button type="button" disabled={disabled} onClick={onClick}>
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
    EditTagsModal: ({ isOpen, spaceId, fileId, initialTagIds, onSaved }: any) => (
        isOpen ? (
            <div data-testid="edit-tags-modal">
                编辑标签弹窗
                <span data-testid="edit-tags-space-id">{spaceId}</span>
                <span data-testid="edit-tags-file-id">{fileId}</span>
                <span data-testid="edit-tags-initial-ids">{(initialTagIds || []).join(",")}</span>
                <button type="button" onClick={onSaved}>保存标签</button>
            </div>
        ) : null
    ),
}));

jest.mock("../SpaceDetail/AiChat/KnowledgeAiPanel", () => ({
    KnowledgeAiPanel: ({ spaceId, folderId, contextLabel, onClose }: any) => (
        <div data-testid="knowledge-ai-panel">
            <span>space:{spaceId}</span>
            <span>folder:{folderId || ""}</span>
            <span>context:{contextLabel}</span>
            <button type="button" onClick={onClose}>关闭知识AI</button>
        </div>
    ),
}));

jest.mock("~/pages/Subscription/AiChat/AiAssistantPanel", () => ({
    AiAssistantPanel: ({ fileChat, onClose, portalDrawer }: any) => (
        <div data-testid="ai-assistant-panel">
            文件AI:{fileChat?.spaceId}:{fileChat?.fileId}
            门户抽屉模式:{String(Boolean(portalDrawer))}
            <button type="button" onClick={onClose}>关闭AI组件</button>
        </div>
    ),
}));

jest.mock("../SpaceDetail/KnowledgeSpaceShareDialog", () => ({
    KnowledgeSpaceShareDialog: ({ open, resourceName, resourceType }: any) => (
        open ? <div data-testid="space-share-dialog">成员管理:{resourceType}:{resourceName}</div> : null
    ),
}));

jest.mock("~/components/approval/ApprovalCenterDialog", () => ({
    ApprovalCenterDialog: ({ open, target }: any) => (
        open ? <div data-testid="approval-center-dialog">审批中心:{target?.tab}</div> : null
    ),
}));

jest.mock("~/components/NotificationsDialog", () => ({
    NotificationsDialog: ({ open }: any) => (
        open ? <div data-testid="notifications-dialog">消息</div> : null
    ),
}));

jest.mock("~/components/ui/icon/File", () => ({
    __esModule: true,
    default: ({ type, className }: any) => (
        <span data-testid={`legacy-file-icon-${type}`} className={className} />
    ),
}));

jest.mock("../CreateKnowledgeSpaceDrawer", () => ({
    CreateKnowledgeSpaceDrawer: ({ open, initialSpaceLevel, mode = "create", editingSpace, showApprovalReason, showSuccessManageMembers, onConfirm }: any) => {
        if (!open) return null;
        const successManageMembersVisible = typeof showSuccessManageMembers === "function"
            ? showSuccessManageMembers(initialSpaceLevel)
            : showSuccessManageMembers !== false;
        return (
            <div data-testid="create-space-drawer">
                mode:{mode}
                initial:{initialSpaceLevel}
                editing:{editingSpace?.name || ""}
                approvalReason:{String(Boolean(showApprovalReason))}
                successManageMembers:{String(successManageMembersVisible)}
                <button
                    type="button"
                    onClick={async () => {
                        mockCreateSpaceConfirmResult = await onConfirm?.({
                            name: "新空间",
                            description: "说明",
                            reason: "申请创建团队知识库",
                            joinPolicy: "review",
                            publishToSquare: "no",
                            spaceLevel: initialSpaceLevel,
                            autoTagEnabled: false,
                            autoTagLibraryId: null,
                        });
                    }}
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
        handleUploadFile: mockHandleUploadFile,
        handleUploadFolder: jest.fn(),
        handleCancelCreateFolder: jest.fn(),
        handleRenameFile: jest.fn(),
        handleDeleteFile: jest.fn(),
        handleEditTags: jest.fn(),
        handleDuplicateSkip: jest.fn(),
        handleDuplicateOverwrite: jest.fn(),
    }),
}));

jest.mock("~/api/permission", () => ({
    checkPermission: (...args: any[]) => mockCheckPermission(...args),
    canOpenPermissionDialog: jest.fn(),
}));

jest.mock("~/api/approval", () => ({
    submitShougangKnowledgeSpaceCreateApprovalApi: jest.fn(),
    getShougangFilePublishTargetSpacesApi: jest.fn(),
    getShougangFilePublishSimilarCandidatesApi: jest.fn(),
    searchShougangFilePublishDocumentsApi: jest.fn(),
    submitShougangFilePublishApprovalApi: jest.fn(),
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
    SortType: {
        NAME: "file_name",
        TYPE: "file_type",
        SIZE: "file_size",
        UPDATE_TIME: "update_time",
    },
    SortDirection: {
        ASC: "asc",
        DESC: "desc",
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
    createFolderApi: jest.fn(),
    listKnowledgeFolders: jest.fn(),
    getMineSpacesApi: jest.fn(),
    getJoinedSpacesApi: jest.fn(),
    getDepartmentSpacesApi: jest.fn(),
    getSpaceInfoApi: jest.fn(),
    updateSpaceApi: jest.fn(),
    deleteSpaceApi: jest.fn(),
    unsubscribeSpaceApi: jest.fn(),
    pinSpaceApi: jest.fn(),
    getSpaceChildrenApi: jest.fn(),
    getSpaceTagsApi: jest.fn(),
    searchSpaceChildrenApi: jest.fn(),
    uploadFileToServerApi: jest.fn(),
    addFilesApi: jest.fn(),
    recommendUploadFoldersApi: jest.fn(),
    listMyUploadedFilesApi: jest.fn(),
    moveUploadedFileFolderApi: jest.fn(),
    getSimilarCandidatesApi: jest.fn(),
    linkAsNewVersionApi: jest.fn(),
    batchDownloadApi: jest.fn(),
    batchDeleteApi: jest.fn(),
    batchRetryApi: jest.fn(),
    getFileDownloadApi: jest.fn(),
    getFilePreviewApi: jest.fn(),
    updateFileEncoding: jest.fn(),
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
            <RecoilRoot>
                <PortalKnowledgeWorkbench />
            </RecoilRoot>
        </QueryClientProvider>,
    );
}

describe("PortalKnowledgeWorkbench", () => {
    beforeEach(() => {
        jest.clearAllMocks();
        localStorage.removeItem("knowledge-view-mode");
        mockCreateSpaceConfirmResult = undefined;
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
        jest.mocked(getSpaceTagsApi).mockResolvedValue([] as any);
        jest.mocked(getFilePreviewApi).mockResolvedValue({
            preview_url: "/preview.md",
            original_url: "/origin.md",
        } as any);
        jest.mocked(updateFileEncoding).mockResolvedValue(makeFile("201", "后端开发.md", {
            fileEncoding: "RPT-PP-00000001",
        }) as any);
        jest.mocked(getFileDownloadApi).mockResolvedValue({
            preview_url: "/preview.md",
            original_url: "/origin.md",
        } as any);
        jest.mocked(batchDownloadApi).mockResolvedValue("/download.zip");
        jest.mocked(batchDeleteApi).mockResolvedValue(undefined as any);
        jest.mocked(batchRetryApi).mockResolvedValue(undefined as any);
        jest.mocked(listKnowledgeFolders).mockResolvedValue({ items: [], total: 0 } as any);
        jest.mocked(uploadFileToServerApi).mockResolvedValue({ file_path: "/tmp/uploaded.pdf" } as any);
        jest.mocked(addFilesApi).mockResolvedValue([] as any);
        jest.mocked(recommendUploadFoldersApi).mockResolvedValue({ items: [] } as any);
        jest.mocked(listMyUploadedFilesApi).mockResolvedValue({ data: [], total: 0 } as any);
        jest.mocked(moveUploadedFileFolderApi).mockResolvedValue(makeFile("501", "测试文档.pdf") as any);
        jest.mocked(createFolderApi).mockResolvedValue(makeFile("folder-1", "上传文件夹", {
            type: FileType.FOLDER,
        }) as any);
        jest.mocked(getSimilarCandidatesApi).mockResolvedValue([] as any);
        jest.mocked(linkAsNewVersionApi).mockResolvedValue({ document_id: 1, new_version_no: 2 } as any);
        jest.mocked(submitShougangKnowledgeSpaceCreateApprovalApi).mockResolvedValue({
            decision: "pending",
            created: false,
            instance_id: 901,
            task_ids: [902],
        } as any);
        jest.mocked(getShougangFilePublishTargetSpacesApi).mockResolvedValue({
            data: [{ id: "public-target", name: "公共发布库", space_level: SpaceLevel.PUBLIC }],
            total: 1,
        } as any);
        jest.mocked(getShougangFilePublishSimilarCandidatesApi).mockResolvedValue({ data: [], total: 0 } as any);
        jest.mocked(searchShougangFilePublishDocumentsApi).mockResolvedValue({ data: [], total: 0 } as any);
        jest.mocked(submitShougangFilePublishApprovalApi).mockResolvedValue({
            decision: "pending",
            created: false,
            instance_id: 903,
            task_ids: [904],
        } as any);
        mockCheckPermission.mockResolvedValue({ allowed: true });
        const { canOpenPermissionDialog } = jest.requireMock("~/api/permission");
        canOpenPermissionDialog.mockResolvedValue(true);
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

        expect(screen.getByTestId("space-sidebar-title-icon")).toHaveAttribute(
            "src",
            "/assets/knowledge-portal/sidebar-title.png",
        );
        expect(screen.getByTestId("space-group-icon-public")).toHaveAttribute(
            "src",
            "/assets/knowledge-portal/group-public-expanded.png",
        );
        expect(screen.getByTestId("space-group-icon-department")).toHaveAttribute(
            "src",
            "/assets/knowledge-portal/group-department-expanded.png",
        );
        expect(screen.getByRole("button", { name: "收起部门知识库" })).toBeInTheDocument();
        expect(screen.getByTestId("space-group-icon-team")).toHaveAttribute(
            "src",
            "/assets/knowledge-portal/group-team-expanded.png",
        );
        expect(screen.getByTestId("space-group-icon-personal")).toHaveAttribute(
            "src",
            "/assets/knowledge-portal/group-personal-expanded.png",
        );
        await waitFor(() => {
            expect(screen.getByTestId("space-row-icon-public-1")).toHaveAttribute(
                "src",
                "/assets/knowledge-portal/knowledge-space-active.png",
            );
        });
        expect(screen.getByTestId("space-row-icon-team-1")).toHaveAttribute(
            "src",
            "/assets/knowledge-portal/knowledge-space.png",
        );

        fireEvent.click(within(publicGroup).getByRole("button", { name: "收起公共知识库" }));
        expect(screen.getByTestId("space-group-icon-public")).toHaveAttribute(
            "src",
            "/assets/knowledge-portal/group-public-collapsed.png",
        );
    });

    test("stores the Lanhu portal icons as static assets", () => {
        const assetNames = [
            "sidebar-title.png",
            "knowledge-space.png",
            "knowledge-space-active.png",
            "group-public-collapsed.png",
            "group-public-expanded.png",
            "group-department-collapsed.png",
            "group-department-expanded.png",
            "group-team-collapsed.png",
            "group-team-expanded.png",
            "group-personal-collapsed.png",
            "group-personal-expanded.png",
            "folder-collapsed.png",
            "folder-expanded.png",
            "sidebar-collapse.png",
            "sidebar-expand.png",
        ];

        assetNames.forEach((assetName) => {
            const assetPath = path.join(__dirname, "../../../../public/assets/knowledge-portal", assetName);
            expect(readFileSync(assetPath).byteLength).toBeGreaterThan(0);
        });
    });

    test("uses Lanhu icons for collapsing and restoring the knowledge sidebar", async () => {
        const publicSpace = makeSpace("public-1", "公共空间01");
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [publicSpace],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        await screen.findByTestId("space-group-public");
        expect(screen.getByTestId("space-sidebar-collapse-icon")).toHaveAttribute(
            "src",
            "/assets/knowledge-portal/sidebar-collapse.png",
        );

        fireEvent.click(screen.getByRole("button", { name: "收起知识库侧栏" }));

        expect(screen.getByTestId("space-sidebar-expand-icon")).toHaveAttribute(
            "src",
            "/assets/knowledge-portal/sidebar-expand.png",
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

    test("submits create knowledge space approval with the selected group level", async () => {
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        fireEvent.click(await screen.findByRole("button", { name: "新增团队知识库知识空间" }));
        expect(screen.getByTestId("create-space-drawer")).toHaveTextContent("approvalReason:true");
        fireEvent.click(screen.getByRole("button", { name: "提交创建" }));

        await waitFor(() => {
            expect(submitShougangKnowledgeSpaceCreateApprovalApi).toHaveBeenCalledTimes(1);
        });
        const payload = jest.mocked(submitShougangKnowledgeSpaceCreateApprovalApi).mock.calls[0][0];
        expect(payload).toEqual({
            name: "新空间",
            description: "说明",
            auth_type: VisibilityType.APPROVAL,
            is_released: false,
            space_level: SpaceLevel.TEAM,
            department_id: undefined,
            auto_tag_enabled: false,
            auto_tag_library_id: null,
            reason: "申请创建团队知识库",
        });
        expect(payload).not.toHaveProperty("user_group_id");
        expect(payload).not.toHaveProperty("business_domain_codes");
        expect(createSpaceApi).not.toHaveBeenCalled();
        expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({ message: "已提交申请" }));
        await waitFor(() => {
            expect(mockCreateSpaceConfirmResult).toEqual({ showSuccess: false });
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

    test("opens personal create drawer with success member management hidden", async () => {
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        const personalGroup = screen.getByTestId("space-group-personal");
        fireEvent.click(await within(personalGroup).findByRole("button", { name: "新建知识库" }));

        expect(screen.getByTestId("create-space-drawer")).toHaveTextContent(`initial:${SpaceLevel.PERSONAL}`);
        expect(screen.getByTestId("create-space-drawer")).toHaveTextContent("successManageMembers:false");
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

    test("disables department create action when department create permission is false", async () => {
        jest.mocked(getCreateSpaceOptionsApi).mockResolvedValue({
            canCreatePublic: true,
            canCreateDepartment: false,
            canCreateTeam: true,
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

        const departmentGroup = screen.getByTestId("space-group-department");

        await waitFor(() => {
            expect(within(departmentGroup).queryByRole("button", { name: "新建知识库" })).not.toBeInTheDocument();
        });

        const departmentCreateButton = screen.getByRole("button", { name: "新增部门知识库知识空间" });
        expect(departmentCreateButton).toBeDisabled();

        fireEvent.click(departmentCreateButton);

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

    test("hides member management action for personal spaces in portal sidebar", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.CREATOR,
            spaceLevel: SpaceLevel.PERSONAL,
        });
        mockUseKnowledgeSpaceActionPermissions.mockReturnValue({
            permissions: {
                "personal-1": ["edit_space", "manage_space_relation", "delete_space"],
            },
            loading: false,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);

        renderWorkbench();

        const personalRow = await screen.findByTestId("space-row-personal-1");
        fireEvent.click(within(personalRow).getByRole("button", { name: "更多我的技术文档操作" }));

        expect(within(personalRow).queryByRole("button", { name: "成员管理" })).not.toBeInTheDocument();
        expect(within(personalRow).getByRole("button", { name: "空间设置" })).toBeInTheDocument();
        expect(within(personalRow).getByRole("button", { name: "删除空间" })).toBeInTheDocument();
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

    test("uses the main work area as a full file list and covers it with preview until back", async () => {
        const personalSpace = makeSpace("personal-1", "信息", {
            role: SpaceRole.ADMIN,
        });
        const file = makeFile("201", "C0_2施肥对设施油桃生物学特性.pdf", {
            type: FileType.PDF,
            size: 236718,
            tags: [{ id: 1, name: "技术文档" }, { id: 2, name: "其他" }],
            fileEncoding: "SGGF-CAS-PP-2026060001",
            updatedAt: "2026-06-01T00:43:00",
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

        const workspace = await screen.findByTestId("portal-file-workspace");
        await waitFor(() => {
            expect(within(workspace).getByTestId("active-space-title")).toHaveTextContent("信息");
        });
        expect(within(workspace).getByTestId("portal-file-table")).toBeInTheDocument();
        expect(within(workspace).getByText("C0_2施肥对设施油桃生物学特性.pdf")).toBeInTheDocument();
        expect(within(workspace).getByText("SGGF-CAS-PP-2026060001")).toBeInTheDocument();
        const actions = within(workspace).getByTestId("portal-file-actions");
        expect(
            within(actions).getAllByRole("button").map((button) => button.getAttribute("aria-label")).filter(Boolean),
        ).toEqual([
            "上传",
            "上传记录",
            "网页链接",
            "在线创建文档",
            "新建文件夹",
            "筛选",
        ]);
        expect(within(workspace).queryByRole("button", { name: /新增|add|add new|com_knowledge\.add_new/i })).not.toBeInTheDocument();
        expect(within(workspace).queryByRole("button", { name: /批量操作|Batch operation|com_knowledge\.batch_operation/i })).not.toBeInTheDocument();
        expect(within(workspace).queryByRole("button", { name: /分享|share|com_knowledge\.share/i })).not.toBeInTheDocument();
        expect(screen.queryByText("请选择一个文件")).not.toBeInTheDocument();
        expect(screen.queryByTestId("portal-tool-rail")).not.toBeInTheDocument();

        fireEvent.click(within(workspace).getByRole("button", { name: "打开C0_2施肥对设施油桃生物学特性.pdf" }));

        const preview = await screen.findByTestId("portal-preview-page");
        expect(preview).toHaveTextContent("C0_2施肥对设施油桃生物学特性.pdf");
        expect(screen.queryByTestId("portal-file-table")).not.toBeInTheDocument();

        fireEvent.click(within(preview).getByRole("button", { name: "返回文件列表" }));

        const restoredWorkspace = await screen.findByTestId("portal-file-workspace");
        expect(within(restoredWorkspace).getByTestId("portal-file-table")).toBeInTheDocument();
        expect(screen.queryByTestId("portal-preview-page")).not.toBeInTheDocument();
    });

    test("opens Bisheng knowledge AI assistant with the current folder context", async () => {
        const personalSpace = makeSpace("personal-1", "信息", {
            role: SpaceRole.ADMIN,
        });
        const folder = makeFile("101", "CS11", {
            type: FileType.FOLDER,
            successFileNum: 3,
            fileNum: 3,
        });
        const rectSpy = jest.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
            x: 0,
            y: 0,
            width: 1280,
            height: 720,
            top: 0,
            left: 0,
            right: 1280,
            bottom: 720,
            toJSON: () => ({}),
        } as DOMRect);
        const originalResizeObserver = global.ResizeObserver;
        class MockResizeObserver {
            observe = jest.fn();
            disconnect = jest.fn();
        }
        (global as any).ResizeObserver = MockResizeObserver;

        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockImplementation((params: any) => Promise.resolve({
            data: params?.parent_id === "101" ? [] : [folder],
            total: params?.parent_id === "101" ? 0 : 1,
        }) as any);

        try {
            renderWorkbench();

            const workspace = await screen.findByTestId("portal-file-workspace");
            fireEvent.click(await within(workspace).findByRole("button", { name: "打开CS11" }));

            await waitFor(() => {
                expect(getSpaceChildrenApi).toHaveBeenCalledWith(expect.objectContaining({
                    space_id: "personal-1",
                    parent_id: "101",
                }));
            });

            fireEvent.click(within(workspace).getByRole("button", { name: /AI 助手|ai assistant|com_knowledge\.ai_assistant/i }));

            const panel = await screen.findByTestId("knowledge-ai-panel");
            expect(panel).toHaveTextContent("space:personal-1");
            expect(panel).toHaveTextContent("folder:101");
            expect(panel).toHaveTextContent("context:文件夹");
            expect(mockShowToast).not.toHaveBeenCalledWith(expect.objectContaining({ message: "暂未开放" }));

            fireEvent.click(within(panel).getByRole("button", { name: "关闭知识AI" }));
            await waitFor(() => {
                expect(screen.queryByTestId("knowledge-ai-panel")).not.toBeInTheDocument();
            });
        } finally {
            rectSpy.mockRestore();
            if (originalResizeObserver) {
                global.ResizeObserver = originalResizeObserver;
            } else {
                delete (global as any).ResizeObserver;
            }
        }
    });

    test("shows publish action for a successful team space file and submits approval", async () => {
        const teamSpace = makeSpace("team-1", "团队空间01", {
            role: SpaceRole.ADMIN,
            spaceLevel: SpaceLevel.TEAM,
        });
        const file = makeFile("301", "制度.pdf", {
            type: FileType.PDF,
            status: FileStatus.SUCCESS,
            spaceId: "team-1",
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [teamSpace],
            personalSpaces: [],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [file],
            total: 1,
        } as any);

        renderWorkbench();

        const fileRow = await screen.findByTestId("file-tree-row-301");
        fireEvent.click(within(fileRow).getByRole("button", { name: "发布" }));

        expect(await screen.findByText("发布文件")).toBeInTheDocument();
        await waitFor(() => {
            expect(getShougangFilePublishTargetSpacesApi).toHaveBeenCalledWith("team-1");
        });
        await waitFor(() => {
            expect(screen.getByRole("button", { name: "提交申请" })).toBeEnabled();
        });
        fireEvent.click(screen.getByRole("button", { name: "提交申请" }));

        await waitFor(() => {
            expect(submitShougangFilePublishApprovalApi).toHaveBeenCalledWith({
                source_space_id: "team-1",
                source_file_id: "301",
                target_space_id: "public-target",
                target_folder_id: null,
                target_document_id: null,
                target_file_id: null,
                reason: undefined,
            });
        });
    });

    test("shows publish action for a successful business domain space file", async () => {
        const departmentSpace = makeSpace("department-1", "业务域空间01", {
            role: SpaceRole.ADMIN,
            spaceLevel: SpaceLevel.DEPARTMENT,
        });
        const file = makeFile("302", "业务制度.pdf", {
            type: FileType.PDF,
            status: FileStatus.SUCCESS,
            spaceId: "department-1",
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [departmentSpace],
            teamSpaces: [],
            personalSpaces: [],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [file],
            total: 1,
        } as any);

        renderWorkbench();

        const fileRow = await screen.findByTestId("file-tree-row-302");
        fireEvent.click(within(fileRow).getByRole("button", { name: "发布" }));

        expect(await screen.findByText("发布文件")).toBeInTheDocument();
        await waitFor(() => {
            expect(getShougangFilePublishTargetSpacesApi).toHaveBeenCalledWith("department-1");
        });
    });

    test("hides publish action without knowledge space upload permission", async () => {
        const teamSpace = makeSpace("team-1", "团队空间01", {
            role: SpaceRole.MEMBER,
            spaceLevel: SpaceLevel.TEAM,
        });
        const file = makeFile("302", "无权限文件.pdf", {
            type: FileType.PDF,
            status: FileStatus.SUCCESS,
            spaceId: "team-1",
        });
        mockCheckPermission.mockImplementation((objectType, _objectId, _relation, permissionId) => {
            if (objectType === "knowledge_space" && permissionId === "upload_file") {
                return Promise.resolve({ allowed: false });
            }
            if (objectType === "knowledge_file" && permissionId === "upload_file") {
                return Promise.resolve({ allowed: true });
            }
            return Promise.resolve({ allowed: true });
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [teamSpace],
            personalSpaces: [],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [file],
            total: 1,
        } as any);

        renderWorkbench();

        const fileRow = await screen.findByTestId("file-tree-row-302");

        await waitFor(() => {
            expect(mockCheckPermission).toHaveBeenCalledWith(
                "knowledge_space",
                "team-1",
                "can_edit",
                "upload_file",
                expect.any(Object),
            );
        });
        expect(within(fileRow).queryByRole("button", { name: "发布" })).not.toBeInTheDocument();
    });

    test("disables publish action for non-success file when space upload permission exists", async () => {
        const teamSpace = makeSpace("team-1", "团队空间01", {
            role: SpaceRole.MEMBER,
            spaceLevel: SpaceLevel.TEAM,
        });
        const successFile = makeFile("303", "可发布.pdf", {
            type: FileType.PDF,
            status: FileStatus.SUCCESS,
            spaceId: "team-1",
        });
        const processingFile = makeFile("304", "解析中文件.pdf", {
            type: FileType.PDF,
            status: FileStatus.PROCESSING,
            spaceId: "team-1",
        });
        mockCheckPermission.mockImplementation((objectType, _objectId, _relation, permissionId) => {
            if (objectType === "knowledge_space" && permissionId === "upload_file") {
                return Promise.resolve({ allowed: true });
            }
            return Promise.resolve({ allowed: true });
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [teamSpace],
            personalSpaces: [],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [successFile, processingFile],
            total: 2,
        } as any);

        renderWorkbench();

        const successRow = await screen.findByTestId("file-tree-row-303");
        const processingRow = await screen.findByTestId("file-tree-row-304");

        await waitFor(() => {
            expect(mockCheckPermission).toHaveBeenCalledWith(
                "knowledge_space",
                "team-1",
                "can_edit",
                "upload_file",
                expect.any(Object),
            );
        });
        expect(within(successRow).getByRole("button", { name: "发布" })).toBeEnabled();
        expect(within(processingRow).getByRole("button", { name: "发布" })).toBeDisabled();

        fireEvent.click(within(processingRow).getByRole("button", { name: "发布" }));
        expect(screen.queryByText("发布文件")).not.toBeInTheDocument();
    });

    test("opens approval center and notifications from portal shell messages", async () => {
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [],
        } as any);

        renderWorkbench();

        act(() => {
            window.dispatchEvent(new MessageEvent("message", {
                data: { type: "shougang-portal:open-approval-tasks" },
            }));
        });
        expect(await screen.findByTestId("approval-center-dialog")).toHaveTextContent("审批中心:my_tasks");

        act(() => {
            window.dispatchEvent(new MessageEvent("message", {
                data: { type: "shougang-portal:open-approval-requests" },
            }));
        });
        expect(await screen.findByTestId("approval-center-dialog")).toHaveTextContent("审批中心:my_requests");

        act(() => {
            window.dispatchEvent(new MessageEvent("message", {
                data: { type: "shougang-portal:open-notifications" },
            }));
        });
        expect(await screen.findByTestId("notifications-dialog")).toBeInTheDocument();
    });

    test("uses Lanhu folder icons and keeps existing Bisheng file type icons in the portal file tree", async () => {
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
        expect(within(folderRow).getByTestId("portal-folder-icon-101")).toHaveAttribute(
            "src",
            "/assets/knowledge-portal/folder-collapsed.png",
        );
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

        expect(within(folderRow).getByTestId("portal-folder-icon-101")).toHaveAttribute(
            "src",
            "/assets/knowledge-portal/folder-expanded.png",
        );
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
        fireEvent.click(within(fileRow).getByRole("checkbox"));

        expect(getFilePreviewApi).not.toHaveBeenCalled();
        expect(screen.queryByRole("button", { name: /批量操作|Batch operation|com_knowledge\.batch_operation/i })).not.toBeInTheDocument();

        fireEvent.click(within(fileRow).getByRole("button", { name: "打开后端开发.md" }));

        await waitFor(() => {
            expect(getFilePreviewApi).toHaveBeenCalledWith("personal-1", "201");
        });
    });

    test("shows folder permission management action only when the folder is manageable", async () => {
        const teamSpace = makeSpace("team-1", "团队技术文档", {
            spaceLevel: SpaceLevel.TEAM,
            role: SpaceRole.MEMBER,
        });
        const manageableFolder = makeFile("101", "可管理目录", {
            type: FileType.FOLDER,
            successFileNum: 1,
            fileNum: 7,
        });
        const hiddenFolder = makeFile("102", "无权限目录", {
            type: FileType.FOLDER,
            successFileNum: 0,
            fileNum: 3,
        });
        mockCheckPermission.mockImplementation((objectType, objectId, relation, permissionId) => {
            if (objectType === "folder" && objectId === "101" && relation === "can_read" && permissionId === "download_folder") {
                return Promise.resolve({ allowed: true });
            }
            if (objectType === "folder" && objectId === "102" && relation === "can_read" && permissionId === "download_folder") {
                return Promise.resolve({ allowed: true });
            }
            return Promise.resolve({ allowed: false });
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [teamSpace],
            personalSpaces: [],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [manageableFolder, hiddenFolder],
            total: 2,
        } as any);
        const { canOpenPermissionDialog } = jest.requireMock("~/api/permission");
        canOpenPermissionDialog.mockImplementation((resourceType: string, resourceId: string) => (
            Promise.resolve(resourceType === "folder" && resourceId === "101")
        ));

        renderWorkbench();

        const manageableRow = await screen.findByTestId("file-tree-row-101");
        const hiddenRow = screen.getByTestId("file-tree-row-102");

        await waitFor(() => {
            expect(within(manageableRow).getByRole("button", { name: "更多可管理目录操作" })).toBeInTheDocument();
        });
        expect(within(hiddenRow).queryByRole("button", { name: "更多无权限目录操作" })).not.toBeInTheDocument();

        fireEvent.click(within(manageableRow).getByRole("button", { name: "权限管理" }));

        expect(screen.getByTestId("space-share-dialog")).toHaveTextContent("成员管理:folder:可管理目录");
    });

    test("hides file and folder permission management actions for personal spaces", async () => {
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
            spaceLevel: undefined,
            space_level: SpaceLevel.PERSONAL,
        });
        const folder = makeFile("101", "个人目录", {
            type: FileType.FOLDER,
            successFileNum: 1,
            fileNum: 2,
        });
        const file = makeFile("201", "个人文档.md");
        const { canOpenPermissionDialog } = jest.requireMock("~/api/permission");
        canOpenPermissionDialog.mockResolvedValue(true);
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [folder, file],
            total: 2,
        } as any);

        renderWorkbench();

        const folderRow = await screen.findByTestId("file-tree-row-101");
        const fileRow = await screen.findByTestId("file-tree-row-201");

        await act(async () => undefined);
        fireEvent.mouseEnter(folderRow);
        fireEvent.mouseEnter(fileRow);
        await waitFor(() => {
            expect(screen.getAllByRole("button", { name: /下载|download|com_knowledge\.download/i }).length).toBeGreaterThan(0);
        });

        expect(canOpenPermissionDialog).not.toHaveBeenCalled();
        expect(within(folderRow).queryByRole("button", { name: "权限管理" })).not.toBeInTheDocument();
        expect(within(fileRow).queryByRole("button", { name: "权限管理" })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "权限管理" })).not.toBeInTheDocument();

        fireEvent.click(within(fileRow).getByRole("button", { name: "打开个人文档.md" }));
        const actions = await screen.findByTestId("portal-document-actions");
        expect(within(actions).queryByRole("button", { name: "权限管理" })).not.toBeInTheDocument();

        const rail = await screen.findByTestId("portal-tool-rail");
        expect(within(rail).queryByRole("button", { name: "权限" })).not.toBeInTheDocument();
    });

    test("hides card view file and folder permission management actions for personal spaces", async () => {
        class MockResizeObserver {
            observe = jest.fn();
            unobserve = jest.fn();
            disconnect = jest.fn();
        }
        Object.defineProperty(window, "ResizeObserver", {
            configurable: true,
            writable: true,
            value: MockResizeObserver,
        });
        Object.defineProperty(global, "ResizeObserver", {
            configurable: true,
            writable: true,
            value: MockResizeObserver,
        });
        localStorage.setItem("knowledge-view-mode", "card");
        const personalSpace = makeSpace("personal-1", "我的技术文档", {
            role: SpaceRole.ADMIN,
            spaceLevel: undefined,
            space_level: SpaceLevel.PERSONAL,
        });
        const folder = makeFile("101", "个人目录", {
            type: FileType.FOLDER,
            successFileNum: 1,
            fileNum: 2,
        });
        const file = makeFile("201", "个人文档.md");
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [folder, file],
            total: 2,
        } as any);

        renderWorkbench();

        const folderName = await screen.findByText("个人目录");
        const fileName = await screen.findByText("个人文档.md");
        const folderCard = folderName.closest(".group");
        const fileCard = fileName.closest(".group");
        expect(folderCard).not.toBeNull();
        expect(fileCard).not.toBeNull();

        fireEvent.mouseEnter(folderCard!);
        fireEvent.mouseEnter(fileCard!);

        await waitFor(() => {
            expect(screen.getAllByRole("button", { name: /下载|download|com_knowledge\.download/i }).length).toBeGreaterThan(0);
        });

        expect(screen.queryByRole("button", { name: "权限管理" })).not.toBeInTheDocument();
    });

    test("renders document preview actions with the share action hidden", async () => {
        const teamSpace = makeSpace("team-1", "我的技术文档", {
            spaceLevel: SpaceLevel.TEAM,
            role: SpaceRole.ADMIN,
        });
        const file = makeFile("201", "后端开发.md", {
            spaceId: "team-1",
            fileEncoding: "RPT-PP-00000001",
            size: 2048,
            updatedAt: "2026-05-20T12:30:00",
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [teamSpace],
            personalSpaces: [],
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
            "编辑标签",
            "下载",
            "权限管理",
            "复制",
        ]);
        expect(within(actions).queryByRole("button", { name: "AI 对话" })).not.toBeInTheDocument();

        fireEvent.click(within(actions).getByRole("button", { name: "编辑标签" }));
        expect(screen.getByTestId("edit-tags-modal")).toBeInTheDocument();

        expect(within(actions).queryByRole("button", { name: "分享" })).not.toBeInTheDocument();

        fireEvent.click(within(actions).getByRole("button", { name: "下载" }));
        await waitFor(() => {
            expect(getFileDownloadApi).toHaveBeenCalledWith("team-1", "201");
        });

        fireEvent.click(within(actions).getByRole("button", { name: "权限管理" }));
        expect(screen.getByTestId("space-share-dialog")).toHaveTextContent("成员管理:knowledge_file:后端开发.md");
    });

    test("opens document AI from the right rail as a drawer and hides left panes until closed", async () => {
        const teamSpace = makeSpace("team-1", "我的技术文档", {
            spaceLevel: SpaceLevel.TEAM,
            role: SpaceRole.ADMIN,
        });
        const file = makeFile("201", "后端开发.md", {
            spaceId: "team-1",
            fileEncoding: "RPT-PP-00000001",
            size: 2048,
            updatedAt: "2026-05-20T12:30:00",
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [teamSpace],
            personalSpaces: [],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [file],
            total: 1,
        } as any);

        renderWorkbench();

        const fileRow = await screen.findByTestId("file-tree-row-201");
        fireEvent.click(within(fileRow).getByRole("button", { name: "打开后端开发.md" }));

        const rail = await screen.findByTestId("portal-tool-rail");
        fireEvent.click(within(rail).getByRole("button", { name: "AI 对话" }));

        const aiDrawer = await screen.findByTestId("portal-ai-drawer");
        expect(aiDrawer).toHaveTextContent("AI对话");
        expect(aiDrawer).not.toHaveTextContent("后端开发.md");
        expect(aiDrawer).not.toHaveTextContent("全部知识库/团队知识库/我的技术文档/后端开发.md");
        expect(aiDrawer).not.toHaveTextContent("2.0 KB");
        expect(within(aiDrawer).getByTestId("ai-assistant-panel")).toHaveTextContent("文件AI:team-1:201");
        expect(within(aiDrawer).getByTestId("ai-assistant-panel")).toHaveTextContent("门户抽屉模式:true");
        expect(screen.queryByTestId("portal-info-drawer")).not.toBeInTheDocument();
        expect(screen.queryByTestId("active-space-title")).not.toBeInTheDocument();
        expect(screen.queryByTestId("space-group-team")).not.toBeInTheDocument();

        fireEvent.click(within(aiDrawer).getByRole("button", { name: "关闭AI抽屉" }));

        expect(screen.queryByTestId("portal-ai-drawer")).not.toBeInTheDocument();
        expect(await screen.findByTestId("portal-preview-page")).toHaveTextContent("后端开发.md");
        expect(screen.queryByTestId("active-space-title")).not.toBeInTheDocument();
        expect(screen.queryByTestId("portal-file-table")).not.toBeInTheDocument();
        expect(screen.getByTestId("space-group-team")).toBeInTheDocument();
    });

    test("keeps the document preview share entry commented out", () => {
        const previewSource = readFileSync(path.join(__dirname, "components/DocumentPreview.tsx"), "utf8");
        const previewWorkspaceSource = readFileSync(path.join(__dirname, "components/PortalPreviewWorkspace.tsx"), "utf8");

        expect(previewSource).toContain('title="分享"');
        expect(stripComments(previewSource)).not.toContain('title="分享"');
        expect(previewWorkspaceSource).toContain('onOpenShare={() => setActivePanel("share")}');
        expect(stripComments(previewWorkspaceSource)).not.toContain('onOpenShare={() => setActivePanel("share")}');
    });

    test("hides document preview permission action without file management permission", async () => {
        const teamSpace = makeSpace("team-1", "我的技术文档", {
            spaceLevel: SpaceLevel.TEAM,
            role: SpaceRole.MEMBER,
        });
        const file = makeFile("201", "后端开发.md", {
            spaceId: "team-1",
            fileEncoding: "RPT-PP-00000001",
        });
        const { canOpenPermissionDialog } = jest.requireMock("~/api/permission");
        canOpenPermissionDialog.mockResolvedValue(false);
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [teamSpace],
            personalSpaces: [],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [file],
            total: 1,
        } as any);

        renderWorkbench();

        const fileRow = await screen.findByTestId("file-tree-row-201");
        fireEvent.click(within(fileRow).getByRole("button", { name: "打开后端开发.md" }));

        const actions = await screen.findByTestId("portal-document-actions");
        await waitFor(() => {
            expect(within(actions).queryByRole("button", { name: "权限管理" })).not.toBeInTheDocument();
        });
        expect(screen.queryByTestId("space-share-dialog")).not.toBeInTheDocument();
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
            "AI 对话",
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

    test("shows drawer tabs with screenshot-aligned detail fields", async () => {
        const teamSpace = makeSpace("team-1", "我的技术文档", {
            spaceLevel: SpaceLevel.TEAM,
            role: SpaceRole.ADMIN,
        });
        const file = makeFile("201", "后端开发.md", {
            spaceId: "team-1",
            createdAt: "2025-12-16T16:11:12",
            fileEncoding: "202512160001",
            fileSource: "channel",
            tags: [{ id: 1, name: "数据库优化" }, { id: 2, name: "性能提升" }],
            size: 2.3 * 1024 * 1024,
            updatedAt: "2025-12-16T16:11:12",
            user_name: "陈亮",
            version_no: 1,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [teamSpace],
            personalSpaces: [],
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
        expect(within(drawer).getByRole("tablist", { name: "文件详情" })).toBeInTheDocument();
        expect(within(drawer).getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
            "属性",
            "时间",
            "来源",
            "使用",
            "权限",
        ]);
        expect(within(drawer).getByRole("tab", { name: "属性" })).toHaveAttribute("aria-selected", "true");
        expect(within(drawer).getByText("文件名")).toBeInTheDocument();
        expect(within(drawer).getByText("后端开发")).toBeInTheDocument();
        expect(within(drawer).queryByText("后端开发.md")).not.toBeInTheDocument();
        expect(within(drawer).getByText("202512160001")).toBeInTheDocument();
        expect(within(drawer).getByText("此处为中文说明占位")).toBeInTheDocument();
        expect(within(drawer).getByText("文档")).toBeInTheDocument();
        expect(within(drawer).getByText("2.3 MB")).toBeInTheDocument();
        expect(within(drawer).getByText("md")).toBeInTheDocument();
        expect(within(drawer).getByText("数据库优化")).toBeInTheDocument();
        expect(within(drawer).getByText("性能提升")).toBeInTheDocument();
        expect(within(drawer).getByText("1.1.0")).toBeInTheDocument();

        fireEvent.click(within(rail).getByRole("button", { name: "侧边栏展开和关闭" }));
        expect(screen.queryByTestId("portal-info-drawer")).not.toBeInTheDocument();

        fireEvent.click(within(rail).getByRole("button", { name: "时间" }));
        expect(screen.getByRole("tab", { name: "时间" })).toHaveAttribute("aria-selected", "true");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("创建时间");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("2025-12-16 16:11:12");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("最后修改时间");
        expect(screen.getByTestId("portal-info-drawer")).not.toHaveTextContent("解析状态");

        fireEvent.click(screen.getByRole("tab", { name: "来源" }));
        expect(screen.getByRole("tab", { name: "来源" })).toHaveAttribute("aria-selected", "true");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("创建人");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("最后修改人");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("陈亮");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("部门");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("产品研发中心-数智组");
        expect(screen.getByTestId("portal-info-drawer")).not.toHaveTextContent("知识库");
        expect(screen.getByTestId("portal-info-drawer")).not.toHaveTextContent("路径");

        fireEvent.click(within(rail).getByRole("button", { name: "使用" }));
        expect(screen.getByRole("tab", { name: "使用" })).toHaveAttribute("aria-selected", "true");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("下载次数");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("652");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("浏览次数");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("1216");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("分享次数");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("1000");

        fireEvent.click(within(rail).getByRole("button", { name: "权限" }));
        expect(screen.getByRole("tab", { name: "权限" })).toHaveAttribute("aria-selected", "true");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("当前用户角色");
        expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent("admin");
        expect(screen.queryByTestId("space-share-dialog")).not.toBeInTheDocument();
    });

    test("edits the selected file encoding from the portal property drawer when file edit permission exists", async () => {
        const teamSpace = makeSpace("team-1", "我的技术文档", {
            spaceLevel: SpaceLevel.TEAM,
            role: SpaceRole.MEMBER,
        });
        const file = makeFile("201", "后端开发.md", {
            spaceId: "team-1",
            fileEncoding: "RPT-PP-00000001",
        });
        const nextEncoding = "SGGF-STD-PP-20260500000005";
        mockCheckPermission.mockResolvedValue({ allowed: true });
        jest.mocked(updateFileEncoding).mockResolvedValue({
            ...file,
            fileEncoding: nextEncoding,
        } as any);
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [teamSpace],
            personalSpaces: [],
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

        const editButton = await within(drawer).findByRole("button", { name: "编辑文件编码" });
        fireEvent.click(editButton);

        fireEvent.change(screen.getByDisplayValue("RPT-PP-00000001"), {
            target: { value: nextEncoding },
        });
        fireEvent.click(screen.getByRole("button", { name: /保存|Save|com_knowledge\.save/ }));

        await waitFor(() => {
            expect(updateFileEncoding).toHaveBeenCalledWith("team-1", "201", nextEncoding);
        });
        await waitFor(() => {
            expect(screen.getByTestId("portal-info-drawer")).toHaveTextContent(nextEncoding);
        });
        expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({
            message: "编码更新成功",
        }));
    });

    test("keeps the portal property drawer file encoding read-only without file edit permission", async () => {
        const teamSpace = makeSpace("team-1", "我的技术文档", {
            spaceLevel: SpaceLevel.TEAM,
            role: SpaceRole.MEMBER,
        });
        const file = makeFile("201", "后端开发.md", {
            spaceId: "team-1",
            fileEncoding: "RPT-PP-00000001",
        });
        mockCheckPermission.mockImplementation((_objectType, _objectId, _relation, permissionId) => (
            Promise.resolve({ allowed: permissionId !== "rename_file" })
        ));
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [teamSpace],
            personalSpaces: [],
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

        await waitFor(() => {
            expect(mockCheckPermission).toHaveBeenCalledWith(
                "knowledge_file",
                "201",
                "can_edit",
                "rename_file",
                expect.any(Object),
            );
        });
        expect(within(drawer).getByText("RPT-PP-00000001")).toBeInTheDocument();
        expect(within(drawer).queryByRole("button", { name: "编辑文件编码" })).not.toBeInTheDocument();
        expect(updateFileEncoding).not.toHaveBeenCalled();
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

    test("sizes the knowledge space sidebar and file pane to the reference layout ratio", () => {
        const css = readFileSync(path.join(__dirname, "PortalKnowledgeWorkbench.module.css"), "utf8");
        const sidebarRule = css.match(/\.spaceSidebar\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";
        const filePaneRule = css.match(/\.filePane\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";
        const collapsedRule = css.match(/\.spaceSidebar\.spaceSidebarCollapsed\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";

        expect(sidebarRule).toMatch(/width\s*:\s*216px/);
        expect(sidebarRule).toMatch(/min-width\s*:\s*216px/);
        expect(filePaneRule).toMatch(/width\s*:\s*360px/);
        expect(filePaneRule).toMatch(/min-width\s*:\s*360px/);
        expect(collapsedRule).toMatch(/width\s*:\s*72px/);
    });

    test("keeps the knowledge sidebar content compact and aligned left", () => {
        const css = readFileSync(path.join(__dirname, "PortalKnowledgeWorkbench.module.css"), "utf8");
        const spaceHeaderRule = css.match(/\.spaceHeader\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";
        const spaceHeaderIconRule = css.match(/\.spaceHeaderIcon\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";
        const groupRowRule = css.match(/\.groupRow\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";
        const groupIconRule = css.match(/\.groupIcon\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";
        const groupLabelRule = css.match(/\.groupToggleButton strong\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";
        const spaceSelectRule = css.match(/\.spaceSelectButton\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";
        const createSpaceRule = css.match(/\.createSpaceRow\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";
        const spaceNameRule = css.match(/\.spaceName\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";

        expect(spaceHeaderRule).toMatch(/height\s*:\s*46px/);
        expect(spaceHeaderRule).toMatch(/padding\s*:\s*0 10px/);
        expect(spaceHeaderRule).toMatch(/font-size\s*:\s*15px/);
        expect(spaceHeaderIconRule).toMatch(/width\s*:\s*24px/);
        expect(spaceHeaderIconRule).toMatch(/height\s*:\s*24px/);
        expect(groupRowRule).toMatch(/padding\s*:\s*0 10px 0 32px/);
        expect(groupIconRule).toMatch(/width\s*:\s*14px/);
        expect(groupIconRule).toMatch(/height\s*:\s*14px/);
        expect(groupLabelRule).toMatch(/font-size\s*:\s*12\.5px/);
        expect(spaceSelectRule).toMatch(/padding\s*:\s*0 0 0 42px/);
        expect(createSpaceRule).toMatch(/padding\s*:\s*0 10px 0 42px/);
        expect(spaceNameRule).toMatch(/font-size\s*:\s*12\.5px/);
    });

    test("keeps upload review table inside a wide dialog instead of overflowing the modal", () => {
        const css = readFileSync(path.join(__dirname, "PortalKnowledgeWorkbench.module.css"), "utf8");
        const reviewContentRule = css.match(/\.uploadReviewContent\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";
        const reviewInnerRule = css.match(/\.uploadReviewInner\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";
        const reviewTableRule = css.match(/\.uploadReviewTable\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";

        expect(reviewContentRule).toMatch(/max-width\s*:\s*min\(1280px,\s*calc\(100vw - 96px\)\)\s*!important/);
        expect(reviewContentRule).toMatch(/overflow\s*:\s*hidden/);
        expect(reviewInnerRule).toMatch(/max-width\s*:\s*100%/);
        expect(reviewInnerRule).toMatch(/overflow\s*:\s*hidden/);
        expect(reviewTableRule).toMatch(/width\s*:\s*100%/);
        expect(reviewTableRule).toMatch(/overflow\s*:\s*auto/);
    });

    test("uses a right-side AI drawer sized to the reference layout", () => {
        const css = readFileSync(path.join(__dirname, "PortalKnowledgeWorkbench.module.css"), "utf8");
        const aiDrawerRule = css.match(/\.aiDrawer\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";
        const aiDrawerHeaderRule = css.match(/\.aiDrawerHeader\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";
        const aiDrawerBodyRule = css.match(/\.aiDrawerBody\s*\{(?<body>[^}]*)\}/)?.groups?.body ?? "";

        expect(aiDrawerRule).toMatch(/width\s*:\s*560px/);
        expect(aiDrawerRule).toMatch(/box-shadow\s*:\s*-6px 0 10px rgba\(0,\s*0,\s*0,\s*0\.1\)/);
        expect(aiDrawerRule).toMatch(/border-left\s*:\s*1px solid #dfe7f2/);
        expect(aiDrawerHeaderRule).toMatch(/height\s*:\s*46px/);
        expect(aiDrawerHeaderRule).toMatch(/padding\s*:\s*12px 16px 0/);
        expect(aiDrawerHeaderRule).toMatch(/border-bottom\s*:\s*1px solid #edf1f7/);
        expect(aiDrawerBodyRule).toMatch(/display\s*:\s*flex/);
        expect(css).toContain("portalAiPanel");
        expect(css).toContain("portalAiInput");
    });

    test("keeps the portal workbench entrypoint below the maintenance size limit", () => {
        const source = readFileSync(path.join(__dirname, "PortalKnowledgeWorkbench.tsx"), "utf8");
        const nonEmptyLineCount = source
            .split("\n")
            .filter((line) => line.trim().length > 0).length;

        expect(nonEmptyLineCount).toBeLessThanOrEqual(1400);
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
            "上传记录",
            "网页链接",
            "在线创建文档",
            "新建文件夹",
            "筛选",
        ]);
    });

    test("opens upload dialog from portal upload action and shows selected files with optional file category", async () => {
        const personalSpace = makeSpace("personal-1", "设备部", {
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

        fireEvent.click(await screen.findByRole("button", { name: "上传" }));

        const dialog = await screen.findByTestId("portal-upload-dialog");
        expect(within(dialog).getByText("上传文件")).toBeInTheDocument();
        expect(within(dialog).getByLabelText("文件分类")).toHaveDisplayValue("请选择文件分类");
        expect(within(dialog).queryByText("*")).not.toBeInTheDocument();
        expect(within(dialog).getByRole("option", { name: "报告" })).toHaveValue("RPT");
        expect(within(dialog).getByLabelText("目标知识库")).toHaveValue("设备部");
        expect(within(dialog).getByTestId("selected-upload-folder")).toHaveTextContent("未选择目录（AI推荐）");
        expect(within(dialog).getByRole("button", { name: "选择上传目录根目录" })).toBeInTheDocument();
        expect(mockHandleUploadFile).not.toHaveBeenCalled();

        const file = new File(["pdf"], "测试文档.pdf", { type: "application/pdf" });
        fireEvent.change(within(dialog).getByLabelText("选择文件"), {
            target: { files: [file] },
        });

        expect(within(dialog).getByText("已选择的文件 (1)")).toBeInTheDocument();
        expect(within(dialog).getByText("测试文档.pdf")).toBeInTheDocument();
        expect(within(dialog).getByRole("button", { name: "移除测试文档.pdf" })).toBeInTheDocument();
    });

    test("opens upload records after successful upload and supports moving uploaded file folder", async () => {
        const personalSpace = makeSpace("personal-1", "设备部", {
            role: SpaceRole.ADMIN,
        });
        const registeredFile = makeFile("501", "测试文档.pdf", {
            type: FileType.PDF,
            status: FileStatus.PROCESSING,
        });
        const uploadedRecord = {
            ...registeredFile,
            spaceName: "设备部",
            spaceLevel: SpaceLevel.PERSONAL,
            folderPathName: "根目录",
            fileEncoding: "SGGF-STD-EM-20260600000001",
            tags: [{ id: 1, name: "能源" }],
            summary: "AI 摘要",
        };
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({ data: [], total: 0 } as any);
        jest.mocked(uploadFileToServerApi).mockResolvedValue({ file_path: "/tmp/测试文档.pdf" } as any);
        jest.mocked(addFilesApi).mockResolvedValue([registeredFile] as any);
        jest.mocked(listMyUploadedFilesApi).mockResolvedValue({ data: [uploadedRecord], total: 1 } as any);
        jest.mocked(listKnowledgeFolders).mockImplementation(({ parent_id }: any = {}) => Promise.resolve({
            items: parent_id === 37
                ? [{ id: 38, file_name: "能源管理", file_type: 0 }]
                : [{ id: 37, file_name: "技术文档", file_type: 0 }],
            total: 1,
        } as any));
        jest.mocked(moveUploadedFileFolderApi).mockResolvedValue({
            ...registeredFile,
            parentId: "38",
            path: "/37/38",
        } as any);

        renderWorkbench();

        fireEvent.click(await screen.findByRole("button", { name: "上传" }));
        const dialog = await screen.findByTestId("portal-upload-dialog");
        const file = new File(["pdf"], "测试文档.pdf", { type: "application/pdf" });
        fireEvent.change(within(dialog).getByLabelText("选择文件"), {
            target: { files: [file] },
        });
        fireEvent.click(within(dialog).getByRole("button", { name: "上传" }));

        const drawer = await screen.findByTestId("portal-uploaded-files-drawer");
        expect(listMyUploadedFilesApi).toHaveBeenCalledWith(expect.objectContaining({ page: 1, pageSize: 20 }));
        expect(within(drawer).getByText("文件编码")).toBeInTheDocument();
        expect(within(drawer).getByText("标签")).toBeInTheDocument();
        expect(within(drawer).queryByText("AI推荐文件类型")).not.toBeInTheDocument();
        expect(within(drawer).queryByText("AI标签")).not.toBeInTheDocument();
        expect(within(drawer).getByText("测试文档.pdf")).toBeInTheDocument();
        expect(within(drawer).getByText("个人知识库:设备部")).toBeInTheDocument();
        expect(within(drawer).getByText("解析中")).toHaveClass("uploadRecordStatusInfo");
        expect(within(drawer).getByText("根目录")).toBeInTheDocument();
        expect(within(drawer).getByText("SGGF-STD-EM-20260600000001")).toBeInTheDocument();
        expect(within(drawer).getByText("能源")).toBeInTheDocument();
        expect(within(drawer).queryByText("个人知识库 / 设备部")).not.toBeInTheDocument();
        expect(within(drawer).queryByText("AI业务域")).not.toBeInTheDocument();
        expect(within(drawer).queryByText("操作")).not.toBeInTheDocument();

        fireEvent.click(within(drawer).getByRole("button", { name: "修改测试文档.pdf上传目录 当前目录：根目录" }));
        const picker = await within(drawer).findByTestId("upload-record-folder-picker");
        expect(within(picker).getByText("选择上传目录")).toBeInTheDocument();
        expect(within(picker).getByRole("button", { name: "选择测试文档.pdf目标目录根目录" })).toBeInTheDocument();
        fireEvent.click(within(picker).getByRole("button", { name: "展开测试文档.pdf目标目录技术文档" }));
        fireEvent.click(await within(picker).findByRole("button", { name: "选择测试文档.pdf目标目录能源管理" }));
        fireEvent.click(within(drawer).getByRole("button", { name: "保存测试文档.pdf目录" }));

        await waitFor(() => {
            expect(moveUploadedFileFolderApi).toHaveBeenCalledWith("personal-1", "501", "38");
        });
    });

    test("keeps the uploaded file current folder selected when editing upload records", async () => {
        const personalSpace = makeSpace("personal-1", "设备部", {
            role: SpaceRole.ADMIN,
        });
        const uploadedRecord = {
            ...makeFile("501", "嵌套目录文档.pdf", {
                type: FileType.PDF,
                status: FileStatus.SUCCESS,
                parentId: "38",
                path: "/37/38",
            }),
            spaceName: "设备部",
            folderPathName: "技术文档/能源管理",
            fileEncoding: "SGGF-STD-EM-20260600000001",
            tags: [],
        };
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({ data: [], total: 0 } as any);
        jest.mocked(listMyUploadedFilesApi).mockResolvedValue({ data: [uploadedRecord], total: 1 } as any);
        jest.mocked(listKnowledgeFolders).mockResolvedValue({
            items: [{ id: 37, file_name: "技术文档", file_type: 0 }],
            total: 1,
        } as any);

        renderWorkbench();

        fireEvent.click(await screen.findByRole("button", { name: "上传记录" }));
        const drawer = await screen.findByTestId("portal-uploaded-files-drawer");
        fireEvent.click(within(drawer).getByRole("button", { name: "修改嵌套目录文档.pdf上传目录 当前目录：技术文档/能源管理" }));

        const picker = await within(drawer).findByTestId("upload-record-folder-picker");
        expect(within(picker).getByText("已选择：技术文档/能源管理")).toBeInTheDocument();
    });

    test("edits an uploaded record encoding from the current value", async () => {
        const personalSpace = makeSpace("personal-1", "设备部", {
            role: SpaceRole.ADMIN,
        });
        const uploadedRecord = {
            ...makeFile("501", "编码文档.pdf", {
                type: FileType.PDF,
                status: FileStatus.SUCCESS,
            }),
            spaceName: "设备部",
            spaceLevel: SpaceLevel.PERSONAL,
            folderPathName: "根目录",
            fileEncoding: "SGGF-STD-EM-20260600000001",
            tags: [],
        };
        const nextEncoding = "SGGF-STD-EM-20260600000002";
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({ data: [], total: 0 } as any);
        jest.mocked(listMyUploadedFilesApi).mockResolvedValueOnce({ data: [uploadedRecord], total: 1 } as any)
            .mockResolvedValue({ data: [{ ...uploadedRecord, fileEncoding: nextEncoding }], total: 1 } as any);
        jest.mocked(updateFileEncoding).mockResolvedValue({
            ...uploadedRecord,
            fileEncoding: nextEncoding,
        } as any);

        renderWorkbench();

        fireEvent.click(await screen.findByRole("button", { name: "上传记录" }));
        const drawer = await screen.findByTestId("portal-uploaded-files-drawer");
        fireEvent.click(within(drawer).getByRole("button", {
            name: "修改编码文档.pdf文件编码 当前编码：SGGF-STD-EM-20260600000001",
        }));

        fireEvent.change(screen.getByDisplayValue("SGGF-STD-EM-20260600000001"), {
            target: { value: nextEncoding },
        });
        fireEvent.click(screen.getByRole("button", { name: /保存|Save|com_knowledge\.save/ }));

        await waitFor(() => {
            expect(updateFileEncoding).toHaveBeenCalledWith("personal-1", "501", nextEncoding);
        });
        await waitFor(() => {
            expect(within(drawer).getByText(nextEncoding)).toBeInTheDocument();
        });
    });

    test("opens an uploaded record tag editor from the current tags", async () => {
        const personalSpace = makeSpace("personal-1", "设备部", {
            role: SpaceRole.ADMIN,
        });
        const uploadedRecord = {
            ...makeFile("501", "标签文档.pdf", {
                type: FileType.PDF,
                status: FileStatus.SUCCESS,
            }),
            spaceName: "设备部",
            spaceLevel: SpaceLevel.PERSONAL,
            folderPathName: "根目录",
            fileEncoding: "SGGF-STD-EM-20260600000001",
            tags: [{ id: 1, name: "能源" }, { id: 2, name: "安全" }],
        };
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({ data: [], total: 0 } as any);
        jest.mocked(listMyUploadedFilesApi).mockResolvedValue({ data: [uploadedRecord], total: 1 } as any);

        renderWorkbench();

        fireEvent.click(await screen.findByRole("button", { name: "上传记录" }));
        const drawer = await screen.findByTestId("portal-uploaded-files-drawer");
        fireEvent.click(within(drawer).getByRole("button", {
            name: "修改标签文档.pdf标签 当前标签：能源、安全",
        }));

        const modal = await screen.findByTestId("edit-tags-modal");
        expect(within(modal).getByTestId("edit-tags-space-id")).toHaveTextContent("personal-1");
        expect(within(modal).getByTestId("edit-tags-file-id")).toHaveTextContent("501");
        expect(within(modal).getByTestId("edit-tags-initial-ids")).toHaveTextContent("1,2");

        fireEvent.click(within(modal).getByRole("button", { name: "保存标签" }));

        await waitFor(() => {
            expect(listMyUploadedFilesApi).toHaveBeenCalledTimes(2);
        });
    });

    test("paginates uploaded records instead of showing only the first page", async () => {
        const personalSpace = makeSpace("personal-1", "设备部", {
            role: SpaceRole.ADMIN,
        });
        const firstPageRecord = {
            ...makeFile("501", "第一页文档.pdf", { type: FileType.PDF }),
            spaceName: "设备部",
            folderPathName: "根目录",
            tags: [],
        };
        const secondPageRecord = {
            ...makeFile("601", "第二页文档.pdf", { type: FileType.PDF }),
            spaceName: "设备部",
            folderPathName: "根目录",
            tags: [],
        };
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({ data: [], total: 0 } as any);
        jest.mocked(listMyUploadedFilesApi).mockImplementation(async ({ page }: any = {}) => ({
            data: page === 2 ? [secondPageRecord] : [firstPageRecord],
            total: 25,
        } as any));

        renderWorkbench();

        fireEvent.click(await screen.findByRole("button", { name: "上传记录" }));
        const drawer = await screen.findByTestId("portal-uploaded-files-drawer");
        expect(within(drawer).getByText("第一页文档.pdf")).toBeInTheDocument();

        fireEvent.click(within(drawer).getByRole("button", { name: "下一页" }));

        await waitFor(() => {
            expect(listMyUploadedFilesApi).toHaveBeenCalledWith(expect.objectContaining({ page: 2, pageSize: 20 }));
        });
        expect(await within(drawer).findByText("第二页文档.pdf")).toBeInTheDocument();
    });

    test("selects a local folder in the upload dialog and keeps only root-level files", async () => {
        const personalSpace = makeSpace("personal-1", "设备部", {
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

        fireEvent.click(await screen.findByRole("button", { name: "上传" }));
        const dialog = await screen.findByTestId("portal-upload-dialog");
        const rootFile = new File(["root"], "根层文档.pdf", { type: "application/pdf" });
        const nestedFile = new File(["nested"], "子目录文档.pdf", { type: "application/pdf" });
        Object.defineProperty(rootFile, "webkitRelativePath", { value: "研发资料/根层文档.pdf" });
        Object.defineProperty(nestedFile, "webkitRelativePath", { value: "研发资料/子目录/子目录文档.pdf" });

        fireEvent.change(within(dialog).getByLabelText("选择文件夹"), {
            target: { files: [rootFile, nestedFile] },
        });

        expect(within(dialog).getByText("将创建文件夹：研发资料")).toBeInTheDocument();
        expect(within(dialog).getByText("已选择的文件 (1)")).toBeInTheDocument();
        expect(within(dialog).getByText("根层文档.pdf")).toBeInTheDocument();
        expect(within(dialog).queryByText("子目录文档.pdf")).not.toBeInTheDocument();
        expect(within(dialog).getByText("仅上传所选文件夹根目录下的支持文件，子目录文件不会上传。")).toBeInTheDocument();
    });

    test("defaults upload target to AI recommendation and supports selecting a loaded child folder", async () => {
        const personalSpace = makeSpace("personal-1", "设备部", {
            role: SpaceRole.ADMIN,
        });
        const folder = makeFile("101", "技术文档", {
            type: FileType.FOLDER,
        });
        jest.mocked(getGroupedSpacesApi).mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [],
            personalSpaces: [personalSpace],
        } as any);
        jest.mocked(getSpaceChildrenApi).mockImplementation(({ parent_id }: any) => Promise.resolve(
            parent_id === "101"
                ? { data: [], total: 0 }
                : { data: [folder], total: 1 },
        ) as any);
        jest.mocked(listKnowledgeFolders).mockImplementation(({ parent_id }: any) => Promise.resolve({
            items: parent_id === 101
                ? [{ id: 102, file_name: "子目录", file_type: 0 }]
                : [{ id: 101, file_name: "技术文档", file_type: 0 }],
            total: 1,
        }) as any);

        renderWorkbench();

        const folderRow = await screen.findByTestId("file-tree-row-101");
        fireEvent.click(within(folderRow).getByRole("button", { name: "展开技术文档" }));
        fireEvent.click(screen.getByRole("button", { name: "上传" }));

        const dialog = await screen.findByTestId("portal-upload-dialog");
        expect(within(dialog).getByTestId("selected-upload-folder")).toHaveTextContent("未选择目录（AI推荐）");

        fireEvent.click(within(dialog).getByRole("button", { name: "展开上传目录技术文档" }));
        const childButton = await within(dialog).findByRole("button", { name: "选择上传目录子目录" });
        fireEvent.click(childButton);

        expect(listKnowledgeFolders).toHaveBeenCalledWith(expect.objectContaining({
            space_id: "personal-1",
            parent_id: 101,
        }));
        expect(within(dialog).getByTestId("selected-upload-folder")).toHaveTextContent("子目录");
    });

    test("uploads selected files and opens upload records without entering review", async () => {
        const personalSpace = makeSpace("personal-1", "设备部", {
            role: SpaceRole.ADMIN,
        });
        const registeredFile = makeFile("501", "测试文档.pdf", {
            type: FileType.PDF,
            size: 2048,
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
        jest.mocked(uploadFileToServerApi).mockResolvedValue({ file_path: "/tmp/测试文档.pdf" } as any);
        jest.mocked(addFilesApi).mockResolvedValue([registeredFile] as any);

        renderWorkbench();

        fireEvent.click(await screen.findByRole("button", { name: "上传" }));
        const dialog = await screen.findByTestId("portal-upload-dialog");
        const file = new File(["pdf"], "测试文档.pdf", { type: "application/pdf" });
        fireEvent.change(within(dialog).getByLabelText("选择文件"), {
            target: { files: [file] },
        });
        fireEvent.click(within(dialog).getByRole("button", { name: "上传" }));

        await waitFor(() => {
            expect(uploadFileToServerApi).toHaveBeenCalledWith("personal-1", file);
        });
        expect(addFilesApi).toHaveBeenCalledWith("personal-1", {
            file_path: ["/tmp/测试文档.pdf"],
            parent_id: null,
        });
        expect(getSimilarCandidatesApi).not.toHaveBeenCalled();
        expect(linkAsNewVersionApi).not.toHaveBeenCalled();
        expect(screen.queryByTestId("portal-upload-review-dialog")).not.toBeInTheDocument();
        expect(await screen.findByTestId("portal-uploaded-files-drawer")).toBeInTheDocument();
    });

    test("creates a destination folder for folder upload before opening upload records", async () => {
        const personalSpace = makeSpace("personal-1", "设备部", {
            role: SpaceRole.ADMIN,
        });
        const createdFolder = makeFile("777", "研发资料", {
            type: FileType.FOLDER,
        });
        const registeredFile = makeFile("778", "根层文档.pdf", {
            type: FileType.PDF,
            parentId: "777",
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
        jest.mocked(listKnowledgeFolders).mockResolvedValue({ items: [], total: 0 } as any);
        jest.mocked(createFolderApi).mockResolvedValue(createdFolder as any);
        jest.mocked(uploadFileToServerApi).mockResolvedValue({ file_path: "/tmp/根层文档.pdf" } as any);
        jest.mocked(addFilesApi).mockResolvedValue([registeredFile] as any);

        renderWorkbench();

        fireEvent.click(await screen.findByRole("button", { name: "上传" }));
        const dialog = await screen.findByTestId("portal-upload-dialog");
        const rootFile = new File(["root"], "根层文档.pdf", { type: "application/pdf" });
        Object.defineProperty(rootFile, "webkitRelativePath", { value: "研发资料/根层文档.pdf" });

        fireEvent.change(within(dialog).getByLabelText("选择文件夹"), {
            target: { files: [rootFile] },
        });
        fireEvent.change(within(dialog).getByLabelText("文件分类"), {
            target: { value: "RPT" },
        });
        fireEvent.click(within(dialog).getByRole("button", { name: "上传" }));

        await waitFor(() => {
            expect(createFolderApi).toHaveBeenCalledWith("personal-1", {
                name: "研发资料",
                parent_id: null,
            });
        });
        expect(uploadFileToServerApi).toHaveBeenCalledWith("personal-1", rootFile, "根层文档.pdf");
        expect(addFilesApi).toHaveBeenCalledWith("personal-1", {
            file_path: ["/tmp/根层文档.pdf"],
            parent_id: 777,
            file_category_code: "RPT",
        });
        expect(getSimilarCandidatesApi).not.toHaveBeenCalled();
        expect(screen.queryByTestId("portal-upload-review-dialog")).not.toBeInTheDocument();
        expect(await screen.findByTestId("portal-uploaded-files-drawer")).toBeInTheDocument();
    });

    test("blocks folder upload when the target directory already has the same folder name", async () => {
        const personalSpace = makeSpace("personal-1", "设备部", {
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
        jest.mocked(listKnowledgeFolders).mockResolvedValue({
            items: [{ id: 900, file_name: "研发资料", file_type: 0 }],
            total: 1,
        } as any);

        renderWorkbench();

        fireEvent.click(await screen.findByRole("button", { name: "上传" }));
        const dialog = await screen.findByTestId("portal-upload-dialog");
        const rootFile = new File(["root"], "根层文档.pdf", { type: "application/pdf" });
        Object.defineProperty(rootFile, "webkitRelativePath", { value: "研发资料/根层文档.pdf" });

        fireEvent.change(within(dialog).getByLabelText("选择文件夹"), {
            target: { files: [rootFile] },
        });
        fireEvent.change(within(dialog).getByLabelText("文件分类"), {
            target: { value: "RPT" },
        });
        fireEvent.click(within(dialog).getByRole("button", { name: "上传" }));

        await waitFor(() => {
            expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({
                message: "该位置已存在同名文件夹「研发资料」",
            }));
        });
        expect(createFolderApi).not.toHaveBeenCalled();
        expect(uploadFileToServerApi).not.toHaveBeenCalled();
        expect(screen.queryByTestId("portal-upload-review-dialog")).not.toBeInTheDocument();
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

        const input = screen.getByPlaceholderText("在当前知识空间进行搜索");
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

        const input = screen.getByPlaceholderText("在当前知识空间进行搜索");
        fireEvent.change(input, { target: { value: "搜索" } });
        fireEvent.keyDown(input, { key: "Enter" });

        expect(await screen.findByText("搜索结果.md")).toBeInTheDocument();
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

        await screen.findByTestId("portal-file-workspace");
        expect(screen.queryByRole("button", { name: /批量操作|Batch operation|com_knowledge\.batch_operation/i })).not.toBeInTheDocument();

        const folderRow = await screen.findByTestId("file-tree-row-101");
        const fileRow = screen.getByTestId("file-tree-row-201");
        fireEvent.click(within(folderRow).getByRole("checkbox"));
        fireEvent.click(within(fileRow).getByRole("checkbox"));

        expect(await screen.findByRole("button", { name: /批量操作|Batch operation|com_knowledge\.batch_operation/i })).toBeEnabled();

        fireEvent.click(screen.getByRole("button", { name: /批量下载|Batch download|com_knowledge\.batch_download|^download$/i }));
        await waitFor(() => {
            expect(batchDownloadApi).toHaveBeenCalledWith("personal-1", {
                file_ids: [201],
                folder_ids: [101],
            });
        });

        fireEvent.click(screen.getByRole("button", { name: /批量重试|Batch retry|com_knowledge\.batch_retry|^retry$/i }));
        await waitFor(() => {
            expect(batchRetryApi).toHaveBeenCalledWith("personal-1", [101, 201]);
        });

        const refreshedFolderRow = await screen.findByTestId("file-tree-row-101");
        const refreshedFileRow = screen.getByTestId("file-tree-row-201");
        fireEvent.click(within(refreshedFolderRow).getByRole("checkbox"));
        fireEvent.click(within(refreshedFileRow).getByRole("checkbox"));
        fireEvent.click(screen.getByRole("button", { name: /批量删除|Batch delete|com_knowledge\.batch_delete|^delete$/i }));
        await waitFor(() => {
            expect(batchDeleteApi).toHaveBeenCalledWith("personal-1", {
                file_ids: [201],
                folder_ids: [101],
            });
        });
    });
});
