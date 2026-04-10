/**
 * ConversationHistory — slide-in sidebar listing past conversations.
 * Displays server-backed session records with inline rename + delete support.
 */
import { useEffect, useRef, useState } from "react";
import {
    HistoryIcon,
    MessageSquareIcon,
    MoreHorizontalIcon,
    PencilLine,
    Trash2Icon,
    XIcon,
} from "lucide-react";
import { NotificationSeverity } from "~/common";
import { Button } from "~/components";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import { Input } from "~/components/ui/Input";
import type { FolderSession } from "~/api/chatApi";
import { knowledgeSpaceDropdownSurfaceClassName } from "~/components/SidebarListMoreMenu";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import { cn } from "~/utils";

interface ConversationHistoryProps {
    sessions: FolderSession[];
    activeChatId: string;
    onSelect: (chatId: string) => void;
    onDelete: (chatId: string) => void;
    onRename: (chatId: string, name: string) => Promise<boolean>;
    onClose: () => void;
}

export function ConversationHistory({
    sessions,
    activeChatId,
    onSelect,
    onDelete,
    onRename,
    onClose,
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
        <div className="absolute inset-0 z-30 flex flex-col bg-white animate-in slide-in-from-right duration-200">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-[#e5e6eb] shrink-0">
                <div className="flex items-center gap-2">
                    <HistoryIcon className="size-4 text-[#4e5969]" />
                    <h3 className="text-sm font-medium text-[#1d2129]">
                        {localize("com_knowledge.history_chat")}
                    </h3>
                </div>
                <Button
                    variant="ghost"
                    size="icon"
                    className="w-7 h-7 text-[#86909c] hover:text-[#4e5969]"
                    onClick={onClose}
                >
                    <XIcon className="size-4" />
                </Button>
            </div>

            {/* Session list */}
            <div className="flex-1 overflow-y-auto">
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
                                    className={`group flex items-center justify-between w-full px-3 py-2.5 rounded-lg transition-colors ${isEditing ? "cursor-default" : "cursor-pointer"
                                        } ${session.chat_id === activeChatId
                                            ? "bg-[#e8f3ff] text-[#165dff]"
                                            : "text-[#4e5969] hover:bg-[#f7f8fa]"
                                        }`}
                                    onClick={() => {
                                        if (isEditing) return;
                                        onSelect(session.chat_id);
                                    }}
                                >
                                    <div className="flex-1 min-w-0 pr-1">
                                        {isEditing ? (
                                            <Input
                                                ref={renameInputRef}
                                                value={renameValue}
                                                onChange={(e) => setRenameValue(e.target.value)}
                                                disabled={renameSubmitting}
                                                className="h-7 text-sm font-medium px-2 py-1 border-[#c9cdd4] focus-visible:ring-1"
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
                                            <p className="text-sm font-medium truncate">
                                                {getSessionDisplayName(session)}
                                            </p>
                                        )}
                                        <p className="text-xs text-[#86909c] mt-0.5">
                                            {formatDate(session.update_time || session.create_time)}
                                        </p>
                                    </div>
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
                                                        "flex-shrink-0 ml-2 p-1 rounded text-[#86909c] hover:text-[#4e5969] hover:bg-black/5 opacity-0 group-hover:opacity-100 transition-opacity",
                                                        (menuOpen || session.chat_id === activeChatId) &&
                                                        "opacity-100"
                                                    )}
                                                    onClick={(e) => e.stopPropagation()}
                                                    aria-label="More actions"
                                                >
                                                    <MoreHorizontalIcon className="size-4" />
                                                </button>
                                            </DropdownMenuTrigger>
                                            <DropdownMenuContent
                                                align="end"
                                                className={cn("min-w-[140px]", knowledgeSpaceDropdownSurfaceClassName)}
                                                onClick={(e) => e.stopPropagation()}
                                            >
                                                <DropdownMenuItem
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        startInlineRename(session);
                                                    }}
                                                >
                                                    <PencilLine className="size-4 mr-2" />
                                                    {localize("com_knowledge.rename")}
                                                </DropdownMenuItem>
                                                <DropdownMenuItem
                                                    className="text-[#f53f3f] focus:text-[#f53f3f]"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        onDelete(session.chat_id);
                                                    }}
                                                >
                                                    <Trash2Icon className="size-4 mr-2 text-[#f53f3f]" />
                                                    {localize("com_notifications_delete")}
                                                </DropdownMenuItem>
                                            </DropdownMenuContent>
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
