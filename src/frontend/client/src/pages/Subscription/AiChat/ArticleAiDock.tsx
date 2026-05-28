import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useRecoilState } from "recoil";
import { Outlined } from "bisheng-icons";
import { Button, TextareaAutosize } from "~/components/ui";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "~/components/ui/Tooltip2";
import AiChatMessages from "~/components/Chat/AiChatMessages";
import AiModelSelect from "~/components/Chat/AiModelSelect";
import SpeechToTextComponent from "~/components/Voice/SpeechToText";
import { SendIcon } from "~/components/svg";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { useAuthContext } from "~/hooks/AuthContext";
import { useGetBsConfig, useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider";
import useChannelChat from "~/hooks/useChannelChat";
import useChatModelMemo from "~/hooks/useChatModelMemo";
import { useConfirm } from "~/Providers";
import { cn } from "~/utils";
import store from "~/store";

interface ArticleAiDockProps {
    /** ES article document id — drives the channel chat. */
    articleDocId: string;
}

interface ModelSelectProps {
    options?: any[];
    value?: any;
    onChange: (val: string) => void;
    disabled?: boolean;
}

/**
 * The dock input: model select · auto-grow textarea (≤180px) · mic · send.
 * `variant` controls both the frame and the layout:
 *   - 'box'  collapsed: a white rounded bordered box. Single row while the text
 *            fits one line; restacks (textarea on top, model + send below) on wrap.
 *   - 'line' expanded: no box; sits inside the chat card on a white fill with a top
 *            divider. Always two rows — full-width textarea over a model + send row.
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
    /** When set, force the input container to this px height (e.g. mobile-expanded = 120). */
    fixedHeight?: number;
    /** Forward textarea focus/blur so the panel can dim the page while typing. */
    onFocusChange?: (focused: boolean) => void;
}) {
    const [multiline, setMultiline] = useState(false);
    const taRef = useRef<HTMLTextAreaElement>(null);
    const { data: modelData } = useGetWorkbenchModelsQuery();
    const showVoice = !!modelData?.asr_model?.id;

    // Expanded ('line') is always two rows; collapsed ('box') restacks only on wrap.
    const stacked = variant === "line" || multiline;

    // Reset to single row when the text is cleared (incl. parent-driven clears on send).
    useEffect(() => {
        if (!value) setMultiline(false);
    }, [value]);

    const submit = () => {
        const trimmed = value.trim();
        if (!trimmed || disabled || isStreaming) return;
        onSend(trimmed);
        if (taRef.current) taRef.current.style.height = "auto";
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
                stacked ? "flex-col gap-2" : "items-end gap-2",
            )}
            style={fixedHeight ? { height: `${fixedHeight}px` } : undefined}
        >
            {/* Single-row only: model select sits to the left of the textarea. */}
            {!stacked && modelSelect && (
                <div key="model-inline" className="shrink-0">{modelSelect}</div>
            )}

            {/* Textarea — keyed so it stays mounted across the layout switch. */}
            <div key="textarea" className={cn(stacked ? "w-full" : "min-w-0 flex-1", fixedHeight && "min-h-0 flex-1")}>
                <TextareaAutosize
                    ref={taRef}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    onKeyDown={handleKeyDown}
                    onHeightChange={(h: number, meta?: { rowHeight?: number }) => {
                        // Only escalate to multi-row; collapsing back on height would
                        // oscillate (wider row re-fits to one line → infinite loop).
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

            {/* Controls. Single-row: mic + send on the right. Two-row: model left, mic + send right. */}
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
 * Subscription article AI dock (PC). A persistent input bar pinned to the bottom of
 * the article-detail pane. Typing stays in place; the first send slides a chat panel
 * (header + messages) UP from above the input — the input itself never moves, it just
 * loses its box and gains a divider line. Collapsing (down-chevron) hides the panel
 * again without losing the conversation.
 *
 * Self-contained (channel chat only) so the shared AiAssistantPanel — still used by
 * the knowledge-space file preview — stays untouched.
 */
export function ArticleAiDock({ articleDocId }: ArticleAiDockProps) {
    const localize = useLocalize();
    const confirm = useConfirm();
    const { user } = useAuthContext();
    const { data: bsConfig } = useGetBsConfig();
    const [chatModel, setChatModel] = useRecoilState(store.chatModel);
    const [open, setOpen] = useState(false);
    const [inputText, setInputText] = useState("");
    const isH5 = usePrefersMobileLayout();
    const [inputFocused, setInputFocused] = useState(false);
    /** Tracks visual viewport so the mobile-expanded panel sits above the virtual keyboard and
     *  follows any iOS-Safari scroll that happens when the focused input is brought into view. */
    const [viewportHeight, setViewportHeight] = useState<number | null>(null);
    const [viewportOffsetTop, setViewportOffsetTop] = useState(0);

    useEffect(() => {
        if (!isH5 || typeof window === "undefined") return;
        const vv = window.visualViewport;
        if (!vv) return;
        const sync = () => {
            setViewportHeight(vv.height);
            setViewportOffsetTop(vv.offsetTop);
        };
        sync();
        vv.addEventListener("resize", sync);
        vv.addEventListener("scroll", sync);
        return () => {
            vv.removeEventListener("resize", sync);
            vv.removeEventListener("scroll", sync);
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
    } = useChannelChat(articleDocId);

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

    const handleSend = (text: string) => {
        sendMessage(text);
        setInputText("");
        if (!open) setOpen(true); // first send slides the panel up
    };

    const handleClear = async () => {
        const ok = await confirm({
            title: localize("com_subscription.prompt_tip"),
            description: localize("com_subscription.clear_chat_confirm"),
            confirmText: localize("com_subscription.confirm"),
            cancelText: localize("com_subscription.cancel"),
        });
        if (ok) clearConversation();
    };

    // Mobile + expanded: take over the full viewport with a stacked header/messages/input
    // layout. Header centered title 16px, input forced to 120px, fade gradient above input,
    // and a grey gradient overlay when the textarea is focused (keyboard-up state).
    if (isH5 && open) {
        const messageHeader = (
            <div
                className="relative flex shrink-0 items-center px-4 pt-[calc(env(safe-area-inset-top,0px)+12px)] pb-3"
            >
                <h3 className="mx-auto truncate text-base font-medium leading-6 text-[#212121]">
                    {localize("com_subscription.ai_assistant")}
                </h3>
                <div className="absolute right-3 top-[calc(env(safe-area-inset-top,0px)+8px)] flex items-center gap-1">
                    <Button
                        variant="ghost"
                        size="icon"
                        className="size-8 text-gray-400 hover:text-gray-600"
                        onClick={handleClear}
                        aria-label={localize("com_subscription.clear_chat")}
                    >
                        <Outlined.Delete className="size-4" />
                    </Button>
                    <Button
                        variant="ghost"
                        size="icon"
                        className="size-8 text-[#86909c] hover:text-[#4e5969]"
                        onClick={() => setOpen(false)}
                        aria-label={localize("com_ui_collapse")}
                    >
                        <Outlined.DoubleDown className="size-4" />
                    </Button>
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
                        onPresetClick={(q) => setInputText(q)}
                        onRegenerate={regenerate}
                    />
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
                {inputFocused && (
                    <div
                        aria-hidden
                        className="pointer-events-none absolute inset-0 z-[2] bg-gradient-to-b from-[rgba(0,0,0,0.10)] to-[rgba(0,0,0,0.45)]"
                    />
                )}

                {/* Input area — fixed 120px height. `relative z-[3]` lifts the input
                    wrapper above the grey overlay; the wrapper has no bg, so the gradient
                    bleeds through the bottom padding (`pb-[...]`) under the input. */}
                <div className="relative z-[3] shrink-0 px-3 pb-[max(8px,env(safe-area-inset-bottom))]">
                    <DockInput
                        value={inputText}
                        onChange={setInputText}
                        onSend={handleSend}
                        model={model}
                        disabled={!modelOptions?.length}
                        isStreaming={isStreaming}
                        placeholder={localize("com_subscription.ask_article_placeholder")}
                        variant="box"
                        fixedHeight={120}
                        onFocusChange={setInputFocused}
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
            {isH5 && !open && inputFocused && (
                <div
                    aria-hidden
                    className="pointer-events-none fixed inset-0 z-[19] bg-gradient-to-b from-[rgba(0,0,0,0.10)] to-[rgba(0,0,0,0.45)]"
                />
            )}
        <div
            className={cn(
                "absolute inset-x-0 bottom-0 z-20 flex flex-col px-4 pb-[max(16px,env(safe-area-inset-bottom))]",
                // Keep the pt-10 spacing regardless so the input doesn't jump when the
                // keyboard opens; only the white-fade backdrop hides while focused so the
                // grey overlay's gradient can carry through to the input area.
                !open && "pt-10",
                !open && !inputFocused && "bg-gradient-to-b from-white/0 to-white",
            )}
        >
            <div
                className={cn(
                    "relative flex flex-col",
                    open &&
                        "overflow-hidden rounded-[20px] border border-[#ECECEC] bg-gradient-to-b from-white/80 to-white shadow-[0_4px_20px_0_rgba(3,7,117,0.05)] backdrop-blur-[16px]",
                )}
            >
                {/* Floating expand button: only once a conversation exists and the panel is
                    collapsed. Hovers ~10px above the input's top-right, right-aligned with it. */}
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
                {/* Header + messages grow upward above the input. Animating max-height
                    between 0 and the fixed 440px panel height keeps the reveal smooth and
                    monotonic — unlike a grid `fr` transition, which can overshoot/bounce. */}
                <div
                    className={cn(
                        "overflow-hidden transition-[max-height] duration-300 ease-out",
                        open ? "max-h-[440px]" : "max-h-0",
                    )}
                >
                    <div className="flex h-[440px] flex-col">
                            {/* Header: title left, clear + collapse-down right */}
                            <div className="relative flex shrink-0 items-center gap-2 px-4 py-3">
                                <h3 className="pointer-events-none min-w-0 shrink truncate text-left text-sm font-medium leading-[22px] text-[#212121]">
                                    {localize("com_subscription.ai_assistant")}
                                </h3>
                                <div className="min-w-0 flex-1" aria-hidden />
                            <div className="flex shrink-0 items-center gap-2">
                                <TooltipProvider>
                                    <Tooltip>
                                        <TooltipTrigger asChild>
                                            <Button
                                                variant="ghost"
                                                className="group relative h-5 w-5 p-0.5 text-gray-400"
                                                onClick={handleClear}
                                            >
                                                <Outlined.Delete className="size-4" />
                                            </Button>
                                        </TooltipTrigger>
                                        <TooltipContent>
                                            <p>{localize("com_subscription.clear_chat")}</p>
                                        </TooltipContent>
                                    </Tooltip>
                                </TooltipProvider>
                                <TooltipProvider>
                                    <Tooltip>
                                        <TooltipTrigger asChild>
                                            <Button
                                                variant="ghost"
                                                type="button"
                                                size="icon"
                                                className="size-8 shrink-0 text-[#86909c] hover:text-[#4e5969]"
                                                onClick={() => setOpen(false)}
                                                aria-label={localize("com_ui_collapse")}
                                            >
                                                <Outlined.DoubleDown className="size-4 shrink-0" />
                                            </Button>
                                        </TooltipTrigger>
                                        <TooltipContent side="bottom">
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
                            presetQuestions={[
                                localize("com_subscription.summarize_article_points"),
                                localize("com_subscription.main_conclusion"),
                            ]}
                            hideShare
                            hideHeaderTitle
                            flatMode
                            knowledgeChatLayout
                            contentWidthClassName="max-w-none px-4"
                            onPresetClick={(q) => setInputText(q)}
                            onRegenerate={regenerate}
                        />
                    </div>
                </div>

                {/* Input bar. Collapsed: a standalone white box. Expanded: pinned to
                    the bottom of the card, white fill with a top divider (line variant). */}
                <DockInput
                    value={inputText}
                    onChange={setInputText}
                    onSend={handleSend}
                    model={model}
                    disabled={!modelOptions?.length}
                    isStreaming={isStreaming}
                    placeholder={localize("com_subscription.ask_article_placeholder")}
                    variant={open ? "line" : "box"}
                    onFocusChange={setInputFocused}
                />
            </div>
        </div>
        </>
    );
}
