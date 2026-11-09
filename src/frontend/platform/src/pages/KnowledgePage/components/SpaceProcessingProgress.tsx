import { Button, Pagination } from "@bisheng/ui";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  knowledgeSpaceApi,
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
import { showApiError } from "@/controllers/request";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";

interface SpaceProcessingProgressProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  jobId: string;
  kind?: ProcessingKind;
  onCompleted?: () => void;
}
export function SpaceProcessingProgress({
  scope,
  spaceId,
  jobId,
  kind,
  onCompleted,
}: SpaceProcessingProgressProps) {
  const { t } = useTranslation("knowledge");
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
  const job = useKnowledgeProcessingJob(scope, spaceId, jobId, api);
  const items = useKnowledgeProcessingItems(
    scope,
    spaceId,
    jobId,
    { page, page_size: 20 },
    api,
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
  const state = job.data?.state;
  const refreshJob = job.refetch,
    refreshItems = items.refetch;
  useEffect(() => {
    if (state === "succeeded" && !reported.current) {
      reported.current = true;
      completedCallback.current?.();
    }
    if (state !== "accepted" && state !== "running") return;
    const timer = window.setInterval(() => {
      void Promise.all([refreshJob(), refreshItems()]).catch(showApiError);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [state, refreshJob, refreshItems]);
  const handleRetry = async () => {
    if (!job.data?.retryable || busy) return;
    const request =
      retry?.revision === job.data.revision
        ? retry
        : { revision: job.data.revision, key: crypto.randomUUID() };
    setRetry(request);
    setBusy(true);
    try {
      await actions.retryJob(jobId, {
        expected_job_revision: request.revision,
        idempotency_key: request.key,
      });
      await job.refetch();
      await items.refetch();
    } catch (error) {
      showApiError(error);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="space-y-3" aria-live="polite">
      {!job.data ? (
        <Button onClick={() => void job.refetch()}>{t("retry")}</Button>
      ) : (
        <>
          <p>{t(`f118.processing_state_${job.data.state}`)}</p>
          <p>
            {t("f118.processing_counts", {
              completed: job.data.succeeded_count,
              failed: job.data.failed_count,
              pending: job.data.pending_count,
            })}
          </p>
          {job.data.error_code && (
            <p role="alert">{t(`api_errors:${job.data.error_code}`)}</p>
          )}
          {job.data.hidden_item_count > 0 && (
            <p>
              {t("f118.processing_hidden", {
                count: job.data.hidden_item_count,
              })}
            </p>
          )}
          {job.data.retryable && (
            <Button disabled={busy} onClick={() => void handleRetry()}>
              {t("retry")}
            </Button>
          )}
        </>
      )}
      <ul className="divide-y">
        {items.data?.data.map((item, index) => (
          <li className="py-2" key={item.id}>
            {t("f118.processing_item_number", {
              number: (page - 1) * 20 + index + 1,
            })}
            : {t(`f118.processing_item_${item.state}`)}
            {item.error_code ? ` (${t(`api_errors:${item.error_code}`)})` : ""}
          </li>
        ))}
      </ul>
      {items.data && items.data.total > 20 && (
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
