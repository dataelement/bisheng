import { Badge, Button } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import type { Channel } from "~/api/channels";
import { MODULE_HOME_COLUMN, MODULE_HOME_FRAME, ModuleHomeHeader } from "~/components/ModuleHome";
import { useLocalize, useWorkbenchMenuNames } from "~/hooks";
import { DemoTag } from "~/mock/demo/DemoTag";
import { cn } from "~/utils";
import { formatTimeCard } from "~/pages/knowledge/knowledgeUtils";

interface ChannelHomePageProps {
    createdChannels: Channel[];
    subscribedChannels: Channel[];
    onChannelSelect: (channel: Channel) => void;
    onCreateChannel: () => void;
}

interface ChannelCardProps {
    channel: Channel;
    /** 1-based position inside its section — printed as the card's issue number. */
    index: number;
    onSelect: (channel: Channel) => void;
}

// Headline face for the newspaper-style cards: the platform's Songti/Mincho where one
// exists, the generic serif otherwise. System fonts only — nothing is downloaded.
const HEADLINE_FONT =
    "font-['Songti_SC','STSong','Noto_Serif_CJK_SC','Source_Han_Serif_SC','SimSun','Hiragino_Mincho_ProN',Georgia,serif]";

/**
 * A channel as a cell of a ruled newspaper index: issue-number kicker, serif headline,
 * optional standfirst, dateline (last update · source count · unread). The cell has no box
 * of its own — it carries the row rule (border-b) and an inset column rule on its left;
 * see the grid wrapper for how the outer rules are closed.
 */
function ChannelCard({ channel, index, onSelect }: ChannelCardProps) {
    const localize = useLocalize();
    return (
        <button
            type="button"
            onClick={() => onSelect(channel)}
            className="group relative flex min-h-[116px] min-w-0 flex-col border-b border-border-base px-4 py-4 text-left before:absolute before:bottom-4 before:left-0 before:top-4 before:w-px before:bg-border-base"
        >
            <div className="flex h-5 w-full min-w-0 items-center gap-2">
                <span className="shrink-0 font-mono text-caption-sm tracking-[0.12em] text-text-3 tabular-nums">
                    NO.{String(index).padStart(2, "0")}
                </span>
                <DemoTag id={channel.id} className="shrink-0" />
                {channel.isPinned ? <Outlined.Pin className="size-3.5 shrink-0 text-text-3" aria-hidden /> : null}
                <Outlined.ArrowRightUp
                    className="ml-auto size-4 shrink-0 text-text-3 transition-transform duration-200 group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-blue-500"
                    aria-hidden
                />
            </div>
            <span className={cn(HEADLINE_FONT, "mt-1.5 line-clamp-2 w-full break-words text-h3 font-semibold text-text-1 transition-colors group-hover:text-blue-500")}>
                {channel.name}
            </span>
            {/* my_channels rarely carries a description (it comes with the channel detail);
                the standfirst only shows when the list really has one. */}
            {channel.description ? (
                <span className="mt-1 line-clamp-2 w-full text-caption text-text-2">{channel.description}</span>
            ) : null}
            <span className="min-h-3 flex-1" aria-hidden />
            <div className="flex w-full items-center gap-2 text-caption text-text-3 tabular-nums">
                {channel.updatedAt ? (
                    <span className="shrink-0 whitespace-nowrap font-mono tracking-[0.04em]">
                        {formatTimeCard(channel.updatedAt)}
                    </span>
                ) : null}
                {channel.updatedAt ? <span className="size-0.5 shrink-0 rounded-full bg-text-3" aria-hidden /> : null}
                <span className="min-w-0 truncate">
                    {localize("com_subscription.home_source_count", { 0: channel.source_list?.length ?? 0 })}
                </span>
                {channel.unreadCount > 0 ? <Badge count={channel.unreadCount} className="ml-auto shrink-0" /> : null}
            </div>
        </button>
    );
}

/**
 * Desktop 频道订阅 · 我的 view (see ~/components/ModuleHome for the shared frame): the
 * user's channels as card grids (我创建的 / 我关注的). 广场 is the switcher's other half,
 * rendered once by the page so it survives the view change. 创建频道 is the header's action.
 * Per-channel management stays on the channel page's settings menu. Users with no
 * channel at all never get here; they see ChannelDiscoveryHome instead.
 */
export function ChannelHomePage({
    createdChannels,
    subscribedChannels,
    onChannelSelect,
    onCreateChannel,
}: ChannelHomePageProps) {
    const localize = useLocalize();
    const menuNames = useWorkbenchMenuNames();

    const sections = [
        { key: "created", title: localize("com_subscription.created_by_me"), channels: createdChannels },
        { key: "subscribed", title: localize("com_subscription.followed_by_me"), channels: subscribedChannels },
    ];

    return (
        // The scroll area spans the full width so its scrollbar sits at the page edge, not
        // beside the column.
        <div className={cn(MODULE_HOME_FRAME, "px-[clamp(1rem,3.5%,2rem)] py-6")}>
            <ModuleHomeHeader title={menuNames.channel}>
                <Button onClick={onCreateChannel}>
                    <Outlined.Plus />
                    {localize("com_subscription.create_channel")}
                </Button>
            </ModuleHomeHeader>
            <div className="scroll-on-scroll flex min-h-0 w-full flex-1 flex-col items-center overflow-y-auto">
                <div className={cn(MODULE_HOME_COLUMN, "flex flex-col gap-6 pb-3 pt-4")}>
                    {sections.map((section) => (
                        <section key={section.key} className="flex flex-col gap-3">
                            <h2 className="flex h-8 min-w-0 items-center truncate text-body font-medium text-text-1">{section.title}</h2>
                            {section.channels.length > 0 ? (
                                // Ruled index: the wrapper draws the heavier top/bottom rules; cells draw
                                // the row rules. -mb-px + overflow-hidden clips the last row's own rule so a
                                // partially filled last row still closes with a full-width line. The grid also
                                // hangs one cell padding (-ml-4) past the clipped left edge: the first column's
                                // inset rule falls outside and its content lines up with the section title,
                                // whatever the auto-fill column count is.
                                <div className="overflow-hidden border-y border-border-deep">
                                    <div className="-mb-px -ml-4 grid grid-cols-[repeat(auto-fill,minmax(min(100%,320px),1fr))]">
                                        {section.channels.map((channel, i) => (
                                            <ChannelCard key={channel.id} channel={channel} index={i + 1} onSelect={onChannelSelect} />
                                        ))}
                                    </div>
                                </div>
                            ) : (
                                <div className="flex h-24 items-center justify-center text-body text-text-3">
                                    {localize("com_subscription.no_data")}
                                </div>
                            )}
                        </section>
                    ))}
                </div>
            </div>
        </div>
    );
}
