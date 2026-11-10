import { Button, SearchInput, Select } from "@bisheng/ui";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { knowledgeSpaceApi } from "@/controllers/API/knowledgeSpace";
import type { MoveDestination } from "@/controllers/API/knowledgeMove";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";

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
  const labels = useSelectLabels();
  const [keyword, setKeyword] = useState("");
  const [trail, setTrail] = useState<{ id: number; name: string }[]>([]);
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
  const folders = useInfiniteQuery({
    queryKey: [
      ...prefix,
      "move-destination-folders",
      value.spaceId,
      value.folderId,
    ],
    queryFn: ({ pageParam = null }) =>
      knowledgeSpaceApi.listChildren(value.spaceId, {
        parent_id: value.folderId,
        file_type: 0,
        page_size: 60,
        cursor: pageParam,
      }),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    cacheTime: 0,
    retry: false,
  });
  useEffect(() => {
    const error = spaces.error ?? folders.error;
    if (error) showApiError(error);
  }, [spaces.error, folders.error]);
  const options = useMemo(() => {
    const rows = new Map(
      (spaces.data?.pages.flatMap((page) => page.data) ?? [])
        .filter((row) => Number.isSafeInteger(row.id) && row.id > 0)
        .map((row) => [row.id, { value: String(row.id), label: row.name }]),
    );
    if (!rows.has(sourceId))
      rows.set(sourceId, {
        value: String(sourceId),
        label: t("move.current_space"),
      });
    return [...rows.values()];
  }, [spaces.data, sourceId, t]);
  const rows = [
    ...new Map(
      (folders.data?.pages.flatMap((page) => page.data) ?? [])
        .filter(
          (row) =>
            row.file_type === 0 && Number.isSafeInteger(row.id) && row.id > 0,
        )
        .map((row) => [row.id, row]),
    ).values(),
  ];
  const spaceLabel =
    options.find((option) => option.value === String(value.spaceId))?.label ??
    t("move.current_space");
  return (
    <section className="space-y-3">
      <SearchInput
        aria-label={t("move.search_spaces")}
        value={keyword}
        onChange={(event) => setKeyword(event.target.value)}
      />
      <Select
        {...labels}
        aria-label={t("move.target_space")}
        value={String(value.spaceId)}
        options={options}
        onChange={(next) => {
          setTrail([]);
          onChange(
            { spaceId: Number(next), folderId: null },
            options.find((option) => option.value === String(next))?.label ??
              t("move.root"),
          );
        }}
      />
      {spaces.hasNextPage && (
        <Button
          variant="text"
          disabled={spaces.isFetchingNextPage}
          onClick={() => {
            void spaces.fetchNextPage();
          }}
        >
          {t("shared:knowledge.selection.loadMore")}
        </Button>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="text"
          onClick={() => {
            setTrail([]);
            onChange({ ...value, folderId: null }, spaceLabel);
          }}
        >
          {t("move.root")}
        </Button>
        {trail.map((folder, index) => (
          <Button
            key={folder.id}
            variant="text"
            onClick={() => {
              setTrail(trail.slice(0, index + 1));
              onChange(
                { ...value, folderId: folder.id },
                [
                  spaceLabel,
                  ...trail.slice(0, index + 1).map((row) => row.name),
                ].join(" / "),
              );
            }}
          >
            {folder.name}
          </Button>
        ))}
      </div>
      <p className="text-body-sm text-text-2">{t("move.choose_folder_hint")}</p>
      {value.folderId !== null && !trail.length && (
        <p>{t("move.current_folder")}</p>
      )}
      <ul className="max-h-52 overflow-y-auto">
        {rows.map((folder) => (
          <li key={folder.id}>
            <Button
              variant="link"
              onClick={() => {
                setTrail([...trail, { id: folder.id, name: folder.file_name }]);
                onChange(
                  { ...value, folderId: folder.id },
                  [
                    spaceLabel,
                    ...trail.map((row) => row.name),
                    folder.file_name,
                  ].join(" / "),
                );
              }}
            >
              {folder.file_name}
            </Button>
          </li>
        ))}
      </ul>
      {(spaces.isInitialLoading || folders.isInitialLoading) && (
        <p role="status">{t("f118.loading_directory")}</p>
      )}
      {(spaces.isError || folders.isError) && (
        <Button
          variant="outlined"
          onClick={() => {
            void Promise.all([spaces.refetch(), folders.refetch()]).catch(
              showApiError,
            );
          }}
        >
          {t("retry")}
        </Button>
      )}
      {folders.hasNextPage && (
        <Button
          variant="text"
          disabled={folders.isFetchingNextPage}
          onClick={() => {
            void folders.fetchNextPage();
          }}
        >
          {t("f118.more_files")}
        </Button>
      )}
    </section>
  );
}
