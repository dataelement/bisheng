import {
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import {
    Download,
    Edit,
    FileImageIcon,
    FileUserIcon,
    FolderIcon,
    MoreVertical,
    PencilLineIcon,
    RefreshCw,
    SortDescIcon,
    Tag, Trash2
} from "lucide-react";
import {
    Checkbox,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger
} from "~/components";
import { cn } from "~/utils";
import FileIcon from "./FileIcon";
import TagGroup from "./TagGroup";
import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import { SortType, SortDirection, FileStatus, FileType, KnowledgeFile } from "~/api/knowledge";
import { formatBytes } from "~/utils";
import { useInlineRename } from "../hooks/useInlineRename";
import { useLocalize } from "~/hooks";

// ============================================================
// 列定义：key、最小宽度、初始宽度
// ============================================================
const COLUMN_CONFIG = {
    checkbox: { minWidth: 48, initialWidth: 48 },
    name: { minWidth: 140, initialWidth: 280 },
    fileType: { minWidth: 80, initialWidth: 100 },
    size: { minWidth: 80, initialWidth: 120 },
    tags: { minWidth: 140, initialWidth: 200 },
    updateTime: { minWidth: 140, initialWidth: 180 },
    status: { minWidth: 80, initialWidth: 120 },
    actions: { minWidth: 80, initialWidth: 80 },
} as const;

type ColumnKey = keyof typeof COLUMN_CONFIG;

// 不参与拖拽调整的列
const NON_RESIZABLE_COLUMNS: ColumnKey[] = ["checkbox", "actions"];
// 左侧固定列
const STICKY_COLUMNS: ColumnKey[] = ["checkbox", "name"];

// ============================================================
// Hook: useResizableColumns — 列宽状态 + 拖拽逻辑
// ============================================================
function useResizableColumns() {
    const [columnWidths, setColumnWidths] = useState<Record<ColumnKey, number>>(() => {
        const widths = {} as Record<ColumnKey, number>;
        for (const [key, config] of Object.entries(COLUMN_CONFIG)) {
            widths[key as ColumnKey] = config.initialWidth;
        }
        return widths;
    });

    const dragging = useRef<{ key: ColumnKey; startX: number; startWidth: number } | null>(null);

    const onResizeStart = useCallback((columnKey: ColumnKey, e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();

        dragging.current = {
            key: columnKey,
            startX: e.clientX,
            startWidth: columnWidths[columnKey],
        };

        // 拖拽时全局禁止选中、设置 cursor
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";

        const onMouseMove = (ev: MouseEvent) => {
            if (!dragging.current) return;
            const delta = ev.clientX - dragging.current.startX;
            const minW = COLUMN_CONFIG[dragging.current.key].minWidth;
            const newWidth = Math.max(minW, dragging.current.startWidth + delta);
            setColumnWidths(prev => ({ ...prev, [dragging.current!.key]: newWidth }));
        };

        const onMouseUp = () => {
            dragging.current = null;
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
            document.removeEventListener("mousemove", onMouseMove);
            document.removeEventListener("mouseup", onMouseUp);
        };

        document.addEventListener("mousemove", onMouseMove);
        document.addEventListener("mouseup", onMouseUp);
    }, [columnWidths]);

    const totalWidth = useMemo(
        () => Object.values(columnWidths).reduce((sum, w) => sum + w, 0),
        [columnWidths]
    );

    return { columnWidths, onResizeStart, totalWidth };
}

// ============================================================
// Hook: useScrollShadow — 监听滚动容器，控制左右阴影
// ============================================================
function useScrollShadow(scrollRef: React.RefObject<HTMLDivElement | null>) {
    const [showLeftShadow, setShowLeftShadow] = useState(false);
    const [showRightShadow, setShowRightShadow] = useState(false);

    const update = useCallback(() => {
        const el = scrollRef.current;
        if (!el) return;
        setShowLeftShadow(el.scrollLeft > 0);
        setShowRightShadow(el.scrollLeft + el.clientWidth < el.scrollWidth - 1);
    }, [scrollRef]);

    useEffect(() => {
        const el = scrollRef.current;
        if (!el) return;

        update();
        el.addEventListener("scroll", update, { passive: true });

        // 监听容器尺寸变化
        const ro = new ResizeObserver(update);
        ro.observe(el);

        return () => {
            el.removeEventListener("scroll", update);
            ro.disconnect();
        };
    }, [scrollRef, update]);

    return { showLeftShadow, showRightShadow };
}

// ============================================================
// 辅助组件：状态标签渲染
// ============================================================
const StatusBadge = ({ status }: { status: FileStatus }) => {
    const localize = useLocalize();
    const config: Record<string, { label: string; color: string; bg: string; dot: string }> = {
        [FileStatus.SUCCESS]: { label: localize("com_knowledge.success"), color: "text-[#00b42a]", bg: "bg-[#e8ffea]", dot: "bg-[#00b42a]" },
        [FileStatus.PROCESSING]: { label: localize("com_knowledge.parsing_status"), color: "text-[#165dff]", bg: "bg-[#e8f3ff]", dot: "bg-[#165dff]" },
        [FileStatus.WAITING]: { label: localize("com_knowledge.queueing_status"), color: "text-[#165dff]", bg: "bg-[#e8f3ff]", dot: "bg-[#165dff]" },
        [FileStatus.REBUILDING]: { label: localize("com_knowledge.rebuilding_status"), color: "text-[#165dff]", bg: "bg-[#e8f3ff]", dot: "bg-[#165dff]" },
        [FileStatus.UPLOADING]: { label: localize("com_knowledge.uploading_status"), color: "text-[#165dff]", bg: "bg-[#e8f3ff]", dot: "bg-[#165dff]" },
        [FileStatus.FAILED]: { label: localize("com_knowledge.fail"), color: "text-[#f53f3f]", bg: "bg-[#fff2f0]", dot: "bg-[#f53f3f]" },
        [FileStatus.TIMEOUT]: { label: localize("com_knowledge.timeout"), color: "text-[#f53f3f]", bg: "bg-[#fff2f0]", dot: "bg-[#f53f3f]" },
    };
    const item = config[status] || config[FileStatus.WAITING];
    return (
        <div className={cn("inline-flex items-center gap-1.5 px-2 py-0.5 rounded-sm text-xs font-medium", item.bg, item.color)}>
            <span className={cn("size-1.5 rounded-full", item.dot)} />
            {item.label}
        </div>
    );
};

// ============================================================
// 拖拽手柄
// ============================================================
function ResizeHandle({ columnKey, onResizeStart }: { columnKey: ColumnKey; onResizeStart: (key: ColumnKey, e: React.MouseEvent) => void }) {
    return (
        <div
            className="absolute right-0 top-0 bottom-0 w-[6px] cursor-col-resize z-10 group/handle flex items-center justify-center"
            onMouseDown={(e) => onResizeStart(columnKey, e)}
        >
            {/* 悬停时显示蓝色高亮线 */}
            <div className="w-[2px] h-full bg-transparent group-hover/handle:bg-[#165dff] transition-colors" />
        </div>
    );
}

// ============================================================
// 左侧固定列阴影 — 绝对定位渐变，不受相邻 td 遮挡
// ============================================================
function StickyColumnShadow({ show }: { show: boolean }) {
    if (!show) return null;
    return (
        <div
            aria-hidden
            className="pointer-events-none absolute top-0 right-[-12px] h-full w-[12px] z-10"
            style={{
                background: "linear-gradient(to right, rgba(0,0,0,0.08), transparent)",
            }}
        />
    );
}

// ============================================================
const SortableHeader = ({
    children,
    sortKey,
    currentSort,
    onSort,
    width,
    columnKey,
    onResizeStart,
    stickyLeft,
    showShadow,
}: {
    children: React.ReactNode;
    sortKey: string;
    currentSort: { key: string; direction: string };
    onSort: (key: string) => void;
    width: number;
    columnKey: ColumnKey;
    onResizeStart: (key: ColumnKey, e: React.MouseEvent) => void;
    stickyLeft?: number;
    showShadow?: boolean;
}) => {
    const isActive = currentSort?.key === sortKey;
    const direction = isActive ? currentSort.direction : "asc";
    const isSticky = stickyLeft !== undefined;
    const isResizable = !NON_RESIZABLE_COLUMNS.includes(columnKey);

    return (
        <TableHead
            className={cn(
                "group relative p-0 pr-3 my-2 cursor-pointer select-none overflow-visible",
                "hover:bg-[#f2f3f5] transition-colors",
                isSticky && "sticky z-20 bg-[#f7f8fa]"
            )}
            style={{
                width,
                minWidth: width,
                maxWidth: width,
                ...(isSticky ? { left: stickyLeft } : {}),
            }}
            onClick={() => onSort(sortKey)}
        >
            <div className="flex items-center gap-1.5 border-l pl-3">
                <span className={cn("text-sm font-normal", isActive ? "text-[#1d2129]" : "text-[#4e5969]")}>
                    {children}
                </span>
                <SortDescIcon className={`size-4 group-hover:opacity-100 opacity-0 transition-opacity ${isActive ? "opacity-100 text-primary" : ""} ${direction === "asc" ? "rotate-180" : ""}`} />
            </div>
            {isResizable && <ResizeHandle columnKey={columnKey} onResizeStart={onResizeStart} />}
            {/* 固定列右侧阴影 */}
            <StickyColumnShadow show={!!showShadow} />
        </TableHead>
    );
};

// ============================================================
// 表头组件
// ============================================================
function FileTableHeader({
    columnWidths,
    onResizeStart,
    showLeftShadow,
    sortBy,
    sortDirection,
    onSort,
    isAdmin,
}: {
    columnWidths: Record<ColumnKey, number>;
    onResizeStart: (key: ColumnKey, e: React.MouseEvent) => void;
    showLeftShadow: boolean;
    sortBy: SortType;
    sortDirection: SortDirection;
    onSort: (sortBy: SortType) => void;
    isAdmin: boolean;
}) {
    const localize = useLocalize();
    const currentSort = { key: sortBy, direction: sortDirection };

    const handleSort = (key: string) => {
        onSort(key as SortType);
    };

    return (
        <TableHeader className="bg-[#f7f8fa] border-b border-[#e5e6eb]">
            <TableRow className="hover:bg-transparent border-none">
                {/* 复选框列 — 左侧固定 */}
                <TableHead
                    className="text-center p-0 sticky left-0 z-20 bg-[#f7f8fa]"
                    style={{ width: columnWidths.checkbox, minWidth: columnWidths.checkbox, maxWidth: columnWidths.checkbox }}
                >
                    <Checkbox className="border-gray-400 checked:border-primary" />
                </TableHead>

                {/* 文件名 — 左侧固定 */}
                <SortableHeader
                    sortKey={SortType.NAME}
                    currentSort={currentSort}
                    onSort={handleSort}
                    width={columnWidths.name}
                    columnKey="name"
                    onResizeStart={onResizeStart}
                    stickyLeft={columnWidths.checkbox}
                    showShadow={showLeftShadow}
                >
                    {localize("com_knowledge.file_name")}</SortableHeader>

                {/* 文件类型 */}
                <SortableHeader
                    sortKey={SortType.TYPE}
                    currentSort={currentSort}
                    onSort={handleSort}
                    width={columnWidths.fileType}
                    columnKey="fileType"
                    onResizeStart={onResizeStart}
                >
                    {localize("com_knowledge.type")}</SortableHeader>

                {/* 文件大小 */}
                <SortableHeader
                    sortKey={SortType.SIZE}
                    currentSort={currentSort}
                    onSort={handleSort}
                    width={columnWidths.size}
                    columnKey="size"
                    onResizeStart={onResizeStart}
                >
                    {localize("com_knowledge.file_size")}</SortableHeader>

                {/* 标签 — 不排序 */}
                <TableHead
                    className="text-[#4e5969] font-normal p-0 pr-3 relative"
                    style={{ width: columnWidths.tags, minWidth: columnWidths.tags, maxWidth: columnWidths.tags }}
                >
                    <div className="flex items-center gap-1.5 border-l pl-3">
                        {localize("com_knowledge.tag")}</div>
                    <ResizeHandle columnKey="tags" onResizeStart={onResizeStart} />
                </TableHead>

                {/* 更新时间 */}
                <SortableHeader
                    sortKey={SortType.UPDATE_TIME}
                    currentSort={currentSort}
                    onSort={handleSort}
                    width={columnWidths.updateTime}
                    columnKey="updateTime"
                    onResizeStart={onResizeStart}
                >
                    {localize("com_knowledge.update_time")}</SortableHeader>

                {/* 状态 — 不排序, only visible to admins */}
                {isAdmin && (
                    <TableHead
                        className="text-[#4e5969] font-normal p-0 pr-3 relative"
                        style={{ width: columnWidths.status, minWidth: columnWidths.status, maxWidth: columnWidths.status }}
                    >
                        <div className="flex items-center gap-1.5 border-l pl-3">
                            {localize("com_knowledge.status")}</div>
                        <ResizeHandle columnKey="status" onResizeStart={onResizeStart} />
                    </TableHead>
                )}

                {/* 操作 */}
                <TableHead
                    className="text-[#4e5969] font-normal p-0"
                    style={{ width: columnWidths.actions, minWidth: columnWidths.actions, maxWidth: columnWidths.actions }}
                >
                    <div className="flex items-center gap-1.5 border-l pl-3">
                        {localize("com_knowledge.operation")}</div>
                </TableHead>
            </TableRow>
        </TableHeader>
    );
}

// ============================================================
// 主表格组件
// ============================================================

interface FileTableProps {
    files: KnowledgeFile[];
    selectedFiles: Set<string>;
    handleSelectAll: () => void;
    handleSelectFile: (id: string, selected: boolean) => void;
    isAdmin: boolean;
    onDownload: (id: string) => void;
    onEditTags: (id: string) => void;
    onRename: (id: string, newName: string) => void;
    onDelete: (id: string) => void;
    onRetry: (id: string) => void;
    onNavigateFolder: (id: string) => void;
    onPreview?: (id: string) => void;
    onValidateName: (name: string, isFolder: boolean, fileId: string, isCreating: boolean) => string | null;
    onCancelCreate?: () => void;
    sortBy: SortType;
    sortDirection: SortDirection;
    onSort: (sortBy: SortType) => void;
}

export function FileTable({ files, selectedFiles, handleSelectAll, handleSelectFile, isAdmin, onDownload, onEditTags, onRename, onDelete, onRetry, onNavigateFolder, onPreview, onValidateName, onCancelCreate, sortBy, sortDirection, onSort }: FileTableProps) {
    const { columnWidths, onResizeStart, totalWidth } = useResizableColumns();
    const scrollRef = useRef<HTMLDivElement>(null);
    const { showLeftShadow, showRightShadow } = useScrollShadow(scrollRef);

    return (
        <div className="border-t border-[#e5e6eb] relative overflow-hidden">
            {/* 滚动容器 */}
            <div
                ref={scrollRef}
                className="overflow-x-auto overflow-y-visible"
            >
                <table
                    className="w-full caption-bottom text-sm border-collapse"
                    style={{ tableLayout: "fixed", width: totalWidth, minWidth: "100%" }}
                >
                    <FileTableHeader
                        columnWidths={columnWidths}
                        onResizeStart={onResizeStart}
                        showLeftShadow={showLeftShadow}
                        sortBy={sortBy}
                        sortDirection={sortDirection}
                        onSort={onSort}
                        isAdmin={isAdmin}
                    />
                    <TableBody>
                        {files.map((file) => (
                            <FileRow
                                key={file.id}
                                file={file}
                                isAdmin={isAdmin}
                                isSelected={selectedFiles.has(file.id)}
                                onSelect={(val) => handleSelectFile(file.id, val)}
                                onDownload={() => onDownload(file.id)}
                                onEditTags={() => onEditTags(file.id)}
                                onRename={(newName) => onRename(file.id, newName)}
                                onDelete={() => onDelete(file.id)}
                                onRetry={() => onRetry?.(file.id)}
                                onNavigateFolder={() => onNavigateFolder?.(file.id)}
                                onPreview={() => onPreview?.(file.id)}
                                onValidateName={(newName) => onValidateName?.(newName, file.type === FileType.FOLDER, file.id, !!file.isCreating)}
                                onCancelCreate={onCancelCreate}
                                columnWidths={columnWidths}
                                showLeftShadow={showLeftShadow}
                            />
                        ))}
                    </TableBody>
                </table>
            </div>

            {/* 右侧溢出阴影 */}
            {showRightShadow && (
                <div
                    className="absolute top-0 right-0 bottom-0 w-4 pointer-events-none z-30"
                    style={{
                        background: "linear-gradient(to left, rgba(0,0,0,0.06), transparent)",
                    }}
                />
            )}
        </div>
    );
}

// ============================================================
// 行组件
// ============================================================
function FileRow({
    file,
    isSelected,
    onSelect,
    isAdmin,
    onDownload,
    onEditTags,
    onRename,
    onDelete,
    onRetry,
    onNavigateFolder,
    onPreview,
    onValidateName,
    onCancelCreate,
    columnWidths,
    showLeftShadow,
}: {
    file: KnowledgeFile;
    isSelected: boolean;
    onSelect: (val: boolean) => void;
    isAdmin: boolean;
    onDownload: () => void;
    onEditTags: () => void;
    onRename: (newName: string) => void;
    onDelete: () => void;
    onRetry: () => void;
    onNavigateFolder?: () => void;
    onPreview?: () => void;
    onValidateName?: (newName: string) => string | null;
    onCancelCreate?: () => void;
    columnWidths: Record<ColumnKey, number>;
    showLeftShadow: boolean;
}) {
    const localize = useLocalize();
    const isFolder = file.type === FileType.FOLDER;
    const isCreating = !!file.isCreating;
    const rowBg = isSelected ? "bg-primary/10" : "bg-white";

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

    return (
        <TableRow className={cn(
            "group border-b-[#e5e6eb] transition-colors",
            isSelected ? "bg-primary/10 hover:bg-primary/10" : "hover:bg-[#f7f8fa]"
        )}>
            {/* 复选框 — 左侧固定 */}
            <TableCell
                className={cn("text-center py-3 px-0 sticky left-0 z-10", rowBg)}
                style={{ width: columnWidths.checkbox, minWidth: columnWidths.checkbox, maxWidth: columnWidths.checkbox }}
            >
                <div className="flex items-center justify-center">
                    <Checkbox
                        checked={isSelected}
                        onCheckedChange={onSelect}
                        className={`size-4 border-gray-400 ${isSelected ? "border-primary" : ""}`}
                    />
                </div>
            </TableCell>

            {/* 文件名 — 左侧固定 */}
            <TableCell
                className={cn("py-3 sticky z-10 overflow-visible", rowBg)}
                style={{
                    width: columnWidths.name,
                    minWidth: columnWidths.name,
                    maxWidth: columnWidths.name,
                    left: columnWidths.checkbox,
                }}
            >
                <div className="flex items-center gap-2 min-w-0 text-gray-300 ">
                    <div className="bg-white rounded-sm size-5 flex items-center justify-center flex-shrink-0">
                        {isFolder
                            ? <FolderIcon className="size-4" />
                            : (file.thumbnail ? <FileImageIcon className="size-4" /> : <FileUserIcon className="size-4" />)
                        }
                    </div>
                    {isRenaming ? (
                        <input
                            ref={inputRef}
                            type="text"
                            value={renameValue}
                            onChange={(e) => setRenameValue(e.target.value)}
                            onBlur={handleRenameSubmit}
                            onKeyDown={handleKeyDown}
                            onClick={(e) => e.stopPropagation()}
                            className="flex-1 h-7 px-2 text-sm border border-[#165dff] rounded outline-none shadow-[0_0_0_2px_rgba(22,93,255,0.2)] bg-white font-normal text-[#1d2129]"
                        />
                    ) : (
                        <span
                            className="text-sm text-[#1d2129] truncate cursor-pointer hover:text-[#165dff] flex-1"
                            onClick={(e) => {
                                e.stopPropagation();
                                if (isFolder) {
                                    onNavigateFolder?.();
                                    return;
                                }
                                onPreview?.();
                            }}
                        >
                            {file.name}
                        </span>
                    )}
                </div>
                {/* 固定列右侧阴影 */}
                <StickyColumnShadow show={showLeftShadow} />
            </TableCell>

            {/* 类型 */}
            <TableCell
                className="text-[#86909c] text-sm py-3"
                style={{ width: columnWidths.fileType, minWidth: columnWidths.fileType, maxWidth: columnWidths.fileType }}
            >
                <span className="truncate block">
                    {isFolder ? localize("com_knowledge.folder") : (file.name.split('.').pop()?.toLowerCase() || "--")}
                </span>
            </TableCell>

            {/* 大小 */}
            <TableCell
                className="text-[#86909c] text-sm py-3"
                style={{ width: columnWidths.size, minWidth: columnWidths.size, maxWidth: columnWidths.size }}
            >
                <span className="truncate block">
                    {isFolder ? "--" : (file.size ? formatBytes(file.size, 2, true) : "--")}
                </span>
            </TableCell>

            {/* 标签 */}
            <TableCell
                className="py-3 group/tags"
                style={{ width: columnWidths.tags, minWidth: columnWidths.tags, maxWidth: columnWidths.tags }}
            >
                <div className="flex items-center gap-1.5 overflow-hidden w-full h-full">
                    {!isFolder && (
                        <TagGroup
                            tags={file.tags}
                            actionButton={
                                isAdmin ? (
                                    <div
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            onEditTags();
                                        }}
                                        className="hidden group-hover/tags:flex items-center justify-center text-[#165dff] hover:text-[#165dff]/80 transition-colors cursor-pointer"
                                    >
                                        <PencilLineIcon className="size-3.5" />
                                    </div>
                                ) : undefined
                            }
                        />
                    )}
                </div>
            </TableCell>

            {/* 时间 */}
            <TableCell
                className="text-[#86909c] text-sm whitespace-nowrap py-3"
                style={{ width: columnWidths.updateTime, minWidth: columnWidths.updateTime, maxWidth: columnWidths.updateTime }}
            >
                <span className="truncate block">{file.updatedAt}</span>
            </TableCell>

            {/* 状态 — only visible to admins */}
            {isAdmin && (
                <TableCell
                    className="py-3"
                    style={{ width: columnWidths.status, minWidth: columnWidths.status, maxWidth: columnWidths.status }}
                >
                    {isFolder
                        ? (
                            <span className={`text-sm ${file.successFileNum !== undefined && file.fileNum !== undefined && file.successFileNum < file.fileNum
                                    ? 'text-[#f53f3f]'
                                    : 'text-[#86909c]'
                                }`}>
                                {file.successFileNum ?? 0}/{file.fileNum ?? 0}
                            </span>
                        )
                        : <StatusBadge status={file.status} />
                    }
                </TableCell>
            )}

            {/* 操作 */}
            <TableCell
                className="text-right pr-4 py-3"
                style={{ width: columnWidths.actions, minWidth: columnWidths.actions, maxWidth: columnWidths.actions }}
            >
                <div className="invisible group-hover:visible flex justify-end">
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <button className="size-7 flex items-center justify-center hover:bg-[#e5e6eb] rounded-md text-[#4e5969] transition-colors">
                                <MoreVertical className="size-4" />
                            </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-32">
                            <DropdownMenuItem onClick={onDownload}>
                                <Download className="size-4 mr-2" />{localize("com_knowledge.download")}</DropdownMenuItem>
                            {isAdmin && (
                                <>
                                    {!isFolder && (
                                        <DropdownMenuItem onClick={onEditTags}>
                                            <Tag className="size-4 mr-2" />{localize("com_knowledge.edit_tags")}</DropdownMenuItem>
                                    )}
                                    <DropdownMenuItem onClick={() => startRenaming()}>
                                        <Edit className="size-4 mr-2" />{localize("com_knowledge.rename")}</DropdownMenuItem>
                                    {/* Retry for failed files */}
                                    {!isFolder && file.status === FileStatus.FAILED && (
                                        <DropdownMenuItem onClick={onRetry}>
                                            <RefreshCw className="size-4 mr-2" />{localize("com_knowledge.retry")}</DropdownMenuItem>
                                    )}
                                    {/* Retry for folders with partial failures */}
                                    {isFolder && file.successFileNum !== undefined && file.fileNum !== undefined && file.successFileNum < file.fileNum && (
                                        <DropdownMenuItem onClick={onRetry}>
                                            <RefreshCw className="size-4 mr-2" />{localize("com_knowledge.retry")}</DropdownMenuItem>
                                    )}
                                    <DropdownMenuItem onClick={onDelete} className="text-[#f53f3f] focus:text-[#f53f3f] focus:bg-[#fff2f0]">
                                        <Trash2 className="size-4 mr-2" />{localize("com_knowledge.delete")}</DropdownMenuItem>
                                </>
                            )}
                        </DropdownMenuContent>
                    </DropdownMenu>
                </div>
            </TableCell>
        </TableRow>
    );
}