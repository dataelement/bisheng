import type { ComponentProps } from "react";
import { ApprovalCenterDialog } from "~/components/approval/ApprovalCenterDialog";
import { NotificationsDialog } from "~/components/NotificationsDialog";
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "~/components/ui";
import type { ApprovalCenterTab } from "~/api/approval";
import type { KnowledgeFile, KnowledgeSpace, SpaceLevel } from "~/api/knowledge";
import { CreateKnowledgeSpaceDrawer, type CreateKnowledgeSpaceFormData } from "../../CreateKnowledgeSpaceDrawer";
import { EditTagsModal } from "../../SpaceDetail/EditTagsModal";
import { FilePublishDialog } from "../../SpaceDetail/FilePublishDialog";
import { KnowledgeSpaceShareDialog } from "../../SpaceDetail/KnowledgeSpaceShareDialog";
import { useVersionManagementEnabled } from "~/hooks";
import type { ResourceType } from "~/api/permission";
import s from "../PortalKnowledgeWorkbench.module.css";
import { PortalAiDialog } from "./PortalAiDialog";
import { PortalUploadDialog } from "./PortalUploadDialog";

type DuplicateFile = {
    fileId: string | number;
    fileName: string;
    oldFileLevelPath?: string | null;
};

type PortalDialogsProps = {
    activeSpace: KnowledgeSpace | null;
    selectedFile: KnowledgeFile | null;
    permissionTarget: KnowledgeFile | null;
    documentPath: string;
    tagModalOpen: boolean;
    onTagModalOpenChange: (open: boolean) => void;
    onTagsSaved: () => void;
    permissionResourceType: ResourceType;
    permissionOpen: boolean;
    onPermissionOpenChange: (open: boolean) => void;
    approvalDialogOpen: boolean;
    approvalDialogTarget: { tab?: ApprovalCenterTab; instanceId?: number; taskId?: number };
    onApprovalDialogOpenChange: (open: boolean) => void;
    onApprovalDialogTargetChange: (target: { tab?: ApprovalCenterTab; instanceId?: number; taskId?: number }) => void;
    notificationsOpen: boolean;
    onNotificationsOpenChange: (open: boolean) => void;
    aiDialogOpen: boolean;
    onAiDialogOpenChange: (open: boolean) => void;
    publishingFile: KnowledgeFile | null;
    onPublishingFileChange: (file: KnowledgeFile | null) => void;
    spacePermissionDialogSpace: KnowledgeSpace | null;
    spacePermissionOpen: boolean;
    onSpacePermissionOpenChange: (open: boolean) => void;
    onSpacePermissionChanged: () => void | Promise<void>;
    createDrawerOpen: boolean;
    onCreateDrawerOpenChange: (open: boolean) => void;
    onConfirmCreateSpace: (form: CreateKnowledgeSpaceFormData) => Promise<boolean>;
    editingSpace: KnowledgeSpace | null;
    pendingCreateLevel: SpaceLevel;
    onViewCreatedSpace: () => void;
    onManageEditingSpaceMembers: () => void;
    uploadDialogProps: ComponentProps<typeof PortalUploadDialog>;
    duplicateFiles: DuplicateFile[];
    onDuplicateSkip: () => void;
    onDuplicateOverwrite: () => void;
};

