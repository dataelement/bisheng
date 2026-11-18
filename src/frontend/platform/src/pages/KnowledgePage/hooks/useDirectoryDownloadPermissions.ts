import { useQueries } from "@tanstack/react-query";
import { useEffect } from "react";
import { inspectBatchItems } from "@/controllers/API/knowledgeBatch";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import { showApiError } from "@/controllers/request";

interface DirectoryDownloadOptions {
  prefix: readonly unknown[];
  spaceId: number;
  pages: readonly { data: KnowledgeSpaceChild[] }[];
}

export function useDirectoryDownloadPermissions({ prefix, spaceId, pages }: DirectoryDownloadOptions) {
  const queries = useQueries({
    queries: pages.map((page, index) => {
      const items = page.data
        .filter((item) => item.file_type === 1)
        .map((item) => ({ id: item.id, type: "file" as const }));
      return {
        queryKey: [...prefix, "download-permissions", index, page],
        queryFn: () => inspectBatchItems({ spaceId, operation: "download", items }),
        enabled: items.length > 0,
        staleTime: Infinity,
        cacheTime: 0,
        retry: false,
      };
    }),
  });
  const error = queries.find((query) => query.isError)?.error;
  useEffect(() => {
    if (error) showApiError(error);
  }, [error]);
  return new Set(
    queries.flatMap((query) =>
      query.isSuccess && query.data.check_complete
        ? query.data.valid_items.filter((item) => item.type === "file").map((item) => item.id)
        : [],
    ),
  );
}
