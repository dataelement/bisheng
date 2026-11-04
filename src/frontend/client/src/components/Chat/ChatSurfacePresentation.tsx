import { TaskWorkspacePresentation } from "./TaskWorkspacePresentation";
import { ApiRequestFailure } from "~/components/ApiRequestFailure";
import { createPortal } from "react-dom";
import AiChatInput from "~/components/Chat/AiChatInput";
import AiChatMessages from "~/components/Chat/AiChatMessages";
import { PinnedTaskPanel } from "~/components/Linsight/Execution/PinnedTaskPanel";
import { WorkspacePanel } from "~/components/Linsight/Artifacts/WorkspacePanel";
import { TaskTurnLoadContext } from "~/components/Linsight/Execution/taskTurnLoad";
import { cn } from "~/utils";
import Landing from "./Landing";
import { DailyFeaturedApps } from "./DailyFeaturedApps";
import Presentation from "./Presentation";
import { listUploadableSpacesApi } from "~/api/messageExport";
import {
  ExportFormatSheet,
  MessageSelectionToolbar,
} from "~/components/Chat/MessageSelection";
import { AddToKnowledgeModal } from "~/pages/Subscription/Article/AddToKnowledgeModal";
import type { ChatViewModel } from "./ChatView";

interface ChatSurfacePresentationProps {
  model: ChatViewModel;
}

