import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Channel, SortType, getChannelsApi } from "~/api/channels";
import { Popover, PopoverContent, PopoverTrigger } from "~/components/ui/Popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import { ChannelSquareTabs } from "../ChannelSquareTabs";
import { useChannelActions } from "../hooks/useChannelActions";

interface ChannelSwitcherProps {
    activeChannelId?: string;
    /** Current channel display name shown in the trigger. */
    channelName: string;
    onChannelSelect: (channel: Channel) => void;
    onCreateChannel?: () => void;
    onChannelSquare?: () => void;
    /** Channel info shown in a tooltip when hovering the title (PC variant only). */
    infoContent?: ReactNode;
    /** PC only: center the title on the pane's absolute midpoint (browse mode, no
     *  article open). When false, it centers between its flex neighbours instead
     *  (reading mode, where the narrowed pane needs exact-truncation). */
    absoluteCenterTitle?: boolean;
    /** "default" = PC top-title popover. "mobile" = H5 below-titlebar fixed panel + backdrop. */
    variant?: "default" | "mobile";
    /** Mobile: CSS `top` for the dropdown panel (just under the H5 title bar). */
    mobileTopOffset?: string;
    /** Optional controlled open state (callers can force-close, e.g. when search opens). */
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
}

type ChannelGroup = "created" | "subscribed";

// Serif stack for the channel-name title. Songti SC (iOS/macOS) / SimSun 宋体 (Windows) /
// Noto Serif CJK (Android & Linux), ending in the generic `serif` keyword so any device
// without a named family still falls back to its system serif rather than sans-serif.
export const SERIF_FONT_STACK =
    '"Songti SC", STSong, "SimSun", "Noto Serif CJK SC", "Noto Serif SC", "Source Han Serif SC", serif';

/**
 * Channel switcher — picks an active channel from "我创建的" / "我关注的".
 * PC variant: borderless 切换频道 button on the left + centered channel-name title;
 *   the panel is a Radix Popover under the button that slides in from the left.
 * Mobile variant: borderless 切换频道 text trigger + fixed full-width panel anchored
 *   under the H5 title bar, with an interactive pin toggle per row.
 */
