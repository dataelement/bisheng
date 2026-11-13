import { useInfiniteQuery } from "@tanstack/react-query";
import {
  knowledgeSpaceApi,
  type KnowledgeSpaceInfo,
} from "@/controllers/API/knowledgeSpace";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";

/** Search ordinary visibility or page the trusted management catalog, never mix them. */
export function useSpaceCatalog(
  scope: KnowledgeQueryScope,
  keyword: string,
  enabled: boolean,
) {
  return useInfiniteQuery({
    queryKey: [
      ...knowledgeQueryKeys.scope(scope),
      "navigation-catalog",
      keyword,
    ],
    queryFn: async ({
      pageParam,
      signal,
    }): Promise<{ data: KnowledgeSpaceInfo[]; next?: number | string }> => {
      if (signal?.aborted)
        throw new DOMException("Retired navigation read", "AbortError");
      if (scope.view === "admin") {
        const page = typeof pageParam === "number" ? pageParam : 1;
        const result = await knowledgeSpaceApi.listAdminSpaces({
          page,
          page_size: 200,
          ...(keyword ? { keyword } : {}),
        });
        if (result.total > page * 200 && !result.data.length)
          throw new Error("Invalid management space page");
        return {
          data: result.data,
          next: page * 200 < result.total ? page + 1 : undefined,
        };
      }
      const result = await knowledgeSpaceApi.listVisibleSpaces({
        page_size: 200,
        ...(keyword ? { keyword } : {}),
        ...(typeof pageParam === "string" ? { cursor: pageParam } : {}),
      });
      if (
        result.has_more &&
        (!result.next_cursor || result.next_cursor === pageParam)
      )
        throw new Error("Invalid visible space cursor");
      return {
        data: result.data,
        next: result.has_more ? (result.next_cursor ?? undefined) : undefined,
      };
    },
    getNextPageParam: (page) => page.next,
    enabled,
    staleTime: 30_000,
    cacheTime: 0,
    retry: false,
  });
}
