import type { ModelSelectProps } from "./ArticleDockInput";
import { FileDockInput } from "./FileDockInput";
import { useClientEnvironment } from "~/hooks/useClientEnvironment";
import { ApiRequestFailure } from "~/components/ApiRequestFailure";
import {
  Tooltip as SharedTooltip,
  TooltipProvider as SharedTooltipProvider,
} from "@bisheng/ui";
import { useEffect, useRef, useState } from "react";
import { Outlined } from "bisheng-icons";
import AiChatMessages from "~/components/Chat/AiChatMessages";
import { ArticleQAIllustration } from "~/components/illustrations";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { useAuthContext } from "~/hooks/AuthContext";
import {
  useGetBsConfig,
  useGetWorkbenchModelsQuery,
} from "~/hooks/queries/data-provider";
import {
  readAdminDefaultModelId,
  type ChatModelOption,
} from "~/hooks/useChatModelResolution";
import { useSurfaceModel } from "~/hooks/useSurfaceModel";
import useFileChat from "~/hooks/useFileChat";
import { useConfirm } from "~/Providers";
import { cn } from "~/utils";

interface FileAiDockProps {
  /** Knowledge space id. */
  spaceId: string;
  /** File id within the space — drives the single-file chat. */
  fileId: string;
}

/**
 * Knowledge-space single-file AI dock. Structurally identical to `ArticleAiDock`
 * (a bottom-anchored input that slides a chat panel up on first send) but driven by
 * `useFileChat(spaceId, fileId)` — flat history + clear, no sessions/tags (matching
 * the file-chat backend, same surface as channel chat).
 *
 * Why a sibling of ArticleAiDock instead of extending KnowledgeAiBottomDock: that dock
 * is built around the multi-session `useFolderChat` API (session list, create/switch/
 * rename/delete, ConversationHistory, '#'-tag input). File chat exposes none of that, so
 * forcing the swap would mean faking a session surface and risking the file-list page.
 * The session-less ArticleAiDock is the correct template here.
 *
 * Parent contract: render inside a `position: relative` container; the dock is
 * `absolute inset-x-0 bottom-0` (collapsed) / `fixed` full-viewport (mobile-expanded).
 */
