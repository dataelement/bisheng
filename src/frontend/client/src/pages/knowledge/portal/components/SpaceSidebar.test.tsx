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

function renderSidebar() {
    const groups: SpaceGroup[] = [
        {
            key: "personal",
            title: "个人知识库",
            level: SpaceLevel.PERSONAL,
            iconSrc: { collapsed: "", expanded: "" },
            spaces: [
                createSpace({ id: "117", name: "我的收藏", isFavorite: true }),
                createSpace({ id: "2", name: "普通库", isFavorite: false }),
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
        expandedGroups: { public: false, department: false, team: false, personal: true } as Record<SpaceGroupKey, boolean>,
        groupRefs,
        createOptionsLoading: false,
        createPermissionByLevel: { public: false, department: false, team: false, personal: false } as Record<SpaceLevel, boolean>,
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
    };
    return render(<SpaceSidebar {...props} />);
}

describe("SpaceSidebar 收藏库操作门控（portal 内嵌工作台）", () => {
    it("普通知识库菜单含 空间设置/置顶空间/删除空间", async () => {
        const user = userEvent.setup();
        renderSidebar();
        await user.click(screen.getByLabelText("更多普通库操作"));
        expect(await screen.findByText("空间设置")).toBeInTheDocument();
        expect(screen.getByText("置顶空间")).toBeInTheDocument();
        expect(screen.getByText("删除空间")).toBeInTheDocument();
    });

    it("『我的收藏』保留菜单按钮与置顶，隐藏 空间设置/删除空间", async () => {
        const user = userEvent.setup();
        renderSidebar();
        const trigger = screen.getByLabelText("更多我的收藏操作");
        expect(trigger).toBeInTheDocument();
        await user.click(trigger);
        expect(await screen.findByText("置顶空间")).toBeInTheDocument();
        expect(screen.queryByText("空间设置")).not.toBeInTheDocument();
        expect(screen.queryByText("删除空间")).not.toBeInTheDocument();
    });
});
