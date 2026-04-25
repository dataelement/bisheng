import { useCallback, useEffect, useState } from "react";
import { Channel } from "~/api/channels";
import { getGrantableRelationModels } from "~/api/permission";
import type { RelationModel } from "~/api/permission";
import { PermissionGrantTab } from "~/components/permission/PermissionGrantTab";
import { PermissionListTab } from "~/components/permission/PermissionListTab";
import {
    Button,
    Checkbox,
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

interface ChannelShareDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    channel: Channel | null;
}

export function ChannelShareDialog({
    open,
    onOpenChange,
    channel,
}: ChannelShareDialogProps) {
    const localize = useLocalize();
    const [refreshKey, setRefreshKey] = useState(0);
    const [currentSubjectType, setCurrentSubjectType] = useState<"user" | "department" | "user_group">("user");
    const [grantDialogOpen, setGrantDialogOpen] = useState(false);
    const [grantSubjectType, setGrantSubjectType] = useState<"user" | "department" | "user_group">("user");
    const [grantIncludeChildren, setGrantIncludeChildren] = useState(true);
    const [grantableModels, setGrantableModels] = useState<RelationModel[]>([]);
    const [grantableModelsLoaded, setGrantableModelsLoaded] = useState(false);

    useEffect(() => {
        if (open) {
            setCurrentSubjectType("user");
        }
    }, [open, channel?.id]);

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

    const handleGrantSuccess = useCallback(() => {
        setRefreshKey((key) => key + 1);
        setCurrentSubjectType(grantSubjectType);
        setGrantDialogOpen(false);
    }, [grantSubjectType]);

    if (!channel) return null;

    const resourceName = channel.name ? ` - ${channel.name}` : "";
    const dialogTitle = `${localize("com_permission.dialog_title")}${resourceName}`;

    const SUBJECT_TABS: Array<{
        value: "user" | "department" | "user_group";
        labelKey: string;
    }> = [
        { value: "user", labelKey: "com_permission.subject_user" },
        { value: "department", labelKey: "com_permission.subject_department" },
        { value: "user_group", labelKey: "com_permission.subject_user_group" },
    ];

    const permissionPanel = (
        <Tabs
            value={currentSubjectType}
            onValueChange={(value) => setCurrentSubjectType(value as "user" | "department" | "user_group")}
            className="flex min-h-0 flex-1 flex-col"
        >
            <div className="flex items-center justify-between gap-3">
                <TabsList className="w-fit shrink-0 rounded-[6px] border border-[#ECECEC] bg-white p-[3px] shadow-none">
                    {SUBJECT_TABS.map((tab) => (
                        <TabsTrigger
                            key={tab.value}
                            value={tab.value}
                            className="min-w-0 rounded-[4px] px-3 py-0.5 text-[14px] font-normal leading-[22px] text-[#818181] shadow-none data-[state=active]:bg-[rgba(51,92,255,0.15)] data-[state=active]:font-medium data-[state=active]:text-[#335CFF] data-[state=active]:shadow-none"
                        >
                            {localize(tab.labelKey)}
                        </TabsTrigger>
                    ))}
                </TabsList>

                <Button
                    type="button"
                    className="h-8 shrink-0 rounded-[6px] px-3 text-[14px] leading-[22px]"
                    onClick={() => {
                        setGrantSubjectType(currentSubjectType);
                        setGrantDialogOpen(true);
                    }}
                >
                    {localize("com_permission.tab_grant")}
                </Button>
            </div>

            <TabsContent
                value={currentSubjectType}
                className="mt-3 min-h-0 flex-1 p-0"
            >
                <PermissionListTab
                    resourceType="channel"
                    resourceId={channel.id}
                    refreshKey={refreshKey}
                    fixedSubjectType={currentSubjectType}
                    prefetchedGrantableModels={grantableModels}
                    prefetchedGrantableModelsLoaded={grantableModelsLoaded}
                    skipGrantableModelsRequest
                />
            </TabsContent>
        </Tabs>
    );

    return (
        <>
            <Dialog open={open} onOpenChange={onOpenChange}>
                <DialogContent className="!flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-5">
                    <DialogHeader className="shrink-0">
                        <DialogTitle>{dialogTitle}</DialogTitle>
                    </DialogHeader>

                    <div className="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden">
                        {permissionPanel}
                    </div>
                </DialogContent>
            </Dialog>

            <Dialog open={grantDialogOpen} onOpenChange={setGrantDialogOpen}>
                <DialogContent className="!flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-5">
                    <DialogHeader className="shrink-0">
                        <DialogTitle>
                            {localize("com_permission.tab_grant")}{resourceName}
                        </DialogTitle>
                    </DialogHeader>

                    <div className="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden">
                        <div className="flex items-center gap-3">
                            <div className="inline-flex w-fit shrink-0 items-center justify-center rounded-[6px] border border-[#ECECEC] bg-white p-[3px]">
                                {SUBJECT_TABS.map((tab) => (
                                    <button
                                        key={tab.value}
                                        type="button"
                                        className={[
                                            "min-w-0 rounded-[4px] px-3 py-0.5 text-[14px] leading-[22px] transition-colors",
                                            grantSubjectType === tab.value
                                                ? "bg-[rgba(51,92,255,0.15)] font-medium text-[#335CFF]"
                                                : "font-normal text-[#818181]",
                                        ].join(" ")}
                                        onClick={() => setGrantSubjectType(tab.value)}
                                    >
                                        {localize(tab.labelKey)}
                                    </button>
                                ))}
                            </div>

                            {grantSubjectType === "department" && (
                                <label className="flex shrink-0 cursor-pointer items-center gap-2 text-[14px] leading-[22px] text-[#212121]">
                                    <Checkbox
                                        checked={grantIncludeChildren}
                                        onCheckedChange={(value) => setGrantIncludeChildren(value === true)}
                                    />
                                    {localize("com_permission.include_children")}
                                </label>
                            )}
                        </div>

                        <div className="mt-4 min-h-0 flex-1 overflow-hidden">
                            <PermissionGrantTab
                                resourceType="channel"
                                resourceId={channel.id}
                                onSuccess={handleGrantSuccess}
                                prefetchedGrantableModels={grantableModels}
                                prefetchedGrantableModelsLoaded={grantableModelsLoaded}
                                skipGrantableModelsRequest
                                fixedSubjectType={grantSubjectType}
                                includeChildren={grantIncludeChildren}
                                onIncludeChildrenChange={setGrantIncludeChildren}
                                hideDepartmentIncludeChildrenControl
                            />
                        </div>
                    </div>
                </DialogContent>
            </Dialog>
        </>
    );
}
