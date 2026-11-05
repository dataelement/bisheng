import { Fragment } from "react";
import { EmptyStateIllustration } from "~/components/illustrations";
import { FolderPlus, Link2 } from "lucide-react";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { FileType } from "~/api/knowledge";
import { Outlined } from "bisheng-icons";
import { Dropdown, DropdownItem, DropdownSeparator } from "@bisheng/ui";
import { FileCard } from "./FileCard";
import { FileListView } from "./FileListView";
import { SelectionPathBreadcrumb } from "./SelectionPathBreadcrumb";
import { cn } from "~/utils";
import { knowledgeUploadCapabilities } from "../knowledgeUploadCapabilities";
import type { KnowledgeSpaceModel } from "./index";
import { KnowledgeSpaceOverlays } from "./KnowledgeSpaceOverlays";
import { KnowledgeSpaceToolbar } from "./KnowledgeSpaceToolbar";
import desktopLayout from "./KnowledgeSpaceLayout.module.css";
interface KnowledgeSpacePresentationProps {
  model: KnowledgeSpaceModel;
}
export function KnowledgeSpacePresentation({
  model,
}: KnowledgeSpacePresentationProps) {
  const {
    localize,
    isH5,
    fileListScrollRevealRef,
    displayFiles,
    handleListScroll,
    searchQuery,
    searchTagIds,
    viewMode,
    selectedFiles,
    contextMenuOpen,
    setContextMenuOpen,
    contextMenuPosition,
    cardGridRef,
    cardCols,
    isAdmin,
    canManageMembers,
    versionManagementEnabled,
    setVersionMgmtFile,
    setVersionHistoryFile,
    canCreateFolder,
    canUploadFile,
    canMoveFile,
    canMoveFolder,
    isSearching,
    permissionEntryIds,
    renameEntryIds,
    deleteEntryIds,
    downloadEntryIds,
    pendingFileIds,
    listBottomStatus,
    ensureFilePermissions,
    triggerUpload,
    triggerWebLink,
    handleContentContextMenu,
    handleDragEnter,
    handleDragLeave,
    handleDragOver,
    handleDrop,
    handleSelectFile,
    handleManagePermission,
    openMove,
    dropMoveToFolder,
    handleSingleDownload,
    handlePreviewFile,
    handleOpenEditTags,
    handleDelete,
    handleSingleRetry,
    validateFileName,
    effectiveViewMode,
    suppressList,
    selectionActive,
    batchActions,
    inlineActions,
    overflowActions,
    cardDrag,
    space,
    loading,
    loadError,
    onNavigateFolder,
    onCreateFolder,
    onRenameFile,
    onCancelCreateFolder,
  } = model;
  return (
    <div
      className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-x-hidden overflow-y-hidden rounded-lg max-[767px]:overflow-hidden"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <KnowledgeSpaceToolbar model={model} />
      {/* The content scrolls while narrow-layout pagination stays below it. */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div
          className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-white"
          onContextMenu={handleContentContextMenu}
        >
          <Dropdown
            open={contextMenuOpen}
            onOpenChange={setContextMenuOpen}
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
                  <DropdownItem icon={<Link2 />} onSelect={triggerWebLink}>
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
              </>
            }
          >
            <button
              type="button"
              aria-hidden="true"
              tabIndex={-1}
              className="fixed size-0 opacity-0"
              style={{
                left: contextMenuPosition.x,
                top: contextMenuPosition.y,
              }}
            />
          </Dropdown>
          {suppressList ? (
            // Search page before any query — intentionally empty.
            <div className="min-h-0 flex-1" />
          ) : loading && displayFiles.length === 0 ? (
            // Space switching / first load: show a spinner instead of the
            // "no files here" empty illustration. The fileManager hook clears
            // `files` immediately on activeSpace change, so this branch fires
            // for the entire fetch window — the right pane no longer keeps
            // showing the previous space's contents while the API responds.
            // A folder upload no longer hits this branch: its placeholder card
            // lives in the grid (displayFiles), keeping the rest interactive.
            <div className="flex h-full flex-1 flex-col items-center justify-center gap-3 pb-[112px] pt-10 text-center text-text-3">
              <LoadingIcon className="size-20 text-primary" />
              <span className="text-sm">{localize("com_list_loading")}</span>
            </div>
          ) : loadError && displayFiles.length === 0 ? (
            <div className="flex h-full flex-1 flex-col items-center justify-center pb-[112px] pt-10 text-center">
              <p className="text-[14px] font-normal leading-6 text-text-3">
                {localize("com_list_load_failed")}
              </p>
            </div>
          ) : displayFiles.length === 0 ? (
            // pb-[112px] reserves room for the floating AI dock so the empty state
            // centers in the visible region above it, matching the card grid.
            <div className="flex h-full flex-1 flex-col items-center justify-center pb-[112px] pt-10 text-center">
              <EmptyStateIllustration className="size-[120px] mb-4" />
              <p className="text-[14px] font-normal leading-6 text-text-3">
                {searchQuery
                  ? localize("com_knowledge.no_matched_file")
                  : canUploadFile
                    ? localize("com_knowledge.no_file_here_please")
                    : localize("com_knowledge.no_file_here")}
                {canUploadFile && !searchQuery && (
                  <span
                    className="cursor-pointer text-blue-500 transition-colors hover:text-blue-400 active:text-blue-700"
                    onClick={triggerUpload}
                  >
                    {localize("com_knowledge.upload_file")}
                  </span>
                )}
              </p>
            </div>
          ) : isH5 || viewMode === "card" ? (
            <div
              ref={fileListScrollRevealRef}
              onScroll={handleListScroll}
              className="min-h-0 flex-1 overflow-y-auto scrollbar-on-scroll"
            >
              <div
                ref={cardGridRef}
                className={cn(
                  desktopLayout.grid,
                  // pb-[112px] reserves room for the bottom AI dock (40px gap + 56px input + 16px safe-area)
                  // so the last card row clears the dock with a 40px visual gap above the input top.
                  "w-full min-w-0 pb-[112px]",
                  effectiveViewMode === "list"
                    ? // H5 list stays full-bleed — its rows carry their own px-4 so a
                      // selected row's background spans the full width.
                      "grid grid-cols-1 gap-0 pt-4"
                    : "grid gap-2 px-2 pt-1",
                )}
                style={
                  effectiveViewMode === "card"
                    ? {
                        gridTemplateColumns: `repeat(${cardCols}, minmax(0, 1fr))`,
                      }
                    : undefined
                }
              >
                {displayFiles.map((file) => (
                  <div key={file.id} data-knowledge-file-item>
                    <FileCard
                      file={file}
                      userRole={space.role}
                      onEnsureFilePermissions={ensureFilePermissions}
                      permissionsLoading={pendingFileIds.has(String(file.id))}
                      isSelected={selectedFiles.has(file.id)}
                      onSelect={(selected) =>
                        handleSelectFile(file.id, selected)
                      }
                      onDownload={() => handleSingleDownload(file.id)}
                      onRename={(newName) => onRenameFile(file.id, newName)}
                      onMove={() => openMove([file])}
                      canMove={
                        file.type === FileType.FOLDER
                          ? canMoveFolder
                          : canMoveFile
                      }
                      onDelete={() => handleDelete(file.id)}
                      onEditTags={() => handleOpenEditTags(file.id)}
                      onRetry={() => handleSingleRetry(file.id)}
                      onNavigateFolder={() => onNavigateFolder(file.id)}
                      onPreview={handlePreviewFile}
                      onValidateName={(newName) =>
                        validateFileName(
                          newName,
                          file.type === FileType.FOLDER,
                          file.id,
                          !!file.isCreating,
                        )
                      }
                      onCancelCreate={onCancelCreateFolder}
                      onManagePermission={
                        permissionEntryIds.has(file.id)
                          ? () => handleManagePermission(file.id)
                          : undefined
                      }
                      versionManagementEnabled={versionManagementEnabled}
                      onOpenVersionManagement={(f) => setVersionMgmtFile(f)}
                      onOpenVersionHistory={(f) => setVersionHistoryFile(f)}
                      canManageMembers={canManageMembers}
                      canRename={renameEntryIds.has(file.id)}
                      canDelete={deleteEntryIds.has(file.id)}
                      canDownload={downloadEntryIds.has(file.id)}
                      mobileListMode={isH5}
                      highlightedTagIds={searchTagIds}
                      highlightKeyword={searchQuery}
                      cardDraggable={cardDrag.enabled}
                      onCardDragStart={cardDrag.handleDragStart(file)}
                      isFolderDragOver={cardDrag.dragOverFolderId === file.id}
                      onFolderDragOver={cardDrag.handleFolderDragOver(file)}
                      onFolderDragLeave={cardDrag.handleFolderDragLeave(file)}
                      onFolderDrop={cardDrag.handleFolderDrop(file)}
                    />
                  </div>
                ))}
                {listBottomStatus}
              </div>
            </div>
          ) : (
            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
              <FileListView
                files={displayFiles}
                onEnsureFilePermissions={ensureFilePermissions}
                onScroll={handleListScroll}
                /* Reserve 112px under the last row so the bottom AI dock leaves
                                       a 40px visual gap above the input. */
                bottomSpacing={112}
                selectedFiles={selectedFiles}
                handleSelectFile={handleSelectFile}
                isAdmin={isAdmin}
                currentUserRole={space.role}
                onDownload={(id) => handleSingleDownload(id)}
                onEditTags={(id) => handleOpenEditTags(id)}
                onRename={(id, newName) => onRenameFile(id, newName)}
                onMove={(file) => openMove([file])}
                canMoveFile={canMoveFile}
                canMoveFolder={canMoveFolder}
                onMoveToFolder={
                  canUploadFile
                    ? (folderId, items, folderName) =>
                        dropMoveToFolder(items, folderId, folderName)
                    : undefined
                }
                onDelete={(id) => handleDelete(id)}
                onRetry={(id) => handleSingleRetry(id)}
                onNavigateFolder={(id) => onNavigateFolder(id)}
                onPreview={(id) => handlePreviewFile(id)}
                onValidateName={validateFileName}
                onCancelCreate={onCancelCreateFolder}
                permissionEntryIds={permissionEntryIds}
                pendingFileIds={pendingFileIds}
                renameEntryIds={renameEntryIds}
                deleteEntryIds={deleteEntryIds}
                downloadEntryIds={downloadEntryIds}
                onManagePermission={handleManagePermission}
                versionManagementEnabled={versionManagementEnabled}
                onOpenVersionManagement={(f) => setVersionMgmtFile(f)}
                onOpenVersionHistory={(f) => setVersionHistoryFile(f)}
                canManageMembers={canManageMembers}
                highlightedTagIds={searchTagIds}
                highlightKeyword={searchQuery}
                footer={listBottomStatus}
              />
            </div>
          )}
        </div>
      </div>

      {/* Selected search results show their path breadcrumb without pagination. */}
      {!isH5 && isSearching && selectedFiles.size > 0 && (
        <div className="mt-auto w-full min-w-0 shrink-0">
          <div className="flex w-full min-w-0 flex-shrink-0 items-center gap-y-1 border-t border-border-base bg-white px-4 py-3">
            <SelectionPathBreadcrumb
              spaceId={space.id}
              spaceName={space.name}
              selectedFiles={selectedFiles}
              displayFiles={displayFiles}
            />
          </div>
        </div>
      )}

      {/* Mobile batch action bar — pinned to the bottom, replaces the AI dock while
                files are selected. Actions + permissions mirror the desktop toolbar. */}
      {selectionActive && batchActions.length > 0 && (
        /* Floating capsule: 16px from left/right/bottom, 12px inner padding. Buttons share
                   width evenly (flex-1); a 12px-tall divider sits between them. */
        <div className="absolute inset-x-0 bottom-[max(16px,env(safe-area-inset-bottom))] z-30 px-4">
          <div className="flex w-full items-center rounded-[20px] border border-border-base bg-white p-3 shadow-[0_6px_24px_0_rgba(0,17,147,0.12)]">
            {inlineActions.map((a, i) => (
              <Fragment key={a.key}>
                {i > 0 && (
                  <span className="h-3 w-px shrink-0 bg-fill-3" aria-hidden />
                )}
                <button
                  type="button"
                  onClick={a.onClick}
                  className={cn(
                    "flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap px-4 py-[5px] text-sm",
                    a.danger ? "text-[#F53F3F]" : "text-text-1",
                  )}
                >
                  <a.Icon className="size-4" />
                  {a.label}
                </button>
              </Fragment>
            ))}
            {overflowActions.length > 0 && (
              <>
                {inlineActions.length > 0 && (
                  <span className="h-3 w-px shrink-0 bg-fill-3" aria-hidden />
                )}
                <Dropdown
                  side="top"
                  align="end"
                  menu={overflowActions.map((a, i) => (
                    <Fragment key={a.key}>
                      {a.danger && i > 0 && <DropdownSeparator />}
                      <DropdownItem
                        danger={a.danger}
                        icon={<a.Icon />}
                        onSelect={a.onClick}
                      >
                        {a.label}
                      </DropdownItem>
                    </Fragment>
                  ))}
                >
                  <button
                    type="button"
                    className="flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap px-4 py-[5px] text-sm text-text-1"
                  >
                    <Outlined.More className="size-4" />
                    {localize("com_knowledge.more")}
                  </button>
                </Dropdown>
              </>
            )}
          </div>
        </div>
      )}

      <KnowledgeSpaceOverlays model={model} />
    </div>
  );
}
