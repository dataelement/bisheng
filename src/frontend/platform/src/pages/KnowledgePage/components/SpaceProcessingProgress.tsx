import { LoadingState } from "@/components/bs-icons/loading/LoadingState";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { KnowledgeDialogTable } from "@bisheng/knowledge";
import { Button, Pagination, Tooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  knowledgeSpaceApi,
  type ItemState,
  type JobState,
  type ProcessingKind,
} from "@/controllers/API/knowledgeSpace";
import {
  readProcessingJob,
  readProcessingItems,
  retryProcessing,
} from "@/controllers/API/knowledgeProcessing";
import {
  useKnowledgeProcessingJob,
  useKnowledgeProcessingItems,
  useKnowledgeProcessingActions,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { processingFailureKey } from "./processingFailure";
import { Progress } from "@/components/bs-ui/progress";
import { showApiError } from "@/controllers/request";
import { SpaceProcessingLoading } from "./SpaceProcessingLoading";
import { SpaceProcessingItemsTable } from "./SpaceProcessingItemsTable";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { createDshOperationId as createOperationId } from "@/util/dshOperationId";

interface SpaceProcessingProgressProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  jobId: string;
  kind?: ProcessingKind;
  onCompleted?: () => void;
  onStateChange?: (state: JobState) => void;
  onBack?: () => void;
  fill?: boolean;
}
export function SpaceProcessingProgress({
  scope,
  spaceId,
  jobId,
  kind,
  onCompleted,
  onStateChange,
  onBack,
  fill = false,
}: SpaceProcessingProgressProps) {
  const { t } = useTranslation("knowledge");
  const metadata = kind === "metadata_schema_change";
  const [page, setPage] = useState(1),
    [busy, setBusy] = useState(false);
  const [itemFilter, setItemFilter] = useState<ItemState>();
  const history = Boolean(onBack) && !metadata;
  const locale = usePaginationLocale();
  const api = useMemo(
    () => ({
      ...knowledgeSpaceApi,
      getProcessingJob: (sid: number, jid: string) =>
        readProcessingJob(sid, jid, kind),
      listProcessingItems: (
        sid: number,
        jid: string,
        query: Parameters<typeof readProcessingItems>[2],
      ) => readProcessingItems(sid, jid, query, kind),
      retryProcessingJob: (
        sid: number,
        jid: string,
        request: Parameters<typeof retryProcessing>[2],
      ) => retryProcessing(sid, jid, request, kind),
    }),
    [kind],
  );
  const queryOptions = metadata
    ? { refetchOnMount: "always" as const }
    : undefined;
  const job = useKnowledgeProcessingJob(
    scope,
    spaceId,
    jobId,
    api,
    queryOptions,
  );
  const jobData = !metadata || job.isFetchedAfterMount ? job.data : undefined;
  const progressReadFailed = job.isError && !job.isFetching;
  const hasFailures = (jobData?.failed_count ?? 0) > 0;
  const items = useKnowledgeProcessingItems(
    scope,
    spaceId,
    jobId,
    { page, page_size: 20, state: metadata ? "failed" : itemFilter },
    api,
    { enabled: !metadata || hasFailures, ...queryOptions },
  );
  const actions = useKnowledgeProcessingActions(scope, spaceId, api);
  const [retry, setRetry] = useState<{
    revision: number;
    key: string;
    refreshSource: boolean;
  } | null>(null);
  useEffect(() => {
    const error = job.error || items.error;
    if (error) showApiError(error);
  }, [job.error, items.error]);
  const reported = useRef(false);
  const completedCallback = useRef(onCompleted);
  completedCallback.current = onCompleted;
  const state = jobData?.state;
  useEffect(() => {
    if (state) onStateChange?.(state);
  }, [onStateChange, state]);
  const refreshJob = job.refetch,
    refreshItems = items.refetch;
  useEffect(() => {
    if (state === "succeeded" && !reported.current) {
      reported.current = true;
      completedCallback.current?.();
    }
    if (state !== "accepted" && state !== "running") return;
    const timer = window.setInterval(() => {
      if (metadata) {
        void refreshJob()
          .then(({ data }) => {
            if (hasFailures && data?.failed_count) return refreshItems();
          })
          .catch(showApiError);
      } else {
        void Promise.all([refreshJob(), refreshItems()]).catch(showApiError);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [metadata, state, hasFailures, refreshJob, refreshItems]);
  const handleRetry = async (
    refreshSource = false,
    source: typeof jobData = jobData,
  ) => {
    if (!source?.retryable || busy) return;
    const request =
      retry?.revision === source.revision &&
      retry.refreshSource === refreshSource
        ? retry
        : {
            revision: source.revision,
            key: createOperationId(),
            refreshSource,
          };
    setRetry(request);
    setBusy(true);
    try {
      await actions.retryJob(jobId, {
        expected_job_revision: request.revision,
        idempotency_key: request.key,
        ...(refreshSource ? { refresh_source: true } : {}),
      }, kind);
      if (metadata) {
        setPage(1);
      } else {
        await job.refetch();
        await items.refetch();
      }
    } catch (error) {
      showApiError(error);
    } finally {
      setBusy(false);
    }
  };
  const status = state && t(`f118.processing_state_${state}`);
  const counts =
    jobData &&
    t("f118.processing_counts", {
      completed: jobData.succeeded_count,
      failed: jobData.failed_count,
      pending: jobData.pending_count,
    });
  let percent: number | undefined;
  if (state === "succeeded") {
    percent = 100;
  } else if (jobData?.total_count) {
    const processed = jobData.succeeded_count + jobData.failed_count;
    percent = Math.min(
      100,
      Math.floor((processed / jobData.total_count) * 100),
    );
  }
  const showItems = !metadata || hasFailures;
  const itemRows = items.data?.data ?? [];
  const itemTotal = items.data?.total;
  useEffect(() => {
    if (history && itemTotal !== undefined) {
      const lastPage = Math.max(1, Math.ceil(itemTotal / 20));
      if (page > lastPage) setPage(lastPage);
    }
  }, [history, itemTotal, page]);
  const failureKey =
    jobData && processingFailureKey(jobData, kind ?? jobData.kind);
  return (
    <section className={fill ? "flex min-h-0 flex-1 flex-col gap-3 [&>p]:shrink-0 [&>button]:shrink-0 [&>button]:self-start" : "space-y-3"} aria-live="polite">
      {onBack && (
        <header className="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1">
          <Tooltip content={t("detail.back_to_jobs")}>
            <Button
              type="button"
              variant="text"
              color="default"
              size="small"
              iconOnly
              aria-label={t("detail.back_to_jobs")}
              onClick={onBack}
            >
              <Outlined.ArrowLeft aria-hidden />
            </Button>
          </Tooltip>
          <h3 className="text-body font-medium text-text-1">{t("f118.processing_items")}</h3>
          {counts && <p className="text-caption text-text-3">{counts}</p>}
        </header>
      )}
      {metadata && (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <span>
              {status ?? (progressReadFailed ? t("detail.load_failed") : <LoadingState size="inline" label={t("detail.loading")} />)}
            </span>
            {percent !== undefined && (
              <span className="tabular-nums">{percent}%</span>
            )}
          </div>
          <Progress
            aria-label={t("f118.processing_kind_metadata_schema_change")}
            aria-valuetext={counts}
            className="h-2"
            value={percent}
            error={state === "failed" || state === "partial_failed"}
          />
        </div>
      )}
      {!metadata && job.isInitialLoading ? (
        <SpaceProcessingLoading className={fill ? "min-h-0 flex-1" : undefined} />
      ) : !jobData ? (
        progressReadFailed ? (
          <>
            {!metadata && <p role="alert">{t("detail.load_failed")}</p>}
            <Button onClick={() => void job.refetch()}>{t("retry")}</Button>
          </>
        ) : (
          !metadata && <LoadingState label={t("detail.loading")} />
        )
      ) : (
        <>
          {!metadata && !onBack && (
            <>
              <p>{status}</p>
              <p>{counts}</p>
            </>
          )}
          {failureKey && !onBack && <p role="alert">{t(failureKey)}</p>}
          {showItems && jobData.hidden_item_count > 0 && (
            <p>
              {t("f118.processing_hidden", {
                count: jobData.hidden_item_count,
              })}
            </p>
          )}
          {jobData.retryable && (
            <Button disabled={busy} onClick={() => void handleRetry()}>
              {t("retry")}
            </Button>
          )}
          {jobData.retryable && kind === "space_copy" && (
            <Button
              variant="outlined"
              disabled={busy}
              onClick={() =>
                bsConfirm({
                  title: t("f118.copy_refresh_source"),
                  desc: t("f118.copy_refresh_source_notice"),
                  onOk: async (next) => {
                    try {
                      const latest = (await job.refetch()).data;
                      await handleRetry(true, latest);
                    } catch (error) {
                      showApiError(error);
                    } finally {
                      next();
                    }
                  },
                })
              }
            >
              {t("f118.copy_refresh_source")}
            </Button>
          )}
        </>
      )}
      {metadata && hasFailures && items.isError && (
        <Button onClick={() => void items.refetch()}>{t("retry")}</Button>
      )}
      {history && jobData && (
        <SpaceProcessingItemsTable
          items={itemRows}
          fill={fill}
          kind={kind ?? jobData.kind}
          filter={itemFilter}
          onFilterChange={(state) => {
            setPage(1);
            setItemFilter(state);
          }}
          loading={items.isInitialLoading}
          failed={items.isError}
          onRetry={() => { void items.refetch(); }}
        />
      )}
      {!history && showItems && itemRows.length > 0 && (
        <KnowledgeDialogTable
          caption={t("f118.processing_items")}
          showCaption={!onBack}
          columns={[
            { label: t("f118.processing_item") },
            { label: t("status") },
            { label: t("batch.column_reason") },
          ]}
          rows={itemRows.map((item) => ({
            key: item.id,
            cells: [
              item.file_name ??
                t("f118.processing_file_id", { id: item.file_id }),
              t(`f118.processing_item_${item.state}`),
              processingFailureKey(item, kind ?? jobData?.kind)
                ? t(processingFailureKey(item, kind ?? jobData?.kind)!)
                : "—",
            ],
          }))}
        />
      )}
      {showItems && items.data && items.data.total > 20 && (
        <Pagination
          className="shrink-0"
          current={page}
          total={items.data.total}
          pageSize={20}
          onChange={setPage}
          locale={locale}
        />
      )}
    </section>
  );
}
