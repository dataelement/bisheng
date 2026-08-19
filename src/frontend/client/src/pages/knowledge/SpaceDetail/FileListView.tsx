import { useState } from "react";

import { FileType, SpaceRole, updateFileEncoding, type KnowledgeFile } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useLocalize, useScrollRevealRef } from "~/hooks";
import { useGetBsConfig } from "~/hooks/queries/endpoints/queries";
import { useToastContext } from "~/Providers";
import { useKnowledgeMoveDrag } from "../hooks/useKnowledgeMoveDrag";
import { EditEncodingModal } from "./EditEncodingModal";
import { FileListRow } from "./FileListRow";

/**
 * Desktop list view — the scroll container plus its rows (Figma 13198:75843).
 *
 * Replaces the former column table (`FileTable`). It owns only what the list as
 * a whole needs: the scroll container, the same-space drag-move wiring, and the
 * Shougang encoding editor that the meta line links to. Everything per-row
 * lives in `FileListRow`.
 */
interface FileListViewProps {
    files: KnowledgeFile[];
    onEnsureFilePermissions?: (file: KnowledgeFile) => void;
    selectedFiles: Set<string>;
    handleSelectFile: (id: string, selected: boolean) => void;
    isAdmin: boolean;
    /** The current user's role within this specific space. Used to gate encoding edits. */
    currentUserRole?: SpaceRole | null;
    onDownload: (id: string) => void;
    onEditTags: (id: string) => void;
    onRename: (id: string, newName: string) => void;
    onDelete: (id: string) => void;
    onRetry: (id: string) => void;
    onNavigateFolder: (id: string) => void;
    onPreview?: (id: string) => void;
    onValidateName: (name: string, isFolder: boolean, fileId: string, isCreating: boolean) => string | null;
    onCancelCreate?: () => void;
    permissionEntryIds?: Set<string>;
    renameEntryIds?: Set<string>;
    deleteEntryIds?: Set<string>;
    downloadEntryIds?: Set<string>;
    onManagePermission?: (id: string) => void;
    /** F034: open the move dialog for a file/folder. Shown when provided. */
    onMove?: (file: KnowledgeFile) => void;
    /** F034: move permission for files / folders (move_file / move_folder). A
     *  role may grant one without the other, so they're probed separately. */
    canMoveFile?: boolean;
    canMoveFolder?: boolean;
    /** F034 drag-move: drop dragged items into a same-space folder. */
    onMoveToFolder?: (folderId: string, items: KnowledgeFile[], folderName: string) => void;
    versionManagementEnabled?: boolean;
    onOpenVersionManagement?: (file: KnowledgeFile) => void;
    onOpenVersionHistory?: (file: KnowledgeFile) => void;
    canManageMembers?: boolean;
    /** Tag IDs hit by the active search; matching tags are highlighted in TagGroup. */
    highlightedTagIds?: number[];
    /** Keyword hit by the active search; matching substring in the file name is highlighted. */
    highlightKeyword?: string;
    onScroll?: React.UIEventHandler<HTMLDivElement>;
    /** Extra spacing reserved below the last row (e.g. to clear a floating bottom dock). */
    bottomSpacing?: number;
    onOpenApprovalDetail?: (requestId: number) => void;
    onPreviewPendingUpload?: (requestId: number) => void;
    onDecidePendingUpload?: (requestId: number, action: "approve" | "reject") => void;
    onWithdrawPendingUpload?: (requestId: number) => void;
    pendingUploadDeciding?: boolean;
    currentUserId?: string | number;
}

