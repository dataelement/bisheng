import { Alert, Button, Tag, toast } from "@bisheng/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getKunlianIntegrationStatusApi,
  getKunlianIntegrationStatusSilentApi,
  triggerKunlianSyncApi,
} from "@/controllers/API/kunlianApiKeys";
import { showApiError } from "@/controllers/request";
import type { KunlianIntegrationStatus } from "@/types/api/kunlianApiKey";
import { formatIsoDateTime } from "@/util/utils";

const POLL_INTERVAL_MS = 2000;
const MAX_POLL_ATTEMPTS = 60;

type StatusTone = "default" | "brand" | "success" | "warning" | "danger";

function directoryStatusColor(status?: string): StatusTone {
  if (status === "PUBLISHED") return "success";
  if (status === "FETCHING") return "brand";
  if (status === "FAILED") return "danger";
  return "default";
}

function projectionStatusColor(status?: string): StatusTone {
  if (status === "SUCCEEDED") return "success";
  if (status === "PENDING") return "brand";
  if (status === "UNMAPPED") return "warning";
  if (status === "FAILED") return "danger";
  return "default";
}

function isSyncRunning(
  status: KunlianIntegrationStatus | null,
  targetVersion: number | null,
): boolean {
  if (status?.directory_status === "FAILED" || status?.projection_status === "FAILED") {
    return false;
  }
  if (
    targetVersion !== null &&
    (status?.sync_completed_version ?? 0) < targetVersion
  ) {
    return true;
  }
  return (
    status?.directory_status === "FETCHING" ||
    Boolean(status?.running_batch_id) ||
    (status?.projection_pending ?? 0) > 0
  );
}

function formatMetricCount(value: number | null | undefined): string {
  return typeof value === "number" ? String(value) : "-";
}

