import { Circle, MoreVertical, X } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { FileStatus, FileType, KnowledgeFile, SpaceRole } from "~/api/knowledge";
import { Button, Checkbox } from "~/components";
import { Card, CardContent } from "~/components/ui/Card";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger
} from "~/components/ui/DropdownMenu";
import { cn } from "~/utils";
import FileIconRenderer from "./FileIcon";
import TagGroup from "./TagGroup";
import { useToastContext } from "~/Providers";

interface FileCardProps {
    file: KnowledgeFile;
    userRole: SpaceRole;
    isSelected: boolean;
    onSelect: (selected: boolean) => void;
    onDownload: () => void;
    onRename: (newName: string) => void;
    onDelete: () => void;
    onEditTags: () => void;
    onRetry?: () => void;
    onValidateName?: (newName: string) => string | null;
    onCancelCreate?: () => void;
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
    onRetry,
    onValidateName,
    onCancelCreate
}: FileCardProps) {
    const isCreating = !!(file as any).isCreating;
    const [hovered, setHovered] = useState(false);
    const [isRenaming, setIsRenaming] = useState(isCreating);
    const [renameValue, setRenameValue] = useState(file.name);
    const inputRef = useRef<HTMLInputElement>(null);
    const { showToast } = useToastContext();

    const isAdmin = userRole === SpaceRole.CREATOR || userRole === SpaceRole.ADMIN;
    const isFolder = file.type === FileType.FOLDER;

    useEffect(() => {
        if (isRenaming && inputRef.current) {
            inputRef.current.focus();
            // Select text before extension if possible
            const dotIndex = file.name.lastIndexOf('.');
            if (dotIndex > 0 && !isFolder) {
                inputRef.current.setSelectionRange(0, dotIndex);
            } else {
                inputRef.current.select();
            }
        }
    }, [isRenaming, isFolder, file.name]);

    const handleRenameSubmit = () => {
        const trimmed = renameValue.trim();

        if (isCreating && !trimmed) {
            showToast({ message: "文件夹名称不能为空", status: "error", severity: "error" } as any);
            inputRef.current?.focus();
            return;
        }

        if (!isCreating && !trimmed) {
            setRenameValue(file.name);
            setIsRenaming(false);
            return;
        }

        if (trimmed === file.name && !isCreating) {
            setIsRenaming(false);
            return;
        }

        if (onValidateName) {
            const err = onValidateName(trimmed);
            if (err) {
                showToast({ message: err, status: "error", severity: "error" } as any);
                inputRef.current?.focus();
                return;
            }
        }

        onRename(trimmed);
        setIsRenaming(false);
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter') {
            handleRenameSubmit();
        } else if (e.key === 'Escape') {
            if (isCreating) {
                onCancelCreate?.();
            } else {
                setRenameValue(file.name);
                setIsRenaming(false);
            }
        }
    };

    const formatTime = (dateString: string) => {
        const date = new Date(dateString);
        const yyyy = date.getFullYear();
        const mm = String(date.getMonth() + 1).padStart(2, '0');
        const dd = String(date.getDate()).padStart(2, '0');
        const HH = String(date.getHours()).padStart(2, '0');
        const min = String(date.getMinutes()).padStart(2, '0');

        const now = new Date();
        const isToday = date.toDateString() === now.toDateString();

        if (isToday) {
            return `${HH}:${min}`;
        } else {
            return `${yyyy}-${mm}-${dd}`;
        }
    };

    const getStatusText = () => {
        if (isRenaming) {
            return (
                <div className="flex-1 min-w-0 pr-1">
                    <input
                        ref={inputRef}
                        type="text"
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onBlur={handleRenameSubmit}
                        onKeyDown={handleKeyDown}
                        onClick={(e) => e.stopPropagation()}
                        className="w-full h-6 px-1.5 text-sm border border-[#165dff] rounded outline-none shadow-[0_0_0_2px_rgba(22,93,255,0.2)] bg-white font-normal"
                    />
                </div>
            );
        }

        if (!isAdmin || isFolder) {
            return <span className="truncate">{file.name}</span>;
        }

        switch (file.status) {
            case FileStatus.PROCESSING:
            case FileStatus.QUEUED:
            case FileStatus.UPLOADING:
                return (
                    <div className="flex items-center flex-1 min-w-0">
                        <Circle className="size-1.5 fill-[#165dff] text-[#165dff] shrink-0 mr-1.5" />
                        <span className="truncate text-[#1d2129]">{file.name}</span>
                        <span className="text-[#86909c] text-xs ml-1.5 shrink-0">上传中...</span>
                    </div>
                );
            case FileStatus.FAILED:
            case FileStatus.TIMEOUT:
                return (
                    <div className="flex items-center flex-1 min-w-0">
                        <Circle className="size-1.5 fill-[#f53f3f] text-[#f53f3f] shrink-0 mr-1.5" />
                        <span className="truncate text-[#1d2129]">{file.name}</span>
                    </div>
                );
            default:
                return <span className="truncate text-[#1d2129]">{file.name}</span>;
        }
    };

    const handleCardClick = () => {
        if (isFolder || isCreating || isRenaming) return;
        const url = `${__APP_ENV__.BASE_URL}/knowledge/file/${file.id}?name=${encodeURIComponent(file.name)}&type=${encodeURIComponent(file.type)}`;
        window.open(url, '_blank');
    };

    return (
        <Card
            className={cn(
                "group transition-all cursor-pointer group rounded-lg overflow-hidden border p-0 gap-0",
                isSelected ? "border-primary shadow-sm" : "hover:border-[#c9cdd4]",
                hovered && "shadow-md"
            )}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
            onClick={handleCardClick}
        >
            <CardContent className="p-0 flex flex-col">
                {/* 缩略图或图标区域 */}
                <div className={`relative h-[106px] flex items-center justify-center shrink-0 ${isFolder ? 'bg-[#FAFCFF]' : 'bg-gray-50'}`}>
                    <FileIconRenderer file={file} isFolder={isFolder} />

                    {/* Hover 时显示的操作 */}
                    {(hovered || isSelected) && (
                        <div className="absolute top-2 left-2 z-10">
                            <Checkbox className={isSelected ? "border-primary" : "border-gray-400"} checked={isSelected} onCheckedChange={(checked) => onSelect(!!checked)} onClick={(e) => e.stopPropagation()} />
                        </div>
                    )}

                    <div className="absolute top-2 right-2 z-10 opacity-0 group-hover:opacity-100 transition-opacity">
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <Button
                                    variant="outline"
                                    size="icon"
                                    className="w-5 h-5 rounded-md"
                                    onClick={(e) => e.stopPropagation()}
                                >
                                    <MoreVertical className="size-4 text-[#4e5969] group-hover:text-[#1d2129]" />
                                </Button>
                            </DropdownMenuTrigger>

                            <DropdownMenuContent align="end" className="min-w-[120px]">
                                {/* 下载功能现在移到了列表第一项 */}
                                <DropdownMenuItem onClick={(e) => {
                                    e.stopPropagation();
                                    onDownload();
                                }}>
                                    <span>下载</span>
                                </DropdownMenuItem>

                                {/* 如果是管理员，显示后续管理操作 */}
                                {isAdmin && (
                                    <>
                                        <DropdownMenuItem onClick={onEditTags}>编辑标签</DropdownMenuItem>
                                        <DropdownMenuItem onClick={() => {
                                            setRenameValue(file.name);
                                            setIsRenaming(true);
                                        }}>重命名</DropdownMenuItem>
                                        <DropdownMenuItem onClick={onDelete} className="text-[#f53f3f] focus:text-[#f53f3f]">
                                            删除
                                        </DropdownMenuItem>
                                    </>
                                )}

                                {/* 失败重试逻辑 */}
                                {file.status === FileStatus.FAILED && onRetry && (
                                    <DropdownMenuItem onClick={onRetry}>重试</DropdownMenuItem>
                                )}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>
                </div>

                {/* 底部内容区域 */}
                <div className="p-1">
                    {/* 文件名和状态 */}
                    <div className="flex items-center text-sm font-medium min-w-0">
                        {getStatusText()}
                    </div>

                    {/* 底部信息 (标签、数量和时间) */}
                    <div className="flex items-center justify-between mt-1 min-w-0 gap-2">
                        <div className="flex items-center flex-1 min-w-0">
                            {isAdmin && isFolder && (
                                <div className="text-sm font-medium leading-none">
                                    <span className="text-[#00b42a]">7</span>
                                    <span className="text-[#86909c]">/11</span>
                                </div>
                            )}
                            {(!isFolder && file.tags && file.tags.length > 0) && (
                                <TagGroup tags={file.tags} />
                            )}
                        </div>
                        <span className="text-[#86909c] text-xs shrink-0">{formatTime(file.updatedAt)}</span>
                    </div>
                </div>
            </CardContent>
        </Card>
    );
}
