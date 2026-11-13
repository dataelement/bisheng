import { useQueries, useQuery } from "@tanstack/react-query";
import {
  knowledgeSpaceApi,
  type KnowledgeSpaceInfo,
} from "@/controllers/API/knowledgeSpace";
import {
  listNavigationSpaces,
  type SpaceSection,
} from "@/controllers/API/knowledgeSpaceNavigation";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";

import { useSpaceCatalog } from "./useSpaceCatalog";

const sections: SpaceSection[] = ["department", "created", "joined"];
function available(rows: KnowledgeSpaceInfo[], scope: KnowledgeQueryScope) {
  return rows.find(
    (row) =>
      Number.isSafeInteger(row.id) &&
      row.id > 0 &&
      (row.tenant_id == null || row.tenant_id === scope.tenantId),
  );
}
export function useInitialSpace(scope: KnowledgeQueryScope, enabled: boolean) {
  const admin = useSpaceCatalog(scope, "", enabled && scope.view === "admin");
  const groups = useQueries({
    queries: sections.map((section) => ({
      queryKey: [
        ...knowledgeQueryKeys.scope(scope),
        "navigation-sections",
        section,
        "update_time",
      ],
      queryFn: () => listNavigationSpaces(section, "update_time"),
      enabled: enabled && scope.view === "ordinary",
      retry: false,
      cacheTime: 0,
    })),
  });
  const ready = groups.every((query) => query.isSuccess);
  const first = ready
    ? groups.map((query) => available(query.data ?? [], scope)).find(Boolean)
    : undefined;
  // Child-only grants may be absent from the personal navigation groups.
  const fallback = useQuery({
    queryKey: [...knowledgeQueryKeys.scope(scope), "initial-visible-space"],
    queryFn: async ({ signal }) => {
      let cursor: string | undefined;
      const seen = new Set<string>();
      while (!signal?.aborted) {
        const page = await knowledgeSpaceApi.listVisibleSpaces({
          page_size: 1,
          ...(cursor ? { cursor } : {}),
        });
        const row = available(page.data, scope);
        if (row || !page.has_more) return row ?? null;
        if (!page.next_cursor || seen.has(page.next_cursor))
          throw new Error("Invalid visible-space cursor");
        cursor = page.next_cursor;
        seen.add(cursor);
      }
      throw new DOMException("Retired initial space read", "AbortError");
    },
    enabled: enabled && scope.view === "ordinary" && ready && !first,
    retry: false,
    cacheTime: 0,
  });
  if (scope.view === "admin") {
    const rows = admin.data?.pages.flatMap((page) => page.data) ?? [];
    return {
      space:
        available(
          rows.filter((row) => row.space_kind === "department"),
          scope,
        ) ?? available(rows, scope),
      loading: enabled && admin.isInitialLoading,
      error: admin.isError,
      retry: () => admin.refetch(),
    };
  }
  return {
    space: first ?? (ready ? (fallback.data ?? undefined) : undefined),
    loading:
      enabled &&
      ((!ready && !groups.some((query) => query.isError)) ||
        (ready && !first && fallback.isInitialLoading)),
    error:
      groups.some((query) => query.isError) ||
      (ready && !first && fallback.isError),
    retry: () =>
      Promise.all([
        ...groups
          .filter((query) => query.isError)
          .map((query) => query.refetch()),
        ...(fallback.isError ? [fallback.refetch()] : []),
      ]),
  };
}
