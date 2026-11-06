import type { Dispatch, SetStateAction } from "react";
import type { QueryClient } from "@tanstack/react-query";
import type { useLocalize } from "~/hooks";
import type { useToastContext, useConfirm } from "~/Providers";
import type { useStorageQuotaGuard } from "~/hooks/usePersonalStorageQuota";
import type { useRefreshEffectiveQuota } from "~/hooks/useEffectiveQuota";
import {
  FileStatus,
  KnowledgeFile,
  KnowledgeSpace,
  SortDirection,
  SortType,
} from "~/api/knowledge";
import { type UploadSizeLimits } from "../knowledgeUtils";
import { SearchParams } from "./CompoundSearchInput";
import type {
  OperationPrecheck,
  PageData,
  ProcessingIdentityScope,
  ProcessingItemRead,
  ProcessingJobRead,
} from "~/api/knowledgeProcessing";

/** Display data remains distinct from an executable confirmation plan. */
export interface KnowledgeProcessingState {
  jobs: PageData<ProcessingJobRead> | null;
  selectedJob: ProcessingJobRead | null;
  items: PageData<ProcessingItemRead> | null;
  loading: boolean;
  error: unknown;
}

/** A later mutation must compare this issuing scope with the current identity. */
export interface KnowledgeProcessingConfirmation {
  scope: Readonly<ProcessingIdentityScope>;
  precheck: OperationPrecheck;
}

export interface KnowledgeSpaceContentProps {
  space: KnowledgeSpace;
  files: KnowledgeFile[];
  total: number;
  /** Infinite scroll: load the next page (appends). */
  onLoadMore: () => void;
  /** Whether more pages remain to load. */
  hasMore: boolean;
  loading: boolean;
  loadError?: boolean;
  loadMoreError?: boolean;
  onSearch: (params: SearchParams) => void;
  onFilterStatus: (status: FileStatus[]) => void;
  onSort: (
    sortBy: SortType | undefined,
    direction: SortDirection | undefined,
  ) => void;
  onNavigateFolder: (folderId?: string) => void;
  onUploadFile: (files?: FileList | File[]) => void;
  onUploadFolder: (
    fileList: FileList | File[],
    options: {
      allowedExtensions: readonly string[];
      maxSizeMB: number;
      limits?: UploadSizeLimits;
    },
  ) => void;
  onCreateFolder: () => void;
  onDownloadFile: (fileId: string) => void;
  onRenameFile: (fileId: string, newName: string) => void | Promise<void>;
  onDeleteFile: (fileId: string) => void;
  /** Optimistic batch delete: removes the given ids in place. Resolves true on success. */
  onBatchDeleteFiles: (ids: Array<string | number>) => Promise<boolean>;
  onEditTags: (fileId: string) => void;
  onRetryFile: (fileId: string) => void;
  currentPath: Array<{ id?: string; name: string }>;
  currentFolderId?: string;
  onDragStateChange?: (isDragging: boolean, error?: string | null) => void;
  uploadingFiles?: KnowledgeFile[];
  creatingFolder?: KnowledgeFile | null;
  /** Placeholder folder card shown while a dragged/picked folder batch uploads. */
  uploadingFolder?: KnowledgeFile | null;
  onCancelCreateFolder?: () => void;
  onCreateSpace?: () => void;
  onGoKnowledgeSquare?: () => void;
  /** Mobile top bar — provided by the Knowledge page (index.tsx). */
  onOpenSystemMenu?: () => void;
  onToggleSpaceList?: () => void;
  spaceListOpen?: boolean;
  /** Edit current space (opens the space settings drawer owned by the page); permission-gated by the menu. */
  onEditSpace?: () => void;
  /** Delete current space (navigates back to the list); permission-gated by the menu. */
  onDeleteSpace?: () => void;
  /** Leave a joined space (navigates back to the list); permission-gated by the menu. */
  onLeaveSpace?: () => void;
  /** Open the search page from the top-bar search icon. */
  onOpenSearch?: () => void;
  /** Mobile full-page search mode: replaces the top bar with an inline search header. */
  searchMode?: boolean;
  onCloseSearch?: () => void;
  /** Notify the page when a mobile batch selection is active, so it can hide the AI dock. */
  onSelectionActiveChange?: (active: boolean) => void;
}

export type KnowledgeStateSetter<T> = Dispatch<SetStateAction<T>>;
export interface KnowledgeUiPorts {
  localize: ReturnType<typeof useLocalize>;
  showToast: ReturnType<typeof useToastContext>["showToast"];
  confirm: ReturnType<typeof useConfirm>;
}
export interface KnowledgePermissionTarget {
  id: string;
  name: string;
  type: "folder" | "knowledge_file";
}

export interface UseKnowledgeFilePermissionsOptions {
  displayFiles: KnowledgeFile[];
  space: KnowledgeSpaceContentProps["space"];
  currentFolderId: KnowledgeSpaceContentProps["currentFolderId"];
}