export function ChatSurfacePresentation({
  model,
}: ChatSurfacePresentationProps) {
  const {
    t,
    conversationId,
    inputText,
    setInputText,
    taskMode,
    bsConfig,
    chatModel,
    searchType,
    setSearchType,
    landingHasSelection,
    setLandingHasSelection,
    selectedOrgKbs,
    setSelectedOrgKbs,
    messages,
    activeConvoId,
    chatTitle,
    isLoading,
    historyError,
    isClearing,
    retryHistory,
    isStreaming,
    isParsingMedia,
    stopGenerating,
    regenerate,
    selectionState,
    isH5,
    chatContainerRef,
    isCompactLayout,
    isPhoneViewport,
    exportSheetOpen,
    setExportSheetOpen,
    importModalOpen,
    setImportModalOpen,
    handleImportSelect,
    canUseTaskMode,
    inviteQuotaBar,
    inviteQuotaDialog,
    handleSend,
    isNew,
    hasMessages,
    activeCitationMessageId,
    citationPanelElement,
    onOpenCitationPanel,
    closeCitationPanel,
    latestTaskVersionId,
    handleModelChange,
    handleModelAutoChange,
    attachmentAsk,
    retireAttachmentAsk,
    isTextAskPending,
    handleToggleTaskMode,
    taskArtifacts,
    chatAttachments,
    dockedCardRef,
    compareFreeze,
    fsMounted,
    taskLinsight,
    taskWorkspaceFiles,
    reportTaskTurnLoadFailed,
    taskWorkspaceLoadState,
    taskRunning,
    awaitingUserInput,
    handleStop,
    shareToken,
  } = model;
  return (
    <TaskTurnLoadContext.Provider value={reportTaskTurnLoadFailed}>
      <Presentation isLingsi={false}>
        {inviteQuotaDialog}
        <div className="dsh-chat-surface" data-testid="dsh-chat-surface">
          <div
            ref={chatContainerRef}
            className="relative z-10 flex h-full min-w-0 flex-1 flex-col"
          >
            {/* Layout: treat "loading an existing conversation" the same as
              "has messages" so the input stays pinned to the bottom during
              sidebar navigation (otherwise the centered welcome-page layout
              briefly floats the input up before messages arrive). */}
            {(() => {
              // A history fetch must not blank a turn that is already on screen.
              // Content-safety replies finish in one SSE tick, which used to flip
              // isLoading while the just-sent messages were still mounted.
              const loadingExistingConvo =
                isLoading && conversationId !== "new" && !hasMessages;
              // Keep input pinned to bottom as soon as a send starts (before first token lands),
              // otherwise mobile can briefly fall back to the centered landing layout.
              // An EXISTING conversation (id !== 'new') always uses the detail layout,
              // even with zero messages — opening an empty conversation must show the
              // conversation view, not the welcome/landing page (landing is /c/new only).
              // A module ask is already a conversation intent on its first render,
              // including while its model, scope or send lease is still preparing.
              const useMessagesLayout =
                hasMessages ||
                loadingExistingConvo ||
                isStreaming ||
                !isNew ||
                isTextAskPending;
              return (
                <div
                  className={cn(
                    "flex min-h-0 flex-1 flex-col relative",
                    // Landing (non-messages) layout keeps auto height on the desktop
                    // shell (≥768) so the vh-positioned welcome block + apps flow
                    // naturally. The H5 shell (≤767) needs a definite height so the
                    // landing block's `min-h-full` centering resolves against the
                    // visible scroll-area height.
                    useMessagesLayout ? "h-full" : "dsh-chat-column h-full",
                  )}
                >
                  {/* Content area: Split into Chat Main and Citation Sidebar */}
                  {loadingExistingConvo ? (
                    <div
                      className="flex h-full items-center justify-center text-text-3"
                      role="status"
                    >
                      {t("dshChat.loadingConversation")}
                    </div>
                  ) : useMessagesLayout ? (
                    <div
                      ref={compareFreeze.rowRef}
                      className="flex min-h-0 flex-1 overflow-hidden"
                    >
                      {/* Left: Chat Main (Messages + Input). F071: while the report is
                        compared with a cited source the workspace takes this column's
                        width; fade it, and pin its children's width while compare is
                        open so the hidden messages are clipped, never re-wrapped at
                        ~0px (useCompareTransitionFreeze). */}
                      <div
                        ref={compareFreeze.chatRef}
                        className={cn(
                          "dsh-chat-column relative flex min-w-0 flex-1 min-h-0 flex-col overflow-hidden transition-opacity duration-200",
                          "[&>*]:min-w-[var(--compare-freeze-w,0px)]",
                          taskArtifacts.comparing &&
                            !isCompactLayout &&
                            "pointer-events-none opacity-0",
                        )}
                        aria-hidden={
                          taskArtifacts.comparing && !isCompactLayout
                            ? true
                            : undefined
                        }
                      >
                        <div className="relative flex min-h-0 flex-1 overflow-hidden">
                          {Boolean(historyError) && (
                            <ApiRequestFailure
                              error={historyError}
                              onRetry={retryHistory}
                            />
                          )}
                          <AiChatMessages
                            messages={messages}
                            conversationId={activeConvoId}
                            title={chatTitle}
                            isLoading={false}
                            isStreaming={isStreaming}
                            shareToken={shareToken}
                            knowledgeChatLayout
                            allowExport
                            stripCitationHandlesOnCopy
                            contentWidthClassName="dsh-chat-content"
                            onRegenerate={regenerate}
                            onOpenCitationPanel={(payload) => {
                              taskArtifacts.closeWorkspace();
                              onOpenCitationPanel(payload);
                            }}
                            activeCitationMessageId={activeCitationMessageId}
                            onOpenWorkspace={() => {
                              closeCitationPanel();
                              taskArtifacts.openWorkspace();
                            }}
                            // Show the workspace entry whenever this is a task
                            // conversation (regardless of whether files exist yet);
                            // it's hidden only while the panel itself is open.
                            hasWorkspaceFiles={
                              !!latestTaskVersionId ||
                              chatAttachments.length > 0
                            }
                            workspaceOpen={taskArtifacts.open}
                            onPreviewFile={(file) => {
                              closeCitationPanel();
                              taskArtifacts.openPreview(file);
                            }}
                            hideEmptyState
                            flatMode
                          />
                          {/* Soft translucent fade so the scrolling step flow
                            dissolves into the pinned task panel / input instead of
                            ending on a hard cut. */}
                          <div aria-hidden className="dsh-chat-scroll-fade" />
                        </div>

                        {/* Input area — moved inside the left column to be independent of sidebar.
                          When F028 selection mode is active, the input is replaced by the
                          selection toolbar at 100% width. */}
                        {!shareToken &&
                          (activeConvoId &&
                          selectionState.active &&
                          selectionState.chatId === activeConvoId ? (
                            <div className="dsh-chat-composer-seat">
                              <MessageSelectionToolbar
                                chatId={activeConvoId}
                                messages={messages}
                                onExportToLocal={
                                  isH5
                                    ? () => setExportSheetOpen(true)
                                    : undefined
                                }
                                onImportToKnowledge={() =>
                                  setImportModalOpen(true)
                                }
                              />
                            </div>
                          ) : (
                            <div className="dsh-chat-composer-seat">
                              {latestTaskVersionId && (
                                <PinnedTaskPanel
                                  versionId={latestTaskVersionId}
                                />
                              )}
                              {inviteQuotaBar}
                              <AiChatInput
                                allowConfiguration={false}
                                disabled={
                                  Boolean(historyError) ||
                                  isLoading ||
                                  isClearing ||
                                  !bsConfig?.models?.length ||
                                  !!shareToken
                                }
                                sendDisabled={taskRunning}
                                isStreaming={isStreaming}
                                isParsingMedia={isParsingMedia}
                                // Parked awaiting the user → not "running": drop the Stop
                                // button (sendDisabled still blocks a new round until the
                                // current one resolves). The user replies via the
                                // ClarifyCard in the stream above, not this input.
                                taskRunning={taskRunning && !awaitingUserInput}
                                features={{
                                  taskModeEntry: canUseTaskMode,
                                  taskMode:
                                    (taskMode || taskRunning) && canUseTaskMode,
                                }}
                                onToggleTaskMode={handleToggleTaskMode}
                                placeholder={
                                  awaitingUserInput
                                    ? t("com_linsight_awaiting_reply")
                                    : taskMode
                                      ? (
                                          bsConfig as {
                                            linsightConfig?: {
                                              input_placeholder?: string;
                                            };
                                          }
                                        )?.linsightConfig?.input_placeholder ||
                                        t("com_linsight_input_placeholder")
                                      : undefined
                                }
                                onScrollToBottom={() => {}}
                                modelOptions={bsConfig?.models}
                                modelValue={chatModel.id}
                                onModelChange={handleModelChange}
                                onModelAutoChange={handleModelAutoChange}
                                onSend={handleSend}
                                onStop={handleStop}
                                value={inputText}
                                onChange={setInputText}
                                bsConfig={bsConfig}
                                selectedOrgKbs={selectedOrgKbs}
                                onSelectedOrgKbsChange={setSelectedOrgKbs}
                                searchType={searchType}
                                onSearchTypeChange={setSearchType}
                              />
                            </div>
                          ))}
                      </div>

                      {/* F035: inline workspace panel docked to the right of the chat
                        main for the latest task turn. Opens from the header entry
                        button; the file preview renders in place. Fullscreen is a
                        separate overlay (below) covering the whole route viewport.

                        The wrapper stays mounted whenever a task turn exists so
                        open/close animates its width + opacity instead of hard
                        mount/unmount. Width uses an inline clamp() (not min/max-w
                        classes) so it interpolates smoothly 0px → 46% — min-width
                        doesn't transition and would otherwise snap to 440px on the
                        first frame. The inner box keeps a min-width so the panel
                        content slides/clips rather than reflowing while it collapses.

                        The inner WorkspacePanel renders only while the fullscreen
                        overlay is NOT mounted (`!fsMounted`): the overlay is its own
                        instance, so showing both would double the preview fetch and
                        flash two toolbars during the fullscreen transition. The
                        wrapper still reserves its docked width throughout (so the
                        chat column doesn't reflow), it's just emptied — the overlay
                        collapses back onto exactly this box before unmounting.

                        ≤1023px is handled by the mobile branch below instead — the
                        docked clamp() width would otherwise squeeze the chat column
                        on small screens instead of taking over the viewport. */}
                      {(latestTaskVersionId || chatAttachments.length > 0) &&
                        !isCompactLayout && (
                          <div
                            className={cn(
                              "min-h-0 shrink-0 overflow-hidden transition-[width,opacity,padding] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]",
                              taskArtifacts.open
                                ? "p-1 opacity-100"
                                : "pointer-events-none p-0 opacity-0",
                            )}
                            // F071: compare view → the whole row (the chat column gives way).
                            style={{
                              width: !taskArtifacts.open
                                ? "0px"
                                : taskArtifacts.comparing
                                  ? "100%"
                                  : "clamp(440px, 46%, 720px)",
                            }}
                          >
                            {!fsMounted && (
                              // F071: pinned to its end width while entering/leaving compare
                              // (useCompareTransitionFreeze) so the wrapper's width animation
                              // clips the report + source instead of re-laying them out.
                              <div
                                ref={dockedCardRef}
                                className="h-full min-w-[420px]"
                              >
                                <WorkspacePanel
                                  files={[
                                    ...chatAttachments,
                                    ...taskWorkspaceFiles,
                                  ]}
                                  loading={taskWorkspaceLoadState === "loading"}
                                  loadFailed={
                                    taskWorkspaceLoadState === "failed"
                                  }
                                  versionId={latestTaskVersionId}
                                  citations={
                                    taskLinsight?.output_result?.citations
                                  }
                                  messageId={
                                    taskLinsight?.message_id ?? undefined
                                  }
                                  previewFile={taskArtifacts.previewFile}
                                  fullscreen={false}
                                  sourcePreview={taskArtifacts.sourcePreview}
                                  onOpenSource={taskArtifacts.openSource}
                                  onCloseSource={taskArtifacts.closeSource}
                                  onPreview={taskArtifacts.openPreview}
                                  onBack={taskArtifacts.backToList}
                                  onClose={taskArtifacts.closeWorkspace}
                                  onToggleFullscreen={
                                    taskArtifacts.toggleFullscreen
                                  }
                                />
                              </div>
                            )}
                          </div>
                        )}

                      {/* F035: mobile (≤1023px) workspace panel — mirrors the daily-mode
                        citation panel's responsive tiers. Renders only while open
                        (hard mount/unmount, no width reservation, so the chat column
                        keeps full width behind it). The fullscreen toggle is hidden
                        (`hideFullscreenToggle`) since the panel already takes over the
                        screen / docks as a drawer here. `fullscreen` is passed so the
                        inner card drops its own border/radius — the overlay/drawer
                        container provides the chrome. */}
                      {(latestTaskVersionId || chatAttachments.length > 0) &&
                        isCompactLayout &&
                        taskArtifacts.open &&
                        (() => {
                          const mobilePanel = (
                            <WorkspacePanel
                              files={[
                                ...chatAttachments,
                                ...taskWorkspaceFiles,
                              ]}
                              loading={taskWorkspaceLoadState === "loading"}
                              loadFailed={taskWorkspaceLoadState === "failed"}
                              versionId={latestTaskVersionId}
                              citations={taskLinsight?.output_result?.citations}
                              messageId={taskLinsight?.message_id ?? undefined}
                              previewFile={taskArtifacts.previewFile}
                              fullscreen
                              hideFullscreenToggle
                              sourcePreview={taskArtifacts.sourcePreview}
                              compareLayout="tabs"
                              onOpenSource={taskArtifacts.openSource}
                              onCloseSource={taskArtifacts.closeSource}
                              onPreview={taskArtifacts.openPreview}
                              onBack={taskArtifacts.backToList}
                              onClose={taskArtifacts.closeWorkspace}
                              onToggleFullscreen={
                                taskArtifacts.toggleFullscreen
                              }
                            />
                          );

                          // ≤576: full-screen overlay flush to the viewport edges.
                          if (isPhoneViewport) {
                            return (
                              <div className="fixed inset-0 z-[120] flex h-[100dvh] min-h-0 flex-col overflow-hidden overscroll-contain bg-[#FBFBFB]">
                                {mobilePanel}
                              </div>
                            );
                          }

                          // 768–1023: flex-inline would interleave with HeaderTitle / main
                          // stacking contexts; portal a fixed right drawer to <body> at a
                          // higher z so it clears the chrome (mirrors the citation panel).
                          if (!isH5) {
                            return createPortal(
                              <div className="fixed inset-y-0 right-0 z-[150] flex min-h-0 flex-col overflow-hidden rounded-tl-xl border-l border-border-base bg-[#FBFBFB] shadow-[-8px_0_28px_rgba(0,0,0,0.1)] animate-in slide-in-from-right duration-300 w-[min(480px,100vw)]">
                                {mobilePanel}
                              </div>,
                              document.body,
                            );
                          }

                          // 577–767: right drawer docked to the viewport edge (z above
                          // MobileNav z-60), full height, slide-in from the right.
                          return (
                            <div className="dsh-chat-preview-modal fixed inset-0 z-[120] flex h-[100dvh] min-h-0 flex-col overflow-hidden overscroll-contain bg-bg-page">
                              {mobilePanel}
                            </div>
                          );
                        })()}

                      {citationPanelElement}
                    </div>
                  ) : (
                    /* Landing page branch — the welcome block is pinned to the
                     region's vertical center via absolute positioning, so its
                     position is INDEPENDENT of whether recommended apps exist
                     (apps just flow below it and scroll if they overflow).

                     ≥768 (desktop): center at 45vh; apps sit 40px below via
                     `paddingTop: calc(45vh + halfBlock + 40px)`.

                     ≤767 (H5 shell): can't use `vh` (MobileNav + Banner sit above
                     this scroll container). The parent is a definite `h-full` box,
                     so the block centers at 35% of it (`top-[35%]`) and the apps
                     offset is computed in px from the measured region height
                     (landingParentHeight) — a `%` paddingTop would resolve against
                     width, not height. */
                    <div className="dsh-chat-landing">
                      {/* Welcome message + input, absolutely centered. ≥768 at 45vh,
                        ≤767 at 40% of the definite-height region. */}
                      <div className="dsh-chat-hero">
                        {/* F035 Track H (P5): daily/task mode switch removed —
                          task mode is reached via the sidebar "new task" entry
                          and the input-bar task-mode button. */}
                        <Landing
                          isNew={isNew}
                          hideSubtitle={landingHasSelection}
                          onStarterClick={setInputText}
                        />

                        {/* Input area for landing page */}
                        {!shareToken && (
                          <div className="w-full">
                            {inviteQuotaBar}
                            <AiChatInput
                              elevated
                              disabled={
                                Boolean(historyError) ||
                                isLoading ||
                                isClearing ||
                                !bsConfig?.models?.length ||
                                !!shareToken
                              }
                              sendDisabled={taskRunning}
                              isStreaming={isStreaming}
                              isParsingMedia={isParsingMedia}
                              features={{
                                taskModeEntry: canUseTaskMode,
                                taskMode: taskMode && canUseTaskMode,
                              }}
                              onToggleTaskMode={handleToggleTaskMode}
                              placeholder={
                                taskMode
                                  ? (
                                      bsConfig as {
                                        linsightConfig?: {
                                          input_placeholder?: string;
                                        };
                                      }
                                    )?.linsightConfig?.input_placeholder ||
                                    t("com_linsight_input_placeholder")
                                  : undefined
                              }
                              onScrollToBottom={() => {}}
                              modelOptions={bsConfig?.models}
                              modelValue={chatModel.id}
                              onModelChange={handleModelChange}
                              onModelAutoChange={handleModelAutoChange}
                              onSend={handleSend}
                              onStop={stopGenerating}
                              value={inputText}
                              onChange={setInputText}
                              bsConfig={bsConfig}
                              selectedOrgKbs={selectedOrgKbs}
                              onSelectedOrgKbsChange={setSelectedOrgKbs}
                              searchType={searchType}
                              onSearchTypeChange={setSearchType}
                              onSelectionPresenceChange={setLandingHasSelection}
                              attachmentAsk={attachmentAsk}
                              onAttachmentAskDone={retireAttachmentAsk}
                            />
                          </div>
                        )}
                      </div>

                      {/* Recommended apps: 40px below the centered block, so the
                        block's own position never shifts when apps appear.
                        offset = (block center) + (half block height) + 40px.
                        ≥768 block center = 45vh; ≤767 = 40% of the measured region
                        height (px, since `vh`/`%`-padding don't work here). */}
                      <DailyFeaturedApps t={t} />
                    </div>
                  )}
                </div>
              );
            })()}

            {/* F035: fullscreen workspace preview — portaled to <body> + fixed so it
              escapes chatContainer and can cover the sidebar conversation list.
              Separate instance from the inline panel above (only one is ever
              mounted, so the preview never double fetches). The box animates between
              the docked panel's measured box (padding 0) and the content card's box
              (padding 4px): the gray border slides out from the docked 4px margin to
              the card edge while the inner content — and the toolbar buttons — stay
              fixed (box grows +4px exactly as padding grows +4px). Fills the card
              edge-to-edge in #FBFBFB (the 4px is overlay bg, not a white ring) with
              the border on the outermost ring. Unmounts on transitionEnd.
              Desktop-only (≥1024px): below that the panel is already an overlay /
              drawer (mobile branch above), so the fullscreen overlay is suppressed
              and resizing desktop→mobile tears any open overlay down cleanly. */}
            <TaskWorkspacePresentation model={model} />
          </div>

          {/* F028: portal-style sheets/modals (the floating toolbar lives next to the input) */}
          {activeConvoId &&
            selectionState.active &&
            selectionState.chatId === activeConvoId && (
              <>
                <ExportFormatSheet
                  open={exportSheetOpen}
                  onOpenChange={setExportSheetOpen}
                  chatId={activeConvoId}
                  messages={messages}
                />
                <AddToKnowledgeModal
                  open={importModalOpen}
                  onOpenChange={setImportModalOpen}
                  mode="channel_sync"
                  dataSourceApi={listUploadableSpacesApi}
                  onSyncSelect={handleImportSelect}
                />
              </>
            )}
        </div>
      </Presentation>
    </TaskTurnLoadContext.Provider>
  );
}
