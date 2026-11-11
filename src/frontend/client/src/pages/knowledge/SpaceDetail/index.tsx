import type { KnowledgeSpaceContentProps } from "./knowledgeSpaceTypes";
import { getKnowledgeBatchActions } from "./getKnowledgeBatchActions";
import { useKnowledgeSelectionActions } from "./useKnowledgeSelectionActions";
import { useKnowledgeSpaceHeader } from "./useKnowledgeSpaceHeader";
import { useState, useEffect } from "react";
import { useRecoilValue, useRecoilState } from "recoil";
import { knowledgeSelectedFilesState } from "../selectionStore";
import { FileStatus, FileType, SortDirection, SortType } from "~/api/knowledge";
import { useConfirm, useToastContext } from "~/Providers";
import { useKnowledgeMoveDrag } from "../hooks/useKnowledgeMoveDrag";
import {
  getAllowedExtensions,
  getFileInputAccept,
  isKnowledgeItemRetryable,
  resolveUploadSizeLimits,
} from "../knowledgeUtils";
import { bishengConfState } from "~/pages/appChat/store/atoms";
import { LoadMore } from "./LoadMore";
import { useLocalize, usePrefersMobileLayout, useScrollRevealRef } from "~/hooks";
import { useRefreshEffectiveQuota } from "~/hooks/useEffectiveQuota";
import { useStorageQuotaGuard } from "~/hooks/usePersonalStorageQuota";
import { useKnowledgeFilePermissions } from "./useKnowledgeFilePermissions";
import { useKnowledgeUploads } from "./useKnowledgeUploads";
import { useKnowledgeFileActions } from "./useKnowledgeFileActions";
import { useKnowledgeCardColumns } from "./useKnowledgeCardColumns";
import { KnowledgeSpacePresentation } from "./KnowledgeSpacePresentation";

interface KnowledgeSpacePorts {
  localize: ReturnType<typeof useLocalize>;
  showToast: ReturnType<typeof useToastContext>["showToast"];
  confirm: ReturnType<typeof useConfirm>;
}

