import { KnowledgeDialogTable } from "@bisheng/knowledge";
import { Button, Pagination } from "@bisheng/ui";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  knowledgeSpaceApi,
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
import { Progress } from "@/components/bs-ui/progress";
import { showApiError } from "@/controllers/request";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { createDshOperationId as createOperationId } from "@/util/dshOperationId";

interface SpaceProcessingProgressProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  jobId: string;
  kind?: ProcessingKind;
  onCompleted?: () => void;
  onStateChange?: (state: JobState) => void;
}
export function SpaceProcessingProgress({
  scope,
  spaceId,
  jobId,
  kind,
  onCompleted,
  onStateChange,
}: SpaceProcessingProgressProps) {
  const { t } = useTranslation("knowledge");
  const metadata = kind === "metadata_schema_change";
  const [page, setPage] = useState(1),
    [busy, setBusy] = useState(false);
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
  const queryOptions = metadata ? { refetchOnMount: "always" as const } : undefined;
  const job = useKnowledgeProcessingJob(scope, spaceId, jobId, api, queryOptions);
  const jobData = !metadata || job.isFetchedAfterMount ? job.data : undefined;
  const hasFailures = (jobData?.failed_count ?? 0) > 0;
  const items = useKnowledgeProcessingItems(
    scope,
    spaceId,
    jobId,
    { page, page_size: 20, state: metadata ? "failed" : undefined },
    api,
    { enabled: !metadata || hasFailures, ...queryOptions },
  );
  const actions = useKnowledgeProcessingActions(scope, spaceId, api);
  const [retry, setRetry] = useState<{ revision: number; key: string } | null>(
    null,
  );
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
  const handleRetry = async () => {
    if (!jobData?.retryable || busy) return;
    const request =
      retry?.revision === jobData.revision
        ? retry
        : { revision: jobData.revision, key: createOperationId() };
    setRetry(request);
    setBusy(true);
    try {
      await actions.retryJob(jobId, {
        expected_job_revision: request.revision,
        idempotency_key: request.key,
      });
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
  const counts = jobData && t("f118.processing_counts", {
    completed: jobData.succeeded_count,
    failed: jobData.failed_count,
    pending: jobData.pending_count,
  });
  let percent: number | undefined;
  if (state === "succeeded") {
    percent = 100;
  } else if (jobData?.total_count) {
    const processed = jobData.succeeded_count + jobData.failed_count;
    percent = Math.min(100, Math.floor((processed / jobData.total_count) * 100));
  }
  const showItems = !metadata || hasFailures;
  const itemRows = items.data?.data ?? [];
  return (
    <section className="space-y-3" aria-live="polite">
      {metadata && (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <span>{status ?? t(job.isError ? "detail.load_failed" : "detail.loading")}</span>
            {percent !== undefined && <span className="tabular-nums">{percent}%</span>}
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
      {!jobData ? (
        (!metadata || job.isError) && (
          <Button onClick={() => void job.refetch()}>{t("retry")}</Button>
        )
      ) : (
        <>
          {!metadata && (
            <>
              <p>{status}</p>
              <p>{counts}</p>
            </>
          )}
          {jobData.error_code && (
            <p role="alert">{t(`api_errors:${jobData.error_code}`)}</p>
          )}
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
        </>
      )}
      {metadata && hasFailures && items.isError && (
        <Button onClick={() => void items.refetch()}>{t("retry")}</Button>
      )}
      {showItems && itemRows.length > 0 && (
        <KnowledgeDialogTable
          caption={t("f118.processing_items")}
          columns={[
            { label: t("f118.processing_item") },
            { label: t("status") },
            { label: t("batch.column_reason") },
          ]}
          rows={itemRows.map((item, index) => ({
            key: item.id,
            cells: [
              t("f118.processing_item_number", { number: (page - 1) * 20 + index + 1 }),
              t(`f118.processing_item_${item.state}`),
              item.error_code ? t(`api_errors:${item.error_code}`) : "—",
            ],
          }))}
        />
      )}
      {showItems && items.data && items.data.total > 20 && (
        <Pagination
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
