import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { MutableRefObject } from "react";
import { KnowledgeSpace, SpaceLevel, SpaceRole } from "~/api/knowledge";
import type { SpaceGroup, SpaceGroupKey } from "../types";
import { SpaceSidebar } from "./SpaceSidebar";

const createSpace = (overrides: Partial<KnowledgeSpace> = {}): KnowledgeSpace =>
    ({
        id: "1",
        name: "普通库",
        visibility: "private",
        creator: "admin",
        creatorId: "1",
        memberCount: 1,
        fileCount: 0,
        totalFileCount: 0,
        role: SpaceRole.CREATOR,
        isPinned: false,
        createdAt: "2026-06-01T00:00:00Z",
        updatedAt: "2026-06-01T00:00:00Z",
        tags: [],
        isReleased: false,
        spaceLevel: SpaceLevel.PERSONAL,
        isFavorite: false,
        ...overrides,
    }) as KnowledgeSpace;

function renderSidebar(extraGroups: SpaceGroup[] = [], options: { isAdminUser?: boolean } = {}) {
    const groups: SpaceGroup[] = [
        ...extraGroups,
        {
            key: "personal",
            title: "个人知识库",
            level: SpaceLevel.PERSONAL,
            iconSrc: { collapsed: "", expanded: "" },
            spaces: [
                createSpace({ id: "117", name: "我的收藏", isFavorite: true }),
                // Personal spaces must hide pin UI even if legacy data marks one as pinned.
                createSpace({ id: "2", name: "普通库", isFavorite: false, isPinned: true }),
            ],
        },
    ];
    const groupRefs = {
        current: { public: null, department: null, team: null, personal: null },
    } as unknown as MutableRefObject<Record<SpaceGroupKey, HTMLDivElement | null>>;

    const props = {
        groups,
        activeSpaceId: undefined,
        collapsed: false,
        expandedGroups: { public: true, department: false, team: false, personal: true } as Record<SpaceGroupKey, boolean>,
        groupRefs,
        createOptionsLoading: false,
        createPermissionByLevel: { public: false, department: false, team: false, personal: false } as Record<SpaceLevel, boolean>,
        isAdminUser: options.isAdminUser ?? false,
        spaceLoading: false,
        spaceMenuOpenId: null,
        // 收藏库是个人空间、用户即 creator，权限默认全开——正是 bug 场景
        getSpacePermissions: () => ({ canEditSpace: true, canDeleteSpace: true, canManageMembers: false }),
        onRestoreSidebar: jest.fn(),
        onCollapseSidebar: jest.fn(),
        onToggleGroup: jest.fn(),
        onOpenCreateSpace: jest.fn(),
        onSelectSpace: jest.fn(),
        onSpaceMenuOpenChange: jest.fn(),
        onOpenSpaceSettings: jest.fn(),
        onOpenSpaceMembers: jest.fn(),
        onPinSpace: jest.fn(),
        onDeleteSpace: jest.fn(),
        onLeaveSpace: jest.fn(),
        onGlobalSearchSelectFile: jest.fn(),
    };
    return render(<SpaceSidebar {...props} />);
}

describe("SpaceSidebar 收藏库操作门控（portal 内嵌工作台）", () => {
    it("普通个人知识库菜单不含置顶操作", async () => {
        const user = userEvent.setup();
        renderSidebar();
        await user.click(screen.getByLabelText("更多普通库操作"));
        expect(await screen.findByText("空间设置")).toBeInTheDocument();
        expect(screen.queryByText("置顶空间")).not.toBeInTheDocument();
        expect(screen.queryByText("取消置顶")).not.toBeInTheDocument();
        expect(screen.getByText("删除空间")).toBeInTheDocument();
    });

    it("『我的收藏』不显示菜单按钮", () => {
        renderSidebar();
        expect(screen.getByTestId("space-row-117")).toBeInTheDocument();
        expect(screen.queryByLabelText("更多我的收藏操作")).not.toBeInTheDocument();
    });

    it("公共知识库仍显示置顶操作", async () => {
        const user = userEvent.setup();
        renderSidebar([
            {
                key: "public",
                title: "公共知识库",
                level: SpaceLevel.PUBLIC,
                iconSrc: { collapsed: "", expanded: "" },
                spaces: [createSpace({ id: "3", name: "公共库", spaceLevel: SpaceLevel.PUBLIC })],
            },
        ]);
        await user.click(screen.getByLabelText("更多公共库操作"));
        expect(await screen.findByText("置顶空间")).toBeInTheDocument();
    });
});

describe("SpaceSidebar 置顶状态标识", () => {
    it("置顶的公共知识库在名称后显示不可独立交互的置顶标识", () => {
        renderSidebar([
            {
                key: "public",
                title: "公共知识库",
                level: SpaceLevel.PUBLIC,
                iconSrc: { collapsed: "", expanded: "" },
                spaces: [createSpace({ id: "3", name: "置顶公共库", isPinned: true, spaceLevel: SpaceLevel.PUBLIC })],
            },
        ]);

        const pinIcon = screen.getByTestId("space-pin-icon-3");
        expect(pinIcon).toHaveAttribute("aria-hidden", "true");
        expect(pinIcon).not.toHaveAttribute("role", "button");
        expect(pinIcon.previousElementSibling).toHaveTextContent("置顶公共库");
    });

    it("未置顶知识库和个人知识库不显示置顶标识", () => {
        renderSidebar([
            {
                key: "public",
                title: "公共知识库",
                level: SpaceLevel.PUBLIC,
                iconSrc: { collapsed: "", expanded: "" },
                spaces: [createSpace({ id: "3", name: "普通公共库", spaceLevel: SpaceLevel.PUBLIC })],
            },
        ]);

        expect(screen.queryByTestId("space-pin-icon-3")).not.toBeInTheDocument();
        expect(screen.queryByTestId("space-pin-icon-117")).not.toBeInTheDocument();
        expect(screen.queryByTestId("space-pin-icon-2")).not.toBeInTheDocument();
    });
});

describe("SpaceSidebar 个人知识库不能新建（去掉 + 按钮）", () => {
    it("个人知识库分组不渲染新增(+)按钮", () => {
        renderSidebar();
        expect(screen.queryByLabelText("新增个人知识库")).not.toBeInTheDocument();
    });

    it("其他分组（公共）管理员仍渲染新增(+)按钮", () => {
        const publicGroup: SpaceGroup = {
            key: "public",
            title: "公共知识库",
            level: SpaceLevel.PUBLIC,
            iconSrc: { collapsed: "", expanded: "" },
            spaces: [],
        };
        renderSidebar([publicGroup], { isAdminUser: true });
        expect(screen.getByLabelText("新增公共知识库")).toBeInTheDocument();
        expect(screen.queryByLabelText("新增个人知识库")).not.toBeInTheDocument();
    });

    it("公共/部门知识库非管理员不渲染新增(+)按钮", () => {
        const publicGroup: SpaceGroup = {
            key: "public",
            title: "公共知识库",
            level: SpaceLevel.PUBLIC,
            iconSrc: { collapsed: "", expanded: "" },
            spaces: [],
        };
        const departmentGroup: SpaceGroup = {
            key: "department",
            title: "部门知识库",
            level: SpaceLevel.DEPARTMENT,
            iconSrc: { collapsed: "", expanded: "" },
            spaces: [],
        };
        renderSidebar([publicGroup, departmentGroup], { isAdminUser: false });
        expect(screen.queryByLabelText("新增公共知识库")).not.toBeInTheDocument();
        expect(screen.queryByLabelText("新增部门知识库")).not.toBeInTheDocument();
    });
});
