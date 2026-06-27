import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useRecoilState } from "recoil";
import { Outlined } from "bisheng-icons";
import { TextareaAutosize } from "~/components/ui";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "~/components/ui/Tooltip2";
import AiChatMessages from "~/components/Chat/AiChatMessages";
import { ArticleQAIllustration } from "~/components/illustrations";
import AiModelSelect from "~/components/Chat/AiModelSelect";
import SpeechToTextComponent from "~/components/Voice/SpeechToText";
import { SendIcon } from "~/components/svg";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { useAuthContext } from "~/hooks/AuthContext";
import { useGetBsConfig, useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider";
import useChatModelMemo from "~/hooks/useChatModelMemo";
import useFileChat from "~/hooks/useFileChat";
import { useConfirm } from "~/Providers";
import { cn } from "~/utils";
import store from "~/store";

interface FileAiDockProps {
    /** Knowledge space id. */
    spaceId: string;
    /** File id within the space — drives the single-file chat. */
    fileId: string;
}

interface ModelSelectProps {
    options?: any[];
    value?: any;
    onChange: (val: string) => void;
    disabled?: boolean;
}

/**
 * The dock input: model select · auto-grow textarea (≤180px) · mic · send.
 * Mirrors `ArticleAiDock`'s DockInput verbatim — kept local so the file dock stays
 * self-contained and the article dock is never touched.
 */
function DockInput({
    value,
    onChange,
    onSend,
    model,
    disabled,
    isStreaming,
    placeholder,
    variant,
    fixedHeight,
    onFocusChange,
}: {
    value: string;
    onChange: (v: string) => void;
    onSend: (text: string) => void;
    model: ModelSelectProps;
    disabled: boolean;
    isStreaming: boolean;
    placeholder: string;
    variant: "box" | "line";
    fixedHeight?: number;
    onFocusChange?: (focused: boolean) => void;
}) {
    const [multiline, setMultiline] = useState(false);
    const taRef = useRef<HTMLTextAreaElement>(null);
    const { data: modelData } = useGetWorkbenchModelsQuery();
    const showVoice = !!modelData?.asr_model?.id;
    const isH5 = usePrefersMobileLayout();

    // Mobile is always two-row (textarea on top, model + send below) — matches the file-list input.
    const stacked = variant === "line" || multiline || isH5;

    useEffect(() => {
        if (!value) setMultiline(false);
    }, [value]);

    const submit = () => {
        const trimmed = value.trim();
        if (!trimmed || disabled || isStreaming) return;
        onSend(trimmed);
        if (taRef.current) taRef.current.style.height = "auto";
        // Mobile: blur after sending so the keyboard dismisses and the grey overlay
        // (driven by focus → keyboardVisible) clears instead of lingering.
        if (isH5) taRef.current?.blur();
    };

    const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (!isStreaming) submit();
        }
    };

    const modelSelect = model.options ? (
        <AiModelSelect
            disabled={!!disabled}
            value={model.value}
            options={model.options}
            onChange={model.onChange}
        />
    ) : null;

    const sendControls = (
        <div className="flex shrink-0 items-center gap-1.5">
            {showVoice && (
                <SpeechToTextComponent
                    disabled={disabled}
                    onChange={(e) => onChange(value + e)}
                />
            )}
            <button
                type="button"
                onClick={submit}
                disabled={!value.trim() || disabled || isStreaming}
                className="rounded-full bg-primary p-1 transition-all duration-200 disabled:cursor-not-allowed disabled:bg-[#E5E6EB] [&>svg]:text-white disabled:[&>svg]:text-[#4E5969]"
                aria-label="Send message"
            >
                <SendIcon size={24} />
            </button>
        </div>
    );

    return (
        <div
            className={cn(
                "flex bg-white",
                variant === "box"
                    ? "rounded-[20px] border border-[#E5E6EB] p-3 shadow-[0_2px_12px_rgba(0,0,0,0.06)]"
                    : "border-t border-[#EBEBEB] p-3",
                stacked ? "flex-col gap-2" : "items-center gap-2",
            )}
            style={fixedHeight ? { height: `${fixedHeight}px` } : undefined}
        >
            {!stacked && modelSelect && (
                <div key="model-inline" className="shrink-0">{modelSelect}</div>
            )}

            <div key="textarea" className={cn(stacked ? "w-full" : "min-w-0 flex-1", fixedHeight && "min-h-0 flex-1")}>
                <TextareaAutosize
                    ref={taRef}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    onKeyDown={handleKeyDown}
                    onHeightChange={(h: number, meta?: { rowHeight?: number }) => {
                        if (h > (meta?.rowHeight ?? 24) * 1.4) setMultiline(true);
                    }}
                    onFocus={() => onFocusChange?.(true)}
                    onBlur={() => onFocusChange?.(false)}
                    disabled={disabled}
                    placeholder={placeholder}
                    rows={1}
                    className={cn(
                        "m-0 block w-full resize-none bg-transparent py-1 text-sm leading-6 outline-none placeholder-[#86909c]",
                        fixedHeight ? "h-full max-h-full overflow-y-auto" : "max-h-[180px]",
                    )}
                />
            </div>

            <div
                key="controls"
                className={cn("flex items-center", stacked ? "w-full justify-between" : "shrink-0")}
            >
                {stacked && modelSelect && <div className="shrink-0">{modelSelect}</div>}
                {sendControls}
            </div>
        </div>
    );
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
    const [chatModel, setChatModel] = useRecoilState(store.chatModel);
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
                const active = document.activeElement;
                if (active && (active.tagName === "TEXTAREA" || active.tagName === "INPUT")) {
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
    }, [isH5]);

    const {
        messages,
        conversationId,
        title,
        isLoading,
        isStreaming,
        sendMessage,
        stopGenerating,
        clearConversation,
        regenerate,
    } = useFileChat(spaceId, fileId);

    useChatModelMemo(user, bsConfig as any);

    const modelOptions = bsConfig?.models;
    const model: ModelSelectProps = {
        options: modelOptions,
        value: chatModel.id,
        disabled: !modelOptions?.length,
        onChange: (val) => {
            const m = modelOptions?.find((x) => x.id === val);
            setChatModel({ id: Number(val), name: m?.displayName || "" });
        },
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
                    <h3 className="mx-auto truncate text-base font-medium leading-6 text-[#212121]">
                        {assistantTitle}
                    </h3>
                    <div className="absolute right-4 top-1/2 flex -translate-y-1/2 items-center justify-end gap-3">
                        <button
                            type="button"
                            onClick={handleClear}
                            aria-label={localize("com_subscription.clear_chat")}
                            className="inline-flex size-4 shrink-0 items-center justify-center text-[#212121] transition-colors hover:text-[#4e5969]"
                        >
                            <Outlined.Delete className="size-4" />
                        </button>
                        <button
                            type="button"
                            onClick={() => setOpen(false)}
                            aria-label={localize("com_ui_collapse")}
                            className="inline-flex size-4 shrink-0 items-center justify-center text-[#999999] transition-colors hover:text-[#4e5969]"
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
                        emptyStateIllustration={<ArticleQAIllustration className="mx-auto block size-[80px]" />}
                        onPresetClick={(q) => setInputText(q)}
                        onRegenerate={regenerate}
                    />
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
                    <DockInput
                        value={inputText}
                        onChange={setInputText}
                        onSend={handleSend}
                        model={model}
                        disabled={!modelOptions?.length}
                        isStreaming={isStreaming}
                        placeholder={placeholder}
                        variant="box"
                        fixedHeight={120}
                        onFocusChange={setKeyboardVisible}
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
                    !open && (!isH5 || !keyboardVisible) && "bg-gradient-to-b from-white/0 to-white",
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
                            "overflow-hidden rounded-[20px] border border-[#ECECEC] bg-white shadow-[0_4px_20px_0_rgba(3,7,117,0.05)]",
                    )}
                >
                    {!open && messages.length > 0 && (
                        <TooltipProvider>
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <button
                                        type="button"
                                        onClick={() => setOpen(true)}
                                        aria-label={localize("com_ui_expand")}
                                        className="absolute bottom-full right-0 z-10 mb-2.5 flex size-8 items-center justify-center rounded-[20px] border border-[#EBEBEB] bg-white text-[#86909c] drop-shadow-[0_0_8px_rgba(3,7,117,0.05)] transition-colors hover:text-[#4e5969]"
                                    >
                                        <Outlined.DoubleDown className="size-4 rotate-180" />
                                    </button>
                                </TooltipTrigger>
                                <TooltipContent>
                                    <p>{localize("com_ui_expand")}</p>
                                </TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    )}

                    <div
                        className={cn(
                            // Height scales with the viewport (taller on large screens); floored at 440px,
                            // capped so it never overflows the file-display area.
                            "overflow-hidden transition-[max-height] duration-300 ease-out",
                            open ? "max-h-[clamp(440px,70vh,calc(100vh_-_160px))]" : "max-h-0",
                        )}
                    >
                        <div className="flex h-[clamp(440px,70vh,calc(100vh_-_160px))] flex-col">
                            <div className="relative flex shrink-0 items-center gap-2 px-4 py-3">
                                <h3 className="pointer-events-none min-w-0 shrink truncate text-left text-sm font-medium leading-[22px] text-[#212121]">
                                    {assistantTitle}
                                </h3>
                                <div className="min-w-0 flex-1" aria-hidden />
                                {/* Clear · DoubleDown — bare 16px icons, 12px gap, right-aligned (matches the knowledge dock). */}
                                <div className="flex shrink-0 items-center justify-end gap-3 py-1">
                                    <TooltipProvider>
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <button
                                                    type="button"
                                                    onClick={handleClear}
                                                    aria-label={localize("com_subscription.clear_chat")}
                                                    className="inline-flex size-4 shrink-0 items-center justify-center text-[#212121] transition-colors hover:text-[#4e5969]"
                                                >
                                                    <Outlined.Delete className="size-4 shrink-0" />
                                                </button>
                                            </TooltipTrigger>
                                            <TooltipContent>
                                                <p>{localize("com_subscription.clear_chat")}</p>
                                            </TooltipContent>
                                        </Tooltip>
                                    </TooltipProvider>
                                    <TooltipProvider>
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <button
                                                    type="button"
                                                    onClick={() => setOpen(false)}
                                                    aria-label={localize("com_ui_collapse")}
                                                    className="inline-flex size-4 shrink-0 items-center justify-center text-[#999999] transition-colors hover:text-[#4e5969]"
                                                >
                                                    <Outlined.DoubleDown className="size-4 shrink-0" />
                                                </button>
                                            </TooltipTrigger>
                                            <TooltipContent side="top">
                                                <p>{localize("com_ui_collapse")}</p>
                                            </TooltipContent>
                                        </Tooltip>
                                    </TooltipProvider>
                                </div>
                            </div>

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
                                emptyStateIllustration={<ArticleQAIllustration className="mx-auto block size-[80px]" />}
                                onPresetClick={(q) => setInputText(q)}
                                onRegenerate={regenerate}
                            />
                        </div>
                    </div>

                    <DockInput
                        value={inputText}
                        onChange={setInputText}
                        onSend={handleSend}
                        model={model}
                        disabled={!modelOptions?.length}
                        isStreaming={isStreaming}
                        placeholder={placeholder}
                        variant={open ? "line" : "box"}
                        onFocusChange={setKeyboardVisible}
                    />
                </div>
            </div>
        </>
    );
}
