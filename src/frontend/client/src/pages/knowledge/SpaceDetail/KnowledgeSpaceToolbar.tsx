import { WorkbenchMenuButton } from "~/layouts/WorkbenchMenuButton";
import { FolderPlus, Link2 } from "lucide-react";
import { SortDirection, SortType, SpaceRole } from "~/api/knowledge";
import { Outlined } from "bisheng-icons";
import { Button, Dropdown, DropdownGroup, DropdownItem } from "@bisheng/ui";
import { CompoundSearchInput } from "./CompoundSearchInput";
import { FileListToolbar } from "./FileListToolbar";
import { KnowledgeSpaceHeader } from "./KnowledgeSpaceHeader";
import { cn } from "~/utils";
import { knowledgeUploadCapabilities } from "../knowledgeUploadCapabilities";
import type { KnowledgeSpaceModel } from "./index";
interface KnowledgeSpaceToolbarProps {
  model: KnowledgeSpaceModel;
}
export function KnowledgeSpaceToolbar({ model }: KnowledgeSpaceToolbarProps) {
  const {
    localize,
    moveProgress,
    isH5,
    viewMode,
    setViewMode,
    selectedFiles,
    setSelectedFiles,
    statusFilter,
    sortBy,
    sortDirection,
    ensureSpaceActions,
    canShareSpace,
    canDeleteSpace,
    canManageMembers,
    canEditSpace,
    canLeaveSpace,
    versionManagementEnabled,
    handleProcessSimilar,
    showShareInMenu,
    handleCopyShareLink,
    canCreateFolder,
    canUploadFile,
    isSearching,
    fileInputAccept,
    fileInputRef,
    folderInputRef,
    triggerUpload,
    triggerUploadFolder,
    triggerWebLink,
    handleFileChange,
    handleFolderChange,
    handleSearch,
    handleStatusFilter,
    handleSort,
    handleSelectAll,
    selectableFiles,
    isAllSelectedOnPage,
    isSelectionIndeterminate,
    hasFailedFiles,
    hasFoldersSelected,
    canBatchMove,
    canBatchDelete,
    canBatchDownload,
    handleBatchDownload,
    handleBatchTag,
    handleBatchMove,
    handleBatchDelete,
    handleBatchRetry,
    hasSimilarSelected,
    space,
    onNavigateFolder,
    onCreateFolder,
    currentPath,
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
  } = model;
  return (
    <>
      {/* Hidden File Input */}
      <input
        type="file"
        multiple
        className="hidden"
        ref={fileInputRef}
        onChange={handleFileChange}
        accept={fileInputAccept}
      />
      {/* Hidden Folder Input — `webkitdirectory` makes the picker select a
                directory; each File carries its `webkitRelativePath`. No `accept`:
                extension filtering is done silently in the hook per spec. */}
      <input
        type="file"
        multiple
        className="hidden"
        ref={folderInputRef}
        onChange={handleFolderChange}
        // `webkitdirectory`/`directory` are non-standard but accepted by
        // every browser we ship to; React typings don't list them.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        {...({ webkitdirectory: "", directory: "" } as any)}
      />
      {/* Narrow full-page search header: inline search box (scope + keyword + tags) + cancel.
                Per design (Figma 11495:16476): the search-box+cancel row is 64px tall, no top padding;
                tags flow immediately below. The 64px row is owned by CompoundSearchInput pageMode. */}
      {isH5 && searchMode && (
        <div className="shrink-0 rounded-t-xl bg-white px-4">
          <CompoundSearchInput
            pageMode
            spaceId={space.id}
            isRoot={currentPath.length === 0}
            onSearch={handleSearch}
            trailing={
              <button
                type="button"
                onClick={() => {
                  handleSearch({
                    scope: currentPath.length === 0 ? "all" : "current",
                    tagIds: [],
                    keyword: "",
                  });
                  onCloseSearch?.();
                }}
                className="shrink-0 text-sm text-text-3"
              >
                {localize("com_knowledge.cancel")}
              </button>
            }
          />
        </div>
      )}

      {/* Mobile top bar: system menu + space-name dropdown + search/sort/more.
                Search/sort/more are greyed + disabled while the space-list dropdown is open. */}
      {isH5 && !searchMode && (
        /* Root has no padding on mobile; the inner row's px-4 gives the 16px gutter. */
        <div className="shrink-0 rounded-t-xl bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)]">
          <div className="flex h-11 w-full min-w-0 items-center gap-3 px-4">
            {/* Left group — fixed width that mirrors the right group, so the
                            center title stays screen-centered even when truncated.
                            84px = search(20) + gap(12) + sort(20) + gap(12) + more(20). */}
            <div className="flex min-w-[84px] shrink-0 items-center justify-start">
              <WorkbenchMenuButton
                type="button"
                aria-label={localize("com_nav_open_sidebar")}
                onClick={() => onOpenSystemMenu?.()}
                disabled={spaceListOpen}
                className={cn(
                  "inline-flex size-5 shrink-0 items-center justify-center text-text-1",
                  spaceListOpen && "pointer-events-none text-text-4",
                )}
              >
                <Outlined.SidebarMenu className="size-5" />
              </WorkbenchMenuButton>
            </div>
            {/* Center group — title grows then truncates while staying centered */}
            <button
              type="button"
              onClick={() => onToggleSpaceList?.()}
              aria-expanded={spaceListOpen}
              className="flex min-w-0 flex-1 items-center justify-center gap-1 outline-none"
            >
              <span className="truncate text-[16px] font-medium leading-6 text-text-1">
                {currentPath.length > 0
                  ? currentPath[currentPath.length - 1].name
                  : space.name}
              </span>
              <Outlined.Down
                className={cn(
                  "size-5 shrink-0 text-text-3 transition-transform",
                  spaceListOpen && "rotate-180",
                )}
              />
            </button>
            {/* Right group — same fixed width as the left group */}
            <div className="flex min-w-[84px] shrink-0 items-center justify-end gap-3">
              <button
                type="button"
                aria-label={localize("com_knowledge.search")}
                onClick={() => onOpenSearch?.()}
                className={cn(
                  "inline-flex size-5 shrink-0 items-center justify-center text-text-1",
                  spaceListOpen && "pointer-events-none text-text-4",
                )}
              >
                <Outlined.Search className="size-5" />
              </button>
              <Dropdown
                align="end"
                disabled={spaceListOpen}
                onOpenChange={(open) => {
                  if (open) ensureSpaceActions(space.id);
                }}
                menu={
                  <DropdownGroup label={localize("com_knowledge.sort_field")}>
                    {[
                      {
                        value: SortType.NAME,
                        label: localize("com_knowledge.sort_by_name_label"),
                      },
                      {
                        value: SortType.TYPE,
                        label: localize("com_knowledge.sort_by_type_label"),
                      },
                      {
                        value: SortType.UPDATE_TIME,
                        label: localize(
                          "com_knowledge.sort_by_update_time_label",
                        ),
                      },
                    ].map((opt) => (
                      <DropdownItem
                        key={opt.value}
                        onSelect={() => handleSort(opt.value)}
                        // Active field shows its direction; picking it again flips it.
                        shortcut={
                          sortBy === opt.value
                            ? sortDirection === SortDirection.ASC
                              ? "↑"
                              : "↓"
                            : undefined
                        }
                      >
                        {opt.label}
                      </DropdownItem>
                    ))}
                  </DropdownGroup>
                }
              >
                <button
                  type="button"
                  aria-label={localize("com_knowledge.sort_field")}
                  className={cn(
                    "inline-flex size-5 shrink-0 items-center justify-center text-text-1 outline-none",
                    spaceListOpen && "pointer-events-none text-text-4",
                  )}
                >
                  <Outlined.Sort className="size-5" />
                </button>
              </Dropdown>
              {/* Hide the whole "..." trigger when every item is permission-gated
                                away — an empty menu is confusing on mobile. */}
              {(canUploadFile ||
                canCreateFolder ||
                showShareInMenu ||
                canManageMembers ||
                canDeleteSpace ||
                canLeaveSpace) && (
                <Dropdown
                  align="end"
                  disabled={spaceListOpen}
                  onOpenChange={(open) => {
                    if (open) ensureSpaceActions(space.id);
                  }}
                  menu={
                    <>
                      {canUploadFile && (
                        <DropdownItem
                          icon={<Outlined.Upload />}
                          onSelect={triggerUpload}
                        >
                          {localize("com_knowledge.upload_file")}
                        </DropdownItem>
                      )}
                      {canUploadFile && knowledgeUploadCapabilities.webLink && (
                        <DropdownItem
                          icon={<Link2 />}
                          onSelect={triggerWebLink}
                        >
                          {localize("com_knowledge.web_link")}
                        </DropdownItem>
                      )}
                      {canCreateFolder && (
                        <DropdownItem
                          icon={<FolderPlus />}
                          onSelect={() => onCreateFolder()}
                        >
                          {localize("com_knowledge.new_folder")}
                        </DropdownItem>
                      )}
                      {(canEditSpace || canManageMembers) && onEditSpace && (
                        <DropdownItem
                          icon={<Outlined.Edit />}
                          onSelect={() => onEditSpace()}
                        >
                          {localize("com_knowledge.space_settings")}
                        </DropdownItem>
                      )}
                      {showShareInMenu && (
                        <DropdownItem
                          icon={<Outlined.Share />}
                          onSelect={handleCopyShareLink}
                        >
                          {localize("com_knowledge.share")}
                        </DropdownItem>
                      )}
                      {canDeleteSpace && (
                        <DropdownItem
                          danger
                          icon={<Outlined.Delete />}
                          onSelect={() => onDeleteSpace?.()}
                        >
                          {localize("com_knowledge.delete_space")}
                        </DropdownItem>
                      )}
                      {canLeaveSpace && onLeaveSpace && (
                        <DropdownItem
                          danger
                          icon={<Outlined.LogOut />}
                          onSelect={() => onLeaveSpace()}
                        >
                          {localize("com_knowledge.exit_space_short")}
                        </DropdownItem>
                      )}
                    </>
                  }
                >
                  <button
                    type="button"
                    aria-label={localize("com_knowledge.more")}
                    className={cn(
                      "inline-flex size-5 shrink-0 items-center justify-center text-text-1 outline-none",
                      spaceListOpen && "pointer-events-none text-text-4",
                    )}
                  >
                    <Outlined.MoreCircle className="size-5" />
                  </button>
                </Dropdown>
              )}
            </div>
          </div>
        </div>
      )}
      {moveProgress?.available && (
        <div className="flex justify-end">
          <Button
            size="small"
            variant="text"
            onClick={moveProgress.showHistory}
          >
            {localize("com_knowledge.move_progress_title")}
          </Button>
        </div>
      )}
      {/* Header (desktop only; on mobile these actions live in the top-bar menu) */}
      {!isH5 && (
        <div className="shrink-0">
          <KnowledgeSpaceHeader
            space={space}
            currentPath={currentPath}
            onNavigateFolder={onNavigateFolder}
            isSearching={isSearching}
            onCreateFolder={onCreateFolder}
            onTriggerUpload={triggerUpload}
            onTriggerUploadFolder={triggerUploadFolder}
            onTriggerWebLink={triggerWebLink}
            canCreateFolder={canCreateFolder}
            canUploadFile={canUploadFile}
            selectedCount={selectedFiles.size}
            hasFoldersSelected={hasFoldersSelected}
            hasFailedFiles={hasFailedFiles}
            onClearSelection={() => setSelectedFiles(new Set())}
            onBatchDownload={handleBatchDownload}
            canBatchDownload={canBatchDownload}
            onBatchTag={handleBatchTag}
            onBatchRetry={handleBatchRetry}
            onBatchMove={handleBatchMove}
            canBatchMove={canBatchMove}
            onBatchDelete={handleBatchDelete}
            canBatchDelete={canBatchDelete}
            onGoKnowledgeSquare={onGoKnowledgeSquare}
            canShareSpace={canShareSpace}
            versionManagementEnabled={versionManagementEnabled}
            hasSimilarSelected={hasSimilarSelected}
            onProcessSimilar={handleProcessSimilar}
            canManageMembers={canManageMembers}
            onOpenSettings={onEditSpace}
            onDeleteSpace={onDeleteSpace}
            onLeaveSpace={onLeaveSpace}
            canEditSpace={canEditSpace}
            canDeleteSpace={canDeleteSpace}
            canLeaveSpace={canLeaveSpace}
          />
        </div>
      )}

      {/* Unified toolbar — shared by the list and card views (Figma 13198:75844).
                Hidden in the full-page search view, which carries its own search box. */}
      {!isH5 && !searchMode && (
        <FileListToolbar
          spaceId={space.id}
          isRoot={currentPath.length === 0}
          onSearch={handleSearch}
          statusFilter={statusFilter}
          onFilterStatus={handleStatusFilter}
          showFilter={space.role !== SpaceRole.MEMBER}
          sortBy={sortBy}
          sortDirection={sortDirection}
          onSort={handleSort}
          viewMode={viewMode}
          setViewMode={setViewMode}
          isAllSelected={isAllSelectedOnPage}
          isIndeterminate={isSelectionIndeterminate}
          hasSelectableFiles={selectableFiles.length > 0}
          onSelectAll={() => handleSelectAll(isAllSelectedOnPage)}
        />
      )}
    </>
  );
}