export function KunlianSyncCard() {
  const { t } = useTranslation("orgSync");
  const tRef = useRef(t);
  tRef.current = t;

  const [status, setStatus] = useState<KunlianIntegrationStatus | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [polling, setPolling] = useState(false);

  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollCountRef = useRef(0);
  const targetVersionRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current !== null) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    pollCountRef.current = 0;
    if (mountedRef.current) {
      setPolling(false);
    }
  }, []);

  const evaluatePollingProgress = useCallback(
    (latest: KunlianIntegrationStatus, notifyCompletion: boolean) => {
      const targetVersion = targetVersionRef.current;
      const hasError =
        latest.directory_status === "FAILED" ||
        latest.projection_status === "FAILED" ||
        (latest.projection_failed ?? 0) > 0;
      const versionCaughtUp =
        targetVersion === null ||
        (latest.sync_completed_version ?? 0) >= targetVersion;
      const settled =
        versionCaughtUp &&
        latest.directory_status === "PUBLISHED" &&
        (latest.projection_pending ?? 0) === 0 &&
        !latest.running_batch_id;

      if (hasError) {
        targetVersionRef.current = null;
        stopPolling();
        if (notifyCompletion) {
          toast.show({
            type: "warning",
            message: tRef.current("kunlianSync.feedback.finishedWithWarning"),
          });
        }
        return;
      }
      if (settled) {
        targetVersionRef.current = null;
        stopPolling();
        if (notifyCompletion) {
          toast.show({
            type: "success",
            message: tRef.current("kunlianSync.feedback.completed", {
              count: latest.member_count ?? 0,
            }),
          });
        }
      }
    },
    [stopPolling],
  );

  const startPolling = useCallback(
    (notifyCompletion: boolean) => {
      stopPolling();
      setPolling(true);
      pollTimerRef.current = setInterval(() => {
        pollCountRef.current += 1;
        void getKunlianIntegrationStatusSilentApi().then((latest) => {
          if (!mountedRef.current) return;
          if (latest) {
            setStatus(latest);
            evaluatePollingProgress(latest, notifyCompletion);
          }
          if (
            pollTimerRef.current !== null &&
            pollCountRef.current >= MAX_POLL_ATTEMPTS
          ) {
            targetVersionRef.current = null;
            stopPolling();
            if (notifyCompletion) {
              toast.show({
                type: "info",
                message: tRef.current("kunlianSync.feedback.pollTimeout"),
              });
            }
          }
        });
      }, POLL_INTERVAL_MS);
    },
    [evaluatePollingProgress, stopPolling],
  );

  const fetchStatus = useCallback(
    async (silent: boolean) => {
      setLoadingStatus(true);
      try {
        const next = silent
          ? await getKunlianIntegrationStatusSilentApi()
          : await getKunlianIntegrationStatusApi();
        if (!mountedRef.current || !next) return;
        setStatus(next);
        if (isSyncRunning(next, targetVersionRef.current)) {
          startPolling(targetVersionRef.current !== null);
        }
      } catch (error) {
        if (!silent) {
          showApiError(error);
        }
      } finally {
        if (mountedRef.current) {
          setLoadingStatus(false);
        }
      }
    },
    [startPolling],
  );

  useEffect(() => {
    mountedRef.current = true;
    void fetchStatus(true);
    return () => {
      mountedRef.current = false;
      if (pollTimerRef.current !== null) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [fetchStatus]);

  const handleTriggerSync = async () => {
    if (triggering || polling) return;
    setTriggering(true);
    try {
      const triggered = await triggerKunlianSyncApi();
      if (!mountedRef.current) return;
      targetVersionRef.current = triggered.requested_version;
      toast.show({
        type: triggered.dispatched === false ? "info" : "success",
        message:
          triggered.dispatched === false
            ? t("kunlianSync.feedback.queuedFallback", {
                version: triggered.requested_version,
              })
            : t("kunlianSync.feedback.triggered"),
      });
      startPolling(true);
      void getKunlianIntegrationStatusSilentApi().then((latest) => {
        if (!mountedRef.current || !latest) return;
        setStatus(latest);
        evaluatePollingProgress(latest, true);
      });
    } catch (error) {
      showApiError(error);
    } finally {
      if (mountedRef.current) {
        setTriggering(false);
      }
    }
  };

  const syncing = triggering || polling || isSyncRunning(status, targetVersionRef.current);
  const directoryLabel = status?.directory_status
    ? t(`kunlianSync.directoryStatus.${status.directory_status}`, status.directory_status)
    : "-";
  const projectionLabel = status?.projection_status
    ? t(`kunlianSync.projectionStatus.${status.projection_status}`, status.projection_status)
    : "-";
  const showFailureAlert =
    status?.directory_status === "FAILED" || status?.projection_status === "FAILED";
  const showNotReadyAlert =
    !showFailureAlert && status !== null && status.ready === false && (status.reasons?.length ?? 0) > 0;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-text-1">
              {t("kunlianSync.title")}
            </span>
            {status?.connection_id && (
              <Tag size="small" color="default">
                {t("kunlianSync.connectionLabel", { id: status.connection_id })}
              </Tag>
            )}
            <Tag size="small" dot color={directoryStatusColor(status?.directory_status)}>
              {t("kunlianSync.directoryStatusLabel")}: {directoryLabel}
            </Tag>
            <Tag size="small" dot color={projectionStatusColor(status?.projection_status)}>
              {t("kunlianSync.projectionStatusLabel")}: {projectionLabel}
            </Tag>
          </div>
          <p className="text-xs leading-relaxed text-text-3">
            {t("kunlianSync.subtitle")}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Button
            type="button"
            variant="outlined"
            color="default"
            size="small"
            disabled={loadingStatus || triggering}
            onClick={() => void fetchStatus(false)}
          >
            {t("kunlianSync.actions.refresh")}
          </Button>
          <Button
            type="button"
            color="primary"
            size="small"
            disabled={syncing}
            onClick={() => void handleTriggerSync()}
          >
            {syncing ? t("kunlianSync.actions.syncing") : t("kunlianSync.actions.syncNow")}
          </Button>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 border-t border-border pt-3 text-xs text-text-2 sm:grid-cols-3 lg:grid-cols-6">
        <div>
          <span className="block text-text-4">{t("kunlianSync.metrics.members")}</span>
          <span className="font-mono font-medium">{formatMetricCount(status?.member_count)}</span>
        </div>
        <div>
          <span className="block text-text-4">{t("kunlianSync.metrics.unmapped")}</span>
          <span className="font-mono font-medium">{formatMetricCount(status?.unmapped_count)}</span>
        </div>
        <div>
          <span className="block text-text-4">{t("kunlianSync.metrics.pending")}</span>
          <span className="font-mono font-medium">{formatMetricCount(status?.projection_pending)}</span>
        </div>
        <div>
          <span className="block text-text-4">{t("kunlianSync.metrics.failed")}</span>
          <span className="font-mono font-medium">{formatMetricCount(status?.projection_failed)}</span>
        </div>
        <div>
          <span className="block text-text-4">{t("kunlianSync.metrics.lastPublished")}</span>
          <span className="font-mono">{formatIsoDateTime(status?.last_published_at)}</span>
        </div>
        <div>
          <span className="block text-text-4">{t("kunlianSync.metrics.lastRun")}</span>
          <span className="font-mono">{formatIsoDateTime(status?.last_run_at)}</span>
        </div>
      </div>

      {showFailureAlert && (
        <div className="mt-3">
          <Alert
            type="error"
            title={t("kunlianSync.alerts.syncFailedTitle")}
            description={t("kunlianSync.alerts.syncFailed", {
              reason: status?.last_reason_code || "UNKNOWN",
            })}
          />
        </div>
      )}

      {showNotReadyAlert && (
        <div className="mt-3">
          <Alert
            type="warning"
            title={t("kunlianSync.alerts.notReadyTitle")}
            description={t("kunlianSync.alerts.notReady", {
              reasons: status?.reasons?.join(", "),
            })}
          />
        </div>
      )}
    </div>
  );
}
