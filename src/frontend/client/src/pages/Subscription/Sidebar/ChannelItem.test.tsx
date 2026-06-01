import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChannelRole } from "~/api/channels";
import type { Channel } from "~/api/channels";
import ChannelItem from "./ChannelItem";

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => {
        const labels: Record<string, string> = {
            "com_subscription.channel_settings": "频道设置",
            "com_subscription.member_management": "成员管理",
            "com_subscription.unpin": "取消置顶",
            "com_subscription.pin_channel": "置顶频道",
            "com_subscription.prompt_tip": "提示",
            "com_subscription.confirm_unsubscribe_channel_and_subs": "取消订阅",
            "com_subscription.confirm_delete_channel_for_all": "删除频道",
            "com_subscription.confirm": "确认",
            "com_subscription.cancel": "取消",
            "com_subscription.max_10_characters": "最多10个字符",
        };
        return labels[key] ?? key;
    },
}));

jest.mock("~/Providers", () => ({
    useConfirm: () => jest.fn().mockResolvedValue(true),
    useToastContext: () => ({
        showToast: jest.fn(),
    }),
}));

jest.mock("~/components/ui/icon/ClosedIcon", () => ({
    __esModule: true,
    default: () => <span data-testid="closed-icon" />,
}));

jest.mock("~/components/icons/channels", () => ({
    ChannelPinIcon: () => <span data-testid="pin-icon" />,
}));

jest.mock("~/components/icons/SpaceNotebookIcon", () => ({
    SpaceNotebookIcon: () => <span data-testid="notebook-icon" />,
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

function renderChannelItem(
    role: Channel["role"],
    type: "created" | "subscribed" = "subscribed",
    permissionIds?: string[],
) {
    const props = {
        channel: createChannel(role, permissionIds),
        isActive: false,
        type,
        onSelect: jest.fn(),
        onUpdate: jest.fn(),
        onDelete: jest.fn(),
        onUnsubscribe: jest.fn(),
        onPin: jest.fn(),
        onManageMembers: jest.fn(),
        onChannelSettings: jest.fn(),
    };

    const view = render(<ChannelItem {...props} />);
    return { ...view, props };
}

describe("ChannelItem relation actions", () => {
    it("shows channel settings to editor without member management", async () => {
        const user = userEvent.setup();
        const { container } = renderChannelItem("editor");
        const menuTrigger = container.querySelector("button");

        expect(menuTrigger).not.toBeNull();
        await user.click(menuTrigger as HTMLButtonElement);

        expect(await screen.findByText("频道设置")).toBeInTheDocument();
        expect(screen.queryByText("成员管理")).not.toBeInTheDocument();
    });

    it("does not show channel settings to viewer", async () => {
        const user = userEvent.setup();
        const { container } = renderChannelItem("viewer");
        const menuTrigger = container.querySelector("button");

        expect(menuTrigger).not.toBeNull();
        await user.click(menuTrigger as HTMLButtonElement);

        expect(screen.queryByText("频道设置")).not.toBeInTheDocument();
        expect(screen.queryByText("成员管理")).not.toBeInTheDocument();
    });

    it("hides member management when manager model no longer grants it", async () => {
        const user = userEvent.setup();
        const { container } = renderChannelItem("manager", "subscribed", ["view_channel", "edit_channel"]);
        const menuTrigger = container.querySelector("button");

        expect(menuTrigger).not.toBeNull();
        await user.click(menuTrigger as HTMLButtonElement);

        expect(await screen.findByText("频道设置")).toBeInTheDocument();
        expect(screen.queryByText("成员管理")).not.toBeInTheDocument();
    });

    it("keeps legacy creator able to open channel settings", async () => {
        const user = userEvent.setup();
        const { container } = renderChannelItem(ChannelRole.CREATOR, "created");
        const menuTrigger = container.querySelector("button");

        expect(menuTrigger).not.toBeNull();
        await user.click(menuTrigger as HTMLButtonElement);

        expect(await screen.findByText("频道设置")).toBeInTheDocument();
    });
});
