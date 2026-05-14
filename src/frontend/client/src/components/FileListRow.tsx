import { useState } from "react";
import { Folder, FileText, Download, MoreVertical, Circle, Edit, Tag } from "lucide-react";
import { KnowledgeFile, FileType, FileStatus, SpaceRole } from "~/api/knowledge";
import { formatFileSize, getFileTypeColor } from "~/mock/knowledge";
import { Badge } from "~/components/ui/Badge";
import { cn } from "~/utils";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger
} from "~/components/ui/DropdownMenu";

interface FileListRowProps {
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

export function FileListRow({
    file,
    userRole,
    isSelected,
    onSelect,
    onDownload,
    onRename,
    onDelete,
    onEditTags,
    onRetry
}: FileListRowProps) {
    const [hovered, setHovered] = useState(false);
    const isAdmin = userRole === SpaceRole.CREATOR || userRole === SpaceRole.ADMIN;
    const isFolder = file.type === FileType.FOLDER;

    const formatTime = (dateString: string) => {
        const date = new Date(dateString);
        return date.toLocaleString("zh-CN", {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit"
        }).replace(/\//g, "-");
    };

    const getFileTypeLabel = (type: FileType): string => {
        const typeMap: Record<FileType, string> = {
            [FileType.FOLDER]: "文件夹",
            [FileType.PDF]: "pdf",
            [FileType.DOC]: "doc",
            [FileType.DOCX]: "docx",
            [FileType.XLS]: "xls",
            [FileType.XLSX]: "xlsx",
            [FileType.PPT]: "ppt",
            [FileType.PPTX]: "pptx",
            [FileType.JPG]: "jpg",
            [FileType.JPEG]: "jpeg",
            [FileType.PNG]: "png",
            [FileType.OTHER]: "其他"
        };
        return typeMap[type] || type;
    };

    const getStatusDisplay = () => {
        if (isFolder) {
            return <span className="text-[#86909c]">7/11</span>;
        }

        switch (file.status) {
            case FileStatus.SUCCESS:
                return <span className="text-[#00b42a]">成功</span>;
            case FileStatus.PROCESSING:
                return <span className="text-[#165dff]">处理中</span>;
            case FileStatus.FAILED:
                return <span className="text-[#f53f3f]">失败</span>;
            default:
                return null;
        }
    };

    return (
        <div
            className={cn(
                "flex items-center px-4 py-3 border-b border-[#e5e6eb] hover:bg-[#f7f8fa] transition-colors cursor-pointer",
                isSelected && "bg-[#e8f3ff]",
                hovered && "bg-[#f7f8fa]"
            )}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
        >
            {/* 复选框 */}
            <div className="w-12 flex items-center justify-center">
                <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={(e) => onSelect(e.target.checked)}
                    className="size-4"
                    onClick={(e) => e.stopPropagation()}
                />
            </div>

            {/* 文件名 */}
            <div className="flex-1 flex items-center gap-2 min-w-0">
                {isFolder ? (
                    <Folder className="size-4 flex-shrink-0" style={{ color: getFileTypeColor(file.type) }} />
                ) : (
                    <FileText className="size-4 flex-shrink-0" style={{ color: getFileTypeColor(file.type) }} />
                )}
                <span className="text-sm text-[#1d2129] truncate" title={file.name}>
                    {file.name}
                </span>
            </div>

            {/* 文件类型 */}
            <div className="w-28 text-sm text-[#86909c]">
                {getFileTypeLabel(file.type)}
            </div>

            {/* 文件大小 */}
            <div className="w-32 text-sm text-[#86909c]">
                {file.size !== undefined ? formatFileSize(file.size) : "--"}
            </div>

            {/* 标签 */}
            <div className="w-48 flex items-center gap-1">
                {file.tags.length > 0 ? (
                    <>
                        {file.tags.slice(0, 2).map((tag, index) => (
                            <Badge key={index} variant="secondary" className="text-xs px-2 py-0">
                                {tag}
                            </Badge>
                        ))}
                        {file.tags.length > 2 && (
                            <span className="text-xs text-[#86909c]">+{file.tags.length - 2}</span>
                        )}
                    </>
                ) : (
                    <span className="text-sm text-[#86909c]">--</span>
                )}
            </div>

            {/* 更新时间 */}
            <div className="w-48 text-sm text-[#86909c]">
                {formatTime(file.updatedAt)}
            </div>

            {/* 状态 */}
            <div className="w-24 text-sm">
                {getStatusDisplay()}
            </div>

            {/* 操作 */}
            <div className="w-24 flex items-center gap-2 justify-end">
                {hovered && (
                    <>
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                onDownload();
                            }}
                            className="p-1.5 hover:bg-[#e5e6eb] rounded"
                            title="下载"
                        >
                            <Download className="size-4 text-[#4e5969]" />
                        </button>

                        {isAdmin && (
                            <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                    <button
                                        className="p-1.5 hover:bg-[#e5e6eb] rounded"
                                        onClick={(e) => e.stopPropagation()}
                                    >
                                        <MoreVertical className="size-4 text-[#4e5969]" />
                                    </button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end">
                                    <DropdownMenuItem onClick={onEditTags}>
                                        <Tag className="size-4 mr-2" />
                                        编辑标签
                                    </DropdownMenuItem>
                                    <DropdownMenuItem onClick={onRename}>
                                        <Edit className="size-4 mr-2" />
                                        重命名
                                    </DropdownMenuItem>
                                    {file.status === FileStatus.FAILED && onRetry && (
                                        <DropdownMenuItem onClick={onRetry}>
                                            <Circle className="size-4 mr-2" />
                                            重试
                                        </DropdownMenuItem>
                                    )}
                                    <DropdownMenuItem onClick={onDelete} className="text-[#f53f3f]">
                                        <Circle className="size-4 mr-2" />
                                        删除
                                    </DropdownMenuItem>
                                </DropdownMenuContent>
                            </DropdownMenu>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}
