import { useState } from "react";
import { Folder, FileText, Download, MoreVertical, Circle } from "lucide-react";
import { KnowledgeFile, FileType, FileStatus, SpaceRole } from "~/api/knowledge";
import { formatFileSize, getFileTypeColor } from "~/mock/knowledge";
import { Badge } from "~/components/ui/Badge";
import { Card, CardContent } from "~/components/ui/Card";
import { cn } from "~/utils";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger
} from "~/components/ui/DropdownMenu";

interface FileCardProps {
    file: KnowledgeFile;
    userRole: SpaceRole;
    isSelected: boolean;
    onSelect: (selected: boolean) => void;
    onDownload: () => void;
    onRename: () => void;
    onDelete: () => void;
    onEditTags: () => void;
    onRetry?: () => void;
}

export function FileCard({
    file,
    userRole,
    isSelected,
    onSelect,
    onDownload,
    onRename,
    onDelete,
    onEditTags,
    onRetry
}: FileCardProps) {
    const [hovered, setHovered] = useState(false);
    const isAdmin = userRole === SpaceRole.CREATOR || userRole === SpaceRole.ADMIN;
    const isFolder = file.type === FileType.FOLDER;

    const formatTime = (dateString: string) => {
        const date = new Date(dateString);
        const now = new Date();
        const isToday = date.toDateString() === now.toDateString();

        if (isToday) {
            return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
        } else {
            return date.toDateString();
        }
    };

    const getStatusDot = () => {
        if (!isAdmin || isFolder) return null;

        switch (file.status) {
            case FileStatus.PROCESSING:
                return <Circle className="size-2 fill-[#165dff] text-[#165dff]" />;
            case FileStatus.FAILED:
                return <Circle className="size-2 fill-[#f53f3f] text-[#f53f3f]" />;
            default:
                return null;
        }
    };

    return (
        <Card
            className={cn(
                "transition-all cursor-pointer group",
                isSelected && "border-[#165dff]",
                hovered && "shadow-md"
            )}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
        >
            <CardContent className="p-3">
                {/* 缩略图或图标区域 */}
                <div className="relative mb-2 h-32 bg-[#f7f8fa] rounded flex items-center justify-center">
                    {isFolder ? (
                        <Folder className="size-16" style={{ color: getFileTypeColor(file.type) }} />
                    ) : file.thumbnail ? (
                        <img src={file.thumbnail} alt={file.name} className="w-full h-full object-cover rounded" />
                    ) : (
                        <FileText className="size-16" style={{ color: getFileTypeColor(file.type) }} />
                    )}

                    {/* Hover 时显示的操作 */}
                    {hovered && (
                        <>
                            <div className="absolute top-2 right-2">
                                <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={(e) => onSelect(e.target.checked)}
                                    className="size-4"
                                    onClick={(e) => e.stopPropagation()}
                                />
                            </div>

                            <div className="absolute bottom-2 right-2 flex gap-1">
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        onDownload();
                                    }}
                                    className="p-1.5 bg-white rounded shadow-sm hover:bg-[#f7f8fa]"
                                >
                                    <Download className="size-4 text-[#4e5969]" />
                                </button>

                                {isAdmin && (
                                    <DropdownMenu>
                                        <DropdownMenuTrigger asChild>
                                            <button
                                                className="p-1.5 bg-white rounded shadow-sm hover:bg-[#f7f8fa]"
                                                onClick={(e) => e.stopPropagation()}
                                            >
                                                <MoreVertical className="size-4 text-[#4e5969]" />
                                            </button>
                                        </DropdownMenuTrigger>
                                        <DropdownMenuContent align="end">
                                            <DropdownMenuItem onClick={onEditTags}>编辑标签</DropdownMenuItem>
                                            <DropdownMenuItem onClick={onRename}>重命名</DropdownMenuItem>
                                            <DropdownMenuItem onClick={onDelete} className="text-[#f53f3f]">
                                                删除
                                            </DropdownMenuItem>
                                            {file.status === FileStatus.FAILED && onRetry && (
                                                <DropdownMenuItem onClick={onRetry}>重试</DropdownMenuItem>
                                            )}
                                        </DropdownMenuContent>
                                    </DropdownMenu>
                                )}
                            </div>
                        </>
                    )}
                </div>

                {/* 文件名和状态 */}
                <div className="flex items-center gap-1 mb-2">
                    {getStatusDot()}
                    <span className="text-sm font-medium truncate flex-1" title={file.name}>
                        {file.name}
                    </span>
                </div>

                {/* 标签 */}
                {file.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-2 min-h-[24px]">
                        {file.tags.slice(0, 3).map((tag, index) => (
                            <Badge key={index} variant="secondary" className="text-xs px-2 py-0">
                                {tag}
                            </Badge>
                        ))}
                        {file.tags.length > 3 && (
                            <Badge variant="secondary" className="text-xs px-2 py-0">
                                +{file.tags.length - 3}
                            </Badge>
                        )}
                    </div>
                )}

                {/* 底部信息 */}
                <div className="flex items-center justify-between text-xs text-[#86909c]">
                    {isAdmin && isFolder && (
                        <span>7/11</span>
                    )}
                    <span className="ml-auto">{formatTime(file.updatedAt)}</span>
                </div>
            </CardContent>
        </Card>
    );
}
