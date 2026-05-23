import type { Dispatch, SetStateAction } from "react";
import {
    Download,
    FolderPlus,
    FunnelIcon,
    Globe2,
    History,
    ListChecks,
    Search,
    SquarePen,
    Upload,
    X,
} from "lucide-react";
import { FileStatus, type KnowledgeFile } from "~/api/knowledge";
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import { STATUS_FILTER_OPTIONS } from "../constants";
import type { PortalFileTreeNode } from "../types";
import { FileTree } from "./FileTree";
import s from "../PortalKnowledgeWorkbench.module.css";

interface FilePaneProps {
    activeSpaceName?: string;
    hasActiveSpace: boolean;
    searchText: string;
    searchMode: boolean;
    searchLoading: boolean;
    treeLoading: boolean;
    treeRootLoadingMore: boolean;
    treeRootHasMore: boolean;
    visibleTreeNodes: PortalFileTreeNode[];
    searchResults: KnowledgeFile[];
    selectedFileId?: string;
    selectedFileIds: Set<string>;
    selectedFolderIds: Set<string>;
    selectedCount: number;
    selectedDownloadable: boolean;
    selectedDeletable: boolean;
    canBatchRetry: boolean;
    canUploadInPortal: boolean;
    canCreateFolderInPortal: boolean;
    statusFilter: FileStatus[];
    folderDraft: string;
    onFolderDraftChange: Dispatch<SetStateAction<string>>;
    onSearchTextChange: (value: string) => void;
    onSearch: () => void;
    onOpenUploadDialog: () => void;
    onShowUnavailable: () => void;
    onCreateFolder: () => void;
    onToggleStatusFilter: (status: FileStatus, checked: boolean) => void;
    onBatchDownload: () => void;
    onBatchRetry: () => void;
    onBatchDelete: () => void;
    onLoadMoreRoot: () => void;
    onConfirmCreateFolder: () => void;
    onCancelCreateFolder: () => void;
    onSelectFile: (file: KnowledgeFile) => void;
    onToggleFileSelection: (file: KnowledgeFile, checked: boolean) => void;
    canPublishFile: (file: KnowledgeFile) => boolean;
    onPublishFile: (file: KnowledgeFile) => void;
    onToggleFolder: (node: PortalFileTreeNode) => void;
    onLoadMoreChildren: (node: PortalFileTreeNode) => void;
}

