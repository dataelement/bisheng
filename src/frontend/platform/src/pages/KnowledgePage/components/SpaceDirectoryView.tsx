import {
  Button,
  Checkbox,
  Dropdown,
  DropdownItem,
  SearchInput,
} from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import type { ComponentProps, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table";
import type {
  KnowledgeChildrenQuery,
  KnowledgeSpaceChild,
} from "@/controllers/API/knowledgeSpace";
import { FileStatusFilter } from "./FileStatusFilter";

export type DirectorySortField = NonNullable<
  KnowledgeChildrenQuery["order_field"]
>;
export type DirectoryViewMode = "list" | "card";

interface SpaceDirectoryViewProps {
  workspace: boolean;
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
  rows: KnowledgeSpaceChild[];
  renderRow: (
    item: KnowledgeSpaceChild,
    layout?: DirectoryViewMode,
  ) => ReactNode;
}

const SORT_OPTIONS = [
  { field: "file_name", key: "sort_name" },
  { field: "update_time", key: "sort_time" },
  { field: "file_size", key: "sort_size" },
  { field: "file_type", key: "sort_type" },
] as const;

/** Presentation adapted from the former client FileListView and FileListToolbar. */
export function SpaceDirectoryView({
  workspace,
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
  rows,
  renderRow,
}: SpaceDirectoryViewProps) {
  const { t } = useTranslation("knowledge");
  if (!workspace)
    return (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("fileName")}</TableHead>
            <TableHead>{t("updateTime")}</TableHead>
            <TableHead>
              <span className="inline-flex items-center gap-1">
                {t("status")}
                <FileStatusFilter {...filter} />
              </span>
            </TableHead>
            <TableHead className="text-right">{t("operations")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>{rows.map((item) => renderRow(item))}</TableBody>
      </Table>
    );
  const nextMode = viewMode === "list" ? "card" : "list";
  return (
    <div className="min-w-0">
      <div
        className={`flex min-h-11 flex-wrap items-center gap-2 rounded-t-md px-4 py-1 ${viewMode === "list" ? "bg-fill-1" : ""}`}
      >
        <Checkbox
          aria-label={t("workspace.select_all")}
          checked={someSelected && !allSelected ? "indeterminate" : allSelected}
          disabled={!canSelect}
          onCheckedChange={(checked) => onSelectAll(checked === true)}
        />
        <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-2">
          <SearchInput
            aria-label={t("searchFileName")}
            placeholder={t("searchFileName")}
            className="w-48 max-w-full"
            value={keyword}
            onChange={(event) => onKeywordChange(event.target.value)}
          />
          <FileStatusFilter {...filter} />
          <Dropdown
            align="end"
            menu={SORT_OPTIONS.map((option) => (
              <DropdownItem
                key={option.field}
                onSelect={() => onSort(option.field)}
                shortcut={
                  sortField === option.field ? (
                    sortDirection === "asc" ? (
                      <Outlined.ArrowUp />
                    ) : (
                      <Outlined.ArrowDown />
                    )
                  ) : undefined
                }
              >
                {t(`workspace.${option.key}`)}
              </DropdownItem>
            ))}
          >
            <Button
              variant="text"
              color="default"
              icon={<Outlined.Sort />}
              aria-label={t("workspace.sort")}
            >
              {t("workspace.sort")}
            </Button>
          </Dropdown>
          <span aria-hidden className="mx-1 h-3 w-px bg-border-base" />
          <Button
            variant="text"
            color="default"
            icon={
              viewMode === "list" ? (
                <Outlined.List />
              ) : (
                <Outlined.ViewGridCard />
              )
            }
            aria-label={t(`workspace.${nextMode}_view`)}
            onClick={() => onViewModeChange(nextMode)}
          >
            {t(`workspace.${viewMode}_view`)}
          </Button>
        </div>
      </div>
      <div
        className={
          viewMode === "card"
            ? "grid grid-cols-[repeat(auto-fill,minmax(min(100%,168px),1fr))] gap-4 p-4"
            : "flex flex-col"
        }
        data-view-mode={viewMode}
      >
        {rows.map((item) => renderRow(item, viewMode))}
      </div>
    </div>
  );
}