export interface UseKnowledgeCardColumnsOptions {
  displayFiles: KnowledgeFile[];
  viewMode: "card" | "list";
}

export interface UseKnowledgeSpaceHeaderOptions {
  selectedFiles: Set<string>;
  space: KnowledgeSpaceContentProps["space"];
  onDeleteFile: KnowledgeSpaceContentProps["onDeleteFile"];
  localize: KnowledgeUiPorts["localize"];
  showToast: KnowledgeUiPorts["showToast"];
}

export interface UseKnowledgeUploadsOptions {
  localize: KnowledgeUiPorts["localize"];
  setContextMenuOpen: KnowledgeStateSetter<boolean>;
  setContextMenuPosition: KnowledgeStateSetter<{ x: number; y: number }>;
  queryClient: QueryClient;
  canUploadFile: boolean;
  canUseContextMenuActions: boolean;
  showToast: KnowledgeUiPorts["showToast"];
  confirm: KnowledgeUiPorts["confirm"];
  isStorageBlocked: ReturnType<typeof useStorageQuotaGuard>;
  refreshQuota: ReturnType<typeof useRefreshEffectiveQuota>;
  uploadSizeLimits: UploadSizeLimits;
  maxFileSizeMB: number;
  enableEtl4lm: boolean;
  allowedExtensions: readonly string[];
  space: KnowledgeSpaceContentProps["space"];
  onUploadFile: KnowledgeSpaceContentProps["onUploadFile"];
  onUploadFolder: KnowledgeSpaceContentProps["onUploadFolder"];
  onDeleteFile: KnowledgeSpaceContentProps["onDeleteFile"];
  currentFolderId: KnowledgeSpaceContentProps["currentFolderId"];
  onDragStateChange: KnowledgeSpaceContentProps["onDragStateChange"];
}

export interface UseKnowledgeFileActionsOptions {
  localize: KnowledgeUiPorts["localize"];
  displayFiles: KnowledgeFile[];
  selectedFiles: Set<string>;
  setSelectedFiles: KnowledgeStateSetter<Set<string>>;
  editingTagsFileId: string | null;
  setEditingTagsFileId: KnowledgeStateSetter<string | null>;
  setIsBatchTagging: KnowledgeStateSetter<boolean>;
  queryClient: QueryClient;
  canMoveFile: boolean;
  deleteEntryIds: Set<string>;
  downloadEntryIds: Set<string>;
  showToast: KnowledgeUiPorts["showToast"];
  confirm: KnowledgeUiPorts["confirm"];
  selectedList: KnowledgeFile[];
  canBatchDelete: boolean;
  space: KnowledgeSpaceContentProps["space"];
  onDeleteFile: KnowledgeSpaceContentProps["onDeleteFile"];
  onBatchDeleteFiles: KnowledgeSpaceContentProps["onBatchDeleteFiles"];
  onEditTags: KnowledgeSpaceContentProps["onEditTags"];
}

export interface UseKnowledgeSelectionActionsOptions {
  displayFiles: KnowledgeFile[];
  setSearchQuery: KnowledgeStateSetter<string>;
  setSearchTagIds: KnowledgeStateSetter<number[]>;
  selectedFiles: Set<string>;
  setSelectedFiles: KnowledgeStateSetter<Set<string>>;
  statusFilter: FileStatus[];
  setStatusFilter: KnowledgeStateSetter<FileStatus[]>;
  sortBy: SortType | undefined;
  setSortBy: KnowledgeStateSetter<SortType | undefined>;
  sortDirection: SortDirection | undefined;
  setSortDirection: KnowledgeStateSetter<SortDirection | undefined>;
  setPermTarget: KnowledgeStateSetter<KnowledgePermissionTarget | null>;
  onSearch: KnowledgeSpaceContentProps["onSearch"];
  onFilterStatus: KnowledgeSpaceContentProps["onFilterStatus"];
  onSort: KnowledgeSpaceContentProps["onSort"];
}

export interface GetKnowledgeBatchActionsOptions {
  selectedFiles: Set<string>;
  isAdmin: boolean;
  canManageMembers: boolean;
  versionManagementEnabled: boolean;
  handleProcessSimilar: () => void;
  handleManagePermission: (fileId: string) => void;
  hasFailedFiles: boolean;
  hasFoldersSelected: boolean;
  canBatchMove: boolean;
  canBatchDelete: boolean;
  canBatchDownload: boolean;
  handleBatchDownload: () => void;
  handleBatchTag: () => void;
  handleBatchMove: () => void;
  handleSingleDownload: (fileId: string) => void;
  handleBatchDelete: () => void;
  handleBatchRetry: () => void;
  hasSimilarSelected: boolean;
  singleSelectedId: string | undefined;
  canManageSinglePermission: boolean;
  localize: KnowledgeUiPorts["localize"];
}