export function FilePane({
    activeSpaceName,
    hasActiveSpace,
    searchText,
    searchMode,
    searchLoading,
    treeLoading,
    treeRootLoadingMore,
    treeRootHasMore,
    visibleTreeNodes,
    searchResults,
    selectedFileId,
    selectedFileIds,
    selectedFolderIds,
    selectedCount,
    selectedDownloadable,
    selectedDeletable,
    canBatchRetry,
    canUploadInPortal,
    canCreateFolderInPortal,
    statusFilter,
    folderDraft,
    onFolderDraftChange,
    onSearchTextChange,
    onSearch,
    onOpenUploadDialog,
    onShowUnavailable,
    onCreateFolder,
    onToggleStatusFilter,
    onBatchDownload,
    onBatchRetry,
    onBatchDelete,
    onLoadMoreRoot,
    onConfirmCreateFolder,
    onCancelCreateFolder,
    onSelectFile,
    onToggleFileSelection,
    canPublishFile,
    onPublishFile,
    onToggleFolder,
    onLoadMoreChildren,
}: FilePaneProps) {
    return (
        <aside className={s.filePane}>
            <div className={s.filePaneHeader}>
                <div className={s.sectionTitle} data-testid="active-space-title">{activeSpaceName || "我的技术文档"}</div>
                <div className={s.searchBox}>
                    <Search size={14} />
                    <input
                        className={s.searchInput}
                        value={searchText}
                        placeholder="搜索文件..."
                        onChange={(event) => onSearchTextChange(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === "Enter") onSearch();
                        }}
                    />
                </div>
                <div className={s.fileActions} data-testid="portal-file-actions">
                    <button
                        type="button"
                        className={s.folderAction}
                        onClick={onOpenUploadDialog}
                        disabled={!canUploadInPortal}
                        title={canUploadInPortal ? "上传" : "无上传权限"}
                        aria-label="上传"
                    >
                        <Upload size={14} />
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
                        disabled={!canCreateFolderInPortal}
                        title={canCreateFolderInPortal ? "新建文件夹" : "无创建权限"}
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
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <button
                                type="button"
                                className={`${s.folderAction} ${selectedCount > 0 ? s.folderActionActive : ""}`}
                                disabled={selectedCount === 0}
                                title={selectedCount > 0 ? `批量操作：已选择 ${selectedCount} 项` : "请先选择文件"}
                                aria-label="批量操作"
                            >
                                <ListChecks size={14} />
                            </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start" className={s.actionMenu}>
                            <DropdownMenuItem onClick={onBatchDownload} disabled={!selectedDownloadable}>
                                <Download size={14} />
                                <span>批量下载</span>
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={onBatchRetry} disabled={!canBatchRetry}>
                                <History size={14} />
                                <span>批量重试</span>
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={onBatchDelete} disabled={!selectedDeletable}>
                                <X size={14} />
                                <span>批量删除</span>
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                </div>
            </div>

            <div className={s.fileList}>
                {!hasActiveSpace ? (
                    <div className={s.stateBox}>
                        <div className={s.stateTitle}>暂无可用知识库</div>
                        <div>请先在 BiSheng 中创建或加入知识库。</div>
                    </div>
                ) : treeLoading && visibleTreeNodes.length === 0 ? (
                    <div className={s.stateBox}>正在加载文件...</div>
                ) : searchLoading ? (
                    <div className={s.stateBox}>正在搜索文件...</div>
                ) : searchMode ? (
                    searchResults.length === 0 ? (
                        <div className={s.stateBox}>暂无匹配文件</div>
                    ) : (
                        <>
                            <div className={s.searchResultTitle}>搜索结果</div>
                            <FileTree
                                files={searchResults}
                                selectedFileId={selectedFileId}
                                selectedFileIds={selectedFileIds}
                                selectedFolderIds={selectedFolderIds}
                                folderDraft={folderDraft}
                                onFolderDraftChange={onFolderDraftChange}
                                onConfirmCreateFolder={onConfirmCreateFolder}
                                onCancelCreateFolder={onCancelCreateFolder}
                                onSelectFile={onSelectFile}
                                onToggleFileSelection={onToggleFileSelection}
                                canPublishFile={canPublishFile}
                                onPublishFile={onPublishFile}
                                onToggleFolder={onToggleFolder}
                                onLoadMoreChildren={onLoadMoreChildren}
                            />
                        </>
                    )
                ) : visibleTreeNodes.length === 0 ? (
                    <div className={s.stateBox}>暂无文件</div>
                ) : (
                    <>
                        <FileTree
                            nodes={visibleTreeNodes}
                            selectedFileId={selectedFileId}
                            selectedFileIds={selectedFileIds}
                            selectedFolderIds={selectedFolderIds}
                            folderDraft={folderDraft}
                            onFolderDraftChange={onFolderDraftChange}
                            onConfirmCreateFolder={onConfirmCreateFolder}
                            onCancelCreateFolder={onCancelCreateFolder}
                            onSelectFile={onSelectFile}
                            onToggleFileSelection={onToggleFileSelection}
                            canPublishFile={canPublishFile}
                            onPublishFile={onPublishFile}
                            onToggleFolder={onToggleFolder}
                            onLoadMoreChildren={onLoadMoreChildren}
                        />
                        {treeRootHasMore ? (
                            <button
                                type="button"
                                className={s.treeLoadMore}
                                disabled={treeRootLoadingMore}
                                onClick={onLoadMoreRoot}
                            >
                                {treeRootLoadingMore ? "加载中..." : "加载更多"}
                            </button>
                        ) : null}
                    </>
                )}
            </div>
        </aside>
    );
}
