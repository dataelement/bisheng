import { FolderPlus, FunnelIcon, Globe2, History, SquarePen, Upload } from "lucide-react";
import type { FileStatus } from "~/api/knowledge";
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import { STATUS_FILTER_OPTIONS } from "../constants";
import s from "../PortalKnowledgeWorkbench.module.css";

interface PortalHeaderActionsProps {
    canUpload: boolean;
    canCreateFolder: boolean;
    statusFilter: FileStatus[];
    onOpenUploadDialog: () => void;
    onOpenUploadedFiles: () => void;
    onShowUnavailable: () => void;
    onCreateFolder: () => void;
    onToggleStatusFilter: (status: FileStatus, checked: boolean) => void;
}

export function PortalHeaderActions({
    canUpload,
    canCreateFolder,
    statusFilter,
    onOpenUploadDialog,
    onOpenUploadedFiles,
    onShowUnavailable,
    onCreateFolder,
    onToggleStatusFilter,
}: PortalHeaderActionsProps) {
    return (
        <div className={`${s.fileActions} ${s.portalHeaderFileActions}`} data-testid="portal-file-actions">
            <button
                type="button"
                className={s.folderAction}
                onClick={onOpenUploadDialog}
                disabled={!canUpload}
                title={canUpload ? "上传" : "无上传权限"}
                aria-label="上传"
            >
                <Upload size={14} />
            </button>
            <button
                type="button"
                className={s.folderAction}
                onClick={onOpenUploadedFiles}
                title="上传记录"
                aria-label="上传记录"
            >
                <History size={14} />
            </button>
            <button
                type="button"
                className={s.folderAction}
                onClick={onShowUnavailable}
                title="网页链接"
                aria-label="网页链接"
            >
                <Globe2 size={14} />
            </button>
            <button
                type="button"
                className={s.folderAction}
                onClick={onShowUnavailable}
                title="在线创建文档"
                aria-label="在线创建文档"
            >
                <SquarePen size={14} />
            </button>
            <button
                type="button"
                className={s.folderAction}
                onClick={onCreateFolder}
                disabled={!canCreateFolder}
                title={canCreateFolder ? "新建文件夹" : "无创建权限"}
                aria-label="新建文件夹"
            >
                <FolderPlus size={14} />
            </button>
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <button
                        type="button"
                        className={`${s.folderAction} ${statusFilter.length ? s.folderActionActive : ""}`}
                        title={statusFilter.length ? `筛选：已选择 ${statusFilter.length} 项` : "筛选"}
                        aria-label="筛选"
                    >
                        <FunnelIcon size={14} />
                    </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className={s.actionMenu}>
                    <div className={s.actionMenuTitle}>状态</div>
                    {STATUS_FILTER_OPTIONS.map((option) => (
                        <DropdownMenuCheckboxItem
                            key={option.status}
                            checked={statusFilter.includes(option.status)}
                            onCheckedChange={(checked) => onToggleStatusFilter(option.status, Boolean(checked))}
                            onSelect={(event) => event.preventDefault()}
                        >
                            {option.label}
                        </DropdownMenuCheckboxItem>
                    ))}
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    );
}
