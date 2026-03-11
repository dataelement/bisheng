/**
 * ConversationHistory — slide-in sidebar listing past conversations.
 * Displays conversation records for the current location (space or folder).
 */
import { HistoryIcon, MessageSquareIcon, XIcon } from "lucide-react";
import { Button } from "~/components";

interface ConversationRecord {
    id: string;
    title: string;
    createdAt: string;
    updatedAt: string;
}

interface ConversationHistoryProps {
    history: ConversationRecord[];
    activeConversationId?: string;
    onSelect: (id: string) => void;
    onClose: () => void;
}

export function ConversationHistory({
    history,
    activeConversationId,
    onSelect,
    onClose,
}: ConversationHistoryProps) {
    // Format date for display
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
                    <h3 className="text-sm font-medium text-[#1d2129]">历史会话</h3>
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

            {/* History list */}
            <div className="flex-1 overflow-y-auto">
                {history.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-center px-6 gap-2">
                        <MessageSquareIcon className="size-10 text-[#c9cdd4]" />
                        <p className="text-sm text-[#86909c]">暂无历史会话</p>
                    </div>
                ) : (
                    <div className="p-2 space-y-1">
                        {history.map(record => (
                            <button
                                key={record.id}
                                onClick={() => onSelect(record.id)}
                                className={`w-full text-left px-3 py-2.5 rounded-lg transition-colors ${record.id === activeConversationId
                                        ? "bg-[#e8f3ff] text-[#165dff]"
                                        : "text-[#4e5969] hover:bg-[#f7f8fa]"
                                    }`}
                            >
                                <p className="text-sm font-medium truncate">
                                    {record.title || "新的对话"}
                                </p>
                                <p className="text-xs text-[#86909c] mt-0.5">
                                    {formatDate(record.updatedAt)}
                                </p>
                            </button>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
