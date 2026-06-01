import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { NotificationSeverity } from "~/common";
import type { Channel } from "~/api/channels";
import { SortType } from "~/api/channels";
import { useChannelActions } from "./useChannelActions";

const mockShowToast = jest.fn();
const mockUnsubscribeChannelApi = jest.fn();

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => {
        const labels: Record<string, string> = {
            "com_subscription.unsubscribe_failed_retry": "取消订阅失败，请重试",
            "com_subscription.unsubscribed": "已取消订阅",
            "com_subscription.organization_grant_unsubscribe_blocked": ORGANIZATION_GRANT_MESSAGE,
        };
        return labels[key] ?? key;
    },
}));

jest.mock("~/Providers", () => ({
    useToastContext: () => ({
        showToast: mockShowToast,
    }),
}));

jest.mock("~/api/channels", () => ({
    SortType: {
        RECENT_UPDATE: "latest_update",
        RECENT_ADDED: "latest_added",
        NAME: "channel_name",
    },
    pinChannelApi: jest.fn(),
    updateChannelApi: jest.fn(),
    deleteChannelApi: jest.fn(),
    unsubscribeChannelApi: (...args: unknown[]) => mockUnsubscribeChannelApi(...args),
}));

const ORGANIZATION_GRANT_MESSAGE = "本频道通过部门/用户组授权给你，暂无法取消订阅";

function createChannel(id = "channel-1"): Channel {
    return {
        id,
        name: "资讯频道",
        creator: "owner",
        creatorId: "1",
        subscriberCount: 3,
        articleCount: 5,
        unreadCount: 0,
        role: "viewer",
        isPinned: false,
        createdAt: "2026-05-28T00:00:00Z",
        updatedAt: "2026-05-28T00:00:00Z",
        subChannels: [],
        permissionIds: ["view_channel"],
    };
}

describe("useChannelActions unsubscribe", () => {
    let queryClient: QueryClient;

    beforeEach(() => {
        queryClient = new QueryClient({
            defaultOptions: {
                queries: { retry: false },
                mutations: { retry: false },
            },
        });
        mockShowToast.mockClear();
        mockUnsubscribeChannelApi.mockReset();
    });

    function wrapper({ children }: { children: ReactNode }) {
        return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    it("shows organization grant message and restores optimistic state when unsubscribe is blocked", async () => {
        const channel = createChannel();
        const onChannelSelect = jest.fn();
        queryClient.setQueryData(["channels", "subscribed", SortType.RECENT_UPDATE], [channel]);
        const invalidateQueriesSpy = jest.spyOn(queryClient, "invalidateQueries");
        mockUnsubscribeChannelApi.mockResolvedValue({
            status_code: 19055,
        });

        const { result } = renderHook(() => useChannelActions({
            activeChannelId: channel.id,
            createdSortBy: SortType.RECENT_UPDATE,
            subscribedSortBy: SortType.RECENT_UPDATE,
            createdChannels: [],
            subscribedChannels: [channel],
            onChannelSelect,
        }), { wrapper });

        await act(async () => {
            await result.current.handleUnsubscribeChannel(channel.id);
        });

        await waitFor(() => {
            expect(mockShowToast).toHaveBeenCalledWith({
                message: ORGANIZATION_GRANT_MESSAGE,
                severity: NotificationSeverity.ERROR,
            });
        });
        expect(mockShowToast).not.toHaveBeenCalledWith(expect.objectContaining({
            message: "已取消订阅",
        }));
        expect(queryClient.getQueryData(["channels", "subscribed", SortType.RECENT_UPDATE])).toEqual([channel]);
        expect(onChannelSelect).toHaveBeenLastCalledWith(channel);
        expect(onChannelSelect).not.toHaveBeenCalledWith(null);
        expect(mockUnsubscribeChannelApi).toHaveBeenCalledWith(channel.id);
        expect(invalidateQueriesSpy).not.toHaveBeenCalledWith({
            queryKey: ["channels", "subscribed"],
        });
    });
});
