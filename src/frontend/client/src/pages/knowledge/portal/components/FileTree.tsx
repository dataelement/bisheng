import type { Dispatch, ReactNode, SetStateAction } from "react";
import { ChevronDown, ChevronRight, MoreHorizontal, Send, Shield } from "lucide-react";
import { FileStatus, type KnowledgeFile } from "~/api/knowledge";
import LegacyFileIcon from "~/components/ui/icon/File";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import type { LegacyFileIconType } from "../constants";
import type { PortalFileTreeNode } from "../types";
import {
    folderCountText,
    getPortalFileIconType,
    isFolder,
    statusText,
} from "../utils";
import s from "../PortalKnowledgeWorkbench.module.css";

interface FileTreeProps {
    nodes?: PortalFileTreeNode[];
    files?: KnowledgeFile[];
    selectedFileId?: string;
    selectedFileIds: Set<string>;
    selectedFolderIds: Set<string>;
    folderDraft: string;
    onFolderDraftChange: Dispatch<SetStateAction<string>>;
    onConfirmCreateFolder: () => void;
    onCancelCreateFolder: () => void;
    onSelectFile: (file: KnowledgeFile) => void;
    onToggleFileSelection: (file: KnowledgeFile, checked: boolean) => void;
    permissionEntryIds: Set<string>;
    onOpenPermission: (file: KnowledgeFile) => void;
    canShowPublishFile: (file: KnowledgeFile) => boolean;
    onPublishFile: (file: KnowledgeFile) => void;
    onToggleFolder: (node: PortalFileTreeNode) => void;
    onLoadMoreChildren: (node: PortalFileTreeNode) => void;
}

function getStatusClassName(file: KnowledgeFile) {
    switch (file.status) {
        case FileStatus.SUCCESS:
            return `${s.fileStatusBadge} ${s.fileStatusSuccess}`;
        case FileStatus.FAILED:
        case FileStatus.TIMEOUT:
        case FileStatus.VIOLATION:
            return `${s.fileStatusBadge} ${s.fileStatusDanger}`;
        case FileStatus.UPLOADING:
        case FileStatus.PROCESSING:
        case FileStatus.WAITING:
        case FileStatus.REBUILDING:
            return `${s.fileStatusBadge} ${s.fileStatusInfo}`;
        default:
            return s.fileStatusBadge;
    }
}

