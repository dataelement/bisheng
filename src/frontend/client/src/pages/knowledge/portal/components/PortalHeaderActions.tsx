import type { FileStatus } from "~/api/knowledge";
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import { STATUS_FILTER_OPTIONS } from "../constants";
import { StatusFilterIcon } from "./SpaceIcons";
import s from "../PortalKnowledgeWorkbench.module.css";

interface PortalHeaderActionsProps {
    canUpload: boolean;
    canCreateFolder: boolean;
    statusFilter: FileStatus[];
    onOpenUploadDialog: () => void;
    onOpenWebLinkDialog: () => void;
    onShowUnavailable: () => void;
    onCreateFolder: () => void;
    onToggleStatusFilter: (status: FileStatus, checked: boolean) => void;
}

export function PortalHeaderActions({
    canUpload,
    canCreateFolder,
    statusFilter,
    onOpenUploadDialog,
    onOpenWebLinkDialog,
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
                {/* <Upload size={14} /> */}
                <img src={`${__APP_ENV__.BASE_URL}/assets/knowledge-portal/upload.svg`} alt="" className="size-[16px]" />
            </button>
            <button
                type="button"
                className={s.folderAction}
                onClick={onOpenWebLinkDialog}
                disabled={!canUpload}
                title={canUpload ? "网页链接" : "无上传权限"}
                aria-label="网页链接"
            >
                {/* <Globe2 size={14} /> */}
                <img src={`${__APP_ENV__.BASE_URL}/assets/knowledge-portal/web-link.svg`} alt="" className="size-[16px]" />
            </button>
            <button
                type="button"
                className={s.folderAction}
                onClick={onCreateFolder}
                disabled={!canCreateFolder}
                title={canCreateFolder ? "新建文件夹" : "无创建权限"}
                aria-label="新建文件夹"
            >
                
                <img src={`${__APP_ENV__.BASE_URL}/assets/knowledge-portal/new-folder.svg`} alt="" className="size-[16px]" />
                {/* <FolderPlus size={14} /> */}
            </button>
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <button
                        type="button"
                        className={`${s.folderAction} ${statusFilter.length ? s.folderActionActive : ""}`}
                        title={statusFilter.length ? `筛选：已选择 ${statusFilter.length} 项` : "筛选"}
                        aria-label="筛选"
                    >
                        <StatusFilterIcon className="size-[16px]" style={{ color: statusFilter.length ? "#2c76f4" : "#545A60" }} />
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
