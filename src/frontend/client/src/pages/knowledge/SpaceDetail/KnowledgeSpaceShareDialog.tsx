import { useCallback, useEffect, useMemo, useState } from "react";
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
import { getGrantableRelationModels } from "~/api/permission";
import type { RelationModel, ResourceType } from "~/api/permission";

interface KnowledgeSpaceShareDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    resourceType?: ResourceType;
    resourceId: string;
    resourceName: string;
    /**
     * F033: department knowledge spaces authorize only within the bound
     * department subtree and forbid the user-group dimension. When true, the
     * user-group tab is hidden in both the permission list and the grant dialog.
     * Backend enforces the same restriction regardless of this flag.
     */
    isDepartmentSpace?: boolean;
}

export function KnowledgeSpaceShareDialog({
    open,
    onOpenChange,
    resourceType = "knowledge_space",
    resourceId,
    resourceName,
    isDepartmentSpace = false,
}: KnowledgeSpaceShareDialogProps) {
    const localize = useLocalize();
    const [refreshKey, setRefreshKey] = useState(0);
    const [currentSubjectType, setCurrentSubjectType] = useState<"user" | "department" | "user_group">("user");
    const [grantDialogOpen, setGrantDialogOpen] = useState(false);
    const [grantSubjectType, setGrantSubjectType] = useState<"user" | "department" | "user_group">("user");
    const [grantIncludeChildren, setGrantIncludeChildren] = useState(true);
    const [grantableModels, setGrantableModels] = useState<RelationModel[]>([]);
    const [grantableModelsLoaded, setGrantableModelsLoaded] = useState(false);
    const [useDefaultModels, setUseDefaultModels] = useState(false);

    useEffect(() => {
        if (open) {
            setCurrentSubjectType("user");
            setGrantSubjectType("user");
            setGrantIncludeChildren(true);
        }
    }, [open]);

    useEffect(() => {
        if (grantSubjectType !== "department" && grantIncludeChildren !== true) {
            setGrantIncludeChildren(true);
        }
    }, [grantIncludeChildren, grantSubjectType]);

    useEffect(() => {
        if (!open) return;

        setGrantableModelsLoaded(false);
        getGrantableRelationModels(resourceType, resourceId)
            .then((res) => {
                setUseDefaultModels(false);
                setGrantableModels(Array.isArray(res) ? res : []);
                setGrantableModelsLoaded(true);
            })
            .catch(() => {
                setUseDefaultModels(false);
                setGrantableModels([]);
                setGrantableModelsLoaded(true);
            });
    }, [open, resourceId, resourceType]);

    const handleGrantSuccess = useCallback(() => {
        setRefreshKey((key) => key + 1);
        setCurrentSubjectType(grantSubjectType);
        setGrantDialogOpen(false);
    }, [grantSubjectType]);

    const dialogTitle = `${localize("com_permission.dialog_title")} - ${resourceName}`;

    // F033: department spaces drop the user-group dimension. The list view and
    // the grant dialog share this array, so both lose the tab at once.
    const SUBJECT_TABS = useMemo<Array<{
        value: "user" | "department" | "user_group";
        labelKey: string;
    }>>(() => {
        const tabs = [
            { value: "user" as const, labelKey: "com_permission.subject_user" },
            { value: "department" as const, labelKey: "com_permission.subject_department" },
            { value: "user_group" as const, labelKey: "com_permission.subject_user_group" },
        ];
        return isDepartmentSpace ? tabs.filter((tab) => tab.value !== "user_group") : tabs;
    }, [isDepartmentSpace]);

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
                    resourceType={resourceType}
                    resourceId={resourceId}
                    refreshKey={refreshKey}
                    fixedSubjectType={currentSubjectType}
                    prefetchedGrantableModels={grantableModels}
                    prefetchedGrantableModelsLoaded={grantableModelsLoaded}
                    prefetchedUseDefaultModels={useDefaultModels}
                    skipGrantableModelsRequest
                />
            </TabsContent>
        </Tabs>
    );

    return (
        <>
            <Dialog open={open} onOpenChange={onOpenChange}>
                <DialogContent className="!flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-5 max-[768px]:fixed max-[768px]:inset-0 max-[768px]:h-[100dvh] max-[768px]:max-h-[100dvh] max-[768px]:w-full max-[768px]:max-w-none max-[768px]:translate-x-0 max-[768px]:translate-y-0 max-[768px]:rounded-none max-[768px]:p-4">
                    <DialogHeader className="shrink-0 text-left">
                        <DialogTitle className="text-left">{dialogTitle}</DialogTitle>
                    </DialogHeader>

                    <div className="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden">
                        {permissionPanel}
                    </div>
                </DialogContent>
            </Dialog>

            <Dialog open={grantDialogOpen} onOpenChange={setGrantDialogOpen}>
                <DialogContent className="!flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-5 max-[768px]:fixed max-[768px]:inset-0 max-[768px]:h-[100dvh] max-[768px]:max-h-[100dvh] max-[768px]:w-full max-[768px]:max-w-none max-[768px]:translate-x-0 max-[768px]:translate-y-0 max-[768px]:rounded-none max-[768px]:p-4">
                    <DialogHeader className="shrink-0 text-left">
                        <DialogTitle className="text-left">
                            {localize("com_permission.tab_grant")} - {resourceName}
                        </DialogTitle>
                    </DialogHeader>

                    <div className="user-manger mt-4 flex min-h-0 flex-1 flex-col overflow-hidden">
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
                                resourceType={resourceType}
                                resourceId={resourceId}
                                onSuccess={handleGrantSuccess}
                                prefetchedGrantableModels={grantableModels}
                                prefetchedGrantableModelsLoaded={grantableModelsLoaded}
                                prefetchedUseDefaultModels={useDefaultModels}
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
