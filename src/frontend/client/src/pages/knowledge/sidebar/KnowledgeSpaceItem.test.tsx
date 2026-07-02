import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { KnowledgeSpace, SpaceLevel, SpaceRole } from "~/api/knowledge";
import KnowledgeSpaceItem from "./KnowledgeSpaceItem";

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => {
        const labels: Record<string, string> = {
            "com_knowledge.space_settings": "空间设置",
            "com_knowledge.member_management": "成员管理",
            "com_knowledge.pin_space": "置顶空间",
            "com_knowledge.unpin": "取消置顶",
            "com_knowledge.delete_space": "删除空间",
            "com_knowledge.exit_space_short": "退出空间",
            "com_knowledge.prompt": "提示",
            "com_knowledge.confirm_operation": "确认操作",
            "com_knowledge.confirm_exit_space": "确认退出",
            "com_knowledge.delete": "删除",
            "com_knowledge.exit": "退出",
            "com_knowledge.cancel": "取消",
        };
        return labels[key] ?? key;
    },
}));

jest.mock("~/Providers", () => ({
    useConfirm: () => jest.fn().mockResolvedValue(true),
    useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock("~/hooks/queries/data-provider", () => ({
    useGetBsConfig: () => ({
        data: { knowledge_space: { tree_structured_directory_display: false } },
    }),
}));

jest.mock("react-router-dom", () => ({
    useNavigate: () => jest.fn(),
    useParams: () => ({}),
}));

jest.mock("~/components/icons/channels", () => ({
    ChannelPinIcon: () => <span data-testid="pin-icon" />,
}));

jest.mock("~/components/ui/icon/ClosedIcon", () => ({
    __esModule: true,
    default: () => <span data-testid="closed-icon" />,
}));

jest.mock("~/components/icons/SpaceNotebookIcon", () => ({
    SpaceNotebookIcon: () => <span data-testid="notebook-icon" />,
}));

jest.mock("./KnowledgeFolderTree", () => ({
    KnowledgeFolderTree: () => <div data-testid="folder-tree" />,
}));

const createSpace = (overrides: Partial<KnowledgeSpace> = {}): KnowledgeSpace =>
    ({
        id: "space-1",
        name: "普通知识库",
        visibility: "private",
        creator: "owner",
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

function renderItem(
    overrides: Partial<KnowledgeSpace> = {},
    permissions: { canEditSpace?: boolean; canDeleteSpace?: boolean; canManageMembers?: boolean } = {},
) {
    const props = {
        space: createSpace(overrides),
        isActive: false,
        type: SpaceLevel.PERSONAL,
        onSelect: jest.fn(),
        onUpdate: jest.fn(),
        onDelete: jest.fn(),
        onLeave: jest.fn(),
        onPin: jest.fn(),
        onSettings: jest.fn(),
        onManageMembers: jest.fn(),
        // 收藏库是用户个人空间，用户即 creator，权限默认全开——正是 bug 场景
        canEditSpace: true,
        canDeleteSpace: true,
        canManageMembers: false,
        ...permissions,
    };
    const view = render(<KnowledgeSpaceItem {...props} />);
    return { ...view, props };
}

describe("KnowledgeSpaceItem 收藏库操作门控", () => {
    it("普通个人空间显示操作菜单（设置/置顶/删除）", async () => {
        const user = userEvent.setup();
        const { container } = renderItem({ isFavorite: false });
        const trigger = container.querySelector("button");
        expect(trigger).not.toBeNull();
        await user.click(trigger as HTMLButtonElement);
        expect(await screen.findByText("空间设置")).toBeInTheDocument();
        expect(screen.getByText("置顶空间")).toBeInTheDocument();
        expect(screen.getByText("删除空间")).toBeInTheDocument();
    });

    it("『我的收藏』保留菜单与置顶，隐藏 空间设置/删除空间", async () => {
        const user = userEvent.setup();
        const { container } = renderItem({ isFavorite: true, name: "我的收藏" });
        const trigger = container.querySelector("button");
        expect(trigger).not.toBeNull();
        await user.click(trigger as HTMLButtonElement);
        expect(await screen.findByText("置顶空间")).toBeInTheDocument();
        expect(screen.queryByText("空间设置")).not.toBeInTheDocument();
        expect(screen.queryByText("删除空间")).not.toBeInTheDocument();
    });

    it("『我的收藏』空间名称不可双击重命名", async () => {
        const user = userEvent.setup();
        renderItem({ isFavorite: true, name: "我的收藏" });
        await user.dblClick(screen.getByText("我的收藏"));
        expect(screen.queryByRole("textbox")).toBeNull();
    });

    it("普通空间名称可双击重命名", async () => {
        const user = userEvent.setup();
        renderItem({ isFavorite: false, name: "普通知识库" });
        await user.dblClick(screen.getByText("普通知识库"));
        expect(screen.getByRole("textbox")).toBeInTheDocument();
    });
});
