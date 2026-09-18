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
    onSelect: (channel: Channel) => void;
}

function ChannelCard({ channel, onSelect }: ChannelCardProps) {
    const localize = useLocalize();
    return (
        <button
            type="button"
            onClick={() => onSelect(channel)}
            className="flex min-w-0 flex-col gap-1 rounded-lg border border-border-base px-4 py-3 text-left transition-colors hover:bg-fill-1"
        >
            <div className="flex w-full min-w-0 items-center gap-1">
                <span className="min-w-0 truncate text-body text-text-1">{channel.name}</span>
                <DemoTag id={channel.id} className="shrink-0" />
                {channel.isPinned ? <Outlined.Pin className="size-3.5 shrink-0 text-text-3" aria-hidden /> : null}
                {channel.unreadCount > 0 ? <Badge count={channel.unreadCount} className="ml-auto shrink-0" /> : null}
            </div>
            {/* my_channels returns neither counts nor a description (those come with the
                channel detail), so the card sticks to what the list really knows. */}
            <div className="flex w-full items-center gap-3 text-caption text-text-3 tabular-nums">
                <span className="whitespace-nowrap">
                    {localize("com_subscription.home_source_count", { 0: channel.source_list?.length ?? 0 })}
                </span>
                {channel.updatedAt ? <span className="min-w-0 truncate">{formatTimeCard(channel.updatedAt)}</span> : null}
            </div>
        </button>
    );
}

/**
 * Desktop 频道订阅 · 我的 view (see ~/components/ModuleHome for the shared frame): the
 * user's channels as card grids (我创建的 / 我关注的). 广场 is the switcher's other half,
 * rendered once by the page so it survives the view change.
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
        { key: "created", title: localize("com_subscription.created_by_me"), channels: createdChannels, canCreate: true },
        { key: "subscribed", title: localize("com_subscription.followed_by_me"), channels: subscribedChannels, canCreate: false },
    ];

    return (
        // The scroll area spans the full width so its scrollbar sits at the page edge, not
        // beside the column.
        <div className={MODULE_HOME_FRAME}>
            <ModuleHomeHeader title={menuNames.channel} />
            <div className="scroll-on-scroll flex min-h-0 w-full flex-1 flex-col items-center overflow-y-auto">
                <div className={cn(MODULE_HOME_COLUMN, "flex flex-col gap-6 pb-3 pt-4")}>
                    {sections.map((section) => (
                        <section key={section.key} className="flex flex-col gap-3">
                            <div className="flex h-8 items-center justify-between gap-3">
                                <h2 className="min-w-0 truncate text-body font-medium text-text-1">{section.title}</h2>
                                {section.canCreate && (
                                    <Button color="primary" variant="text" onClick={onCreateChannel}>
                                        <Outlined.Plus />
                                        {localize("com_subscription.create_channel")}
                                    </Button>
                                )}
                            </div>
                            {section.channels.length > 0 ? (
                                <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3">
                                    {section.channels.map((channel) => (
                                        <ChannelCard key={channel.id} channel={channel} onSelect={onChannelSelect} />
                                    ))}
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