export function FileListView({
    files,
    onEnsureFilePermissions,
    selectedFiles,
    handleSelectFile,
    isAdmin,
    currentUserRole,
    onDownload,
    onEditTags,
    onRename,
    onDelete,
    onRetry,
    onNavigateFolder,
    onPreview,
    onValidateName,
    onCancelCreate,
    permissionEntryIds,
    renameEntryIds,
    deleteEntryIds,
    downloadEntryIds,
    onManagePermission,
    onMove,
    canMoveFile = false,
    canMoveFolder = false,
    onMoveToFolder,
    versionManagementEnabled = false,
    onOpenVersionManagement,
    onOpenVersionHistory,
    canManageMembers = false,
    highlightedTagIds,
    highlightKeyword,
    onScroll,
    bottomSpacing = 0,
    onOpenApprovalDetail,
    onPreviewPendingUpload,
    onDecidePendingUpload,
    onWithdrawPendingUpload,
    pendingUploadDeciding = false,
    currentUserId,
}: FileListViewProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const scrollRevealRef = useScrollRevealRef<HTMLDivElement>();

    // Shougang feature gate — encoding is shown on the row's meta line.
    const { data: bsConfig } = useGetBsConfig();
    const shougangEnabled = bsConfig?.shougang?.enabled ?? false;
    const [editingEncodingFile, setEditingEncodingFile] = useState<KnowledgeFile | null>(null);

    // Encoding edits are restricted to the space creator or space admin.
    // currentUserRole carries the user's role within this specific space (not platform-admin).
    const canEditEncoding =
        currentUserRole === SpaceRole.CREATOR || currentUserRole === SpaceRole.ADMIN;

    const handleSubmitEncoding = async (newEncoding: string) => {
        if (!editingEncodingFile) return;
        try {
            await updateFileEncoding(
                String(editingEncodingFile.spaceId),
                String(editingEncodingFile.id),
                newEncoding,
            );
            // Trigger file list reload via the existing custom event mechanism
            window.dispatchEvent(new CustomEvent("knowledge-space-files:refresh", {
                detail: { spaceId: editingEncodingFile.spaceId },
            }));
            showToast?.({
                message: localize("com_knowledge.file_encoding_update_success"),
                severity: NotificationSeverity.SUCCESS,
            });
        } catch (e) {
            showToast?.({
                message: localize("com_knowledge.file_encoding_update_failed"),
                severity: NotificationSeverity.ERROR,
            });
            throw e;
        }
    };

    // F034 same-space drag-move: rows are drag sources, folder rows are drop targets.
    const {
        enabled: dragMoveEnabled,
        dragOverFolderId,
        handleDragStart: handleRowDragStart,
        handleFolderDragOver,
        handleFolderDragLeave,
        handleFolderDrop,
    } = useKnowledgeMoveDrag({ files, selectedFiles, onMoveToFolder });

    return (
        <div className="relative flex min-h-0 min-w-0 max-w-full flex-1 flex-col overflow-hidden">
            <div
                ref={scrollRevealRef}
                onScroll={onScroll}
                className="min-h-0 max-w-full flex-1 overflow-y-auto scrollbar-on-scroll"
            >
                {files.map((file, index) => (
                    <FileListRow
                        key={file.id}
                        file={file}
                        index={index}
                        isAdmin={isAdmin}
                        onEnsureFilePermissions={onEnsureFilePermissions}
                        isSelected={selectedFiles.has(file.id)}
                        onSelect={(val) => handleSelectFile(file.id, val)}
                        onDownload={() => onDownload(file.id)}
                        onEditTags={() => onEditTags(file.id)}
                        onRename={(newName) => onRename(file.id, newName)}
                        onDelete={() => onDelete(file.id)}
                        onRetry={() => onRetry?.(file.id)}
                        onNavigateFolder={() => onNavigateFolder?.(file.id)}
                        onPreview={() => onPreview?.(file.id)}
                        onValidateName={(newName) => onValidateName?.(newName, file.type === FileType.FOLDER, file.id, !!file.isCreating)}
                        onCancelCreate={onCancelCreate}
                        onManagePermission={
                            onManagePermission && permissionEntryIds?.has(file.id)
                                ? () => onManagePermission(file.id)
                                : undefined
                        }
                        onMove={onMove ? () => onMove(file) : undefined}
                        canMove={file.type === FileType.FOLDER ? canMoveFolder : canMoveFile}
                        versionManagementEnabled={versionManagementEnabled}
                        onOpenVersionManagement={onOpenVersionManagement}
                        onOpenVersionHistory={onOpenVersionHistory}
                        canManageMembers={canManageMembers}
                        canRename={Boolean(renameEntryIds?.has(file.id))}
                        canDelete={Boolean(deleteEntryIds?.has(file.id))}
                        canDownload={Boolean(downloadEntryIds?.has(file.id))}
                        shougangEnabled={shougangEnabled}
                        canEditEncoding={canEditEncoding}
                        onEditEncoding={canEditEncoding ? setEditingEncodingFile : undefined}
                        highlightedTagIds={highlightedTagIds}
                        highlightKeyword={highlightKeyword}
                        rowDraggable={dragMoveEnabled}
                        onRowDragStart={handleRowDragStart(file)}
                        isFolderDragOver={dragOverFolderId === file.id}
                        onFolderDragOver={handleFolderDragOver(file)}
                        onFolderDragLeave={handleFolderDragLeave(file)}
                        onFolderDrop={handleFolderDrop(file)}
                        onOpenApprovalDetail={onOpenApprovalDetail}
                        onPreviewPendingUpload={onPreviewPendingUpload}
                        onDecidePendingUpload={onDecidePendingUpload}
                        onWithdrawPendingUpload={onWithdrawPendingUpload}
                        pendingUploadDeciding={pendingUploadDeciding}
                        currentUserId={currentUserId}
                    />
                ))}
                {bottomSpacing > 0 && <div style={{ height: bottomSpacing }} aria-hidden />}
            </div>

            {shougangEnabled && (
                <EditEncodingModal
                    file={editingEncodingFile}
                    open={!!editingEncodingFile}
                    onClose={() => setEditingEncodingFile(null)}
                    onSubmit={handleSubmitEncoding}
                />
            )}
        </div>
    );
}
