import type { UseKnowledgeSelectionActionsOptions } from "./knowledgeSpaceTypes";
import {
  FileStatus,
  FileType,
  KnowledgeFile,
  SortDirection,
  SortType,
} from "~/api/knowledge";
import { isKnowledgeItemUploading } from "../knowledgeUtils";
import { SearchParams } from "./CompoundSearchInput";

export function useKnowledgeSelectionActions({
  displayFiles,
  setSearchQuery,
  setSearchTagIds,
  selectedFiles,
  setSelectedFiles,
  statusFilter,
  setStatusFilter,
  sortBy,
  setSortBy,
  sortDirection,
  setSortDirection,
  setPermTarget,
  onSearch,
  onFilterStatus,
  onSort,
}: UseKnowledgeSelectionActionsOptions) {
  const handleSearch = (params: SearchParams) => {
    setSearchQuery(params.keyword);
    setSearchTagIds(params.tagIds);
    setSelectedFiles(new Set());
    onSearch(params);
  };

  const handleStatusFilter = (status: FileStatus, checked: boolean) => {
    const newFilter = checked
      ? statusFilter.includes(status)
        ? statusFilter
        : [...statusFilter, status]
      : statusFilter.filter((s) => s !== status);
    setStatusFilter(newFilter);
    onFilterStatus(newFilter);
  };

  const handleSort = (newSortBy: SortType) => {
    const newDirection =
      sortBy === newSortBy && sortDirection === SortDirection.ASC
        ? SortDirection.DESC
        : SortDirection.ASC;
    setSortBy(newSortBy);
    setSortDirection(newDirection);
    onSort(newSortBy, newDirection);
  };

  // An uploading folder placeholder has only a temp id and no backend identity —
  // it must not be selectable (neither individually nor via select-all).
  const isFolderUploadPlaceholder = (f: KnowledgeFile) =>
    f.type === FileType.FOLDER && isKnowledgeItemUploading(f);

  const handleSelectFile = (fileId: string, selected: boolean) => {
    const target = displayFiles.find((f) => f.id === fileId);
    if (target && isFolderUploadPlaceholder(target)) return;
    const newSelected = new Set(selectedFiles);
    if (selected) {
      newSelected.add(fileId);
    } else {
      newSelected.delete(fileId);
    }
    setSelectedFiles(newSelected);
  };

  const handleManagePermission = (fileId: string) => {
    const target = displayFiles.find((file) => file.id === fileId);
    if (!target) {
      return;
    }

    setPermTarget({
      id: target.id,
      name: target.name,
      type: target.type === FileType.FOLDER ? "folder" : "knowledge_file",
    });
  };

  const handleSelectAll = (isAllSelectedOnPage: boolean) => {
    const newSelected = new Set(selectedFiles);
    // Skip uploading folder placeholders so select-all never picks them up.
    const selectable = displayFiles.filter(
      (f) => !isFolderUploadPlaceholder(f),
    );
    if (isAllSelectedOnPage) {
      selectable.forEach((f) => newSelected.delete(f.id));
    } else {
      selectable.forEach((f) => newSelected.add(f.id));
    }
    setSelectedFiles(newSelected);
  };

  return {
    handleSearch,
    handleStatusFilter,
    handleSort,
    isFolderUploadPlaceholder,
    handleSelectFile,
    handleManagePermission,
    handleSelectAll,
  };
}
