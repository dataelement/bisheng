import { ApiRequestFailure } from "~/components/ApiRequestFailure";
import { Tooltip as SharedTooltip, TooltipProvider as SharedTooltipProvider } from "@bisheng/ui";
import { useEffect, useRef, useState } from "react";
import { Outlined } from "bisheng-icons";


import AiChatMessages from "~/components/Chat/AiChatMessages";
import { ArticleQAIllustration } from "~/components/illustrations";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { useAuthContext } from "~/hooks/AuthContext";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import useChannelChat from "~/hooks/useChannelChat";
import { readAdminDefaultModelId, type ChatModelOption } from "~/hooks/useChatModelResolution";
import { useSurfaceModel } from "~/hooks/useSurfaceModel";
import type { Article } from "~/api/channels";
import { ArticleAskBar } from "./ArticleAskBar";
import { DockInput, type ModelSelectProps } from "./ArticleDockInput";
import { useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider";
import { useConfirm } from "~/Providers";
import { cn } from "~/utils";

interface ArticleAiDockProps {
  /** ES article document id — drives the channel chat. */
  articleDocId: string;
  /** The article itself. With it, desktop hands questions to the main chat (ArticleAskBar);
   *  without it there is nothing to attach, so the in-place dock stays. */
  article?: Article;
}

function useDockModel(): ModelSelectProps {
  const { user } = useAuthContext();
  const { data: bsConfig } = useGetBsConfig();
  const { data: workbenchCfg } = useGetWorkbenchModelsQuery();
  const { model, selectModel, repairModel } = useSurfaceModel({
    userId: user?.id,
    surfaceKey: "articleAi",
    models: (bsConfig?.models || []) as ChatModelOption[],
    adminDefaultId: readAdminDefaultModelId(workbenchCfg, "daily"),
  });
  return {
    options: bsConfig?.models,
    value: model.id,
    disabled: !bsConfig?.models?.length,
    onChange: selectModel,
    onAutoChange: repairModel,
  };
}

/**
 * Entry point. Desktop: ArticleAskBar — the question is answered on the 对话 page, so its
 * history joins the workbench conversation list. Mobile: the in-place dock, unchanged.
 */
export function ArticleAiDock({ articleDocId, article }: ArticleAiDockProps) {
  const isH5 = usePrefersMobileLayout();
  const model = useDockModel();
  if (!isH5 && article) return <ArticleAskBar article={article} model={model} />;
  return <ArticleAiInPlaceDock articleDocId={articleDocId} />;
}

/**
 * Subscription article AI dock (PC). A persistent input bar pinned to the bottom of
 * the article-detail pane. Typing stays in place; the first send slides a chat panel
 * (header + messages) UP from above the input — the input itself never moves, it just
 * loses its box and gains a divider line. Collapsing (down-chevron) hides the panel
 * again without losing the conversation.
 *
 * Self-contained (channel chat only) so the shared AiAssistantPanel — still used by
 * the knowledge-space file preview — stays untouched.
 */
function ArticleAiInPlaceDock({ articleDocId }: Pick<ArticleAiDockProps, "articleDocId">) {
  const localize = useLocalize();
  const confirm = useConfirm();
  const { user } = useAuthContext();
  const { data: bsConfig } = useGetBsConfig();
  // Admin-customizable assistant name; empty/absent falls back to the localized default.
  const assistantTitle =
    bsConfig?.subscription?.assistant_name?.trim() || localize("com_subscription.ai_assistant");
  // Own model selection, isolated from /c: picking a model here must not
  // change what the main chat shows (see useSurfaceModel).
  const { data: workbenchCfg } = useGetWorkbenchModelsQuery();
  const {
    model: surfaceModel,
    selectModel,
    repairModel,
  } = useSurfaceModel({
    userId: user?.id,
    surfaceKey: "articleAi",
    models: (bsConfig?.models || []) as ChatModelOption[],
    adminDefaultId: readAdminDefaultModelId(workbenchCfg, "daily"),
  });
  const [open, setOpen] = useState(false);
  const [inputText, setInputText] = useState("");
  const isH5 = usePrefersMobileLayout();
  /** Tracks visual viewport so the mobile-expanded panel sits above the virtual keyboard
   *  and follows any iOS-Safari scroll that happens when the focused input is brought into view. */
  const [viewportHeight, setViewportHeight] = useState<number | null>(null);
  const [viewportOffsetTop, setViewportOffsetTop] = useState(0);
  /** Drives the grey overlay. Two signals push it open/closed:
   *   - textarea focus/blur via `DockInput.onFocusChange` — instant response on tap and
   *     on the keyboard's "完成"/Done button (which fires blur).
   *   - visualViewport restoring after having been shrunk — catches the keyboard's
   *     "关闭"/dismiss button which hides the keyboard WITHOUT blurring the textarea.
   *   We don't drive it ON from viewport alone because the keyboard animation lags the
   *   focus event by ~250ms and we want the overlay up immediately on tap. */
  const [keyboardVisible, setKeyboardVisible] = useState(false);
  const peakVvHeightRef = useRef(0);
  const keyboardUpRef = useRef(false);

  useEffect(() => {
    if (!isH5 || typeof window === "undefined") return;
    const vv = window.visualViewport;
    if (!vv) return;
    const sync = () => {
      setViewportHeight(vv.height);
      setViewportOffsetTop(vv.offsetTop);
      if (vv.height > peakVvHeightRef.current) peakVvHeightRef.current = vv.height;
      if (peakVvHeightRef.current === 0) return;
      const ratio = vv.height / peakVvHeightRef.current;
      if (ratio < 0.6) {
        keyboardUpRef.current = true;
      } else if (ratio > 0.85 && keyboardUpRef.current) {
        keyboardUpRef.current = false;
        setKeyboardVisible(false);
        // Force blur the active textarea/input so the next tap re-fires the focus event.
        // iOS WeChat WKWebView's "收起" keyboard button hides the keyboard but keeps focus
        // on the textarea, so the next tap is a no-op (no focus change → no onFocus).
        const active = document.activeElement;
        if (active && (active.tagName === "TEXTAREA" || active.tagName === "INPUT")) {
          (active as HTMLElement).blur();
        }
      }
    };
    sync();
    vv.addEventListener("resize", sync);
    vv.addEventListener("scroll", sync);
    // window.resize fires when WeChat WKWebView reflows the layout after keyboard
    // dismissal — an extra backup signal alongside visualViewport.resize.
    window.addEventListener("resize", sync);
    return () => {
      vv.removeEventListener("resize", sync);
      vv.removeEventListener("scroll", sync);
      window.removeEventListener("resize", sync);
    };
  }, [isH5]);

  const {
    messages,
    conversationId,
    title,
    isLoading,
    historyError,
    isClearing,
    retryHistory,
    isStreaming,
    sendMessage,
    clearConversation,
    regenerate,
  } = useChannelChat(articleDocId, surfaceModel);

  const modelOptions = bsConfig?.models;
  const model: ModelSelectProps = {
    options: modelOptions,
    value: surfaceModel.id,
    disabled: !modelOptions?.length,
    onChange: selectModel,
    onAutoChange: repairModel,
  };

  const handleSend = (text: string) => {
    sendMessage(text);
    setInputText("");
    if (!open) setOpen(true); // first send slides the panel up
  };

  const handleClear = async () => {
    const ok = await confirm({
      variant: "destructive",
      title: localize("com_subscription.clear_chat_title"),
      description: localize("com_subscription.clear_chat_confirm"),
      confirmText: localize("com_subscription.clear_chat_action"),
      cancelText: localize("com_subscription.clear_chat_cancel"),
    });
    if (ok) clearConversation();
  };

  // Mobile + expanded: take over the full viewport with a stacked header/messages/input
  // layout. Header centered title 16px, input forced to 120px, fade gradient above input,
  // and a grey gradient overlay when the textarea is focused (keyboard-up state).
  if (isH5 && open) {
    const messageHeader = (
      // Mirror the knowledge-space file-list header so the dock top aligns with it:
      // outer pt = safe-area + 8px, inner row is a fixed h-11 (44px) with the px-4 gutter.
      <div className="shrink-0 pt-[calc(env(safe-area-inset-top,0px)+8px)]">
        <div className="relative flex h-11 w-full min-w-0 items-center px-4">
          <h3 className="mx-auto truncate text-base font-medium leading-6 text-text-1">{assistantTitle}</h3>
          <div className="absolute right-4 top-1/2 flex -translate-y-1/2 items-center justify-end gap-3">
            <button
              type="button"
              onClick={handleClear}
              aria-label={localize("com_subscription.clear_chat")}
              className="inline-flex size-4 shrink-0 items-center justify-center text-text-1 transition-colors hover:text-text-2"
            >
              <Outlined.Delete className="size-4" />
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label={localize("com_ui_collapse")}
              className="inline-flex size-4 shrink-0 items-center justify-center text-text-3 transition-colors hover:text-text-2"
            >
              <Outlined.DoubleDown className="size-4" />
            </button>
          </div>
        </div>
      </div>
    );

    return (
      <div
        className="fixed inset-x-0 top-0 z-50 flex flex-col bg-white"
        // Pin the panel to the visual viewport. iOS Safari (and WeChat WKWebView)
        // scrolls the *layout* viewport when an input gets focus so the keyboard
        // doesn't cover it — but with us already filling the viewport, that scroll
        // drags the panel upward off-screen. Compensating with `translateY(offsetTop)`
        // keeps the panel locked to the visible region; height shrinks to the
        // keyboard-clipped viewport height.
        style={{
          height: viewportHeight ? `${viewportHeight}px` : "100dvh",
          transform: `translateY(${viewportOffsetTop}px)`,
        }}
        role="dialog"
        aria-modal="true"
      >
        {messageHeader}

        {/* Messages — scrollable, with bottom fade-out. Default z-auto so it falls
                    below the focused-state grey overlay. */}
        <div className="relative min-h-0 flex-1">
          {historyError ? (
            <ApiRequestFailure error={historyError} onRetry={retryHistory} />
          ) : (
            <AiChatMessages
              messages={messages}
              conversationId={conversationId}
              title={title}
              isLoading={isLoading}
              isStreaming={isStreaming}
              presetQuestions={[
                localize("com_subscription.summarize_article_points"),
                localize("com_subscription.main_conclusion"),
              ]}
              hideShare
              hideHeaderTitle
              flatMode
              knowledgeChatLayout
              contentWidthClassName="max-w-none px-4"
              emptyStateIllustration={<ArticleQAIllustration grey className="mx-auto block size-[80px]" />}
              onPresetClick={(q) => setInputText(q)}
              onRegenerate={regenerate}
            />
          )}
          {/* White gradient where messages meet the input — text appears to fade out. */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 bottom-0 z-[1] h-10 bg-gradient-to-t from-white to-white/0"
          />
        </div>

        {/* Grey gradient overlay while the input is focused (keyboard up).
                    `absolute inset-0` of panel root → covers header + messages + bottom
                    padding area. Sits between content (z-auto) and the input wrapper
                    (z-[3]) so only the white input box stays untouched. */}
        {keyboardVisible && (
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 z-[2] bg-gradient-to-b from-[rgba(0,0,0,0.10)] to-[rgba(0,0,0,0.45)]"
          />
        )}

        {/* Input area — fixed 120px height. `relative z-[3]` lifts the input
                    wrapper above the grey overlay; the wrapper has no bg, so the gradient
                    bleeds through the bottom padding (`pb-[...]`) under the input. */}
        <div className="relative z-[3] shrink-0 px-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          <DockInput
            value={inputText}
            onChange={setInputText}
            onSend={handleSend}
            model={model}
            disabled={Boolean(historyError) || isLoading || isClearing || !modelOptions?.length}
            isStreaming={isStreaming}
            placeholder={localize("com_subscription.ask_article_placeholder")}
            variant="box"
            fixedHeight={120}
            onFocusChange={setKeyboardVisible}
          />
        </div>
      </div>
    );
  }

  // Bottom-anchored dock. Collapsed: a white input box fading in from the article
  // via a gradient. Expanded: a frosted floating card (header + messages + two-row
  // input) inset 16px from the pane edges, grown upward by the grid-rows animation.
  return (
    <>
      {/* Mobile collapsed-state grey overlay — when the box input is focused (keyboard up).
                Fixed full-viewport at z-[19], one tier below the dock (z-20), so the white input
                box stays visible while the article behind gets dimmed top-to-bottom. */}
      {isH5 && !open && keyboardVisible && (
        <div
          aria-hidden
          className="pointer-events-none fixed inset-0 z-[19] bg-gradient-to-b from-[rgba(0,0,0,0.10)] to-[rgba(0,0,0,0.45)]"
        />
      )}
      <div
        className={cn(
          // z-40 sits above any sticky list header so the expanded dialog isn't covered.
          "absolute inset-x-0 bottom-0 z-40 flex flex-col px-4 pb-[max(16px,env(safe-area-inset-bottom))]",
          // Keep the pt-10 spacing regardless so the input doesn't jump when the
          // keyboard opens; only the white-fade backdrop hides while focused so the
          // grey overlay's gradient can carry through to the input area.
          !open && "pt-10",
          // On mobile the fade hides while focused (grey keyboard overlay carries through);
          // on desktop there is no such overlay, so keep the fade consistent regardless of focus.
          !open && (!isH5 || !keyboardVisible) && "bg-gradient-to-b from-white/0 to-white",
          // Expanded: same transparent→white fade masks the content behind the dialog.
          open && "bg-gradient-to-b from-white/0 to-white",
        )}
      >
        <div
          className={cn(
            "relative mx-auto flex w-full max-w-[800px] flex-col",
            open &&
              "overflow-hidden rounded-[20px] border border-border-base bg-white shadow-[0_4px_20px_0_rgba(3,7,117,0.05)]",
          )}
        >
          {/* Floating expand button: only once a conversation exists and the panel is
                    collapsed. Hovers ~10px above the input's top-right, right-aligned with it. */}
          {!open && messages.length > 0 && (
            <SharedTooltipProvider>
              <SharedTooltip
                content={
                  <>
                    <p>{localize("com_ui_expand")}</p>
                  </>
                }
              >
                <button
                  type="button"
                  onClick={() => setOpen(true)}
                  aria-label={localize("com_ui_expand")}
                  className="absolute bottom-full right-0 z-10 mb-2.5 flex size-8 items-center justify-center rounded-[20px] border border-[#EBEBEB] bg-white text-text-3 drop-shadow-[0_0_8px_rgba(3,7,117,0.05)] transition-colors hover:text-text-2"
                >
                  <Outlined.DoubleDown className="size-4 rotate-180" />
                </button>
              </SharedTooltip>
            </SharedTooltipProvider>
          )}
          {/* Header + messages grow upward above the input. Height scales with the viewport
                    (taller on large screens), floored at 440px and capped so it never overflows. */}
          <div
            className={cn(
              "overflow-hidden transition-[max-height] duration-300 ease-out",
              open ? "max-h-[clamp(440px,70vh,calc(100vh_-_160px))]" : "max-h-0",
            )}
          >
            <div className="flex h-[clamp(440px,70vh,calc(100vh_-_160px))] flex-col">
              {/* Header: title left, clear + collapse-down right */}
              <div className="relative flex shrink-0 items-center gap-2 px-4 py-3">
                <h3 className="pointer-events-none min-w-0 shrink truncate text-left text-sm font-medium leading-[22px] text-text-1">
                  {assistantTitle}
                </h3>
                <div className="min-w-0 flex-1" aria-hidden />
                {/* Clear · DoubleDown — bare 16px icons, 12px gap, right-aligned (matches the knowledge dock). */}
                <div className="flex shrink-0 items-center justify-end gap-3 py-1">
                  <SharedTooltipProvider>
                    <SharedTooltip
                      content={
                        <>
                          <p>{localize("com_subscription.clear_chat")}</p>
                        </>
                      }
                    >
                      <button
                        type="button"
                        onClick={handleClear}
                        aria-label={localize("com_subscription.clear_chat")}
                        className="inline-flex size-4 shrink-0 items-center justify-center text-text-1 transition-colors hover:text-text-2"
                      >
                        <Outlined.Delete className="size-4 shrink-0" />
                      </button>
                    </SharedTooltip>
                  </SharedTooltipProvider>
                  <SharedTooltipProvider>
                    <SharedTooltip
                      content={
                        <>
                          <p>{localize("com_ui_collapse")}</p>
                        </>
                      }
                      side="top"
                    >
                      <button
                        type="button"
                        onClick={() => setOpen(false)}
                        aria-label={localize("com_ui_collapse")}
                        className="inline-flex size-4 shrink-0 items-center justify-center text-text-3 transition-colors hover:text-text-2"
                      >
                        <Outlined.DoubleDown className="size-4 shrink-0" />
                      </button>
                    </SharedTooltip>
                  </SharedTooltipProvider>
                </div>
              </div>

              {historyError ? (
                <ApiRequestFailure error={historyError} onRetry={retryHistory} />
              ) : (
                <AiChatMessages
                  messages={messages}
                  conversationId={conversationId}
                  title={title}
                  isLoading={isLoading}
                  isStreaming={isStreaming}
                  presetQuestions={[
                    localize("com_subscription.summarize_article_points"),
                    localize("com_subscription.main_conclusion"),
                  ]}
                  hideShare
                  hideHeaderTitle
                  flatMode
                  knowledgeChatLayout
                  contentWidthClassName="max-w-none px-4"
                  emptyStateIllustration={
                    <ArticleQAIllustration grey className="mx-auto block size-[80px]" />
                  }
                  onPresetClick={(q) => setInputText(q)}
                  onRegenerate={regenerate}
                />
              )}
            </div>
          </div>

          {/* Input bar. Collapsed: a standalone white box. Expanded: pinned to
                    the bottom of the card, white fill with a top divider (line variant). */}
          <DockInput
            value={inputText}
            onChange={setInputText}
            onSend={handleSend}
            model={model}
            disabled={Boolean(historyError) || isLoading || isClearing || !modelOptions?.length}
            isStreaming={isStreaming}
            placeholder={localize("com_subscription.ask_article_placeholder")}
            variant={open ? "line" : "box"}
            onFocusChange={setKeyboardVisible}
          />
        </div>
      </div>
    </>
  );
}