function useKnowledgeSpaceDetail(
  {
    space,
    files,
    onLoadMore,
    hasMore,
    loading,
    loadError = false,
    loadMoreError = false,
    onSearch,
    onFilterStatus,
    onSort,
    onNavigateFolder,
    onUploadFile,
    onUploadFolder,
    onCreateFolder,
    onRenameFile,
    onDeleteFile,
    onBatchDeleteFiles,
    onEditTags,
    currentPath,
    currentFolderId,
    onDragStateChange,
    uploadingFiles = [],
    creatingFolder,
    uploadingFolder = null,
    onCancelCreateFolder,
    onGoKnowledgeSquare,
    onOpenSystemMenu,
    onToggleSpaceList,
    spaceListOpen = false,
    onEditSpace,
    onDeleteSpace,
    onLeaveSpace,
    onOpenSearch,
    searchMode = false,
    onCloseSearch,
    onSelectionActiveChange,
  }: KnowledgeSpaceContentProps,
  { localize, showToast, confirm }: KnowledgeSpacePorts,
) {
  const isH5 = usePrefersMobileLayout();
  const fileListScrollRevealRef = useScrollRevealRef<HTMLDivElement>();
  const displayFiles = [
    ...(creatingFolder ? [creatingFolder] : []),
    // In-progress folder upload: show its placeholder card (keyed to the space +
    // folder it was started in, like the file placeholders below) so it stays put
    // when the user navigates elsewhere mid-upload.
    ...(uploadingFolder &&
    String(uploadingFolder.spaceId) === String(space.id) &&
    String(uploadingFolder.parentId ?? "") === String(currentFolderId ?? "")
      ? [uploadingFolder]
      : []),
    // Uploading placeholders are keyed to the space AND folder they were
    // started in (placeholder.parentId = the folder at upload time). Filter to
    // the active space + current folder so an in-progress root upload does not
    // leak into a subfolder's list (and vice versa), and uploads in space A
    // don't show in space B after switching.
    ...uploadingFiles.filter(
      (f) =>
        String(f.spaceId) === String(space.id) &&
        String(f.parentId ?? "") === String(currentFolderId ?? ""),
    ),
    ...files,
  ];

  // Infinite scroll: trigger the next page when the scroll container nears its bottom.
  const handleListScroll = (e: React.UIEvent<HTMLDivElement>) => {
    if (!hasMore || loading) return;
    const el = e.currentTarget;
    if (el.scrollHeight - el.scrollTop - el.clientHeight <= 240) {
      onLoadMore();
    }
  };

  const [searchQuery, setSearchQuery] = useState("");
  const [searchTagIds, setSearchTagIds] = useState<number[]>([]);
  const [viewMode, setViewModeState] = useState<"card" | "list">(() => {
    if (typeof window === "undefined") return "list";
    return localStorage.getItem("knowledge-view-mode") === "card" ? "card" : "list";
  });
  const setViewMode = (mode: "card" | "list") => {
    setViewModeState(mode);
    localStorage.setItem("knowledge-view-mode", mode);
  };

  // Shared atom (not local state) so the bottom AI dock can clear the selection
  // on focus/send without prop drilling. See selectionStore.ts.
  const [selectedFiles, setSelectedFiles] = useRecoilState(knowledgeSelectedFilesState);
  const [statusFilter, setStatusFilter] = useState<FileStatus[]>([]);
  const [sortBy, setSortBy] = useState<SortType | undefined>(undefined);
  const [sortDirection, setSortDirection] = useState<SortDirection | undefined>(undefined);
  const [editingTagsFileId, setEditingTagsFileId] = useState<string | null>(null);
  const [isBatchTagging, setIsBatchTagging] = useState(false);
  const [contextMenuOpen, setContextMenuOpen] = useState(false);
  const [contextMenuPosition, setContextMenuPosition] = useState({
    x: 0,
    y: 0,
  });

  // Card view: compute columns by *container width* (not viewport width).
  // Thresholds (container width):
  // >=1296: 7, 1024-1295: 6, 768-1023: 5, 600-767: 4, 480-599: 3, 320-479: 2, <320: 1
  const cardColumns = useKnowledgeCardColumns({ displayFiles, viewMode });

  useEffect(() => {
    setSelectedFiles(new Set());
    setSearchQuery("");
    setSearchTagIds([]);
  }, [space.id]);

  const {
    isAdmin,
    ensureSpaceActions,
    canShareSpace,
    canDeleteSpace,
    canManageMembers,
    canEditSpace,
    canLeaveSpace,
    versionManagementEnabled,
    queryClient,
    spaceIdNum,
    versionMgmtFile,
    setVersionMgmtFile,
    versionHistoryFile,
    setVersionHistoryFile,
    similarDialogOpen,
    setSimilarDialogOpen,
    similarRestrictIds,
    setSimilarRestrictIds,
    handleProcessSimilar,
    handleVersionAction,
    showShareInMenu,
    handleCopyShareLink,
  } = useKnowledgeSpaceHeader({
    selectedFiles,
    space,
    onDeleteFile,
    localize,
    showToast,
  });

  const isSearching = searchQuery.trim().length > 0 || searchTagIds.length > 0;
  const [permTarget, setPermTarget] = useState<{
    id: string;
    name: string;
    type: "folder" | "knowledge_file";
  } | null>(null);
  const listBottomStatus =
    displayFiles.length > 0 ? (
      <>
        {hasMore && !loadMoreError ? (
          <LoadMore
            onLoad={onLoadMore}
            loading={loading}
            disabled={loading}
            loadingText={localize("com_list_loading_more")}
          />
        ) : null}
        {!hasMore ? (
          <div className="col-span-full flex h-10 w-full items-center justify-center text-xs text-text-4">
            {loadMoreError ? localize("com_list_load_failed") : localize("com_list_all_loaded")}
          </div>
        ) : null}
      </>
    ) : null;

  const isStorageBlocked = useStorageQuotaGuard();
  const refreshQuota = useRefreshEffectiveQuota();

  const filePermissions = useKnowledgeFilePermissions({
    displayFiles,
    space,
    currentFolderId,
  });
  const {
    canCreateFolder,
    canUploadFile,
    canMoveFile,
    permissionEntryIds,
    deleteEntryIds,
    renameEntryIds,
    downloadEntryIds,
  } = filePermissions;

  // Blank-area right-click menu opens when the user can upload a file OR create a folder.
  const canUseContextMenuActions = (canUploadFile || canCreateFolder) && !isSearching;
  // Read max file size from env config (MB), fallback to default 200MB
  const bishengConfig = useRecoilValue(bishengConfState);
  const uploadSizeLimits = resolveUploadSizeLimits(bishengConfig);
  const maxFileSizeMB = uploadSizeLimits.defaultMaxMB;
  const enableEtl4lm = bishengConfig?.enable_etl4lm ?? false;
  const allowedExtensions = getAllowedExtensions(enableEtl4lm);
  const fileInputAccept = getFileInputAccept(enableEtl4lm);

  // ─── File Upload Trigger ─────────────────────────────────────────────
  const uploadActions = useKnowledgeUploads({
    localize,
    setContextMenuOpen,
    setContextMenuPosition,
    queryClient,
    canUploadFile,
    canUseContextMenuActions,
    showToast,
    confirm,
    isStorageBlocked,
    refreshQuota,
    uploadSizeLimits,
    maxFileSizeMB,
    enableEtl4lm,
    allowedExtensions,
    space,
    onUploadFile,
    onUploadFolder,
    onDeleteFile,
    currentFolderId,
    onDragStateChange,
  });

  const {
    handleSearch,
    handleStatusFilter,
    handleSort,
    isFolderUploadPlaceholder,
    handleSelectFile,
    handleManagePermission,
    handleSelectAll,
  } = useKnowledgeSelectionActions({
    displayFiles,
    setSearchQuery,
    setSearchTagIds,
    selectedFiles,
    setSelectedFiles,
    statusFilter,
    setStatusFilter,
    sortBy,
    setSortBy,
    sortDirection,
    setSortDirection,
    setPermTarget,
    onSearch,
    onFilterStatus,
    onSort,
  });

  const selectableFiles = displayFiles.filter((f) => !isFolderUploadPlaceholder(f));
  const isAllSelectedOnPage =
    selectableFiles.length > 0 && selectableFiles.every((f) => selectedFiles.has(f.id));
  const isSelectionIndeterminate =
    !isAllSelectedOnPage && selectableFiles.some((f) => selectedFiles.has(f.id));
  const hasFailedFiles = displayFiles.some(
    (f) => selectedFiles.has(f.id) && isKnowledgeItemRetryable(f),
  );
  const hasFoldersSelected = displayFiles.some(
    (f) => selectedFiles.has(f.id) && f.type === FileType.FOLDER,
  );
  const selectedList = displayFiles.filter((f) => selectedFiles.has(f.id));
  // The actual server review classifies each selected source and the target.
  // Uploading placeholders no longer block the entry — the
  // move flow warns about them and lets the user move the rest (handleBatchMove).
  const canBatchMove = selectedList.length > 0;
  const canBatchDelete = selectedList.length > 0;
  const canBatchDownload = selectedList.length > 0;

  const fileActions = useKnowledgeFileActions({
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
    canDeleteSpace,
    deletionScopeKey: JSON.stringify([
      currentFolderId,
      Array.from(selectedFiles).sort(),
      Array.from(deleteEntryIds).sort(),
      Array.from(renameEntryIds).sort(),
    ]),
    space,
    onDeleteFile,
    onBatchDeleteFiles,
    onEditTags,
  });
  const {
    handleBatchDownload,
    handleBatchTag,
    dropMoveToFolder,
    handleBatchMove,
    handleSingleDownload,
    handleBatchDelete,
    handleBatchRetry,
  } = fileActions;

  // Toolbar select-all state — uploading folder placeholders (no backend
  // identity) never count, mirroring handleSelectAll / handleSelectFile.

  // appears whenever ANY selected file is a pending similar document. The dialog is then
  // scoped to exactly the selected files (see handleProcessSimilar).
  const hasSimilarSelected = selectedList.some(
    (f) => f.has_similar && !f.is_multi_version && f.status === FileStatus.SUCCESS,
  );

  // Mobile only ever shows the list form — never the multi-column card grid.
  const effectiveViewMode: "card" | "list" = isH5 ? "list" : viewMode;
  // Search page starts empty: show results only once a keyword/tag search is active.
  const suppressList = searchMode && !isSearching;

  // ─── Mobile batch action bar ────────────────────────────────────────
  // Shown at the bottom (replacing the AI dock) once any file is selected. Which
  // actions appear mirrors the desktop toolbar exactly (same permission/status gates).
  const selectionActive = isH5 && selectedFiles.size > 0;
  useEffect(() => {
    onSelectionActiveChange?.(selectionActive);
  }, [selectionActive, onSelectionActiveChange]);

  // Permission management is a single-target action: only with exactly one selected item,
  // and only when the user is allowed to manage its permission (permissionEntryIds is the
  // permission-probed set, so this respects the user's permission).
  const singleSelectedId = selectedFiles.size === 1 ? Array.from(selectedFiles)[0] : undefined;
  const canManageSinglePermission = !!singleSelectedId && permissionEntryIds.has(singleSelectedId);

  const { batchActions, inlineActions, overflowActions } = getKnowledgeBatchActions({
    selectedFiles,
    isAdmin,
    canManageMembers,
    versionManagementEnabled,
    handleProcessSimilar,
    handleManagePermission,
    hasFailedFiles,
    hasFoldersSelected,
    canBatchMove,
    canBatchDelete,
    canBatchDownload,
    handleBatchDownload,
    handleBatchTag,
    handleBatchMove,
    handleSingleDownload,
    handleBatchDelete,
    handleBatchRetry,
    hasSimilarSelected,
    singleSelectedId,
    canManageSinglePermission,
    localize,
  });

  // F034: drag-move wiring for the card grid (table view wires its own internally).
  const cardDrag = useKnowledgeMoveDrag({
    files: displayFiles,
    selectedFiles,
    onMoveToFolder: (folderId, items, folderName) => dropMoveToFolder(items, folderId, folderName),
  });

  return {
    ...filePermissions,
    ...uploadActions,
    ...fileActions,
    ...cardColumns,
    localize,
    isH5,
    fileListScrollRevealRef,
    displayFiles,
    handleListScroll,
    searchQuery,
    searchTagIds,
    viewMode,
    setViewMode,
    selectedFiles,
    setSelectedFiles,
    statusFilter,
    sortBy,
    sortDirection,
    contextMenuOpen,
    setContextMenuOpen,
    contextMenuPosition,
    isAdmin,
    ensureSpaceActions,
    canShareSpace,
    canDeleteSpace,
    canManageMembers,
    canEditSpace,
    canLeaveSpace,
    versionManagementEnabled,
    setVersionMgmtFile,
    setVersionHistoryFile,
    handleProcessSimilar,
    showShareInMenu,
    handleCopyShareLink,
    isSearching,
    listBottomStatus,
    fileInputAccept,
    handleSearch,
    handleStatusFilter,
    handleSort,
    handleSelectFile,
    handleManagePermission,
    handleSelectAll,
    selectableFiles,
    isAllSelectedOnPage,
    isSelectionIndeterminate,
    hasFailedFiles,
    hasFoldersSelected,
    canBatchMove,
    canBatchDelete,
    canBatchDownload,
    hasSimilarSelected,
    effectiveViewMode,
    suppressList,
    selectionActive,
    batchActions,
    inlineActions,
    overflowActions,
    cardDrag,
    space,
    files,
    loading,
    loadError,
    onSearch,
    onFilterStatus,
    onSort,
    onNavigateFolder,
    onCreateFolder,
    onRenameFile,
    onEditTags,
    currentPath,
    onCancelCreateFolder,
    onGoKnowledgeSquare,
    onOpenSystemMenu,
    onToggleSpaceList,
    spaceListOpen,
    onEditSpace,
    onDeleteSpace,
    onLeaveSpace,
    onOpenSearch,
    searchMode,
    onCloseSearch,
    editingTagsFileId,
    isBatchTagging,
    spaceIdNum,
    versionMgmtFile,
    versionHistoryFile,
    similarDialogOpen,
    setSimilarDialogOpen,
    similarRestrictIds,
    setSimilarRestrictIds,
    handleVersionAction,
    permTarget,
    setPermTarget,
    showToast,
    currentFolderId,
    setContextMenuPosition,
    queryClient,
    canUseContextMenuActions,
    confirm,
    isStorageBlocked,
    refreshQuota,
    uploadSizeLimits,
    maxFileSizeMB,
    enableEtl4lm,
    allowedExtensions,
    onUploadFile,
    onUploadFolder,
    onDeleteFile,
    onDragStateChange,
    setEditingTagsFileId,
    setIsBatchTagging,
    selectedList,
    onBatchDeleteFiles,
    setSearchQuery,
    setSearchTagIds,
    setStatusFilter,
    setSortBy,
    setSortDirection,
    handleBatchDownload,
    handleBatchTag,
    handleBatchMove,
    handleSingleDownload,
    handleBatchDelete,
    handleBatchRetry,
    singleSelectedId,
    canManageSinglePermission,
  };
}

export type KnowledgeSpaceModel = ReturnType<typeof useKnowledgeSpaceDetail>;

export function KnowledgeSpaceContent(props: KnowledgeSpaceContentProps) {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const confirm = useConfirm();
  const model = useKnowledgeSpaceDetail(props, {
    localize,
    showToast,
    confirm,
  });
  return <KnowledgeSpacePresentation model={model} />;
}