export function ChannelSwitcher({
    activeChannelId,
    channelName,
    onChannelSelect,
    onCreateChannel,
    onChannelSquare,
    infoContent,
    absoluteCenterTitle = false,
    variant = "default",
    mobileTopOffset,
    open: openProp,
    onOpenChange,
}: ChannelSwitcherProps) {
    const localize = useLocalize();
    const queryClient = useQueryClient();
    const isMobile = variant === "mobile";
    const [internalOpen, setInternalOpen] = useState(false);
    const open = openProp ?? internalOpen;
    const setOpen = (next: boolean) => {
        onOpenChange?.(next);
        if (openProp === undefined) setInternalOpen(next);
    };
    const [infoOpen, setInfoOpen] = useState(false);
    const [group, setGroup] = useState<ChannelGroup>("created");
    const [createdSortBy, setCreatedSortBy] = useState<SortType>(SortType.RECENT_UPDATE);
    const [subscribedSortBy, setSubscribedSortBy] = useState<SortType>(SortType.RECENT_UPDATE);
    const listRef = useRef<HTMLDivElement>(null);

    const { data: createdChannels = [] } = useQuery({
        queryKey: ["channels", "created", createdSortBy],
        queryFn: () => getChannelsApi({ type: "created", sortBy: createdSortBy }),
        placeholderData: (prev) => prev,
    });
    const { data: subscribedChannels = [] } = useQuery({
        queryKey: ["channels", "subscribed", subscribedSortBy],
        queryFn: () => getChannelsApi({ type: "subscribed", sortBy: subscribedSortBy }),
        placeholderData: (prev) => prev,
    });

    const channels = group === "created" ? createdChannels : subscribedChannels;
    const currentSort = group === "created" ? createdSortBy : subscribedSortBy;

    const { handlePinChannel } = useChannelActions({
        activeChannelId,
        createdSortBy,
        subscribedSortBy,
        createdChannels,
        subscribedChannels,
        onChannelSelect: (c) => { if (c) onChannelSelect(c); },
    });

    // Reset the list scroll to the top whenever the group switches.
    useEffect(() => {
        listRef.current?.scrollTo({ top: 0 });
    }, [group]);

    // On open, default to the group the active channel belongs to.
    const handleOpenChange = (next: boolean) => {
        if (next) {
            if (subscribedChannels.some((c) => c.id === activeChannelId)) {
                setGroup("subscribed");
            } else if (createdChannels.some((c) => c.id === activeChannelId)) {
                setGroup("created");
            }
        } else {
            setInfoOpen(false);
        }
        setOpen(next);
    };

    const getSortText = (sortType: SortType) => {
        switch (sortType) {
            case SortType.RECENT_UPDATE: return localize("com_subscription.recently_updated");
            case SortType.RECENT_ADDED: return localize("com_subscription.recently_added");
            case SortType.NAME: return localize("com_subscription.channel_name");
        }
    };

    const toggleSort = () => {
        const sortTypes = [SortType.RECENT_UPDATE, SortType.RECENT_ADDED, SortType.NAME];
        const next = sortTypes[(sortTypes.indexOf(currentSort) + 1) % sortTypes.length];
        queryClient.removeQueries({ queryKey: ["channels", group, currentSort] });
        if (group === "created") setCreatedSortBy(next);
        else setSubscribedSortBy(next);
    };

    const handleSelect = (channel: Channel) => {
        onChannelSelect(channel);
        setOpen(false);
    };

    // Shared section header (group toggle + action icons).
    const renderSectionHeader = () => (
        <div className="flex w-full shrink-0 items-center justify-between">
            <button
                type="button"
                onClick={() => setGroup((g) => (g === "created" ? "subscribed" : "created"))}
                className="flex items-center gap-1 rounded-md p-1 text-[12px] font-medium leading-5 text-text-3 transition-colors fine-pointer:hover:bg-fill-1"
            >
                <span>
                    {group === "created"
                        ? localize("com_subscription.created_by_me")
                        : localize("com_subscription.followed_by_me")}
                </span>
                <Outlined.Exchange className="size-4" />
            </button>
            {/* Each action is a 20px hit-box wrapping a 16px icon; 12px between them.
                The + shortcut is mobile-only: PC creates from the header 创建频道 button. */}
            <div className="flex items-center gap-3">
                {isMobile && group === "created" && onCreateChannel ? (
                    <button
                        type="button"
                        onClick={() => { onCreateChannel(); setOpen(false); }}
                        aria-label={localize("com_subscription.create")}
                        title={localize("com_subscription.create")}
                        className="flex size-5 shrink-0 items-center justify-center text-text-3 transition-colors fine-pointer:hover:text-text-1"
                    >
                        <Outlined.Plus className="size-4" />
                    </button>
                ) : null}
                <button
                    type="button"
                    onClick={toggleSort}
                    aria-label={getSortText(currentSort)}
                    title={getSortText(currentSort)}
                    className="flex size-5 shrink-0 items-center justify-center text-text-3 transition-colors fine-pointer:hover:text-text-1"
                >
                    <Outlined.Sort className="size-4" />
                </button>
            </div>
        </div>
    );

    // Persistent "create channel" button shown at the bottom of the H5 panel.
    // (Plaza navigation now lives in the header 频道/广场 toggle.)
    const renderCreateChannelButton = () =>
        onCreateChannel ? (
            <button
                type="button"
                onClick={() => { onCreateChannel(); setOpen(false); }}
                className="flex w-full shrink-0 items-center justify-center gap-1 rounded-lg border border-[#E3E3E3] bg-white px-3 py-[5px] text-[14px] leading-[22px] text-text-1 transition-colors fine-pointer:hover:bg-fill-1"
            >
                <Outlined.Plus className="size-4 text-text-3" />
                {localize("com_subscription.create_channel")}
            </button>
        ) : null;

    const renderChannelList = () => (
        <div
            ref={listRef}
            className={cn(
                "scrollbar-os flex min-h-0 w-full flex-1 flex-col overflow-y-auto",
            )}
        >
            {channels.length === 0 ? (
                <div className="py-6 text-center text-sm text-text-3">{localize("com_subscription.no_data")}</div>
            ) : (
                channels.map((c) => {
                    const isActive = c.id === activeChannelId;
                    return (
                        <div
                            key={c.id}
                            className="group flex w-full shrink-0 items-center gap-1 border-b border-dashed border-border-base py-1 transition-colors last:border-b-0 fine-pointer:hover:bg-fill-1"
                        >
                            <button
                                type="button"
                                onClick={() => handleSelect(c)}
                                className="flex h-10 min-w-0 flex-1 items-center px-1 text-left outline-none"
                            >
                                <span className={cn(
                                    "max-w-full truncate py-1 text-[14px] leading-[22px] text-text-1 [font-family:-apple-system,system-ui,'PingFang_SC','Microsoft_YaHei','Noto_Sans_CJK_SC',sans-serif]",
                                    isActive ? "border-b border-[#212121] font-semibold" : "font-normal",
                                )}>
                                    {c.name}
                                </span>
                            </button>
                            {/* Pin toggle — always shown: gray when unpinned, dark gray when pinned. */}
                            <button
                                type="button"
                                aria-label={c.isPinned ? localize("com_subscription.unpin") : localize("com_subscription.pin_channel")}
                                aria-pressed={c.isPinned}
                                onClick={() => handlePinChannel(c.id, !c.isPinned, group)}
                                className="flex size-6 shrink-0 items-center justify-center rounded outline-none transition-colors fine-pointer:hover:bg-fill-3"
                            >
                                <Outlined.ToTop className={cn("size-3 transition-colors", c.isPinned ? "text-text-2" : "text-text-4")} />
                            </button>
                        </div>
                    );
                })
            )}
        </div>
    );

    if (isMobile) {
        return (
            <>
                {/* Borderless text trigger — sits left of the 仅看未读 button; the channel
                    name itself is a plain title rendered by the caller. */}
                <button
                    type="button"
                    onClick={() => handleOpenChange(!open)}
                    aria-expanded={open}
                    className="flex shrink-0 items-center gap-0.5 whitespace-nowrap py-[3px] text-sm text-text-1 outline-none"
                >
                    <span>{localize("com_subscription.switch_channel")}</span>
                    <Outlined.Down className={cn(
                        "size-4 shrink-0 text-text-3 transition-transform",
                        open && "rotate-180",
                    )} />
                </button>
                {open ? (
                    <div
                        className="fixed inset-x-0 bottom-0 z-[55] flex flex-col bg-white"
                        style={{ top: mobileTopOffset ?? "calc(env(safe-area-inset-top, 0px) + 44px)" }}
                        role="dialog"
                        aria-modal="true"
                    >
                        {/* Header + scrollable list + footer button are now distinct
                            hierarchy layers (matching the chat-history / knowledge
                            switchers) instead of flat siblings under one padded box. */}
                        <div className="shrink-0 pl-3 pr-4 pt-3">{renderSectionHeader()}</div>
                        <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-3 pt-2">
                            {renderChannelList()}
                        </div>
                        <div className="shrink-0 bg-white px-4 pt-4 pb-[calc(env(safe-area-inset-bottom,0px)+16px)]">
                            {renderCreateChannelButton()}
                        </div>
                    </div>
                ) : null}
            </>
        );
    }

    return (
        <div className="relative flex h-10 w-full min-w-0 items-center gap-6">
            {/* Borderless 切换频道 + 创建频道 group. -ml-2 cancels the buttons' own px-2
                so their labels sit optically flush with the 40px content edge. */}
            <div className="-ml-2 flex shrink-0 items-center gap-1">
                <Popover open={open} onOpenChange={handleOpenChange}>
                    <PopoverTrigger asChild>
                        <button
                            type="button"
                            aria-haspopup="menu"
                            aria-expanded={open}
                            className={cn(
                                "flex shrink-0 items-center gap-1 rounded-md px-2 py-[5px] text-sm leading-[22px] text-text-2 outline-none transition-colors",
                                open ? "bg-fill-1 text-text-1" : "fine-pointer:hover:bg-fill-1 fine-pointer:hover:text-text-1",
                            )}
                        >
                            <Outlined.ListTree className="size-4 shrink-0" />
                            <span>{localize("com_subscription.switch_channel")}</span>
                        </button>
                    </PopoverTrigger>
                    <PopoverContent
                        align="start"
                        sideOffset={8}
                        // 32px gap above the MainLayout white card's bottom edge: the card is
                        // inset 8px from the viewport (py-2), so 32 + 8 = 40 viewport padding.
                        collisionPadding={{ bottom: 40 }}
                        // Fixed height (h-, not max-h-): the panel always stretches down to the
                        // 32px bottom gap regardless of how many channels it lists.
                        // `!` overrides the base PopoverContent motion (slide-from-top + zoom)
                        // so the panel purely slides in from the left and back out to the left.
                        className="flex h-[var(--radix-popover-content-available-height)] w-[320px] flex-col gap-2 rounded-lg border-0 bg-white p-3 shadow-[0px_4px_20px_0px_rgba(23,0,176,0.1)] data-[state=open]:!zoom-in-100 data-[state=open]:!slide-in-from-left-6 data-[side=bottom]:!slide-in-from-top-0 data-[state=closed]:!zoom-out-100 data-[state=closed]:slide-out-to-left-6"
                    >
                        {renderSectionHeader()}
                        {renderChannelList()}
                    </PopoverContent>
                </Popover>
                {/* 创建频道 — PC keeps creation next to the switcher (the panel and the
                    top-right ⋯ menu deliberately do NOT carry it on PC). */}
                {onCreateChannel ? (
                    <button
                        type="button"
                        onClick={onCreateChannel}
                        className="flex shrink-0 items-center gap-1 rounded-md px-2 py-[5px] text-sm leading-[22px] text-text-2 outline-none transition-colors fine-pointer:hover:bg-fill-1 fine-pointer:hover:text-text-1"
                    >
                        <Outlined.Plus className="size-4 shrink-0" />
                        <span>{localize("com_subscription.create_channel")}</span>
                    </button>
                ) : null}
            </div>
            {/* Channel-name title. Info tooltip is scoped to the name; the name itself
                is not clickable — switching lives on the left button.
                Two centering modes (per design):
                - pane full width (no article open): ABSOLUTE center of the content pane,
                  clamped so it still cannot overlap the side groups;
                - article detail open (narrow pane): a flex sibling with 24px gaps that
                  truncates to exactly the space its neighbours leave. */}
            <div
                className={cn(
                    absoluteCenterTitle
                        ? "pointer-events-none absolute left-1/2 top-1/2 flex max-w-[clamp(96px,calc(100%-480px),600px)] -translate-x-1/2 -translate-y-1/2"
                        : "flex min-w-0 flex-1 justify-center",
                )}
            >
                <Tooltip open={Boolean(infoContent) && infoOpen && !open} onOpenChange={setInfoOpen}>
                    <TooltipTrigger asChild>
                        <span
                            className="pointer-events-auto max-w-full truncate text-[32px] font-bold leading-[40px] text-text-1"
                            style={{ fontFamily: SERIF_FONT_STACK }}
                            onMouseEnter={() => setInfoOpen(true)}
                            onMouseLeave={() => setInfoOpen(false)}
                        >
                            {channelName}
                        </span>
                    </TooltipTrigger>
                    {infoContent ? (
                        <TooltipContent noArrow side="bottom" align="center" className="rounded-lg w-[240px] max-w-md bg-white px-3 py-2 text-gray-800 shadow-popup">
                            {infoContent}
                        </TooltipContent>
                    ) : null}
                </Tooltip>
            </div>
            {absoluteCenterTitle ? <div className="min-w-0 flex-1" aria-hidden /> : null}
            {/* Invisible clone of the persistent 频道/广场 toggle (overlaid at the row's
                right edge by Subscription/index): reserves exactly its width, so the
                flex-mode title keeps a real 24px gap to it and never slides underneath. */}
            <div className="invisible shrink-0" aria-hidden>
                <ChannelSquareTabs active="channel" />
            </div>
        </div>
    );
}
