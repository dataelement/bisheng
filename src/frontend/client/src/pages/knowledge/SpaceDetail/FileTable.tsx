import {
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/Table";
import { Outlined } from "bisheng-icons";
import { GitBranch, History, FileSearch } from "lucide-react";
import {
    Checkbox,
    DropdownMenu,
    DropdownMenuTrigger
} from "~/components";
import { ActionMenuContent, ActionMenuItem } from "~/components/ActionMenu";
import { cn } from "~/utils";
import TagGroup from "./TagGroup";
import { EditEncodingModal } from "./EditEncodingModal";
import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import { SortType, SortDirection, FileStatus, FileType, KnowledgeFile, SpaceRole, updateFileEncoding } from "~/api/knowledge";
import { formatBytes } from "~/utils";
import { useInlineRename } from "../hooks/useInlineRename";
import { useKnowledgeMoveDrag } from "../hooks/useKnowledgeMoveDrag";
import { formatTime, getKnowledgeApprovalStatusLabel, isKnowledgeApprovalRejected, isKnowledgeItemPreviewable, isKnowledgeItemUploading } from "../knowledgeUtils";
import { useLocalize, useScrollRevealRef } from "~/hooks";
import { useGetBsConfig } from "~/hooks/queries/endpoints/queries";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Highlight case-insensitive matches of `keyword` inside `text` (Figma 11814:70449). */
const renderHighlightedName = (text: string, keyword?: string) => {
    const kw = keyword?.trim();
    if (!kw) return text;
    const parts = text.split(new RegExp(`(${escapeRegExp(kw)})`, "gi"));
    const lowerKw = kw.toLowerCase();
    return parts.map((part, i) =>
        part.toLowerCase() === lowerKw
            ? <span key={i} className="text-[#3a74e9]">{part}</span>
            : part
    );
};

/** 状态列悬停：下载 / 更多 — 白底、细灰边、8px 圆角 */
const FILE_ROW_ACTION_BTN_CLASS =
    "size-7 shrink-0 flex items-center justify-center rounded-[8px] border border-[#ECECEC] bg-white text-[#4e5969] hover:bg-[#f7f7f7] transition-colors";

// ============================================================
// 列定义：key、最小宽度、初始宽度
// ============================================================
const COLUMN_CONFIG = {
    checkbox: { minWidth: 48, initialWidth: 48 },
    name: { minWidth: 140, initialWidth: 280 },
    fileType: { minWidth: 140, initialWidth: 140 },
    size: { minWidth: 140, initialWidth: 140 },
    tags: { minWidth: 140, initialWidth: 200 },
    fileEncoding: { minWidth: 160, initialWidth: 204 },
    updateTime: { minWidth: 140, initialWidth: 180 },
    status: { minWidth: 120, initialWidth: 160 },
} as const;

type ColumnKey = keyof typeof COLUMN_CONFIG;

// 不参与拖拽调整的列
// Resize handles use `translate-x-1/2` to straddle the column edge for a nicer
// hit area. The trade-off: the last resizable column's handle pokes 4px past
// the table's right edge, which counts toward scrollWidth and produces a
// permanent 4px horizontal scroll. Excluding `updateTime` (the last data
// column in every mode) removes its handle and the 4px overflow.
// fileType / size are pinned to a fixed 100px and not user-resizable.
const NON_RESIZABLE_COLUMNS: ColumnKey[] = ["checkbox", "updateTime", "fileType", "size"];
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
// Status pill — matches the card-view tag (Figma 11671:34506). Neutral grey for
// in-progress states (parsing / queueing / rebuilding / uploading), red for errors,
// blue for pending approval, green for success.
const StatusBadge = ({ status, file }: { status: FileStatus; file?: KnowledgeFile }) => {
    const localize = useLocalize();
    const approvalStatusLabel = file ? getKnowledgeApprovalStatusLabel(file) : null;
    const statusReason = file?.approvalReason?.trim() || file?.errorMessage?.trim() || null;

    type Tone = { bg: string; text: string; dot: string };
    const neutralTone: Tone = { bg: "bg-[#f2f4f7]", text: "text-[#6b7785]", dot: "bg-[#6b7785]" };
    const errorTone: Tone = { bg: "bg-[#fff2f0]", text: "text-[#f53f3f]", dot: "bg-[#f53f3f]" };
    const infoTone: Tone = { bg: "bg-[#e8f3ff]", text: "text-[#165dff]", dot: "bg-[#165dff]" };
    const successTone: Tone = { bg: "bg-[#e8ffea]", text: "text-[#00b42a]", dot: "bg-[#00b42a]" };

    const wrapWithReason = (node: React.ReactNode) => {
        // Skip tooltip for queueing status
        if (!statusReason || status === FileStatus.WAITING) return node;
        return (
            <Tooltip>
                <TooltipTrigger asChild>
                    <div className="inline-flex max-w-full">{node}</div>
                </TooltipTrigger>
                <TooltipContent noArrow side="top" className="max-w-[320px] rounded-md bg-[#1D2129] px-3 py-2 text-left text-xs leading-5 text-white">
                    {statusReason}
                </TooltipContent>
            </Tooltip>
        );
    };

    let label: string;
    let tone: Tone;

    if (approvalStatusLabel) {
        label = approvalStatusLabel;
        tone = (file && isKnowledgeApprovalRejected(file)) ? errorTone : infoTone;
    } else {
        const config: Record<string, { label: string; tone: Tone }> = {
            [FileStatus.SUCCESS]: { label: localize("com_knowledge.success"), tone: successTone },
            [FileStatus.PROCESSING]: { label: localize("com_knowledge.parsing_status"), tone: neutralTone },
            [FileStatus.WAITING]: { label: localize("com_knowledge.queueing_status"), tone: neutralTone },
            [FileStatus.REBUILDING]: { label: localize("com_knowledge.rebuilding_status"), tone: neutralTone },
            [FileStatus.UPLOADING]: { label: localize("com_knowledge.uploading_status"), tone: neutralTone },
            [FileStatus.FAILED]: { label: localize("com_knowledge.fail"), tone: errorTone },
            [FileStatus.TIMEOUT]: { label: localize("com_knowledge.timeout"), tone: errorTone },
            [FileStatus.VIOLATION]: { label: localize("com_knowledge.violation"), tone: errorTone },
        };
        const item = config[status] || config[FileStatus.WAITING];
        label = item.label;
        tone = item.tone;
    }

    return wrapWithReason(
        <div
            className={cn(
                "inline-flex shrink-0 items-center justify-center gap-1 whitespace-nowrap rounded-[4px] px-2 text-xs leading-5",
                tone.bg,
                tone.text,
            )}
        >
            <span className={cn("size-1 shrink-0 rounded-full", tone.dot)} />
            {label}
        </div>
    );
};

// ============================================================
// 拖拽手柄
// ============================================================
function ResizeHandle({ columnKey, onResizeStart }: { columnKey: ColumnKey; onResizeStart: (key: ColumnKey, e: React.MouseEvent) => void }) {
    return (
        <div
            className="group/handle absolute right-0 top-0 bottom-0 z-10 flex w-2 cursor-col-resize items-center justify-center translate-x-1/2"
            onMouseDown={(e) => onResizeStart(columnKey, e)}
        >
            {/* 高亮线与列分界线对齐：手柄跨在相邻两列边界上，避免命中区偏在分割线左侧 */}
            <div className="h-full w-0.5 bg-transparent group-hover/handle:bg-[#999] transition-colors" />
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

/**
 * Right-side counterpart of StickyColumnShadow. Renders inside the zero-width
 * sticky right-0 cell at the end of each row/header, so the shadow's vertical
 * extent matches that cell (i.e. covers only header + row, never the empty
 * area below the last row).
 */
function StickyColumnShadowRight({ show }: { show: boolean }) {
    if (!show) return null;
    return (
        <div
            aria-hidden
            className="pointer-events-none absolute top-0 left-[-12px] h-full w-[12px] z-10"
            style={{
                background: "linear-gradient(to left, rgba(0,0,0,0.08), transparent)",
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
    /** 表头内容与排序图标整体右对齐（与数字列单元格一致） */
    headerAlignEnd,
    /** true：排序图标在标题左侧（如文件大小列） */
    sortIconBeforeText,
    /** false：左侧不分隔竖线（如紧贴复选框列的「文件名」表头） */
    leadingBorder = true,
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
    headerAlignEnd?: boolean;
    sortIconBeforeText?: boolean;
    leadingBorder?: boolean;
}) => {
    const isActive = currentSort?.key === sortKey;
    const direction = isActive ? currentSort.direction : "asc";
    const isSticky = stickyLeft !== undefined;
    const isResizable = !NON_RESIZABLE_COLUMNS.includes(columnKey);
    const ArrowIcon = direction === "asc" ? Outlined.SortAmountUp : Outlined.SortAmountDown;
    const sortIcon = (
        <ArrowIcon
            className={cn(
                "size-4 shrink-0 transition-opacity",
                isActive ? "text-[#212121] opacity-100" : "text-[#999] opacity-0",
                "group-hover:opacity-100",
            )}
        />
    );
    const title = (
        <span className={cn("text-sm font-normal", isActive ? "text-[#1d2129]" : "text-[#4e5969]")}>{children}</span>
    );
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
            <div
                className={cn(
                    "flex min-w-0 items-center gap-1.5 pl-3",
                    leadingBorder && "border-l",
                    headerAlignEnd && "w-full justify-end"
                )}
            >
                {sortIconBeforeText ? (
                    <>
                        {sortIcon}
                        {title}
                    </>
                ) : (
                    <>
                        {title}
                        {sortIcon}
                    </>
                )}
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
    showRightShadow,
    sortBy,
    sortDirection,
    onSort,
    isAdmin,
    showStatusColumn,
    isAllSelected,
    isIndeterminate,
    onSelectAll,
    shougangEnabled,
}: {
    columnWidths: Record<ColumnKey, number>;
    onResizeStart: (key: ColumnKey, e: React.MouseEvent) => void;
    showLeftShadow: boolean;
    showRightShadow: boolean;
    sortBy: SortType | undefined;
    sortDirection: SortDirection | undefined;
    onSort: (sortBy: SortType) => void;
    isAdmin: boolean;
    showStatusColumn: boolean;
    isAllSelected: boolean;
    isIndeterminate: boolean;
    onSelectAll: () => void;
    shougangEnabled: boolean;
}) {
    const localize = useLocalize();
    const currentSort = { key: sortBy, direction: sortDirection };

    const handleSort = (key: string) => {
        onSort(key as SortType);
    };

    return (
        <TableHeader className="sticky top-0 z-30 bg-[rgb(251,251,251)] [&_th]:border-b [&_th]:border-[#e5e6eb]">
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
                    leadingBorder={false}
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
                    headerAlignEnd
                    sortIconBeforeText
                >
                    {localize("com_knowledge.file_size")}</SortableHeader>

                {/* 标签 — 不排序 */}
                <TableHead
                    className="relative bg-[rgb(251,251,251)] p-0 font-normal text-[#4e5969]"
                    style={{ width: columnWidths.tags, minWidth: columnWidths.tags, maxWidth: columnWidths.tags }}
                >
                    <div className="flex items-center gap-1.5 border-l pl-3">
                        {localize("com_knowledge.tag")}</div>
                    <ResizeHandle columnKey="tags" onResizeStart={onResizeStart} />
                </TableHead>

                {/* 文件编码 — 仅 shougang 模式显示 */}
                {shougangEnabled && (
                    <TableHead
                        className="relative bg-[rgb(251,251,251)] p-0 font-normal text-[#4e5969]"
                        style={{
                            width: columnWidths.fileEncoding,
                            minWidth: columnWidths.fileEncoding,
                            maxWidth: columnWidths.fileEncoding,
                        }}
                    >
                        <div className="flex items-center gap-1.5 border-l pl-3">
                            {localize("com_knowledge.file_encoding")}
                        </div>
                        <ResizeHandle columnKey="fileEncoding" onResizeStart={onResizeStart} />
                    </TableHead>
                )}

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

                {/* Status column removed — non-success status pills now render inline
                    next to the file name (see row cell). */}

                {/* 行末锚点列（零宽）— 与 tbody 列结构保持一致 + 承载右侧 sticky 阴影 */}
                <TableHead
                    className="sticky right-0 z-[31] overflow-visible border-none bg-[rgb(251,251,251)] p-0"
                    style={{ width: 0, minWidth: 0, maxWidth: 0 }}
                >
                    <StickyColumnShadowRight show={showRightShadow} />
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
    /** F040: lazily resolve a file's action permissions when its row menu opens. */
    onEnsureFilePermissions?: (file: KnowledgeFile) => void;
    selectedFiles: Set<string>;
    handleSelectAll: (isAllSelected: boolean) => void;
    handleSelectFile: (id: string, selected: boolean) => void;
    isAdmin: boolean;
    /** The current user's role within this specific space. Used to gate encoding edits. */
    currentUserRole?: SpaceRole | null;
    onDownload: (id: string) => void;
    onEditTags: (id: string) => void;
    onRename: (id: string, newName: string) => void;
    onDelete: (id: string) => void;
    onRetry: (id: string) => void;
    onNavigateFolder: (id: string) => void;
    onPreview?: (id: string) => void;
    onValidateName: (name: string, isFolder: boolean, fileId: string, isCreating: boolean) => string | null;
    onCancelCreate?: () => void;
    permissionEntryIds?: Set<string>;
    renameEntryIds?: Set<string>;
    deleteEntryIds?: Set<string>;
    downloadEntryIds?: Set<string>;
    onManagePermission?: (id: string) => void;
    /** F034: open the move dialog for a file/folder. Shown when provided. */
    onMove?: (file: KnowledgeFile) => void;
    /** F034: move permission for files / folders (move_file / move_folder). A
     *  role may grant one without the other, so they're probed separately. */
    canMoveFile?: boolean;
    canMoveFolder?: boolean;
    /** F034 drag-move: drop dragged items into a same-space folder. */
    onMoveToFolder?: (folderId: string, items: KnowledgeFile[], folderName: string) => void;
    /** Version management gating for per-row version actions / badges. */
    versionManagementEnabled?: boolean;
    /** Open the version-management (similar-document linking) dialog for a file. */
    onOpenVersionManagement?: (file: KnowledgeFile) => void;
    /** Open the version-history sheet for a file. */
    onOpenVersionHistory?: (file: KnowledgeFile) => void;
    /** Whether the current user can manage members (gates the "similar" pill). */
    canManageMembers?: boolean;
    sortBy: SortType | undefined;
    sortDirection: SortDirection | undefined;
    onSort: (sortBy: SortType) => void;
    /** Tag IDs hit by the active search; matching tags are highlighted in TagGroup. */
    highlightedTagIds?: number[];
    /** Keyword hit by the active search; matching substring in the file name is highlighted. */
    highlightKeyword?: string;
    /** Scroll handler attached to the table's internal scroll container (for infinite scroll). */
    onScroll?: React.UIEventHandler<HTMLDivElement>;
    /** Extra spacing reserved below the last row (e.g. to clear a floating bottom dock). */
    bottomSpacing?: number;
}

export function FileTable({ files, onEnsureFilePermissions, selectedFiles, handleSelectAll, handleSelectFile, isAdmin, currentUserRole, onDownload, onEditTags, onRename, onDelete, onRetry, onNavigateFolder, onPreview, onValidateName, onCancelCreate, permissionEntryIds, renameEntryIds, deleteEntryIds, downloadEntryIds, onManagePermission, onMove, canMoveFile = false, canMoveFolder = false, onMoveToFolder, versionManagementEnabled = false, onOpenVersionManagement, onOpenVersionHistory, canManageMembers = false, sortBy, sortDirection, onSort, highlightedTagIds, highlightKeyword, onScroll, bottomSpacing = 0 }: FileTableProps) {
    const { columnWidths, onResizeStart, totalWidth } = useResizableColumns();
    const scrollRef = useRef<HTMLDivElement>(null);
    const hScrollRevealRef = useScrollRevealRef<HTMLDivElement>();
    const { showLeftShadow, showRightShadow } = useScrollShadow(scrollRef);
    const showStatusColumn = isAdmin || files.some((file) => Boolean(file.approvalStatus));
    const localize = useLocalize();

    // Shougang feature gate
    const { data: bsConfig } = useGetBsConfig();
    const shougangEnabled = bsConfig?.shougang?.enabled ?? false;
    const { showToast } = useToastContext();

    const [editingEncodingFile, setEditingEncodingFile] = useState<KnowledgeFile | null>(null);

    // Encoding edits are restricted to the space creator or space admin.
    // currentUserRole carries the user's role within this specific space (not platform-admin).
    const canEditEncoding =
        currentUserRole === SpaceRole.CREATOR ||
        currentUserRole === SpaceRole.ADMIN;

    const handleOpenEditEncoding = (file: KnowledgeFile) => {
        if (!canEditEncoding) return;
        setEditingEncodingFile(file);
    };

    // F034 same-space drag-move: rows are drag sources, folder rows are drop targets.
    const {
        enabled: dragMoveEnabled,
        dragOverFolderId,
        handleDragStart: handleRowDragStart,
        handleFolderDragOver,
        handleFolderDragLeave,
        handleFolderDrop,
    } = useKnowledgeMoveDrag({ files, selectedFiles, onMoveToFolder });

    const handleSubmitEncoding = async (newEncoding: string) => {
        if (!editingEncodingFile) return;
        try {
            await updateFileEncoding(
                String(editingEncodingFile.spaceId),
                String(editingEncodingFile.id),
                newEncoding,
            );
            // Trigger file list reload via the existing custom event mechanism
            window.dispatchEvent(new CustomEvent("knowledge-space-files:refresh", {
                detail: { spaceId: editingEncodingFile.spaceId },
            }));
            showToast?.({
                message: localize("com_knowledge.file_encoding_update_success"),
                severity: NotificationSeverity.SUCCESS,
            });
        } catch (e) {
            showToast?.({
                message: localize("com_knowledge.file_encoding_update_failed"),
                severity: NotificationSeverity.ERROR,
            });
            throw e;
        }
    };

    // Uploading folder placeholders aren't selectable — exclude them so the header
    // checkbox can still reach the "all selected" state and select-all skips them.
    const selectableFiles = files.filter((f) => !(f.type === FileType.FOLDER && isKnowledgeItemUploading(f)));
    const isAllSelected = selectableFiles.length > 0 && selectableFiles.every((f) => selectedFiles.has(f.id));
    const isIndeterminate = !isAllSelected && selectableFiles.some((f) => selectedFiles.has(f.id));

    return (
        <div className="relative flex min-h-0 min-w-0 max-w-full flex-1 flex-col overflow-hidden">
            {/* Single scroll container — both axes here so the sticky <thead> tracks
                vertical scroll without being trapped by an inner-only x-scroll wrapper. */}
            <div
                ref={(el) => {
                    scrollRef.current = el;
                    hScrollRevealRef(el);
                }}
                onScroll={onScroll}
                className="min-h-0 max-w-full flex-1 overflow-auto scrollbar-on-scroll"
            >
                <table
                    className="w-full caption-bottom border-separate border-spacing-0 text-sm"
                    style={{
                        tableLayout: "fixed",
                        width: totalWidth,
                        minWidth: "100%",
                    }}
                >
                    <FileTableHeader
                        columnWidths={columnWidths}
                        onResizeStart={onResizeStart}
                        showLeftShadow={showLeftShadow}
                        showRightShadow={showRightShadow}
                        sortBy={sortBy}
                        sortDirection={sortDirection}
                        onSort={onSort}
                        isAdmin={isAdmin}
                        showStatusColumn={showStatusColumn}
                        isAllSelected={isAllSelected}
                        isIndeterminate={isIndeterminate}
                        onSelectAll={() => handleSelectAll(isAllSelected)}
                        shougangEnabled={shougangEnabled}
                    />
                    <TableBody>
                        {files.map((file) => (
                            <FileRow
                                key={file.id}
                                file={file}
                                isAdmin={isAdmin}
                                onEnsureFilePermissions={onEnsureFilePermissions}
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
                                onManagePermission={
                                    onManagePermission && permissionEntryIds?.has(file.id)
                                        ? () => onManagePermission(file.id)
                                        : undefined
                                }
                                onMove={onMove ? () => onMove(file) : undefined}
                                canMove={file.type === FileType.FOLDER ? canMoveFolder : canMoveFile}
                                versionManagementEnabled={versionManagementEnabled}
                                onOpenVersionManagement={onOpenVersionManagement}
                                onOpenVersionHistory={onOpenVersionHistory}
                                canManageMembers={canManageMembers}
                                canRename={Boolean(renameEntryIds?.has(file.id))}
                                canDelete={Boolean(deleteEntryIds?.has(file.id))}
                                canDownload={Boolean(downloadEntryIds?.has(file.id))}
                                columnWidths={columnWidths}
                                showStatusColumn={showStatusColumn}
                                showLeftShadow={showLeftShadow}
                                showRightShadow={showRightShadow}
                                shougangEnabled={shougangEnabled}
                                canEditEncoding={canEditEncoding}
                                onEditEncoding={handleOpenEditEncoding}
                                highlightedTagIds={highlightedTagIds}
                                highlightKeyword={highlightKeyword}
                                rowDraggable={dragMoveEnabled}
                                onRowDragStart={handleRowDragStart(file)}
                                isFolderDragOver={dragOverFolderId === file.id}
                                onFolderDragOver={handleFolderDragOver(file)}
                                onFolderDragLeave={handleFolderDragLeave(file)}
                                onFolderDrop={handleFolderDrop(file)}
                            />
                        ))}
                    </TableBody>
                </table>
                {bottomSpacing > 0 && <div style={{ height: bottomSpacing }} aria-hidden />}
            </div>

            {shougangEnabled && (
                <EditEncodingModal
                    file={editingEncodingFile}
                    open={!!editingEncodingFile}
                    onClose={() => setEditingEncodingFile(null)}
                    onSubmit={handleSubmitEncoding}
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
    onEnsureFilePermissions,
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
    onManagePermission,
    onMove,
    canMove = false,
    versionManagementEnabled = false,
    onOpenVersionManagement,
    onOpenVersionHistory,
    canManageMembers = false,
    canRename = false,
    canDelete = false,
    canDownload = false,
    columnWidths,
    showStatusColumn,
    showLeftShadow,
    showRightShadow,
    shougangEnabled = false,
    canEditEncoding = false,
    onEditEncoding,
    highlightedTagIds,
    highlightKeyword,
    rowDraggable = false,
    onRowDragStart,
    isFolderDragOver = false,
    onFolderDragOver,
    onFolderDragLeave,
    onFolderDrop,
}: {
    file: KnowledgeFile;
    onEnsureFilePermissions?: (file: KnowledgeFile) => void;
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
    onManagePermission?: () => void;
    onMove?: () => void;
    canMove?: boolean;
    versionManagementEnabled?: boolean;
    onOpenVersionManagement?: (file: KnowledgeFile) => void;
    onOpenVersionHistory?: (file: KnowledgeFile) => void;
    canManageMembers?: boolean;
    canRename?: boolean;
    canDelete?: boolean;
    canDownload?: boolean;
    columnWidths: Record<ColumnKey, number>;
    showStatusColumn: boolean;
    showLeftShadow: boolean;
    showRightShadow: boolean;
    shougangEnabled?: boolean;
    canEditEncoding?: boolean;
    onEditEncoding?: (file: KnowledgeFile) => void;
    highlightedTagIds?: number[];
    highlightKeyword?: string;
    // F034 drag-move: row is a drag source; folder rows are drop targets.
    rowDraggable?: boolean;
    onRowDragStart?: (e: React.DragEvent) => void;
    isFolderDragOver?: boolean;
    onFolderDragOver?: (e: React.DragEvent) => void;
    onFolderDragLeave?: () => void;
    onFolderDrop?: (e: React.DragEvent) => void;
}) {
    const localize = useLocalize();
    const [moreMenuOpen, setMoreMenuOpen] = useState(false);
    // F040: resolve this file's action permissions lazily, only when the menu opens.
    const handleMoreMenuOpenChange = (open: boolean) => {
        setMoreMenuOpen(open);
        if (open) onEnsureFilePermissions?.(file);
    };
    const isFolder = file.type === FileType.FOLDER;
    const isCreating = !!file.isCreating;
    // Uploading placeholder rows have no backend identity yet — not movable.
    const isUploading = isKnowledgeItemUploading(file);
    // A folder still uploading its batch: masked (50% faded content), shows an
    // "uploading" tag, not clickable, checkbox greyed-out — mirrors the card view.
    const isUploadingFolderPlaceholder = isFolder && isUploading;
    // 每格统一底色 + 同一套 transition，避免固定列用 group-hover、其余列透出 tr:hover 时不同步闪一下
    // F034: 拖拽悬停的目标文件夹整行高亮（比选中态更深的蓝，明确"放到这里"）
    const rowBg = isFolderDragOver
        ? "bg-[#bcd4ff] transition-colors duration-150"
        : isSelected
            ? "bg-[#E6EDFC] transition-colors duration-150 group-hover:bg-[#F8F8F8]"
            : "bg-white transition-colors duration-150 group-hover:bg-[#f7f7f7]";
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
            file.status === FileStatus.VIOLATION ||
            (isFolder && file.successFileNum !== undefined && file.fileNum !== undefined && file.successFileNum < file.fileNum)
        )
    );
    const showMoveItem = Boolean(onMove) && !isCreating;
    const showVersionManagement = versionManagementEnabled && !isFolder && file.status === FileStatus.SUCCESS && isAdmin && Boolean(onOpenVersionManagement);
    const showVersionHistory = versionManagementEnabled && !isFolder && Boolean(file.is_multi_version) && Boolean(onOpenVersionHistory);
    // Placeholder has only a temp id (no backend identity) — suppress all row actions.
    const showMoreMenu = !isUploadingFolderPlaceholder && (canDownload || isAdmin || canRename || canDelete || Boolean(onManagePermission) || showMoveItem || showVersionManagement || showVersionHistory);
    const namePreviewable = isKnowledgeItemPreviewable(file);
    const [rowHovered, setRowHovered] = useState(false);
    const showRowActions = (rowHovered || moreMenuOpen) && !isUploadingFolderPlaceholder;
    const rowActions = (
        <div
            className="absolute right-3 top-1/2 z-[35] flex -translate-y-1/2 items-center gap-1"
        >
            {canDownload && (
                <button
                    type="button"
                    className={FILE_ROW_ACTION_BTN_CLASS}
                    onClick={(e) => {
                        e.stopPropagation();
                        onDownload();
                    }}
                    title={localize("com_knowledge.download")}
                >
                    <Outlined.Download className="size-4" />
                </button>
            )}
            {showMoreMenu && (
                <DropdownMenu open={moreMenuOpen} onOpenChange={handleMoreMenuOpenChange}>
                    <DropdownMenuTrigger asChild>
                        <button type="button" className={FILE_ROW_ACTION_BTN_CLASS}>
                            <Outlined.More className="size-4" />
                        </button>
                    </DropdownMenuTrigger>
                    <ActionMenuContent align="end">
                        {isAdmin && !isFolder && (
                            <ActionMenuItem
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onEditTags();
                                }}
                                icon={<Outlined.Tag />}
                                label={localize("com_knowledge.edit_tags")}
                            />
                        )}
                        {canRename && (
                            <ActionMenuItem
                                onClick={(e) => {
                                    e.stopPropagation();
                                    startRenaming();
                                }}
                                icon={<Outlined.Edit />}
                                label={localize("com_knowledge.rename")}
                            />
                        )}
                        {showMoveItem && (
                            <ActionMenuItem
                                disabled={!canMove || isUploading}
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onMove?.();
                                }}
                                icon={<Outlined.MoveToFolder />}
                                label={localize("com_knowledge.move")}
                            />
                        )}
                        {isAdmin && hasRetryOption && (
                            <ActionMenuItem
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onRetry?.();
                                }}
                                icon={<Outlined.Refresh />}
                                label={localize("com_knowledge.retry")}
                            />
                        )}
                        {onManagePermission && (
                            <ActionMenuItem
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onManagePermission();
                                }}
                                icon={<Outlined.PeopleSafe />}
                                label={localize("com_permission.manage_permission")}
                            />
                        )}
                        {showVersionManagement && (
                            <ActionMenuItem
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onOpenVersionManagement?.(file);
                                }}
                                icon={<GitBranch />}
                                label={localize("com_knowledge.version.menu_version_management")}
                            />
                        )}
                        {showVersionHistory && (
                            <ActionMenuItem
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onOpenVersionHistory?.(file);
                                }}
                                icon={<History />}
                                label={localize("com_knowledge.version.menu_version_history")}
                            />
                        )}
                        {canDelete && (
                            <ActionMenuItem
                                danger
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onDelete();
                                }}
                                icon={<Outlined.Delete />}
                                label={localize("com_knowledge.delete")}
                            />
                        )}
                    </ActionMenuContent>
                </DropdownMenu>
            )}
        </div>
    );

    return (
        <TableRow
            data-knowledge-file-item
            draggable={rowDraggable && !isCreating && !isRenaming && !isUploading}
            onDragStart={rowDraggable ? onRowDragStart : undefined}
            onDragOver={isFolder && !isUploadingFolderPlaceholder ? onFolderDragOver : undefined}
            onDragLeave={isFolder && !isUploadingFolderPlaceholder ? onFolderDragLeave : undefined}
            onDrop={isFolder && !isUploadingFolderPlaceholder ? onFolderDrop : undefined}
            className={cn(
                // border-separate on the table means <tr>.border-b doesn't paint —
                // push the row separator onto each direct <td> instead.
                "group [&>td]:border-b [&>td]:border-[#e5e6eb]",
                // 取消 Table 默认 tr:hover 底色，整行颜色只由单元格 rowBg + group-hover 控制
                "bg-transparent hover:bg-transparent"
            )}
            onMouseEnter={() => setRowHovered(true)}
            onMouseLeave={() => setRowHovered(false)}
        >
            {/* 复选框 — 左侧固定 */}
            <TableCell
                className={cn("sticky left-0 z-10 px-0 py-3 text-center", rowBg)}
                style={{ width: columnWidths.checkbox, minWidth: columnWidths.checkbox, maxWidth: columnWidths.checkbox }}
            >
                <div className="flex items-center justify-center">
                    <Checkbox
                        checked={isSelected}
                        onCheckedChange={onSelect}
                        disabled={isUploadingFolderPlaceholder}
                        className={cn(
                            "size-4 border-gray-400",
                            isSelected && "border-primary",
                            isUploadingFolderPlaceholder && "cursor-not-allowed opacity-50",
                        )}
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
                    <div className={cn(
                        "flex size-4 shrink-0 items-center justify-center",
                        namePreviewable ? "text-[#212121]" : "text-[#999]",
                        isUploadingFolderPlaceholder && "opacity-50",
                    )}>
                        {isFolder
                            ? <Outlined.FolderClose className="size-[14px]" />
                            : (['png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp'].includes(file.name.split('.').pop()?.toLowerCase() || "")
                                ? <Outlined.FileImage className="size-[14px]" />
                                : <Outlined.File className="size-[14px]" />)
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
                            className="flex-1 h-7 px-2 text-sm border border-[#DDDDDD] rounded outline-none shadow-[0_0_0_2px_#F1F5F9] bg-white font-normal text-[#1d2129]"
                        />
                    ) : (
                        <>
                            {versionManagementEnabled && file.is_multi_version && file.version_no != null && file.version_no >= 1 && (
                                <span className="flex h-5 shrink-0 items-center justify-center rounded bg-[#E8F3FF] px-1.5 text-xs font-medium text-[#165DFF]">
                                    {`V${file.version_no}`}
                                </span>
                            )}
                            <span
                                className={cn(
                                    "text-sm truncate flex-1",
                                    namePreviewable && !isUploadingFolderPlaceholder
                                        ? "cursor-pointer text-[#212121] hover:text-[#4080FF]"
                                        : "cursor-default text-[#999]",
                                    isUploadingFolderPlaceholder && "opacity-50",
                                )}
                                onClick={(e) => {
                                    e.stopPropagation();
                                    if (isUploadingFolderPlaceholder) return;
                                    if (isFolder) {
                                        onNavigateFolder?.();
                                        return;
                                    }
                                    if (!namePreviewable) return;
                                    onPreview?.();
                                }}
                            >
                                <span className="block truncate">{renderHighlightedName(file.name, highlightKeyword)}</span>
                            </span>
                        </>
                    )}
                    {/* Inline status tag — non-folder files in any non-success state,
                        plus the uploading-folder placeholder ("上传中"). */}
                    {file.status && ((!isFolder && file.status !== FileStatus.SUCCESS) || isUploadingFolderPlaceholder) && (
                        <StatusBadge status={file.status} file={file} />
                    )}
                    {/* Similar-document tag — occupies the same slot as the status tag
                        (mutually exclusive: it only shows on SUCCESS files, the status tag
                        only on non-success). */}
                    {versionManagementEnabled && canManageMembers && file.has_similar && !file.is_multi_version && file.status === FileStatus.SUCCESS && (
                        <button
                            type="button"
                            onClick={(e) => {
                                e.stopPropagation();
                                onOpenVersionManagement?.(file);
                            }}
                            className="flex h-5 shrink-0 items-center gap-1 rounded bg-[#FFF3E8] px-1.5 text-xs text-[#F76F44] hover:bg-[#FFE6D2]"
                        >
                            <FileSearch className="size-3" />
                            {localize("com_knowledge.version.pill_similar")}
                        </button>
                    )}
                </div>
                {/* 固定列右侧阴影 */}
                <StickyColumnShadow show={showLeftShadow} />
            </TableCell>

            {/* 类型 */}
            <TableCell
                className={cn("py-3 text-sm text-[#86909c]", rowBg)}
                style={{ width: columnWidths.fileType, minWidth: columnWidths.fileType, maxWidth: columnWidths.fileType }}
            >
                <span className={cn("truncate block", isUploadingFolderPlaceholder && "opacity-50")}>
                    {isFolder ? localize("com_knowledge.folder") : (file.name.split('.').pop()?.toLowerCase() || "--")}
                </span>
            </TableCell>

            {/* 大小 — 单元格右对齐，与表头一致 */}
            <TableCell
                className={cn("py-3 text-right text-sm text-[#86909c]", rowBg)}
                style={{ width: columnWidths.size, minWidth: columnWidths.size, maxWidth: columnWidths.size }}
            >
                <span className={cn("block truncate", isUploadingFolderPlaceholder && "opacity-50")}>
                    {isFolder ? "--" : (file.size ? formatBytes(file.size, 2, true) : "--")}
                </span>
            </TableCell>

            {/* 标签 — 行悬停时显示编辑（管理员、非文件夹） */}
            <TableCell
                className={cn("py-3", rowBg)}
                style={{ width: columnWidths.tags, minWidth: columnWidths.tags, maxWidth: columnWidths.tags }}
            >
                <div className="flex h-full w-full items-center gap-1.5 overflow-hidden">
                    {!isFolder && (
                        <TagGroup
                            tags={file.tags}
                            highlightedTagIds={highlightedTagIds}
                            actionButton={
                                isAdmin ? (
                                    <button
                                        type="button"
                                        title={localize("com_knowledge.edit_tags")}
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            onEditTags();
                                        }}
                                        className="hidden cursor-pointer items-center justify-center text-[#212121] transition-colors hover:text-[#4080FF] group-hover:flex"
                                    >
                                        <Outlined.Edit className="size-3.5" />
                                    </button>
                                ) : undefined
                            }
                        />
                    )}
                </div>
            </TableCell>

            {/* 文件编码 — 仅 shougang 模式显示 */}
            {shougangEnabled && (
                <TableCell
                    style={{
                        width: columnWidths.fileEncoding,
                        minWidth: columnWidths.fileEncoding,
                        maxWidth: columnWidths.fileEncoding,
                    }}
                    className={cn("py-3", rowBg)}
                >
                    <div className="flex h-full w-full items-center gap-1.5 overflow-hidden">
                        {file.status === FileStatus.PROCESSING && !file.fileEncoding ? (
                            <span className="text-muted-foreground italic text-sm">
                                {localize("com_knowledge.file_encoding_generating")}
                            </span>
                        ) : file.fileEncoding ? (
                            <>
                                <span className="truncate text-sm text-[#86909c]" title={file.fileEncoding}>
                                    {file.fileEncoding}
                                </span>
                                {canEditEncoding && (
                                    <button
                                        type="button"
                                        title={localize("com_knowledge.file_encoding_edit_title")}
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            onEditEncoding?.(file);
                                        }}
                                        className="hidden cursor-pointer items-center justify-center text-[#212121] transition-colors hover:text-[#4080FF] group-hover:flex"
                                    >
                                        <Outlined.Edit className="size-3.5" />
                                    </button>
                                )}
                            </>
                        ) : (
                            <span className="text-muted-foreground">—</span>
                        )}
                    </div>
                </TableCell>
            )}

            {/* 更新时间 — 操作按钮改到行末占位列，避免盖住文字 */}
            <TableCell
                className={cn("relative overflow-visible py-3 text-sm text-[#86909c]", rowBg)}
                style={{ width: columnWidths.updateTime, minWidth: columnWidths.updateTime, maxWidth: columnWidths.updateTime }}
            >
                <span className={cn("block truncate whitespace-nowrap", isUploadingFolderPlaceholder && "opacity-50")}>{formatTime(file.updatedAt)}</span>
            </TableCell>

            {/* Status column removed; non-success pills now render inline next to the file name. */}
            {/* 行末锚点：固定在可视区最右侧，按钮距右侧 12px，不受横向滚动影响 */}
            <TableCell
                className="sticky right-0 z-[34] overflow-visible border-none bg-transparent p-0"
                style={{ width: 0, minWidth: 0, maxWidth: 0 }}
            >
                <StickyColumnShadowRight show={showRightShadow} />
                {showRowActions && rowActions}
            </TableCell>
        </TableRow>
    );
}
