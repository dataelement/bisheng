import { Button, SearchInput } from "@bisheng/ui";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { knowledgeFilesApi } from "@/controllers/API/knowledgeFiles";
import { knowledgeSpaceApi } from "@/controllers/API/knowledgeSpace";
import type { MoveDestination } from "@/controllers/API/knowledgeMove";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { KnowledgeFolderTree } from "../sidebar/KnowledgeFolderTree";
import { ScrollableTreeName } from "../sidebar/ScrollableTreeName";
import { useKnowledgeTreeScroll } from "../sidebar/useKnowledgeTreeScroll";

interface MoveDestinationPickerProps {
  scope: KnowledgeQueryScope;
  sourceId: number;
  value: MoveDestination;
  onChange: (value: MoveDestination, label: string) => void;
}

/** Candidate visibility is only for navigation; final upload authority is checked by precheck. */
export function MoveDestinationPicker({
  scope,
  sourceId,
  value,
  onChange,
}: MoveDestinationPickerProps) {
  const { t } = useTranslation("knowledge");
  const [keyword, setKeyword] = useState("");
  const [expanded, setExpanded] = useState(() => new Set([value.spaceId]));
  const treeRef = useRef<HTMLDivElement>(null);
  useKnowledgeTreeScroll(treeRef);
  const prefix = knowledgeQueryKeys.scope(scope);
  const spaces = useInfiniteQuery({
    queryKey: [...prefix, "move-destination-spaces", keyword],
    queryFn: ({ pageParam = null }) =>
      knowledgeSpaceApi.listVisibleSpaces({
        cursor: pageParam,
        page_size: 60,
        keyword,
      }),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    cacheTime: 0,
    retry: false,
  });
  const contents = useInfiniteQuery({
    queryKey: [
      ...prefix,
      "move-destination-contents",
      value.spaceId,
      value.folderId,
    ],
    queryFn: ({ pageParam = null }) =>
      knowledgeSpaceApi.listChildren(value.spaceId, {
        parent_id: value.folderId,
        page_size: 60,
        cursor: pageParam,
      }),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    cacheTime: 0,
    retry: false,
  });
  const parents = useQuery({
    queryKey: [
      ...prefix,
      "move-destination-path",
      value.spaceId,
      value.folderId,
    ],
    queryFn: () =>
      knowledgeFilesApi.listSpaceFolderParents(value.spaceId, value.folderId!),
    enabled: value.folderId !== null,
    cacheTime: 0,
    retry: false,
  });
  useEffect(() => {
    const error = spaces.error ?? contents.error ?? parents.error;
    if (error) showApiError(error);
  }, [spaces.error, contents.error, parents.error]);
  const options = useMemo(() => {
    const rows = new Map(
      (spaces.data?.pages.flatMap((page) => page.data) ?? [])
        .filter((row) => Number.isSafeInteger(row.id) && row.id > 0)
        .map((row) => [row.id, row]),
    );
    // Keep a route back to the source, without inserting it into unrelated search results.
    if (!keyword.trim() && !rows.has(sourceId))
      rows.set(sourceId, { id: sourceId, name: t("move.current_space") });
    return [...rows.values()];
  }, [spaces.data, sourceId, keyword, t]);
  const rows = [
    ...new Map(
      (contents.data?.pages.flatMap((page) => page.data) ?? [])
        .filter((row) => Number.isSafeInteger(row.id) && row.id > 0)
        // Files and folders have independent ID sequences.
        .map((row) => [`${row.file_type}:${row.id}`, row]),
    ).values(),
  ];
  const spaceLabel =
    options.find((space) => space.id === value.spaceId)?.name ??
    t(value.spaceId === sourceId ? "move.current_space" : "move.target_space");
  const path = parents.data ?? [];
  const handleSelectSpace = (spaceId: number, name: string) => {
    setExpanded((previous) => new Set(previous).add(spaceId));
    onChange({ spaceId, folderId: null }, name);
  };
  const handleSelectFolder = (folderId: number, name: string) => {
    setExpanded((previous) => new Set(previous).add(value.spaceId));
    onChange({ ...value, folderId }, `${spaceLabel} / ${name}`);
  };

  return (
    <section className="flex h-[420px] min-h-0 overflow-hidden rounded-lg border border-border-base">
      <div className="flex w-72 shrink-0 flex-col border-r border-border-base max-[768px]:w-2/5">
        <div className="p-3">
          <SearchInput
            aria-label={t("move.search_spaces")}
            placeholder={t("move.search_spaces")}
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
        </div>
        <div
          ref={treeRef}
          className="min-h-0 flex-1 overflow-auto px-2 pb-2 [container-type:inline-size]"
        >
          <div className="w-max min-w-full">
            {(["department", "personal"] as const).map((category) => {
              const items = options.filter(
                (space) =>
                  (space.space_kind === "department") ===
                  (category === "department"),
              );
              if (!items.length) return null;
              return (
                <section
                  key={category}
                  className="mb-2"
                  aria-label={t(`sidebar.${category}`)}
                >
                  <h3 className="px-2 py-1 text-body-sm font-medium text-text-3">
                    {t(`sidebar.${category}`)}
                  </h3>
                  <ul className="space-y-0.5">
                    {items.map((space) => {
                      const active = value.spaceId === space.id;
                      const rootSelected = active && value.folderId === null;
                      const isExpanded = expanded.has(space.id);
                      const Icon =
                        category === "department"
                          ? Outlined.City
                          : Outlined.Notebook;
                      return (
                        <li key={space.id}>
                          <div
                            className={`flex h-7 items-center rounded-md pr-1 text-body-sm text-text-1 ${rootSelected ? "bg-fill-2 font-semibold" : "hover:bg-fill-1"}`}
                          >
                            <button
                              type="button"
                              aria-label={`${t(isExpanded ? "sidebar.collapse" : "sidebar.expand")} ${space.name}`}
                              aria-expanded={isExpanded}
                              className="flex size-5 shrink-0 items-center justify-center"
                              onClick={() =>
                                setExpanded((previous) => {
                                  const next = new Set(previous);
                                  if (next.has(space.id)) next.delete(space.id);
                                  else next.add(space.id);
                                  return next;
                                })
                              }
                            >
                              <Outlined.Right
                                aria-hidden
                                className={`size-3.5 text-text-3 ${isExpanded ? "rotate-90" : ""}`}
                              />
                            </button>
                            <button
                              type="button"
                              title={space.name}
                              aria-current={
                                rootSelected ? "location" : undefined
                              }
                              className="flex h-full min-w-0 flex-1 items-center text-left"
                              onClick={() =>
                                handleSelectSpace(space.id, space.name)
                              }
                            >
                              <Icon
                                aria-hidden
                                className={`size-4 shrink-0 ${rootSelected ? "text-text-1" : "text-text-3"}`}
                              />
                              <ScrollableTreeName name={space.name} />
                            </button>
                          </div>
                          {isExpanded && (
                            <KnowledgeFolderTree
                              scope={scope}
                              spaceId={space.id}
                              parentId={null}
                              selectedId={active ? value.folderId : null}
                              path={
                                active ? path.map((folder) => folder.id) : []
                              }
                              onSelect={(spaceId, folderId) => {
                                onChange(
                                  { spaceId, folderId },
                                  `${space.name} / ${t("move.current_folder")}`,
                                );
                              }}
                            />
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })}
          </div>
          {spaces.isInitialLoading && (
            <p
              role="status"
              className="py-3 text-center text-body-sm text-text-3"
            >
              {t("sidebar.loading")}
            </p>
          )}
          {!spaces.isInitialLoading && !spaces.isError && !options.length && (
            <p className="py-8 text-center text-body-sm text-text-3">
              {t("sidebar.empty")}
            </p>
          )}
          {spaces.isError && (
            <Button
              variant="text"
              onClick={() => {
                void (spaces.hasNextPage
                  ? spaces.fetchNextPage()
                  : spaces.refetch());
              }}
            >
              {t("retry")}
            </Button>
          )}
          {spaces.hasNextPage && !spaces.isError && (
            <Button
              variant="text"
              loading={spaces.isFetchingNextPage}
              onClick={() => {
                void spaces.fetchNextPage();
              }}
            >
              {t("sidebar.more_spaces")}
            </Button>
          )}
        </div>
      </div>
      <div
        className="flex min-w-0 flex-1 flex-col"
        aria-label={t("workspace.files")}
      >
        {value.folderId !== null && (
          <nav
            className="flex shrink-0 flex-wrap items-center gap-1 border-b border-border-base p-2"
            aria-label={t("move.destination", { destination: spaceLabel })}
          >
            <Button
              variant="text"
              size="small"
              onClick={() => onChange({ ...value, folderId: null }, spaceLabel)}
            >
              {t("move.root")}
            </Button>
            {path.map((folder) => (
              <Button
                key={folder.id}
                variant="text"
                size="small"
                className="max-w-full"
                onClick={() =>
                  handleSelectFolder(folder.id, String(folder.file_name))
                }
              >
                <span className="truncate">{String(folder.file_name)}</span>
              </Button>
            ))}
            {parents.isError && (
              <Button
                variant="text"
                size="small"
                onClick={() => {
                  void parents.refetch();
                }}
              >
                {t("retry")}
              </Button>
            )}
          </nav>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {contents.isInitialLoading ? (
            <p
              role="status"
              className="flex h-full items-center justify-center text-body-sm text-text-3"
            >
              {t("f118.loading_directory")}
            </p>
          ) : !contents.isError && !rows.length ? (
            <p className="flex h-full items-center justify-center text-body-sm text-text-3">
              {t("f118.directory_empty")}
            </p>
          ) : (
            <ul>
              {rows
                .filter((item) => item.file_type === 0)
                .map((folder) => (
                  <li key={`folder:${folder.id}`}>
                    <button
                      type="button"
                      className="flex h-7 w-full items-center gap-1 rounded-md px-1 text-left text-body-sm text-text-1 hover:bg-fill-1"
                      onClick={() =>
                        handleSelectFolder(folder.id, folder.file_name)
                      }
                    >
                      <Outlined.FolderClose
                        aria-hidden
                        className="size-4 shrink-0"
                      />
                      <span
                        className="min-w-0 flex-1 truncate"
                        title={folder.file_name}
                      >
                        {folder.file_name}
                      </span>
                      <Outlined.Right
                        aria-hidden
                        className="size-3.5 shrink-0 text-text-4"
                      />
                    </button>
                  </li>
                ))}
              {rows
                .filter((item) => item.file_type !== 0)
                .map((file) => (
                  <li
                    key={`file:${file.id}`}
                    className="flex h-7 cursor-default items-center gap-1 px-1 text-body-sm text-text-3"
                    aria-disabled="true"
                  >
                    <Outlined.File aria-hidden className="size-4 shrink-0" />
                    <span
                      className="min-w-0 flex-1 truncate"
                      title={file.file_name}
                    >
                      {file.file_name}
                    </span>
                  </li>
                ))}
            </ul>
          )}
          {contents.isError && (
            <Button
              variant="text"
              onClick={() => {
                void (contents.hasNextPage
                  ? contents.fetchNextPage()
                  : contents.refetch());
              }}
            >
              {t("retry")}
            </Button>
          )}
          {contents.hasNextPage && !contents.isError && (
            <Button
              variant="text"
              loading={contents.isFetchingNextPage}
              onClick={() => {
                void contents.fetchNextPage();
              }}
            >
              {t("f118.more_files")}
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}
