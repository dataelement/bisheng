import type { UseKnowledgeFileActionsOptions } from "./knowledgeSpaceTypes";
import {
  FileType,
  batchDownloadApi,
  batchRetryApi,
  getFileDownloadApi,
} from "~/api/knowledge";
import { useKnowledgeMove } from "../hooks/useKnowledgeMove";
import { dispatchKnowledgeSpaceFilesRefresh } from "../hooks/useFileManager";
import {
  isKnowledgeItemRetryable,
  isKnowledgeItemUploading,
  triggerUrlDownload,
} from "../knowledgeUtils";
import { getFullWidthLength } from "~/utils";
export function useKnowledgeFileActions({
  localize,
  displayFiles,
  selectedFiles,
  setSelectedFiles,
  editingTagsFileId,
  setEditingTagsFileId,
  setIsBatchTagging,
  queryClient,
  canMoveFile,
  deleteEntryIds,
  downloadEntryIds,
  showToast,
  confirm,
  selectedList,
  canBatchDelete,
  space,
  onDeleteFile,
  onBatchDeleteFiles,
  onEditTags,
}: UseKnowledgeFileActionsOptions) {
  const handleBatchDownload = async () => {
    const selectedList = displayFiles.filter((f) => selectedFiles.has(f.id));
    const canDownloadSelected =
      selectedList.length > 0 &&
      selectedList.every((file) => downloadEntryIds.has(file.id));
    if (!canDownloadSelected) {
      showToast({
        message: localize("com_knowledge.download_failed"),
        status: "warning",
      });
      return;
    }
    const fileIds = selectedList
      .filter((f) => f.type !== FileType.FOLDER)
      .map((f) => Number(f.id));
    const folderIds = selectedList
      .filter((f) => f.type === FileType.FOLDER)
      .map((f) => Number(f.id));
    try {
      const url = await batchDownloadApi(space.id, {
        file_ids: fileIds.length ? fileIds : undefined,
        folder_ids: folderIds.length ? folderIds : undefined,
      });
      if (!url) {
        showToast({
          message: localize("com_knowledge.get_download_link_failed"),
          status: "warning",
        });
        return;
      }
      const now = new Date();
      const dateStr =
        String(now.getFullYear()) +
        String(now.getMonth() + 1).padStart(2, "0") +
        String(now.getDate()).padStart(2, "0");
      const randomStr = Math.random()
        .toString(36)
        .substring(2, 8)
        .toUpperCase();
      triggerUrlDownload(url, `${dateStr}_${randomStr}.zip`);
    } catch {
      showToast({
        message: localize("com_knowledge.download_failed"),
        status: "warning",
      });
    }
  };

  const handleBatchTag = () => {
    setIsBatchTagging(true);
  };

  // F034: move selected files/folders (same-space or cross-space) via MoveToDialog,
  // plus drag-to-folder move (dropMoveToFolder wired into the table/card drag sources).
  const {
    moveDialogOpen,
    setMoveDialogOpen,
    openMove,
    requestBatchMove,
    handleMoveConfirm,
    dropMoveToFolder,
  } = useKnowledgeMove({
    spaceId: space.id,
    onMoved: () => {
      setSelectedFiles(new Set());
      queryClient.invalidateQueries({ queryKey: ["file-versions"] });
      onDeleteFile(""); // generic "file list changed, reload" signal (same as batch delete).
      // Refresh the left sidebar folder tree(s). No spaceId → global refresh,
      // so a cross-space move updates both the source and target trees.
      dispatchKnowledgeSpaceFilesRefresh();
    },
  });
  const handleBatchMove = () => {
    const selected = displayFiles.filter((f) => selectedFiles.has(f.id));
    // Uploading placeholders have no backend id yet → can't be moved. Surface
    // them in the partial-move dialog so the user can still move the rest.
    const uploading = selected.filter((f) => isKnowledgeItemUploading(f));
    const movable = selected.filter((f) => !isKnowledgeItemUploading(f));
    if (!movable.length && !uploading.length) return;
    // Frontend pre-flight (space-level move permission, simple block): if the user
    // can't move in this space, every movable item is denied → block dialog before
    // the picker. The backend re-validates per item on the move.
    const permitted = canMoveFile ? movable : [];
    const denied = canMoveFile ? [] : movable;
    requestBatchMove(permitted, denied, uploading);
  };

  const handleSingleDownload = async (fileId: string) => {
    const file = displayFiles.find((f) => f.id === fileId);
    const isFolder = file?.type === FileType.FOLDER;
    if (!downloadEntryIds.has(fileId)) {
      showToast({
        message: localize("com_knowledge.download_failed"),
        status: "warning",
      });
      return;
    }
    try {
      if (isFolder) {
        // Folders must use batch download (returns zip)
        const url = await batchDownloadApi(space.id, {
          folder_ids: [Number(fileId)],
        });
        if (!url) {
          showToast({
            message: localize("com_knowledge.get_download_link_failed"),
            status: "warning",
          });
          return;
        }
        triggerUrlDownload(url, `${file?.name ?? "folder"}.zip`);
      } else {
        // Single file: use preview_url for channel files, original_url for others
        const downloadData = await getFileDownloadApi(String(space.id), fileId);
        const downloadUrl =
          file?.fileSource === "channel"
            ? downloadData.preview_url || downloadData.original_url
            : downloadData.original_url;
        if (!downloadUrl) {
          showToast({
            message: localize("com_knowledge.get_download_link_failed"),
            status: "warning",
          });
          return;
        }
        triggerUrlDownload(downloadUrl, file?.name);
      }
    } catch {
      showToast({
        message: localize("com_knowledge.download_failed"),
        status: "warning",
      });
    }
  };

  const handlePreviewFile = (fileId: string, explicitFileName?: string) => {
    const file = displayFiles.find((f) => f.id === fileId);
    // Version files aren't in displayFiles, so accept an explicit name for them.
    const fileName =
      explicitFileName || file?.name || localize("com_knowledge.unknown_file");
    // Use extension from filename for preview viewer dispatch instead of API type field
    const ext = fileName.split(".").pop()?.toLowerCase() || "";
    const url = `${__APP_ENV__.BASE_URL}/knowledge/file/${fileId}?name=${encodeURIComponent(fileName)}&type=${encodeURIComponent(ext)}&spaceId=${encodeURIComponent(space.id)}`;
    window.open(url, "_blank");
  };

  const handleOpenEditTags = (fileId: string) => {
    setEditingTagsFileId(fileId);
    setIsBatchTagging(false);
  };

  const handleCloseEditTags = async (safeClose: boolean) => {
    if (safeClose) {
      setEditingTagsFileId(null);
      setIsBatchTagging(false);
      return;
    }
    const confirmed = await confirm({
      description: localize("com_knowledge.unsaved_tags_confirm_close"),
      cancelText: localize("com_knowledge.cancel"),
      confirmText: localize("com_knowledge.confirm_close"),
    });
    if (confirmed) {
      setEditingTagsFileId(null);
      setIsBatchTagging(false);
    }
  };

  // Called after tags are saved successfully — refresh file list
  const handleTagsSaved = () => {
    setEditingTagsFileId(null);
    setIsBatchTagging(false);
    setSelectedFiles(new Set());
    // Trigger a refresh of the file list from parent
    onEditTags(editingTagsFileId || "");
  };

  const handleBatchDelete = async () => {
    const confirmed = await confirm({
      description: `${localize("com_knowledge.confirm_delete_files_count", { 0: selectedFiles.size })}${localize("com_knowledge.delete_irreversible_warning")}`,
      variant: "destructive",
    });

    if (!confirmed) return;

    if (!canBatchDelete) {
      showToast({
        message: localize("com_knowledge.batch_delete_failed"),
        status: "warning",
      });
      return;
    }

    // Optimistic batch delete (handled by the parent): rows are dropped from
    // the list in place — keeps the scroll position and works regardless of
    // which page they were loaded from. The parent rolls back on API failure.
    const ids = selectedList.map((f) => f.id);
    setSelectedFiles(new Set());
    const ok = await onBatchDeleteFiles(ids);
    if (ok) {
      showToast({
        message: localize("com_knowledge.batch_delete_success"),
        status: "success",
      });
    } else {
      showToast({
        message: localize("com_knowledge.batch_delete_failed"),
        status: "warning",
      });
    }
  };

  const handleDelete = async (fileId: string) => {
    const file = displayFiles.find((f) => f.id === fileId);
    if (!file) return;

    const isFolder = file.type === FileType.FOLDER;
    if (!deleteEntryIds.has(fileId)) {
      showToast({
        message: localize("com_knowledge.delete_failed"),
        status: "warning",
      });
      return;
    }

    const confirmed = await confirm({
      description: isFolder
        ? `${localize("com_knowledge.confirm_delete_folder_name", { 0: file.name })}${localize("com_knowledge.delete_folder_permanent_warning")}`
        : `${localize("com_knowledge.confirm_delete_file")}${localize("com_knowledge.delete_irreversible_warning")}`,
      variant: "destructive",
    });

    if (confirmed) {
      onDeleteFile(fileId);
    }
  };

  const handleBatchRetry = async () => {
    // Find selected files/folders that have an abnormal status or descendant.
    const retryIds = displayFiles
      .filter((f) => selectedFiles.has(f.id) && isKnowledgeItemRetryable(f))
      .map((f) => Number(f.id));

    if (retryIds.length === 0) return;

    try {
      await batchRetryApi(space.id, retryIds);
      showToast({
        message: localize("com_knowledge.batch_retry_started"),
        status: "success",
      });
      setSelectedFiles(new Set());
      // Refresh list
      onDeleteFile("");
    } catch {
      showToast({
        message: localize("com_knowledge.batch_retry_failed"),
        status: "warning",
      });
    }
  };

  const handleSingleRetry = async (fileId: string) => {
    try {
      await batchRetryApi(space.id, [Number(fileId)]);
      showToast({
        message: localize("com_knowledge.retry_started"),
        status: "success",
      });
      // Refresh list
      onDeleteFile("");
    } catch {
      showToast({
        message: localize("com_knowledge.retry_failed"),
        status: "warning",
      });
    }
  };

  const validateFileName = (
    name: string,
    isFolder: boolean,
    currentId: string,
    isCreating: boolean,
  ) => {
    const trimmed = name.trim();
    if (!trimmed) {
      return isFolder && isCreating
        ? localize("com_knowledge.folder_name_empty")
        : localize("com_knowledge.name_empty");
    }
    if (getFullWidthLength(trimmed) > 50) {
      return localize("com_knowledge.name_max_50");
    }

    const duplicate = displayFiles.some(
      (f) =>
        f.name === trimmed &&
        f.id !== currentId &&
        (isFolder ? f.type === FileType.FOLDER : f.type !== FileType.FOLDER),
    );
    if (duplicate) {
      return isFolder
        ? localize("com_knowledge.name_duplicate_folder")
        : localize("com_knowledge.name_duplicate_file");
    }
    return null;
  };

  return {
    handleBatchDownload,
    handleBatchTag,
    moveDialogOpen,
    setMoveDialogOpen,
    openMove,
    handleMoveConfirm,
    dropMoveToFolder,
    handleBatchMove,
    handleSingleDownload,
    handlePreviewFile,
    handleOpenEditTags,
    handleCloseEditTags,
    handleTagsSaved,
    handleBatchDelete,
    handleDelete,
    handleBatchRetry,
    handleSingleRetry,
    validateFileName,
  };
}
