import { Outlined } from "bisheng-icons";

import { FileStatus, SortDirection, SortType } from "~/api/knowledge";
import { Checkbox } from "~/components";
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import { knowledgeSpaceDropdownSurfaceClassName } from "~/components/SidebarListMoreMenu";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import { PENDING_REVIEW_FILTER, type FileStatusFilter } from "../knowledgeUtils";
import { CompoundSearchInput, type SearchParams } from "./CompoundSearchInput";

/**
 * Toolbar shared by the list and card views (Figma 13198:75844).
 *
 * The old table carried its own sortable column headers; the list view has no
 * headers at all, so sorting, filtering, search and the view toggle all live
 * here — one 44px bar that stays identical in both view modes.
 */

/** Ghost icon+label button, 28px tall (Figma 13198:75851). */
const TOOLBAR_BUTTON_CLASS =
    "inline-flex h-7 shrink-0 items-center gap-1 rounded-md px-[5px] text-sm text-text-2 transition-colors hover:bg-fill-1";

function ToolbarDivider() {
    return <span aria-hidden className="mx-2 h-2 w-px shrink-0 bg-[#ededed]" />;
}

/** Status options, in the order the filter menu lists them (Figma 13198:78111). */
const STATUS_FILTER_OPTIONS: Array<{ value: FileStatusFilter; labelKey: string }> = [
    { value: PENDING_REVIEW_FILTER, labelKey: "com_knowledge.pending_review_status" },
    { value: FileStatus.UPLOADING, labelKey: "com_knowledge.uploading_status" },
    { value: FileStatus.WAITING, labelKey: "com_knowledge.queueing_status" },
    { value: FileStatus.PROCESSING, labelKey: "com_knowledge.parsing_status" },
    { value: FileStatus.REBUILDING, labelKey: "com_knowledge.rebuilding_status" },
    { value: FileStatus.SUCCESS, labelKey: "com_knowledge.success" },
    { value: FileStatus.FAILED, labelKey: "com_knowledge.fail" },
    { value: FileStatus.TIMEOUT, labelKey: "com_knowledge.timeout" },
    { value: FileStatus.VIOLATION, labelKey: "com_knowledge.violation" },
];

const SORT_OPTIONS: Array<{ value: SortType; labelKey: string }> = [
    { value: SortType.NAME, labelKey: "com_knowledge.sort_by_name_label" },
    { value: SortType.TYPE, labelKey: "com_knowledge.sort_by_type_label" },
    { value: SortType.SIZE, labelKey: "com_knowledge.sort_by_size_label" },
    { value: SortType.UPDATE_TIME, labelKey: "com_knowledge.sort_by_update_time_label" },
];

interface FileListToolbarProps {
    spaceId: string;
    isRoot: boolean;
    onSearch: (params: SearchParams) => void;
    statusFilter: FileStatusFilter[];
    onFilterStatus: (status: FileStatusFilter, checked: boolean) => void;
    /** Members don't get the status filter (they only ever see parsed files). */
    showFilter?: boolean;
    /** Only spaces with upload approval enabled can have pending-review rows. */
    showPendingReviewFilter?: boolean;
    sortBy: SortType | undefined;
    sortDirection: SortDirection | undefined;
    onSort: (sortBy: SortType) => void;
    viewMode: "card" | "list";
    setViewMode: (mode: "card" | "list") => void;
    showViewToggle?: boolean;
    isAllSelected: boolean;
    isIndeterminate: boolean;
    hasSelectableFiles: boolean;
    onSelectAll: () => void;
}

export function FileListToolbar({
    spaceId,
    isRoot,
    onSearch,
    statusFilter,
    onFilterStatus,
    showFilter = true,
    showPendingReviewFilter = false,
    sortBy,
    sortDirection,
    onSort,
    viewMode,
    setViewMode,
    showViewToggle = true,
    isAllSelected,
    isIndeterminate,
    hasSelectableFiles,
    onSelectAll,
}: FileListToolbarProps) {
    const localize = useLocalize();
    const filterActive = statusFilter.length > 0;
    const statusOptions = showPendingReviewFilter
        ? STATUS_FILTER_OPTIONS
        : STATUS_FILTER_OPTIONS.filter((option) => option.value !== PENDING_REVIEW_FILTER);

    return (
        <div
            className={cn(
                "flex h-11 shrink-0 items-center gap-2 px-4",
                // The grey band reads as the list's header row, so it only applies
                // in list mode; over the card grid the toolbar sits on the page.
                viewMode === "list" && "bg-[#fafafa]",
            )}
        >
            <Checkbox
                aria-label={localize("com_knowledge.select_all")}
                className="border-border-deep data-[state=checked]:border-primary data-[state=indeterminate]:border-primary"
                checked={isIndeterminate ? "indeterminate" : isAllSelected}
                disabled={!hasSelectableFiles}
                onCheckedChange={onSelectAll}
            />

            <div className="ml-auto flex min-w-0 items-center">
                <CompoundSearchInput
                    collapsible
                    toolbarMode
                    spaceId={spaceId}
                    isRoot={isRoot}
                    onSearch={onSearch}
                />

                {showFilter && (
                    <>
                        <ToolbarDivider />
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <button
                                    type="button"
                                    className={cn(TOOLBAR_BUTTON_CLASS, filterActive && "text-blue-500")}
                                >
                                    <Outlined.Filter className="size-4 shrink-0" />
                                    {localize("com_knowledge.filter")}
                                </button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className={knowledgeSpaceDropdownSurfaceClassName}>
                                <div className="px-2 py-1.5 text-xs font-medium text-text-3">
                                    {localize("com_knowledge.filter_file_status")}
                                </div>
                                {statusOptions.map((option) => (
                                    <DropdownMenuCheckboxItem
                                        key={option.value}
                                        checked={statusFilter.includes(option.value)}
                                        onCheckedChange={(checked) => onFilterStatus(option.value, checked)}
                                        onSelect={(e) => e.preventDefault()}
                                    >
                                        {localize(option.labelKey)}
                                    </DropdownMenuCheckboxItem>
                                ))}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </>
                )}

                <ToolbarDivider />
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <button type="button" className={TOOLBAR_BUTTON_CLASS}>
                            <Outlined.Sort className="size-4 shrink-0" />
                            {localize("com_knowledge.sort")}
                        </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className={knowledgeSpaceDropdownSurfaceClassName}>
                        <div className="px-2 py-1.5 text-xs font-medium text-text-3">
                            {localize("com_knowledge.sort_field")}
                        </div>
                        {SORT_OPTIONS.map((option) => (
                            <DropdownMenuItem key={option.value} onClick={() => onSort(option.value)}>
                                {localize(option.labelKey)}
                                {sortBy === option.value && (sortDirection === SortDirection.ASC ? " ↑" : " ↓")}
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuContent>
                </DropdownMenu>

                {showViewToggle && (
                    <>
                        <ToolbarDivider />
                        <button
                            type="button"
                            className={TOOLBAR_BUTTON_CLASS}
                            onClick={() => setViewMode(viewMode === "list" ? "card" : "list")}
                        >
                            {/* Reads as a state label, not an action: it names the view
                                you are in, while clicking switches to the other one. */}
                            {viewMode === "list" ? (
                                <Outlined.List className="size-4 shrink-0" />
                            ) : (
                                <Outlined.ViewGridCard className="size-4 shrink-0" />
                            )}
                            {viewMode === "list"
                                ? localize("com_knowledge.list_view")
                                : localize("com_knowledge.card_view")}
                        </button>
                    </>
                )}
            </div>
        </div>
    );
}