export function PortalDialogs({
    activeSpace,
    selectedFile,
    permissionTarget,
    documentPath,
    tagModalOpen,
    onTagModalOpenChange,
    onTagsSaved,
    permissionResourceType,
    permissionOpen,
    onPermissionOpenChange,
    approvalDialogOpen,
    approvalDialogTarget,
    onApprovalDialogOpenChange,
    onApprovalDialogTargetChange,
    notificationsOpen,
    onNotificationsOpenChange,
    aiDialogOpen,
    onAiDialogOpenChange,
    publishingFile,
    onPublishingFileChange,
    spacePermissionDialogSpace,
    spacePermissionOpen,
    onSpacePermissionOpenChange,
    onSpacePermissionChanged,
    createDrawerOpen,
    onCreateDrawerOpenChange,
    onConfirmCreateSpace,
    editingSpace,
    pendingCreateLevel,
    onViewCreatedSpace,
    onManageEditingSpaceMembers,
    uploadDialogProps,
    duplicateFiles,
    onDuplicateSkip,
    onDuplicateOverwrite,
}: PortalDialogsProps) {
    const versionManagementEnabled = useVersionManagementEnabled();

    return (
        <>
            {activeSpace && selectedFile ? (
                <EditTagsModal
                    isOpen={tagModalOpen}
                    onClose={() => onTagModalOpenChange(false)}
                    onSaved={onTagsSaved}
                    spaceId={activeSpace.id}
                    fileId={selectedFile.id}
                    initialTagIds={selectedFile.tags.map((tag) => tag.id).filter((id) => id >= 0)}
                />
            ) : null}

            {activeSpace && permissionTarget ? (
                <KnowledgeSpaceShareDialog
                    open={permissionOpen}
                    onOpenChange={onPermissionOpenChange}
                    resourceType={permissionResourceType}
                    resourceId={permissionTarget.id}
                    resourceName={permissionTarget.name}
                    currentUserRole={activeSpace.role}
                    showShareTab={false}
                    showPermissionTab
                />
            ) : null}

            <PortalAiDialog
                open={aiDialogOpen}
                activeSpace={activeSpace}
                selectedFile={selectedFile}
                documentPath={documentPath}
                onOpenChange={onAiDialogOpenChange}
            />

            <NotificationsDialog
                open={notificationsOpen}
                onOpenChange={onNotificationsOpenChange}
                onOpenApprovalCenter={(target) => {
                    onNotificationsOpenChange(false);
                    onApprovalDialogTargetChange({
                        tab: target.tab,
                        instanceId: target.instanceId ?? undefined,
                        taskId: target.taskId ?? undefined,
                    });
                    onApprovalDialogOpenChange(true);
                }}
            />

            <ApprovalCenterDialog
                open={approvalDialogOpen}
                onOpenChange={onApprovalDialogOpenChange}
                target={approvalDialogTarget}
            />

            <FilePublishDialog
                open={Boolean(activeSpace && publishingFile)}
                activeSpace={activeSpace}
                file={publishingFile}
                versionManagementEnabled={versionManagementEnabled}
                onOpenChange={(open) => {
                    if (!open) onPublishingFileChange(null);
                }}
            />

            {spacePermissionDialogSpace ? (
                <KnowledgeSpaceShareDialog
                    open={spacePermissionOpen}
                    onOpenChange={onSpacePermissionOpenChange}
                    resourceId={spacePermissionDialogSpace.id}
                    resourceName={spacePermissionDialogSpace.name}
                    currentUserRole={spacePermissionDialogSpace.role}
                    spaceLevel={spacePermissionDialogSpace.spaceLevel}
                    showShareTab={false}
                    showMembersTab={false}
                    showPermissionTab
                    onPermissionChanged={onSpacePermissionChanged}
                />
            ) : null}

            <CreateKnowledgeSpaceDrawer
                open={createDrawerOpen}
                onOpenChange={onCreateDrawerOpenChange}
                onConfirm={onConfirmCreateSpace}
                mode={editingSpace ? "edit" : "create"}
                editingSpace={editingSpace}
                initialSpaceLevel={pendingCreateLevel}
                showApprovalReason
                onViewSpace={onViewCreatedSpace}
                onManageMembers={onManageEditingSpaceMembers}
            />

            <PortalUploadDialog {...uploadDialogProps} />

            <Dialog open={duplicateFiles.length > 0} onOpenChange={(open) => !open && onDuplicateSkip()}>
                <DialogContent className="sm:max-w-[460px]" onPointerDownOutside={(event) => event.preventDefault()}>
                    <DialogHeader>
                        <DialogTitle>发现重名文件</DialogTitle>
                    </DialogHeader>
                    <ul className={s.dialogList}>
                        {duplicateFiles.map((entry) => (
                            <li key={entry.fileId} className={s.dialogListItem}>
                                {entry.fileName}
                                {entry.oldFileLevelPath ? `（${entry.oldFileLevelPath}）` : ""}
                            </li>
                        ))}
                    </ul>
                    <DialogFooter>
                        <Button variant="outline" className="h-8" onClick={onDuplicateSkip}>
                            取消
                        </Button>
                        <Button className="h-8" onClick={onDuplicateOverwrite}>
                            覆盖
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    );
}
