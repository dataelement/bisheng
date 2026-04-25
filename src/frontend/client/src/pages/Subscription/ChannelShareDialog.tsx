import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Channel, ChannelRole, getChannelDetailApi } from "~/api/channels";
import { canOpenPermissionDialog, getGrantableRelationModels } from "~/api/permission";
import type { RelationModel } from "~/api/permission";
import { ChannelMemberManagementPanel } from "~/components/ChannelMemberManagementPanel";
import { PermissionGrantTab, PermissionListTab } from "~/components/permission";
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

const SHARE_TAB = "share";
const MEMBERS_TAB = "members";
const PERMISSION_TAB = "permission";

type ChannelShareTab = typeof SHARE_TAB | typeof MEMBERS_TAB | typeof PERMISSION_TAB;

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
    const [refreshKey, setRefreshKey] = useState(0);
    const [grantableModels, setGrantableModels] = useState<RelationModel[]>([]);
    const [grantableModelsLoaded, setGrantableModelsLoaded] = useState(false);

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
    const { data: canManagePermission = canManageMembers } = useQuery({
        queryKey: ["channelShareDialogPermission", channel?.id],
        queryFn: async () => {
            if (!channel?.id) return false;
            return await canOpenPermissionDialog("channel", channel.id);
        },
        enabled: open && !!channel?.id,
        staleTime: 60_000,
    });
    const showShareTab = channelDetail ? channelDetail.visibility !== "private" : canManageMembers;
    const showMembersTab = canManageMembers;
    const showPermissionTab = Boolean(channel?.id) && canManagePermission;

    const resolveVisibleTab = useCallback((preferred: ChannelShareTab): ChannelShareTab => {
        if (preferred === SHARE_TAB && showShareTab) return SHARE_TAB;
        if (preferred === MEMBERS_TAB && showMembersTab) return MEMBERS_TAB;
        if (preferred === PERMISSION_TAB && showPermissionTab) return PERMISSION_TAB;
        if (showShareTab) return SHARE_TAB;
        if (showMembersTab) return MEMBERS_TAB;
        if (showPermissionTab) return PERMISSION_TAB;
        return preferred;
    }, [showMembersTab, showPermissionTab, showShareTab]);

    useEffect(() => {
        if (!open) return;
        setActiveTab(resolveVisibleTab(initialTab));
        setCopied(false);
    }, [channel?.id, initialTab, open, resolveVisibleTab]);

    useEffect(() => {
        if (!open) return;
        const nextTab = resolveVisibleTab(activeTab);
        if (nextTab !== activeTab) {
            setActiveTab(nextTab);
        }
    }, [activeTab, open, resolveVisibleTab]);

    useEffect(() => {
        if (!open || !channel?.id) return;

        setGrantableModelsLoaded(false);
        getGrantableRelationModels("channel", channel.id)
            .then((res) => {
                setGrantableModels(Array.isArray(res) ? res : []);
                setGrantableModelsLoaded(true);
            })
            .catch(() => {
                setGrantableModels([]);
                setGrantableModelsLoaded(true);
            });
    }, [channel?.id, open]);

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
            : showMembersTab
                ? localize("com_subscription.management_member")
                : localize("com_permission.dialog_title")
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
                active={open && activeTab === MEMBERS_TAB}
            />
        </div>
    );

    const handleGrantSuccess = () => {
        setRefreshKey((key) => key + 1);
        setActiveTab(PERMISSION_TAB);
    };

    const permissionPanel = (
        <>
            <TabsList className="bg-surface-primary-alt p-1">
                <TabsTrigger value="list">
                    {localize("com_permission.tab_list")}
                </TabsTrigger>
                <TabsTrigger value="grant">
                    {localize("com_permission.tab_grant")}
                </TabsTrigger>
            </TabsList>
            <TabsContent value="list" className="p-0">
                <PermissionListTab
                    resourceType="channel"
                    resourceId={channel.id}
                    refreshKey={refreshKey}
                    prefetchedGrantableModels={grantableModels}
                    prefetchedGrantableModelsLoaded={grantableModelsLoaded}
                    skipGrantableModelsRequest
                />
            </TabsContent>
            <TabsContent value="grant" className="p-0">
                <PermissionGrantTab
                    resourceType="channel"
                    resourceId={channel.id}
                    onSuccess={handleGrantSuccess}
                    prefetchedGrantableModels={grantableModels}
                    prefetchedGrantableModelsLoaded={grantableModelsLoaded}
                    skipGrantableModelsRequest
                />
            </TabsContent>
        </>
    );

    const hasMultipleTabs = [showShareTab, showMembersTab, showPermissionTab].filter(Boolean).length > 1;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[680px]">
                <DialogHeader>
                    <DialogTitle>{dialogTitle}</DialogTitle>
                </DialogHeader>

                {hasMultipleTabs ? (
                    <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as ChannelShareTab)}>
                        <TabsList className="bg-surface-primary-alt p-1">
                            {showShareTab && (
                                <TabsTrigger value={SHARE_TAB}>
                                    {localize("com_subscription.share")}
                                </TabsTrigger>
                            )}
                            {showMembersTab && (
                                <TabsTrigger value={MEMBERS_TAB}>
                                    {localize("com_subscription.member_management")}
                                </TabsTrigger>
                            )}
                            {showPermissionTab && (
                                <TabsTrigger value={PERMISSION_TAB}>
                                    {localize("com_permission.manage_permission")}
                                </TabsTrigger>
                            )}
                        </TabsList>
                        {showShareTab && (
                            <TabsContent value={SHARE_TAB} className="p-0">
                                {sharePanel}
                            </TabsContent>
                        )}
                        {showMembersTab && (
                            <TabsContent value={MEMBERS_TAB} className="flex min-h-0 flex-1 p-0">
                                {memberPanel}
                            </TabsContent>
                        )}
                        {showPermissionTab && (
                            <TabsContent value={PERMISSION_TAB} className="p-0">
                                <Tabs defaultValue="list">{permissionPanel}</Tabs>
                            </TabsContent>
                        )}
                    </Tabs>
                ) : showShareTab ? (
                    sharePanel
                ) : showMembersTab ? (
                    memberPanel
                ) : showPermissionTab ? (
                    <Tabs defaultValue="list">{permissionPanel}</Tabs>
                ) : null
                }
            </DialogContent>
        </Dialog>
    );
}
