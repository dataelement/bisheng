import { useCallback, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
    authorizeChannelApi,
    Channel,
    getChannelGrantableRelationModelsApi,
    getChannelGrantSubjectsDepartmentChildrenApi,
    getChannelGrantSubjectsDepartmentPathTreeApi,
    getChannelGrantSubjectsUserGroupsApi,
    getChannelGrantSubjectsUsersApi,
    getChannelPermissionsApi,
    searchChannelGrantSubjectsDepartmentsApi,
} from "~/api/channels";
import type { RelationModel, SubjectType } from "~/api/permission";
import { PermissionGrantTab } from "~/components/permission/PermissionGrantTab";
import type { PermissionGrantApiAdapter } from "~/components/permission/PermissionGrantTab";
import { PermissionListTab } from "~/components/permission/PermissionListTab";
import type { PermissionApiAdapter } from "~/components/permission/PermissionListTab";
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

const CHANNEL_RESOURCE_TYPE = "channel" as const;

interface ChannelPermissionDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    channel: Channel | null;
}

type ChannelPermissionApiAdapter = PermissionApiAdapter & PermissionGrantApiAdapter;

const SUBJECT_TABS: Array<{
    value: SubjectType;
    labelKey: string;
}> = [
    { value: "user", labelKey: "com_permission.subject_user" },
    { value: "department", labelKey: "com_permission.subject_department" },
    { value: "user_group", labelKey: "com_permission.subject_user_group" },
];

