import { useEffect, useState, type ComponentProps } from "react";
import { ApprovalCenterDialog } from "~/components/approval/ApprovalCenterDialog";
import { NotificationsDialog } from "~/components/NotificationsDialog";
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "~/components/ui";
import {
    getShougangFilePublishSimilarCandidatesApi,
    getShougangFilePublishTargetSpacesApi,
    searchShougangFilePublishDocumentsApi,
    submitShougangFilePublishApprovalApi,
    type ApprovalCenterTab,
    type ShougangFilePublishTargetSpace,
} from "~/api/approval";
import type { KnowledgeFile, KnowledgeSpace, SpaceLevel } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { CreateKnowledgeSpaceDrawer, type CreateKnowledgeSpaceFormData } from "../../CreateKnowledgeSpaceDrawer";
import { EditTagsModal } from "../../SpaceDetail/EditTagsModal";
import { KnowledgeSpaceShareDialog } from "../../SpaceDetail/KnowledgeSpaceShareDialog";
import s from "../PortalKnowledgeWorkbench.module.css";
import { PortalAiDialog } from "./PortalAiDialog";
import { PortalUploadDialog } from "./PortalUploadDialog";

type DuplicateFile = {
    fileId: string | number;
    fileName: string;
    oldFileLevelPath?: string | null;
};

