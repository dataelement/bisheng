import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Channel, ChannelRole } from "~/api/channels";
import { canOpenPermissionDialog, getGrantableRelationModels } from "~/api/permission";
import type { RelationModel } from "~/api/permission";
import { ChannelMemberManagementPanel } from "~/components/ChannelMemberManagementPanel";
import { PermissionGrantTab, PermissionListTab } from "~/components/permission";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "~/components/ui";
import { useLocalize } from "~/hooks";

const MEMBERS_TAB = "members";
const PERMISSION_TAB = "permission";

type ChannelShareTab = typeof MEMBERS_TAB | typeof PERMISSION_TAB;

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
    initialTab = "members",
}: ChannelShareDialogProps) {
    const localize = useLocalize();
    const [activeTab, setActiveTab] = useState<ChannelShareTab>(initialTab);
    const [refreshKey, setRefreshKey] = useState(0);
    const [grantableModels, setGrantableModels] = useState<RelationModel[]>([]);
    const [grantableModelsLoaded, setGrantableModelsLoaded] = useState(false);

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
    const showMembersTab = canManageMembers;
    const showPermissionTab = Boolean(channel?.id) && canManagePermission;

    const resolveVisibleTab = useCallback((preferred: ChannelShareTab): ChannelShareTab => {
        if (preferred === MEMBERS_TAB && showMembersTab) return MEMBERS_TAB;
        if (preferred === PERMISSION_TAB && showPermissionTab) return PERMISSION_TAB;
        if (showMembersTab) return MEMBERS_TAB;
        if (showPermissionTab) return PERMISSION_TAB;
        return preferred;
    }, [showMembersTab, showPermissionTab]);

    useEffect(() => {
        if (!open) return;
        setActiveTab(resolveVisibleTab(initialTab));
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

    if (!channel) return null;

    const dialogTitle = `${
        activeTab === MEMBERS_TAB
            ? localize("com_subscription.management_member")
            : localize("com_permission.dialog_title")
    } - ${channel.name}`;

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

    const hasMultipleTabs = [showMembersTab, showPermissionTab].filter(Boolean).length > 1;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="!flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-5">
                <DialogHeader className="shrink-0">
                    <DialogTitle>{dialogTitle}</DialogTitle>
                </DialogHeader>

                <div className="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden">
                    {hasMultipleTabs ? (
                        <Tabs
                            value={activeTab}
                            onValueChange={(value) => setActiveTab(value as ChannelShareTab)}
                            className="flex min-h-0 flex-1 flex-col"
                        >
                            <TabsList className="bg-surface-primary-alt p-1">
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
                            {showMembersTab && (
                                <TabsContent value={MEMBERS_TAB} className="flex min-h-0 flex-1 p-0">
                                    {memberPanel}
                                </TabsContent>
                            )}
                            {showPermissionTab && (
                                <TabsContent value={PERMISSION_TAB} className="min-h-0 flex-1 p-0">
                                    <Tabs defaultValue="list">{permissionPanel}</Tabs>
                                </TabsContent>
                            )}
                        </Tabs>
                    ) : showMembersTab ? (
                        memberPanel
                    ) : showPermissionTab ? (
                        <Tabs defaultValue="list">{permissionPanel}</Tabs>
                    ) : null}
                </div>
            </DialogContent>
        </Dialog>
    );
}
