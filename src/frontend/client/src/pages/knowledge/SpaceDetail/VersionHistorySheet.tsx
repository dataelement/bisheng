import { showApiError } from "~/api/request";
import { Button as RetryButton } from "@bisheng/ui";
import {
  VersionHistoryAction,
  VersionHistoryStatusBadge,
  VersionHistorySummary,
  VersionHistoryTable,
  versionDialogStyles as styles,
} from "@bisheng/knowledge";
import { useQueryClient, useQuery, useMutation } from "@tanstack/react-query";
import { CheckCircle, Download, Eye, Loader2, Trash2, X } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "~/components/ui/Dialog";

import { Button } from "~/components/ui/Button";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import { useConfirm } from "~/Providers";
import {
  FileStatus,
  FileVersionEntry,
  getFileVersionsApi,
  setPrimaryVersionApi,
  deleteFileVersionApi,
} from "~/api/knowledge";

// ─── Props ────────────────────────────────────────────────────────────────────

interface VersionHistoryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** knowledge_file_id of the current primary version; null when closed */
  fileId: number | null;
  /** Shown in the dialog header for context (falls back to API response title) */
  documentTitle?: string;
  /** User has owner/manager role on this space */
  canManage: boolean;
  onPreview?: (versionFileId: number, fileName: string) => void;
  onDownload?: (versionFileId: number, fileName: string) => void;
  onPrimaryChanged?: () => void;
  onDeleted?: () => void;
}

function numericStatusToEnum(n: number): FileStatus {
  switch (n) {
    case 1:
      return FileStatus.PROCESSING;
    case 2:
      return FileStatus.SUCCESS;
    case 3:
      return FileStatus.FAILED;
    case 4:
      return FileStatus.REBUILDING;
    case 5:
      return FileStatus.WAITING;
    case 6:
      return FileStatus.TIMEOUT;
    case 7:
      return FileStatus.VIOLATION;
    default:
      return FileStatus.WAITING;
  }
}

interface VersionTableActionsProps {
  version: FileVersionEntry;
  canManage: boolean;
  setPrimaryPending: boolean;
  deletePending: boolean;
  onPreview?: (versionFileId: number, fileName: string) => void;
  onDownload?: (versionFileId: number, fileName: string) => void;
  onSetPrimary: (versionId: number, versionNo: number) => void;
  onDelete: (versionId: number, versionNo: number) => void;
}

function VersionTableActions({
  version,
  canManage,
  setPrimaryPending,
  deletePending,
  onPreview,
  onDownload,
  onSetPrimary,
  onDelete,
}: VersionTableActionsProps) {
  const localize = useLocalize();
  const isSuccess = numericStatusToEnum(version.status ?? 0) === FileStatus.SUCCESS;
  const canSetPrimary = canManage && !version.is_primary && isSuccess;
  const canDelete = canManage && !version.is_primary;
  const anyPending = setPrimaryPending || deletePending;

  return (
    <>
      {onPreview && (
        <VersionHistoryAction
          label={localize("com_knowledge.version.history_action_preview")}
          onClick={() => onPreview(version.knowledge_file_id, version.original_file_name)}
          disabled={anyPending}
        >
          <Eye className="size-4" />
        </VersionHistoryAction>
      )}
      {onDownload && (
        <VersionHistoryAction
          label={localize("com_knowledge.version.history_action_download")}
          onClick={() => onDownload(version.knowledge_file_id, version.original_file_name)}
          disabled={anyPending}
        >
          <Download className="size-4" />
        </VersionHistoryAction>
      )}
      {canSetPrimary && (
        <VersionHistoryAction
          label={localize("com_knowledge.version.history_action_set_primary")}
          onClick={() => onSetPrimary(version.version_id, version.version_no)}
          disabled={anyPending}
          tone="primary"
        >
          <CheckCircle className="size-4" />
        </VersionHistoryAction>
      )}
      {canDelete && (
        <VersionHistoryAction
          label={localize("com_knowledge.version.history_action_delete")}
          onClick={() => onDelete(version.version_id, version.version_no)}
          disabled={anyPending}
          tone="danger"
        >
          <Trash2 className="size-4" />
        </VersionHistoryAction>
      )}
    </>
  );
}

