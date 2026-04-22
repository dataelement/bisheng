import { useCallback, useEffect, useMemo, useState } from "react";
import { PermissionGrantTab } from "~/components/permission/PermissionGrantTab";
import { PermissionListTab } from "~/components/permission/PermissionListTab";
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
const PERMISSION_TAB = "permission";

interface KnowledgeSpaceShareDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    resourceId: string;
    resourceName: string;
    showShareTab: boolean;
    showPermissionTab: boolean;
}

export function KnowledgeSpaceShareDialog({
    open,
    onOpenChange,
    resourceId,
    resourceName,
    showShareTab,
    showPermissionTab,
}: KnowledgeSpaceShareDialogProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const defaultTab = showShareTab ? SHARE_TAB : PERMISSION_TAB;
    const [activeTab, setActiveTab] = useState(defaultTab);
    const [refreshKey, setRefreshKey] = useState(0);
    const [copied, setCopied] = useState(false);

    useEffect(() => {
        if (open) {
            setActiveTab(showShareTab ? SHARE_TAB : PERMISSION_TAB);
            setCopied(false);
        }
    }, [open, showShareTab]);

    const shareLink = useMemo(() => {
        if (typeof window === "undefined") return "";
        const base = window.location.origin + (__APP_ENV__.BASE_URL || "");
        const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;
        return `${normalizedBase}/knowledge/share/${resourceId}`;
    }, [resourceId]);

    const handleGrantSuccess = useCallback(() => {
        setRefreshKey((key) => key + 1);
        setActiveTab(PERMISSION_TAB);
    }, []);

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

    const dialogTitle = `${
        showShareTab
            ? localize("com_knowledge.share")
            : localize("com_permission.dialog_title")
    } - ${resourceName}`;
    const hasMultipleTabs = showShareTab && showPermissionTab;

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
                    resourceType="knowledge_space"
                    resourceId={resourceId}
                    refreshKey={refreshKey}
                />
            </TabsContent>
            <TabsContent value="grant" className="p-0">
                <PermissionGrantTab
                    resourceType="knowledge_space"
                    resourceId={resourceId}
                    onSuccess={handleGrantSuccess}
                />
            </TabsContent>
        </>
    );

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[680px]">
                <DialogHeader>
                    <DialogTitle>{dialogTitle}</DialogTitle>
                </DialogHeader>

                {hasMultipleTabs ? (
                    <Tabs value={activeTab} onValueChange={setActiveTab}>
                        <TabsList className="bg-surface-primary-alt p-1">
                            <TabsTrigger value={SHARE_TAB}>
                                {localize("com_knowledge.share")}
                            </TabsTrigger>
                            <TabsTrigger value={PERMISSION_TAB}>
                                {localize("com_permission.manage_permission")}
                            </TabsTrigger>
                        </TabsList>
                        <TabsContent value={SHARE_TAB} className="p-0">
                            {sharePanel}
                        </TabsContent>
                        <TabsContent value={PERMISSION_TAB} className="p-0">
                            <Tabs defaultValue="list">{permissionPanel}</Tabs>
                        </TabsContent>
                    </Tabs>
                ) : showShareTab ? (
                    sharePanel
                ) : (
                    <Tabs defaultValue="list">{permissionPanel}</Tabs>
                )}
            </DialogContent>
        </Dialog>
    );
}
