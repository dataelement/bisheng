import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Channel, SortType, getChannelsApi } from "~/api/channels";
import { Popover, PopoverContent, PopoverTrigger } from "~/components/ui/Popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

interface ChannelSwitcherProps {
    activeChannelId?: string;
    /** Current channel display name shown in the trigger. */
    channelName: string;
    onChannelSelect: (channel: Channel) => void;
    onCreateChannel?: () => void;
    onChannelSquare?: () => void;
    /** Channel info shown in a tooltip when hovering the title. */
    infoContent?: ReactNode;
}

type ChannelGroup = "created" | "subscribed";

/**
 * Top-title channel switcher dropdown (replaces the left ChannelSidebar on PC).
 * Switch between 我创建的 / 我关注的, create/sort, pick a channel, go to square.
 * Per-channel management lives in the page-level ChannelActionsMenu (top-right ⊙).
 */
export function ChannelSwitcher({
    activeChannelId,
    channelName,
    onChannelSelect,
    onCreateChannel,
    onChannelSquare,
    infoContent,
}: ChannelSwitcherProps) {
    const localize = useLocalize();
    const queryClient = useQueryClient();
    const [open, setOpen] = useState(false);
    const [infoOpen, setInfoOpen] = useState(false);
    // After closing the dropdown with the pointer still over the title, suppress hover
    // styles until the pointer leaves and re-enters (avoids sticky hover).
    const [hoverSuppressed, setHoverSuppressed] = useState(false);
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
            // Closing: keep hover suppressed until the pointer leaves the title.
            setHoverSuppressed(true);
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

    return (
        <Tooltip open={Boolean(infoContent) && infoOpen && !open && !hoverSuppressed} onOpenChange={setInfoOpen}>
            <TooltipTrigger asChild>
            <div
                className="group inline-flex min-w-0"
                onMouseEnter={() => { setHoverSuppressed(false); setInfoOpen(true); }}
                onMouseLeave={() => { setHoverSuppressed(false); setInfoOpen(false); }}
            >
            <Popover open={open} onOpenChange={handleOpenChange}>
            <PopoverTrigger asChild>
                <button
                    type="button"
                    className="flex min-w-0 items-center gap-2 text-[32px] leading-[40px] text-[#212121] outline-none [font-family:'Songti_SC','STSong','SimSun',serif] font-bold"
                >
                    <span className="shrink-0">{localize("com_subscription.subscribe")}</span>
                    <span className="shrink-0 text-[#C9CDD4]">·</span>
                    <span className={cn("truncate text-[#212121] transition-colors", !open && !hoverSuppressed && "fine-pointer:group-hover:text-[#878787]")}>{channelName}</span>
                    <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-md transition-colors", !open && !hoverSuppressed && "fine-pointer:hover:bg-[#F7F8FA]")}>
                        <Outlined.Down className={cn("size-6 text-[#86909C] transition-transform", open && "rotate-180")} />
                    </span>
                </button>
            </PopoverTrigger>
            <PopoverContent
                align="start"
                sideOffset={8}
                className="flex max-h-[560px] w-[320px] flex-col gap-2 rounded-[8px] border-0 bg-white p-3 shadow-[0px_4px_20px_0px_rgba(23,0,176,0.1)]"
            >
                {/* Header: group switch pill + actions */}
                <div className="flex w-full shrink-0 items-center justify-between">
                    <button
                        type="button"
                        onClick={() => setGroup((g) => (g === "created" ? "subscribed" : "created"))}
                        className="flex items-center gap-1 rounded-[6px] p-1 text-[12px] font-medium leading-5 text-[#999] transition-colors fine-pointer:hover:bg-[#F7F7F7]"
                    >
                        <span>{group === "created" ? localize("com_subscription.created_by_me") : localize("com_subscription.followed_by_me")}</span>
                        <Outlined.Exchange className="size-4" />
                    </button>
                    <div className="flex items-center gap-2.5 px-1">
                        {group === "created" && onCreateChannel ? (
                            <button
                                type="button"
                                onClick={onCreateChannel}
                                aria-label={localize("com_subscription.create")}
                                title={localize("com_subscription.create")}
                                className="text-[#86909C] transition-colors fine-pointer:hover:text-[#212121]"
                            >
                                <Outlined.Plus className="size-4" />
                            </button>
                        ) : null}
                        <button
                            type="button"
                            onClick={toggleSort}
                            aria-label={getSortText(currentSort)}
                            title={getSortText(currentSort)}
                            className="text-[#86909C] transition-colors fine-pointer:hover:text-[#212121]"
                        >
                            <Outlined.Sort className="size-4" />
                        </button>
                    </div>
                </div>

                {/* Channel list */}
                <div ref={listRef} className="scrollbar-os flex min-h-0 w-full flex-1 flex-col overflow-y-auto">
                    {channels.length === 0 ? (
                        <div className="py-6 text-center text-sm text-[#818181]">{localize("com_subscription.no_data")}</div>
                    ) : (
                        channels.map((c) => {
                            const isActive = c.id === activeChannelId;
                            return (
                                <button
                                    type="button"
                                    key={c.id}
                                    onClick={() => handleSelect(c)}
                                    className="group flex w-full shrink-0 items-center gap-1 border-b border-dashed border-[#ececec] py-1 text-left transition-colors last:border-b-0 fine-pointer:hover:bg-[#F7F7F7]"
                                >
                                    <span className="flex h-10 min-w-0 flex-1 items-center px-1">
                                        <span className={cn(
                                            "max-w-full truncate py-1 text-[14px] leading-[22px] text-[#212121] [font-family:-apple-system,system-ui,'PingFang_SC','Microsoft_YaHei','Noto_Sans_CJK_SC',sans-serif]",
                                            isActive ? "border-b border-[#212121] font-semibold" : "font-normal",
                                        )}>
                                            {c.name}
                                        </span>
                                    </span>
                                    {c.isPinned && <Outlined.ToTop className="size-3 shrink-0 text-[#86909C]" />}
                                </button>
                            );
                        })
                    )}
                </div>

                {/* Footer: go to square */}
                {onChannelSquare ? (
                    <button
                        type="button"
                        onClick={() => { onChannelSquare(); setOpen(false); }}
                        className="flex w-full shrink-0 items-center justify-center gap-1 rounded-[6px] border border-[#E3E3E3] bg-white px-3 py-[5px] text-[14px] leading-[22px] text-[#212121] transition-colors fine-pointer:hover:bg-[#F7F8FA]"
                    >
                        <Outlined.BlocksAndArrows className="size-4 text-[#86909C]" />
                        {localize("com_subscription.go_to_square")}
                    </button>
                ) : null}
            </PopoverContent>
            </Popover>
            </div>
            </TooltipTrigger>
            {infoContent ? (
                <TooltipContent noArrow side="bottom" align="start" className="w-[240px] max-w-md bg-white px-3 py-2 text-gray-800 shadow-md">
                    {infoContent}
                </TooltipContent>
            ) : null}
        </Tooltip>
    );
}
