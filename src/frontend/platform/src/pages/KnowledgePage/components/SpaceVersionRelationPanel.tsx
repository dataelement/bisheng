import { Button, Input } from "@bisheng/ui";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import {
  knowledgeFilesApi,
  type SpaceFilePreview,
} from "@/controllers/API/knowledgeFiles";
import {
  knowledgeVersionsApi,
  type KnowledgeVersionsApi,
  type VersionDocumentCandidate,
} from "@/controllers/API/knowledgeVersions";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
const PreviewFile = lazy(() => import("./PreviewFile"));

export interface SpaceVersionRelationPanelProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  fileId: number;
  mode: "merge" | "link";
  disabled?: boolean;
  api?: KnowledgeVersionsApi;
  onChanged: () => Promise<void>;
  onBusyChange?: (busy: boolean) => void;
}

export function SpaceVersionRelationPanel({
  scope,
  spaceId,
  fileId,
  mode,
  disabled = false,
  api = knowledgeVersionsApi,
  onChanged,
  onBusyChange,
}: SpaceVersionRelationPanelProps) {
  const { t } = useTranslation("knowledge");
  const [keyword, setKeyword] = useState(""),
    [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false),
    [submitted, setSubmitted] = useState(false);
  const [preview, setPreview] = useState<{
    id: number;
    title: string;
    data: SpaceFilePreview;
  } | null>(null);
  const lifetime = useRef<AbortController>();
  const writing = useRef(false);
  const opening = useId(),
    previewSequence = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => {
      controller.abort();
      onBusyChange?.(false);
    };
  }, [onBusyChange]);
  const prefix = [
    ...knowledgeQueryKeys.space(scope, spaceId),
    "version-candidates",
    fileId,
    mode,
    opening,
  ];
  const recommendations = useQuery({
    queryKey: [...prefix, "recommended"],
    queryFn: ({ signal }) =>
      api.getVersionRecommendations(fileId, mode === "merge", signal),
    retry: false,
    cacheTime: 0,
  });
  const results = useInfiniteQuery({
    queryKey: [...prefix, search],
    enabled: search.trim().length > 0,
    queryFn: async ({ pageParam, signal }) => {
      const page = await api.searchVersionDocuments(
        spaceId,
        fileId,
        search,
        mode === "merge",
        pageParam,
        signal,
      );
      if (
        page.has_more &&
        (!page.next_cursor || page.next_cursor === pageParam)
      )
        throw new Error("Version candidate cursor did not progress");
      return page;
    },
    getNextPageParam: (page, pages) =>
      page.has_more &&
      page.next_cursor &&
      !pages.slice(0, -1).some((old) => old.next_cursor === page.next_cursor)
        ? page.next_cursor
        : undefined,
    retry: false,
    cacheTime: 0,
    keepPreviousData: false,
  });
  useEffect(() => {
    const error = recommendations.error || results.error;
    if (error) showApiError(error);
  }, [recommendations.error, results.error]);
  const handleRelate = (candidate: VersionDocumentCandidate) => {
    if (
      disabled ||
      writing.current ||
      submitted ||
      lifetime.current?.signal.aborted
    )
      return;
    const controller = lifetime.current;
    let attempted = false;
    bsConfirm({
      title: t(mode === "merge" ? "versions.merge" : "versions.as_version"),
      desc: t(
        mode === "merge" ? "versions.confirm_merge" : "versions.confirm_link",
        { name: candidate.title },
      ),
      signal: controller?.signal,
      onOk: async (close) => {
        if (
          !controller ||
          controller.signal.aborted ||
          writing.current ||
          attempted
        )
          return;
        attempted = true;
        writing.current = true;
        setBusy(true);
        onBusyChange?.(true);
        try {
          if (mode === "merge")
            await api.mergeSpaceFileVersion(
              fileId,
              candidate.document_id,
              controller.signal,
            );
          else
            await api.linkSpaceFileVersion(
              fileId,
              candidate.document_id,
              controller.signal,
            );
          if (controller.signal.aborted) return;
          close();
          await onChanged();
        } catch (error) {
          if (!controller.signal.aborted) {
            setSubmitted(true);
            close();
            showApiError(error);
          }
        } finally {
          writing.current = false;
          if (!controller.signal.aborted) {
            setBusy(false);
            onBusyChange?.(false);
          }
        }
      },
    });
  };
  const handlePreview = async (candidate: VersionDocumentCandidate) => {
    const controller = lifetime.current,
      id = candidate.primary_knowledge_file_id;
    const sequence = ++previewSequence.current;
    if (!controller || controller.signal.aborted || !id) return;
    try {
      const data = await knowledgeFilesApi.getSpaceFilePreview(spaceId, id);
      if (!controller.signal.aborted && sequence === previewSequence.current)
        setPreview({ id, title: candidate.title, data });
    } catch (error) {
      if (!controller.signal.aborted) showApiError(error);
    }
  };
  const renderCandidate = (candidate: VersionDocumentCandidate) => (
    <li
      key={candidate.document_id}
      className="flex items-center justify-between gap-2 border-b py-2"
    >
      <div className="min-w-0">
        <p className="truncate">{candidate.title}</p>
        <p className="text-xs text-muted-foreground">
          {candidate.doc_code} · V{candidate.current_primary_version_no}
        </p>
      </div>
      <div className="flex shrink-0 gap-1">
        {candidate.primary_knowledge_file_id && (
          <Button
            size="small"
            variant="text"
            onClick={() => void handlePreview(candidate)}
          >
            {t("versions.preview")}
          </Button>
        )}
        <Button
          size="small"
          variant="outlined"
          disabled={disabled || busy || submitted}
          onClick={() => handleRelate(candidate)}
        >
          {t(mode === "merge" ? "versions.merge" : "versions.as_version")}
        </Button>
      </div>
    </li>
  );
  return (
    <section className="space-y-3 rounded-md border p-3">
      <h3 className="font-medium">
        {t(mode === "merge" ? "versions.merge" : "versions.as_version")}
      </h3>
      <p className="text-sm text-muted-foreground">
        {t(mode === "merge" ? "versions.merge_hint" : "versions.link_hint")}
      </p>
      {submitted && (
        <p role="alert" className="text-sm">
          {t("versions.uncertain")}
        </p>
      )}
      <h4 className="text-sm">{t("versions.recommendations")}</h4>
      {recommendations.isError ? (
        <Button
          variant="outlined"
          onClick={() => void recommendations.refetch()}
        >
          {t("retry")}
        </Button>
      ) : recommendations.isInitialLoading ? (
        <p role="status">{t("loading")}</p>
      ) : (
        <ul>
          {recommendations.data?.length ? (
            recommendations.data.map((row) =>
              renderCandidate({ ...row, document_id: row.target_document_id }),
            )
          ) : (
            <li className="text-sm text-muted-foreground">
              {t("versions.no_candidates")}
            </li>
          )}
        </ul>
      )}
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setSearch(keyword.trim());
        }}
      >
        <Input
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder={t("versions.search_placeholder")}
          aria-label={t("versions.search_placeholder")}
        />
        <Button type="submit" variant="outlined">
          {t("versions.search")}
        </Button>
      </form>
      {!!search &&
        (results.isError ? (
          <Button variant="outlined" onClick={() => void results.refetch()}>
            {t("retry")}
          </Button>
        ) : results.isInitialLoading ? (
          <p role="status">{t("loading")}</p>
        ) : (
          <>
            <ul>
              {results.data?.pages
                .flatMap((page) => page.data)
                .map(renderCandidate)}
            </ul>
            {results.data?.pages.every((page) => page.data.length === 0) && (
              <p className="text-sm text-muted-foreground">
                {t("versions.no_candidates")}
              </p>
            )}
            {results.hasNextPage && (
              <Button
                variant="outlined"
                disabled={results.isFetchingNextPage}
                onClick={() => void results.fetchNextPage()}
              >
                {t("versions.load_more")}
              </Button>
            )}
          </>
        ))}
      {preview && (
        <section className="space-y-2 border-t pt-3">
          <div className="flex justify-between">
            <h4>{preview.title}</h4>
            <Button
              size="small"
              variant="text"
              onClick={() => setPreview(null)}
            >
              {t("close", { ns: "bs" })}
            </Button>
          </div>
          <Suspense fallback={<p role="status">{t("loading")}</p>}>
            <PreviewFile
              file={{ id: preview.id, fileName: preview.title, fileType: "" }}
              rawFiles={[]}
              partitions={{}}
              chunks={[]}
              setChunks={() => undefined}
              edit={false}
              urlState={{
                load: true,
                url: preview.data.preview_url || preview.data.original_url,
              }}
              previewData={preview.data}
            />
          </Suspense>
        </section>
      )}
    </section>
  );
}
