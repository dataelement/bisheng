import { useQueries } from "@tanstack/react-query";
import { useEffect } from "react";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import { showApiError } from "@/controllers/request";

interface DirectorySelectionActionsOptions {
  prefix: readonly unknown[];
  rows: KnowledgeSpaceChild[];
}

/** Match row-menu actions; mixed selections still go through the server review. */
export function useDirectorySelectionActions({ prefix, rows }: DirectorySelectionActionsOptions) {
  const queries = useQueries({
    queries: rows.map(item => ({
      queryKey: [...prefix, "selection-actions", item.file_type, item.id],
      queryFn: () => getMyResourcePermissionsApi(item.file_type === 0 ? "folder" : "knowledge_file", String(item.id)),
      retry: false,
      cacheTime: 0,
      keepPreviousData: false,
    })),
  });
  const error = queries.find(query => query.isError)?.error;
  useEffect(() => {
    if (error) showApiError(error);
  }, [error]);
  const has = (index: number, action: string) => {
    const query = queries[index];
    return query?.isSuccess && !query.isFetching && query.data?.actions?.includes(action) === true;
  };
  return {
    canMove: rows.some((_, index) => has(index, "move")),
    canDelete: rows.some((_, index) => has(index, "delete")),
    canDownload: rows.some((_, index) => has(index, "download")),
    canTag: rows.every(item => item.file_type === 1) && rows.some((item, index) =>
      has(index, "rename") && ![1, 5].includes(item.status ?? -1)),
    canRetry: rows.some((item, index) => has(index, "rename") && (
      item.file_type === 0 ? item.has_failed_files === true : [3, 6, 7].includes(item.status ?? -1)
    )),
  };
}
