import { useKnowledgeBatch } from "../hooks/useKnowledgeBatch";
import type { BatchResult } from "~/api/knowledgeBatch";
import { useKnowledgeDeletion } from "../hooks/useKnowledgeDeletion";
import type { UseKnowledgeFileActionsOptions } from "./knowledgeSpaceTypes";
import { FileType, type KnowledgeFile, getFileDownloadApi } from "~/api/knowledge";
import { useKnowledgeMove } from "../hooks/useKnowledgeMove";
import { dispatchKnowledgeSpaceFilesRefresh } from "../hooks/useFileManager";
import { isKnowledgeItemUploading, triggerUrlDownload } from "../knowledgeUtils";
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
  deleteEntryIds,
  downloadEntryIds,
  showToast,
  confirm,
  selectedList,
  canBatchDelete,
  canDeleteSpace,
  deletionScopeKey,
  space,
  onDeleteFile,
  onEditTags,
}: UseKnowledgeFileActionsOptions) {
  const batch = useKnowledgeBatch(JSON.stringify([space.id, deletionScopeKey]));
  const runOrdinaryBatch = async (operation: "download" | "retry", items: typeof selectedList) => {
    const result = await batch.open({
      spaceId: Number(space.id),
      operation,
      items: items.map((file) => ({
        id: Number(file.id),
        type: file.type === FileType.FOLDER ? "folder" : "file",
        name: file.name,
      })),
    });
    if (result && operation === "retry") {
      const accepted = new Set(
        result.items
          .filter((item) => ["succeeded", "accepted", "running"].includes(item.state))
          .map((item) => String(item.id)),
      );
      setSelectedFiles((old) => new Set([...old].filter((id) => !accepted.has(id))));
      onDeleteFile("");
      dispatchKnowledgeSpaceFilesRefresh(space.id);
    }
    return result;
  };
  const handleBatchDownload = async () => {
    await runOrdinaryBatch("download", selectedList);
  };

  const handleBatchTag = () => {
    setIsBatchTagging(true);
  };

  // F034: move selected files/folders (same-space or cross-space) via MoveToDialog,
  // plus drag-to-folder move (dropMoveToFolder wired into the table/card drag sources).
  const {
    moveProgress,
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
    // The server classifies concrete source move actions; source upload is unrelated.
    const permitted = movable;
    const denied: KnowledgeFile[] = [];
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
        if (file) await runOrdinaryBatch("download", [file]);
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
    const fileName = explicitFileName || file?.name || localize("com_knowledge.unknown_file");
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

  const deletion = useKnowledgeDeletion(JSON.stringify([space.id, deletionScopeKey]));
  const deleteItems = async (items: typeof selectedList) => {
    const ok = await deletion.open({
      spaceId: Number(space.id),
      kind: "files",
      items: items.map((file) => ({
        id: Number(file.id),
        type: file.type === FileType.FOLDER ? "folder" : "file",
      })),
    });
    if (ok) {
      setSelectedFiles(new Set());
      onDeleteFile("");
      dispatchKnowledgeSpaceFilesRefresh(space.id);
      void queryClient.invalidateQueries({ queryKey: ["file-versions"] });
      showToast({ message: localize("com_knowledge.deletion.success"), status: "success" });
    }
  };
  const handleBatchDelete = async () => {
    if (!canBatchDelete || !selectedList.length) return;
    await deleteItems(selectedList);
  };
  const handleDelete = async (fileId: string) => {
    const file = displayFiles.find((file) => file.id === fileId);
    if (file && deleteEntryIds.has(fileId)) await deleteItems([file]);
  };
  const handleClearSpace = async () => {
    if (!canDeleteSpace) return;
    if (await deletion.open({ spaceId: Number(space.id), kind: "clear" })) {
      setSelectedFiles(new Set());
      onDeleteFile("");
      dispatchKnowledgeSpaceFilesRefresh(space.id);
      void queryClient.invalidateQueries({ queryKey: ["file-versions"] });
      showToast({ message: localize("com_knowledge.deletion.success"), status: "success" });
    }
  };
  const handleReferences = () => {
    if (selectedList.length && canBatchDelete)
      void deletion.open(
        {
          spaceId: Number(space.id),
          kind: "files",
          items: selectedList.map((file) => ({
            id: Number(file.id),
            type: file.type === FileType.FOLDER ? "folder" : "file",
          })),
        },
        true,
      );
    else if (!selectedList.length && canDeleteSpace)
      void deletion.open({ spaceId: Number(space.id), kind: "delete" }, true);
  };

  const handleBatchRetry = async () => {
    await runOrdinaryBatch("retry", selectedList);
  };
  const handleSingleRetry = async (fileId: string) => {
    const file = displayFiles.find((file) => file.id === fileId);
    if (file) await runOrdinaryBatch("retry", [file]);
  };
  const handleBatchTagsSaved = (result: BatchResult) => {
    const changed = new Set(
      result.items.filter((item) => item.state === "succeeded").map((item) => String(item.id)),
    );
    setSelectedFiles((old) => new Set([...old].filter((id) => !changed.has(id))));
    setEditingTagsFileId(null);
    setIsBatchTagging(false);
    onEditTags("");
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
    batch,
    handleBatchTagsSaved,
    deletion,
    handleClearSpace,
    handleReferences,
    handleBatchDownload,
    handleBatchTag,
    moveProgress,
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
