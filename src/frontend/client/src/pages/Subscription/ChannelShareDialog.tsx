import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Channel, ChannelRole, getChannelDetailApi } from "~/api/channels";
import { ChannelMemberManagementPanel } from "~/components/ChannelMemberManagementPanel";
import {
    Button,
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    Input,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "~/components/ui";
import { useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";
import { copyText } from "~/utils";

type ChannelShareTab = "share" | "members";

interface ChannelShareDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    channel: Channel | null;
    initialTab?: ChannelShareTab;
}

export function ChannelShareDialog({
    open,
    onOpenChange,
    channel,
    initialTab = "share",
}: ChannelShareDialogProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const [activeTab, setActiveTab] = useState<ChannelShareTab>(initialTab);
    const [copied, setCopied] = useState(false);

    const { data: channelDetail } = useQuery({
        queryKey: ["channelShareDialogDetail", channel?.id],
        queryFn: async () => {
            if (!channel?.id) return null;
            return await getChannelDetailApi(channel.id);
        },
        enabled: open && !!channel?.id,
        staleTime: 60_000,
    });

    const canManageMembers =
        channel?.role === ChannelRole.CREATOR || channel?.role === ChannelRole.ADMIN;
    const showShareTab = channelDetail ? channelDetail.visibility !== "private" : canManageMembers;
    const showMembersTab = canManageMembers;
    useEffect(() => {
        if (!open) return;
        setActiveTab(initialTab);
        setCopied(false);
    }, [open, initialTab]);

    useEffect(() => {
        if (!open) return;
        if (activeTab === "share" && !showShareTab && showMembersTab) {
            setActiveTab("members");
        }
        if (activeTab === "members" && !showMembersTab && showShareTab) {
            setActiveTab("share");
        }
    }, [activeTab, open, showMembersTab, showShareTab]);

    const shareLink = useMemo(() => {
        if (!channel?.id || typeof window === "undefined") return "";
        const base = window.location.origin + (__APP_ENV__.BASE_URL || "");
        const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;
        return `${normalizedBase}/channel/share/${channel.id}`;
    }, [channel?.id]);

    if (!channel) return null;

    const dialogTitle = `${
        showShareTab
            ? localize("com_subscription.share")
            : localize("com_subscription.management_member")
    } - ${channel.name}`;

    const sharePanel = (
        <div className="space-y-3 pt-2">
            <div className="rounded-lg border border-[#EBECF0] bg-[#F7F8FA] p-3">
                <div className="mb-2 text-sm font-medium text-[#1D2129]">
                    {localize("com_ui_copy_link")}
                </div>
                <div className="flex items-center gap-2">
                    <Input
                        readOnly
                        value={shareLink}
                        className="flex-1 border-[#EBECF0] bg-white"
                    />
                    <Button
                        type="button"
                        variant="outline"
                        className="shrink-0"
                        onClick={async () => {
                            try {
                                await copyText(shareLink);
                                setCopied(true);
                                showToast({
                                    message: localize("com_subscription.share_link_copied"),
                                    status: "success",
                                });
                            } catch {
                                showToast({
                                    message: localize("com_knowledge.copy_failed_retry"),
                                    status: "error",
                                });
                            }
                        }}
                    >
                        {copied ? localize("com_ui_duplicated") : localize("com_ui_copy_link")}
                    </Button>
                </div>
            </div>
        </div>
    );

    const memberPanel = (
        <div className="flex min-h-0 flex-1 flex-col pt-2">
            <ChannelMemberManagementPanel
                channelId={channel.id}
                currentUserRole={channel.role}
                active={open && activeTab === "members"}
            />
        </div>
    );

    const hasMultipleTabs = showShareTab && showMembersTab;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[680px]">
                <DialogHeader>
                    <DialogTitle>{dialogTitle}</DialogTitle>
                </DialogHeader>

                {hasMultipleTabs ? (
                    <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as ChannelShareTab)}>
                        <TabsList className="bg-surface-primary-alt p-1">
                            <TabsTrigger value="share">
                                {localize("com_subscription.share")}
                            </TabsTrigger>
                            <TabsTrigger value="members">
                                {localize("com_subscription.member_management")}
                            </TabsTrigger>
                        </TabsList>
                        <TabsContent value="share" className="p-0">
                            {sharePanel}
                        </TabsContent>
                        <TabsContent value="members" className="flex min-h-0 flex-1 p-0">
                            {memberPanel}
                        </TabsContent>
                    </Tabs>
                ) : activeTab === "share" || (showShareTab && !showMembersTab) ? (
                    sharePanel
                ) : (
                    memberPanel
                )}
            </DialogContent>
        </Dialog>
    );
}
