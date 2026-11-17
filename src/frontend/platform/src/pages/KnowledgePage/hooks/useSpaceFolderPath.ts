import { useQuery } from "@tanstack/react-query";
import { knowledgeFilesApi } from "@/controllers/API/knowledgeFiles";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";

export function useSpaceFolderPath(
  scope: KnowledgeQueryScope,
  spaceId?: number,
  folderId?: number | null,
) {
  return useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId ?? 0), "navigation-path", folderId],
    queryFn: ({ signal }) => knowledgeFilesApi.listSpaceFolderParents(spaceId!, folderId!, signal),
    enabled: spaceId !== undefined && folderId != null,
    // The tree and breadcrumb share this read. Retire it when both leave the folder.
    cacheTime: 0,
    keepPreviousData: false,
    refetchOnMount: false,
    retry: false,
  });
}
