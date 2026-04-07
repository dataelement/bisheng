/**
 * ConversationHistory — slide-in sidebar listing past conversations.
 * Displays server-backed session records with delete support.
 */
import { HistoryIcon, MessageSquareIcon, MoreHorizontalIcon, Trash2Icon, XIcon } from "lucide-react";
import { Button } from "~/components";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import type { FolderSession } from "~/api/chatApi";
import { useLocalize } from "~/hooks";

interface ConversationHistoryProps {
    sessions: FolderSession[];
    activeChatId: string;
    onSelect: (chatId: string) => void;
    onDelete: (chatId: string) => void;
    onClose: () => void;
}

export function ConversationHistory({
    sessions,
    activeChatId,
    onSelect,
    onDelete,
    onClose,
}: ConversationHistoryProps) {
    // Format date for display
    const localize = useLocalize();
  const formatDate = (dateStr: string) => {
        const d = new Date(dateStr);
        const now = new Date();
        const isToday = d.toDateString() === now.toDateString();
        if (isToday) {
            return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
        }
        return d.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
    };

    return (
        <div className="absolute inset-0 z-30 flex flex-col bg-white animate-in slide-in-from-right duration-200">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-[#e5e6eb] shrink-0">
                <div className="flex items-center gap-2">
                    <HistoryIcon className="size-4 text-[#4e5969]" />
                    <h3 className="text-sm font-medium text-[#1d2129]">{localize("com_knowledge.history_chat")}</h3>
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
                        <p className="text-sm text-[#86909c]">{localize("com_knowledge.no_history_chat")}</p>
                    </div>
                ) : (
                    <div className="p-2 space-y-1">
                        {sessions.map((session) => (
                            <div
                                key={session.chat_id}
                                className={`group flex items-center justify-between w-full px-3 py-2.5 rounded-lg transition-colors cursor-pointer ${
                                    session.chat_id === activeChatId
                                        ? "bg-[#e8f3ff] text-[#165dff]"
                                        : "text-[#4e5969] hover:bg-[#f7f8fa]"
                                }`}
                                onClick={() => onSelect(session.chat_id)}
                            >
                                <div className="flex-1 min-w-0">
                                    <p className="text-sm font-medium truncate">
                                        {session.flow_name || localize("com_knowledge.new_chat")}
                                    </p>
                                    <p className="text-xs text-[#86909c] mt-0.5">
                                        {formatDate(session.update_time || session.create_time)}
                                    </p>
                                </div>
                                {/* More menu — visible on hover */}
                                <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                        <button
                                            type="button"
                                            className="flex-shrink-0 ml-2 p-1 rounded text-[#86909c] hover:text-[#4e5969] hover:bg-black/5 opacity-0 group-hover:opacity-100 max-[575px]:opacity-100 [@media(hover:none)]:opacity-100 transition-all"
                                            onClick={(e) => e.stopPropagation()}
                                            aria-label="More actions"
                                        >
                                            <MoreHorizontalIcon className="size-4" />
                                        </button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent
                                        align="end"
                                        className="min-w-[140px]"
                                        onClick={(e) => e.stopPropagation()}
                                    >
                                        <DropdownMenuItem
                                            className="text-[#f53f3f] focus:text-[#f53f3f]"
                                            onClick={() => onDelete(session.chat_id)}
                                        >
                                            <Trash2Icon className="size-4 mr-2" />
                                            {localize("com_notifications_delete")}
                                        </DropdownMenuItem>
                                    </DropdownMenuContent>
                                </DropdownMenu>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
