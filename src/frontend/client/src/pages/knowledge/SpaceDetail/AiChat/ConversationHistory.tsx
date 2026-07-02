/**
 * ConversationHistory — overlay panel listing past conversations.
 * Displays server-backed session records with inline rename + delete support.
 */
import { useEffect, useRef, useState } from "react";
import { MessageSquareIcon } from "lucide-react";
import { Outlined } from "bisheng-icons";
import { NotificationSeverity } from "~/common";
import {
    DropdownMenu,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import { ActionMenuContent, ActionMenuItem } from "~/components/ActionMenu";
import { Input } from "~/components/ui/Input";
import type { FolderSession } from "~/api/chatApi";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import { cn } from "~/utils";

interface ConversationHistoryProps {
    sessions: FolderSession[];
    activeChatId: string;
    onSelect: (chatId: string) => void;
    onDelete: (chatId: string) => void;
    onRename: (chatId: string, name: string) => Promise<boolean>;
    /** Back to the conversation view (standard variant only). */
    onBack?: () => void;
    /** Start a fresh conversation and reveal it (standard variant only). */
    onNewChat?: () => void;
    /** Collapse the whole dock. */
    onCollapse: () => void;
    /**
     * Entry-dependent look:
     * - "standard" (default) — opened from the assistant header; slides in from the
     *   right and keeps the back + new-chat header buttons.
     * - "direct" — opened straight from the collapsed dock's floating history button;
     *   fades in and shows only the title + collapse button.
     */
    variant?: "standard" | "direct";
    /**
     * Layout mode. Default (false) overlays the parent card (`absolute inset-0`).
     * When true the panel sizes to its session list instead — min 160px, capped at
     * the expanded-panel default height so it never grows taller than the normal
     * conversation view. Used by the direct desktop entry.
     */
    fitContent?: boolean;
}

export function ConversationHistory({
    sessions,
    activeChatId,
    onSelect,
    onDelete,
    onRename,
    onBack,
    onNewChat,
    onCollapse,
    variant = "standard",
    fitContent = false,
}: ConversationHistoryProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const [menuOpenChatId, setMenuOpenChatId] = useState<string | null>(null);
    const [editingChatId, setEditingChatId] = useState<string | null>(null);
    const [renameValue, setRenameValue] = useState("");
    const [renameBaseline, setRenameBaseline] = useState("");
    const [renameSubmitting, setRenameSubmitting] = useState(false);
    const renameInputRef = useRef<HTMLInputElement>(null);

    const getSessionDisplayName = (session: FolderSession) => {
        const raw = session.name;
        if (raw != null && String(raw).trim() !== "") {
            return String(raw).trim();
        }
        return localize("com_knowledge.new_chat");
    };

    const formatDate = (dateStr: string) => {
        const d = new Date(dateStr);
        const now = new Date();
        const isToday = d.toDateString() === now.toDateString();
        if (isToday) {
            return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
        }
        return d.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
    };

    const startInlineRename = (session: FolderSession) => {
        setMenuOpenChatId(null);
        const title = getSessionDisplayName(session);
        setRenameBaseline(title);
        setRenameValue(title);
        setEditingChatId(session.chat_id);
    };

    useEffect(() => {
        if (!editingChatId) return;
        const t = window.setTimeout(() => {
            const el = renameInputRef.current;
            if (el) {
                el.focus();
                el.select();
            }
        }, 0);
        return () => window.clearTimeout(t);
    }, [editingChatId]);

    const commitRename = async () => {
        if (!editingChatId || renameSubmitting) return;
        const trimmed = renameValue.trim();
        const session = sessions.find((s) => s.chat_id === editingChatId);
        if (!session) {
            setEditingChatId(null);
            setRenameBaseline("");
            return;
        }
        if (!trimmed || trimmed === renameBaseline.trim()) {
            setEditingChatId(null);
            setRenameBaseline("");
            return;
        }
        setRenameSubmitting(true);
        try {
            const ok = await onRename(editingChatId, trimmed);
            if (ok) {
                setEditingChatId(null);
                setRenameBaseline("");
                showToast({
                    message: localize("com_knowledge.rename_success"),
                    severity: NotificationSeverity.SUCCESS,
                    showIcon: true,
                } as any);
            } else {
                showToast({
                    message: localize("com_knowledge.rename_failed"),
                    severity: NotificationSeverity.ERROR,
                    showIcon: true,
                } as any);
            }
        } finally {
            setRenameSubmitting(false);
        }
    };

    const cancelRename = () => {
        if (renameSubmitting) return;
        setEditingChatId(null);
        setRenameBaseline("");
    };

    return (
        <div
            className={cn(
                "z-30 flex flex-col bg-white",
                // Fit-content hugs the session list — floored at 160px, capped at the
                // expanded-panel default height. Its entrance is animated by the parent's
                // max-height wrapper, so no animate-in here. Overlay mode fills the card:
                // standard entry slides in like a drawer; direct entry just fades in.
                fitContent
                    ? "relative min-h-[160px] max-h-[clamp(440px,70vh,calc(100vh_-_160px))]"
                    : cn(
                          "absolute inset-0 animate-in",
                          variant === "direct"
                              ? "fade-in duration-150"
                              : "slide-in-from-right duration-200",
                      ),
            )}
        >
            {/* Header — mirrors the AI assistant header exactly (px-4 py-3, no bottom
                border, leading-[22px] title row, right icon group in py-1) so both panels
                line up. Standard: back · divider · title + new chat · collapse on the
                right. Direct: title + collapse only. */}
            <div className="relative flex shrink-0 items-center gap-2 px-4 py-3">
                {variant === "standard" ? (
                    // Back arrow · divider · title — 12px gap between all three.
                    <div className="flex shrink-0 items-center gap-3">
                        <button
                            type="button"
                            onClick={onBack}
                            aria-label={localize("com_ui_go_back")}
                            className="inline-flex size-4 shrink-0 items-center justify-center text-[#999999] transition-colors hover:text-[#4e5969]"
                        >
                            <Outlined.ArrowLeft className="size-4" />
                        </button>
                        <span className="h-3.5 w-px shrink-0 bg-[#e5e6eb]" aria-hidden />
                        <h3 className="text-sm font-medium leading-[22px] text-[#212121]">
                            {localize("com_knowledge.history_chat")}
                        </h3>
                    </div>
                ) : (
                    <h3 className="shrink-0 text-sm font-medium leading-[22px] text-[#212121]">
                        {localize("com_knowledge.history_chat")}
                    </h3>
                )}
                <div className="min-w-0 flex-1" aria-hidden />
                <div className="flex shrink-0 items-center justify-end gap-3 py-1">
                    {variant === "standard" && (
                        <button
                            type="button"
                            onClick={onNewChat}
                            aria-label={localize("com_knowledge.create_chat")}
                            className="inline-flex size-4 shrink-0 items-center justify-center text-[#212121] transition-colors hover:text-[#4e5969]"
                        >
                            <Outlined.MessagePlus className="size-4" />
                        </button>
                    )}
                    <button
                        type="button"
                        onClick={onCollapse}
                        aria-label={localize("com_ui_collapse")}
                        className="inline-flex size-4 shrink-0 items-center justify-center text-[#999999] transition-colors hover:text-[#4e5969]"
                    >
                        <Outlined.DoubleDown className="size-4" />
                    </button>
                </div>
            </div>

            {/* Session list — min-h-0 lets it shrink and scroll when the panel hits
                its max height in fit-content mode. */}
            <div className="min-h-0 flex-1 overflow-y-auto">
                {sessions.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-center px-6 gap-2">
                        <MessageSquareIcon className="size-10 text-[#c9cdd4]" />
                        <p className="text-sm text-[#86909c]">
                            {localize("com_knowledge.no_history_chat")}
                        </p>
                    </div>
                ) : (
                    <div className="p-2 space-y-1">
                        {sessions.map((session) => {
                            const menuOpen = menuOpenChatId === session.chat_id;
                            const isEditing = editingChatId === session.chat_id;
                            return (
                                <div
                                    key={session.chat_id}
                                    className={cn(
                                        // Active + hover colors match the knowledge-space sidebar item (gray, no blue).
                                        "group flex h-8 items-center gap-2 rounded-lg px-3 text-[#1d2129] transition-colors",
                                        isEditing ? "cursor-default" : "cursor-pointer",
                                        session.chat_id === activeChatId
                                            ? "bg-[#EEEEEE] hover:bg-[#EEEEEE]"
                                            : "hover:bg-[#F4F4F4]",
                                    )}
                                    onClick={() => {
                                        if (isEditing) return;
                                        onSelect(session.chat_id);
                                    }}
                                >
                                    {isEditing ? (
                                        <Input
                                            ref={renameInputRef}
                                            value={renameValue}
                                            onChange={(e) => setRenameValue(e.target.value)}
                                            disabled={renameSubmitting}
                                            className="h-6 flex-1 px-2 py-0 text-sm font-medium border-[#c9cdd4] focus-visible:ring-1"
                                            onClick={(e) => e.stopPropagation()}
                                            onKeyDown={(e) => {
                                                if (e.key === "Enter") {
                                                    e.preventDefault();
                                                    void commitRename();
                                                } else if (e.key === "Escape") {
                                                    e.preventDefault();
                                                    cancelRename();
                                                }
                                            }}
                                            onBlur={() => {
                                                void commitRename();
                                            }}
                                        />
                                    ) : (
                                        // Name + time on one line: name truncates, time sticks right after it.
                                        <div className="flex min-w-0 flex-1 items-baseline gap-2">
                                            <span
                                                className={cn(
                                                    "min-w-0 truncate text-sm",
                                                    // Active conversation title = semibold (600), matching the sidebar selected item.
                                                    session.chat_id === activeChatId ? "font-semibold" : "font-medium",
                                                )}
                                            >
                                                {getSessionDisplayName(session)}
                                            </span>
                                            <span className="shrink-0 text-xs text-[#86909c]">
                                                {formatDate(session.update_time || session.create_time)}
                                            </span>
                                        </div>
                                    )}
                                    {!isEditing && (
                                        <DropdownMenu
                                            open={menuOpen}
                                            onOpenChange={(open) =>
                                                setMenuOpenChatId(open ? session.chat_id : null)
                                            }
                                        >
                                            <DropdownMenuTrigger asChild>
                                                <button
                                                    type="button"
                                                    className={cn(
                                                        "flex-shrink-0 rounded p-1 text-[#86909c] hover:bg-black/5 hover:text-[#4e5969] transition-opacity",
                                                        // Desktop mouse: show on row hover or when menu open / active session; touch: always visible
                                                        "opacity-0 group-hover:opacity-100 coarse-pointer:opacity-100",
                                                        (menuOpen || session.chat_id === activeChatId) &&
                                                            "opacity-100",
                                                    )}
                                                    onClick={(e) => e.stopPropagation()}
                                                    aria-label="More actions"
                                                >
                                                    <Outlined.More className="size-4" />
                                                </button>
                                            </DropdownMenuTrigger>
                                            <ActionMenuContent
                                                width={140}
                                                onClick={(e) => e.stopPropagation()}
                                            >
                                                <ActionMenuItem
                                                    icon={<Outlined.Edit />}
                                                    label={localize("com_knowledge.rename")}
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        startInlineRename(session);
                                                    }}
                                                />
                                                <ActionMenuItem
                                                    danger
                                                    icon={<Outlined.Delete />}
                                                    label={localize("com_notifications_delete")}
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        onDelete(session.chat_id);
                                                    }}
                                                />
                                            </ActionMenuContent>
                                        </DropdownMenu>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
}
