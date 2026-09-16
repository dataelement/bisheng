import { Button } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useCallback, useEffect, useState } from "react";
import {
  getPreviewStatusApi,
  reclaimPreviewApi,
  startPreviewApi,
  type PreviewStatus,
} from "~/api/hostedAppPreview";
import { extractApiErrorMessage } from "~/utils/apiStatusError";
import type { LocalizeFn } from "./approvalPresentation";

/**
 * 「预览试用」 — pinned to the top of the review view (F055 AC-26 … AC-28).
 *
 * Reading the code tells an approver what a release claims to do; running it
 * tells them whether it does. So this sits above the tabs rather than inside
 * one: it is the first thing offered, not a fifth thing to find.
 *
 * **Four interface states**, and each says a different thing:
 *
 * | state | what the approver sees |
 * |---|---|
 * | 未拉起 | one button and what a trial is |
 * | 拉起中 | the button in its loading state — this can take a minute |
 * | 可用 | 「打开预览」 + 「回收」 + when it expires |
 * | 已回收 | why it ended, and that a new one can be raised |
 *
 * 「拉起中」 is the client's own state, not the platform's: the start call
 * answers only once the instance has passed its readiness gate, so there is no
 * half-started status to poll for — and polling one would be inventing a state
 * the backend deliberately does not have.
 *
 * The preview opens in a **new tab**. It runs the version under review at a URL
 * of its own, and replacing the approval panel with it would leave the approver
 * navigating back out of somebody else's application to record a decision.
 */

export interface AppPreviewPanelProps {
  appId: string;
  versionId: string;
  localize: LocalizeFn;
}

const BLOCKED_REASON_KEY: Record<string, string> = {
  no_image: "com_approval_preview_blocked_no_image",
  settled: "com_approval_preview_blocked_settled",
};

const RECLAIM_REASON_KEY: Record<string, string> = {
  manual: "com_approval_preview_reclaimed_manual",
  approval_terminal: "com_approval_preview_reclaimed_approval",
  expired: "com_approval_preview_reclaimed_expired",
};

function formatExpiry(value: string | null): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleString();
}

export function AppPreviewPanel({ appId, versionId, localize }: AppPreviewPanelProps) {
  const [status, setStatus] = useState<PreviewStatus | null>(null);
  const [busy, setBusy] = useState(false);
  // A box rather than a string: an empty message is falsy and would fall back
  // to "nothing went wrong", which is how a refusal renders as a normal panel.
  const [failure, setFailure] = useState<{ message: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setStatus(null);
    setFailure(null);
    getPreviewStatusApi(appId, versionId)
      .then((data) => {
        if (!cancelled) setStatus(data);
      })
      .catch((error: unknown) => {
        if (!cancelled) setFailure({ message: extractApiErrorMessage(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [appId, versionId]);

  const run = useCallback(
    async (action: () => Promise<PreviewStatus>) => {
      setBusy(true);
      setFailure(null);
      try {
        setStatus(await action());
      } catch (error: unknown) {
        // The status is left as it was: a failed reclaim must not draw the
        // instance as gone, and a failed start must not draw one as running.
        setFailure({ message: extractApiErrorMessage(error) });
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const handleStart = () => run(() => startPreviewApi(appId, versionId));
  const handleReclaim = () => {
    const sessionId = status?.session_id;
    if (!sessionId) return;
    return run(() => reclaimPreviewApi(appId, versionId, sessionId));
  };

  const blockedKey = status?.not_runnable_reason
    ? BLOCKED_REASON_KEY[status.not_runnable_reason]
    : undefined;
  const reclaimedKey = status?.reclaim_reason ? RECLAIM_REASON_KEY[status.reclaim_reason] : undefined;
  const running = status?.state === "running" && !!status.entry_url;
  const expiry = running ? formatExpiry(status.expires_at) : "";

  return (
    <section
      data-testid="app-preview-panel"
      className="rounded-lg border border-fill-2 bg-fill-1 px-4 py-3"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Outlined.Eye className="size-4 shrink-0 text-text-3" />
        <span className="text-[14px] font-medium text-text-primary">
          {localize("com_approval_preview_title")}
        </span>

        <div className="ml-auto flex items-center gap-2">
          {running ? (
            <>
              <Button
                color="primary"
                variant="solid"
                size="small"
                onClick={() => window.open(status.entry_url as string, "_blank", "noopener,noreferrer")}
              >
                <Outlined.ViewOnNewTab className="size-3.5" />
                {localize("com_approval_preview_open")}
              </Button>
              <Button
                color="default"
                variant="outlined"
                size="small"
                loading={busy}
                onClick={handleReclaim}
              >
                {localize("com_approval_preview_reclaim")}
              </Button>
            </>
          ) : (
            <Button
              color="primary"
              variant="solid"
              size="small"
              loading={busy}
              disabled={!status || status.runnable === false}
              onClick={handleStart}
            >
              {localize(
                status?.state === "reclaimed"
                  ? "com_approval_preview_start_again"
                  : "com_approval_preview_start",
              )}
            </Button>
          )}
        </div>
      </div>

      <p className="mt-1.5 text-[12px] text-text-3">
        {failure ? (
          <span className="text-danger">
            {failure.message || localize("com_approval_preview_action_failed")}
          </span>
        ) : blockedKey ? (
          localize(blockedKey)
        ) : running ? (
          expiry
            ? localize("com_approval_preview_expires_at", { time: expiry })
            : localize("com_approval_preview_running_hint")
        ) : reclaimedKey ? (
          localize(reclaimedKey)
        ) : (
          localize("com_approval_preview_hint")
        )}
      </p>
    </section>
  );
}