export function VersionHistorySheet({
  open,
  onOpenChange,
  fileId,
  documentTitle,
  canManage,
  onPreview,
  onDownload,
  onPrimaryChanged,
  onDeleted,
}: VersionHistoryDialogProps): JSX.Element | null {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const confirm = useConfirm();
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["file-versions", fileId],
    queryFn: () => getFileVersionsApi(fileId!),
    onError: showApiError,
    enabled: open && fileId !== null,
  });
  const versions = data?.versions ?? [];
  const sortedVersions = [...versions].sort((a, b) => a.version_no - b.version_no);
  const headerTitle = data?.title ?? documentTitle ?? "";
  const docCode = data?.doc_code ?? null;
  const primaryVersionNo = data?.current_primary_version_no ?? null;

  const setPrimaryMutation = useMutation({
    mutationFn: (versionId: number) => setPrimaryVersionApi(versionId),
    onSuccess: () => {
      showToast({
        message: localize("com_knowledge.version.toast_set_primary_success"),
        status: "success",
      });
      queryClient.invalidateQueries({ queryKey: ["file-versions", fileId] });
      onPrimaryChanged?.();
    },
    onError: showApiError,
  });

  const deleteMutation = useMutation({
    mutationFn: (versionId: number) => deleteFileVersionApi(versionId),
    onSuccess: () => {
      showToast({
        message: localize("com_knowledge.version.toast_delete_success"),
        status: "success",
      });
      queryClient.invalidateQueries({ queryKey: ["file-versions", fileId] });
      onDeleted?.();
    },
    onError: showApiError,
  });

  const handleSetPrimary = async (versionId: number, versionNo: number) => {
    const ok = await confirm({
      title: localize("com_knowledge.version.history_confirm_set_primary_title"),
      description: localize("com_knowledge.version.history_confirm_set_primary_description", {
        version: String(versionNo),
      }),
    });
    if (!ok) return;
    setPrimaryMutation.mutate(versionId);
  };

  const handleDelete = async (versionId: number, versionNo: number) => {
    const ok = await confirm({
      title: localize("com_knowledge.version.history_confirm_delete_title"),
      description: localize("com_knowledge.version.history_confirm_delete_description", {
        version: String(versionNo),
      }),
    });
    if (!ok) return;
    deleteMutation.mutate(versionId);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={`${styles.historySize} ${styles.historyFrame} [&>button]:hidden`}>
        {/* Header */}
        <DialogHeader className={styles.historyHeader}>
          <DialogTitle className={styles.historyTitle}>
            {localize("knowledge.version.history.title", { ns: "shared" })}
          </DialogTitle>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className={styles.close}
            aria-label={localize("com_knowledge.close") || "Close"}
          >
            <X className="size-4" />
          </button>
        </DialogHeader>

        {/* Body */}
        <div className={`${styles.body} py-4`}>
          <VersionHistorySummary
            documentTitle={headerTitle}
            documentCode={docCode}
            primaryVersion={primaryVersionNo}
          />

          {/* Table */}
          {isLoading ? (
            <div className="flex h-32 items-center justify-center">
              <Loader2 className="size-6 animate-spin text-text-3" />
            </div>
          ) : error ? (
            <div role="alert" className="flex h-32 items-center justify-center gap-2">
              <span>{error instanceof Error ? error.message : localize("com_ui_error")}</span>
              <RetryButton variant="outlined" onClick={() => void refetch()}>
                {localize("com_ui_retry")}
              </RetryButton>
            </div>
          ) : sortedVersions.length === 0 ? (
            <div className="flex h-32 items-center justify-center text-sm text-text-3">—</div>
          ) : (
            <VersionHistoryTable
              rows={sortedVersions.map((version) => ({
                id: version.version_id,
                versionNumber: version.version_no,
                isPrimary: version.is_primary,
                fileName: version.original_file_name,
                fileCode: version.file_code,
                uploader: version.uploader_name,
                uploadedAt: version.upload_time,
                status: <VersionHistoryStatusBadge status={version.status ?? 0} />,
                actions: (
                  <VersionTableActions
                    version={version}
                    canManage={canManage}
                    setPrimaryPending={setPrimaryMutation.isPending}
                    deletePending={deleteMutation.isPending}
                    onPreview={onPreview}
                    onDownload={onDownload}
                    onSetPrimary={handleSetPrimary}
                    onDelete={handleDelete}
                  />
                ),
              }))}
            />
          )}
        </div>

        {/* Footer */}
        <div className={styles.footer}>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {localize("com_knowledge.version.btn_close")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
