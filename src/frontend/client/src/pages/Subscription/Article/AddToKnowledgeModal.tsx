import { useLocalize } from "~/hooks";
import { EmptyStateIllustration } from "~/components/illustrations";
import { ChevronLeft, Loader2, X } from "lucide-react";
import { type RefObject } from "react";
import { SearchInput } from "@bisheng/ui";
import { Button } from "~/components/ui/Button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/Dialog";
import { useToastContext } from "~/Providers";
import { cn } from "~/utils";
import { TreeNode } from "./KnowledgePickerTree";
import { useAddToKnowledge } from "./useAddToKnowledge";
export interface KnowledgeNode {
  id: string;
  name: string;
  type: "space" | "folder";
  level: number; // 1 = knowledge space, 2+ = folder
  parentId: string | null;
  /** The space_id this node belongs to (for API calls) */
  spaceId: string;
  children?: KnowledgeNode[];
  /** Whether children have been loaded from the API */
  childrenLoaded?: boolean;
  /** Whether children are currently loading */
  childrenLoading?: boolean;
}

export interface AddToKnowledgeSelection {
  knowledgeSpaceId: string;
  knowledgeSpaceName: string;
  folderId: string | null;
  folderPath: string | null;
}

/** Minimal space record consumed by the picker tree. */
export interface AddToKnowledgeSpaceSummary {
  id: string;
  name: string;
}

export interface AddToKnowledgeModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Article ID to add to the selected knowledge space/folder (article mode). */
  articleId?: string | number;
  /**
   * v2.5 Module D: when set to "channel_sync", the modal becomes a generic
   * space/folder picker — confirm returns selection info via onSyncSelect
   * instead of calling addArticleToKnowledgeApi.
   */
  mode?: "article" | "channel_sync";
  /** Receives the chosen knowledge space / folder; only fires in channel_sync mode. */
  onSyncSelect?: (selection: AddToKnowledgeSelection) => void;

  /** Retained for existing callers; the picker uses its normal modal shell. */
  channelSyncPortalHostRef?: RefObject<HTMLDivElement | null>;
  /**
   * F028: optional custom space-list loader. When provided, overrides the
   * mode-based default (getMineSpacesApi / getManagedSpacesApi). Used by
   * the workstation conversation-export flow to feed in the user's
   * upload_file-eligible spaces. Original article / channel_sync callers
   * leave this undefined and keep their existing behavior.
   */
  dataSourceApi?: () => Promise<AddToKnowledgeSpaceSummary[]>;
}

// ─── Helpers ─────────────────────────────────────────────────────────────

