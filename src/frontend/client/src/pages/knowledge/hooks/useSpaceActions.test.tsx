import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { NotificationSeverity } from "~/common";
import type { KnowledgeSpace } from "~/api/knowledge";
import { SpaceRole, SpaceSortType, VisibilityType } from "~/api/knowledge";
import { useSpaceActions } from "./useSpaceActions";

const mockShowToast = jest.fn();
const mockUnsubscribeSpaceApi = jest.fn();

const ORGANIZATION_GRANT_MESSAGE = "本空间通过部门/用户组授权给你，暂无法退出";

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => {
        const labels: Record<string, string> = {
            "com_knowledge.exit_space_failed": "退出空间失败",
            "com_knowledge.exited_space": "已退出空间",
            "com_knowledge.organization_grant_exit_blocked": ORGANIZATION_GRANT_MESSAGE,
        };
        return labels[key] ?? key;
    },
}));

jest.mock("~/Providers", () => ({
    useToastContext: () => ({
        showToast: mockShowToast,
    }),
}));

jest.mock("~/api/knowledge", () => ({
    SpaceRole: {
        CREATOR: "creator",
        ADMIN: "admin",
        MEMBER: "member",
    },
    SpaceSortType: {
        NAME: "name",
        UPDATE_TIME: "update_time",
    },
    VisibilityType: {
        PUBLIC: "public",
        PRIVATE: "private",
        APPROVAL: "approval",
    },
    updateSpaceApi: jest.fn(),
    deleteSpaceApi: jest.fn(),
    unsubscribeSpaceApi: (...args: unknown[]) => mockUnsubscribeSpaceApi(...args),
    pinSpaceApi: jest.fn(),
}));

function createSpace(id = "space-1"): KnowledgeSpace {
    return {
        id,
        name: "知识空间",
        description: "用于回归测试",
        icon: "",
        visibility: VisibilityType.PUBLIC,
        creator: "owner",
        creatorId: "1",
        memberCount: 3,
        fileCount: 5,
        totalFileCount: 5,
        role: SpaceRole.MEMBER,
        isPinned: false,
        createdAt: "2026-05-28T00:00:00Z",
        updatedAt: "2026-05-28T00:00:00Z",
        tags: [],
        isReleased: true,
    };
}

describe("useSpaceActions leave", () => {
    let queryClient: QueryClient;

    beforeEach(() => {
        queryClient = new QueryClient({
            defaultOptions: {
                queries: { retry: false },
                mutations: { retry: false },
            },
        });
        mockShowToast.mockClear();
        mockUnsubscribeSpaceApi.mockReset();
    });

    function wrapper({ children }: { children: ReactNode }) {
        return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    it("shows organization grant message and keeps joined state when leave is blocked", async () => {
        const space = createSpace();
        const onSpaceSelect = jest.fn();
        queryClient.setQueryData(["knowledgeSpaces", "joined", SpaceSortType.UPDATE_TIME], [space]);
        const invalidateQueriesSpy = jest.spyOn(queryClient, "invalidateQueries");
        mockUnsubscribeSpaceApi.mockResolvedValue({
            status_code: 18071,
        });

        const { result } = renderHook(() => useSpaceActions({
            activeSpaceId: space.id,
            createdSortBy: SpaceSortType.UPDATE_TIME,
            joinedSortBy: SpaceSortType.UPDATE_TIME,
            departmentSortBy: SpaceSortType.UPDATE_TIME,
            createdSpaces: [],
            joinedSpaces: [space],
            departmentSpaces: [],
            onSpaceSelect,
        }), { wrapper });

        await act(async () => {
            await result.current.handleLeaveSpace(space.id);
        });

        await waitFor(() => {
            expect(mockShowToast).toHaveBeenCalledWith({
                message: ORGANIZATION_GRANT_MESSAGE,
                severity: NotificationSeverity.ERROR,
            });
        });
        expect(mockShowToast).not.toHaveBeenCalledWith(expect.objectContaining({
            message: "已退出空间",
        }));
        expect(queryClient.getQueryData(["knowledgeSpaces", "joined", SpaceSortType.UPDATE_TIME])).toEqual([space]);
        expect(onSpaceSelect).not.toHaveBeenCalledWith(null);
        expect(mockUnsubscribeSpaceApi).toHaveBeenCalledWith(space.id);
        expect(invalidateQueriesSpy).not.toHaveBeenCalledWith({
            queryKey: ["knowledgeSpaces", "joined"],
        });
    });
});
