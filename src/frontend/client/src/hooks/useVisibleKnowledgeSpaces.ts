import { useMemo, useRef } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  getVisibleSpacesPageApi,
  getVisibleSpacesTenant,
} from "~/api/knowledgeVisible";
import { useAuthContext } from "./AuthContext";

let nextCredentialScope = 0;

/** A credential change gets a fresh cache scope without placing a JWT in query keys. */
export function useVisibleKnowledgeSpaces({
  enabled = true,
  keyword = "",
}: {
  enabled?: boolean;
  keyword?: string;
} = {}) {
  const { user, token, isAuthenticated } = useAuthContext();
  const userId = user?.id;
  const credentialScope = useMemo(
    () => (userId != null && token ? ++nextCredentialScope : 0),
    [userId, token],
  );
  const active = enabled && isAuthenticated && userId != null && !!token;
  const tenant = useQuery({
    queryKey: ["visible-space-tenant", userId, credentialScope],
    queryFn: ({ signal }) => getVisibleSpacesTenant(signal),
    enabled: active,
    cacheTime: 0,
    staleTime: 0,
    retry: false,
  });
  const query = useInfiniteQuery({
    queryKey: [
      "visible-space-candidates",
      userId,
      tenant.data,
      credentialScope,
      keyword.trim(),
    ],
    queryFn: ({ pageParam, signal }) =>
      getVisibleSpacesPageApi({ cursor: pageParam, keyword, signal }),
    getNextPageParam: (page) => (page.has_more ? page.next_cursor : undefined),
    enabled: active && tenant.isSuccess,
    cacheTime: 0,
    staleTime: 0,
    retry: false,
  });
  // v4 does not expose isFetchNextPageError; remember the actual failed operation.
  const paging = useRef({ key: "", failed: false });
  const pagingKey = JSON.stringify([
    credentialScope,
    tenant.data,
    keyword.trim(),
  ]);
  if (paging.current.key !== pagingKey)
    paging.current = { key: pagingKey, failed: false };
  const loadNext = async () => {
    if (!active || query.isFetching || !query.hasNextPage) return;
    const current = paging.current;
    const result = await query.fetchNextPage();
    current.failed = result.isError;
  };
  const spaces = useMemo(() => {
    const seen = new Set<string>();
    return (query.data?.pages ?? [])
      .flatMap((page) => page.data)
      .filter((space) => {
        if (seen.has(space.id)) return false;
        seen.add(space.id);
        return true;
      });
  }, [query.data]);
  return {
    spaces: active && tenant.isSuccess ? spaces : [],
    isFetching: active && (tenant.isFetching || query.isFetching),
    isError: tenant.isError || query.isError,
    hasMore: active && tenant.isSuccess && !!query.hasNextPage,
    loadMore: () => {
      void loadNext();
    },
    retry: () =>
      tenant.isError
        ? tenant.refetch()
        : paging.current.failed
          ? loadNext()
          : query.refetch(),
  };
}
