import { Button, Input, Tag, Tooltip } from "@bisheng/ui";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Check, Link2, Search } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { knowledgeVersionsApi, type PendingSimilarFile, type VersionDocumentCandidate } from "@/controllers/API/knowledgeVersions";
import { knowledgeQueryKeys } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import type { SpaceVersionRelationPanelProps } from "./SpaceVersionRelationPanel";

interface SpaceSimilarDocumentPanelProps extends Omit<SpaceVersionRelationPanelProps, "mode"> {
  file?: PendingSimilarFile;
  onUncertain?: () => void;
}
/** The client's four-section interaction, using Platform's scoped API and primitives. */
export function SpaceSimilarDocumentPanel(props: SpaceSimilarDocumentPanelProps) {
  return <SimilarFilePanel key={JSON.stringify([props.scope, props.spaceId, props.fileId])} {...props} />;
}
function SimilarFilePanel({ scope, spaceId, fileId, file, api = knowledgeVersionsApi, disabled = false, onChanged, onBusyChange, onUncertain }: SpaceSimilarDocumentPanelProps) {
  const { t } = useTranslation("knowledge");
  const [keyword, setKeyword] = useState("");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const lifetime = useRef<AbortController>();
  const writing = useRef(false);
  const opening = useId();
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => { controller.abort(); onBusyChange?.(false); };
  }, [onBusyChange]);
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(keyword.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [keyword]);
  const prefix = [...knowledgeQueryKeys.space(scope, spaceId), "similar-review", fileId, opening];
  const recommendations = useQuery({
    queryKey: [...prefix, "recommended"],
    queryFn: ({ signal }) => api.getVersionRecommendations(fileId, false, signal),
    retry: false, cacheTime: 0,
  });
  const results = useInfiniteQuery({
    queryKey: [...prefix, "search", search],
    enabled: !!search,
    queryFn: async ({ pageParam, signal }) => {
      const page = await api.searchVersionDocuments(spaceId, fileId, search, false, pageParam, signal);
      if (page.has_more && (!page.next_cursor || page.next_cursor === pageParam)) throw new Error("Version candidate cursor did not progress");
      return page;
    },
    getNextPageParam: (page, pages) => page.has_more && page.next_cursor && !pages.slice(0, -1).some(old => old.next_cursor === page.next_cursor) ? page.next_cursor : undefined,
    retry: false, cacheTime: 0, keepPreviousData: false,
  });
  useEffect(() => {
    const error = recommendations.error || results.error;
    if (error) showApiError(error);
  }, [recommendations.error, results.error]);
  const locked = disabled || busy || uncertain;
  const handleAction = (candidate?: VersionDocumentCandidate) => {
    const controller = lifetime.current;
    if (!controller || controller.signal.aborted || locked || writing.current) return;
    let attempted = false;
    bsConfirm({
      title: t(candidate ? "versions.as_version" : "versions.keep_two"),
      desc: candidate ? t("similarReview.confirmLink", { name: file?.file_name ?? String(fileId), target: candidate.title }) : t("versions.keep_two_hint"),
      signal: controller.signal,
      onOk: async close => {
        if (controller.signal.aborted || writing.current || attempted) return;
        attempted = true; writing.current = true; setBusy(true); onBusyChange?.(true);
        try {
          if (candidate) await api.linkSpaceFileVersion(fileId, candidate.document_id, controller.signal);
          else await api.dismissSpaceSimilarFile(fileId, controller.signal);
          if (controller.signal.aborted) return;
          close(); await onChanged();
        } catch (error) {
          if (!controller.signal.aborted) { setUncertain(true); onUncertain?.(); close(); showApiError(error); }
        } finally {
          writing.current = false;
          if (!controller.signal.aborted) { setBusy(false); onBusyChange?.(false); }
        }
      },
    });
  };
  const renderCandidate = (candidate: VersionDocumentCandidate, similarity?: number) => <div key={candidate.document_id} className="flex items-center justify-between gap-3 rounded-lg border border-border-base bg-background px-4 py-3">
    <div className="min-w-0 flex-1">
      <div className="mb-1 flex items-center gap-2">
        <Tooltip content={candidate.title}><p className="truncate font-medium text-text-1">{candidate.title}</p></Tooltip>
        {similarity !== undefined && <Tag size="small" color="warning">{t("similarReview.similarity")} {(similarity * 100).toFixed(0)}%</Tag>}
      </div>
      <p className="text-xs text-text-3">{candidate.doc_code ? `${candidate.doc_code} · ` : ""}{t("similarReview.primaryVersion", { version: candidate.current_primary_version_no })}</p>
      {(candidate.primary_uploader_name || candidate.primary_upload_time) && <p className="text-xs text-text-3">{candidate.primary_uploader_name} {candidate.primary_upload_time?.replace("T", " ").slice(0, 16)}</p>}
    </div>
    <Button size="small" disabled={locked} onClick={() => handleAction(candidate)}><Link2 className="mr-1 size-4" />{t("versions.as_version")}</Button>
  </div>;
  return <div className="flex min-h-full flex-col gap-5 p-5">
    <section className="flex shrink-0 items-start justify-between gap-3 rounded-lg border border-border-base bg-fill-2 px-4 py-3">
      <div className="min-w-0">
        <p className="mb-1 text-xs text-text-3">{t("similarReview.currentFile")}</p>
        <Tooltip content={file?.file_name ?? String(fileId)}><p className="truncate text-base font-medium">{file?.file_name ?? fileId}</p></Tooltip>
        <p className="mt-1 text-xs text-text-3">{file?.file_code ? `${file.file_code} · ` : ""}{t("similarReview.primaryVersion", { version: file?.current_primary_version_no ?? 1 })} {file?.primary_uploader_name}</p>
      </div>
      <Tag color="warning" size="small">{t("similarReview.recommendCount", { count: file?.candidate_count ?? recommendations.data?.length ?? 0 })}</Tag>
    </section>
    <div className="flex flex-col gap-5 rounded-lg border border-border-base bg-fill-2 p-4">
      <section>
        <h3 className="font-medium">{t("versions.recommendations")}</h3>
        <p className="mb-3 text-xs text-text-3">{t("similarReview.recommendHint")}</p>
        {recommendations.isError ? <Button variant="outlined" onClick={() => void recommendations.refetch()}>{t("retry")}</Button>
          : recommendations.isInitialLoading ? <p role="status">{t("loading")}</p>
          : <div className="max-h-56 space-y-2 overflow-y-auto">{recommendations.data?.length ? recommendations.data.map(row => renderCandidate({ ...row, document_id: row.target_document_id }, row.similarity)) : <p className="text-sm text-text-3">{t("versions.no_candidates")}</p>}</div>}
      </section>
      <section>
        <h3 className="font-medium">{t("similarReview.searchTitle")}</h3>
        <p className="mb-3 text-xs text-text-3">{t("similarReview.searchHint")}</p>
        <form className="mb-3 flex gap-2" onSubmit={event => { event.preventDefault(); setSearch(keyword.trim()); }}>
          <Input value={keyword} onChange={event => setKeyword(event.target.value)} placeholder={t("versions.search_placeholder")} aria-label={t("versions.search_placeholder")} />
          <Button type="submit" variant="outlined"><Search className="mr-1 size-4" />{t("versions.search")}</Button>
        </form>
        {!search ? <p className="rounded-md border border-dashed border-border-base bg-background p-4 text-center text-sm text-text-3">{t("versions.search_placeholder")}</p>
          : results.isError ? <Button variant="outlined" onClick={() => void results.refetch()}>{t("retry")}</Button>
          : results.isInitialLoading ? <p role="status">{t("loading")}</p>
          : <div className="max-h-56 space-y-2 overflow-y-auto">
            {results.data?.pages.flatMap(page => page.data).map(row => renderCandidate(row))}
            {results.data?.pages.every(page => !page.data.length) && <p className="text-sm text-text-3">{t("similarReview.noSearchResults")}</p>}
            {results.hasNextPage && <Button variant="outlined" disabled={results.isFetchingNextPage} onClick={() => void results.fetchNextPage()}>{t("versions.load_more")}</Button>}
          </div>}
      </section>
    </div>
    <section className="mt-auto flex items-center justify-between gap-3 rounded-lg border border-dashed border-border-base px-4 py-3">
      <div><h3 className="font-medium">{t("similarReview.keepTitle")}</h3><p className="text-xs text-text-3">{t("versions.keep_two_hint")}</p></div>
      <Button variant="outlined" disabled={locked} onClick={() => handleAction()}><Check className="mr-1 size-4" />{t("versions.keep_two")}</Button>
    </section>
    {uncertain && <p role="alert">{t("versions.uncertain")}</p>}
  </div>;
}
