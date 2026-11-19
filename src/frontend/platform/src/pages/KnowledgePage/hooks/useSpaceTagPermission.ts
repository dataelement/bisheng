import { useQuery } from "@tanstack/react-query";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";

export interface SpaceTagPermission {
  status: "checking" | "allowed" | "restricted" | "unavailable";
  retry: () => void;
}

/** File tag assignments and the space-wide tag dictionary have different owners. */
export function useSpaceTagPermission(scope: KnowledgeQueryScope, spaceId: number, open: boolean): SpaceTagPermission {
  const permission = useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "tag-management-actions"],
    queryFn: () => getMyResourcePermissionsApi("knowledge_space", String(spaceId), { showError: false }),
    enabled: open,
    cacheTime: 0,
    staleTime: 0,
    retry: false,
    keepPreviousData: false,
  });
  return {
    status: permission.isFetching || !open ? "checking"
      : permission.isError ? "unavailable"
      : permission.isSuccess ? (permission.data.actions.includes("edit") ? "allowed" : "restricted")
      : "checking",
    retry: () => { void permission.refetch(); },
  };
}
