import { WorkbenchMenuButton } from "~/layouts/WorkbenchMenuButton";
import { knowledgePathWithTab } from "./knowledgeListNavigation";
import { ApiRequestFailure } from "~/components/ApiRequestFailure";
import { createPortal } from "react-dom";
import { Plus } from "lucide-react";
import { EmptyStateIllustration } from "~/components/illustrations";
import { Outlined } from "bisheng-icons";
import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui";
import { NotificationSeverity } from "~/common";
import { KnowledgeSpaceSidebar } from "./sidebar/KnowledgeSpaceSidebar";
import { KnowledgeHomePage } from "./KnowledgeHomePage";
import { MODULE_PAGE_DESKTOP_COLUMN, MODULE_PAGE_DESKTOP_FRAME } from "~/components/ModuleHome";
import desktopLayout from "./SpaceDetail/KnowledgeSpaceLayout.module.css";
import { KnowledgeSpaceContent } from "./SpaceDetail";
import { KnowledgeAiBottomDock } from "./SpaceDetail/AiChat/KnowledgeAiBottomDock";
import { KnowledgeSpacePreviewDrawer } from "./KnowledgeSpacePreviewDrawer";
import KnowledgeSquare from "./KnowledgeSquare";
import {
  FROSTED_GLASS_CLASS,
  FROSTED_GLASS_ENABLED,
} from "~/utils/frostedGlass";
import { cn } from "~/utils";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import type { KnowledgePageModel } from "./index";
interface KnowledgePageContentProps {
  model: KnowledgePageModel;
}

