/**
 * KnowledgeAiBottomDock — bottom-anchored AI dock for a single knowledge space.
 *
 * Architecture mirrors the subscription `ArticleAiDock`:
 *   - Collapsed: a floating white input box pinned to the bottom of the pane.
 *   - Expanded: a floating frosted card (header + messages + line-variant input)
 *               grown upward by a `max-height` transition. The input itself never
 *               moves — only its frame swaps between `box` and `line`.
 *
 * Differences from `ArticleAiDock`:
 *   - Backend is `useFolderChat(spaceId, folderId)` — server-backed sessions,
 *     history, rename, delete, regenerate.
 *   - Input is `KnowledgeAiInput` — keeps the `#`-tag picker, tag badge, voice,
 *     model select, and Enter-to-send behaviour intact across both variants.
 *   - Header includes history toggle + new-session button (no destructive clear,
 *     consistent with the prior side-panel UX).
 *
 * Parent contract: render inside a `position: relative` container with enough
 * room above the dock for at least one row of content. The dock is `absolute
 * inset-x-0 bottom-0` and overlays the bottom of that container.
 */
import { useEffect, useRef, useState } from "react";
import { Outlined } from "bisheng-icons";
import { useQuery } from "@tanstack/react-query";
import { useRecoilValue, useResetRecoilState } from "recoil";
import { knowledgeSelectedFilesState } from "../../selectionStore";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "~/components/ui/Tooltip2";
import AiChatMessages from "~/components/Chat/AiChatMessages";
import { ArticleQAIllustration } from "~/components/illustrations";
import { KnowledgeAiInput } from "./KnowledgeAiInput";
import { ConversationHistory } from "./ConversationHistory";
import useFolderChat from "~/hooks/useFolderChat";
import type { FolderChatTag } from "~/hooks/useFolderChat";
import { getSpaceTagsApi } from "~/api/knowledge";
import { useGetBsConfig } from "~/hooks/queries/endpoints/queries";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { cn } from "~/utils";
import store from "~/store";

interface KnowledgeAiBottomDockProps {
    /** Active knowledge space id. The dock unmounts when this is empty. */
    spaceId: string;
    /** Current folder id, undefined when browsing the space root. */
    folderId?: string;
    /** Welcome text disambiguates space-wide vs folder-scoped Q&A. */
    contextLabel?: string;
}