export function AddToKnowledgeModal(props: AddToKnowledgeModalProps) {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const {
    treeScrollRevealRef,
    duplicateListScrollRevealRef,
    isFullScreenLayout,
    isChannelSyncFullScreen,
    isChannelSyncCentered,
    isArticleFullScreen,
    search,
    setSearch,
    selectedId,
    expandedIds,
    editingId,
    isCreatingFolder,
    canConfirm,
    isConfirming,
    spacesLoading,
    duplicateFiles,
    setDuplicateFiles,
    showDuplicate,
    setShowDuplicate,
    setPendingConfirm,
    articleDialogContentRef,
    actionFooterRef,
    displayTree,
    isSearchMode,
    toggleExpand,
    handleSelect,
    handleAddFolder,
    handleSaveEdit,
    handleCancelEdit,
    handleConfirm,
    handleOpenChange,
    isEmpty,
    titleLabel,
    goBackToChannelForm,
    isChannelSyncFullScreenFooter,
    open,
    onOpenChange,
    mode,
  } = useAddToKnowledge(props, localize, showToast);
  const pickerBody = (
    <>
      {
        <DialogHeader className="flex flex-row items-center justify-between gap-3 space-y-0 px-5 pb-0 pt-5 text-left touch-mobile:px-4 touch-mobile:pt-4">
          <DialogTitle className="min-w-0 flex-1 text-base font-medium leading-6 text-text-1">
            {titleLabel}
          </DialogTitle>
          <button
            type="button"
            onClick={() => handleOpenChange(false)}
            className="inline-flex size-8 shrink-0 items-center justify-center rounded-md text-text-2 hover:bg-fill-1"
            aria-label={localize("com_ui_close")}
          >
            <X className="size-5" />
          </button>
        </DialogHeader>
      }

      <div className={"px-5 pt-4 touch-mobile:px-4"}>
        {/* Spec SearchInput — built-in clear replaces the hand-rolled X. */}
        <SearchInput
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={localize(
            "com_subscription.search_knowledge_space_placeholder",
          )}
          clearLabel={localize("com_ui_clear")}
        />
      </div>

      <div
        className={
          isChannelSyncFullScreen
            ? "mb-4 flex min-h-0 flex-1 flex-col px-5 pt-4 touch-mobile:px-4"
            : isArticleFullScreen
              ? "flex min-h-0 flex-1 flex-col px-4 pt-4 pb-[64px]"
              : "flex min-h-0 flex-1 flex-col px-5 pt-4 touch-mobile:px-4"
        }
      >
        <div
          ref={treeScrollRevealRef}
          className={
            "scrollbar-gutter-stable flex min-h-0 flex-1 flex-col overflow-y-auto overflow-x-hidden rounded-md border border-[#ECECEC] p-1 scrollbar-on-scroll"
          }
        >
          {spacesLoading ? (
            <div className="flex items-center justify-center h-full min-h-[200px] text-text-3">
              <Loader2 className="size-5 animate-spin mr-2" />
              {localize("com_subscription.loading")}
            </div>
          ) : isEmpty ? (
            <div className="flex flex-col items-center justify-center h-full min-h-[200px] text-gray-800">
              <EmptyStateIllustration className="size-[120px] mb-4" />
              <p className="text-[14px] font-normal text-text-3">
                {localize("com_subscription.no_selectable_knowledge_space")}
              </p>
            </div>
          ) : displayTree.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full min-h-[200px] text-gray-800">
              <EmptyStateIllustration className="size-[120px] mb-4" />
              <p className="text-[14px] font-normal text-text-3">
                {localize("com_subscription.no_matching_knowledge_space")}
              </p>
            </div>
          ) : (
            <div className="w-full min-w-0 max-w-full space-y-1 pb-1">
              {displayTree.map((node) => (
                <TreeNode
                  key={node.id}
                  node={node}
                  nodes={displayTree}
                  selectedId={selectedId}
                  expandedIds={expandedIds}
                  editingId={editingId}
                  onSelect={handleSelect}
                  onToggle={toggleExpand}
                  onAddFolder={handleAddFolder}
                  onSaveEdit={handleSaveEdit}
                  onCancelEdit={handleCancelEdit}
                  searchMode={isSearchMode}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      <div
        ref={actionFooterRef}
        className={
          isChannelSyncFullScreen
            ? "mt-auto flex w-full min-w-0 shrink-0 flex-row justify-stretch gap-2 bg-white px-4 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))] pt-0"
            : isArticleFullScreen
              ? "fixed inset-x-0 bottom-0 z-[140] flex w-full min-w-0 shrink-0 flex-row justify-stretch gap-2 bg-white px-4 py-3"
              : "mt-auto flex w-full min-w-0 shrink-0 flex-row justify-end bg-white px-5 pb-5 pt-4 touch-mobile:mt-auto touch-mobile:px-4 touch-mobile:py-3"
        }
      >
        <div
          className={cn(
            "min-w-0",
            !isChannelSyncFullScreenFooter && "ml-auto",
            isChannelSyncFullScreen || isArticleFullScreen
              ? "flex w-full items-center gap-2"
              : "flex w-auto shrink-0 items-center gap-2",
          )}
        >
          <Button
            color="default"
            variant="outlined"
            size="medium"
            onClick={goBackToChannelForm}
            className={cn(
              "min-w-[64px] shrink-0",
              isChannelSyncFullScreenFooter &&
                "rounded-lg border-border-base text-text-2 hover:bg-fill-1",
              isChannelSyncFullScreenFooter && "flex-1",
              false,
              mode === "article" && isFullScreenLayout && "touch-mobile:flex-1",
            )}
          >
            {localize("com_subscription.cancel")}
          </Button>
          <Button
            color="primary"
            variant="solid"
            size="medium"
            onClick={() => void handleConfirm()}
            disabled={!canConfirm}
            loading={isConfirming || isCreatingFolder}
            className={cn(
              "min-w-[64px] shrink-0",
              isChannelSyncFullScreenFooter && "rounded-lg",
              isChannelSyncFullScreenFooter && "flex-1",
              false,
              mode === "article" && isFullScreenLayout && "touch-mobile:flex-1",
            )}
          >
            {localize("com_subscription.add")}
          </Button>
        </div>
      </div>
    </>
  );

  return (
    <>
      {open && isChannelSyncFullScreen && (
        <Dialog open={open} onOpenChange={handleOpenChange}>
          <DialogContent
            close={false}
            className="!fixed !inset-0 !left-0 !top-0 !z-[100] !flex !h-[100dvh] !w-screen !max-w-none !min-h-0 !translate-x-0 !translate-y-0 !flex-col !gap-0 !overflow-hidden !rounded-none !p-0 !animate-none"
            style={{
              position: "fixed",
              inset: 0,
              left: 0,
              top: 0,
              width: "100vw",
              height: "100dvh",
              maxWidth: "none",
              transform: "none",
              borderRadius: 0,
              padding: 0,
            }}
          >
            {pickerBody}
          </DialogContent>
        </Dialog>
      )}
      {open && isChannelSyncCentered && (
        <Dialog open={open} onOpenChange={handleOpenChange}>
          <DialogContent
            close={false}
            overlayClassName="bg-gray-500/90 dark:bg-gray-800/90"
            className="flex h-[80vh] max-h-[600px] w-[576px] max-w-[92vw] min-h-0 flex-col gap-0 overflow-hidden rounded-2xl border-[#ebebeb] p-0 shadow-[0_0_16px_0_rgba(3,7,117,0.05)] sm:rounded-2xl dark:border-gray-700"
          >
            {pickerBody}
          </DialogContent>
        </Dialog>
      )}
      {open && mode === "article" && (
        <Dialog open={open} onOpenChange={handleOpenChange}>
          <DialogContent
            close={false}
            ref={articleDialogContentRef}
            overlayClassName="bg-gray-500/90 dark:bg-gray-800/90"
            className="flex h-[80vh] max-h-[600px] w-[576px] max-w-[92vw] min-h-0 flex-col gap-0 overflow-hidden rounded-2xl border-[#ebebeb] p-0 shadow-[0_0_16px_0_rgba(3,7,117,0.05)] sm:rounded-2xl dark:border-gray-700 max-[575px]:inset-0 max-[575px]:left-0 max-[575px]:top-0 max-[575px]:h-[100dvh] max-[575px]:w-screen max-[575px]:max-w-none max-[575px]:translate-x-0 max-[575px]:translate-y-0 max-[575px]:rounded-none max-[575px]:animate-none"
            style={
              isFullScreenLayout
                ? {
                    position: "fixed",
                    inset: 0,
                    left: 0,
                    top: 0,
                    width: "100vw",
                    height: "100dvh",
                    maxWidth: "none",
                    maxHeight: "none",
                    transform: "none",
                    borderRadius: 0,
                    padding: 0,
                  }
                : undefined
            }
          >
            {pickerBody}
          </DialogContent>
        </Dialog>
      )}

      {/* Duplicate File Confirmation Dialog */}
      <Dialog open={showDuplicate} onOpenChange={setShowDuplicate}>
        <DialogContent
          overlayClassName="bg-gray-500/90 dark:bg-gray-800/90"
          className="w-[480px] max-w-[90vw] gap-0 overflow-hidden rounded-2xl border-[#ebebeb] p-0 shadow-[0_0_16px_0_rgba(3,7,117,0.05)] sm:rounded-2xl dark:border-gray-700"
        >
          <DialogHeader className="px-5 pb-0 pt-5">
            <DialogTitle className="text-base font-medium leading-6 text-text-1">
              {localize("com_subscription.duplicate_files_title")}
            </DialogTitle>
          </DialogHeader>
          <div
            ref={duplicateListScrollRevealRef}
            className="max-h-[200px] overflow-y-auto px-5 pt-4 scrollbar-on-scroll"
          >
            {duplicateFiles.map((file, idx) => {
              // Truncate file name > 10 chars with ellipsis
              const displayName =
                file.name.length > 10
                  ? file.name.slice(0, 10) +
                    "..." +
                    (file.name.includes(".")
                      ? file.name.slice(file.name.lastIndexOf("."))
                      : "")
                  : file.name;
              return (
                <div
                  key={idx}
                  className="flex items-center gap-2 py-1.5 text-sm"
                >
                  <span
                    className="text-gray-800 font-medium truncate max-w-[200px]"
                    title={file.name}
                  >
                    {displayName}
                  </span>
                  {file.path && (
                    <span
                      className="text-text-3 text-xs truncate max-w-[180px]"
                      title={file.path}
                    >
                      ({file.path})
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          <DialogFooter className="flex flex-row justify-end gap-2 px-5 pb-5 pt-4">
            <Button
              color="default"
              variant="outlined"
              size="medium"
              onClick={() => {
                setShowDuplicate(false);
                setPendingConfirm(null);
                setDuplicateFiles([]);
              }}
            >
              {localize("com_subscription.cancel")}
            </Button>
            <Button
              color="primary"
              variant="solid"
              size="medium"
              onClick={() => handleConfirm(true)}
              disabled={isConfirming}
              loading={isConfirming}
            >
              {localize("com_subscription.replace")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
