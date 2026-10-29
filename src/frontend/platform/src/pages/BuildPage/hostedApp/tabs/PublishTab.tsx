/**
 * Publish tab — the shell plus what F054 itself owns (决议-6):
 * the state badge, the copyable entry link and the operational actions.
 *
 * Everything else is a **slot**. The publish pipeline, capability declaration,
 * resource tier and danger zone belong to F055; the visibility section belongs
 * to F056. They are props rather than inline sections so three features can
 * land without three edits to the same JSX block.
 *
 * Layout, top to bottom: one overview panel (state, entry, instance — the
 * three things that used to be three separate boxes saying the state three
 * times), then two columns — where the release stands (approval) beside what
 * it runs with (settings), the version record under the approval panel —
 * then the danger zone. The tab fills the content width like its sibling
 * tabs; the left column carries two panels so the columns end level.
 *
 * The displayed address, copy action, open action and QR code share the
 * browser's current origin and deployment prefix, just like the app tutorial.
 * The backend's configured address remains available to API/CLI consumers.
 * Local development forwards `/apps/` to the installed app entry via Vite.
 */
import { Button } from "@bisheng/ui"
import { notification } from "@bisheng/ui"
import type {
  HostedAppDetail,
  HostedAppInstance,
  HostedAppPendingReason,
} from "@/controllers/API/hostedApp"
import { copyText } from "@/utils"
import { Copy, ExternalLink, Loader2 } from "lucide-react"
import { QRCodeSVG } from "qrcode.react"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import {
  useHostedAppActions,
  type HostedAppActionKind,
} from "../../useHostedAppActions"
import { Field, formatTimestamp, Panel, StatusTag } from "../publish/Panel"
import {
  pendingAwareStateI18nKey,
  phaseI18nKey,
  stateBadgeClass,
} from "../types"

interface PublishTabProps {
  app: HostedAppDetail
  instance: HostedAppInstance | null
  instanceError?: string
  onChanged: () => void
  /** F055 — release / approval status; the left column. */
  pipelineSlot?: React.ReactNode
  /**
   * What the release runs with — resource tier, platform capabilities (F055)
   * and visibility scope (F056); the right column.
   */
  settingsSlot?: React.ReactNode
  /** F055 — version record, under the approval panel in the left column. */
  historySlot?: React.ReactNode
  /** F055 — danger zone (delete lives there on this page). */
  dangerZoneSlot?: React.ReactNode
  /**
   * F055 — the release read model's own verdict on "may this person retry a
   * parked release" (AC-32 / AC-62). `undefined` while that model has not
   * loaded, or could not be: the button then falls back to the state-only rule
   * below, because hiding an owner's only way forward is worse than offering a
   * button the server will refuse.
   */
  canManualPublish?: boolean
  /**
   * F055 — why the application is parked. Refines the state badge: the plain
   * `pending_capacity` label names only the capacity cause, which is the wrong
   * story for a release that built fine and then failed to start.
   */
  pendingReason?: HostedAppPendingReason | null
}

/** Container health → label; an unknown value is shown as sent. */
const HEALTH_I18N: Record<string, string> = {
  healthy: "hostedApp.publish.healthValue.healthy",
  unhealthy: "hostedApp.publish.healthValue.unhealthy",
  starting: "hostedApp.publish.healthValue.starting",
}