export function FileTree({
    nodes,
    files,
    selectedFileId,
    selectedFileIds,
    selectedFolderIds,
    folderDraft,
    onFolderDraftChange,
    onConfirmCreateFolder,
    onCancelCreateFolder,
    onSelectFile,
    onToggleFileSelection,
    permissionEntryIds,
    onOpenPermission,
    canShowPublishFile,
    onPublishFile,
    onToggleFolder,
    onLoadMoreChildren,
}: FileTreeProps) {
    const renderFileRow = (file: KnowledgeFile, depth: number, node?: PortalFileTreeNode) => {
        const selected = isFolder(file) ? selectedFolderIds.has(file.id) : selectedFileIds.has(file.id);
        const active = selectedFileId === file.id;
        const label = statusText(file);
        const countText = isFolder(file) ? folderCountText(file) : "";
        const publishDisabled = file.status !== FileStatus.SUCCESS;
        const showPublishAction = !isFolder(file) && canShowPublishFile(file);
        const showPermissionAction = permissionEntryIds.has(file.id);
        const showMoreMenu = showPublishAction || showPermissionAction;
        return (
            <div
                key={file.id}
                data-testid={`file-tree-row-${file.id}`}
                className={`${s.treeRow} ${active ? s.treeRowActive : ""}`}
                style={{ paddingLeft: `${8 + depth * 18}px` }}
                title={file.name}
            >
                {isFolder(file) && node ? (
                    <button
                        type="button"
                        className={s.treeExpandButton}
                        aria-label={`${node.expanded ? "收起" : "展开"}${file.name}`}
                        onClick={() => onToggleFolder(node)}
                    >
                        {node.expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    </button>
                ) : (
                    <span className={s.treeExpandPlaceholder} />
                )}
                <input
                    type="checkbox"
                    className={s.treeCheckbox}
                    aria-label={`选择${file.name}`}
                    checked={selected}
                    onChange={(event) => onToggleFileSelection(file, event.currentTarget.checked)}
                    onClick={(event) => event.stopPropagation()}
                />
                <button
                    type="button"
                    className={s.treeItemButton}
                    aria-label={`打开${file.name}`}
                    onClick={() => {
                        if (isFolder(file) && node) {
                            onToggleFolder(node);
                            return;
                        }
                        onSelectFile(file);
                    }}
                >
                    <LegacyFileIcon
                        type={getPortalFileIconType(file) as LegacyFileIconType}
                        className={s.treeFileTypeIcon}
                    />
                    {file.isCreating ? (
                        <input
                            autoFocus
                            className={s.createFolderInput}
                            value={folderDraft}
                            onChange={(event) => onFolderDraftChange(event.target.value)}
                            onClick={(event) => event.stopPropagation()}
                            onBlur={onConfirmCreateFolder}
                            onKeyDown={(event) => {
                                if (event.key === "Enter") onConfirmCreateFolder();
                                if (event.key === "Escape") onCancelCreateFolder();
                            }}
                        />
                    ) : (
                        <span className={s.fileName}>{file.name}</span>
                    )}
                </button>
                {countText ? <span className={s.folderCount}>{countText}</span> : null}
                {!isFolder(file) && label ? <span className={getStatusClassName(file)}>{label}</span> : null}
                {showMoreMenu ? (
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <button
                                type="button"
                                className={s.treeMoreButton}
                                aria-label={`更多${file.name}操作`}
                                onClick={(event) => event.stopPropagation()}
                            >
                                <MoreHorizontal size={14} />
                            </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className={s.actionMenu}>
                            {showPublishAction ? (
                                <DropdownMenuItem
                                    disabled={publishDisabled}
                                    onClick={(event) => {
                                        if (publishDisabled) return;
                                        event?.stopPropagation?.();
                                        onPublishFile(file);
                                    }}
                                >
                                    <Send size={14} />
                                    <span>发布</span>
                                </DropdownMenuItem>
                            ) : null}
                            {showPermissionAction ? (
                                <DropdownMenuItem
                                    onClick={(event) => {
                                        event?.stopPropagation?.();
                                        onOpenPermission(file);
                                    }}
                                >
                                    <Shield size={14} />
                                    <span>权限管理</span>
                                </DropdownMenuItem>
                            ) : null}
                        </DropdownMenuContent>
                    </DropdownMenu>
                ) : null}
            </div>
        );
    };

    const renderTreeNode = (node: PortalFileTreeNode, depth = 0): ReactNode => {
        const hasMore = node.expanded && node.loaded && node.children.length < node.total;
        return (
            <div key={node.file.id}>
                {renderFileRow(node.file, depth, node)}
                {node.expanded && node.loading ? (
                    <div className={s.treeLoadingRow} style={{ paddingLeft: `${34 + (depth + 1) * 18}px` }}>
                        加载中...
                    </div>
                ) : null}
                {node.expanded && node.children.map((child) => renderTreeNode(child, depth + 1))}
                {hasMore ? (
                    <button
                        type="button"
                        className={s.treeLoadMore}
                        style={{ marginLeft: `${34 + (depth + 1) * 18}px` }}
                        onClick={() => onLoadMoreChildren(node)}
                    >
                        加载更多
                    </button>
                ) : null}
            </div>
        );
    };

    if (files) {
        return <>{files.map((file) => renderFileRow(file, 0))}</>;
    }

    return <>{nodes?.map((node) => renderTreeNode(node))}</>;
}
