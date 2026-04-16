import {
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/Table";
import {
    Download,
    Edit,
    FileImageIcon,
    FileUserIcon,
    MoreVertical,
    PencilLineIcon,
    RefreshCw,
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
import TagGroup from "./TagGroup";
import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import { SortType, SortDirection, FileStatus, FileType, KnowledgeFile } from "~/api/knowledge";
import { formatBytes } from "~/utils";
import { useInlineRename } from "../hooks/useInlineRename";
import { formatTime } from "../knowledgeUtils";
import { useLocalize } from "~/hooks";

/** 状态列悬停：下载 / 更多 — 白底、细灰边、4px 圆角 */
const FILE_ROW_ACTION_BTN_CLASS =
    "size-7 shrink-0 flex items-center justify-center rounded-[4px] border border-[#ECECEC] bg-white text-[#4e5969] hover:bg-[#f7f7f7] transition-colors";

// ============================================================
// 列定义：key、最小宽度、初始宽度
// ============================================================
const COLUMN_CONFIG = {
    checkbox: { minWidth: 48, initialWidth: 48 },
    name: { minWidth: 140, initialWidth: 280 },
    fileType: { minWidth: 100, initialWidth: 120 },
    size: { minWidth: 80, initialWidth: 120 },
    tags: { minWidth: 140, initialWidth: 200 },
    updateTime: { minWidth: 140, initialWidth: 180 },
    status: { minWidth: 120, initialWidth: 160 },
} as const;

type ColumnKey = keyof typeof COLUMN_CONFIG;

// 不参与拖拽调整的列
const NON_RESIZABLE_COLUMNS: ColumnKey[] = ["checkbox"];
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
            const d = dragging.current;
            if (!d) return;
            const delta = ev.clientX - d.startX;
            const minW = COLUMN_CONFIG[d.key].minWidth;
            // 单列过宽时横向滚动浏览，避免把整页撑出视口
            const cap = typeof window !== "undefined" ? Math.max(400, window.innerWidth - 80) : 2000;
            const newWidth = Math.min(cap, Math.max(minW, d.startWidth + delta));
            const key = d.key;
            // 必须在 updater 外捕获 key：mouseup 会先清空 dragging，批处理时再读 current 会为 null
            setColumnWidths((prev) => ({ ...prev, [key]: newWidth }));
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
        <div
            className={cn(
                "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm px-2 py-0.5 text-xs font-medium",
                item.bg,
                item.color
            )}
        >
            <span className={cn("size-1.5 shrink-0 rounded-full", item.dot)} />
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
    currentSort: { key?: string; direction?: string };
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
                "group relative my-2 cursor-pointer select-none overflow-visible bg-[rgb(251,251,251)] p-0 pr-3",
                "transition-colors hover:bg-[#f2f3f5]",
                isSticky && "sticky z-20"
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
                {(() => {
                    const arrowDir = direction === "asc" ? "up" : "down";
                    const isActiveSort = isActive;
                    const src = `${__APP_ENV__.BASE_URL}/assets/channel/sort-amount-${arrowDir}${
                        isActiveSort ? "-blue" : ""
                    }.svg`;
                    return (
                        <img
                            className={`size-4 shrink-0 transition-opacity ${
                                isActiveSort ? "opacity-100" : "opacity-0"
                            } group-hover:opacity-100`}
                            src={src}
                            alt="sort"
                        />
                    );
                })()}
                <span className={cn("text-sm font-normal", isActive ? "text-[#1d2129]" : "text-[#4e5969]")}>
                    {children}
                </span>
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
    isAllSelected,
    isIndeterminate,
    onSelectAll,
}: {
    columnWidths: Record<ColumnKey, number>;
    onResizeStart: (key: ColumnKey, e: React.MouseEvent) => void;
    showLeftShadow: boolean;
    sortBy: SortType | undefined;
    sortDirection: SortDirection | undefined;
    onSort: (sortBy: SortType) => void;
    isAdmin: boolean;
    isAllSelected: boolean;
    isIndeterminate: boolean;
    onSelectAll: () => void;
}) {
    const localize = useLocalize();
    const currentSort = { key: sortBy, direction: sortDirection };

    const handleSort = (key: string) => {
        onSort(key as SortType);
    };

    return (
        <TableHeader className="border-b border-[#e5e6eb] bg-[rgb(251,251,251)]">
            <TableRow className="hover:bg-transparent border-none">
                {/* 复选框列 — 左侧固定 */}
                <TableHead
                    className="sticky left-0 z-20 bg-[rgb(251,251,251)] p-0 text-center"
                    style={{ width: columnWidths.checkbox, minWidth: columnWidths.checkbox, maxWidth: columnWidths.checkbox }}
                >
                    <div className="flex h-full items-center justify-center">
                        <Checkbox
                            className="border-gray-400 data-[state=checked]:border-primary"
                            checked={isIndeterminate ? "indeterminate" : isAllSelected}
                            onCheckedChange={onSelectAll}
                        />
                    </div>
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
                    className="relative bg-[rgb(251,251,251)] p-0 pr-3 font-normal text-[#4e5969]"
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
                        className="relative bg-[rgb(251,251,251)] p-0 pr-3 font-normal text-[#4e5969]"
                        style={{ width: columnWidths.status, minWidth: columnWidths.status, maxWidth: columnWidths.status }}
                    >
                        <div className="flex items-center gap-1.5 border-l pl-3">
                            {localize("com_knowledge.status")}</div>
                        <ResizeHandle columnKey="status" onResizeStart={onResizeStart} />
                    </TableHead>
                )}

                {/* 占位空列，吸收多余由于 minWidth:100% 产生的宽度，防止所有固定宽度的列被等比例拉伸 */}
                <TableHead className="pointer-events-none border-none bg-[rgb(251,251,251)] p-0" />
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
    handleSelectAll: (isAllSelected: boolean) => void;
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
    sortBy: SortType | undefined;
    sortDirection: SortDirection | undefined;
    onSort: (sortBy: SortType) => void;
}

