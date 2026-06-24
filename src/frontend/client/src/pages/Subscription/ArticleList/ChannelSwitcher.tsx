import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Channel, SortType, getChannelsApi } from "~/api/channels";
import { Popover, PopoverContent, PopoverTrigger } from "~/components/ui/Popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
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
const SERIF_FONT_STACK =
    '"Songti SC", STSong, "SimSun", "Noto Serif CJK SC", "Noto Serif SC", "Source Han Serif SC", serif';

/**
 * Channel switcher — picks an active channel from "我创建的" / "我关注的".
 * PC variant: 32px title trigger + Radix Popover.
 * Mobile variant: 20px title trigger + fixed full-width panel anchored under the H5 title bar,
 *   with a dimmed backdrop tap-to-close and an interactive pin toggle per row.
 */
export function ChannelSwitcher({
    activeChannelId,
    channelName,
    onChannelSelect,
    onCreateChannel,
    onChannelSquare,
    infoContent,
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
    const titleRef = useRef<HTMLDivElement>(null);
    // Left floor for the dropdown: it stays centered on the arrow but never moves left of the
    // title's left edge (= content-area left + header padding), measured when opening.
    const [collisionLeft, setCollisionLeft] = useState(40);

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
            const left = titleRef.current?.getBoundingClientRect().left;
            if (left != null) setCollisionLeft(Math.round(left));
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
                className="flex items-center gap-1 rounded-[6px] p-1 text-[12px] font-medium leading-5 text-[#999] transition-colors fine-pointer:hover:bg-[#F7F7F7]"
            >
                <span>
                    {group === "created"
                        ? localize("com_subscription.created_by_me")
                        : localize("com_subscription.followed_by_me")}
                </span>
                <Outlined.Exchange className="size-4" />
            </button>
            {/* Each action is a 20px hit-box wrapping a 16px icon; 12px between them. */}
            <div className="flex items-center gap-3">
                {group === "created" && onCreateChannel ? (
                    <button
                        type="button"
                        onClick={() => { onCreateChannel(); setOpen(false); }}
                        aria-label={localize("com_subscription.create")}
                        title={localize("com_subscription.create")}
                        className="flex size-5 shrink-0 items-center justify-center text-[#86909C] transition-colors fine-pointer:hover:text-[#212121]"
                    >
                        <Outlined.Plus className="size-4" />
                    </button>
                ) : null}
                <button
                    type="button"
                    onClick={toggleSort}
                    aria-label={getSortText(currentSort)}
                    title={getSortText(currentSort)}
                    className="flex size-5 shrink-0 items-center justify-center text-[#86909C] transition-colors fine-pointer:hover:text-[#212121]"
                >
                    <Outlined.Sort className="size-4" />
                </button>
            </div>
        </div>
    );

    // Persistent "go to plaza" button shown at the bottom of both the PC popover and the H5 panel.
    const renderChannelSquareButton = () =>
        onChannelSquare ? (
            <button
                type="button"
                onClick={() => { onChannelSquare(); setOpen(false); }}
                className="flex w-full shrink-0 items-center justify-center gap-1 rounded-[8px] border border-[#E3E3E3] bg-white px-3 py-[5px] text-[14px] leading-[22px] text-[#212121] transition-colors fine-pointer:hover:bg-[#F7F8FA]"
            >
                <Outlined.BlocksAndArrows className="size-4 text-[#86909C]" />
                {localize("com_subscription.go_to_square")}
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
                <div className="py-6 text-center text-sm text-[#818181]">{localize("com_subscription.no_data")}</div>
            ) : (
                channels.map((c) => {
                    const isActive = c.id === activeChannelId;
                    return (
                        <div
                            key={c.id}
                            className="group flex w-full shrink-0 items-center gap-1 border-b border-dashed border-[#ececec] py-1 transition-colors last:border-b-0 fine-pointer:hover:bg-[#F7F7F7]"
                        >
                            <button
                                type="button"
                                onClick={() => handleSelect(c)}
                                className="flex h-10 min-w-0 flex-1 items-center px-1 text-left outline-none"
                            >
                                <span className={cn(
                                    "max-w-full truncate py-1 text-[14px] leading-[22px] text-[#212121] [font-family:-apple-system,system-ui,'PingFang_SC','Microsoft_YaHei','Noto_Sans_CJK_SC',sans-serif]",
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
                                className="flex size-6 shrink-0 items-center justify-center rounded outline-none transition-colors fine-pointer:hover:bg-[#ececec]"
                            >
                                <Outlined.ToTop className={cn("size-3 transition-colors", c.isPinned ? "text-[#4E5969]" : "text-[#C9CDD4]")} />
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
                <button
                    type="button"
                    onClick={() => handleOpenChange(!open)}
                    aria-expanded={open}
                    className="flex min-w-0 flex-1 items-center justify-center gap-1 outline-none"
                >
                    <span className="truncate text-[16px] font-medium leading-6 text-[#212121]">
                        {channelName}
                    </span>
                    <Outlined.Down className={cn(
                        "size-5 shrink-0 text-[#86909C] transition-transform",
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
                            {renderChannelSquareButton()}
                        </div>
                    </div>
                ) : null}
            </>
        );
    }

    return (
        <div
            ref={titleRef}
            className="flex min-w-0 items-center gap-2 text-[32px] leading-[40px] text-[#212121] font-bold"
            style={{ fontFamily: SERIF_FONT_STACK }}
        >
            <span className="shrink-0">{localize("com_subscription.subscribe")}</span>
            <span className="shrink-0 text-[#C9CDD4]">·</span>
            {/* Info popover is scoped to the channel name. The name is not clickable — only the
                arrow opens the switcher menu. */}
            <Tooltip open={Boolean(infoContent) && infoOpen && !open} onOpenChange={setInfoOpen}>
                <TooltipTrigger asChild>
                    <span
                        className={cn("truncate text-[#212121] transition-colors", !open && "fine-pointer:hover:text-[#878787]")}
                        onMouseEnter={() => setInfoOpen(true)}
                        onMouseLeave={() => setInfoOpen(false)}
                    >
                        {channelName}
                    </span>
                </TooltipTrigger>
                {infoContent ? (
                    <TooltipContent noArrow side="bottom" align="start" className="w-[240px] max-w-md bg-white px-3 py-2 text-gray-800 shadow-md">
                        {infoContent}
                    </TooltipContent>
                ) : null}
            </Tooltip>
            <Popover open={open} onOpenChange={handleOpenChange}>
                <PopoverTrigger asChild>
                    <button
                        type="button"
                        aria-haspopup="menu"
                        aria-expanded={open}
                        className={cn("flex size-8 shrink-0 items-center justify-center rounded-md outline-none transition-colors", !open && "fine-pointer:hover:bg-[#F7F8FA]")}
                    >
                        <Outlined.Down className={cn("size-6 text-[#86909C] transition-transform", open && "rotate-180")} />
                    </button>
                </PopoverTrigger>
                <PopoverContent
                    align="center"
                    sideOffset={8}
                    collisionPadding={{ left: collisionLeft, bottom: 40 }}
                    className="flex max-h-[var(--radix-popover-content-available-height)] w-[320px] flex-col gap-2 rounded-[8px] border-0 bg-white p-3 shadow-[0px_4px_20px_0px_rgba(23,0,176,0.1)]"
                >
                    {renderSectionHeader()}
                    {renderChannelList()}
                </PopoverContent>
            </Popover>
        </div>
    );
}
