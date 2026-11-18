import { Button, Checkbox, Dropdown, DropdownGroup, DropdownItem, SearchInput } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useEffect, useRef, useState, type ComponentProps } from "react";
import { useTranslation } from "react-i18next";
import type { KnowledgeChildrenQuery } from "@/controllers/API/knowledgeSpace";
import { FileStatusFilter } from "./FileStatusFilter";
import { SPACE_FILE_CHECKBOX_CLASS } from "./spaceFileSelectionStyles";

export type DirectorySortField = NonNullable<KnowledgeChildrenQuery["order_field"]>;
export type DirectoryViewMode = "list" | "card";

interface SpaceDirectoryBrowseToolbarProps {
  viewMode: DirectoryViewMode;
  onViewModeChange: (mode: DirectoryViewMode) => void;
  sortField: DirectorySortField;
  sortDirection: "asc" | "desc";
  onSort: (field: DirectorySortField) => void;
  keyword: string;
  onKeywordChange: (value: string) => void;
  allSelected: boolean;
  someSelected: boolean;
  canSelect: boolean;
  onSelectAll: (checked: boolean) => void;
  filter: ComponentProps<typeof FileStatusFilter>;
}

const TOOLBAR_BUTTON_CLASS =
  "h-7 shrink-0 gap-1 rounded-md px-[5px] text-sm text-text-2 hover:bg-fill-1";

const SORT_OPTIONS = [
  { field: "file_name", key: "sort_name" },
  { field: "file_type", key: "sort_type" },
  { field: "file_size", key: "sort_size" },
  { field: "update_time", key: "sort_time" },
] as const;

function ToolbarDivider() {
  return <span aria-hidden className="mx-2 h-2 w-px shrink-0 bg-[#ededed] dark:bg-border-base" />;
}

export function SpaceDirectoryBrowseToolbar({
  viewMode,
  onViewModeChange,
  sortField,
  sortDirection,
  onSort,
  keyword,
  onKeywordChange,
  allSelected,
  someSelected,
  canSelect,
  onSelectAll,
  filter,
}: SpaceDirectoryBrowseToolbarProps) {
  const { t } = useTranslation("knowledge");
  const [searchActive, setSearchActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const searchButtonRef = useRef<HTMLButtonElement>(null);
  const restoreSearchFocus = useRef(false);
  const searchExpanded = searchActive || keyword.length > 0;
  const nextMode = viewMode === "list" ? "card" : "list";

  useEffect(() => {
    if (searchActive) inputRef.current?.focus();
    if (!searchExpanded && restoreSearchFocus.current) {
      restoreSearchFocus.current = false;
      searchButtonRef.current?.focus();
    }
  }, [searchActive, searchExpanded]);

  return (
    <div className={`flex min-h-11 shrink-0 items-center gap-2 px-4 ${viewMode === "list" ? "bg-[#fafafa] dark:bg-fill-1" : ""}`}>
      <Checkbox
        aria-label={t("workspace.select_all")}
        className={SPACE_FILE_CHECKBOX_CLASS}
        checked={someSelected && !allSelected ? "indeterminate" : allSelected}
        disabled={!canSelect}
        onCheckedChange={(checked) => onSelectAll(checked === true)}
      />
      <div className="ml-auto flex min-w-0 items-center">
        {searchExpanded ? (
          <div
            className="min-w-0"
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) setSearchActive(false);
            }}
          >
            <SearchInput
              ref={inputRef}
              aria-label={t("searchFileName")}
              placeholder={t("searchFileName")}
              clearLabel={t("workspace.clear_search")}
              className="w-[340px] max-w-full"
              inputClassName="text-[13px]"
              value={keyword}
              onFocus={() => setSearchActive(true)}
              onChange={(event) => onKeywordChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Escape" || event.nativeEvent.isComposing || keyword) return;
                event.preventDefault();
                restoreSearchFocus.current = true;
                setSearchActive(false);
              }}
            />
          </div>
        ) : (
          <Button
            ref={searchButtonRef}
            type="button"
            variant="text"
            color="default"
            icon={<Outlined.Search aria-hidden />}
            className={TOOLBAR_BUTTON_CLASS}
            onClick={() => setSearchActive(true)}
          >
            {t("search", { ns: "bs" })}
          </Button>
        )}
        <ToolbarDivider />
        <FileStatusFilter
          {...filter}
          trigger={
            <Button
              type="button"
              variant="text"
              color="default"
              icon={<Outlined.Filter aria-hidden />}
              className={`${TOOLBAR_BUTTON_CLASS} ${filter.selected.length ? "text-blue-500" : ""}`}
            >
              {t("workspace.filter")}
            </Button>
          }
        />
        <ToolbarDivider />
        <Dropdown
          align="end"
          menu={
            <DropdownGroup label={t("workspace.sort_field")}>
              {SORT_OPTIONS.map((option) => (
                <DropdownItem
                  key={option.field}
                  onSelect={() => onSort(option.field)}
                  shortcut={sortField === option.field && (
                    <span className="flex size-4 items-center justify-center text-primary">
                      {sortDirection === "asc" ? <Outlined.ArrowUp /> : <Outlined.ArrowDown />}
                    </span>
                  )}
                >
                  {t(`workspace.${option.key}`)}
                </DropdownItem>
              ))}
            </DropdownGroup>
          }
        >
          <Button type="button" variant="text" color="default" icon={<Outlined.Sort aria-hidden />} className={TOOLBAR_BUTTON_CLASS}>
            {t("workspace.sort")}
          </Button>
        </Dropdown>
        <ToolbarDivider />
        <Button
          type="button"
          variant="text"
          color="default"
          icon={viewMode === "list" ? <Outlined.List aria-hidden /> : <Outlined.ViewGridCard aria-hidden />}
          className={TOOLBAR_BUTTON_CLASS}
          aria-label={t(`workspace.${nextMode}_view`)}
          onClick={() => onViewModeChange(nextMode)}
        >
          {t(`workspace.${viewMode}_view`)}
        </Button>
      </div>
    </div>
  );
}
