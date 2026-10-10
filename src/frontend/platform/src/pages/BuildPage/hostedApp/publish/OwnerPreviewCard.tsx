/**
 * The owner's preview of the version under review (PRD-1 RT-03 AC 11).
 *
 * Running locally does not cover every difference of the hosted environment
 * (build output, read-only file system, outbound allow-list), so while the
 * publish request is pending the owner can start a temporary instance of the
 * submitted version from here. The approval card mounts this only when the
 * server says `can.preview` and names the version under review.
 *
 * Four interface states, mirroring the approver's panel in the client:
 *
 * | state     | what the owner sees                                    |
 * |-----------|--------------------------------------------------------|
 * | absent    | "start preview" and what a preview is                  |
 * | starting  | the button busy, and that this can take a while        |
 * | running   | "open preview" + "reclaim" + when it expires           |
 * | reclaimed | why it ended, and "start again"                        |
 *
 * "Starting" is client-side only: the start call answers once the instance is
 * ready, so there is nothing to poll. The status is read on mount; the approval
 * card unmounts this while the publish status reloads, so every refetch of the
 * publish status reads the preview status again.
 *
 * The preview opens in a new tab. It runs the version at a URL of its own, and
 * replacing the detail page with it would take the owner off their app.
 */
import { Button } from "@/components/bs-ui/button"
import {
  getPreviewStatusApi,
  reclaimPreviewApi,
  startPreviewApi,
  type PreviewStatus,
} from "@/controllers/API/hostedAppPreview"
import { getHostedAppErrorMessage } from "@/controllers/API/hostedApp"
import { Eye, Loader2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

interface OwnerPreviewCardProps {
  appId: string
  /** The version under review — `approval.version_id` of the publish status. */
  versionId: string
}

type PreviewAction = "start" | "reclaim"

const KEY = "hostedApp.publishStatus"

const BLOCKED_REASON_KEY: Record<string, string> = {
  no_image: `${KEY}.previewBlockedNoImage`,
  settled: `${KEY}.previewBlockedSettled`,
}

const RECLAIM_REASON_KEY: Record<string, string> = {
  manual: `${KEY}.previewReclaimedManual`,
  approval_terminal: `${KEY}.previewReclaimedApproval`,
  expired: `${KEY}.previewReclaimedExpired`,
  start_failed: `${KEY}.previewReclaimedStartFailed`,
}

function formatExpiry(value: string | null): string {
  if (!value) return ""
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return ""
  return parsed.toLocaleString()
}

export function OwnerPreviewCard({ appId, versionId }: OwnerPreviewCardProps) {
  const { t } = useTranslation()
  const [status, setStatus] = useState<PreviewStatus | null>(null)
  const [pending, setPending] = useState<PreviewAction | null>(null)
  // A box rather than a string: an empty message is falsy and would read as
  // "nothing went wrong", which is how a refusal renders as a normal card.
  const [failure, setFailure] = useState<{ message: string } | null>(null)

  useEffect(() => {
    let cancelled = false
    setStatus(null)
    setFailure(null)
    getPreviewStatusApi(appId, versionId)
      .then((data) => {
        if (!cancelled) setStatus(data)
      })
      .catch((error: unknown) => {
        if (!cancelled) setFailure({ message: getHostedAppErrorMessage(error) })
      })
    return () => {
      cancelled = true
    }
  }, [appId, versionId])

  const run = useCallback(
    async (action: PreviewAction, request: () => Promise<PreviewStatus>) => {
      setPending(action)
      setFailure(null)
      try {
        setStatus(await request())
      } catch (error: unknown) {
        // The status stays as it was: a failed reclaim must not draw the
        // instance as gone, and a failed start must not draw one as running.
        setFailure({ message: getHostedAppErrorMessage(error) })
      } finally {
        setPending(null)
      }
    },
    [],
  )

  const handleStart = () => {
    void run("start", () => startPreviewApi(appId, versionId))
  }

  const handleReclaim = () => {
    const sessionId = status?.session_id
    if (!sessionId) return
    void run("reclaim", () => reclaimPreviewApi(appId, versionId, sessionId))
  }

  const entryUrl = status?.state === "running" ? status.entry_url : null
  const handleOpen = () => {
    if (entryUrl) window.open(entryUrl, "_blank", "noopener,noreferrer")
  }

  const blockedKey = status?.not_runnable_reason
    ? BLOCKED_REASON_KEY[status.not_runnable_reason] ?? `${KEY}.previewBlockedUnknown`
    : undefined
  const reclaimedKey =
    status?.state === "reclaimed" && status.reclaim_reason
      ? RECLAIM_REASON_KEY[status.reclaim_reason]
      : undefined
  const expiry = entryUrl ? formatExpiry(status?.expires_at ?? null) : ""
  const busy = pending !== null

  let hint: string
  if (failure) {
    hint = failure.message || t(`${KEY}.previewActionFailed`)
  } else if (pending === "start") {
    hint = t(`${KEY}.previewStarting`)
  } else if (blockedKey) {
    hint = t(blockedKey)
  } else if (entryUrl) {
    hint = expiry
      ? t(`${KEY}.previewExpiresAt`, { time: expiry })
      : t(`${KEY}.previewRunningHint`)
  } else if (reclaimedKey) {
    hint = t(reclaimedKey)
  } else {
    hint = t(`${KEY}.previewHint`)
  }

  return (
    <section
      data-testid="owner-preview-card"
      className="flex flex-col gap-2 rounded-md border border-border bg-background px-3 py-2"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Eye aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
        <h3 className="text-sm font-medium">{t(`${KEY}.previewTitle`)}</h3>
        <div className="ml-auto flex items-center gap-2">
          {entryUrl ? (
            <>
              <Button size="sm" disabled={busy} onClick={handleOpen}>
                {t(`${KEY}.previewOpen`)}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={handleReclaim}
              >
                {pending === "reclaim" && (
                  <Loader2 className="mr-1 size-3.5 animate-spin" />
                )}
                {t(`${KEY}.previewReclaim`)}
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              disabled={busy || !status || !status.runnable}
              onClick={handleStart}
            >
              {pending === "start" && (
                <Loader2 className="mr-1 size-3.5 animate-spin" />
              )}
              {t(
                status?.state === "reclaimed"
                  ? `${KEY}.previewStartAgain`
                  : `${KEY}.previewStart`,
              )}
            </Button>
          )}
        </div>
      </div>
      <p
        className={`text-xs ${failure ? "text-red-600 dark:text-red-400" : "text-muted-foreground"}`}
      >
        {hint}
      </p>
    </section>
  )
}