export function FileAiDock({ spaceId, fileId }: FileAiDockProps) {
  const localize = useLocalize();
  const confirm = useConfirm();
  const { user } = useAuthContext();
  const { data: bsConfig } = useGetBsConfig();
  // Admin-customizable assistant name; empty/absent falls back to the localized default.
  const assistantTitle =
    bsConfig?.knowledge_space?.assistant_name?.trim() ||
    localize("com_knowledge.ai_assistant");
  // Own model selection, isolated from /c: picking a model here must not
  // change what the main chat shows (see useSurfaceModel).
  const { data: workbenchCfg } = useGetWorkbenchModelsQuery();
  const {
    model: surfaceModel,
    selectModel,
    repairModel,
  } = useSurfaceModel({
    userId: user?.id,
    surfaceKey: "fileAi",
    models: (bsConfig?.models || []) as ChatModelOption[],
    adminDefaultId: readAdminDefaultModelId(workbenchCfg, "daily"),
  });
  const {
    input: { hasTouchInput },
  } = useClientEnvironment();
  const [open, setOpen] = useState(false);
  const [inputText, setInputText] = useState("");
  const isH5 = usePrefersMobileLayout();

  /** Visual viewport tracking — pins the mobile-expanded panel above the virtual
   *  keyboard. Mirrors `ArticleAiDock`; see that file for the full rationale. */
  const [viewportHeight, setViewportHeight] = useState<number | null>(null);
  const [viewportOffsetTop, setViewportOffsetTop] = useState(0);
  const [keyboardVisible, setKeyboardVisible] = useState(false);
  const peakVvHeightRef = useRef(0);
  const keyboardUpRef = useRef(false);

  useEffect(() => {
    if (!hasTouchInput || typeof window === "undefined") return;
    const vv = window.visualViewport;
    if (!vv) return;
    const sync = () => {
      setViewportHeight(vv.height);
      setViewportOffsetTop(vv.offsetTop);
      if (vv.height > peakVvHeightRef.current)
        peakVvHeightRef.current = vv.height;
      if (peakVvHeightRef.current === 0) return;
      const ratio = vv.height / peakVvHeightRef.current;
      if (ratio < 0.6) {
        const active = document.activeElement;
        if (
          active &&
          (active.tagName === "TEXTAREA" || active.tagName === "INPUT")
        ) {
          keyboardUpRef.current = true;
          setKeyboardVisible(true);
        }
      } else if (ratio > 0.85 && keyboardUpRef.current) {
        keyboardUpRef.current = false;
        setKeyboardVisible(false);
        const active = document.activeElement;
        if (
          active &&
          (active.tagName === "TEXTAREA" || active.tagName === "INPUT")
        ) {
          (active as HTMLElement).blur();
        }
      }
    };
    sync();
    vv.addEventListener("resize", sync);
    vv.addEventListener("scroll", sync);
    window.addEventListener("resize", sync);
    return () => {
      vv.removeEventListener("resize", sync);
      vv.removeEventListener("scroll", sync);
      window.removeEventListener("resize", sync);
    };
  }, [hasTouchInput]);

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
  } = useFileChat(spaceId, fileId, surfaceModel);

  const modelOptions = bsConfig?.models;
  const model: ModelSelectProps = {
    options: modelOptions,
    value: surfaceModel.id,
    disabled: !modelOptions?.length,
    onChange: selectModel,
    onAutoChange: repairModel,
  };

  const placeholder = localize("com_knowledge.ai_input_placeholder_short");

  const handleSend = (text: string) => {
    sendMessage(text);
    setInputText("");
    if (!open) setOpen(true);
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

  // ─── Mobile + expanded: take over the full visual viewport ─────────────
  if (isH5 && open) {
    const messageHeader = (
      // Mirror the knowledge-space file-list header so the dock top aligns with it:
      // outer pt = safe-area + 8px, inner row is a fixed h-11 (44px) with the px-4 gutter.
      <div className="shrink-0 pt-[calc(env(safe-area-inset-top,0px)+8px)]">
        <div className="relative flex h-11 w-full min-w-0 items-center px-4">
          <h3 className="mx-auto truncate text-base font-medium leading-6 text-text-1">
            {assistantTitle}
          </h3>
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
        style={{
          height: viewportHeight ? `${viewportHeight}px` : "100dvh",
          transform: `translateY(${viewportOffsetTop}px)`,
        }}
        role="dialog"
        aria-modal="true"
      >
        {messageHeader}

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
              presetQuestions={[]}
              hideShare
              hideHeaderTitle
              flatMode
              knowledgeChatLayout
              contentWidthClassName="max-w-none px-4"
              emptyStateIllustration={
                <ArticleQAIllustration
                  grey
                  className="mx-auto block size-[80px]"
                />
              }
              onPresetClick={(q) => setInputText(q)}
              onRegenerate={regenerate}
            />
          )}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 bottom-0 z-[1] h-10 bg-gradient-to-t from-white to-white/0"
          />
        </div>

        {keyboardVisible && (
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 z-[2] bg-gradient-to-b from-[rgba(0,0,0,0.10)] to-[rgba(0,0,0,0.45)]"
          />
        )}

        <div className="relative z-[3] shrink-0 px-4 pb-[max(16px,env(safe-area-inset-bottom))]">
          <FileDockInput
            value={inputText}
            onChange={setInputText}
            onSend={handleSend}
            model={model}
            disabled={
              Boolean(historyError) ||
              isLoading ||
              isClearing ||
              !modelOptions?.length
            }
            isStreaming={isStreaming}
            placeholder={placeholder}
            variant="box"
            fixedHeight={120}
            onFocusChange={(focused) => {
              if (!focused) setKeyboardVisible(false);
            }}
          />
        </div>
      </div>
    );
  }

  // ─── Desktop + mobile-collapsed: bottom-anchored dock ──────────────────
  return (
    <>
      {isH5 && !open && keyboardVisible && (
        <div
          aria-hidden
          className="pointer-events-none fixed inset-0 z-[19] bg-gradient-to-b from-[rgba(0,0,0,0.10)] to-[rgba(0,0,0,0.45)]"
        />
      )}
      <div
        className={cn(
          // z-40 sits above the file table's sticky header (z-30) so the expanded dialog isn't covered.
          // pointer-events-none keeps the gradient backdrop visually masking the content while
          // letting clicks fall through to whatever is behind it (e.g. the PDF page thumbnails);
          // the chat card below re-enables pointer events on its own box so it stays interactive.
          "pointer-events-none absolute inset-x-0 bottom-0 z-40 flex flex-col px-4 pb-[max(16px,env(safe-area-inset-bottom))]",
          !open && "pt-10",
          // White fade backdrop. On mobile it hides while the input is focused (grey keyboard
          // overlay carries through); on desktop keep it consistent regardless of focus.
          !open &&
            (!isH5 || !keyboardVisible) &&
            "bg-gradient-to-b from-white/0 to-white",
          // Expanded: same transparent→white fade masks the content behind the dialog.
          open && "bg-gradient-to-b from-white/0 to-white",
        )}
      >
        <div
          className={cn(
            // pointer-events-auto restores interactivity on the card itself (its parent
            // backdrop is pointer-events-none so the content behind stays clickable).
            "pointer-events-auto relative mx-auto flex w-full max-w-[800px] flex-col",
            open &&
              "overflow-hidden rounded-[20px] border border-border-base bg-white shadow-[0_4px_20px_0_rgba(3,7,117,0.05)]",
          )}
        >
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

          <div
            className={cn(
              // Height scales with the viewport (taller on large screens); floored at 440px,
              // capped so it never overflows the file-display area.
              "overflow-hidden transition-[max-height] duration-300 ease-out",
              open
                ? "max-h-[clamp(440px,70vh,calc(100vh_-_160px))]"
                : "max-h-0",
            )}
          >
            <div className="flex h-[clamp(440px,70vh,calc(100vh_-_160px))] flex-col">
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
                <ApiRequestFailure
                  error={historyError}
                  onRetry={retryHistory}
                />
              ) : (
                <AiChatMessages
                  messages={messages}
                  conversationId={conversationId}
                  title={title}
                  isLoading={isLoading}
                  isStreaming={isStreaming}
                  presetQuestions={[]}
                  hideShare
                  hideHeaderTitle
                  flatMode
                  knowledgeChatLayout
                  contentWidthClassName="max-w-none px-4"
                  emptyStateIllustration={
                    <ArticleQAIllustration
                      grey
                      className="mx-auto block size-[80px]"
                    />
                  }
                  onPresetClick={(q) => setInputText(q)}
                  onRegenerate={regenerate}
                />
              )}
            </div>
          </div>

          <FileDockInput
            value={inputText}
            onChange={setInputText}
            onSend={handleSend}
            model={model}
            disabled={
              Boolean(historyError) ||
              isLoading ||
              isClearing ||
              !modelOptions?.length
            }
            isStreaming={isStreaming}
            placeholder={placeholder}
            variant={open ? "line" : "box"}
            onFocusChange={(focused) => {
              if (!focused) setKeyboardVisible(false);
            }}
          />
        </div>
      </div>
    </>
  );
}
