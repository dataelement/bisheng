import { LoadingState } from "@/components/bs-icons/loading/LoadingState";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { KnowledgeDialogTable } from "@bisheng/knowledge";
import {
  Button,
  Pagination,
  StateView,
  SystemErrorIllustration,
  Tooltip,
} from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { SpaceCopyTask } from "@/controllers/API/knowledgeCopy";
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
  knowledgeQueryKeys,
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
  showCopyFailurePage?: boolean;
  copyDisclosure?: {
    open: boolean;
    phase: SpaceCopyTask["phase"];
    render: (retryAction: ReactNode, details: ReactNode, preparing: boolean) => ReactNode;
  };
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
  showCopyFailurePage = false,
  copyDisclosure,
}: SpaceProcessingProgressProps) {
  const { t } = useTranslation("knowledge");
  const queryClient = useQueryClient();
  const metadata = kind === "metadata_schema_change";
  const [page, setPage] = useState(1),
    [busy, setBusy] = useState(false);
  const [itemFilter, setItemFilter] = useState<ItemState>();
  const compactCopy = Boolean(copyDisclosure);
  const detailsOpen = copyDisclosure?.open ?? true;
  const watchJob =
    detailsOpen || copyDisclosure?.phase === "failed" || copyDisclosure?.phase === "copying";
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
    watchJob ? queryOptions : { enabled: false },
  );
  const jobData = !metadata || job.isFetchedAfterMount ? job.data : undefined;
  const progressReadFailed = job.isError && !job.isFetching;
  const state = jobData?.state;
  const preparingCopy = compactCopy && (
    busy || state === "accepted" || copyDisclosure?.phase === "preparing"
  );
  const showDetails = detailsOpen && !preparingCopy;
  const failedJob =
    state === "failed" || state === "partial_failed" || state === "obsolete";
  const copyFailurePage = showCopyFailurePage && (state === undefined || failedJob);
  const copyFailurePanel = copyDisclosure?.phase === "failed" && failedJob;
  const copyJobOutOfSync =
    compactCopy && Boolean(jobData) && (copyDisclosure?.phase === "failed") !== failedJob;
  const canReadItems = showDetails && !copyJobOutOfSync;
  const hasFailures = (jobData?.failed_count ?? 0) > 0;
  const failedItemsOnly = metadata || copyFailurePanel;
  const items = useKnowledgeProcessingItems(
    scope,
    spaceId,
    jobId,
    { page, page_size: 20, state: failedItemsOnly ? "failed" : itemFilter },
    api,
    {
      enabled: canReadItems && (!metadata || hasFailures) && (!compactCopy || Boolean(jobData)),
      ...queryOptions,
    },
  );
  useEffect(() => {
    if (preparingCopy) {
      void queryClient.resetQueries({
        queryKey: knowledgeQueryKeys.jobItems(scope, spaceId, jobId),
      });
    }
  }, [preparingCopy, queryClient, scope, spaceId, jobId]);
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
    if (!watchJob || (state !== "accepted" && state !== "running")) return;
    const timer = window.setInterval(() => {
      if (!canReadItems) {
        void refreshJob().catch(showApiError);
      } else if (metadata) {
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
  }, [watchJob, canReadItems, metadata, state, hasFailures, refreshJob, refreshItems]);
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
      if (metadata || compactCopy) setPage(1);
      if (!metadata) {
        await job.refetch();
        if (!compactCopy) await items.refetch();
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
    if ((history || compactCopy) && itemTotal !== undefined) {
      const lastPage = Math.max(1, Math.ceil(itemTotal / 20));
      if (page > lastPage) setPage(lastPage);
    }
  }, [history, compactCopy, itemTotal, page]);
  const failureKey =
    jobData && processingFailureKey(jobData, kind ?? jobData.kind);
  const hiddenItems =
    showItems && jobData && jobData.hidden_item_count > 0
      ? t("f118.processing_hidden", { count: jobData.hidden_item_count })
      : undefined;
  const retryAction = jobData?.retryable && (
    <Button disabled={busy} onClick={() => void handleRetry()}>
      {t("retry")}
    </Button>
  );
  const handleRefreshSource = () => {
    if (copyFailurePanel) {
      void handleRetry(true);
      return;
    }
    bsConfirm({
      title: t("f118.copy_refresh_source"),
      desc: t("f118.copy_refresh_source_notice"),
      onOk: async (close) => {
        try {
          const latest = (await job.refetch()).data;
          await handleRetry(true, latest);
        } catch (error) {
          showApiError(error);
        } finally {
          close();
        }
      },
    });
  };
  const refreshSourceAction = jobData?.retryable && kind === "space_copy" && (
    <Button
      variant="outlined"
      size={copyFailurePanel ? "small" : "medium"}
      color={copyFailurePage || copyFailurePanel ? "default" : "primary"}
      disabled={busy}
      onClick={handleRefreshSource}
    >
      {t(copyFailurePanel ? "retry" : "f118.copy_refresh_source")}
    </Button>
  );
  const retryReadAction = (
    <Button onClick={() => void job.refetch()}>{t("retry")}</Button>
  );
  const copyItemsCaption = t(
    copyFailurePanel ? "space_copy_ui.failure_details" : "f118.processing_items",
  );
  const layout = copyFailurePage
    ? "flex flex-1 flex-col gap-4"
    : fill
      ? "flex min-h-0 flex-1 flex-col gap-3 overflow-hidden [&>p]:shrink-0 [&>button]:shrink-0 [&>button]:self-start"
      : "space-y-3";
  const content = showDetails ? (
    <section className={layout} aria-live="polite">
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
      {copyFailurePage ? (
        <StateView
          className="h-auto flex-1 py-8"
          image={<SystemErrorIllustration />}
          title={
            state === "obsolete" || state === "partial_failed"
              ? status
              : t("space_copy_ui.failed")
          }
          description={
            jobData ? (
              <>
                <span className="block text-text-2">{counts}</span>
                {(failureKey || hiddenItems) && (
                  <span className="mt-4 block space-y-2 rounded-lg border border-border-base px-4 py-3 text-left text-body-sm text-text-2">
                    {failureKey && (
                      <span role="alert" className="block">{t(failureKey)}</span>
                    )}
                    {hiddenItems && <span className="block">{hiddenItems}</span>}
                    {failureKey && (
                      <span className="block break-all text-caption text-text-2">
                        {t("f118.processing_task_id", { id: jobData.id })}
                      </span>
                    )}
                  </span>
                )}
              </>
            ) : (
              t(progressReadFailed ? "detail.load_failed" : "detail.loading")
            )
          }
          action={
            retryAction ? (
              <>
                {refreshSourceAction}
                {retryAction}
              </>
            ) : progressReadFailed ? (
              retryReadAction
            ) : undefined
          }
        />
      ) : !metadata && job.isInitialLoading ? (
        <SpaceProcessingLoading className={fill ? "min-h-0 flex-1" : undefined} />
      ) : !jobData || copyJobOutOfSync ? (
        progressReadFailed ? (
          <>
            {!metadata && <p role="alert">{t("detail.load_failed")}</p>}
            {retryReadAction}
          </>
        ) : (
          !metadata && <LoadingState label={t("detail.loading")} />
        )
      ) : !copyFailurePanel && (
        <>
          {!metadata && !onBack && !compactCopy && (
            <>
              <p>{status}</p>
              <p>{counts}</p>
            </>
          )}
          {failureKey && !onBack && <p role="alert">{t(failureKey)}</p>}
          {hiddenItems && <p>{hiddenItems}</p>}
          {retryAction}
          {refreshSourceAction}
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
      {compactCopy && jobData && !copyJobOutOfSync && (
        <div className="space-y-2">
          <h3 className="text-body font-medium text-text-1">{copyItemsCaption}</h3>
          {copyFailurePanel && failureKey && (
            <>
              <p className="text-body-sm text-text-2" role="alert">{t(failureKey)}</p>
              <p className="break-all text-caption text-text-2">
                {t("f118.processing_task_id", { id: jobData.id })}
              </p>
            </>
          )}
          {copyFailurePanel && hiddenItems && (
            <p className="text-body-sm text-text-2">{hiddenItems}</p>
          )}
          <div className="-mx-3">
            <SpaceProcessingItemsTable
              caption={copyItemsCaption}
              emptyMessage={copyFailurePanel ? t("space_copy_ui.no_failure_details") : undefined}
              items={itemRows}
              kind={kind}
              showReasons
              loading={items.isInitialLoading}
              failed={items.isError}
              onRetry={() => { void items.refetch(); }}
            />
          </div>
        </div>
      )}
      {!history && !compactCopy && showItems && itemRows.length > 0 && (
        <KnowledgeDialogTable
          caption={t("f118.processing_items")}
          scrollable={fill}
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
      {canReadItems && showItems && items.data && items.data.total > 20 && (
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
  ) : null;
  return copyDisclosure
    ? copyDisclosure.render(
        copyFailurePanel && !preparingCopy ? refreshSourceAction : null,
        content,
        preparingCopy,
      )
    : content;
}