function PortalFilePublishDialog({
    open,
    activeSpace,
    file,
    onOpenChange,
}: {
    open: boolean;
    activeSpace: KnowledgeSpace | null;
    file: KnowledgeFile | null;
    onOpenChange: (open: boolean) => void;
}) {
    const { showToast } = useToastContext();
    const [targetSpaces, setTargetSpaces] = useState<ShougangFilePublishTargetSpace[]>([]);
    const [targetSpaceId, setTargetSpaceId] = useState("");
    const [reason, setReason] = useState("");
    const [loading, setLoading] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [candidates, setCandidates] = useState<any[]>([]);
    const [searchKeyword, setSearchKeyword] = useState("");
    const [searchResults, setSearchResults] = useState<any[]>([]);
    const [targetDocumentId, setTargetDocumentId] = useState<number | null>(null);

    useEffect(() => {
        if (!open) {
            setTargetSpaces([]);
            setTargetSpaceId("");
            setReason("");
            setCandidates([]);
            setSearchKeyword("");
            setSearchResults([]);
            setTargetDocumentId(null);
            return;
        }
        let cancelled = false;
        setLoading(true);
        getShougangFilePublishTargetSpacesApi()
            .then((res) => {
                if (cancelled) return;
                setTargetSpaces(res.data || []);
                const first = res.data?.[0]?.id;
                setTargetSpaceId(first !== undefined ? String(first) : "");
            })
            .catch(() => {
                if (!cancelled) showToast({ message: "加载发布目标失败", severity: NotificationSeverity.ERROR });
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [open, showToast]);

    useEffect(() => {
        if (!open || !file || !targetSpaceId) {
            setCandidates([]);
            return;
        }
        let cancelled = false;
        getShougangFilePublishSimilarCandidatesApi(file.id, targetSpaceId)
            .then((res) => {
                if (!cancelled) setCandidates(res.data || []);
            })
            .catch(() => {
                if (!cancelled) setCandidates([]);
            });
        return () => {
            cancelled = true;
        };
    }, [file?.id, open, targetSpaceId]);

    const handleSearchDocuments = async () => {
        if (!file || !targetSpaceId) return;
        try {
            const res = await searchShougangFilePublishDocumentsApi(file.id, targetSpaceId, searchKeyword);
            setSearchResults(res.data || []);
        } catch {
            showToast({ message: "搜索目标文档失败", severity: NotificationSeverity.ERROR });
        }
    };

    const handleSubmit = async () => {
        if (!activeSpace || !file || !targetSpaceId) return;
        setSubmitting(true);
        try {
            await submitShougangFilePublishApprovalApi({
                source_space_id: activeSpace.id,
                source_file_id: file.id,
                target_space_id: targetSpaceId,
                target_document_id: targetDocumentId,
                reason: reason.trim() || undefined,
            });
            showToast({ message: "已提交发布申请", severity: NotificationSeverity.SUCCESS });
            onOpenChange(false);
        } catch (error) {
            const message = error instanceof Error && error.message ? error.message : "提交发布申请失败";
            showToast({ message, severity: NotificationSeverity.ERROR });
        } finally {
            setSubmitting(false);
        }
    };

    const versionOptions = [
        ...candidates.map((item) => ({
            id: item.target_document_id ?? item.document_id,
            title: item.title,
            source: "推荐",
        })),
        ...searchResults.map((item) => ({
            id: item.document_id ?? item.target_document_id,
            title: item.title,
            source: "搜索",
        })),
    ].filter((item, index, all) => item.id && all.findIndex((one) => one.id === item.id) === index);

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className={s.publishDialog} onPointerDownOutside={(event) => event.preventDefault()}>
                <DialogHeader>
                    <DialogTitle>发布文件</DialogTitle>
                </DialogHeader>
                <div className={s.publishBody}>
                    <div className={s.publishField}>
                        <label>源文件</label>
                        <div className={s.publishReadonly}>{file?.name || "--"}</div>
                    </div>
                    <div className={s.publishField}>
                        <label>源知识库</label>
                        <div className={s.publishReadonly}>{activeSpace?.name || "--"}</div>
                    </div>
                    <div className={s.publishField}>
                        <label>发布目标知识库</label>
                        <select
                            value={targetSpaceId}
                            disabled={loading}
                            onChange={(event) => {
                                setTargetSpaceId(event.target.value);
                                setTargetDocumentId(null);
                                setSearchResults([]);
                            }}
                        >
                            <option value="">{loading ? "加载中..." : "请选择目标知识库"}</option>
                            {targetSpaces.map((space) => (
                                <option key={space.id} value={String(space.id)}>
                                    {space.name}
                                </option>
                            ))}
                        </select>
                    </div>
                    <div className={s.publishField}>
                        <label>版本管理</label>
                        <select
                            value={targetDocumentId ?? ""}
                            onChange={(event) => setTargetDocumentId(event.target.value ? Number(event.target.value) : null)}
                        >
                            <option value="">不关联新版本</option>
                            {versionOptions.map((option) => (
                                <option key={option.id} value={option.id}>
                                    {option.source}：{option.title}
                                </option>
                            ))}
                        </select>
                    </div>
                    <div className={s.publishSearchRow}>
                        <input
                            value={searchKeyword}
                            placeholder="搜索目标空间文档..."
                            onChange={(event) => setSearchKeyword(event.target.value)}
                            onKeyDown={(event) => {
                                if (event.key === "Enter") void handleSearchDocuments();
                            }}
                        />
                        <Button variant="outline" type="button" onClick={() => void handleSearchDocuments()}>
                            搜索
                        </Button>
                    </div>
                    <div className={s.publishField}>
                        <label>申请意见</label>
                        <textarea
                            value={reason}
                            rows={4}
                            placeholder="请输入发布原因..."
                            onChange={(event) => setReason(event.target.value)}
                        />
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" className="h-8" onClick={() => onOpenChange(false)}>
                        取消
                    </Button>
                    <Button className="h-8" disabled={!targetSpaceId || submitting} onClick={() => void handleSubmit()}>
                        {submitting ? "提交中..." : "提交申请"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

type PortalDialogsProps = {
    activeSpace: KnowledgeSpace | null;
    selectedFile: KnowledgeFile | null;
    documentPath: string;
    tagModalOpen: boolean;
    onTagModalOpenChange: (open: boolean) => void;
    onTagsSaved: () => void;
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
    documentPath,
    tagModalOpen,
    onTagModalOpenChange,
    onTagsSaved,
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

            {activeSpace && selectedFile ? (
                <KnowledgeSpaceShareDialog
                    open={permissionOpen}
                    onOpenChange={onPermissionOpenChange}
                    resourceType="knowledge_file"
                    resourceId={selectedFile.id}
                    resourceName={selectedFile.name}
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

            <PortalFilePublishDialog
                open={Boolean(activeSpace && publishingFile)}
                activeSpace={activeSpace}
                file={publishingFile}
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
