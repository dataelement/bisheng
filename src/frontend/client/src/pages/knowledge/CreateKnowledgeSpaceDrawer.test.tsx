import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { CreateKnowledgeSpaceDrawer } from "./CreateKnowledgeSpaceDrawer";
import { getCreateSpaceOptionsApi, getKnowledgeSpaceAutoTagVisibilityApi, SpaceLevel } from "~/api/knowledge";

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
            "com_subscription.create_knowledge_space_success": "创建知识空间成功",
            "com_subscription.goto_knowledge_space": "前往知识空间",
            "com_knowledge.member_management": "成员管理",
            "com_knowledge.cancel": "取消",
            "com_knowledge.confirm_create": "确认创建",
            "com_subscription.premission_settings": "权限设置",
            "com_knowledge.publish_to_square": "发布到广场",
            "com_knowledge.publish_desc": "可在知识广场展示",
            "com_knowledge.yes": "是",
            "com_knowledge.no": "否",
            "com_knowledge.auto_tag_generation": "自动标签生成",
            "com_knowledge.auto_tag_generation_desc": "上传文件解析成功后自动生成标签",
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
    SubjectSearchDepartment: ({ value, onChange, loadDepartments }: any) => {
        const React = require("react");
        const [departments, setDepartments] = React.useState<any[]>([]);
        const [loading, setLoading] = React.useState(Boolean(loadDepartments));
        const [failed, setFailed] = React.useState(false);

        React.useEffect(() => {
            if (!loadDepartments) return;
            let active = true;
            setLoading(true);
            loadDepartments()
                .then((rows: any[]) => {
                    if (active) setDepartments(rows);
                })
                .catch(() => {
                    if (active) setFailed(true);
                })
                .finally(() => {
                    if (active) setLoading(false);
                });
            return () => {
                active = false;
            };
        }, [loadDepartments]);

        return (
            <div data-testid="department-selector">
                <span>{value?.[0]?.name ?? "未选择部门"}</span>
                {loading ? <span>加载部门中</span> : null}
                {!loading && failed ? <span>暂无部门数据</span> : null}
                {!loading && departments.map((department) => (
                    <button
                        key={department.id}
                        type="button"
                        onClick={() => onChange([{ type: "department", id: department.id, name: department.name }])}
                    >
                        选择{department.name}
                    </button>
                ))}
                {!loading && departments.length === 0 ? (
                    <button
                        type="button"
                        onClick={() => onChange([{ type: "department", id: 9, name: "炼铁部" }])}
                    >
                        选择炼铁部
                    </button>
                ) : null}
            </div>
        );
    },
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
        expect(screen.queryByRole("radio", { name: "个人知识库" })).not.toBeInTheDocument();
    });

    test("业务域知识库创建需要选择部门并提交部门", async () => {
        const onConfirm = jest.fn().mockResolvedValue({ showSuccess: false });
        jest.mocked(getCreateSpaceOptionsApi).mockResolvedValue({
            canCreatePublic: false,
            canCreateDepartment: true,
            canCreateTeam: false,
            canCreatePersonal: true,
            departments: [],
            userGroups: [],
            defaultSpaceLevel: SpaceLevel.PERSONAL,
        });

        renderDrawer({ initialSpaceLevel: SpaceLevel.DEPARTMENT, onConfirm });

        await waitFor(() => expect(getCreateSpaceOptionsApi).toHaveBeenCalled());
        expect(screen.getByRole("radio", { name: "业务域知识库" })).toHaveAttribute("aria-checked", "true");
        expect(screen.getByTestId("department-selector")).toBeInTheDocument();

        fireEvent.change(screen.getByPlaceholderText("com_subscription.enter_knowledge_space_name"), {
            target: { value: "业务域资料库" },
        });
        fireEvent.click(screen.getByRole("button", { name: "确认创建" }));

        expect(onConfirm).not.toHaveBeenCalled();

        fireEvent.click(screen.getByRole("button", { name: "选择炼铁部" }));
        fireEvent.click(screen.getByRole("button", { name: "确认创建" }));

        await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1));
        expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({
            name: "业务域资料库",
            spaceLevel: SpaceLevel.DEPARTMENT,
            departmentId: 9,
        }));
    });

    test("业务域知识库创建加载租户全部激活部门时请求参数符合后端限制", async () => {
        jest.mocked(getCreateSpaceOptionsApi).mockResolvedValue({
            canCreatePublic: false,
            canCreateDepartment: true,
            canCreateTeam: false,
            canCreatePersonal: true,
            departments: [],
            userGroups: [],
            defaultSpaceLevel: SpaceLevel.PERSONAL,
        });
        const getDepartments = jest.requireMock("~/api/knowledge").getCreateSpaceDepartmentsApi;
        getDepartments.mockImplementation(({ pageSize }: { pageSize?: number }) => {
            if ((pageSize ?? 20) > 100) {
                return Promise.reject(new Error("page_size must be less than or equal to 100"));
            }
            return Promise.resolve({
                data: [{ id: 12, dept_id: "SG-12", name: "炼钢部", parent_id: null, children: [] }],
                total: 1,
            });
        });

        renderDrawer({ initialSpaceLevel: SpaceLevel.DEPARTMENT });

        await waitFor(() => expect(screen.getByRole("button", { name: "选择炼钢部" })).toBeInTheDocument());
        expect(screen.queryByText("暂无部门数据")).not.toBeInTheDocument();
        expect(getDepartments).toHaveBeenCalledWith(expect.objectContaining({
            approvalRequest: true,
            pageSize: 100,
        }));
    });

    test("创建模式隐藏权限设置和发布到广场并提交默认值", async () => {
        const onConfirm = jest.fn().mockResolvedValue({ showSuccess: false });
        jest.mocked(getCreateSpaceOptionsApi).mockResolvedValue({
            canCreatePublic: false,
            canCreateDepartment: false,
            canCreateTeam: false,
            canCreatePersonal: true,
            departments: [],
            userGroups: [],
            defaultSpaceLevel: SpaceLevel.PERSONAL,
        });

        renderDrawer({ initialSpaceLevel: SpaceLevel.PERSONAL, onConfirm });

        await waitFor(() => expect(getCreateSpaceOptionsApi).toHaveBeenCalled());
        expect(screen.getByRole("radio", { name: "个人知识库" })).toHaveAttribute("aria-checked", "true");
        expect(screen.queryByText("权限设置")).not.toBeInTheDocument();
        expect(screen.queryByText("发布到广场")).not.toBeInTheDocument();

        fireEvent.change(screen.getByPlaceholderText("com_subscription.enter_knowledge_space_name"), {
            target: { value: "个人资料库" },
        });
        fireEvent.click(screen.getByRole("button", { name: "确认创建" }));

        await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1));
        expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({
            joinPolicy: "review",
            publishToSquare: "no",
            spaceLevel: SpaceLevel.PERSONAL,
        }));
    });

    test("创建模式隐藏权限和发布选项时始终保留自动标签生成", async () => {
        jest.mocked(getCreateSpaceOptionsApi).mockResolvedValue({
            canCreatePublic: false,
            canCreateDepartment: false,
            canCreateTeam: false,
            canCreatePersonal: true,
            departments: [],
            userGroups: [],
            defaultSpaceLevel: SpaceLevel.PERSONAL,
        });
        renderDrawer({ initialSpaceLevel: SpaceLevel.PERSONAL });

        await waitFor(() => expect(getCreateSpaceOptionsApi).toHaveBeenCalled());
        expect(screen.queryByText("权限设置")).not.toBeInTheDocument();
        expect(screen.queryByText("发布到广场")).not.toBeInTheDocument();
        expect(screen.getByText("自动标签生成")).toBeInTheDocument();
        expect(getKnowledgeSpaceAutoTagVisibilityApi).not.toHaveBeenCalled();
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

    test("业务域入口层级无创建权限时不展示业务域选择器", async () => {
        jest.mocked(getCreateSpaceOptionsApi).mockResolvedValue({
            canCreatePublic: false,
            canCreateDepartment: false,
            canCreateTeam: true,
            canCreatePersonal: true,
            departments: [],
            userGroups: [],
            defaultSpaceLevel: SpaceLevel.PERSONAL,
        });

        renderDrawer({ initialSpaceLevel: SpaceLevel.DEPARTMENT });

        await waitFor(() => expect(getCreateSpaceOptionsApi).toHaveBeenCalled());
        expect(screen.queryByText("业务域知识库")).not.toBeInTheDocument();
        expect(screen.queryByTestId("department-selector")).not.toBeInTheDocument();
        await waitFor(() => {
            expect(screen.getByRole("radio", { name: "团队知识库" })).toHaveAttribute("aria-checked", "true");
        });
    });

    test("业务域入口层级在权限加载完成前不展示业务域选择器", async () => {
        jest.mocked(getCreateSpaceOptionsApi).mockReturnValue(new Promise(() => undefined) as any);

        renderDrawer({ initialSpaceLevel: SpaceLevel.DEPARTMENT });

        await waitFor(() => expect(getCreateSpaceOptionsApi).toHaveBeenCalled());
        expect(screen.queryByTestId("department-selector")).not.toBeInTheDocument();
        expect(screen.getByRole("button", { name: "确认创建" })).toBeDisabled();
    });

    test("团队知识库创建不展示用户组和业务域类型且可直接提交", async () => {
        const onConfirm = jest.fn().mockResolvedValue({ showSuccess: false });
        jest.mocked(getCreateSpaceOptionsApi).mockResolvedValue({
            canCreatePublic: false,
            canCreateDepartment: false,
            canCreateTeam: true,
            canCreatePersonal: true,
            departments: [],
            userGroups: [],
            defaultSpaceLevel: SpaceLevel.PERSONAL,
        });

        renderDrawer({ initialSpaceLevel: SpaceLevel.TEAM, onConfirm });

        await waitFor(() => expect(getCreateSpaceOptionsApi).toHaveBeenCalled());
        expect(screen.getByRole("radio", { name: "团队知识库" })).toHaveAttribute("aria-checked", "true");
        expect(screen.queryByTestId("user-group-selector")).not.toBeInTheDocument();
        expect(screen.queryByText("业务域类型")).not.toBeInTheDocument();
        expect(screen.queryByRole("checkbox", { name: "生产 PP" })).not.toBeInTheDocument();
        expect(screen.queryByRole("checkbox", { name: "质量 QM" })).not.toBeInTheDocument();

        fireEvent.change(screen.getByPlaceholderText("com_subscription.enter_knowledge_space_name"), {
            target: { value: "团队资料库" },
        });
        fireEvent.click(screen.getByRole("button", { name: "确认创建" }));

        await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1));
        const payload = onConfirm.mock.calls[0][0];
        expect(payload).toEqual(expect.objectContaining({
            name: "团队资料库",
            spaceLevel: SpaceLevel.TEAM,
            userGroupId: undefined,
        }));
        expect(payload).not.toHaveProperty("businessDomainCodes");
    });

    test("个人知识库创建不展示业务域类型", async () => {
        jest.mocked(getCreateSpaceOptionsApi).mockResolvedValue({
            canCreatePublic: false,
            canCreateDepartment: false,
            canCreateTeam: true,
            canCreatePersonal: true,
            departments: [],
            userGroups: [],
            defaultSpaceLevel: SpaceLevel.PERSONAL,
        });

        renderDrawer({ initialSpaceLevel: SpaceLevel.PERSONAL });

        await waitFor(() => expect(getCreateSpaceOptionsApi).toHaveBeenCalled());
        expect(screen.queryByText("业务域类型")).not.toBeInTheDocument();
    });

    test("创建成功页可隐藏成员管理入口", async () => {
        const onConfirm = jest.fn().mockResolvedValue(true);
        jest.mocked(getCreateSpaceOptionsApi).mockResolvedValue({
            canCreatePublic: false,
            canCreateDepartment: false,
            canCreateTeam: false,
            canCreatePersonal: true,
            departments: [],
            userGroups: [],
            defaultSpaceLevel: SpaceLevel.PERSONAL,
        });

        renderDrawer({
            initialSpaceLevel: SpaceLevel.PERSONAL,
            onConfirm,
            showSuccessManageMembers: false,
        });

        await waitFor(() => expect(getCreateSpaceOptionsApi).toHaveBeenCalled());
        fireEvent.change(screen.getByPlaceholderText("com_subscription.enter_knowledge_space_name"), {
            target: { value: "个人资料库" },
        });
        fireEvent.click(screen.getByRole("button", { name: "确认创建" }));

        await waitFor(() => expect(screen.getByText("创建知识空间成功")).toBeInTheDocument());
        expect(screen.getByRole("button", { name: "前往知识空间" })).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "成员管理" })).not.toBeInTheDocument();
    });
});