export function KnowledgePageContent({ model }: KnowledgePageContentProps) {
  const {
    localize,
    menuNames,
    bishengConfig,
    uploadSizeLimits,
    isH5,
    previewNavTimerRef,
    activeSpace,
    showKnowledgeSquare,
    setShowKnowledgeSquare,
    isDragging,
    dragError,
    spaceListDrawerOpen,
    setSpaceListDrawerOpen,
    fileSelectionActive,
    setFileSelectionActive,
    knowledgeSearchMode,
    setKnowledgeSearchMode,
    mobileHeadIconBtnClassName,
    setSystemMenuOpen,
    showToast,
    navigate,
    location,
    previewSpaceId,
    detailSpaceId,
    previewDrawerOpen,
    setPreviewDrawerOpen,
    squarePreviewSpaceId,
    setSquarePreviewSpaceId,
    squarePreviewSpace,
    setSquarePreviewSpace,
    squarePreviewDrawerOpen,
    setSquarePreviewDrawerOpen,
    squareStatusOverride,
    setSquareStatusOverride,
    knowledgePluginGate,
    knowledgePluginEnabled,
    spacesError,
    retrySpaces,
    hasNoSpace,
    fileManager,
    fileUpload,
    handleSpaceSelect,
    handleActiveSpaceUpdate,
    handleCreateSpace,
    handleSpaceSettings,
    handleDeleteActiveSpace,
    handleLeaveActiveSpace,
    handleDragStateChange,
    handleLeaveSquare,
    handleOpenSquare,
  } = model;
  if (knowledgePluginGate === "disabled") return null;
  if (showKnowledgeSquare) {
    return (
      // Mobile: the MainLayout shell is h-auto/overflow-visible and html/body
      // scrolling is globally disabled (WebView bottom-strip fix in index.html),
      // so `h-full` collapses and the square's inner scroller never scrolls.
      // Pin the wrapper to 100dvh on mobile so the inner overflow-y-auto works.
      <div className="relative flex h-full min-h-0 max-[767px]:h-[100dvh]">
        <KnowledgeSquare
          onBack={handleLeaveSquare}
          title={localize("com_knowledge.explore_square")}
          subtitle={localize("com_knowledge.explore_more_spaces")}
          searchPlaceholder={localize("com_knowledge.search_space_placeholder")}
          emptyText={localize("com_knowledge.no_matched_space")}
          joinToastPrefix={localize("com_knowledge.applied_to_join_space")}
          onPreviewSpace={(space) => {
            setSquarePreviewSpaceId(space.id);
            setSquarePreviewSpace(space);
            setSquarePreviewDrawerOpen(true);
          }}
          statusOverride={squareStatusOverride}
          onSquareStatusChange={(id, status) => {
            setSquareStatusOverride((prev) => {
              if (prev[String(id)] === status) {
                return prev;
              }
              return { ...prev, [String(id)]: status };
            });
          }}
        />
        <KnowledgeSpacePreviewDrawer
          spaceId={squarePreviewSpaceId}
          initialSpace={
            squarePreviewSpace
              ? {
                  ...squarePreviewSpace,
                  squareStatus:
                    squareStatusOverride[String(squarePreviewSpace.id)] ??
                    squarePreviewSpace.squareStatus,
                }
              : null
          }
          open={squarePreviewDrawerOpen}
          onOpenChange={(open) => {
            setSquarePreviewDrawerOpen(open);
            if (!open) {
              setSquarePreviewSpaceId(undefined);
              setSquarePreviewSpace(null);
            }
          }}
          onSquareStatusChange={(id, status) => {
            setSquareStatusOverride((prev) => {
              if (prev[String(id)] === status) {
                return prev;
              }
              return { ...prev, [String(id)]: status };
            });
          }}
        />
      </div>
    );
  }

  return (
    <div className="relative flex h-full min-h-0">
      {/* Drag and Drop Overlay. Frosted glass here is the sanctioned exception
                (single full-screen overlay, only while dragging) and is gated by the
                global FROSTED_GLASS_ENABLED switch — see ~/utils/frostedGlass. */}
      {isDragging && (
        <div
          className={`absolute inset-0.5 z-[100] rounded-xl flex flex-col items-center justify-center pointer-events-none transition-all duration-300 ${FROSTED_GLASS_ENABLED ? FROSTED_GLASS_CLASS : ""} ${dragError ? "border border-dashed border-red-500 bg-[rgba(255,236,232,0.7)]" : "border border-dashed bg-[rgba(255,255,255,0.7)]"}`}
        >
          <div
            className={`flex flex-col items-center justify-center p-8 rounded-2xl ${dragError ? "bg-transparent" : "bg-white/50"}`}
          >
            {dragError ? (
              <p className="text-xl font-medium text-red-500 mb-2">
                {dragError}
              </p>
            ) : (
              <p className="text-xl font-medium text-[#161616] mb-2">
                {localize("com_knowledge.drop_to_upload")}
              </p>
            )}
            <div className="text-center text-xs text-gray-400 leading-5">
              <p>{localize("com_knowledge.supported_formats")}</p>
              <p>{localize("com_knowledge.format_list")}</p>
              <p>
                {localize(
                  bishengConfig?.enable_media_upload
                    ? "com_knowledge.upload_size_limits_hint"
                    : "com_knowledge.upload_size_limit_hint_without_media",
                  {
                    docMax: uploadSizeLimits.defaultMaxMB,
                    mediaMax: uploadSizeLimits.mediaMaxMB,
                  },
                )}
              </p>
              <p>{localize("com_knowledge.max_upload_50_short")}</p>
            </div>
          </div>
        </div>
      )}

      {/* No in-module space list column: the workbench sidebar is global now, so every
                shell is list-page-first — /knowledge is the home (KnowledgeHomePage on desktop,
                the full-page list on mobile) and a space opens as its own page. The column's
                auto-select-first effect must not come back: it would bypass that home. */}

      {/* File page: the top Title ▾ opens this drawer to switch spaces (unchanged behaviour). */}
      {/* Kept mounted while a space is active and toggled via `hidden` (not unmounted) so
                the dropdown preserves its last state — cycled type / scroll — across re-opens. */}
      {isH5 && activeSpace && typeof document !== "undefined"
        ? createPortal(
            <div
              className={cn(
                "fixed inset-x-0 bottom-0 z-[80] flex flex-col bg-white",
                !spaceListDrawerOpen && "hidden",
              )}
              style={{ top: "calc(env(safe-area-inset-top, 0px) + 52px)" }}
              role="dialog"
              aria-modal="true"
              aria-hidden={!spaceListDrawerOpen}
              aria-label={menuNames.knowledge}
            >
              <div className="min-h-0 flex-1 overflow-hidden">
                <KnowledgeSpaceSidebar
                  mobileDrawerMode
                  compactMode
                  onDrawerClose={() => setSpaceListDrawerOpen(false)}
                  onNavigateAway={() => setSpaceListDrawerOpen(false)}
                  activeSpaceId={activeSpace?.id}
                  onSpaceSelect={(space) => {
                    handleSpaceSelect(space);
                    setSpaceListDrawerOpen(false);
                  }}
                  onActiveSpaceUpdate={handleActiveSpaceUpdate}
                  onCreateSpace={() => {
                    handleCreateSpace();
                    setSpaceListDrawerOpen(false);
                  }}
                  onSpaceSettings={(space) => {
                    handleSpaceSettings(space);
                    setSpaceListDrawerOpen(false);
                  }}
                  onKnowledgeSquare={() => {
                    setShowKnowledgeSquare(true);
                    setSpaceListDrawerOpen(false);
                  }}
                />
              </div>
              {/* Fixed bottom actions — go-to-square (left) + create space (right) */}
              <div className="flex shrink-0 items-center gap-3 bg-white px-4 pt-4 pb-[calc(env(safe-area-inset-bottom,0px)+16px)]">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setShowKnowledgeSquare(true);
                    setSpaceListDrawerOpen(false);
                  }}
                  className="h-8 flex-1 gap-1 rounded-md border border-[#e3e3e3] bg-white px-3 py-[5px] text-sm font-normal leading-[22px] text-[#666666] hover:bg-[#F4F4F4]"
                >
                  <Outlined.BlocksAndArrows className="size-4" />
                  {localize("com_knowledge.go_to_square")}
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => {
                    handleCreateSpace();
                    setSpaceListDrawerOpen(false);
                  }}
                  className="h-8 flex-1 gap-1 rounded-md bg-blue-100 px-3 py-[5px] text-sm font-normal leading-[22px] text-blue-main hover:bg-blue-200"
                >
                  <Plus className="size-4" />
                  {localize("com_knowledge.create_knowledge_space")}
                </Button>
              </div>
            </div>,
            document.body,
          )
        : null}

      {activeSpace ? (
        <div
          className={cn(
            "flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden",
            MODULE_PAGE_DESKTOP_FRAME,
            desktopLayout.frame,
            // Mobile needs a DEFINITE viewport height (the KeepAlive shell is h-auto,
            // so percentage chains collapse): without it the content grows with the
            // file count and the absolute-bottom AI dock drifts / the layout cramps.
            isH5 ? "h-[100dvh]" : "h-full",
          )}
        >
          {/* Mobile top bar now lives inside KnowledgeSpaceContent (it owns search/sort/upload). */}
          {/* `relative` anchors the bottom AI dock; the content scrolls within its own container while the dock overlays the bottom. */}
          <div
            className={cn(
              MODULE_PAGE_DESKTOP_COLUMN,
              desktopLayout.column,
              "relative flex min-h-0 flex-1 flex-col overflow-hidden bg-white shadow-[0px_4px_20px_0px_rgba(0,17,147,0.05)]",
            )}
          >
            <KnowledgeSpaceContent
              space={activeSpace}
              files={fileManager.files}
              total={fileManager.total}
              onLoadMore={fileManager.loadMore}
              hasMore={fileManager.hasMore}
              loading={fileManager.loading}
              loadError={fileManager.loadError}
              loadMoreError={fileManager.loadMoreError}
              onSearch={fileManager.handleSearch}
              onFilterStatus={fileManager.setStatusFilter}
              onSort={(sortBy, direction) => {
                if (!sortBy || !direction) return;
                fileManager.handleSort(sortBy, direction);
              }}
              onNavigateFolder={(folderId?: string) => {
                // Drive folder navigation through the URL (like the sidebar tree
                // does) so the URL stays the single source of truth: useFileManager's
                // initialFolderId watcher syncs the content pane, and the sidebar
                // tree auto-expands/highlights to the same folder. Setting folder
                // state directly would leave the sidebar out of sync.
                const base = `/knowledge/space/${activeSpace.id}`;
                navigate(
                  knowledgePathWithTab(
                    folderId ? `${base}/folder/${folderId}` : base,
                    location.search,
                  ),
                );
              }}
              onUploadFile={fileUpload.handleUploadFile}
              onUploadFolder={fileUpload.handleUploadFolder}
              onCreateFolder={fileUpload.handleCreateFolder}
              onDownloadFile={() =>
                showToast({
                  message: localize("com_knowledge.start_download"),
                  severity: NotificationSeverity.SUCCESS,
                })
              }
              onRenameFile={fileUpload.handleRenameFile}
              onDeleteFile={fileUpload.handleDeleteFile}
              onBatchDeleteFiles={fileUpload.handleBatchDelete}
              onEditTags={fileUpload.handleEditTags}
              onRetryFile={() =>
                showToast({
                  message: localize("com_knowledge.retry_feature_dev"),
                  severity: NotificationSeverity.INFO,
                })
              }
              currentPath={fileManager.currentPath}
              currentFolderId={fileManager.currentFolderId}
              onDragStateChange={handleDragStateChange}
              uploadingFiles={fileUpload.uploadingFiles}
              creatingFolder={fileUpload.creatingFolder}
              uploadingFolder={fileUpload.uploadingFolder}
              onCancelCreateFolder={fileUpload.handleCancelCreateFolder}
              onCreateSpace={handleCreateSpace}
              onGoKnowledgeSquare={handleOpenSquare}
              onOpenSystemMenu={() => setSystemMenuOpen(true)}
              onToggleSpaceList={() => setSpaceListDrawerOpen((o) => !o)}
              spaceListOpen={spaceListDrawerOpen}
              onEditSpace={() => handleSpaceSettings(activeSpace)}
              onDeleteSpace={() => handleDeleteActiveSpace(activeSpace)}
              onLeaveSpace={() => handleLeaveActiveSpace(activeSpace)}
              onOpenSearch={() => setKnowledgeSearchMode(true)}
              searchMode={knowledgeSearchMode}
              onCloseSearch={() => setKnowledgeSearchMode(false)}
              onSelectionActiveChange={setFileSelectionActive}
            />
            {/* Hide the AI dock during a mobile batch selection (the batch action bar
                            takes the bottom slot) and in search mode (the search page has no dock). */}
            {!fileSelectionActive && !knowledgeSearchMode && (
              <KnowledgeAiBottomDock
                key={String(activeSpace.id)}
                spaceId={String(activeSpace.id)}
                spaceName={activeSpace.name}
              />
            )}
          </div>
        </div>
      ) : isH5 ? (
        /* Mobile: standalone full-page space list. Tapping a space navigates to
                   /knowledge/space/:id (handled by handleSpaceSelect) → the file page. */
        <div className="flex h-[100dvh] min-h-0 w-full flex-col overflow-hidden bg-white">
          <div className="shrink-0 rounded-t-xl bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)]">
            <div className="flex h-11 w-full min-w-0 items-center justify-between gap-3 px-4">
              <WorkbenchMenuButton
                type="button"
                aria-label={localize("com_nav_open_sidebar")}
                onClick={() => setSystemMenuOpen(true)}
                className={mobileHeadIconBtnClassName}
              >
                <Outlined.SidebarMenu className="size-5" />
              </WorkbenchMenuButton>
              <span className="min-w-0 flex-1 truncate text-center text-[16px] font-medium leading-6 text-text-1">
                {menuNames.knowledge}
              </span>
              <span className="size-5 shrink-0" aria-hidden />
            </div>
          </div>
          {spacesError ? (
            <ApiRequestFailure error={spacesError} onRetry={retrySpaces} />
          ) : hasNoSpace ? (
            /* Empty state: no space in any section. Drop the section list +
                           bottom bar and center an illustration with two actions
                           (mirrors the subscription channel empty state). */
            <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-6 pb-16">
              <EmptyStateIllustration className="size-[120px]" />
              <p className="mt-6 text-[14px] leading-6 text-text-3">
                {localize("com_knowledge.no_related_content_you_can")}
              </p>
              <div className="mt-5 flex items-center gap-4">
                <button
                  type="button"
                  onClick={handleOpenSquare}
                  className="h-8 rounded-md border border-border-base bg-white px-4 text-[14px] leading-[22px] text-text-2 transition-colors active:border-blue-500 active:text-blue-500"
                >
                  {localize("com_knowledge.go_to_square")}
                </button>
                <button
                  type="button"
                  onClick={handleCreateSpace}
                  className="h-8 rounded-md bg-blue-500 px-4 text-[14px] leading-[22px] text-white transition-colors active:bg-blue-600 btn-brand-primary"
                >
                  {localize("com_knowledge.create_knowledge_space")}
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="min-h-0 flex-1 overflow-hidden">
                <KnowledgeSpaceSidebar
                  mobilePageMode
                  onSpaceSelect={handleSpaceSelect}
                  onActiveSpaceUpdate={handleActiveSpaceUpdate}
                  onCreateSpace={handleCreateSpace}
                  onSpaceSettings={handleSpaceSettings}
                  onKnowledgeSquare={handleOpenSquare}
                />
              </div>
              {/* Fixed bottom go-to-square — reuses the PC sidebar button style */}
              <div className="shrink-0 bg-white px-4 pt-4 pb-[calc(env(safe-area-inset-bottom,0px)+16px)]">
                <Button
                  variant="secondary"
                  onClick={handleOpenSquare}
                  className="h-8 w-full gap-1 rounded-md border border-[#e3e3e3] bg-white px-3 py-[5px] text-sm font-normal leading-[22px] text-[#666666] hover:bg-[#F4F4F4]"
                >
                  <Outlined.BlocksAndArrows className="size-4" />
                  {localize("com_knowledge.go_to_square")}
                </Button>
              </div>
            </>
          )}
        </div>
      ) : detailSpaceId ? (
        spacesError ? (
          <ApiRequestFailure error={spacesError} onRetry={retrySpaces} />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center py-10 text-center text-text-3">
            <LoadingIcon className="size-20 text-primary" />
          </div>
        )
      ) : (
        <KnowledgeHomePage
          enabled={knowledgePluginEnabled}
          category={
            (["department", "created", "joined"] as const).find(
              (tab) => tab === new URLSearchParams(location.search).get("tab"),
            ) ?? "all"
          }
          onCategoryChange={(tab) => {
            const params = new URLSearchParams(location.search);
            params.set("tab", tab);
            navigate(
              { pathname: location.pathname, search: params.toString() },
              { replace: true },
            );
          }}
          onSpaceSelect={handleSpaceSelect}
          onCreateSpace={handleCreateSpace}
          onSpaceSettings={handleSpaceSettings}
          onKnowledgeSquare={handleOpenSquare}
        />
      )}

      <KnowledgeSpacePreviewDrawer
        spaceId={previewSpaceId}
        open={previewDrawerOpen}
        onOpenChange={(open) => {
          setPreviewDrawerOpen(open);
          if (previewNavTimerRef.current) {
            clearTimeout(previewNavTimerRef.current);
            previewNavTimerRef.current = null;
          }

          if (!open) {
            previewNavTimerRef.current = setTimeout(() => {
              navigate(knowledgePathWithTab("/knowledge", location.search), {
                replace: true,
              });
            }, 400);
          }
        }}
      />

      {/* Duplicate file overwrite confirmation dialog */}
      <Dialog
        open={fileUpload.duplicateFiles.length > 0}
        onOpenChange={(open) => !open && fileUpload.handleDuplicateSkip()}
      >
        <DialogContent
          className="sm:max-w-[460px]"
          onPointerDownOutside={(e) => e.preventDefault()}
        >
          <DialogHeader>
            <DialogTitle>
              {localize("com_knowledge.duplicate_file_title")}
            </DialogTitle>
          </DialogHeader>
          <ul className="overflow-y-auto max-h-[300px] py-2 space-y-1.5">
            {fileUpload.duplicateFiles.map((entry, idx) => {
              const name = entry.fileName;
              const ext = name.includes(".")
                ? name.slice(name.lastIndexOf("."))
                : "";
              const base = name.includes(".")
                ? name.slice(0, name.lastIndexOf("."))
                : name;
              const truncatedName =
                base.length > 10 ? base.slice(0, 10) + "...." + ext : name;
              const path = entry.oldFileLevelPath || "";
              return (
                <li key={idx} className="py-1 text-sm text-gray-700">
                  <span title={name}>{truncatedName}</span>
                  {path && <span className="ml-1 text-gray-400">({path})</span>}
                </li>
              );
            })}
          </ul>
          <DialogFooter>
            <Button
              variant="outline"
              className="h-8"
              onClick={fileUpload.handleDuplicateSkip}
            >
              {localize("com_knowledge.duplicate_cancel")}
            </Button>
            <Button
              className="h-8"
              onClick={fileUpload.handleDuplicateOverwrite}
            >
              {localize("com_knowledge.duplicate_replace")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