export function KnowledgeAiBottomDock({
    spaceId,
    folderId,
}: KnowledgeAiBottomDockProps) {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
    const { data: bsConfig } = useGetBsConfig();
    // Admin-customizable assistant name; empty/absent falls back to the localized default.
    const assistantTitle =
        bsConfig?.knowledge_space?.assistant_name?.trim() ||
        localize("com_knowledge.ai_assistant");
    const chatModel = useRecoilValue(store.chatModel);

    const [open, setOpen] = useState(false);
    const [showHistory, setShowHistory] = useState(false);
    /** Default vs active (input-focused) state — distinct from the mobile-keyboard
     *  `keyboardVisible` flag so styling can hang off it later without coupling. */
    const [isActive, setIsActive] = useState(false);

    // Clears the file-list selection (shared atom). File selection and AI Q&A are
    // independent: focusing or sending in the input clears any lingering selection
    // so the two never read as coupled.
    const resetFileSelection = useResetRecoilState(knowledgeSelectedFilesState);

    /** Input focus/blur. On focus we both mark the dock active and clear the file
     *  selection; also drives the mobile keyboard-overlay flag. */
    const handleInputFocusChange = (focused: boolean) => {
        setIsActive(focused);
        setKeyboardVisible(focused);
        if (focused) resetFileSelection();
    };

    /** Visual viewport tracking — pins the mobile-expanded panel above the virtual
     *  keyboard. Mirrors `ArticleAiDock`. See that file for the full rationale. */
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
                // Force blur on iOS WeChat WKWebView's "收起" keyboard button which
                // hides the keyboard without firing blur on the textarea.
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

    // Space tags drive the '#' picker. Cached per space (shared with other consumers).
    const { data: availableTags = [] } = useQuery({
        queryKey: ["spaceTags", spaceId],
        queryFn: () => getSpaceTagsApi(spaceId),
        enabled: !!spaceId,
    });

    const {
        messages,
        sessions,
        activeChatId,
        isLoading,
        isStreaming,
        sendMessage,
        stopGenerating,
        createSession,
        switchSession,
        deleteSession,
        renameSession,
        regenerate,
    } = useFolderChat(spaceId, folderId);

    // Empty-state hint depends on whether the panel is opened at space root or in a folder.
    const folderQaHint = folderId
        ? localize("com_knowledge.qa_current_folder")
        : localize("com_knowledge.qa_current_space");

    const handleSend = (text: string, files?: any[] | null, tag?: FolderChatTag) => {
        sendMessage(text, files, tag);
        // Sending is an AI interaction — clear any file selection made while typing
        // so selection never appears to feed the Q&A.
        resetFileSelection();
        // First send slides the panel up — the input itself stays put.
        if (!open) setOpen(true);
    };

    const handleNewChat = async () => {
        await createSession();
    };

    // Collapsed-state expand button — opens a fresh conversation. Existing history
    // stays in `sessions` and is reachable via the toggle inside the expanded panel.
    const handleExpandNew = async () => {
        setShowHistory(false);
        // Reuse the current view if it's already an empty new chat; otherwise spin up a
        // fresh session so expanding never resurfaces the conversation last viewed.
        if (messages.length > 0) await createSession();
        setOpen(true);
    };

    const handleHistorySelect = (chatId: string) => {
        switchSession(chatId);
        setShowHistory(false);
    };

    // History-panel header actions. Back returns to the conversation view; new chat
    // starts a fresh conversation and reveals it; collapse folds the whole dock.
    const handleHistoryBack = () => setShowHistory(false);

    const handleHistoryNewChat = async () => {
        setShowHistory(false);
        await createSession();
    };

    const handleHistoryCollapse = () => {
        setShowHistory(false);
        setOpen(false);
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
                    {/* History · MessagePlus · DoubleDown — bare 16px icons, 12px gap, right-aligned (per Figma 11495:13085). */}
                    <div className="absolute right-4 top-1/2 flex -translate-y-1/2 items-center justify-end gap-3">
                        <button
                            type="button"
                            onClick={() => setShowHistory((v) => !v)}
                            aria-label={localize("com_knowledge.history_chat")}
                            className={cn(
                                "inline-flex size-4 shrink-0 items-center justify-center transition-colors",
                                showHistory ? "text-blue-500" : "text-[#212121] hover:text-[#4e5969]",
                            )}
                        >
                            <Outlined.History className="size-4" />
                        </button>
                        <button
                            type="button"
                            onClick={handleNewChat}
                            aria-label={localize("com_knowledge.create_chat")}
                            className="inline-flex size-4 shrink-0 items-center justify-center text-[#212121] transition-colors hover:text-[#4e5969]"
                        >
                            <Outlined.MessagePlus className="size-4" />
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

                {/* Messages — scrollable, with bottom fade-out under z-auto so the
                    focused-state grey overlay can stack above. */}
                <div className="relative min-h-0 flex-1">
                    {/* AiChatMessages owns the empty state; pass the brand ArticleQA
                        illustration so it follows the blue ⇄ green theme. */}
                    <AiChatMessages
                        messages={messages}
                        conversationId={activeChatId}
                        title=""
                        isLoading={isLoading}
                        isStreaming={isStreaming}
                        presetQuestions={[]}
                        hideShare
                        hideHeaderTitle
                        flatMode
                        knowledgeChatLayout
                        contentWidthClassName="max-w-none px-4"
                        emptyStateHint={folderQaHint}
                        emptyStateIllustration={<ArticleQAIllustration grey className="mx-auto block size-[80px]" />}
                        onPresetClick={() => { }}
                        onRegenerate={regenerate}
                    />
                    <div
                        aria-hidden
                        className="pointer-events-none absolute inset-x-0 bottom-0 z-[1] h-10 bg-gradient-to-t from-white to-white/0"
                    />
                </div>

                {/* Grey gradient overlay while the textarea has focus (keyboard up). */}
                {keyboardVisible && (
                    <div
                        aria-hidden
                        className="pointer-events-none absolute inset-0 z-[2] bg-gradient-to-b from-[rgba(0,0,0,0.10)] to-[rgba(0,0,0,0.45)]"
                    />
                )}

                {/* Input — `relative z-[3]` lifts above the grey overlay. */}
                <div className="relative z-[3] shrink-0 px-4 pb-[max(16px,env(safe-area-inset-bottom))]">
                    <KnowledgeAiInput
                        key={spaceId}
                        availableTags={availableTags}
                        modelOptions={bsConfig?.models}
                        modelValue={chatModel.id}
                        isStreaming={isStreaming}
                        disabled={!bsConfig?.models?.length}
                        onSend={handleSend}
                        onStop={stopGenerating}
                        variant="box"
                        onFocusChange={handleInputFocusChange}
                    />
                </div>

                {showHistory && (
                    <ConversationHistory
                        sessions={sessions}
                        activeChatId={activeChatId}
                        onSelect={handleHistorySelect}
                        onDelete={deleteSession}
                        onRename={renameSession}
                        onBack={handleHistoryBack}
                        onNewChat={handleHistoryNewChat}
                        onCollapse={handleHistoryCollapse}
                    />
                )}
            </div>
        );
    }

    // ─── Desktop + mobile-collapsed: bottom-anchored dock ──────────────────
    return (
        <>
            {/* Mobile collapsed-state grey overlay — when the box input is focused. */}
            {isH5 && !open && keyboardVisible && (
                <div
                    aria-hidden
                    className="pointer-events-none fixed inset-0 z-[19] bg-gradient-to-b from-[rgba(0,0,0,0.10)] to-[rgba(0,0,0,0.45)]"
                />
            )}
            <div
                className={cn(
                    // z-40 sits above the file table's sticky header (z-30) and its sticky cells
                    // (up to z-[35]); otherwise the expanded dialog's top is covered by the column header.
                    // pointer-events-none keeps the gradient backdrop visually masking the list while
                    // letting clicks fall through to the file rows behind it; the chat card below
                    // re-enables pointer events on its own box so it stays interactive.
                    "pointer-events-none absolute inset-x-0 bottom-0 z-40 flex flex-col px-4 pb-[max(16px,env(safe-area-inset-bottom))]",
                    // pt-10 always — the fade backdrop hides on focus but the input
                    // shouldn't jump when the keyboard opens.
                    !open && "pt-10",
                    // White fade backdrop. On mobile it hides while the input is focused so the
                    // grey keyboard overlay's gradient can carry through; on desktop there is no
                    // such overlay, so keep the fade consistent regardless of focus.
                    !open && (!isH5 || !keyboardVisible) && "bg-gradient-to-b from-white/0 to-white",
                    // Expanded: same transparent→white fade as the collapsed state, sized to the
                    // dialog (the container hugs the card when open, no pt-10), masking the list behind.
                    open && "bg-gradient-to-b from-white/0 to-white",
                )}
            >
                <div
                    // data-active exposes the default/active (input-focused) state for future
                    // styling hooks and QA, without coupling to the mobile keyboard flag.
                    data-active={isActive}
                    className={cn(
                        // pointer-events-auto restores interactivity on the card itself (its parent
                        // backdrop is pointer-events-none so the file list behind stays clickable).
                        "pointer-events-auto relative mx-auto flex w-full max-w-[800px] flex-col",
                        open &&
                            "overflow-hidden rounded-[20px] border border-[#ECECEC] bg-white shadow-[0_4px_20px_0_rgba(3,7,117,0.05)]",
                    )}
                >
                    {/* Floating expand button — shown whenever any conversation exists.
                        Gate on `sessions`, not `messages`: starting a new chat clears
                        `messages` but the session history is still there, so the button must
                        persist. Opens a fresh conversation. Shared by desktop + mobile-collapsed
                        docks. History stays reachable via the toggle inside the expanded panel. */}
                    {!open && (sessions.length > 0 || messages.length > 0) && (
                        <TooltipProvider>
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <button
                                        type="button"
                                        onClick={handleExpandNew}
                                        aria-label={localize("com_ui_expand")}
                                        className="absolute bottom-full right-0 z-10 mb-2 mr-2 flex size-8 items-center justify-center rounded-[20px] border border-[#EBEBEB] bg-white text-[#86909c] drop-shadow-[0_0_8px_rgba(3,7,117,0.05)] transition-colors hover:text-[#4e5969]"
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

                    {/* Header + messages grow upward above the input. Height scales with the
                        viewport (taller on large screens) — floored at 440px so small screens
                        don't regress, capped so it never overflows the file-display area. */}
                    <div
                        className={cn(
                            "overflow-hidden transition-[max-height] duration-300 ease-out",
                            open ? "max-h-[clamp(440px,70vh,calc(100vh_-_160px))]" : "max-h-0",
                        )}
                    >
                        <div className="flex h-[clamp(440px,70vh,calc(100vh_-_160px))] flex-col">
                            {/* Header */}
                            <div className="relative flex shrink-0 items-center gap-2 px-4 py-3">
                                <h3 className="pointer-events-none min-w-0 shrink truncate text-left text-sm font-medium leading-[22px] text-[#212121]">
                                    {assistantTitle}
                                </h3>
                                <div className="min-w-0 flex-1" aria-hidden />
                                {/* History · MessagePlus · DoubleDown — bare 16px icons, 12px gap, right-aligned (per Figma 11495:13085). */}
                                <div className="flex shrink-0 items-center justify-end gap-3 py-1">
                                    <TooltipProvider>
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <button
                                                    type="button"
                                                    onClick={() => setShowHistory((v) => !v)}
                                                    aria-label={localize("com_knowledge.history_chat")}
                                                    className={cn(
                                                        "inline-flex size-4 shrink-0 items-center justify-center transition-colors",
                                                        showHistory ? "text-blue-500" : "text-[#212121] hover:text-[#4e5969]",
                                                    )}
                                                >
                                                    <Outlined.History className="size-4 shrink-0" />
                                                </button>
                                            </TooltipTrigger>
                                            <TooltipContent>
                                                <p>{localize("com_knowledge.history_chat")}</p>
                                            </TooltipContent>
                                        </Tooltip>
                                    </TooltipProvider>
                                    <TooltipProvider>
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <button
                                                    type="button"
                                                    onClick={handleNewChat}
                                                    aria-label={localize("com_knowledge.create_chat")}
                                                    className="inline-flex size-4 shrink-0 items-center justify-center text-[#212121] transition-colors hover:text-[#4e5969]"
                                                >
                                                    <Outlined.MessagePlus className="size-4 shrink-0" />
                                                </button>
                                            </TooltipTrigger>
                                            <TooltipContent>
                                                <p>{localize("com_knowledge.create_chat")}</p>
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

                            {/* AiChatMessages owns the empty state; pass the brand ArticleQA
                                illustration so it follows the blue ⇄ green theme. */}
                            <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
                                <AiChatMessages
                                    messages={messages}
                                    conversationId={activeChatId}
                                    title=""
                                    isLoading={isLoading}
                                    isStreaming={isStreaming}
                                    presetQuestions={[]}
                                    hideShare
                                    hideHeaderTitle
                                    flatMode
                                    knowledgeChatLayout
                                    contentWidthClassName="max-w-none px-4"
                                    emptyStateHint={folderQaHint}
                                    emptyStateIllustration={<ArticleQAIllustration grey className="mx-auto block size-[80px]" />}
                                    onPresetClick={() => { }}
                                    onRegenerate={regenerate}
                                />
                            </div>
                        </div>
                    </div>

                    {/* Input bar — `box` collapsed, `line` expanded. */}
                    <KnowledgeAiInput
                        key={spaceId}
                        availableTags={availableTags}
                        modelOptions={bsConfig?.models}
                        modelValue={chatModel.id}
                        isStreaming={isStreaming}
                        disabled={!bsConfig?.models?.length}
                        onSend={handleSend}
                        onStop={stopGenerating}
                        variant={open ? "line" : "box"}
                        onFocusChange={handleInputFocusChange}
                    />

                    {open && showHistory && (
                        <ConversationHistory
                            sessions={sessions}
                            activeChatId={activeChatId}
                            onSelect={handleHistorySelect}
                            onDelete={deleteSession}
                            onRename={renameSession}
                            onBack={handleHistoryBack}
                            onNewChat={handleHistoryNewChat}
                            onCollapse={handleHistoryCollapse}
                        />
                    )}
                </div>
            </div>
        </>
    );
}
