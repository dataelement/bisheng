import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChannelRole } from "~/api/channels";
import type { Channel } from "~/api/channels";
import { ChannelActionsMenu } from "./ChannelActionsMenu";

// react-query is mocked so the component reads channel lists straight from the
// stubbed cache; queryKey[1] is "created" | "subscribed" (see component).
const mockLists: Record<string, Channel[]> = { created: [], subscribed: [] };
jest.mock("@tanstack/react-query", () => ({
    useQuery: ({ queryKey }: { queryKey: unknown[] }) => ({
        data: mockLists[queryKey[1] as string] ?? [],
    }),
}));

const mockHandleDeleteChannel = jest.fn();
const mockHandleUnsubscribeChannel = jest.fn();
jest.mock("../hooks/useChannelActions", () => ({
    useChannelActions: () => ({
        handleDeleteChannel: mockHandleDeleteChannel,
        handleUnsubscribeChannel: mockHandleUnsubscribeChannel,
    }),
}));

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => {
        const labels: Record<string, string> = {
            "com_subscription.channel_settings": "频道设置",
            "com_subscription.edit_channel": "编辑频道",
            "com_subscription.permission_management": "权限管理",
            "com_subscription.share": "分享",
            "com_subscription.source_filter": "信息源筛选",
            "com_subscription.dissolve_channel": "解散频道",
            "com_subscription.delete_channel": "删除频道",
            "com_subscription.unsubscribe": "取消订阅",
            "com_subscription.prompt_tip": "提示",
            "com_subscription.confirm_delete_channel_for_all": "删除频道",
            "com_subscription.confirm_unsubscribe_channel_and_subs": "取消订阅",
            "com_subscription.confirm": "确认",
            "com_subscription.cancel": "取消",
        };
        return labels[key] ?? key;
    },
}));

jest.mock("~/Providers", () => ({
    useConfirm: () => jest.fn().mockResolvedValue(true),
    useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock("bisheng-icons", () => ({
    Outlined: new Proxy(
        {},
        { get: () => () => <span data-testid="icon" /> },
    ),
}));

const createChannel = (role: Channel["role"], permissionIds?: string[]): Channel => ({
    id: "channel-1",
    name: "资讯频道",
    creator: "owner",
    creatorId: "1",
    subscriberCount: 3,
    articleCount: 5,
    unreadCount: 0,
    role,
    isPinned: false,
    createdAt: "2026-05-28T00:00:00Z",
    updatedAt: "2026-05-28T00:00:00Z",
    subChannels: [],
    permissionIds,
});

function renderMenu(
    list: "created" | "subscribed",
    role: Channel["role"],
    permissionIds?: string[],
) {
    const channel = createChannel(role, permissionIds);
    mockLists.created = [];
    mockLists.subscribed = [];
    mockLists[list] = [channel];
    const props = {
        channel,
        onChannelSelect: jest.fn(),
        onManageMembers: jest.fn(),
        onChannelSettings: jest.fn(),
    };
    const view = render(<ChannelActionsMenu {...props} />);
    return { ...view, props };
}

async function openMenu(container: HTMLElement) {
    const user = userEvent.setup();
    const trigger = container.querySelector("button");
    expect(trigger).not.toBeNull();
    await user.click(trigger as HTMLButtonElement);
    return user;
}

describe("ChannelActionsMenu permission gating", () => {
    beforeEach(() => {
        mockHandleDeleteChannel.mockClear();
        mockHandleUnsubscribeChannel.mockClear();
    });

    it("shows channel settings to a granted owner whose channel sits in the followed list", async () => {
        const { container } = renderMenu("subscribed", "owner", [
            "view_channel",
            "edit_channel",
            "delete_channel",
            "manage_channel_owner",
        ]);
        await openMenu(container);

        expect(await screen.findByText("频道设置")).toBeInTheDocument();
        expect(screen.getByText("权限管理")).toBeInTheDocument();
    });

    it("shows both dissolve and unsubscribe to a granted owner in the followed list", async () => {
        const { container } = renderMenu("subscribed", "owner", [
            "view_channel",
            "edit_channel",
            "delete_channel",
            "manage_channel_owner",
        ]);
        await openMenu(container);

        expect(await screen.findByText("解散频道")).toBeInTheDocument();
        expect(screen.getByText("取消订阅")).toBeInTheDocument();
    });

    it("shows channel settings to an editor (edit permission, no delete) in the followed list", async () => {
        const { container } = renderMenu("subscribed", "editor", ["view_channel", "edit_channel"]);
        await openMenu(container);

        expect(await screen.findByText("频道设置")).toBeInTheDocument();
        // Editor cannot dissolve (no delete_channel) but can leave.
        expect(screen.queryByText("解散频道")).not.toBeInTheDocument();
        expect(screen.getByText("取消订阅")).toBeInTheDocument();
    });

    it("hides channel settings from a plain subscriber (viewer)", async () => {
        const { container } = renderMenu("subscribed", "viewer", ["view_channel"]);
        await openMenu(container);

        expect(await screen.findByText("取消订阅")).toBeInTheDocument();
        expect(screen.queryByText("频道设置")).not.toBeInTheDocument();
        expect(screen.queryByText("解散频道")).not.toBeInTheDocument();
    });

    it("shows only dissolve (no unsubscribe) for the creator's own channel", async () => {
        const { container } = renderMenu("created", ChannelRole.CREATOR);
        await openMenu(container);

        expect(await screen.findByText("频道设置")).toBeInTheDocument();
        expect(screen.getByText("解散频道")).toBeInTheDocument();
        expect(screen.queryByText("取消订阅")).not.toBeInTheDocument();
    });
});
