import { Outlined } from "bisheng-icons";

import { FileStatus, SortDirection, SortType } from "~/api/knowledge";
import { Checkbox } from "~/components";
import {
    DropdownMenu,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import {
    ActionMenuCheckboxItem,
    ActionMenuContent,
    ActionMenuItem,
    actionMenuLabelClassName,
    actionMenuSectionLabelClassName,
} from "~/components/ActionMenu";
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
    // 待审核 is a permanent status-filter option so reviewers can always narrow
    // to pending-approval uploads, even when none are currently loaded in view.
    const statusOptions = STATUS_FILTER_OPTIONS;

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
                            {/* 120px wide, 8px padding, 32px rows spaced 4px apart, 12px
                                panel radius (Figma 13198:78111 — the dropdown-panel radius
                                the 圆角规范 calls for). Past 240px the list scrolls inside
                                instead of running down the viewport. */}
                            <ActionMenuContent
                                align="center"
                                width={120}
                                // min-w-0 is required: the shared content base sets
                                // min-w-[8rem] (128px), which would otherwise win over
                                // the 120px width.
                                className="max-h-[240px] min-w-0 gap-1 overflow-y-auto rounded-xl"
                            >
                                <div className={actionMenuSectionLabelClassName}>
                                    {localize("com_knowledge.filter_file_status")}
                                </div>
                                {statusOptions.map((option) => (
                                    <ActionMenuCheckboxItem
                                        key={option.value}
                                        checked={statusFilter.includes(option.value)}
                                        onCheckedChange={(checked) => onFilterStatus(option.value, checked)}
                                        onSelect={(e) => e.preventDefault()}
                                    >
                                        <span className={actionMenuLabelClassName}>
                                            {localize(option.labelKey)}
                                        </span>
                                    </ActionMenuCheckboxItem>
                                ))}
                            </ActionMenuContent>
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
                    {/* Same panel as the filter menu: 120px, centred on the trigger,
                        32px rows, 12px radius, scrolls past 240px. The active field's
                        direction sits in the trailing slot the filter uses for its check. */}
                    <ActionMenuContent
                        align="center"
                        width={120}
                        className="max-h-[240px] min-w-0 gap-1 overflow-y-auto rounded-xl"
                    >
                        <div className={actionMenuSectionLabelClassName}>
                            {localize("com_knowledge.sort_field")}
                        </div>
                        {SORT_OPTIONS.map((option) => (
                            <ActionMenuItem
                                key={option.value}
                                className="rounded-lg"
                                onClick={() => onSort(option.value)}
                            >
                                <span className={actionMenuLabelClassName}>
                                    {localize(option.labelKey)}
                                </span>
                                {sortBy === option.value && (
                                    <span className="ml-auto flex size-4 shrink-0 items-center justify-center text-primary">
                                        {sortDirection === SortDirection.ASC
                                            ? <Outlined.ArrowUp className="size-4" />
                                            : <Outlined.ArrowDown className="size-4" />}
                                    </span>
                                )}
                            </ActionMenuItem>
                        ))}
                    </ActionMenuContent>
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
