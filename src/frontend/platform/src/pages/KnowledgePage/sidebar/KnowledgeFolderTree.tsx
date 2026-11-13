import { Button } from "@bisheng/ui";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { knowledgeSpaceApi, type KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { ScrollableTreeName } from "./ScrollableTreeName";

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
  const selected = item.id === props.selectedId;
  // Reveal the selected row through its ancestors; the row itself opens via its arrow.
  const pathTarget = !selected && props.path.includes(item.id);
  const [expanded, setExpanded] = useState(pathTarget);
  useEffect(() => {
    if (pathTarget) setExpanded(true);
  }, [pathTarget, props.selectedId]);
  const iconClass = `size-4 shrink-0 ${selected ? "text-text-1" : "text-[#8D93A0] dark:text-text-3"}`;
  return (
    <li className="space-y-0.5">
      <div
        className={`flex h-7 select-none items-center rounded-md pr-1 text-[12px] leading-5 text-text-1 transition-colors ${selected ? "bg-[#EEEEEE] font-semibold dark:bg-fill-2" : "hover:bg-[#F4F4F4] dark:hover:bg-fill-1"}`}
        style={{ paddingLeft: depth * 20 }}
      >
        <button
          type="button"
          aria-label={`${t(expanded ? "sidebar.collapse" : "sidebar.expand")} ${item.file_name}`}
          aria-expanded={expanded}
          className="flex size-5 shrink-0 items-center justify-center rounded"
          onClick={() => setExpanded((value) => !value)}
        >
          <Outlined.Right aria-hidden className={`size-4 text-[#8D93A0] transition-transform duration-150 dark:text-text-3 ${expanded ? "rotate-90" : ""}`} />
        </button>
        <button
          type="button"
          title={item.file_name}
          aria-current={selected ? "page" : undefined}
          className="flex h-full min-w-0 flex-1 cursor-pointer items-center text-left"
          onClick={() => props.onSelect(props.spaceId, item.id)}
        >
          <span className="flex size-5 shrink-0 items-center justify-center">
            {expanded ? <Outlined.FolderOpen aria-hidden className={iconClass} /> : <Outlined.FolderClose aria-hidden className={iconClass} />}
          </span>
          <ScrollableTreeName name={item.file_name} />
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
  if (!rows.length && !query.isInitialLoading && !isError && !hasNextPage) return null;
  return (
    <ul className="space-y-0.5">
      {rows.map((item) => <FolderNode key={item.id} {...props} item={item} />)}
      {query.isInitialLoading && (
        <li role="status" className="sticky left-0 -mx-3 flex w-[100cqi] justify-center py-3">
          <Outlined.Loading aria-hidden className="size-4 animate-spin text-[#8D93A0] dark:text-text-3" />
          <span className="sr-only">{t("sidebar.loading")}</span>
        </li>
      )}
      {query.isError && (
        <li className="sticky left-3 w-fit px-6 py-1 text-[12px] leading-5 text-text-3">
          <span>{t("sidebar.load_failed")}</span>
          <Button variant="text" onClick={() => { void (query.data && query.hasNextPage ? query.fetchNextPage() : query.refetch()).catch(showApiError); }}>{t("retry")}</Button>
        </li>
      )}
      {query.hasNextPage && !query.isError && (
        <li className="sticky left-3 w-fit pl-8">
          <Button variant="text" disabled={query.isFetchingNextPage} onClick={() => { void query.fetchNextPage().catch(showApiError); }}>{t("sidebar.more_folders")}</Button>
        </li>
      )}
    </ul>
  );
}
