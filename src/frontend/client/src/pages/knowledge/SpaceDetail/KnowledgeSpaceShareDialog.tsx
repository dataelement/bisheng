import { useCallback, useEffect, useMemo, useState } from "react";
import { SpaceRole } from "~/api/knowledge";
import { KnowledgeSpaceMemberManagementPanel } from "~/components/KnowledgeSpaceMemberManagementPanel";
import { PermissionGrantTab } from "~/components/permission/PermissionGrantTab";
import { PermissionListTab } from "~/components/permission/PermissionListTab";
import {
    Button,
    Checkbox,
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
import { getGrantableRelationModels } from "~/api/permission";
import type { RelationModel, ResourceType } from "~/api/permission";

const SHARE_TAB = "share";
const MEMBERS_TAB = "members";
const PERMISSION_TAB = "permission";

interface KnowledgeSpaceShareDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    resourceType?: ResourceType;
    resourceId: string;
    resourceName: string;
    currentUserRole?: SpaceRole | null;
    showShareTab: boolean;
    showMembersTab?: boolean;
    showPermissionTab: boolean;
}

export function KnowledgeSpaceShareDialog({
    open,
    onOpenChange,
    resourceType = "knowledge_space",
    resourceId,
    resourceName,
    currentUserRole = null,
    showShareTab,
    showMembersTab = false,
    showPermissionTab,
}: KnowledgeSpaceShareDialogProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const defaultTab = showShareTab ? SHARE_TAB : showMembersTab ? MEMBERS_TAB : PERMISSION_TAB;
    const [activeTab, setActiveTab] = useState(defaultTab);
    const [refreshKey, setRefreshKey] = useState(0);
    const [copied, setCopied] = useState(false);
    const [currentSubjectType, setCurrentSubjectType] = useState<"user" | "department" | "user_group">("user");
    const [grantDialogOpen, setGrantDialogOpen] = useState(false);
    const [grantSubjectType, setGrantSubjectType] = useState<"user" | "department" | "user_group">("user");
    const [grantIncludeChildren, setGrantIncludeChildren] = useState(true);
    const [grantableModels, setGrantableModels] = useState<RelationModel[]>([]);
    const [grantableModelsLoaded, setGrantableModelsLoaded] = useState(false);

    useEffect(() => {
        if (open) {
            setActiveTab(showShareTab ? SHARE_TAB : showMembersTab ? MEMBERS_TAB : PERMISSION_TAB);
            setCopied(false);
            setCurrentSubjectType("user");
            setGrantSubjectType("user");
            setGrantIncludeChildren(true);
        }
    }, [open, showMembersTab, showShareTab]);

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
                setGrantableModels(Array.isArray(res) ? res : []);
                setGrantableModelsLoaded(true);
            })
            .catch(() => {
                setGrantableModels([]);
                setGrantableModelsLoaded(true);
            });
    }, [open, resourceId, resourceType]);

    const shareLink = useMemo(() => {
        if (typeof window === "undefined") return "";
        const base = window.location.origin + (__APP_ENV__.BASE_URL || "");
        const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;
        return `${normalizedBase}/knowledge/share/${resourceId}`;
    }, [resourceId]);

    const handleGrantSuccess = useCallback(() => {
        setRefreshKey((key) => key + 1);
        setCurrentSubjectType(grantSubjectType);
        setGrantDialogOpen(false);
        setActiveTab(PERMISSION_TAB);
    }, [grantSubjectType]);

    const handleCopyLink = useCallback(async () => {
        try {
            await copyText(shareLink);
            setCopied(true);
            showToast({
                message: localize("com_knowledge.share_link_copied"),
                status: "success",
            });
        } catch {
            showToast({
                message: localize("com_knowledge.copy_failed_retry"),
                status: "error",
            });
        }
    }, [localize, shareLink, showToast]);

    // UI simplification: this dialog now only exposes 权限管理.
    // The share/members tabs remain as props to keep caller logic untouched,
    // but they are no longer surfaced as top-level tabs here.
    const dialogTitle = `${localize("com_permission.dialog_title")} - ${resourceName}`;

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
                        onClick={() => {
                            void handleCopyLink();
                        }}
                    >
                        {copied ? localize("com_ui_duplicated") : localize("com_ui_copy_link")}
                    </Button>
                </div>
            </div>
        </div>
    );

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
                    skipGrantableModelsRequest
                />
            </TabsContent>
        </Tabs>
    );

    const memberPanel = (
        <div className="flex min-h-0 flex-1 flex-col pt-2">
            <KnowledgeSpaceMemberManagementPanel
                spaceId={resourceId}
                currentUserRole={currentUserRole}
                active={open && activeTab === MEMBERS_TAB}
            />
        </div>
    );

    return (
        <>
            <Dialog open={open} onOpenChange={onOpenChange}>
                <DialogContent className="!flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-5 max-[768px]:fixed max-[768px]:inset-0 max-[768px]:h-[100dvh] max-[768px]:max-h-[100dvh] max-[768px]:w-full max-[768px]:max-w-none max-[768px]:translate-x-0 max-[768px]:translate-y-0 max-[768px]:rounded-none max-[768px]:p-4">
                    <DialogHeader className="shrink-0">
                        <DialogTitle>{dialogTitle}</DialogTitle>
                    </DialogHeader>

                    <div className="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden">
                        {permissionPanel}
                    </div>
                </DialogContent>
            </Dialog>

            <Dialog open={grantDialogOpen} onOpenChange={setGrantDialogOpen}>
                <DialogContent className="!flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden p-5 max-[768px]:fixed max-[768px]:inset-0 max-[768px]:h-[100dvh] max-[768px]:max-h-[100dvh] max-[768px]:w-full max-[768px]:max-w-none max-[768px]:translate-x-0 max-[768px]:translate-y-0 max-[768px]:rounded-none max-[768px]:p-4">
                    <DialogHeader className="shrink-0">
                        <DialogTitle>
                            {localize("com_permission.tab_grant")} - {resourceName}
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
                                resourceType={resourceType}
                                resourceId={resourceId}
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
