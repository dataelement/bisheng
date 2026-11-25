import { useQuery } from "@tanstack/react-query";
import { knowledgeFilesApi } from "@/controllers/API/knowledgeFiles";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";

import { useSpaceDeletionActive } from "@/store/knowledgeSpaceDeletion";

export function useSpaceFolderPath(
  scope: KnowledgeQueryScope,
  spaceId?: number,
  folderId?: number | null,
) {
  const deleting = useSpaceDeletionActive(scope, spaceId ?? 0);
  return useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId ?? 0), "navigation-path", folderId],
    queryFn: ({ signal }) => knowledgeFilesApi.listSpaceFolderParents(spaceId!, folderId!, signal),
    enabled: !deleting && spaceId !== undefined && folderId != null,
    // The tree and breadcrumb share this read. Retire it when both leave the folder.
    cacheTime: 0,
    keepPreviousData: false,
    refetchOnMount: false,
    retry: false,
  });
}