export function FileTable({ files, selectedFiles, handleSelectAll, handleSelectFile, isAdmin, onDownload, onEditTags, onRename, onDelete, onRetry, onNavigateFolder, onPreview, onValidateName, onCancelCreate, sortBy, sortDirection, onSort }: FileTableProps) {
    const { columnWidths, onResizeStart, totalWidth } = useResizableColumns();
    const scrollRef = useRef<HTMLDivElement>(null);
    const { showLeftShadow, showRightShadow } = useScrollShadow(scrollRef);

    const isAllSelected = files.length > 0 && files.every((f) => selectedFiles.has(f.id));
    const isIndeterminate = !isAllSelected && files.some((f) => selectedFiles.has(f.id));

    return (
        <div className="relative max-w-full min-w-0 overflow-hidden border-t border-[#e5e6eb]">
            {/* 横向滚动限制在容器内，不撑开整页 */}
            <div ref={scrollRef} className="max-w-full overflow-x-auto overflow-y-visible">
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
                        isAllSelected={isAllSelected}
                        isIndeterminate={isIndeterminate}
                        onSelectAll={() => handleSelectAll(isAllSelected)}
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
    const rowBg = isSelected ? "bg-[#E6EDFC] group-hover:bg-[#F8F8F8]" : "bg-white group-hover:bg-[#f7f7f7]";
    const failureMessage = (
        file.status === FileStatus.FAILED || file.status === FileStatus.TIMEOUT
    ) && file.errorMessage?.trim()
        ? file.errorMessage.trim()
        : null;

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

    const hasRetryOption = Boolean(
        (
            file.status === FileStatus.FAILED ||
            (isFolder && file.successFileNum !== undefined && file.fileNum !== undefined && file.successFileNum < file.fileNum)
        )
    );
    const showMoreMenu = isAdmin;

    return (
        <TableRow className={cn(
            "group border-b-[#e5e6eb] transition-colors",
            isSelected ? "bg-[#E6EDFC] hover:bg-[#F8F8F8]" : "hover:bg-[#f7f7f7]"
        )}>
            {/* 复选框 — 左侧固定 */}
            <TableCell
                className={cn("sticky left-0 z-10 px-0 py-3 text-center", rowBg)}
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
                className={cn("sticky z-10 overflow-visible py-3", rowBg)}
                style={{
                    width: columnWidths.name,
                    minWidth: columnWidths.name,
                    maxWidth: columnWidths.name,
                    left: columnWidths.checkbox,
                }}
            >
                <div className="flex items-center gap-2 min-w-0 text-gray-300 ">
                    <div className="flex h-[35px] w-[40px] shrink-0 items-center justify-center rounded-sm bg-white">
                        {isFolder
                            ? (
                                <img
                                    src={`${__APP_ENV__.BASE_URL}/assets/channel/Subtract.svg`}
                                    alt=""
                                    className="h-[35px] w-[40px] object-contain"
                                />
                            )
                            : (['png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp'].includes(file.name.split('.').pop()?.toLowerCase() || "")
                                ? <FileImageIcon className="size-4" />
                                : <FileUserIcon className="size-4" />)
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
                            <span className="block truncate">{file.name}</span>
                        </span>
                    )}
                </div>
                {failureMessage && !isRenaming && (
                    <p
                        className="mt-1 truncate text-xs leading-5 text-[#f53f3f]"
                        title={failureMessage}
                    >
                        {localize("com_knowledge.failure_reason")}: {failureMessage}
                    </p>
                )}
                {/* 固定列右侧阴影 */}
                <StickyColumnShadow show={showLeftShadow} />
            </TableCell>

            {/* 类型 */}
            <TableCell
                className="py-3 text-sm text-[#86909c]"
                style={{ width: columnWidths.fileType, minWidth: columnWidths.fileType, maxWidth: columnWidths.fileType }}
            >
                <span className="truncate block">
                    {isFolder ? localize("com_knowledge.folder") : (file.name.split('.').pop()?.toLowerCase() || "--")}
                </span>
            </TableCell>

            {/* 大小 */}
            <TableCell
                className="py-3 text-sm text-[#86909c]"
                style={{ width: columnWidths.size, minWidth: columnWidths.size, maxWidth: columnWidths.size }}
            >
                <span className="truncate block">
                    {isFolder ? "--" : (file.size ? formatBytes(file.size, 2, true) : "--")}
                </span>
            </TableCell>

            {/* 标签 — 行悬停时显示编辑（管理员、非文件夹） */}
            <TableCell
                className="py-3"
                style={{ width: columnWidths.tags, minWidth: columnWidths.tags, maxWidth: columnWidths.tags }}
            >
                <div className="flex h-full w-full items-center gap-1.5 overflow-hidden">
                    {!isFolder && (
                        <TagGroup
                            tags={file.tags}
                            actionButton={
                                isAdmin ? (
                                    <button
                                        type="button"
                                        title={localize("com_knowledge.edit_tags")}
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            onEditTags();
                                        }}
                                        className="hidden cursor-pointer items-center justify-center text-[#165dff] transition-colors hover:text-[#165dff]/80 group-hover:flex"
                                    >
                                        <PencilLineIcon className="size-3.5" />
                                    </button>
                                ) : undefined
                            }
                        />
                    )}
                </div>
            </TableCell>

            {/* 时间 — 非管理员：行悬停显示下载（无「状态」列时） */}
            <TableCell
                className="py-3 text-sm text-[#86909c]"
                style={{ width: columnWidths.updateTime, minWidth: columnWidths.updateTime, maxWidth: columnWidths.updateTime }}
            >
                {isAdmin ? (
                    <span className="block truncate whitespace-nowrap">{formatTime(file.updatedAt)}</span>
                ) : (
                    <div className="flex min-w-0 items-center justify-between gap-2">
                        <span className="block min-w-0 truncate whitespace-nowrap">{formatTime(file.updatedAt)}</span>
                        <button
                            type="button"
                            className={cn(
                                FILE_ROW_ACTION_BTN_CLASS,
                                "opacity-0 pointer-events-none transition-opacity group-hover:pointer-events-auto group-hover:opacity-100"
                            )}
                            onClick={(e) => {
                                e.stopPropagation();
                                onDownload();
                            }}
                            title={localize("com_knowledge.download")}
                        >
                            <Download className="size-4" />
                        </button>
                    </div>
                )}
            </TableCell>

            {/* 状态（管理员）— 悬停按钮锚在胶囊水平中点：左缘对齐 50%，只盖住右半段文字 */}
            {isAdmin && (
                <TableCell
                    className="relative overflow-visible py-3 align-middle"
                    style={{ width: columnWidths.status, minWidth: columnWidths.status, maxWidth: columnWidths.status }}
                >
                    <div className="relative inline-flex w-max max-w-full items-center">
                        {isFolder ? (
                            <span className="whitespace-nowrap text-sm">
                                <span className="font-medium text-emerald-500">
                                    {file.successFileNum ?? 0}
                                </span>
                                <span className="text-[#86909c]">
                                    /{file.fileNum ?? 0}
                                </span>
                            </span>
                        ) : (
                            <StatusBadge status={file.status ?? FileStatus.WAITING} />
                        )}
                        <div
                            className={cn(
                                "absolute left-1/2 top-1/2 z-[2] flex -translate-y-1/2 items-center gap-1",
                                "pointer-events-none opacity-0 transition-opacity",
                                "group-hover:pointer-events-auto group-hover:opacity-100"
                            )}
                        >
                            <button
                                type="button"
                                className={FILE_ROW_ACTION_BTN_CLASS}
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onDownload();
                                }}
                                title={localize("com_knowledge.download")}
                            >
                                <Download className="size-4" />
                            </button>
                            {showMoreMenu && (
                                <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                        <button type="button" className={FILE_ROW_ACTION_BTN_CLASS}>
                                            <MoreVertical className="size-4" />
                                        </button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end" className="w-32">
                                        {!isFolder && (
                                            <DropdownMenuItem
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    onEditTags();
                                                }}
                                            >
                                                <Tag className="mr-2 size-4" />
                                                {localize("com_knowledge.edit_tags")}
                                            </DropdownMenuItem>
                                        )}
                                        <DropdownMenuItem
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                startRenaming();
                                            }}
                                        >
                                            <Edit className="mr-2 size-4" />
                                            {localize("com_knowledge.rename")}
                                        </DropdownMenuItem>
                                        {hasRetryOption && (
                                            <DropdownMenuItem
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    onRetry?.();
                                                }}
                                            >
                                                <RefreshCw className="mr-2 size-4" />
                                                {localize("com_knowledge.retry")}
                                            </DropdownMenuItem>
                                        )}
                                        <DropdownMenuItem
                                            className="text-[#f53f3f] focus:bg-[#fff2f0] focus:text-[#f53f3f]"
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                onDelete();
                                            }}
                                        >
                                            <Trash2 className="mr-2 size-4" />
                                            {localize("com_knowledge.delete")}
                                        </DropdownMenuItem>
                                    </DropdownMenuContent>
                                </DropdownMenu>
                            )}
                        </div>
                    </div>
                </TableCell>
            )}

            {/* 占位空列 */}
            <TableCell className="pointer-events-none border-none p-0" />
        </TableRow>
    );
}
