import type { GetKnowledgeBatchActionsOptions } from "./knowledgeSpaceTypes";
import { Outlined } from "bisheng-icons";
export function getKnowledgeBatchActions({
  selectedFiles,
  canManageMembers,
  versionManagementEnabled,
  handleProcessSimilar,
  handleManagePermission,
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
}: GetKnowledgeBatchActionsOptions) {
  type BatchAction = {
    key: string;
    label: string;
    Icon: React.ComponentType<{ className?: string }>;
    onClick: () => void;
    danger?: boolean;
  };
  const batchActions: BatchAction[] = [
    canBatchDownload && {
      key: "download",
      label: localize("com_knowledge.download"),
      Icon: Outlined.Download,
      onClick: () =>
        selectedFiles.size === 1
          ? handleSingleDownload(Array.from(selectedFiles)[0])
          : handleBatchDownload(),
    },
    selectedFiles.size > 0 && {
      key: "tag",
      label: localize("com_knowledge.batch_add_tags"),
      Icon: Outlined.Tag,
      onClick: handleBatchTag,
    },
    selectedFiles.size > 0 && {
      key: "retry",
      label: localize("com_knowledge.retry"),
      Icon: Outlined.Refresh,
      onClick: handleBatchRetry,
    },
    versionManagementEnabled &&
      canManageMembers &&
      hasSimilarSelected && {
        key: "similar",
        label: localize("com_knowledge.version.header_process_similar_label"),
        Icon: Outlined.FileSearch,
        onClick: handleProcessSimilar,
      },
    canBatchMove && {
      key: "move",
      label: localize("com_knowledge.move"),
      Icon: Outlined.MoveToFolder,
      onClick: handleBatchMove,
    },
    canManageSinglePermission && {
      key: "permission",
      label: localize("com_permission.manage_permission"),
      Icon: Outlined.PeopleSafe,
      onClick: () => handleManagePermission(singleSelectedId!),
    },
    canBatchDelete && {
      key: "delete",
      label: localize("com_knowledge.delete"),
      Icon: Outlined.Delete,
      onClick: handleBatchDelete,
      danger: true,
    },
  ].filter(Boolean) as BatchAction[];

  const MAX_INLINE = 3;
  const hasOverflow = batchActions.length > MAX_INLINE;
  const inlineActions = hasOverflow ? batchActions.slice(0, MAX_INLINE - 1) : batchActions;
  const overflowActions = hasOverflow ? batchActions.slice(MAX_INLINE - 1) : [];

  return { batchActions, inlineActions, overflowActions };
}
