import { Button } from "@bisheng/ui";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { knowledgeSpaceApi, type KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";

interface KnowledgeFolderTreeProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
  selectedId: number | null;
  path: readonly number[];
  depth?: number;
  onSelect: (spaceId: number, folderId: number) => void;
}

interface FolderNodeProps extends KnowledgeFolderTreeProps {
  item: KnowledgeSpaceChild;
}

function FolderNode({ item, depth = 1, ...props }: FolderNodeProps) {
  const { t } = useTranslation("knowledge");
  const [expanded, setExpanded] = useState(props.path.includes(item.id));
  const pathTarget = props.path.includes(item.id);
  useEffect(() => {
    if (pathTarget) setExpanded(true);
  }, [pathTarget, props.selectedId]);
  const selected = item.id === props.selectedId;
  return (
    <li>
      <div
        className={`group flex min-h-8 items-center gap-1 rounded-md pr-1 text-control text-text-1 hover:bg-fill-1 ${selected ? "bg-fill-2 font-medium" : ""}`}
        style={{ paddingLeft: depth * 20 }}
      >
        <button
          type="button"
          aria-label={`${t(expanded ? "sidebar.collapse" : "sidebar.expand")} ${item.file_name}`}
          aria-expanded={expanded}
          className="flex size-6 shrink-0 items-center justify-center rounded hover:bg-fill-2"
          onClick={() => setExpanded((value) => !value)}
        >
          <Outlined.Right aria-hidden className={`size-4 text-text-3 ${expanded ? "rotate-90" : ""}`} />
        </button>
        <button
          type="button"
          title={item.file_name}
          aria-current={selected ? "page" : undefined}
          className="flex min-w-0 flex-1 items-center gap-2 py-1 text-left"
          onClick={() => props.onSelect(props.spaceId, item.id)}
        >
          {expanded ? <Outlined.FolderOpen aria-hidden className="size-4 shrink-0 text-text-3" /> : <Outlined.FolderClose aria-hidden className="size-4 shrink-0 text-text-3" />}
          <span className="truncate">{item.file_name}</span>
        </button>
      </div>
      {expanded && (
        <KnowledgeFolderTree {...props} parentId={item.id} depth={depth + 1} />
      )}
    </li>
  );
}

/** Adapted from the legacy client tree, using the current cursor-based children API. */
export function KnowledgeFolderTree(props: KnowledgeFolderTreeProps) {
  const { t } = useTranslation("knowledge");
  const { scope, spaceId, parentId, path } = props;
  const query = useInfiniteQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "navigation-folders", parentId],
    queryFn: ({ pageParam }) => knowledgeSpaceApi.listChildren(spaceId, {
      parent_id: parentId,
      file_type: 0,
      page_size: 100,
      ...(typeof pageParam === "string" ? { cursor: pageParam } : {}),
    }),
    getNextPageParam: (page) => page.has_more ? page.next_cursor ?? undefined : undefined,
    retry: false,
    cacheTime: 0,
  });
  useEffect(() => {
    if (query.error) showApiError(query.error);
  }, [query.error]);
  const rows = useMemo(() => [...new Map((query.data?.pages.flatMap((page) => page.data) ?? [])
    .filter((item) => item.file_type === 0 && Number.isSafeInteger(item.id) && item.id > 0)
    .map((item) => [item.id, item])).values()], [query.data]);
  const parentIndex = parentId === null ? -1 : path.indexOf(parentId);
  const target = parentId !== null && parentIndex === -1 ? undefined : path[parentIndex + 1];
  const { hasNextPage, isFetching, isError, fetchNextPage } = query;
  // Deep links may refer to a folder beyond the first cursor page.
  useEffect(() => {
    if (target !== undefined && !rows.some((row) => row.id === target) && hasNextPage && !isFetching && !isError)
      void fetchNextPage().catch(showApiError);
  }, [target, rows, hasNextPage, isFetching, isError, fetchNextPage]);
  return (
    <ul className="space-y-0.5">
      {rows.map((item) => <FolderNode key={item.id} {...props} item={item} />)}
      {query.isInitialLoading && <li role="status" className="px-8 py-2 text-control text-text-3">{t("sidebar.loading")}</li>}
      {query.isError && (
        <li className="px-6 py-1 text-control text-text-3">
          <span>{t("sidebar.load_failed")}</span>
          <Button variant="text" onClick={() => { void (query.data && query.hasNextPage ? query.fetchNextPage() : query.refetch()).catch(showApiError); }}>{t("retry")}</Button>
        </li>
      )}
      {!query.isInitialLoading && !query.isError && rows.length === 0 && (
        <li className="px-8 py-2 text-control text-text-3">{t("sidebar.no_folders")}</li>
      )}
      {query.hasNextPage && !query.isError && (
        <li className="pl-8">
          <Button variant="text" disabled={query.isFetchingNextPage} onClick={() => { void query.fetchNextPage().catch(showApiError); }}>{t("sidebar.more_folders")}</Button>
        </li>
      )}
    </ul>
  );
}
