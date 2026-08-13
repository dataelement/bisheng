import { Outlined } from "bisheng-icons";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
    INCLUDE_CHILDREN_CHECKBOX_CLASS,
    INCLUDE_CHILDREN_LABEL_CLASS,
    PERMISSION_DIALOG_CONTENT_CLASS,
    SUBJECT_TAB_BUTTON_ACTIVE_CLASS,
    SUBJECT_TAB_BUTTON_CLASS,
    SUBJECT_TAB_BUTTON_INACTIVE_CLASS,
    SUBJECT_TAB_LIST_CLASS,
    SUBJECT_TAB_TRIGGER_CLASS,
} from "~/components/permission/permissionDialogStyles";
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
import { getFileTypeIcon } from "~/components/ui/icon/File/FileIcon";
import { useLocalize } from "~/hooks";
import { useRecoilValue } from "recoil";
import store from "~/store";
import { getGrantableRelationModels } from "~/api/permission";
import type { RelationModel, ResourceType } from "~/api/permission";

/**
 * The resource name sits here instead of in the dialog title: file names can run
 * past 100 characters, and appended to the title they wrapped under the close
 * button. One truncated line keeps the header height fixed; the native tooltip
 * still exposes the full name. Icon + name, no container fill — same shape as
 * the uploaded-file rows in chat.
 */
function ResourceContextBar({ name, resourceType }: { name: string; resourceType: ResourceType }) {
    const Icon =
        resourceType === "folder"
            ? Outlined.FolderClose
            : resourceType === "knowledge_space" || resourceType === "knowledge_library"
                ? Outlined.Book
                : getFileTypeIcon(name);

    return (
        <div className="mb-3 flex shrink-0 items-center gap-1.5 text-text-2" title={name}>
            <Icon size={14} className="shrink-0 text-text-3" />
            <span className="truncate text-body-sm">{name}</span>
        </div>
    );
}

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
    const currentUser = useRecoilValue(store.user);
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
                <TabsList className={SUBJECT_TAB_LIST_CLASS}>
                    {SUBJECT_TABS.map((tab) => (
                        <TabsTrigger
                            key={tab.value}
                            value={tab.value}
                            className={SUBJECT_TAB_TRIGGER_CLASS}
                        >
                            {localize(tab.labelKey)}
                        </TabsTrigger>
                    ))}
                </TabsList>

                <Button
                    type="button"
                    className="h-8 shrink-0 rounded-md px-3 text-[14px] leading-[22px]"
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
                    currentUserId={currentUser?.id}
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
                <DialogContent className={PERMISSION_DIALOG_CONTENT_CLASS}>
                    <DialogHeader className="shrink-0 text-left">
                        <DialogTitle className="text-left">
                            {localize("com_permission.dialog_title")}
                        </DialogTitle>
                    </DialogHeader>

                    <div className="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden">
                        <ResourceContextBar name={resourceName} resourceType={resourceType} />
                        {permissionPanel}
                    </div>
                </DialogContent>
            </Dialog>

            <Dialog open={grantDialogOpen} onOpenChange={setGrantDialogOpen}>
                <DialogContent className={PERMISSION_DIALOG_CONTENT_CLASS}>
                    <DialogHeader className="shrink-0 text-left">
                        <DialogTitle className="text-left">
                            {localize("com_permission.tab_grant")}
                        </DialogTitle>
                    </DialogHeader>

                    <div className="user-manger mt-4 flex min-h-0 flex-1 flex-col overflow-hidden">
                        <ResourceContextBar name={resourceName} resourceType={resourceType} />
                        <div className="flex items-center gap-3">
                            <div className={`inline-flex items-center justify-center ${SUBJECT_TAB_LIST_CLASS}`}>
                                {SUBJECT_TABS.map((tab) => (
                                    <button
                                        key={tab.value}
                                        type="button"
                                        className={[
                                            SUBJECT_TAB_BUTTON_CLASS,
                                            grantSubjectType === tab.value
                                                ? SUBJECT_TAB_BUTTON_ACTIVE_CLASS
                                                : SUBJECT_TAB_BUTTON_INACTIVE_CLASS,
                                        ].join(" ")}
                                        onClick={() => setGrantSubjectType(tab.value)}
                                    >
                                        {localize(tab.labelKey)}
                                    </button>
                                ))}
                            </div>

                            {grantSubjectType === "department" && (
                                <label className={INCLUDE_CHILDREN_LABEL_CLASS}>
                                    <Checkbox
                                        className={INCLUDE_CHILDREN_CHECKBOX_CLASS}
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