export function ChannelPermissionDialog({
    open,
    onOpenChange,
    channel,
}: ChannelPermissionDialogProps) {
    const localize = useLocalize();
    const queryClient = useQueryClient();
    const [refreshKey, setRefreshKey] = useState(0);
    const [currentSubjectType, setCurrentSubjectType] = useState<SubjectType>("user");
    const [grantDialogOpen, setGrantDialogOpen] = useState(false);
    const [grantSubjectType, setGrantSubjectType] = useState<SubjectType>("user");
    const [grantIncludeChildren, setGrantIncludeChildren] = useState(true);
    const [grantableModels, setGrantableModels] = useState<RelationModel[]>([]);
    const [grantableModelsLoaded, setGrantableModelsLoaded] = useState(false);

    const channelPermissionApi = useMemo<ChannelPermissionApiAdapter>(() => ({
        getPermissions: (_resourceType, resourceId, config) =>
            getChannelPermissionsApi(resourceId, config),
        authorize: (_resourceType, resourceId, grants, revokes, config) =>
            authorizeChannelApi(resourceId, { grants, revokes }, config),
        getGrantableRelationModels: (_resourceType, resourceId, config) =>
            getChannelGrantableRelationModelsApi(resourceId, config),
        getGrantUsers: (_resourceType, resourceId, params, config) =>
            getChannelGrantSubjectsUsersApi(resourceId, params, config),
        getGrantDepartmentChildren: (_resourceType, resourceId, parentId, config) =>
            getChannelGrantSubjectsDepartmentChildrenApi(resourceId, parentId, config),
        searchGrantDepartments: (_resourceType, resourceId, keyword, limit, config) =>
            searchChannelGrantSubjectsDepartmentsApi(resourceId, keyword, limit, config),
        getGrantDepartmentPathTree: (_resourceType, resourceId, deptId, config) =>
            getChannelGrantSubjectsDepartmentPathTreeApi(resourceId, deptId, config),
        getGrantUserGroups: (_resourceType, resourceId, params, config) =>
            getChannelGrantSubjectsUserGroupsApi(resourceId, params, config),
    }), []);

    useEffect(() => {
        if (!open) return;
        setCurrentSubjectType("user");
        setGrantSubjectType("user");
        setGrantIncludeChildren(true);
    }, [open]);

    useEffect(() => {
        if (grantSubjectType !== "department" && grantIncludeChildren !== true) {
            setGrantIncludeChildren(true);
        }
    }, [grantIncludeChildren, grantSubjectType]);

    useEffect(() => {
        if (!open || !channel?.id) return;
        setGrantableModelsLoaded(false);
        getChannelGrantableRelationModelsApi(channel.id)
            .then((res) => {
                setGrantableModels(Array.isArray(res) ? res : []);
                setGrantableModelsLoaded(true);
            })
            .catch(() => {
                setGrantableModels([]);
                setGrantableModelsLoaded(true);
            });
    }, [channel?.id, open]);

    const handlePermissionChanged = useCallback((subjectType?: SubjectType) => {
        setRefreshKey((key) => key + 1);
        if (subjectType) setCurrentSubjectType(subjectType);
        queryClient.invalidateQueries({ queryKey: ["channels"] });
    }, [queryClient]);

    const handleGrantSuccess = useCallback(() => {
        handlePermissionChanged(grantSubjectType);
        setGrantDialogOpen(false);
    }, [grantSubjectType, handlePermissionChanged]);

    if (!channel) return null;

    const resourceName = channel.name ? ` - ${channel.name}` : "";
    const dialogTitle = `${localize("com_subscription.channel_permission_management")}${resourceName}`;

    return (
        <>
            <Dialog open={open} onOpenChange={onOpenChange}>
                <DialogContent
                    className="!flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-5 max-[768px]:fixed max-[768px]:inset-0 max-[768px]:h-[100dvh] max-[768px]:max-h-[100dvh] max-[768px]:w-full max-[768px]:max-w-none max-[768px]:translate-x-0 max-[768px]:translate-y-0 max-[768px]:rounded-none max-[768px]:p-4"
                    onOpenAutoFocus={(e) => e.preventDefault()}
                >
                    <DialogHeader className="shrink-0 text-left">
                        <DialogTitle className="text-left">{dialogTitle}</DialogTitle>
                    </DialogHeader>

                    <div className="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden">
                        <Tabs
                            value={currentSubjectType}
                            onValueChange={(value) => setCurrentSubjectType(value as SubjectType)}
                            className="flex min-h-0 flex-1 flex-col"
                        >
                            <div className="flex items-center justify-between gap-3">
                                <TabsList className="w-fit shrink-0 rounded-[6px] border border-[#ECECEC] bg-white p-[3px] shadow-none">
                                    {SUBJECT_TABS.map((tab) => (
                                        <TabsTrigger
                                            key={tab.value}
                                            value={tab.value}
                                            className="min-w-0 rounded-[4px] px-3 py-0.5 text-[14px] font-normal leading-[22px] text-[#818181] shadow-none data-[state=active]:bg-[rgb(var(--brand-500)/0.15)] data-[state=active]:font-medium data-[state=active]:text-blue-500 data-[state=active]:shadow-none"
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
                                        setGrantIncludeChildren(true);
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
                                    resourceType={CHANNEL_RESOURCE_TYPE}
                                    resourceId={channel.id}
                                    refreshKey={refreshKey}
                                    fixedSubjectType={currentSubjectType}
                                    prefetchedGrantableModels={grantableModels}
                                    prefetchedGrantableModelsLoaded={grantableModelsLoaded}
                                    skipGrantableModelsRequest
                                    permissionApi={channelPermissionApi}
                                    onChanged={() => handlePermissionChanged()}
                                />
                            </TabsContent>
                        </Tabs>
                    </div>
                </DialogContent>
            </Dialog>

            <Dialog open={grantDialogOpen} onOpenChange={setGrantDialogOpen}>
                <DialogContent className="!flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-5 max-[768px]:fixed max-[768px]:inset-0 max-[768px]:h-[100dvh] max-[768px]:max-h-[100dvh] max-[768px]:w-full max-[768px]:max-w-none max-[768px]:translate-x-0 max-[768px]:translate-y-0 max-[768px]:rounded-none max-[768px]:p-4">
                    <DialogHeader className="shrink-0 text-left">
                        <DialogTitle className="text-left">
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
                                                ? "bg-[rgb(var(--brand-500)/0.15)] font-medium text-blue-500"
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
                                        className="border-[#D9D9D9] data-[state=checked]:border-primary data-[state=indeterminate]:border-primary"
                                        checked={grantIncludeChildren}
                                        onCheckedChange={(value) => setGrantIncludeChildren(value === true)}
                                    />
                                    {localize("com_permission.include_children")}
                                </label>
                            )}
                        </div>

                        <div className="mt-3 min-h-0 flex-1 overflow-hidden">
                            <PermissionGrantTab
                                resourceType={CHANNEL_RESOURCE_TYPE}
                                resourceId={channel.id}
                                onSuccess={handleGrantSuccess}
                                prefetchedGrantableModels={grantableModels}
                                prefetchedGrantableModelsLoaded={grantableModelsLoaded}
                                skipGrantableModelsRequest
                                fixedSubjectType={grantSubjectType}
                                includeChildren={grantIncludeChildren}
                                onIncludeChildrenChange={setGrantIncludeChildren}
                                hideDepartmentIncludeChildrenControl
                                permissionApi={channelPermissionApi}
                            />
                        </div>
                    </div>
                </DialogContent>
            </Dialog>
        </>
    );
}