export function PublishTab({
  app,
  instance,
  instanceError = "",
  onChanged,
  pipelineSlot = null,
  settingsSlot = null,
  historySlot = null,
  dangerZoneSlot = null,
  canManualPublish,
  pendingReason = null,
}: PublishTabProps) {
  const { t } = useTranslation()
  const { stopApp, resumeApp, manualPublishApp } = useHostedAppActions({
    onChanged,
  })

  const appRef = { appId: app.app_id, name: app.name, state: app.state }
  const online = app.state === "online"
  const stopped = app.state === "stopped"
  const parked = app.state === "pending_capacity"
  const entryUrl = app.entry_url
    ? `${window.location.origin}${__APP_ENV__.BASE_URL}/apps/${encodeURIComponent(app.slug)}/`
    : ""

  // These calls wait on the orchestrator — taking an app offline sits through
  // `docker stop`'s 10s SIGTERM grace. Without a busy button the wait reads as
  // a dead click, and the second click loses the state race (16102).
  const [pending, setPending] = useState<HostedAppActionKind | null>(null)
  const runAction = async (
    kind: HostedAppActionKind,
    action: (ref: typeof appRef) => Promise<boolean>,
  ) => {
    if (pending) return
    setPending(kind)
    try {
      await action(appRef)
    } finally {
      setPending(null)
    }
  }

  const handleCopy = async () => {
    await copyText(entryUrl)
    notification.open({
      title: t("prompt"),
      type: "success",
      description: t("hostedApp.publish.copied"),
    })
  }

  const actionButton = (
    kind: HostedAppActionKind,
    action: (ref: typeof appRef) => Promise<boolean>,
    label: string,
  ) => (
    <Button
      variant="outline"
      size="sm"
      disabled={pending !== null}
      onClick={() => runAction(kind, action)}
    >
      {pending === kind && <Loader2 className="mr-1 size-3.5 animate-spin" />}
      {label}
    </Button>
  )

  const health = instance?.health
    ? HEALTH_I18N[instance.health]
      ? t(HEALTH_I18N[instance.health])
      : instance.health
    : "-"

  return (
    <div className="flex flex-col gap-4 pb-6 pt-1">
      <Panel
        title={t("hostedApp.publish.overviewTitle")}
        actions={
          <>
            {online && actionButton("stop", stopApp, t("hostedApp.publish.stop"))}
            {stopped &&
              actionButton("resume", resumeApp, t("hostedApp.publish.resume"))}
            {parked &&
              canManualPublish !== false &&
              actionButton(
                "manualPublish",
                manualPublishApp,
                t("hostedApp.publish.manualPublish"),
              )}
          </>
        }
      >
        <div className="flex flex-wrap items-start gap-6">
          {/*
            The QR code and the link share one visibility rule (T091): both
            are shown whenever the entry exists, and the "not running" hint
            below covers both — a scanned code lands on the same notice page
            the link does.
          */}
          {entryUrl && (
            <div
              className="flex shrink-0 flex-col items-center gap-1.5"
              data-testid="hosted-app-entry-qr"
            >
              <div className="rounded-md border bg-white p-2">
                <QRCodeSVG
                  value={entryUrl}
                  size={88}
                  aria-label={t("hostedApp.publish.qrLabel")}
                />
              </div>
              <span className="text-xs text-muted-foreground">
                {t("hostedApp.publish.qrLabel")}
              </span>
            </div>
          )}
          <div className="flex min-w-0 flex-1 flex-col gap-5">
            <div className="min-w-0">
              <p className="text-xs text-muted-foreground">
                {t("hostedApp.publish.entryLabel")}
              </p>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <code className="min-w-0 max-w-full break-all rounded bg-muted px-2 py-1 font-mono text-sm">
                  {entryUrl}
                </code>
                <Button variant="outline" size="sm" onClick={handleCopy}>
                  <Copy className="mr-1 size-3.5" />
                  {t("hostedApp.publish.copy")}
                </Button>
                <Button variant="outline" size="sm" asChild>
                  <a href={entryUrl} target="_blank" rel="noreferrer">
                    <ExternalLink className="mr-1 size-3.5" />
                    {t("hostedApp.publish.open")}
                  </a>
                </Button>
              </div>
              {!online && (
                <p className="mt-1.5 text-xs text-muted-foreground">
                  {t("hostedApp.publish.entryInactive")}
                </p>
              )}
            </div>

            <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 xl:grid-cols-5">
              <Field label={t("hostedApp.publish.stateLabel")}>
                <StatusTag className={stateBadgeClass(app.state)}>
                  {t(pendingAwareStateI18nKey(app.state, pendingReason))}
                </StatusTag>
              </Field>
              {instance ? (
                <>
                  <Field label={t("hostedApp.publish.instancePhase")}>
                    {t(phaseI18nKey(instance.phase))}
                  </Field>
                  <Field label={t("hostedApp.publish.instanceHealth")}>
                    {health}
                  </Field>
                  <Field label={t("hostedApp.publish.instanceRestart")}>
                    <span className="tabular-nums">
                      {instance.restart_count ?? 0}
                    </span>
                  </Field>
                  <Field label={t("hostedApp.publish.instanceStartedAt")}>
                    <span className="tabular-nums">
                      {formatTimestamp(instance.started_at)}
                    </span>
                  </Field>
                </>
              ) : (
                <div className="col-span-1 sm:col-span-2 xl:col-span-4">
                  <dt className="text-xs text-muted-foreground">
                    {t("hostedApp.publish.instanceTitle")}
                  </dt>
                  <dd className="mt-1 text-sm text-muted-foreground">
                    {instanceError || t("hostedApp.publish.instanceUnavailable")}
                  </dd>
                </div>
              )}
            </dl>
          </div>
        </div>
      </Panel>

      {/* The last block of each column stretches so the two columns end on
          one line; ragged bottoms were half of what made the tab look loose. */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-4 [&>*:last-child]:flex-1">
          {pipelineSlot}
          {historySlot}
        </div>
        <div className="flex min-w-0 flex-col gap-4 [&>*:last-child]:flex-1">
          {settingsSlot}
        </div>
      </div>

      {dangerZoneSlot}
    </div>
  )
}
