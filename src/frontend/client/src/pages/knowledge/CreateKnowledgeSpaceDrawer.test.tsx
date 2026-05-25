import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { CreateKnowledgeSpaceDrawer } from "./CreateKnowledgeSpaceDrawer";
import { getCreateSpaceOptionsApi, SpaceLevel } from "~/api/knowledge";

jest.mock("~/Providers", () => ({
    useToastContext: () => ({ showToast: jest.fn() }),
    useConfirm: () => jest.fn(),
}));

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => {
        const dict: Record<string, string> = {
            "com_subscription.create_konwledge_space": "创建知识空间",
            "com_knowledge.space_level": "空间层级",
            "com_knowledge.public_spaces": "公共知识库",
            "com_knowledge.department_spaces": "业务域知识库",
            "com_knowledge.team_spaces": "团队知识库",
            "com_knowledge.personal_spaces": "个人知识库",
            "com_knowledge.cancel": "取消",
            "com_knowledge.confirm_create": "确认创建",
        };
        return dict[key] || key;
    },
}));

jest.mock("~/components/ui/Button", () => ({
    Button: ({ children, ...props }: any) => <button {...props}>{children}</button>,
}));

jest.mock("~/components/ui/Input", () => ({
    Input: (props: any) => <input {...props} />,
}));

jest.mock("~/components/ui/Label", () => ({
    Label: ({ children, ...props }: any) => <label {...props}>{children}</label>,
}));

jest.mock("~/components/ui/Sheet", () => ({
    Sheet: ({ children, open }: any) => (open ? <div>{children}</div> : null),
    SheetContent: ({ children, hideClose: _hideClose, ...props }: any) => <div {...props}>{children}</div>,
    SheetHeader: ({ children, ...props }: any) => <div {...props}>{children}</div>,
    SheetTitle: ({ children, ...props }: any) => <h2 {...props}>{children}</h2>,
}));

jest.mock("~/components/ui/Select", () => ({
    Select: ({ children }: any) => <div>{children}</div>,
    SelectContent: ({ children }: any) => <div>{children}</div>,
    SelectItem: ({ children }: any) => <div>{children}</div>,
    SelectTrigger: ({ children }: any) => <button type="button">{children}</button>,
    SelectValue: ({ placeholder }: any) => <span>{placeholder}</span>,
}));

jest.mock("~/components/ui/Tabs", () => ({
    Tabs: ({ children }: any) => <div>{children}</div>,
    TabsContent: ({ children }: any) => <div>{children}</div>,
    TabsList: ({ children }: any) => <div>{children}</div>,
    TabsTrigger: ({ children }: any) => <button type="button">{children}</button>,
}));

jest.mock("~/components/ui/Textarea", () => ({
    Textarea: (props: any) => <textarea {...props} />,
}));

jest.mock("~/components/icons/channels", () => ({
    ChannelSuccessIcon: () => <span data-testid="success-icon" />,
}));

jest.mock("~/components/permission/SubjectSearchDepartment", () => ({
    SubjectSearchDepartment: () => <div data-testid="department-selector" />,
}));

jest.mock("~/components/permission/SubjectSearchUserGroup", () => ({
    SubjectSearchUserGroup: () => <div data-testid="user-group-selector" />,
}));

jest.mock("~/api/knowledge", () => ({
    SpaceLevel: {
        PUBLIC: "public",
        DEPARTMENT: "department",
        TEAM: "team",
        PERSONAL: "personal",
    },
    VisibilityType: {
        PUBLIC: "public",
        PRIVATE: "private",
        APPROVAL: "review",
    },
    getCreateSpaceOptionsApi: jest.fn(),
    getCreateSpaceDepartmentsApi: jest.fn().mockResolvedValue({ data: [], total: 0 }),
    getCreateSpaceUserGroupsApi: jest.fn().mockResolvedValue({ data: [], total: 0 }),
    getKnowledgeSpaceAutoTagVisibilityApi: jest.fn().mockResolvedValue({ visible: false }),
    getKnowledgeSpaceTagLibrariesApi: jest.fn().mockResolvedValue({ data: [] }),
    getKnowledgeSpaceTagLibraryDetailApi: jest.fn().mockResolvedValue({ tags: [] }),
}));

function renderDrawer(props: Partial<ComponentProps<typeof CreateKnowledgeSpaceDrawer>> = {}) {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: { retry: false },
        },
    });
    return render(
        <QueryClientProvider client={queryClient}>
            <CreateKnowledgeSpaceDrawer
                open
                onOpenChange={jest.fn()}
                showApprovalReason
                {...props}
            />
        </QueryClientProvider>,
    );
}

describe("CreateKnowledgeSpaceDrawer", () => {
    beforeEach(() => {
        jest.clearAllMocks();
    });

    test("审批创建模式下按创建权限隐藏无权限空间层级", async () => {
        jest.mocked(getCreateSpaceOptionsApi).mockResolvedValue({
            canCreatePublic: false,
            canCreateDepartment: false,
            canCreateTeam: false,
            canCreatePersonal: true,
            departments: [],
            userGroups: [],
            defaultSpaceLevel: SpaceLevel.PERSONAL,
        });

        renderDrawer();

        await waitFor(() => expect(getCreateSpaceOptionsApi).toHaveBeenCalled());
        expect(screen.queryByText("公共知识库")).not.toBeInTheDocument();
        expect(screen.queryByText("业务域知识库")).not.toBeInTheDocument();
        expect(screen.queryByText("团队知识库")).not.toBeInTheDocument();
        expect(screen.getByText("个人知识库")).toBeInTheDocument();
    });

    test("入口层级有创建权限时默认选中入口层级", async () => {
        jest.mocked(getCreateSpaceOptionsApi).mockResolvedValue({
            canCreatePublic: false,
            canCreateDepartment: false,
            canCreateTeam: true,
            canCreatePersonal: true,
            departments: [],
            userGroups: [],
            defaultSpaceLevel: SpaceLevel.PERSONAL,
        });

        renderDrawer({ initialSpaceLevel: SpaceLevel.TEAM });

        await waitFor(() => expect(getCreateSpaceOptionsApi).toHaveBeenCalled());
        expect(screen.getByRole("radio", { name: "团队知识库" })).toHaveAttribute("aria-checked", "true");
        expect(screen.getByRole("radio", { name: "个人知识库" })).toHaveAttribute("aria-checked", "false");
    });

    test("入口层级无创建权限时回退到第一个有权限层级", async () => {
        jest.mocked(getCreateSpaceOptionsApi).mockResolvedValue({
            canCreatePublic: false,
            canCreateDepartment: false,
            canCreateTeam: false,
            canCreatePersonal: true,
            departments: [],
            userGroups: [],
            defaultSpaceLevel: SpaceLevel.PERSONAL,
        });

        renderDrawer({ initialSpaceLevel: SpaceLevel.TEAM });

        await waitFor(() => expect(getCreateSpaceOptionsApi).toHaveBeenCalled());
        expect(screen.queryByText("团队知识库")).not.toBeInTheDocument();
        await waitFor(() => {
            expect(screen.getByRole("radio", { name: "个人知识库" })).toHaveAttribute("aria-checked", "true");
        });
    });
});
