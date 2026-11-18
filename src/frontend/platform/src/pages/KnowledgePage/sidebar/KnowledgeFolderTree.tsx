import { Button, TreeNavigationNode, TreeNavigationStatus } from "@bisheng/ui";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { knowledgeSpaceApi, type KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";

export interface KnowledgeTreeExpansion {
  expandedKeys: ReadonlySet<string>;
  onExpansionChange: (key: string, expanded: boolean) => void;
}

export function knowledgeTreeNodeKey(spaceId: number, folderId?: number) {
  return `${spaceId}/${folderId ?? ""}`;
}

interface KnowledgeFolderTreeProps extends KnowledgeTreeExpansion {
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
  selectedId: number | null;
  path: readonly number[];
  depth?: number;
  onSelect: (spaceId: number, folderId: number) => void;
  onEmptyChange?: (empty: boolean) => void;
}

interface FolderNodeProps extends Omit<KnowledgeFolderTreeProps, "onEmptyChange" | "parentId"> {
  item: KnowledgeSpaceChild;
}

function FolderNode({ item, depth = 1, ...props }: FolderNodeProps) {
  const { t } = useTranslation("knowledge");
  const selected = item.id === props.selectedId;
  const key = knowledgeTreeNodeKey(props.spaceId, item.id);
  const expanded = props.expandedKeys.has(key);
  const [knownEmpty, setKnownEmpty] = useState(false);
  return (
    <TreeNavigationNode
      name={item.file_name}
      depth={depth}
      current={selected && "page"}
      icon={expanded && !knownEmpty ? <Outlined.FolderOpen /> : <Outlined.FolderClose />}
      onSelect={() => props.onSelect(props.spaceId, item.id)}
      disclosure={knownEmpty ? undefined : {
        expanded,
        label: `${t(expanded ? "sidebar.collapse" : "sidebar.expand")} ${item.file_name}`,
        onToggle: () => props.onExpansionChange(key, !expanded),
      }}
    >
      {expanded && <KnowledgeFolderTree {...props} parentId={item.id} depth={depth + 1} onEmptyChange={setKnownEmpty} />}
    </TreeNavigationNode>
  );
}

/** Adapted from the legacy client tree, using the current cursor-based children API. */
export function KnowledgeFolderTree(props: KnowledgeFolderTreeProps) {
  const { t } = useTranslation("knowledge");
  const { scope, spaceId, parentId, path, depth = 1, onEmptyChange, ...nodeProps } = props;
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
  const knownEmpty = query.isSuccess && !rows.length && !hasNextPage;
  useEffect(() => { onEmptyChange?.(knownEmpty); }, [knownEmpty, onEmptyChange]);

  return (
    <>
      {rows.map((item) => <FolderNode key={item.id} {...nodeProps} scope={scope} spaceId={spaceId} path={path} depth={depth} item={item} />)}
      {query.isInitialLoading && <TreeNavigationStatus depth={depth} loading>{t("sidebar.loading")}</TreeNavigationStatus>}
      {isError && (
        <TreeNavigationStatus depth={depth}>
          <span>{t("sidebar.load_failed")}</span>
          <Button variant="text" onClick={() => { void (query.data && query.hasNextPage ? query.fetchNextPage() : query.refetch()).catch(showApiError); }}>{t("retry")}</Button>
        </TreeNavigationStatus>
      )}
      {query.isFetchingNextPage && <TreeNavigationStatus depth={depth} loading>{t("sidebar.loading")}</TreeNavigationStatus>}
      {query.hasNextPage && !isError && !query.isFetchingNextPage && (
        <TreeNavigationStatus depth={depth}>
          <Button variant="text" onClick={() => { void query.fetchNextPage().catch(showApiError); }}>{t("sidebar.more_folders")}</Button>
        </TreeNavigationStatus>
      )}
    </>
  );
}
