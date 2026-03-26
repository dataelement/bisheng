import { Circle, MoreVertical, X } from "lucide-react";
import { useState } from "react";
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
import { useInlineRename } from "../hooks/useInlineRename";
import { formatTime } from "../knowledgeUtils";
import { useLocalize } from "~/hooks";

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
    onNavigateFolder?: (folderId?: string) => void;
    onPreview?: (fileId: string) => void;
    onValidateName?: (newName: string) => string | null;
    onCancelCreate?: () => void;
    disableClickNavigate?: boolean;
    hideSelectionCheckbox?: boolean;
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
    onNavigateFolder,
    onPreview,
    onValidateName,
    onCancelCreate,
    disableClickNavigate = false,
    hideSelectionCheckbox = false,
}: FileCardProps) {
    const localize = useLocalize();
  const isCreating = !!file.isCreating;
    const [hovered, setHovered] = useState(false);

    const isAdmin = userRole === SpaceRole.CREATOR || userRole === SpaceRole.ADMIN;
    const isFolder = file.type === FileType.FOLDER;

    const {
        isRenaming,
        renameValue,
        setRenameValue,
        inputRef,
        handleRenameSubmit,
        handleKeyDown,
        startRenaming,
    } = useInlineRename({
        fileName: file.name,
        isFolder,
        isCreating,
        onRename,
        onValidateName,
        onCancelCreate,
    });

    // formatTime is now imported from ../knowledgeUtils

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
            case FileStatus.UPLOADING:
                return (
                    <div className="flex items-center flex-1 min-w-0">
                        <Circle className="size-1.5 fill-[#165dff] text-[#165dff] shrink-0 mr-1.5" />
                        <span className="truncate text-[#1d2129]">{file.name}</span>
                        <span className="text-[#86909c] text-xs ml-1.5 shrink-0">{localize("com_knowledge.uploading")}</span>
                    </div>
                );
            case FileStatus.PROCESSING:
            case FileStatus.REBUILDING:
                return (
                    <div className="flex items-center flex-1 min-w-0">
                        <Circle className="size-1.5 fill-[#165dff] text-[#165dff] shrink-0 mr-1.5" />
                        <span className="truncate text-[#1d2129]">{file.name}</span>
                        <span className="text-[#86909c] text-xs ml-1.5 shrink-0">{localize("com_knowledge.parsing")}</span>
                    </div>
                );
            case FileStatus.WAITING:
                return (
                    <div className="flex items-center flex-1 min-w-0">
                        <Circle className="size-1.5 fill-[#165dff] text-[#165dff] shrink-0 mr-1.5" />
                        <span className="truncate text-[#1d2129]">{file.name}</span>
                        <span className="text-[#86909c] text-xs ml-1.5 shrink-0">{localize("com_knowledge.queueing")}</span>
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
        if (isCreating || isRenaming) return;
        // Folder click is treated as "enter folder"/"navigate directory"
        // (depending on the parent component's onNavigateFolder implementation).
        if (isFolder) {
            onNavigateFolder?.(file.id);
            return;
        }

        // In preview drawer mode we disable page navigation for file clicks.
        if (disableClickNavigate) return;
        // Call parent-provided preview handler
        onPreview?.(file.id);
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
                    {!hideSelectionCheckbox && (hovered || isSelected) && (
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

                            <DropdownMenuContent align="end" className="min-w-[120px]" onClick={(e) => e.stopPropagation()}>
                                {/* 下载功能现在移到了列表第一项 */}
                                <DropdownMenuItem onClick={(e) => {
                                    e.stopPropagation();
                                    onDownload();
                                }}>
                                    <span>{localize("com_knowledge.download")}</span>
                                </DropdownMenuItem>

                                {/* 如果是管理员，显示后续管理操作 */}
                                {isAdmin && (
                                    <>
                                        {!isFolder && <DropdownMenuItem onClick={(e) => { e.stopPropagation(); onEditTags(); }}>{localize("com_knowledge.edit_tags")}</DropdownMenuItem>}
                                        <DropdownMenuItem onClick={(e) => {
                                            e.stopPropagation();
                                            startRenaming();
                                        }}>{localize("com_knowledge.rename")}</DropdownMenuItem>
                                        <DropdownMenuItem onClick={(e) => { e.stopPropagation(); onDelete(); }} className="text-[#f53f3f] focus:text-[#f53f3f]">
                                            {localize("com_knowledge.delete")}</DropdownMenuItem>
                                    </>
                                )}

                                {/* Retry for failed files or folders with partial failures */}
                                {onRetry && (
                                    file.status === FileStatus.FAILED ||
                                    (isFolder && file.successFileNum !== undefined && file.fileNum !== undefined && file.successFileNum < file.fileNum)
                                ) && (
                                    <DropdownMenuItem onClick={(e) => { e.stopPropagation(); onRetry(); }}>{localize("com_knowledge.retry")}</DropdownMenuItem>
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
                            {isAdmin && isFolder && file.fileNum != null && (
                                <div className="text-sm font-medium leading-none">
                                    <span className="text-[#86909c]">{file.successFileNum ?? 0}</span>
                                    <span className="text-[#86909c]">/{file.fileNum}</span>
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
